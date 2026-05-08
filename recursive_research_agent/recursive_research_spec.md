# Recursive Adversarial Research System — Design Specification

## 1. Purpose

A self-directed investigation system that, given a company name, produces an exhaustive research dossier by recursively prosecuting every material thread it encounters. The system does not make investment decisions, recommend actions, or render judgement. It surfaces findings, flags gaps, and stops only when nothing material remains to investigate. Output feeds a downstream digestion process and is expected to be larger and more comprehensive than any human analyst could reasonably produce.

The defining stance is **investigator, not analyst**: a junior researcher who cannot stop pulling on threads, who never tires, and whose only job is to find things and write them down with their provenance intact.

## 2. Core Mechanism

The system is a tree of model-authored investigations. Each node represents one **thread** — anything a careful reviewer would want to understand more deeply before forming a judgement of the business. Threads include adversarial concerns, verification questions, neutral facts whose implications are not yet clear, and open questions whose answer would change a reviewer's understanding regardless of which way it lands. The framing is deliberately broader than "weakness" — defects and risks are a subset of threads, not the whole.

Investigation of a node produces an analysis; review of that analysis produces zero or more child threads, each accompanied by a model-written brief specifying what the next investigation should look like. The recursion continues along each branch until review surfaces nothing new and material.

### 2.1 Node lifecycle

A node moves through these states: `pending` → `investigating` → `reflecting` → `awaiting_children` → `synthesizing` → `complete`. A node may also enter `failed` and be retried. Persistence captures the state at each transition so that a crashed run resumes from the frontier rather than restarting.

A separate state — `reference` — is described in §2.5 and short-circuits the lifecycle for topical duplicates. A `rejected` state is described in §2.7 for threads that fail circularity arbitration.

### 2.2 Call types

Five distinct model call types, each with its own system prompt and context envelope. Calls are stateless: each is constructed fresh from the tree and carries no conversation history. All call types that produce parseable output use enforced JSON schemas (see §2.8).

- **Scope**: given a company name, produce the initial set of root-level investigation briefs tailored to this specific company.
- **Deep-dive**: given an investigation brief, path-to-root context, and any retrieved prior findings, conduct a thorough investigation using web search. Produces a structured response containing a long-form `analysis`, a one-paragraph `abstract`, a list of flagged `contradictions` with retrieved priors, and a list of `discovered_threads` — threads encountered during the investigation that warrant their own future prosecution (see §2.6).
- **Reflect**: given an analysis, identify every thread a reviewer would want pulled. Produce zero or more child thread candidates, each with topic, description, materiality decision, priority, and a self-contained investigation brief.
- **Branch-synthesize**: given a node's analysis and the summaries of its completed children, write a short orienting paragraph stating what this branch found and what remains loose. Not a judgement, an orientation. Internal nodes only; leaves do not run this call. Returns prose, not JSON.
- **Extract findings**: given a deep-dive analysis, extract atomic findings as structured records for the searchable store (see §6).

A sixth call type — **circularity arbitration** — runs only when the dedup check finds an ancestor match. See §2.7.

### 2.3 Materiality and priority

Reflect produces two judgements per child candidate, recorded as separate fields:

- `material: bool` — is this thread material to the quality or execution of *this specific business*? This is the recursion gate. Only material threads become nodes.
- `priority: 1 | 2 | 3` — among material threads, how urgently should this be investigated relative to peers? This is the queue-ordering signal only. It does not gate.

Splitting these prevents the conflation a single 1–5 score forced. A thread can be material but lower-priority; high-priority threads are always also material.

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

This preserves the §3 independence property — reflect still attacks each canonical analysis on its own merits with no cross-branch context — while eliminating waste from topical duplication.

The similarity threshold matters and is empirical. Too loose merges genuinely distinct investigations ("EU regulatory exposure in payments" vs. "in data privacy"); too tight and true duplicates slip through. Default tight; loosen on observation. The brief-tree audit view (§8.2) is the natural surface for spot-checking dedup decisions.

### 2.6 Threads discovered mid-investigation

A deep-dive may surface threads that are not gaps in the current investigation but rather entirely separate questions encountered along the way. A regulatory deep-dive that incidentally notices a major customer concentration issue should not pause to investigate the customer concentration — it should finish the regulatory work and leave a note for future prosecution.

Deep-dive's structured output includes a `discovered_threads` array with the same schema as reflect's child candidates: topic, description, material, priority, investigation_brief. These threads are enqueued via the same pipeline as reflect's output, subject to the same dedup check (§2.5) and circularity arbitration (§2.7), and treated identically in scheduling. The parent of a discovered thread is the same as the parent of the deep-dive that surfaced it (i.e. they become siblings of the discovering node, not children) — they are independent investigations, not sub-aspects of the discovering node.

