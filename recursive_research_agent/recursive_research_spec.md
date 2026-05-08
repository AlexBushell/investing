# Recursive Adversarial Research System — Design Specification

## 1. Purpose

A self-directed investigation system that, given a company name, produces an exhaustive research dossier by recursively prosecuting every material thread it encounters. The system produces no investment recommendations, ratings, or conclusions about whether the business is a good or bad investment. It surfaces findings, flags gaps, records what is contested or unresolvable, and stops only when nothing material remains to investigate. Output feeds a downstream digestion process and is expected to be larger and more comprehensive than any human analyst could reasonably produce.

The defining stance is **investigator, not analyst**: a junior researcher who cannot stop pulling on threads, who never tires, and whose only job is to find things and write them down with their provenance intact.

The system treats uncertainty, contradiction, rediscovery, and unresolvedness as first-class outputs rather than failure modes. A thread that the model can confidently classify as unresolvable is a useful output; a contradiction between sources is a useful output; the same concern surfacing independently across multiple branches is a useful output. The dossier reflects what is known, what is contested, what is unresolved, and what is unanswerable.

Several v1 design choices — findings persistence across runs, refresh mode (§8), persistent uncertainties (§6.7), reference counts (§2.5) — are heavier than a one-shot dossier generator would require. This is deliberate. The system's persistent state is intended to accumulate across runs and across companies over time, and the v1 structures are sized to support that trajectory. This document specifies v1; the trajectory is acknowledged where load-bearing, not promised as deliverables.

A note on judgement: the system makes operational judgements continuously — what is material, what is high-priority, what is duplicative, what counts as a contradiction, what to retrieve. These judgements are unavoidable and explicit. The constraint the system honors is narrower: the *output artifact* is descriptive, not prescriptive. It does not tell a reader what to do with what it found.

## 1.1 Architectural framing

The system maintains four logical views of its work:

- **Execution topology**: the orchestration tree that schedules investigations.
- **Findings graph**: semantic relationships across all findings stored across runs.
- **Render hierarchy**: the dossier's heading structure.
- **Uncertainty graph**: persistent open questions and their relationships across runs.

In v1 these largely share substrate. The execution tree is also the render hierarchy. The findings graph is implicit in the findings store's indexes. The uncertainty graph is flat. Future versions are likely to separate them as the system's persistent memory matures — most obviously, the render hierarchy diverging from the execution topology when cross-cutting themes need their own thematic sections rather than appearing piecewise across multiple branches.

This separation is named here so that v1 design choices that prematurely fuse these views can be recognized and revisited. When something feels off in a future revision, the test is: which of these four graphs does the concern belong to, and is v1's shared substrate forcing it into the wrong shape?

## 2. Core Mechanism

The system is a tree of model-authored investigations. Each node represents one **thread** — anything a careful reviewer would want to understand more deeply before forming a judgement of the business. Threads include adversarial concerns, verification questions, neutral facts whose implications are not yet clear, and open questions whose answer would change a reviewer's understanding regardless of which way it lands. The framing is deliberately broader than "weakness" — defects and risks are a subset of threads, not the whole.

Investigation of a node produces an analysis; review of that analysis produces zero or more child threads, each accompanied by a model-written brief specifying what the next investigation should look like. The recursion continues along each branch until review surfaces nothing new, material, and unresolved.

### 2.1 Node lifecycle

A node moves through these states: `pending` → `investigating` → `reflecting` → `awaiting_children` → `synthesizing` → `complete`. A node may also enter `failed` and be retried. Persistence captures the state at each transition so that a crashed run resumes from the frontier rather than restarting.

A separate state — `reference` — is described in §2.5 and short-circuits the lifecycle for topical duplicates. A `rejected` state is described in §2.7 for threads that fail circularity arbitration.

### 2.2 Call types

Five primary model call types, plus circularity arbitration. Each has its own system prompt and context envelope. Calls are stateless: each is constructed fresh from the tree and carries no conversation history. All call types that produce parseable output use enforced JSON schemas (see §2.8).

