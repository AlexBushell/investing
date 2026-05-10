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

### Milestone 3B: Swappable Model Providers and OpenRouter

The model client should become provider-neutral before the project grows many
model-specific assumptions. Ollama is the first real backend, but OpenRouter
should be available as a second backend so research quality can be compared
across local and hosted models without changing orchestration, search, or
rendering behavior.

Target boundary:

```text
recursive worker
  -> ResearchModelClient protocol
  -> provider implementation
       - OllamaModelClient
       - OpenRouterModelClient
       - FakeModelClient
```

OpenRouter should be treated first as a model provider, not as an evidence
provider. Even when an OpenRouter model supports native web/search tools, the
research system should keep retrieval and provenance outside the model by
default:

```text
model proposes search/retrieval needs
  -> our SearchProvider / RetrievalProvider gathers evidence
  -> evidence is normalized into SourceMaterial
  -> model analyzes provided evidence and returns structured JSON
```

This preserves the core audit guarantees:

- source URLs, dates, retrieval times, and provider metadata remain visible
  in SQLite and markdown artifacts
- evidence can be deduplicated, reused, and refreshed across runs
- model swapping does not silently change the evidence collection path
- corpus retrieval and evidence sufficiency gates remain provider-independent

OpenRouter-native tools can be added later as an optional discovery provider,
but only if their tool results are captured and normalized into the same
`SourceMaterial`/document provenance records as Brave, filings, or corpus
retrieval. The model should not be allowed to cite opaque tool output that the
run database cannot inspect.

Suggested first CLI shape:

```text
research openrouter-run "Company Name" \
  --model anthropic/claude-sonnet-4.5 \
  --web-search brave \
  --max-depth 2 \
  --max-total-nodes 6 \
  --search-results 6
```

Later, once model-provider selection is generic:

```text
research model-run "Company Name" \
  --provider openrouter \
  --model openai/gpt-4.1 \
  --retrieval corpus \
  --web-search brave \
  --search-on-insufficient-evidence
```

Scope:

- Extract any remaining Ollama-specific assumptions from the research model
  boundary.
- Add an `OpenRouterModelClient` that uses OpenRouter chat completions with
  structured JSON output.
- Support `OPENROUTER_API_KEY` and CLI/API key configuration.
- Persist provider metadata in `model_calls`, including:
  - provider name
  - requested model
  - resolved/returned model when available
  - finish reason and native finish reason
  - prompt/completion/total token counts
  - reported cost when available
- Keep the existing fake model path provider-neutral.
- Do not use model-native search tools in the first OpenRouter implementation.

Acceptance criteria:

- A user can run the same company investigation through either Ollama or
  OpenRouter.
- The same prompt/schema contracts are used across providers.
- OpenRouter structured JSON failures are persisted in `model_calls` with the
  raw returned content when available.
- Search and retrieval behavior does not change when the model provider
  changes.
- CLI help makes the distinction clear:
  - model provider controls reasoning/writing
  - search/retrieval provider controls evidence
- Tests cover request formatting, response parsing, metadata persistence, and
  CLI argument handling for OpenRouter.

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

### Milestone 5B: Dossier Synthesis Quality and Reader-First Assembly

Deep recursive runs can generate a large amount of text without generating a
better research artifact. The dossier renderer and branch synthesis layer must
turn the tree into a readable argument, not simply concatenate every node and
every child summary.

The Microsoft deep-run observation exposed the key failure mode: the system can
reconfirm the same missing disclosure across many branches, repeat identical
child summaries at multiple depths, and bury the strongest conclusion under
pages of duplicated scaffolding. This is a rendering and research-control
problem, not only a prompt problem.

Target dossier shape:

```text
Executive conclusion
  - headline answer
  - confidence and evidence quality
  - strategic/investment implication

Key findings
  - canonical finding IDs
  - source strength
  - what is known / inferred / not disclosed / not knowable

Branch sections
  - parent synthesis only when it adds interpretation
  - child references by canonical finding ID
  - no repeated nested child-summary blocks

Evidence gaps and next research moves
  - normal industry opacity vs company-specific disclosure gap
  - proxy analyses to attempt next
```

