# Recursive Adversarial Research System — Design Specification

## 1. Purpose

A self-directed investigation system that, given a company name, produces an exhaustive research dossier by recursively prosecuting every material thread it encounters. The system does not make investment decisions, recommend actions, or render judgment. It surfaces findings, flags gaps, and stops only when nothing material remains to investigate. Output feeds a downstream digestion process and is expected to be larger and more comprehensive than any human analyst could reasonably produce.

The defining stance is **investigator, not analyst**: a junior researcher who cannot stop pulling on threads, who never tires, and whose only job is to find things and write them down with their provenance intact.

## 2. Core Mechanism

The system is a tree of model-authored investigations. Each node represents one weakness, gap, or uncertainty being prosecuted. Investigation of a node produces an analysis; adversarial review of that analysis produces zero or more child nodes, each accompanied by a model-written brief specifying what the next investigation should look like. The recursion continues along each branch until adversarial review surfaces nothing new and material.

### 2.1 Node lifecycle

A node moves through these states: `pending` → `investigating` → `reflecting` → `awaiting_children` → `synthesizing` → `complete`. A node may also enter `failed` and be retried. Persistence captures the state at each transition so that a crashed run resumes from the frontier rather than restarting.

### 2.2 Call types

Five distinct model call types, each with its own system prompt and context envelope. Calls are stateless: each is constructed fresh from the tree and carries no conversation history.

- **Scope**: given a company name, produce the initial set of root-level investigation briefs tailored to this specific company. Replaces the original "Phase 1" generic dimensional analysis.
- **Deep-dive**: given an investigation brief and path-to-root context, conduct a thorough investigation using web search. Produces the analysis text that becomes the body of the node.
- **Reflect**: given an analysis (either a deep-dive or a branch synthesis), adversarially attack it. Produce zero or more child weakness nodes, each with topic, description, materiality score, and a self-contained investigation brief.
- **Branch-synthesize**: given a node's analysis and its children's branch-syntheses, write a short orienting summary of what this branch found and what remains loose. Not a judgment, an orientation.
- **Extract findings**: given a deep-dive analysis, extract atomic findings as structured records for the searchable store.

### 2.3 Materiality gate

Every weakness produced by reflect is scored 1–5. The threshold for recursion is 3. The framing in the reflect prompt is binary at heart — *does this materially affect the quality or execution of the business?* — with the 1–5 score serving as queue-ordering signal among the things that pass the gate. The original code's habit of forcing scores to decline with depth is removed: third-order weaknesses are sometimes the load-bearing ones.

### 2.4 Stop conditions

A branch terminates when reflect produces no children with score ≥ threshold. A depth cap exists as a circuit breaker (default 8) but is not the primary control. Per-run safety limits — maximum total nodes and maximum wall-clock time — exist for the same reason.

## 3. Context Discipline

Every model call is constructed from scratch. There is no shared message list, no `add_messages` reducer, no conversation history propagating between calls. State lives in the tree; messages are transient I/O.

What each call type receives is defined explicitly:

- **Scope** receives only the company name and its system prompt.
- **Deep-dive** receives the company name, the path from root to this node (each ancestor as topic + its branch synthesis, never full analyses), the investigation brief, any relevant prior findings retrieved from the searchable store, and the system prompt. It does not receive sibling analyses, the initial scope output, or the full tree.
- **Reflect** receives only the analysis being reviewed and the system prompt. No tree context — its job is to attack one piece of writing on its own merits.
- **Branch-synthesize** receives the parent's deep-dive analysis and each child's branch-synthesis. Not the children's full analyses.
- **Extract findings** receives only the analysis to extract from.

The temptation to "help" the model by passing more context than each call needs must be actively resisted. The tree is the orchestrator's memory; the model gets only what serves its narrow local task.

## 4. Briefs as First-Class Artifacts

Each weakness node carries four fields: `topic` (short label), `description` (human-readable summary for the rendered report), `materiality_score`, and `investigation_brief` (the self-contained prompt body that will drive the next deep-dive). The brief is authored by the reflect call that surfaced the weakness, because that call has just read the parent analysis and is best positioned to specify what the next investigation should look for.

Briefs are inspectable artifacts. A separate render mode (see §8) produces a brief-tree view containing only topics, briefs, and scores — the audit surface for whether the system is investigating sharp questions or fuzzy ones.

The reflect prompt explicitly instructs the model that briefs will be executed by a future model with no access to the current conversation, so briefs must be self-contained: name companies, time periods, specific data sources, and specific questions.

## 5. Persistence

A SQLite database holds the structured tree. Schema (informal):

- `runs`: `run_id`, `company`, `started_at`, `completed_at`, `status`
- `nodes`: `node_id`, `run_id`, `parent_id`, `topic`, `description`, `materiality_score`, `investigation_brief`, `analysis`, `branch_synthesis`, `status`, `depth`, `created_at`, `updated_at`
- `node_failures`: `node_id`, `attempt`, `error`, `failed_at` — for retry accounting

Every state transition is committed. On startup, any nodes left in `investigating`, `reflecting`, or `synthesizing` from a prior crashed run are reset to `pending` (or to the appropriate prior state) and resumed.

## 6. Searchable Findings Store

A separate persistent store accumulates atomic findings across all runs and companies. Findings are extracted by a dedicated model call at the end of each deep-dive, not stored as raw analyses.

### 6.1 Finding schema

`finding_id`, `run_id`, `node_id`, `company`, `claim`, `evidence`, `source`, `confidence` (low/medium/high), `date_observed` (when the finding was first recorded), `date_last_verified`, `tags` (sector, theme, free-form).

