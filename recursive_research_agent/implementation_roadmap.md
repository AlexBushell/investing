# Recursive Research Agent Implementation Roadmap

This document translates `recursive_research_spec.md` into an implementation path. The goal is to build the smallest credible Python backend first, prove the recursive investigation loop, and then add the heavier memory and retrieval layers once the execution model is observable and stable.

The guiding principle is: **make the run database the source of truth, keep model calls stateless, and expose progress through durable artifacts rather than in-memory conversations**.

## Architecture Target

The first production-shaped backend should be a Python package with a CLI entry point and a storage boundary that a future Flutter frontend can observe and control.

Suggested layout:

```text
recursive_research_agent/
  app/
    __init__.py
    cli.py
    config.py
    db.py
    models.py
    prompts.py
    llm.py
    search.py
    embeddings.py
    findings_store.py
    dedup.py
    orchestrator.py
    render.py
  data/
    research.sqlite
    lancedb/
  outputs/
    runs/
  tests/
```

Key boundaries:

- `orchestrator.py` owns the node lifecycle and serial worker.
- `db.py` owns SQLite schema, migrations, state transitions, and queries.
- `models.py` owns Pydantic schemas for all structured model outputs.
- `llm.py` owns Ollama calls and structured-output enforcement.
- `render.py` owns dossier and audit markdown generation.
- `findings_store.py` owns persistent extracted findings and retrieval.
- `dedup.py` owns within-run topical deduplication and circularity arbitration.

## Milestone 0: Project Skeleton

Create the Python package, dependency management, baseline CLI, and test harness.

Scope:

- Add a Python project file, preferably `pyproject.toml`.
- Add `app/` package structure.
- Add `tests/`.
- Add CLI command stubs:
  - `research init-db`
  - `research run "<company>"`
  - `research resume <run_id>`
  - `research render <run_id>`
  - `research audit <run_id>`
- Add configuration loading from defaults plus optional local config file.

Acceptance criteria:

- `research --help` shows the available commands.
- `research init-db` creates a local SQLite database.
- Tests can be run with one command.
- No model, search, or embedding dependency is required yet.

## Milestone 1: Persistent Run Database

Implement the durable run and node state model before adding intelligence.

Scope:

- Implement SQLite tables:
  - `runs`
  - `nodes`
  - `node_references`
  - `node_failures`
  - `node_rejections`
  - `model_calls`
- Include `model_calls` even though it is not in the spec. It should record call type, model name, input payload, output payload or text, timing, and errors.
- Implement transactional state transitions.
- Implement startup recovery for transitional node states.
- Implement priority queue selection from persisted `pending` nodes.

Acceptance criteria:

- A run can be created for a company.
- Root and child nodes can be inserted manually in tests.
- Node state transitions are committed one at a time.
- A simulated crash leaves the database resumable.
- Pending nodes are selected by priority, then creation order.
- Transitional states are reset safely on startup.

## Milestone 2: Typed Schemas and Prompt Contracts

Create the strict structured interfaces before wiring real model calls.

Scope:

- Define Pydantic models for:
  - scope output
  - deep-dive output
  - reflect output
  - discovered thread candidate
  - contradiction record
  - extracted finding
  - circularity arbitration output
  - persistent uncertainty classifier output
- Define enums for:
  - node status
  - resolution state
  - evidence basis
  - claim type
  - source type
  - decay class
  - run status
- Draft initial prompt templates for each call type.

Acceptance criteria:

- Every structured call type has a Pydantic schema.
- Invalid JSON-like outputs fail validation in tests.
- Prompt templates are plain files or functions with explicit input variables.
- No prompt depends on chat history or hidden shared context.

## Milestone 3: Model Client and Fake-Model Harness

Build the LLM boundary in a way that can be tested without running real research.

Scope:

- Implement Ollama client support.
- Support JSON schema enforcement through Ollama `format` or equivalent.
- Implement prose calls for branch synthesis.
- Record every model request and response in `model_calls`.
- Add a fake model backend for deterministic tests.

