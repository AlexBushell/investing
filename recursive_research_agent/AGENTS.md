# AGENTS.md

This file is the repo-local operating guide for Codex and other coding agents.
It is intentionally practical. For architecture and product intent, read
`recursive_research_spec.md` and `implementation_roadmap.md`.

## Purpose

This project is a Python backend for a recursive research system. The center of
the system is:

- SQLite as the durable run ledger
- stateless model calls
- a serial orchestrator that advances node lifecycle state
- markdown artifacts (`audit.md`, `dossier.md`) as the primary inspection
  surface

When making changes, preserve those core invariants unless the task explicitly
requires changing them.

## Fast Orientation

Main code paths:

- `app/cli.py`: command entry points and run wiring
- `app/orchestrator.py`: recursive worker lifecycle
- `app/db.py`: SQLite schema and persistence
- `app/llm.py`: fake/Ollama/OpenRouter model boundary
- `app/prompts.py`: structured prompt contracts
- `app/search.py`: directory/web search providers
- `app/render.py`: audit/dossier markdown rendering
- `app/schemas.py`: structured outputs and enums
- `app/fsm.py`: node lifecycle transitions

Primary docs:

- `recursive_research_spec.md`: behavioral spec
- `implementation_roadmap.md`: milestone plan and current checkpoint
- `docs/prompting_principles.md`: prompt-design guidance
- `research.toml`: local run profiles for common model/search/depth settings

## Working Style For Agents

Prefer small, behavior-preserving changes unless the task clearly asks for a
larger refactor.

Before editing:

- identify the relevant layer first: `db`, `fsm`, `orchestrator`, `llm`,
  `search`, `render`, `cli`, or `schemas`
- check whether a similar pattern already exists in adjacent code
- keep prompt/schema/orchestrator contracts aligned

After editing:

- run the smallest relevant test subset first
- only broaden to more tests when the change crosses boundaries
- mention any behavior you could not verify

Do not treat dossier wording changes as cosmetic. In this repo, output shape is
product behavior.

## What "Done" Usually Means

A change is usually not done until it includes all of the following that apply:

- code change in the correct layer
- tests for the affected behavior
- prompt/schema updates if the contract changed
- rendering updates if persisted data shape changed
- roadmap/checkpoint update if the project status materially changed

## Safe Defaults

When in doubt:

- keep model calls stateless
- keep SQLite as the source of truth
- prefer explicit persisted metadata over hidden in-memory behavior
- prefer deterministic fallbacks over silent failure
- preserve comprehensive capture in dossiers; do not over-compress unless asked

## Current Priorities

As of the current roadmap checkpoint, the highest-value open areas are:

1. source appendix / provenance rendering
2. real branch synthesis instead of branch-capture fallback
3. duplicate child-summary suppression across ancestors
4. canonical findings and negative-result budgets
5. light output cleanup for truncation / obvious prose defects
6. moving from search snippets to fetched/chunked evidence

Avoid broad unrelated refactors unless they directly help one of those areas.

## Commands

Environment:

- Python: `>=3.11`
- package entry point: `research`

Common local commands:

```powershell
.\dev.ps1 help
.\dev.ps1 test
.\dev.ps1 test-llm
.\dev.ps1 test-orch
.\dev.ps1 init-db
.\dev.ps1 run "Example Company"
.\dev.ps1 resume <run_id>
.\dev.ps1 render <run_id>
.\dev.ps1 audit <run_id>
```

Git Bash equivalents:

```bash
./dev.sh help
./dev.sh test
./dev.sh test-llm
./dev.sh test-orch
./dev.sh init-db
./dev.sh run "Example Company"
./dev.sh resume <run_id>
./dev.sh render <run_id>
./dev.sh audit <run_id>
```