### 6.2 Indexes

Three coordinated indexes keyed by `finding_id`:

- **Vector index** for semantic similarity (LanceDB or Chroma, embedded, no server).
- **FTS5 lexical index** in SQLite for exact-term queries (named entities, regulations, identifiers that embeddings handle poorly).
- **Structured filters** in SQLite for company, date range, confidence, tags.

Queries combine all three: structured filter narrows the candidate set, vector similarity ranks within it, lexical search serves as both filter and fallback.

### 6.3 Embeddings

Default to a hosted embedding model for retrieval quality (Voyage, Cohere, or OpenAI). A local Ollama option (`nomic-embed-text`) is supported via configuration for fully-local deployments, with the documented tradeoff that retrieval quality is meaningfully lower.

### 6.4 Retrieval at deep-dive start

Before each deep-dive call, the system queries the findings store for prior findings semantically related to the investigation brief, scoped by configurable filters (default: any company, any time within the last 18 months). Retrieved findings are passed into the deep-dive prompt as **prior leads from earlier investigations**, with their full provenance attached, with explicit instruction that they are starting points to verify, not authorities to cite.

### 6.5 Staleness and contradiction

Each retrieved finding is annotated with its age. Findings older than a configurable threshold are flagged stale in the prompt, with explicit instruction to re-verify. When a new deep-dive produces a finding that contradicts a retrieved prior finding, the contradiction is itself surfaced as a weakness for investigation in the current run. This is the mechanism by which the system notices that its own prior conclusions have been falsified.

### 6.6 Deduplication

No deduplication at storage time. Every finding is stored with its run, node, and timestamps. Query-time logic collapses near-duplicates by vector similarity above a high threshold and surfaces the most recent. The historical record is preserved.

## 7. Concurrency and Resilience

Independent branches of the tree are investigated in parallel by a worker pool. The frontier is the set of nodes in `pending` state; workers pull from the frontier, transition the node through its lifecycle, and write completions back. Concurrency is bounded by available local model capacity (Ollama is typically the bottleneck) and by per-worker rate limits on external tools (Brave QPS is enforced per worker, not globally).

Failures are per-node. A failed deep-dive marks the node `failed`, records the error, and either retries on a backoff schedule or skips and continues, depending on configuration. Transient infrastructure problems — search API rate limits, model server restarts, network glitches — degrade run speed but do not terminate runs. The unit of retry is the node; the orchestrator never retries an entire run.

## 8. Output Rendering

Two artifacts are produced from each completed run.

### 8.1 Full dossier

A single markdown document. Each node renders as a section whose heading depth equals the node's depth in the tree. The section structure is:

```
## [Topic]                          (heading at appropriate depth)

[Branch synthesis paragraph(s)]     (omitted for leaves)

[Full deep-dive analysis text]      (untruncated)

### [Child topic]                   (recursive)
...
```

The root of the document begins with a top-level synthesis written *after* all branches complete, with all branch syntheses available as input. The root synthesis is orientational, not conclusive.

No truncation anywhere. No size limit. Sibling order within a parent follows materiality score descending.

### 8.2 Brief-tree audit view

A compact markdown document containing only topics, materiality scores, and briefs in tree order. No analyses, no syntheses. This is the inspection surface for evaluating whether the system is investigating sharp questions; it is not for downstream consumption.

## 9. Prompts

Detailed prompt text is out of scope for this spec but the constraints are:

- Each call type uses a system prompt that establishes its specific stance: investigator, hostile reviewer, orienting writer, finding extractor.
- All prompts forbid synthesis-as-judgment. The system surfaces findings; it does not conclude.
- Reflect prompts are explicitly adversarial in tone — what would a short-seller's report attack here, what was hand-waved, what was assumed.
- Brief-authoring instructions explicitly state that briefs will be executed without access to the current context and must be self-contained.

Prompt iteration is expected to be the primary tuning surface. The architecture is stable; the prompts will be revised as outputs are reviewed.

## 10. Configuration

Run-time parameters, all configurable:

- `materiality_threshold` (default 3)
- `max_depth` (default 8, circuit breaker only)
- `max_total_nodes` (default 500, safety limit)
- `max_wall_clock_hours` (default 24)
- `worker_concurrency` (default 4)
- `brave_qps_per_worker` (default 1)
- `embedding_provider` (`voyage` | `openai` | `cohere` | `ollama`)
- `findings_retrieval_window_months` (default 18)
- `findings_staleness_threshold_months` (default 6)
- `model_name` (default `gemma4:latest`)
- `model_temperature` (default 1.0, per Gemma 4 documentation)

## 11. Out of Scope

The following are explicitly not in this system and should not be added:

- Investment recommendations, ratings, target prices, or any form of decision output.
- Quantitative analysis, backtesting, valuation modelling, or price data ingestion.
- Real-time monitoring, alerts, or scheduled re-runs (the system is invoked per company per run; orchestration of multiple runs is a separate concern).
- Cross-branch context-sharing within a single run (independence of branches is a feature; cross-pollination happens only across runs via the findings store).
- Human-readable executive summaries optimised for brevity. Compression is the downstream digester's job.

## 12. Open Questions

To be resolved before implementation:

- Embedding provider selection (depends on whether fully-local deployment is required).
- Specific vector store choice (LanceDB vs Chroma — both viable, mild preference for LanceDB for its embedded simplicity).
- Whether the contradiction-surfacing mechanism (§6.5) operates within a single run or only across runs in its first version.
- Whether the brief-tree audit view should be generated continuously during a run (for live inspection) or only at completion.