Acceptance criteria:

- Tests can run fully offline using the fake model.
- Real Ollama calls can be smoke-tested with a small schema.
- Failed validation is recorded as a call failure.
- `model_calls` contains enough input/output data to debug prompt behavior.

## Milestone 4: Minimal Recursive Vertical Slice

Prove the core loop without dedup, findings retrieval, or persistent uncertainties.

Scope:

- Implement:
  - scope call
  - root node creation
  - deep-dive call
  - reflect call
  - child node creation
  - branch synthesis
  - completion propagation
- Enforce stop conditions:
  - no material unresolved investigable children
  - max depth
  - max total nodes
  - max wall-clock time
- Implement per-node failure handling.
- Treat findings extraction as a no-op placeholder.

Acceptance criteria:

- `research run "<company>"` can create and complete a small recursive tree using the fake model.
- Leaves complete without branch synthesis.
- Internal nodes synthesize after all children complete.
- Failed child nodes do not block sibling completion.
- A permanently failed child is included in parent synthesis input as a failure marker.
- The run completes when no pending or waiting work remains.

## Milestone 5: Audit View and Full Dossier Rendering

Add the observability surfaces before making the model behavior more complex.

Scope:

- Render brief-tree audit markdown continuously after state transitions.
- Render full dossier markdown when a run completes.
- Include reference and rejection placeholders in audit rendering even before reference-node behavior exists.
- Include heading hierarchy based on tree depth.
- Add root-level synthesis placeholder or initial implementation.

Acceptance criteria:

- Every node state transition regenerates the audit file.
- Audit output includes topic, priority, materiality, resolution state, evidence basis, brief, status, and triggering span when present.
- Completed runs produce a full dossier markdown file.
- Dossier contains untruncated analysis text.
- Rejected nodes are omitted from the dossier but visible in the audit view.

## Milestone 6: Search-Backed Deep Dives

Connect real external research capability behind a narrow abstraction.

Scope:

- Implement a search provider interface.
- Add one concrete provider first.
- Pass search results into deep-dive calls in a structured way.
- Keep `searches_per_deepdive_target` as a soft prompt/config signal, not a hard orchestration loop.
- Record enough search metadata for traceability.

Acceptance criteria:

- Deep-dive prompts receive source material from the configured search provider.
- Search provider failures become node failures or retryable call failures according to config.
- Analyses are prompted to include inline source attribution for concrete factual claims.
- A fake search provider supports deterministic tests.

## Milestone 7: Within-Run Dedup and Reference Nodes

Implement topical deduplication of investigations after the basic tree is inspectable.

Scope:

- Embed `topic + investigation_brief` for pending nodes.
- Compare against non-ancestor canonical nodes.
- Mark sufficiently similar nodes as references.
- Increment canonical `reference_count`.
- Record `node_references`.
- Render convergence notes in the dossier.

Acceptance criteria:

- A duplicate non-ancestor candidate becomes a reference node and runs no model calls.
- Reference nodes complete immediately.
- Parent synthesis receives the canonical summary for reference children.
- Canonical nodes render convergence notes when referenced.
- Audit output clearly marks reference nodes and their canonical target.

## Milestone 8: Circularity Arbitration

Prevent recursive loops against ancestor questions while preserving legitimate narrowing.

Scope:

- Detect candidate similarity against ancestor nodes separately from non-ancestor dedup.
- Run circularity arbitration when an ancestor match is found.
- Support outcomes:
  - narrower sub-question
  - same question rephrased
  - genuinely distinct
- Record rejected nodes and reasons.

Acceptance criteria:

- Same-question ancestor matches are marked `rejected` and not enqueued.
- Narrower sub-questions proceed normally.
- Genuinely distinct questions proceed normally.
- Rejections are visible in the audit view.
- Rejected nodes do not appear in the full dossier.

## Milestone 9: Findings Extraction and SQLite Retrieval