- **Scope**: given a company name, produce the initial set of root-level investigation briefs tailored to this specific company.
- **Deep-dive**: given an investigation brief, path-to-root context, and any retrieved prior findings, conduct a thorough investigation using web search. Produces a structured response containing a long-form `analysis`, a one-paragraph `abstract`, a list of flagged `contradictions` with retrieved priors, and a list of `discovered_threads` — threads encountered during the investigation that warrant their own future prosecution (see §2.6).
- **Reflect**: given an analysis, identify every thread a reviewer would want pulled. Produce zero or more child thread candidates, each with topic, description, materiality decision, priority, resolution state, evidence basis, optional triggering text span, optional why-unresolved note, and a self-contained investigation brief.
- **Branch-synthesize**: given a node's analysis and the summaries of its completed children, write a short oriented summary covering: what was resolved, what remains open, what contradictions surfaced, and confidence in the branch's overall picture. Internal nodes only; leaves do not run this call. Returns prose, not JSON.
- **Extract findings**: given a deep-dive analysis, extract atomic findings as structured records for the searchable store (see §6).
- **Circularity arbitration**: runs only when the dedup check finds an ancestor match. See §2.7.

### 2.3 Reflect output: materiality, priority, resolution, evidence

Reflect produces four judgements per child candidate, recorded as separate fields. The original 1–5 score conflated them; separating prevents the conflation.

- `material: bool` — is this thread material to the quality or execution of *this specific business*? This is a recursion gate.
- `priority: 1 | 2 | 3` — among material threads, urgency relative to peers. Queue-ordering signal only.
- `resolution_state: unresolved_investigable | unresolved_unanswerable | resolved_within_analysis` — is there a meaningful unresolved investigative path left? This is the second recursion gate.
- `evidence_basis: direct | inferred | speculative` — is this thread anchored in the analysis text, or generated from adversarial imagination?

Recursion gates: only threads with `material: true` AND `resolution_state == unresolved_investigable` become nodes. The other resolution states have specific behaviors:

- `unresolved_unanswerable` — recorded as a persistent uncertainty (§6.7) rather than spawning a node. Examples: private company financials, undisclosed strategic plans, unverifiable management claims with no surviving primary sources.
- `resolved_within_analysis` — dropped. The analysis already addressed it.

Evidence basis interacts with priority: `speculative` threads are demoted one priority level (priority 1 → 2, priority 2 → 3) before queueing, on the principle that adversarial imagination earns coverage but not urgency. This preserves coverage of plausible-but-weakly-evidenced concerns without letting reflect's hostile framings drown the queue in hypothetical concerns.

The optional `triggering_text_span` (the passage of analysis that prompted the thread) and `why_unresolved` (a short explanation of why this remains an open question) are encouraged but not enforced. The audit view (§9.2) renders them where present, making it directly inspectable whether reflect is reading the analysis or fabricating concerns.

**The materiality test is about the business, not the thread in absolute terms.** A thread is material if and only if its resolution would change a reviewer's understanding of how this specific business operates, performs, or sustains itself. Threads that are significant in absolute terms but have no meaningful exposure to the company under investigation are immaterial. Threads that are minor in absolute terms but materially affect this company's operations or sustainability are material. The reflect prompt must enforce this framing explicitly, otherwise the model's instinct is to surface things that are dramatic in the abstract — large numbers, scary possibilities — without checking whether they meaningfully affect the company at hand.

The original prompt habit of forcing scores to decline with depth is removed. Third-order threads are sometimes the load-bearing ones; let the model judge each on its own merits.

### 2.4 The abstract — and why

Branch synthesis is written *after* a node's children complete. At the moment a child's deep-dive runs, no ancestor has a branch synthesis yet — the artifact does not exist at the time of the call. To give descendants stable, self-contained context about their ancestors, every deep-dive emits a one-paragraph `abstract` alongside the long-form analysis. The abstract is generated immediately and never updated, so it is always available when descendants need it.

The abstract is constrained by prompt to be self-contained: it must name the company, name the brief it is summarizing, state the load-bearing finding, and avoid referential phrases like "as discussed above." Same self-containment discipline applied to investigation briefs (§4), applied here.

The abstract also serves as the upward summary for leaves. When a parent's branch-synthesize call receives summaries from completed children, internal-node children pass up their `branch_synthesis`; leaf children pass up their `abstract`. The parent does not need to distinguish the two cases.

### 2.5 Reference nodes (within-run topical dedup)

Independent branches will sometimes surface the same topical thread. Without dedup, two parallel subtrees prosecute the same investigation, generating duplicate work and a doubled section in the rendered dossier.