Scope:

- Replace placeholder branch synthesis with actual parent interpretation.
  Parent nodes should synthesize sibling results, weight evidence, identify
  patterns, and escalate what matters. They should not merely restate child
  abstracts.
- Add canonical finding IDs within a run. When the same conclusion recurs, the
  dossier should reference the canonical finding instead of repeating the full
  paragraph.
- Suppress recursive duplicate child-summary blocks in the rendered dossier.
  Child context should appear once, then be referenced.
- Add an executive summary section for completed dossiers that states the
  highest-order answer first.
- Add a "headline conclusion" or "so what" field to synthesis output so the
  dossier does not force the reader to infer the lede.
- Track negative-result budgets. After a small number of independent
  confirmations that a fact is not disclosed, stop spawning further branches
  asking the same question and pivot to proxies or mark the gap as persistent.
- Distinguish evidence states:
  - directly disclosed
  - inferable from proxies
  - not disclosed in retrieved evidence
  - likely not publicly knowable
  - industry-standard opacity
  - anomalous/company-specific opacity
- Add source-tier conventions and use them in prompts/rendering:
  - Tier 1: filings, official investor materials, regulator/exchange documents
  - Tier 2: earnings transcripts and primary company communications
  - Tier 3: reputable analyst/research/news sources
  - Tier 4: industry blogs, generic explainers, aggregators, SEO pages
- Prevent low-tier sources from supporting high-tier claims unless clearly
  labeled as weak or corroborating evidence.
- Filter tautological findings. A finding should advance the analysis; generic
  definitions such as "LTV is projected customer revenue" should be background,
  not a key finding.
- Encourage proxy analysis when direct disclosure fails:
  - peer disclosures
  - third-party market share and spend surveys
  - capex-to-revenue ratios
  - pricing and seat-count sensitivity ranges
  - partner/channel data
  - customer case studies and workload migration costs
- Add a bounded uncertainty range where enough proxy evidence exists, with
  assumptions stated plainly.
- Add strategic/investment implication language to branch and dossier synthesis:
  what the evidence means, why it matters, and whether opacity appears neutral,
  favorable, or concerning.
- Tighten rendered prose:
  - shorter sentences
  - fewer passive constructions
  - less repeated hedging
  - clear separation between fact, inference, and missing evidence

Acceptance criteria:

- A deep recursive run does not repeat the same child-summary paragraph at
  every ancestor level.
- Placeholder branch synthesis text never appears in a completed dossier unless
  the configured model client truly lacks synthesis support and the limitation
  is clearly marked.
- The dossier begins with a concise executive conclusion and top findings.
- Repeated findings are rendered once with stable IDs and referenced elsewhere.
- The dossier clearly marks whether an evidence gap is normal industry opacity,
  company-specific opacity, or merely absent from the retrieved source set.
- The system stops re-investigating the same negative disclosure result after a
  configurable threshold and pivots to proxy analysis.
- Source tiers are visible enough that a reader can tell when a claim rests on
  filings versus weaker secondary material.
- Key findings contain non-trivial conclusions, not generic definitions.

## Milestone 6: Search-Backed Deep Dives

Connect real external research capability behind a narrow abstraction.

Scope:

- Implement a search provider interface.
- Add one concrete provider first: Brave Search-backed web retrieval.
- Keep local file retrieval through `DirectorySearchProvider` as the
  deterministic fixture and cached-source path.
- Pass search results into deep-dive calls in a structured way.
- Keep `searches_per_deepdive_target` as a soft prompt/config signal, not a hard orchestration loop.
- Record enough search metadata for traceability.
- Treat web search as discovery, not final authority. Prefer official company,
  regulator, exchange, filing, and investor-relations sources over generic web
  commentary.
- Preserve source timing:
  - `published_at` when the provider or page exposes it
  - `retrieved_at` for every fetched result
  - filing/report period when the source is a filing or annual report