This separates two genuinely different model behaviors: reflect *attacks the analysis just produced*; deep-dive *notices side-threads while doing its primary work*. Conflating them in the original spec was an oversight.

The number of searches per deep-dive remains a soft target controlled by `searches_per_deepdive_target`. The instruction to the model is that searches are for completing the current investigation; threads encountered along the way go in `discovered_threads` rather than triggering more searches within the current call.

### 2.7 Circular research and ancestor arbitration

The §2.5 dedup check excludes ancestors of the candidate node. Ancestor matches are handled separately because the embedding similarity alone cannot distinguish two distinct cases:

- **Legitimate narrowing**: a thread at depth 4 is a genuine sub-aspect of an ancestor at depth 1. "Customer concentration" at depth 1, "Top 3 customers' renewal cycles" at depth 4 — semantically similar, but the depth-4 thread is a sharper question, not a duplicate. Pursuing it is correct.
- **Circularity**: the model has lost track of where it is in the tree and spawned a thread that's effectively the same question as an ancestor, just rephrased. "Recession sensitivity of member retention" at depth 2, "How members behave in economic downturns" at depth 4 — the same question, two phrasings.

When the dedup check finds an ancestor match (above the same threshold), the orchestrator runs a **circularity arbitration** call: given the ancestor's brief and the candidate's brief, decide whether the candidate is a narrower sub-question of the ancestor, the same question rephrased, or genuinely distinct. The model is the right judge because the discrimination is semantic, not syntactic.

Outcomes:

- **Narrower sub-question**: proceed with the candidate as a normal node (no reference, no rejection).
- **Same question rephrased**: mark the candidate `rejected`, log the rejection with the ancestor it duplicated, do not enqueue. This prevents the doom-loop of the system asking itself the same question at increasing depth.
- **Genuinely distinct**: proceed normally. (This case mostly arises when the embedding match is a false positive.)

Rejected nodes appear in the run database (§5) for inspection but not in the rendered dossier (§8.1). They do appear in the brief-tree audit view (§8.2) with their rejection reason, because the audit view's job includes catching arbitration mistakes.

### 2.8 JSON schema enforcement

Every call type that returns parseable output enforces a JSON schema at the model API level — not via prompt instruction with retry-on-parse-failure. Use Ollama's `format` parameter (or `langchain_ollama`'s `with_structured_output`) bound to a Pydantic schema per call type.

Call types with enforced schemas: scope, deep-dive (envelope: `{analysis, abstract, contradictions, discovered_threads}`), reflect, extract findings, circularity arbitration. Branch-synthesize returns prose and is not JSON-enforced.

Validation failures are treated as call failures (§7.1) — retry with backoff, do not paper over with regex extraction. The original code's parse-then-retry-with-prompt pattern is fragile and leaks malformed text into context.

### 2.9 Stop conditions

A branch terminates when reflect produces no children with `material: true` and the deep-dive surfaced no `discovered_threads` with `material: true`. A depth cap exists as a circuit breaker (default 8) but is not the primary control. Per-run safety limits — maximum total nodes and maximum wall-clock time — exist for the same reason.

## 3. Context Discipline

Every model call is constructed from scratch. There is no shared message list, no `add_messages` reducer, no conversation history propagating between calls. State lives in the tree; messages are transient I/O.

What each call type receives is defined explicitly:

- **Scope** receives only the company name and its system prompt.
- **Deep-dive** receives the company name, the path from root to this node (each ancestor as `topic` + `investigation_brief` + `abstract` — all stable at call time), the investigation brief for this node, any prior findings retrieved from the searchable store (see §6.4), and the system prompt. It does not receive sibling analyses, the scope output, or the full tree.
- **Reflect** receives only the analysis being reviewed and the system prompt. No tree context — its job is to attack one piece of writing on its own merits.
- **Branch-synthesize** receives the parent's deep-dive analysis and the summary of each completed child (`branch_synthesis` for internal children, `abstract` for leaf children).
- **Extract findings** receives only the analysis to extract from.
- **Circularity arbitration** receives the ancestor's brief and the candidate's brief. Nothing else.

The temptation to "help" the model by passing more context than each call needs must be actively resisted. The tree is the orchestrator's memory; the model gets only what serves its narrow local task.

## 4. Briefs as First-Class Artifacts