Before transitioning a `pending` node to `investigating`, the orchestrator embeds the concatenation of its `topic` and `investigation_brief` and runs a similarity check against all other non-ancestor nodes in the run (both pending and complete). If similarity exceeds a configurable threshold against an existing non-ancestor node, the new node is marked a *reference* to that canonical node rather than running a fresh investigation.

Schema: nodes carry a nullable `canonical_node_id`. When null, the node is canonical and behaves normally. When set, the node is a reference: it inherits the canonical's analysis, abstract, and children by reference, runs no calls of its own, and is marked `complete` immediately.

When a reference's parent later runs branch-synthesize, the reference is treated identically to a canonical child — it contributes the canonical's summary to the synthesis input. Both branches' syntheses therefore incorporate the same findings.

**Convergent rediscovery as signal.** Canonical nodes accumulate two fields: `reference_count` (number of references pointing at them) and `reference_origins` (the brief texts of the references). The dossier renders this above the canonical's analysis: *"This concern was independently surfaced by N investigations: [list of origin briefs]."* Independent rediscovery of the same thread across decorrelated branches is evidence of structural centrality and the dossier should make it visible. The original spec silently merged this signal away.

The similarity threshold matters and is empirical. Too loose merges genuinely distinct investigations ("EU regulatory exposure in payments" vs. "in data privacy"); too tight and true duplicates slip through. Default tight; loosen on observation. The brief-tree audit view (§9.2) is the natural surface for spot-checking dedup decisions.

### 2.6 Threads discovered mid-investigation

A deep-dive may surface threads that are not gaps in the current investigation but rather entirely separate questions encountered along the way. A regulatory deep-dive that incidentally notices a major customer concentration issue should not pause to investigate the customer concentration — it should finish the regulatory work and leave a note for future prosecution.

Deep-dive's structured output includes a `discovered_threads` array with the same schema as reflect's child candidates: topic, description, material, priority, resolution_state, evidence_basis, investigation_brief. These threads are enqueued via the same pipeline as reflect's output, subject to the same dedup check (§2.5) and circularity arbitration (§2.7), and treated identically in scheduling. The parent of a discovered thread is the same as the parent of the deep-dive that surfaced it (i.e. they become siblings of the discovering node, not children) — they are independent investigations, not sub-aspects of the discovering node.

This separates two genuinely different model behaviors: reflect *attacks the analysis just produced*; deep-dive *notices side-threads while doing its primary work*. Conflating them in the original spec was an oversight.

The number of searches per deep-dive remains a soft target controlled by `searches_per_deepdive_target`. The instruction to the model is that searches are for completing the current investigation; threads encountered along the way go in `discovered_threads` rather than triggering more searches within the current call.

### 2.7 Circular research and ancestor arbitration

The §2.5 dedup check excludes ancestors of the candidate node. Ancestor matches are handled separately because the embedding similarity alone cannot distinguish two distinct cases:

- **Legitimate narrowing**: a thread at depth 4 is a genuine sub-aspect of an ancestor at depth 1.
- **Circularity**: the model has lost track of where it is in the tree and spawned a thread that's effectively the same question as an ancestor, just rephrased.

When the dedup check finds an ancestor match, the orchestrator runs a **circularity arbitration** call: given the ancestor's brief and the candidate's brief, decide whether the candidate is a narrower sub-question of the ancestor, the same question rephrased, or genuinely distinct. Outcomes:

- **Narrower sub-question**: proceed with the candidate as a normal node.
- **Same question rephrased**: mark the candidate `rejected`, log the rejection with the ancestor it duplicated, do not enqueue.
- **Genuinely distinct**: proceed normally.

Rejected nodes appear in the run database (§5) for inspection but not in the rendered dossier (§9.1). They do appear in the brief-tree audit view (§9.2) with their rejection reason, because the audit view's job includes catching arbitration mistakes.

### 2.8 JSON schema enforcement

Every call type that returns parseable output enforces a JSON schema at the model API level — not via prompt instruction with retry-on-parse-failure. Use Ollama's `format` parameter (or `langchain_ollama`'s `with_structured_output`) bound to a Pydantic schema per call type.

Call types with enforced schemas: scope, deep-dive (envelope: `{analysis, abstract, contradictions, discovered_threads}`), reflect, extract findings, circularity arbitration. Branch-synthesize returns prose and is not JSON-enforced.

Validation failures are treated as call failures (§7.2) — retry with backoff, do not paper over with regex extraction. The original code's parse-then-retry-with-prompt pattern is fragile and leaks malformed text into context.