- Add freshness controls so time-sensitive investigations do not silently rely
  on stale material.
- Chunk fetched pages before passing them to deep-dive, reusing the local
  chunking/ranking path where possible.

Acceptance criteria:

- Deep-dive prompts receive source material from the configured search provider.
- Search provider failures become node failures or retryable call failures according to config.
- Analyses are prompted to include inline source attribution for concrete factual claims.
- A fake search provider supports deterministic tests.
- Web-derived source material includes URL, title, source type, retrieval time,
  and publication/report date where available.
- Undated or stale web sources are clearly marked in the model context and
  should be treated as weaker evidence unless corroborated.
- A CLI run can opt into Brave-backed retrieval without changing the core
  orchestration path.

Suggested first CLI shape:

```text
research ollama-run "Company Name" \
  --model gemma4:latest \
  --web-search brave \
  --freshness-days 730 \
  --max-depth 1 \
  --max-total-nodes 3
```

Provider design notes:

- Keep provider names semantically distinct. Web search, filings, market data,
  and macro data are not interchangeable tools.
- Do not expose a single "do research" mega-provider. The orchestrator should
  know whether evidence came from web discovery, local filings, structured
  financial data, or macro time series.
- In the first version, let the orchestrator deterministically call the
  configured provider. Later, add an `EvidenceRouter` that selects among web,
  filings, market data, and macro providers based on the node topic and
  investigation brief.

### Milestone 6 Evolution: Document Retrieval as the Evidence Substrate

The first Brave-backed implementation proves useful discovery, but search
snippets should not become the long-lived evidence layer. Web search should
discover candidate documents; document retrieval should provide the material
that deep dives analyze.

Target architecture:

```text
node brief
  -> retrieve existing document chunks
  -> classify evidence sufficiency
  -> if insufficient, run web search for discovery
  -> fetch and ingest selected documents/articles/filings/transcripts
  -> chunk and index retrieved documents
  -> retrieve relevant chunks again
  -> deep dive on document chunks, not search snippets
```

Boundary changes:

- Keep SQLite as the durable run ledger:
  - runs
  - nodes
  - model calls
  - source usage provenance
  - document IDs and chunk IDs used by a node
- Do not reimplement a full document retrieval stack just to keep everything in
  SQLite.
- Add a `RetrievalProvider` boundary that can be backed by an existing tool
  such as LlamaIndex, Chroma, Qdrant, LanceDB, or another document/indexing
  system.
- Keep Brave Search as a discovery provider, not the final evidence provider.
- Store enough provenance in SQLite to reproduce why a node saw a given chunk,
  even if the actual document index lives outside SQLite.

Suggested provider shape:

```python
class RetrievalProvider(Protocol):
    def retrieve(
        self,
        *,
        company: str,
        query: str,
        max_chunks: int,
    ) -> list[SourceMaterial]:
        ...

    def ingest_url(
        self,
        *,
        url: str,
        source_hint: str | None = None,
    ) -> DocumentRef:
        ...
```

Evidence sufficiency should become an explicit orchestration step. The worker
should not blindly deep-dive on whatever chunks happen to be retrieved. Before
the deep-dive call, run a deterministic and/or model-backed sufficiency check
over the investigation brief and retrieved chunk summaries.

Suggested sufficiency schema:

```json
{
  "sufficient": false,
  "coverage": "partial",
  "missing_evidence": [
    "No source quantifies Copilot attach rates.",
    "No source explains OpenAI contract economics."
  ],
  "recommended_searches": [
    "Microsoft Copilot paid seats revenue attach rate earnings transcript",
    "Microsoft OpenAI partnership economics annual report"
  ],
  "reasoning": "The chunks cover management strategy but not unit economics."
}
```

Deterministic sufficiency heuristics can run before the model classifier:

- Count distinct documents and publishers.
- Prefer at least one primary or official source for public-company claims.
- Check whether source dates are present and within freshness requirements.
- Check whether retrieved chunks cover the key evidence targets in the brief.
- Flag weak evidence if all chunks are snippets, generic marketing pages, or
  undated secondary commentary.