Each node carries: `topic` (short label), `description` (human-readable summary for the rendered report), `material` (bool), `priority` (1–3), and `investigation_brief` (the self-contained prompt body that will drive the next deep-dive). The brief is authored by the call that surfaced the thread (reflect or deep-dive's `discovered_threads`).

Briefs are inspectable artifacts. The brief-tree audit view (§8.2) renders only topics, briefs, materiality, and priority — the audit surface for whether the system is investigating sharp questions or fuzzy ones.

Brief-authoring instructions explicitly state that briefs will be executed by a future model with no access to the current conversation, so briefs must be self-contained: name companies, time periods, specific data sources, and specific questions.

## 5. Persistence

A SQLite database holds the structured tree. Schema (informal):

- `runs`: `run_id`, `company`, `mode` (new/refresh/incremental — see §7.3), `parent_run_id` (nullable, for refresh/incremental), `started_at`, `completed_at`, `status`
- `nodes`: `node_id`, `run_id`, `parent_id`, `canonical_node_id`, `topic`, `description`, `material`, `priority`, `investigation_brief`, `analysis`, `abstract`, `branch_synthesis`, `status`, `depth`, `created_at`, `updated_at`
- `node_failures`: `node_id`, `attempt`, `error`, `failed_at`
- `node_rejections`: `node_id`, `reason`, `duplicated_ancestor_id`, `rejected_at`

Every state transition is committed. On startup, any nodes left in transitional states from a prior crashed run are reset to the appropriate prior state and resumed.

## 6. Searchable Findings Store

A separate persistent store accumulates atomic findings across all runs and companies. Findings are extracted by a dedicated model call at the end of each deep-dive, not stored as raw analyses.

### 6.1 Finding schema

`finding_id`, `run_id`, `node_id`, `company`, `claim`, `evidence`, `source`, `confidence` (low/medium/high), `decay_class` (historical/structural/current — see §6.4), `date_observed`, `date_last_verified`, `tags` (sector, theme, free-form).

### 6.2 Indexes

Three coordinated indexes keyed by `finding_id`:

- **Vector index** for semantic similarity (LanceDB, embedded, no daemon).
- **FTS5 lexical index** in SQLite for exact-term queries (named entities, regulations, identifiers that embeddings handle poorly).
- **Structured filters** in SQLite for company, date range, confidence, decay class, tags.

Queries combine all three: structured filter narrows the candidate set, vector similarity ranks within it, lexical search serves as both filter and fallback.

### 6.3 Embeddings

Local via Ollama (`nomic-embed-text`). The retrieval-quality gap relative to hosted embedding models (Voyage, OpenAI, Cohere) is real and will manifest as occasionally-noisy retrievals at §6.4. Acceptable for a fully-local deployment.

### 6.4 Retrieval at deep-dive start

Before each deep-dive call, the system queries the findings store for prior findings semantically related to the investigation brief. Retrieved findings are passed into the deep-dive prompt as **prior leads from earlier investigations**, with their full provenance attached, with explicit instruction that they are starting points to verify, not authorities to cite.

No hard age cutoff on retrieval. Each finding is annotated with its `decay_class` and its age in the prompt:

- **historical** — facts whose truth is fixed by a past event. Founded by, sued by, IPO'd at, acquired in. Never stale; age is irrelevant.
- **structural** — facts about the business that drift over months to years. Market share, cost structure, customer concentration, distribution channels. Skepticism scales with age.
- **current** — facts that change frequently. CEO, stated strategy, latest quarter, current pricing. Treat as stale beyond a few months and re-verify.

The deep-dive prompt instructs the model to apply per-class skepticism rather than treating all old findings identically. A 10-year-old historical finding is still load-bearing context; a 6-month-old "current" finding requires re-verification.

Default retrieval scope is `company == current_company` plus findings explicitly tagged as comparable. Cross-company retrieval (sector-wide) is opt-in via a flag for sector-level investigations. The default narrow scope avoids drowning company-specific deep-dives in noise.

### 6.5 Contradiction surfacing

Contradictions are detected at deep-dive time, not extract-findings time. The deep-dive call has access to retrieved priors; it is the call best positioned to notice "the prior says X, my fresh search says Y." The deep-dive prompt mandatorily instructs the model to flag contradictions in its `contradictions` array (and reference them in the analysis text) — not to silently reconcile in favor of the more recent source.

A flagged contradiction is then picked up by the normal reflect step, which sees the contradiction in the analysis and is free to spawn a thread to prosecute the discrepancy. No special-case path. Extract-findings remains narrow and stateless.

This is initially a cross-run mechanism only: the priors are findings from earlier runs. Within-run contradictions (between sibling branches of the same run) are deferred — they would introduce a second-order coupling between nodes that fights §3's context discipline, and are easier to add later than to remove.

### 6.6 Deduplication of findings

No deduplication at storage time. Every finding is stored with its run, node, and timestamps. Query-time logic collapses near-duplicates by vector similarity above a high threshold and surfaces the most recent. The historical record is preserved.

This is distinct from the within-run reference-node mechanism (§2.5), which dedups *investigations*. Findings dedup is across runs only and happens at retrieval time, not storage time.

## 7. Execution Model

### 7.1 Worker and queue

A single worker, serial execution. The frontier is a priority queue of `pending` nodes, ordered by `priority` ascending (1 = highest), with parents preceding children because reflect runs only after deep-dive completes. The worker pulls one node, runs the dedup check (§2.5) and if needed circularity arbitration (§2.7), transitions the node through its lifecycle if canonical or short-circuits to reference/rejected otherwise, commits each state change, and moves on.

No worker pool, no concurrency. The system is intended to run for hours-to-a-day on a single user's machine; the model server is the bottleneck, and parallel workers would contend for it without producing speedup. An optional `inter_request_delay_seconds` exists for users who want to throttle search API usage; otherwise the natural pace of model calls determines throughput.

### 7.2 Failure handling and cascade

Failures are per-node. A failed deep-dive marks the node `failed`, records the error, and either retries on a backoff schedule or skips and continues, depending on configuration. JSON validation failures (§2.8) are call failures and follow the same path. The unit of retry is the node; the orchestrator never retries an entire run. Transient infrastructure problems — search API rate limits, model server restarts, network glitches — degrade run speed but do not terminate runs.

A permanently failed node terminates its own branch: no reflect runs, no children spawn, no further descent through it. It does not block siblings — the parent's branch continues with the surviving children. Branch-synthesize at the parent runs over the surviving children's summaries with the failed node noted explicitly in the synthesis input as `[investigation failed: <topic>]` rather than omitted. Absence is invisible to a reader; an explicit failure marker is not.

If all children of a parent fail, branch-synthesize still runs over the parent's own analysis alone. If the parent's own deep-dive failed, the node has no analysis and produces only a failure record — its parent in turn handles it as above.

### 7.3 Run modes

A run is invoked in one of three modes:

- **`new`** (default): ignore prior runs entirely. The findings store retrieval (§6.4) still pulls priors as leads, but the tree is fresh, briefs are derived from scope, and the dossier stands alone.
- **`refresh`**: copy a prior run's tree structure as the starting frontier. Briefs are inherited from the prior run's reflect outputs (sharper than re-deriving from scratch — those briefs were written by a model that just read the prior analysis). Each deep-dive runs fresh and may produce different findings; reflect runs over the new analysis and may spawn different children. The new tree is aligned at the root with the prior but diverges as new evidence dictates. Refresh runs require `parent_run_id` to be specified.
- **`incremental`**: re-run only the parts of the prior tree where findings are stale per their decay class, leave historical/structural branches alone. Deferred to a later version; named here for forward compatibility.

`refresh` is the expected mode for watchlist re-runs and is where contradiction surfacing earns its keep — the new deep-dive sees the prior run's findings, and contradictions get flagged as threads in the normal flow.

## 8. Output Rendering

Three artifacts are produced from each completed run, plus the run database itself, giving four observability surfaces total. Each serves a different reader; collapsing them is the mistake.

### 8.1 Full dossier

A single markdown document. Each canonical node renders as a section whose heading depth equals the node's depth in the tree. The section structure is:

```
## [Topic]                          (heading at appropriate depth)

[Branch synthesis paragraph(s)]     (omitted for leaves)

[Full deep-dive analysis text]      (untruncated)

### [Child topic]                   (recursive)
...
```

The root of the document begins with a top-level synthesis written *after* all branches complete, with all branch syntheses available as input. The root synthesis is orientational, not conclusive.

Reference nodes (§2.5) render as a topic and brief at their tree position followed by a cross-reference to the canonical's location ("see §X.Y.Z"). The full inline content appears at the canonical's location, which is the location of the *first* occurrence in tree order. Rejected nodes (§2.7) do not appear in the dossier.

No truncation anywhere. No size limit. Sibling order within a parent follows priority ascending.

### 8.2 Brief-tree audit view

A compact markdown document containing only topics, materiality, priority, briefs, reference markers, and rejection markers (with reasons) in tree order. No analyses, no syntheses. This is the inspection surface for evaluating whether the system is investigating sharp questions, whether dedup decisions look right, and whether circularity arbitration is rejecting correctly.

This view is regenerated continuously during a run — on every node state transition, not only at completion. Cost is a SELECT and a render. The continuous regeneration gives a live observability surface during prompt iteration, which is the work-phase that will consume most ongoing development effort.

### 8.3 Findings store

The persistent searchable store described in §6. Available across runs, queryable directly outside the run pipeline.

### 8.4 Run database

The SQLite database described in §5. Available for debugging, resume, and ad-hoc inspection of run state.

## 9. Prompts

Detailed prompt text is out of scope for this spec but the constraints are:

- Each call type uses a system prompt that establishes its specific stance: investigator (deep-dive), reviewer (reflect), orienting writer (branch-synthesize, root synthesis), finding extractor (extract), arbitrator (circularity).
- All prompts forbid synthesis-as-judgement. The system surfaces findings; it does not conclude.
- Reflect prompts adopt multiple reviewer framings simultaneously: what would a short-seller's report attack, what would a regulator flag, what would a competing operator exploit, what would an acquirer's diligence team raise, what would a hostile journalist write about, what would a careful new investor want to verify. The first five are adversarial and catch what gets hand-waved; the last is neutral diligence and catches verification threads, structural facts, and open questions that an attack-only frame would miss. A single frame produces lopsided coverage; the broadened frame is what aligns with §2's "thread" concept rather than "weakness."
- Reflect prompts enforce the materiality test from §2.3: material *to this specific business*, not significant in the abstract. Drama without exposure is not material.
- Brief-authoring instructions explicitly state that briefs will be executed without access to the current context and must be self-contained (name companies, time periods, sources, questions).
- Deep-dive prompts explicitly instruct the model to flag contradictions with retrieved priors in the `contradictions` array rather than silently reconciling, and to record side-threads in `discovered_threads` rather than expanding the current investigation.
- Deep-dive prompts treat `searches_per_deepdive_target` as a soft target, not a hard cap. The instruction is to stop searching when there is enough data, not to stop at a count.
- Circularity arbitration prompts receive minimal context (two briefs only) and are constrained to return a single classification: `narrower`, `same_rephrased`, or `distinct`.

Prompt iteration is expected to be the primary tuning surface. The architecture is stable; the prompts will be revised as outputs are reviewed.

## 10. Configuration

Run-time parameters, all configurable:

- `mode` (`new` | `refresh` | `incremental`, default `new`; `refresh` and `incremental` require `parent_run_id`)
- `parent_run_id` (required for `refresh` and `incremental`)
- `material_gate` — implicit; no threshold. Reflect's `material: bool` decides.
- `max_depth` (default 8, circuit breaker only)
- `max_total_nodes` (default 500, safety limit)
- `max_wall_clock_hours` (default 24)
- `inter_request_delay_seconds` (default 0, optional throttle)
- `searches_per_deepdive_target` (default 6, soft target)
- `dedup_similarity_threshold` (default 0.88, tight; loosen on observation)
- `findings_retrieval_scope` (`company` | `sector`, default `company`)
- `model_name` (default `gemma4:latest`)
- `model_temperature` (default 1.0, per Gemma 4 documentation)

## 11. Out of Scope

The following are explicitly not in this system and should not be added:

- Investment recommendations, ratings, target prices, or any form of decision output.
- Quantitative analysis, backtesting, valuation modelling, or price data ingestion.
- Real-time monitoring, alerts, or scheduled re-runs (the system is invoked per company per run; orchestration of multiple runs is a separate concern).
- Cross-branch context-sharing within a single run via prompts. Independence-of-attack-surfaces is preserved: reflect attacks each analysis on its own merits with no cross-branch context. Topical duplication is permitted to be eliminated structurally via reference nodes (§2.5) — a different axis from prompt-level cross-pollination.
- Within-run contradiction surfacing (§6.5). Cross-run only in this version.
- Incremental run mode (§7.3). Named for forward compatibility but not implemented in v1.
- Human-readable executive summaries optimised for brevity. Compression is the downstream digester's job.

## 12. Remaining Empirical Questions

To be resolved by observation rather than design:

- The `dedup_similarity_threshold` value. Default tight; tune from the brief-tree audit view.
- The arbitration model's classification accuracy in §2.7. The brief-tree audit view exposes rejections with reasons; spot-check on early runs to confirm the classifier is rejecting genuine circularity rather than legitimate narrowing.
- Whether reference-node render placement at first-occurrence is satisfactory or whether the renderer needs the more complex rule (canonical at shallowest reference). Revisit if the arbitrary placement produces awkward dossiers.
- Whether `searches_per_deepdive_target = 6` produces the right cost/quality tradeoff. Adjust on review.