### 2.9 Stop conditions

A branch terminates when reflect produces no children that are both `material: true` and `resolution_state == unresolved_investigable`, AND the deep-dive surfaced no `discovered_threads` matching the same gates. A depth cap exists as a circuit breaker (default 8) but is not the primary control. Per-run safety limits — maximum total nodes and maximum wall-clock time — exist for the same reason.

## 3. Context Discipline

Every model call is constructed from scratch. There is no shared message list, no `add_messages` reducer, no conversation history propagating between calls. State lives in the tree; messages are transient I/O.

What each call type receives is defined explicitly:

- **Scope** receives only the company name and its system prompt.
- **Deep-dive** receives the company name, the path from root to this node (each ancestor as `topic` + `investigation_brief` + `abstract` — all stable at call time), the investigation brief for this node, any prior findings retrieved from the searchable store (see §6.4), any persistent uncertainties relevant to the brief (see §6.7), and the system prompt. It does not receive sibling analyses, the scope output, or the full tree.
- **Reflect** receives only the analysis being reviewed and the system prompt. No tree context — its job is to attack one piece of writing on its own merits.
- **Branch-synthesize** receives the parent's deep-dive analysis and the summary of each completed child (`branch_synthesis` for internal children, `abstract` for leaf children).
- **Extract findings** receives only the analysis to extract from.
- **Circularity arbitration** receives the ancestor's brief and the candidate's brief. Nothing else.

The temptation to "help" the model by passing more context than each call needs must be actively resisted. The tree is the orchestrator's memory; the model gets only what serves its narrow local task.

## 4. Briefs as First-Class Artifacts