Acceptance criteria:

- A node first attempts retrieval from the local document index before running
  new web searches.
- Search results can be ingested as documents and later reused by other nodes
  or future runs.
- Repeated runs for the same company avoid rediscovering the same source URLs
  unless freshness policy requires refetching.
- Deep-dive source materials are document chunks with title, URL, publication
  or report date, retrieval time, and chunk provenance.
- The audit or model-call log records whether the evidence set was considered
  sufficient, partial, or insufficient before deep dive.
- If evidence is insufficient, the system either expands retrieval/search or
  explicitly tells the deep-dive model that the evidence is partial.
- Dossier source references can be traced back to actual documents/chunks,
  not just Brave result snippets.

### Milestone 6B: Sidecar Corpus Builder / Evidence Seeder

The recursive worker should not have to discover every relevant document during
an interactive run. Add a separate corpus-building lane that can run before,
after, or alongside investigations and seed the document repository with likely
useful evidence.

This process is intentionally outside the core recursive tool loop. It can run
slowly, broadly, and opportunistically without consuming investigation node
budget or forcing the model to reason over weak search snippets.

Responsibilities:

- Given a company name and optional ticker, discover and ingest likely useful
  documents:
  - annual reports and 10-Ks
  - 10-Qs and interim reports
  - earnings call transcripts
  - investor presentations
  - proxy filings
  - investor-relations pages
  - product and technical documentation
  - reputable journalism and industry analysis
  - competitor filings and relevant market reports
- Fetch, parse, normalize, deduplicate, date, and chunk documents.
- Add first-class PDF ingestion for both sidecar corpus seeding and
  `DirectorySearchProvider` local-source runs:
  - accept `.pdf` files in local/company evidence directories
  - extract readable text with a lightweight parser such as `pypdf`
  - preserve page boundaries in the extracted text using markers such as
    `[Page 12]`
  - feed extracted PDF text into the existing chunking pipeline so the LLM sees
    ordinary text chunks rather than binary files
  - if a PDF yields no usable text, skip it with a visible parser-status note
    rather than failing the whole ingestion job
  - defer OCR and layout-aware/table reconstruction to a later milestone
- Persist document metadata and provenance:
  - canonical URL
  - title
  - publisher/source
  - source type
  - published/report period
  - retrieved time
  - content hash
  - fetch status and parser status
- Write chunks into the configured retrieval/indexing backend.
- Record enough metadata in SQLite or a metadata store for auditability.
- Refresh stale documents according to source type and freshness policy.

Suggested CLI shape:

```text
research seed-corpus "Microsoft" \
  --ticker MSFT \
  --years 5 \
  --sources filings,earnings,investor,web \
  --web-search brave
```

Alternative implementation shape:

```text
python tools/seed_corpus.py MSFT --years 5
```

The final interface can live inside the `research` CLI or as a separate
maintenance tool. The important boundary is behavioral: corpus seeding enriches
the evidence repository, while `ollama-run` consumes and extends it.

Target run flow after this exists:

```text
seed-corpus builds a company evidence base
  -> recursive run retrieves from corpus first
  -> evidence sufficiency gate decides whether more discovery is needed
  -> runtime search discovers missing sources only when needed
  -> newly discovered documents are ingested back into the corpus
```

Acceptance criteria:

- A user can seed a company corpus without starting a recursive run.
- Seeded documents are reusable across later runs for the same company.
- Duplicate URLs or duplicate content hashes do not create duplicate evidence
  documents.
- A user can place digital PDFs into `source-dir` and have them become readable
  chunked source material for deep-dives.
- Extracted PDF text preserves page markers so dossier claims can be traced back
  to approximate page locations even before richer citation machinery exists.
- PDFs with no extractable text are reported as skipped/weakly parsed rather
  than silently ignored.
- Corpus metadata records source timing and retrieval timing.
- A run can report whether it used pre-seeded corpus evidence, runtime-discovered
  evidence, or both.