Add durable findings memory without vector search first.

Scope:

- Implement `findings` table.
- Implement SQLite FTS5 index.
- Extract findings after successful deep-dives.
- Treat extraction failure as non-fatal.
- Retrieve same-company prior findings using structured filters plus FTS.

Acceptance criteria:

- Successful deep-dives attempt findings extraction.
- Findings extraction failure is logged but does not block reflect or synthesis.
- Findings are queryable by company, claim type, source type, decay class, and text.
- Deep-dive calls receive relevant prior findings from earlier runs for the same company.
- Retrieved priors are presented as leads to verify, not authoritative facts.

## Milestone 10: Vector Retrieval

Add semantic retrieval once enough findings exist to evaluate quality.

Scope:

- Add embedding generation through Ollama, initially `nomic-embed-text`.
- Store finding embeddings.
- Add vector retrieval, either:
  - LanceDB, or
  - SQLite BLOB embeddings plus brute-force cosine similarity for early scale.
- Combine structured filters, FTS, and vector similarity.
- Collapse near-duplicate retrieval results at query time.

Acceptance criteria:

- Findings have stored embeddings.
- Deep-dive retrieval can rank findings semantically against an investigation brief.
- Structured filters constrain retrieval scope.
- FTS can act as fallback for identifiers and exact terms.
- Query-time near-duplicate collapse preserves underlying stored findings.

## Milestone 11: Persistent Uncertainties

Add the first long-lived unresolvedness mechanism.

Scope:

- Implement `persistent_uncertainties`.
- Classify reflect outputs with `resolution_state == unresolved_unanswerable`.
- In v1, support only `unknowable` and rejected-as-miscategorized.
- Retrieve semantically related open uncertainties for deep-dive prompts.
- Render uncertainties in the audit view.

Acceptance criteria:

- Unanswerable reflect candidates do not spawn nodes.
- Candidate persistent uncertainties are classified before storage.
- Stored uncertainties are surfaced to later related deep-dives.
- Audit output lists persistent uncertainties with closure class and reasoning.
- False-positive risk is documented in the audit surface.

## Milestone 12: Flutter-Facing Backend Boundary

Prepare the Python backend to be driven and observed by a Flutter app.

Scope:

- Add a local API process or file/database observation contract.
- Expose:
  - create run
  - resume run
  - pause/stop run
  - list runs
  - get run status
  - get audit markdown path/content
  - get dossier path/content
  - get node tree
  - get failures
- Keep the CLI as a first-class interface.

Acceptance criteria:

- Flutter can control runs without importing Python internals.
- The backend can run headless.
- Long-running research continues independently of frontend navigation.
- Run status is recoverable after process restart.
- CLI and frontend use the same storage-backed backend behavior.

## Milestone 13: Prompt Iteration and Evaluation Harness

Make prompt changes observable rather than vibes-based.

Scope:

- Add fixture companies and fake/search snapshots.
- Add prompt version identifiers.
- Add regression runs that compare:
  - node counts
  - rejection/reference counts
  - average depth
  - failed calls
  - extraction counts
  - unresolved uncertainty counts
- Add manual review checklist for audit files.

Acceptance criteria:

- Prompt changes can be associated with changed run topology.
- Regression runs produce comparable metrics.
- Early runs can be spot-checked for dedup and circularity errors.
- The system can answer: "What changed because of this prompt edit?"

## Suggested First Deliverable

The first useful deliverable is not the complete v1 spec. It is:

```text
CLI command:
  research run "Example Company" --fake-model

Outputs:
  data/research.sqlite
  outputs/runs/<run_id>/audit.md
  outputs/runs/<run_id>/dossier.md
```

This proves the core contract:

- The tree lives in SQLite.
- The worker resumes from persisted state.
- Model calls are stateless.
- The recursive lifecycle terminates.
- The audit and dossier surfaces exist.

Once that is true, real search, real Ollama calls, deduplication, findings memory, and Flutter control can be layered in without changing the center of the system.