Equivalent raw commands:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m pytest tests\test_llm.py -q
.venv\Scripts\python.exe -m pytest tests\test_orchestrator.py tests\test_render.py -q
.venv\Scripts\python.exe -m app.cli init-db
.venv\Scripts\python.exe -m app.cli run "Example Company"
.venv\Scripts\python.exe -m app.cli resume <run_id>
.venv\Scripts\python.exe -m app.cli render <run_id>
.venv\Scripts\python.exe -m app.cli audit <run_id>
```

Real-model runs:

```powershell
.\dev.ps1 ollama-run "Example Company" --web-search brave
.\dev.ps1 openrouter-run "Example Company" --model <provider/model> --openrouter-api-key <key>
```

Git Bash equivalents:

```bash
./dev.sh ollama-run "Example Company" --web-search brave
./dev.sh openrouter-run "Example Company" --model <provider/model> --openrouter-api-key <key>
```

Equivalent raw commands:

```powershell
.venv\Scripts\python.exe -m app.cli ollama-run "Example Company" --web-search brave
.venv\Scripts\python.exe -m app.cli openrouter-run "Example Company" --model <provider/model> --openrouter-api-key <key>
```

Model-call inspection:

```powershell
.venv\Scripts\python.exe -m app.cli model-calls <run_id>
.venv\Scripts\python.exe -m app.cli model-call <call_id> --raw
```

## Test Map

Use the smallest relevant test file first.

- `tests/test_fsm.py`: lifecycle transitions
- `tests/test_db.py`: persistence and recovery behavior
- `tests/test_schemas.py`: Pydantic contracts and enum rules
- `tests/test_prompts.py`: prompt text helpers
- `tests/test_llm.py`: fake/Ollama/OpenRouter behavior and structured parsing
- `tests/test_search.py`: directory/Brave/Tavily search providers
- `tests/test_orchestrator.py`: worker flow, spawning, synthesis readiness,
  dedup/reference behavior
- `tests/test_render.py`: audit/dossier markdown rendering
- `tests/test_cli.py`: command wiring and end-to-end CLI behavior

Suggested validation by change type:

- `schemas` or prompt contract changes:
  - `tests/test_schemas.py`
  - `tests/test_llm.py`
- orchestrator lifecycle changes:
  - `tests/test_orchestrator.py`
  - `tests/test_render.py`
  - `tests/test_cli.py` if CLI-visible
- rendering-only changes:
  - `tests/test_render.py`
- search-provider changes:
  - `tests/test_search.py`
  - `tests/test_cli.py`
- CLI argument changes:
  - `tests/test_cli.py`

## Repo-Specific Cautions

1. Keep prompts, schemas, and tests in sync.
   If you change a structured output shape in `schemas.py`, you will often also
   need changes in `prompts.py`, `llm.py`, and tests.

2. Rendering is coupled to persisted node fields.
   If you change how `analysis`, `abstract`, `branch_synthesis`, references, or
   failures are stored, check `render.py` and dossier/audit tests.

3. The fake model is not just a stub.
   It is a key test harness. If you add a model capability, consider whether
   `FakeModelClient` should support it in a deterministic way.

4. Search and evidence are not the same thing.
   Web search currently provides source material directly, but the roadmap aims
   to move toward fetched/chunked document evidence. Avoid baking snippet-only
   assumptions deeper into the architecture.

5. Reference nodes are reader-facing behavior.
   Avoid changes that accidentally duplicate full analyses when reference-node
   behavior should keep the dossier compact.

6. "Comprehensive capture" matters.
   The dossier should preserve branch-specific evidence and gaps. Do not turn it
   into a heavily compressed executive summary unless the task explicitly asks
   for that.

## Good First Questions For Agents

Before implementing, it often helps to ask:

- Is this a persistence change, a contract change, or just a rendering change?
- Does this alter run behavior, dossier wording, or both?
- What is the smallest test file that should fail before the fix?
- Does the roadmap checkpoint need updating after this lands?

## If You Only Read One More File

Read `implementation_roadmap.md`, especially the current checkpoint and next
implementation chunk. That is the best short view of where the project is and
what matters next.