Each node carries: `topic` (short label), `description` (human-readable summary for the rendered report), `material` (bool), `priority` (1–3), `resolution_state`, `evidence_basis`, optional `triggering_text_span` and `why_unresolved`, and `investigation_brief` (the self-contained prompt body that will drive the next deep-dive). The brief is authored by the call that surfaced the thread (reflect or deep-dive's `discovered_threads`).

Briefs are inspectable artifacts. The brief-tree audit view (§9.2) renders topics, briefs, all four reflect-output fields, and triggering spans where present. The audit view is the inspection surface for whether the system is investigating sharp questions.

Brief-authoring instructions explicitly state that briefs will be executed by a future model with no access to the current conversation, so briefs must be self-contained: name companies, time periods, specific data sources, and specific questions.

## 5. Persistence

A SQLite database holds the structured tree. Schema (informal):

- `runs`: `run_id`, `company`, `mode` (new/refresh/incremental — see §8), `parent_run_id` (nullable, for refresh/incremental), `started_at`, `completed_at`, `status`
- `nodes`: `node_id`, `run_id`, `parent_id`, `canonical_node_id`, `reference_count`, `topic`, `description`, `material`, `priority`, `resolution_state`, `evidence_basis`, `triggering_text_span`, `why_unresolved`, `investigation_brief`, `analysis`, `abstract`, `branch_synthesis`, `status`, `depth`, `created_at`, `updated_at`
- `node_references`: `canonical_node_id`, `reference_node_id`, `origin_brief` — supports `reference_origins` aggregation
- `node_failures`: `node_id`, `attempt`, `error`, `failed_at`
- `node_rejections`: `node_id`, `reason`, `duplicated_ancestor_id`, `rejected_at`

Every state transition is committed. On startup, any nodes left in transitional states from a prior crashed run are reset to the appropriate prior state and resumed.

## 6. Searchable Findings Store

A separate persistent store accumulates atomic findings across all runs and companies. Findings are extracted by a dedicated model call at the end of each deep-dive, not stored as raw analyses.

### 6.1 Finding schema

`finding_id`, `run_id`, `node_id`, `company`, `claim`, `claim_type`, `evidence`, `source`, `source_type`, `primary_vs_secondary`, `confidence` (low/medium/high), `decay_class` (historical/structural/current — see §6.4), `date_observed`, `date_last_verified`, `tags` (sector, theme, free-form).

`claim_type` is one of: `observed_fact | management_claim | third_party_allegation | inferred_conclusion | statistical_observation | historical_event | unresolved_contradiction`. These are epistemically different objects and should not be flattened into a single text blob. The extraction prompt is required to classify each finding, which is itself a useful forcing function — vague claims that resist classification are usually the ones not worth storing.

`source_type` is a coarse enum: `primary_filing | regulatory | reputable_journalism | industry_publication | management_communication | aggregator | social_media | unknown`. Continuous reliability scores are deliberately avoided — they invite false precision the model cannot deliver. `primary_vs_secondary` is a separate boolean because primary status is orthogonal to source type (a primary management communication and a primary regulatory filing are both primary, but not equivalent in reliability).

### 6.2 Indexes

Three coordinated indexes keyed by `finding_id`:

- **Vector index** for semantic similarity (LanceDB, embedded, no daemon).
- **FTS5 lexical index** in SQLite for exact-term queries (named entities, regulations, identifiers that embeddings handle poorly).
- **Structured filters** in SQLite for company, date range, confidence, decay class, claim type, source type, tags.

Queries combine all three: structured filter narrows the candidate set, vector similarity ranks within it, lexical search serves as both filter and fallback.

### 6.3 Embeddings

Local via Ollama (`nomic-embed-text`). The retrieval-quality gap relative to hosted embedding models is real and will manifest as occasionally-noisy retrievals at §6.4. Acceptable for a fully-local deployment.

### 6.4 Retrieval at deep-dive start

Before each deep-dive call, the system queries the findings store for prior findings semantically related to the investigation brief. Retrieved findings are passed into the deep-dive prompt as **prior leads from earlier investigations**, with their full provenance attached, with explicit instruction that they are starting points to verify, not authorities to cite.

No hard age cutoff on retrieval. Each finding is annotated with its `decay_class`, `claim_type`, `source_type`, and age in the prompt:

- **historical** — facts whose truth is fixed by a past event. Never stale; age is irrelevant.
- **structural** — facts about the business that drift over months to years. Skepticism scales with age.
- **current** — facts that change frequently. Treat as stale beyond a few months and re-verify.

The deep-dive prompt instructs the model to apply per-class skepticism rather than treating all old findings identically. A 10-year-old historical finding from a primary filing is still load-bearing context; a 6-month-old current management claim from an aggregator requires re-verification.

Default retrieval scope is `company == current_company` plus findings explicitly tagged as comparable. Cross-company retrieval (sector-wide) is opt-in via a flag for sector-level investigations.

### 6.5 Contradiction surfacing

Contradictions are detected at deep-dive time. The deep-dive prompt mandatorily instructs the model to flag contradictions with retrieved priors in the `contradictions` array (and reference them in the analysis text) — not to silently reconcile in favor of the more recent source.

Source quality affects how contradictions are characterized. The deep-dive prompt instructs the model to weight contradictions by source: a primary filing contradicting a prior management claim is a different finding than a Reddit post contradicting a primary filing. The contradiction record carries both source descriptors so reflect can prioritize accordingly.

A flagged contradiction is then picked up by the normal reflect step, which sees the contradiction in the analysis and is free to spawn a thread to prosecute the discrepancy. No special-case path. Extract-findings remains narrow and stateless.

This is initially a cross-run mechanism only: the priors are findings from earlier runs. Within-run contradictions are deferred.

### 6.6 Deduplication of findings

No deduplication at storage time. Every finding is stored with its run, node, and timestamps. Query-time logic collapses near-duplicates by vector similarity above a high threshold and surfaces the most recent. The historical record is preserved.

This is distinct from the within-run reference-node mechanism (§2.5), which dedups *investigations*. Findings dedup is across runs only and happens at retrieval time, not storage time.

### 6.7 Persistent uncertainties

Some threads are unresolvable in principle, not just unresolved by the current investigation. Without a persistence mechanism, every refresh run rediscovers them as if novel, wasting computation and producing the same dead-end branches repeatedly.

A `persistent_uncertainties` table records these:

`uncertainty_id`, `company`, `description`, `closure_class`, `first_observed_run_id`, `last_observed_run_id`, `related_finding_ids`, `related_contradiction_count`, `status` (`open` | `resolved` | `abandoned`), `created_at`, `updated_at`.

`closure_class` distinguishes three types with different future-run behaviors:

- **`unknowable`** — never re-triggers. Examples: private company financials, undisclosed strategic decisions, contested historical events with no surviving primary sources. Recorded as fixed state; refresh runs surface the uncertainty in deep-dive context but do not spawn investigation threads against it.
- **`insufficient_evidence_yet`** — periodically re-triggers. The question is answerable in principle, the data just isn't available yet. Refresh runs after a configurable interval re-spawn the investigation; new disclosures, filings, or news may have closed the gap.
- **`conflicting_evidence_persists`** — escalates with accumulated contradictions. Each new contradiction increments `related_contradiction_count`; if the count crosses a configurable threshold, the uncertainty itself becomes a high-priority thread in the next run rather than a passive record.

Persistent uncertainties are populated from two sources: reflect outputs with `resolution_state == unresolved_unanswerable`, and accumulated contradictions detected at §6.5. A model call (small, JSON-enforced) classifies new entries into a `closure_class` at creation time.

Honest caveat: the `closure_class` classification is the model's judgement, and the model may be wrong. A thread classified as `unknowable` that was actually `insufficient_evidence_yet` causes the system to silently stop investigating something it should pursue. The audit view (§9.2) renders persistent uncertainties with their classes; spot-checking on early runs is the mitigation.

Persistent uncertainties are surfaced to deep-dive calls (§3) when their description matches the investigation brief semantically, alongside retrieved findings. The deep-dive sees them as "this question has been open since [date] because [reason]" — preventing rediscovery-as-novelty.

## 7. Execution Model

### 7.1 Why serial

A single worker, serial execution. Not because concurrency is hard — though it is — but because serial execution is a deliberate architectural property that supports the system's epistemic design:

- **Reproducible topology.** A given prompt set and findings store produce a deterministic tree (modulo model nondeterminism within calls). Investigative shape is auditable.
- **Inspectable frontier evolution.** The audit view (§9.2) is meaningful because the queue evolves predictably and one transition at a time.
- **Tractable prompt iteration.** When prompts change, observed behavior changes are attributable. Concurrent execution introduces non-determinism that confounds prompt experiments.
- **Legible failure semantics.** Per-node failure with deterministic propagation through the tree is a small set of cases. Concurrent failure modes are not.
- **Reduced context contamination risk.** Serial execution makes it impossible for parallel branches to inadvertently share state through a shared resource.

The bottleneck argument — that a single model server constrains throughput regardless — is confirmatory rather than load-bearing. Even with batched inference, the architectural reasons above remain.

### 7.2 Worker, queue, and failure handling

The frontier is a priority queue of `pending` nodes, ordered by `priority` ascending (1 = highest), with parents preceding children because reflect runs only after deep-dive completes. The worker pulls one node, runs the dedup check (§2.5) and if needed circularity arbitration (§2.7), transitions the node through its lifecycle if canonical or short-circuits to reference/rejected otherwise, commits each state change, and moves on.

An optional `inter_request_delay_seconds` exists for users who want to throttle search API usage; otherwise the natural pace of model calls determines throughput.

Failures are per-node. A failed deep-dive marks the node `failed`, records the error, and either retries on a backoff schedule or skips and continues, depending on configuration. JSON validation failures (§2.8) are call failures and follow the same path. The unit of retry is the node; the orchestrator never retries an entire run. Transient infrastructure problems — search API rate limits, model server restarts, network glitches — degrade run speed but do not terminate runs.

A permanently failed node terminates its own branch: no reflect runs, no children spawn, no further descent through it. It does not block siblings. Branch-synthesize at the parent runs over the surviving children's summaries with the failed node noted explicitly in the synthesis input as `[investigation failed: <topic>]` rather than omitted. Absence is invisible to a reader; an explicit failure marker is not.

If all children of a parent fail, branch-synthesize still runs over the parent's own analysis alone. If the parent's own deep-dive failed, the node has no analysis and produces only a failure record — its parent in turn handles it as above.

## 8. Run Modes

The system supports three modes, distinguishing fresh investigations from inheriting prior structure. Run mode is invoked at the orchestrator level and determines how scope and the initial frontier are populated.

- **`new`** (default): ignore prior runs entirely. The findings store retrieval (§6.4) and persistent uncertainties (§6.7) still surface priors as leads, but the tree is fresh, briefs are derived from scope, and the dossier stands alone.
- **`refresh`**: inherit a prior run's tree structure as the starting frontier. Briefs are inherited from the prior run's reflect outputs (sharper than re-deriving from scratch — those briefs were written by a model that had just read the prior analysis). Each deep-dive runs fresh and may produce different findings; reflect runs over the new analysis and may spawn different children. The new tree is aligned at the root with the prior but diverges as new evidence dictates. Refresh runs require `parent_run_id`.
- **`incremental`**: re-run only parts of the prior tree where findings are stale per their decay class, leave historical/structural branches alone. Deferred to a later version; named here for forward compatibility.

`refresh` is the expected mode for watchlist re-runs and is where the cross-run mechanisms earn their keep. The new deep-dive sees the prior run's findings, contradictions get flagged in the analysis, the new reflect spawns prosecution threads against them, and persistent uncertainties surface for re-verification or escalation per their `closure_class`.

The cross-run feedback loop — findings persist, briefs sharpen, uncertainties accumulate or close, contradictions trigger investigation — is what differentiates this system from a one-shot dossier generator. The v1 implementation supports it; the design intent is for this loop to compound across many refresh cycles over time.

## 9. Output Rendering

Three artifacts are produced from each completed run, plus the run database itself, giving four observability surfaces total. Each serves a different reader; collapsing them is the mistake.

### 9.1 Full dossier

A single markdown document. Each canonical node renders as a section whose heading depth equals the node's depth in the tree. The section structure is:

```
## [Topic]                          (heading at appropriate depth)

[Convergence note if reference_count > 0]
[Branch synthesis paragraph(s)]     (omitted for leaves)

[Full deep-dive analysis text]      (untruncated)

### [Child topic]                   (recursive)
...
```

The convergence note, where present, reads: *"This concern was independently surfaced by N investigations: [list of origin briefs]."* It precedes the branch synthesis to flag structural centrality before the reader descends.

The root of the document begins with a top-level synthesis written *after* all branches complete, with all branch syntheses available as input. The root synthesis uses the same framing as branch syntheses (resolution state, remaining open, contradictions, confidence) rather than narrative summary.

Reference nodes (§2.5) render as a topic and brief at their tree position followed by a cross-reference to the canonical's location ("see §X.Y.Z"). The full inline content appears at the canonical's location, which is the location of the *first* occurrence in tree order. Rejected nodes (§2.7) do not appear in the dossier.

No truncation anywhere. No size limit. Sibling order within a parent follows priority ascending.

### 9.2 Brief-tree audit view

A compact markdown document containing topics, materiality, priority, resolution state, evidence basis, briefs, triggering text spans where present, reference markers, and rejection markers (with reasons) in tree order. Persistent uncertainties surfaced during the run appear in a separate section with their `closure_class` and reasoning. No analyses, no syntheses.

This is the inspection surface for evaluating whether the system is investigating sharp questions, whether dedup decisions look right, whether circularity arbitration is rejecting correctly, and whether closure classification is reasonable.

This view is regenerated continuously during a run — on every node state transition, not only at completion. Cost is a SELECT and a render. The continuous regeneration gives a live observability surface during prompt iteration.

### 9.3 Findings store

The persistent searchable store described in §6. Available across runs, queryable directly outside the run pipeline.

### 9.4 Run database

The SQLite database described in §5. Available for debugging, resume, and ad-hoc inspection of run state.

## 10. Prompts

Detailed prompt text is out of scope for this spec but the constraints are:

- Each call type uses a system prompt that establishes its specific stance: investigator (deep-dive), reviewer (reflect), orienting writer (branch-synthesize, root synthesis), finding extractor (extract), arbitrator (circularity), classifier (closure_class).
- All prompts forbid output-layer judgement — no investment recommendations, ratings, or buy/sell language. Operational judgements internal to the investigation (materiality, priority, resolution state, retrieval relevance) are explicit and required.
- Reflect prompts adopt multiple reviewer framings simultaneously: short-seller's report, regulator, competing operator, acquirer's diligence team, hostile journalist, careful new investor performing verification. The first five are adversarial and catch what gets hand-waved; the last is neutral diligence and catches verification threads, structural facts, and open questions that an attack-only frame would miss.
- Reflect prompts enforce the materiality test from §2.3: material *to this specific business*, not significant in the abstract.
- Reflect prompts require classification of `resolution_state` and `evidence_basis` for every thread candidate. The prompt explicitly distinguishes evidence-anchored threads from speculative possibility-generation, and `triggering_text_span` is encouraged where natural.
- Brief-authoring instructions explicitly state that briefs will be executed without access to the current context and must be self-contained.
- Deep-dive prompts explicitly instruct the model to flag contradictions with retrieved priors in the `contradictions` array (with source descriptors) rather than silently reconciling, and to record side-threads in `discovered_threads` rather than expanding the current investigation.
- Deep-dive prompts treat `searches_per_deepdive_target` as a soft target, not a hard cap.
- Branch-synthesize prompts produce structured prose covering: what was resolved by this branch, what remains open, what contradictions surfaced, confidence in the branch's overall picture. Not narrative summary.
- Circularity arbitration prompts receive minimal context (two briefs only) and return a single classification.
- Closure classifier prompts receive an unresolvable thread and return one of `unknowable | insufficient_evidence_yet | conflicting_evidence_persists` with a short rationale.

Prompt iteration is expected to be the primary tuning surface. The architecture is stable; the prompts will be revised as outputs are reviewed.

## 11. Configuration

Run-time parameters, all configurable:

- `mode` (`new` | `refresh` | `incremental`, default `new`; latter two require `parent_run_id`)
- `parent_run_id` (required for refresh / incremental)
- `max_depth` (default 8, circuit breaker only)
- `max_total_nodes` (default 500, safety limit)
- `max_wall_clock_hours` (default 24)
- `inter_request_delay_seconds` (default 0)
- `searches_per_deepdive_target` (default 6, soft target)
- `dedup_similarity_threshold` (default 0.88)
- `findings_retrieval_scope` (`company` | `sector`, default `company`)
- `uncertainty_resurfacing_interval_days` (default 90; for `insufficient_evidence_yet` class)
- `uncertainty_escalation_contradiction_threshold` (default 3; for `conflicting_evidence_persists` class)
- `model_name` (default `gemma4:latest`)
- `model_temperature` (default 1.0, per Gemma 4 documentation)

## 12. Out of Scope

The following are explicitly not in this system and should not be added:

- Investment recommendations, ratings, target prices, or any output-layer judgement about whether the business is a good or bad investment.
- Quantitative analysis, backtesting, valuation modelling, or price data ingestion.
- Real-time monitoring, alerts, or scheduled re-runs (the system is invoked per company per run; orchestration of multiple runs is a separate concern).
- Cross-branch context-sharing within a single run via prompts. Independence-of-attack-surfaces is preserved: reflect attacks each analysis on its own merits with no cross-branch context. Topical duplication is handled structurally via reference nodes.
- Within-run contradiction surfacing (§6.5). Cross-run only in this version.
- Incremental run mode (§8). Named for forward compatibility but not implemented in v1.
- Continuous numeric reliability scores for sources. Coarse buckets only.
- Human-readable executive summaries optimised for brevity. Compression is the downstream digester's job.

## 13. Remaining Empirical Questions

To be resolved by observation rather than design:

- The `dedup_similarity_threshold` value. Default tight; tune from the brief-tree audit view.
- Circularity arbitration classification accuracy. Spot-check rejections on early runs.
- Closure classifier accuracy. Spot-check `closure_class` assignments — particularly `unknowable` classifications, which silently stop future investigation.
- Whether reference-node render placement at first-occurrence is satisfactory or whether the renderer needs the more complex rule (canonical at shallowest reference).
- Whether `searches_per_deepdive_target = 6` produces the right cost/quality tradeoff.
- Whether `evidence_basis: speculative` priority demotion produces the right balance between coverage and noise.

## Appendix A — Design intent across versions

Several v1 components are sized for trajectories the v1 deliverable does not itself realize. Recording the intent here so v1's heavier-than-necessary structures are legible:

| Component | v1 role | Intended trajectory |
|---|---|---|
| Findings store | Retrieval cache for prior leads | Long-lived structured knowledge substrate accumulating across companies and runs |
| Refresh mode | Re-analysis of a prior run | Temporal continuity; investigative state that compounds over many cycles |
| Persistent uncertainties | Edge-case handling for unresolvable threads | Core epistemic state; the system's record of what is structurally unanswerable vs. open |
| Reference counts | Dedup metadata | Structural centrality signal; convergent rediscovery as evidence |
| Briefs | Prompt artifacts driving deep-dives | Investigative inheritance; sharpened questions passed forward across runs |
| Tree topology | Execution and render structure | Execution topology only; render hierarchy and findings graph diverge as v2+ matures |

These trajectories inform v1 design choices but do not constitute v1 deliverables. The v1 system is a recursive investigation system that produces dossiers and accumulates findings. The trajectories are the direction; revisit when v1 contact with reality clarifies which to pursue first.