- The sidecar can be run repeatedly to refresh or extend the corpus without
  corrupting prior provenance.

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

## Current Status Checkpoint

Last refreshed: 2026-05-10.

Use this section as the living checkpoint when returning to the project. Update
the date, the tested command set, and the "next checkpoint" notes whenever a
meaningful capability lands.

### Working Capabilities

Core backend:

- Python package, `pyproject.toml`, CLI entry points, and automated test suite.
- SQLite-backed run ledger for:
  - runs
  - nodes
  - node events
  - model calls
  - node failures
  - node rejections
  - node references
- FSM-based node lifecycle with persisted transitions.
- Startup recovery for transitional node states before resume/continuation.
- First-class `research resume <run_id>` path.
- Explicit wall-clock stop budget for resumable partial runs.
- Per-node failure isolation:
  - node failures are recorded
  - failed children do not block sibling completion
  - failed children are visible in audit/dossier output
- Continuous audit regeneration during run progress.
- Dossier rendering for completed/failed/reference branches.

Model boundary:

- Deterministic `FakeModelClient` for offline tests.
- Ollama-backed structured calls for:
  - scope
  - search planning
  - deep dive
  - reflection
- OpenRouter-backed structured calls for:
  - scope
  - search planning
  - deep dive
  - reflection
- Ollama keep-alive defaults to `5m`.
- Provider-neutral model boundary across:
  - `FakeModelClient`
  - `OllamaModelClient`
  - `OpenRouterModelClient`
- Structured-output hardening for hosted models includes:
  - retry on invalid JSON / schema-shape failures
  - parsing of fenced JSON blocks
  - parsing of JSON embedded in surrounding prose
- Sibling-consolidation structured output is implemented at the model boundary
  and consumed by orchestration before child-node creation.
- Model-call instrumentation includes:
  - timestamped CLI progress logs
  - Ollama load/total/eval metadata when available
  - OpenRouter provider/model/finish/token/cost metadata when available
  - `research model-calls <run_id>` summary
  - `research model-call <call_id>` inspection
  - `--raw` model-call output for prompt debugging
- Failed structured model calls persist raw response text when available.

Prompt/schema state:

- Scope output is structured.
- Search-plan output is structured and asks for several narrow source-seeking
  queries rather than one broad copied brief.
- Deep-dive output now uses structured JSON sections instead of one large
  freeform `analysis` blob:
  - `core_question`
  - `source_assessment`
  - `key_findings`
  - `evidence_gaps`
  - `conclusion`
  - `abstract`
  - `contradictions`
  - `discovered_threads`
- The rendered node analysis is derived from those fields.
- Completion sentinels are no longer part of the deep-dive model contract.
- Reflection still operates over the rendered analysis text.

Search and evidence:

- `DirectorySearchProvider` supports deterministic local/source-fixture runs.
- `BraveSearchProvider` supports real web discovery.
- `TavilySearchProvider` supports real web discovery through an alternative
  provider path.
- `CompositeSearchProvider` can combine configured sources.
- Search planning is model-guided but bounded by CLI/config limits.
- Web source material carries URL, title, source type, retrieval time,
  publication/page-age metadata where available, and staleness notes.
- Brave query length is guarded before API calls.
- Search progress is logged at a high level during real-model runs.

CLI surface:

- `research init-db`
- `research run` / `research fake-run`
- `research resume`
- `research render`
- `research audit`
- `research model-calls`
- `research model-call`
- Ollama smoke/scope/deep-dive/reflect commands
- `research ollama-run` with:
  - local source directory
  - Brave web search
  - Tavily web search
  - freshness window
  - search result limit
  - planned search query limit
  - max depth
  - max total nodes
  - timeout and keep-alive controls
- `research openrouter-run` with the same search/orchestration path and
  provider-specific API key/model controls

### Recent Real-Model Observations

- Brave-backed Microsoft runs complete successfully with Gemma/Ollama.
- Structured deep-dive sections substantially improved output stability:
  - no sentinel artifacts
  - no observed dangling future-plan endings in the latest run
  - cleaner dossier sections for source assessment, findings, gaps, and
    conclusion
- Branch-synthesis placeholder text no longer appears in completed dossiers.
  Real model clients now fall back to a deterministic branch-capture block
  rather than emitting literal placeholder scaffolding.
- Evidence quality is now the main bottleneck. Search snippets and generic web
  pages are not a strong enough evidence substrate for deeper reports.
- `--search-results 3` is useful for smoke tests but often too sparse for real
  analysis. `6` to `8` is a better starting range.
- Recursion depth only matters when `--max-total-nodes` leaves room beyond the
  root nodes created by scope. A future `--max-root-nodes` control would make
  this easier to manage.
- A much deeper Microsoft run showed that deeper recursion currently creates
  too much duplicated structure:
  - parent sections still over-preserve nested child capture
  - child summaries are repeated at multiple ancestor levels
  - many branches reconfirm the same "not disclosed" result
  - the most important conclusion is buried rather than stated upfront
  - weak source tiers can appear beside primary sources without enough
    weighting distinction
- New Greencoat runs confirm the same pattern: output cleanliness is better,
  but dossier quality is now primarily limited by duplicate suppression,
  provenance visibility, and the absence of canonical findings / negative-result
  controls.

### Known Gaps

Execution/model:

- Branch synthesis is still a deterministic fallback rather than a true
  parent-level interpretive synthesis call.
- Model-native tools, including OpenRouter web/search tools, are not integrated
  and should remain outside the default evidence path until their outputs can
  be normalized into auditable `SourceMaterial` records.
- Retry policy is still simple. Failed nodes are isolated, but there is no
  configurable retry/backoff policy per provider or call type.
- Model-call records capture call input payloads, but not always the fully
  rendered final prompt string as sent to Ollama.

Dossier assembly and analysis quality:

- Completed dossiers still render the tree too literally.
- Parent branch sections still do not provide real cross-child interpretation;
  they use branch-capture fallback text instead.
- Repeated child summaries are duplicated across ancestor levels.
- There is no executive conclusion or reader-first headline section.
- Repeated negative findings are not collapsed into canonical findings.
- The system does not yet distinguish "not disclosed in retrieved evidence"
  from "likely not publicly knowable" or "normal industry opacity."
- No source-tier policy is visible in rendered findings.
- The worker does not yet pivot to proxy analysis after direct-disclosure
  searches fail repeatedly.
- There is no output-boundary cleanup pass yet for minor generation defects
  such as truncation or obvious prose errors.

Evidence/retrieval:

- Search results are still treated as immediate `SourceMaterial`; real document
  fetching/extraction/chunking is not implemented.
- No durable document corpus exists yet.
- No retrieval provider exists over a reusable document/chunk index.
- No explicit evidence sufficiency gate exists before deep dive.
- Dossier output cites `Source 1`, `Source 2`, etc., but does not yet render a
  per-node source appendix showing title, URL, date, retrieval time, and source
  date basis.

Memory/dedup:

- Findings extraction exists at the model boundary, but extracted findings are
  not yet stored or retrieved.
- Deduplication and reference-node behavior are partially active:
  same-run reference nodes are persisted and rendered, and sibling
  consolidation now reduces obvious overlap before child creation.
- Canonical finding IDs, negative-result budgets, and cross-branch duplicate
  suppression are not implemented.
- Circularity arbitration is defined in schemas/fake model but not integrated
  into live child-candidate processing.
- Persistent uncertainties are defined but not integrated.

Product/frontend:

- No Flutter-facing API/control surface yet.
- CLI remains the only active control interface.

### Practical Milestone Assessment

- Milestone 0: complete.
- Milestone 1: mostly complete.
- Milestone 2: complete, with deep-dive schema evolved beyond the original
  prose-blob design.
- Milestone 3: mostly complete for scope/search-plan/deep-dive/reflect; branch
  synthesis remains fallback-only rather than real synthesis.
- Milestone 3B: mostly complete. OpenRouter is implemented as a hosted provider
  without changing the search/retrieval evidence path, though native-tool
  integration remains intentionally disabled.
- Milestone 4: mostly complete for current recursive worker behavior.
- Milestone 5: mostly complete for markdown artifacts and live audit progress.
- Milestone 5B: partially complete. Placeholder scaffolding is gone, but deep
  runs still need real synthesis, canonical findings, duplicate suppression,
  source-tier weighting, provenance rendering, and negative-result/proxy-
  analysis controls.
- Milestone 6: partially complete:
  - Brave discovery exists
  - Tavily discovery exists
  - source timing metadata exists
  - document retrieval/corpus architecture is not implemented yet
- Milestones 7-13: mostly not implemented, except for schema/table/rendering
  groundwork in a few areas.

### Next Checkpoint Goals

The next meaningful refresh should happen after one of these lands:

1. Source appendix rendering for dossier/audit.
2. Real branch synthesis and duplicate child-summary suppression.
3. Canonical finding IDs and negative-result budget.
4. `--max-root-nodes` or equivalent topology control.
5. Document retrieval/corpus provider design spike.
6. Sidecar `seed-corpus` prototype.
7. Evidence sufficiency classifier/gate.
8. Output-boundary cleanup for truncation / obvious prose defects.

Current recommended implementation direction:

1. Add source appendix/provenance rendering so dossier claims are inspectable.
2. Replace branch-capture fallback with real branch synthesis and stop repeated
   child-summary rendering.
3. Add canonical finding IDs plus a negative-result budget so the worker stops
   re-asking exhausted disclosure questions.
4. Add topology controls so deeper runs can reserve node budget for recursion.
5. Add an output cleanup pass for truncation and obvious prose defects without
   changing substantive capture.
6. Move from search snippets to document ingestion/retrieval.
7. Add sidecar corpus seeding for company evidence libraries.
8. Add an evidence sufficiency decision before deep-dive.

## Concrete Backlog

This backlog is the remaining high-value work from the roadmap. Items already
landed in the current checkpoint should be treated as done and left here only
if they still need hardening or follow-through.

### Priority 1: Harden the Vertical Slice Operationally

These items improve resilience and control on top of an already-working
recursive worker.

1. Add configurable retry/backoff policy per provider and call type.
   - Distinguish transient provider failures from deterministic validation
     failures.
   - Allow different retry policies for Ollama, OpenRouter, and search
     providers.
   - Persist retry attempts clearly enough for audit/debugging.

2. Persist the fully rendered final prompt string when useful for debugging.
   - Keep existing structured input payload persistence.
   - Add optional storage of the final rendered prompt text for targeted call
     types where prompt debugging matters most.
   - Avoid exploding storage unnecessarily for every call by default.

3. Add topology controls that make recursion easier to reason about.
   - Implement `--max-root-nodes` or equivalent.
   - Make it easier to reserve node budget for deeper recursion rather than
     spending most of the budget at scope.
   - Add tests showing depth interacts predictably with node-budget controls.

### Priority 2: Make Deep Dossiers Readable and Analytical

These items convert deeper runs from tree dumps into reader-first research
artifacts.

6. Replace placeholder branch synthesis.
   - Add a synthesis prompt and a structured or plain-text contract.
   - Record synthesis calls in `model_calls` the same way other calls are
     recorded.
   - Require parent synthesis to add interpretation across children, not just
     concatenate summaries.
   - Add tests proving placeholder text does not appear in completed dossiers
     when a synthesis-capable model client is used.

7. Suppress recursive child-summary duplication in dossier rendering.
   - Render each substantive node analysis once.
   - Let ancestors reference child nodes or canonical finding IDs rather than
     repeating full child abstracts.
   - Add tests against a multi-level tree where the same child summary would
     otherwise appear at several depths.

8. Add an executive conclusion and canonical findings section.
   - State the lede upfront.
   - Include confidence and evidence quality.
   - Include strategic or investment implication.
   - Assign stable finding IDs within a run and reference them from branch
     sections.

9. Add negative-result budgets and proxy-analysis pivots.
   - Stop re-asking the same direct-disclosure question after a configurable
     number of independent negative confirmations.
   - Mark the gap as normal industry opacity, company-specific opacity, not
     retrieved, or likely not publicly knowable.
   - Spawn or recommend proxy investigations when direct disclosure fails.

10. Add source-tier weighting and finding filters.
    - Classify source tiers in prompts/rendering.
    - Prevent weak sources from carrying high-confidence claims without a clear
      caveat.
    - Filter tautological findings out of key findings.

### Priority 3: Complete the Real-Model and Evidence Path

These items make the live model/search path less of a smoke path and more of a
usable research path.

11. Upgrade external search from snippet discovery to fetched/chunked evidence.
   - Keep Brave and Tavily as discovery providers behind `SearchProvider`.
   - Fetch selected pages/documents rather than passing only result snippets.
   - Chunk fetched content before deep-dive, reusing a future retrieval layer
     where possible.
   - Preserve URL, title, source type, retrieval time, and publication/report
     date metadata through the fetch/chunk path.
   - Preserve `DirectorySearchProvider` as a deterministic local test source and
     cached-filing path.

12. Decide and document source trace behavior.
   - Define what search metadata belongs in the database.
   - Ensure deep-dive prompts receive source material in a stable, debuggable
     structure.
   - Add tests for provider failure handling.
   - Make stale or undated sources visible in both prompt context and audit
     output.

13. Harden OpenRouter parity and provider observability.
   - Keep `OpenRouterModelClient` behind the same research model protocol as
     Ollama and the fake client.
   - Continue improving structured-output robustness and metadata persistence.
   - Ensure provider-specific failures are clearly distinguishable in
     `model_calls`.
   - Keep OpenRouter-native search/tools disabled by default; use Brave,
     Tavily, corpus, filings, or retrieval providers for evidence.
   - If OpenRouter-native tools are later enabled, convert every returned tool
     result into normal source/document provenance before it reaches deep-dive.

### Priority 4: Finish the Unused Persistence Surfaces

These items wire already-designed tables and schemas into real behavior.

14. Implement live writes for `node_rejections`.
   - Use them when circularity arbitration rejects a candidate.
   - Render rejection reasons in audit output.

15. Implement live writes for `node_references`.
    - Mark duplicate investigations as reference nodes.
    - Increment canonical reference counts.
    - Surface canonical context in synthesis and rendering.

16. Confirm `node_failures` usage and retry policy.
    - Decide whether failures are terminal in v1 or retryable.
    - Record failure attempts consistently.
    - Expose failure history in CLI or audit output.

### Priority 5: Add Memory Only After the Core Loop Is Stable

These items should come after the run lifecycle is resilient and observable.

17. Implement findings storage in SQLite.
    - Add `findings` table and FTS5 index.
    - Persist extracted findings after successful deep-dives.
    - Treat extraction failures as non-fatal.

18. Add retrieval of prior same-company findings.
    - Query by company plus structured fields and FTS.
    - Pass retrieved findings to deep-dive prompts as leads, not facts.

19. Add vector retrieval later, only once enough stored findings exist to
    judge quality.

### Priority 6: Add Topology Controls

These items improve recursive quality after the worker is durable.

20. Implement within-run deduplication.
21. Implement circularity arbitration against ancestors.
22. Implement persistent uncertainties.

### Priority 7: Prepare the Frontend Boundary

23. Add a backend control surface for:
    - create run
    - resume run
    - pause or stop run
    - list runs
    - inspect node tree
    - read audit and dossier artifacts

24. Keep the CLI as a first-class client of the same storage-backed backend.

## Recommended Next Implementation Chunk

If work resumes immediately, the best next chunk is:

1. source appendix/provenance rendering
2. real branch synthesis
3. duplicate child-summary suppression
4. executive conclusion plus canonical findings
5. negative-result budget and proxy-analysis pivot

That sequence addresses the current failure mode from deep runs: the worker can
find many related gaps, but the dossier does not yet compress them into a clear
argument.
