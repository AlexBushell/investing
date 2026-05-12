# Recursive Research Agent

Python backend for a recursive adversarial research system.

The system treats research as a durable investigation tree:

- a run starts with root investigation threads
- each node is deep-dived
- the analysis is reflected into child threads
- the worker continues until no material unresolved work remains
- progress and results are written to SQLite and markdown artifacts

The backend is designed around:

- SQLite as the source of truth
- stateless model calls
- inspectable audit and dossier outputs
- resumable execution

For the detailed product/spec view, see
[`recursive_research_spec.md`](./recursive_research_spec.md). For current
status and next implementation steps, see
[`implementation_roadmap.md`](./implementation_roadmap.md).

## Repo Layout

```text
recursive_research_agent/
  app/
    cli.py
    db.py
    fsm.py
    llm.py
    orchestrator.py
    prompts.py
    render.py
    schemas.py
    search.py
  tests/
  outputs/
  data/
  recursive_research_spec.md
  implementation_roadmap.md
  AGENTS.md
```

## Requirements

- Python 3.11+

Install the package and dev tools from the repo root:

```powershell
python -m pip install -e .[dev]
```

If you are using the local virtual environment in this repo:

```powershell
.venv\Scripts\python.exe -m pip install -e .[dev]
```

## Quick Start

If you are on PowerShell, the fastest way to use the repo is via:

```powershell
.\dev.ps1 help
```

If you are on Git Bash, use:

```bash
./dev.sh help
```

These scripts wrap the most common test and CLI commands so you do not need to
retype long Python invocations.

## Settings Profiles

The repo now includes a profile file at `research.toml`.

Profiles let you keep most run settings out of the command line and only pass:

- the command
- the company
- the model
- the profile

Examples:

```bash
./dev.sh ollama-run "Microsoft" --profile ollama_local --model gemma4:latest
./dev.sh openrouter-run "Microsoft" --profile openrouter_fast --model openai/gpt-4.1
./dev.sh openrouter-run "Microsoft" --profile openrouter_deep --model anthropic/claude-sonnet-4.5
```

CLI flags still override profile values, so you can do things like:

```bash
./dev.sh openrouter-run "Microsoft" --profile openrouter_deep --model openai/gpt-4.1 --max-depth 2
```

Use a custom settings file if needed:

```bash
./dev.sh openrouter-run "Microsoft" --profile myprofile --settings-file my-research.toml --model openai/gpt-4.1
```

Initialize the database:

```powershell
.\dev.ps1 init-db
```

Equivalent raw command:

```powershell
.venv\Scripts\python.exe -m app.cli init-db
```

Run a fake-model research pass:

```powershell
.\dev.ps1 run "Example Company"
```

Equivalent raw command:

```powershell
.venv\Scripts\python.exe -m app.cli run "Example Company"
```

Resume a run:

```powershell
.\dev.ps1 resume <run_id>
```

Equivalent raw command:

```powershell
.venv\Scripts\python.exe -m app.cli resume <run_id>
```

Render artifacts for an existing run:

```powershell
.\dev.ps1 audit <run_id>
.\dev.ps1 render <run_id>
```

Equivalent raw commands:

```powershell
.venv\Scripts\python.exe -m app.cli audit <run_id>
.venv\Scripts\python.exe -m app.cli render <run_id>
```

Typical output paths:

- `data/research.sqlite`
- `outputs/runs/<run_id>/audit.md`
- `outputs/runs/<run_id>/dossier.md`

## Real-Model Runs

### Ollama

Smoke test structured output:

```powershell
.\dev.ps1 ollama-smoke
```

Equivalent raw command:

```powershell
.venv\Scripts\python.exe -m app.cli ollama-smoke
```

Run a guarded recursive pass with Ollama:

```powershell
.\dev.ps1 ollama-run "Example Company" --web-search brave
```

Equivalent raw command:

```powershell
.venv\Scripts\python.exe -m app.cli ollama-run "Example Company" --web-search brave
```

Useful options:

- `--source-dir <dir>`
- `--web-search brave`
- `--web-search tavily`
- `--search-results 6`
- `--search-queries 4`
- `--max-depth 2`
- `--max-total-nodes 6`

### OpenRouter

Run with OpenRouter:

```powershell
.\dev.ps1 openrouter-run "Example Company" `
  --model openai/gpt-4.1 `
  --openrouter-api-key <key> `
  --web-search brave
```

Equivalent raw command:

```powershell
.venv\Scripts\python.exe -m app.cli openrouter-run "Example Company" `
  --model openai/gpt-4.1 `
  --openrouter-api-key <key> `
  --web-search brave
```

`OPENROUTER_API_KEY` can also be supplied through the environment.

## CLI Surface

Core commands:

- `research init-db`
- `research run`
- `research resume`
- `research render`
- `research audit`
- `research run-summary`
- `research model-calls`
- `research model-call`
- `research ollama-run`
- `research openrouter-run`

Parser help:

```powershell
.venv\Scripts\python.exe -m app.cli --help
```

Or after editable install:

```powershell
research --help
```

## Inspecting Runs

Print a compact run overview:

```powershell
.venv\Scripts\python.exe -m app.cli run-summary <run_id>
```

Summarize model calls for a run:

```powershell
.venv\Scripts\python.exe -m app.cli model-calls <run_id>
```

Inspect one model call in detail:

```powershell
.venv\Scripts\python.exe -m app.cli model-call <call_id>
.venv\Scripts\python.exe -m app.cli model-call <call_id> --raw
```

These are useful when debugging:

- prompt/schema mismatches
- provider-specific failures
- structured-output parsing issues
- dossier artifacts that look wrong

## Testing

Shortest common commands:

```powershell
.\dev.ps1 test
.\dev.ps1 test-llm
.\dev.ps1 test-orch
.\dev.ps1 test-search
.\dev.ps1 test-cli
```

Git Bash equivalents:

```bash
./dev.sh test
./dev.sh test-llm
./dev.sh test-orch
./dev.sh test-search
./dev.sh test-cli
```

Run the full suite:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

Common targeted runs:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_llm.py -q
.venv\Scripts\python.exe -m pytest tests\test_orchestrator.py tests\test_render.py -q
.venv\Scripts\python.exe -m pytest tests\test_search.py tests\test_cli.py -q
```

Test map:

- `tests/test_fsm.py`: lifecycle transitions
- `tests/test_db.py`: persistence and recovery
- `tests/test_schemas.py`: structured contracts
- `tests/test_prompts.py`: prompt helpers
- `tests/test_llm.py`: fake/Ollama/OpenRouter clients
- `tests/test_search.py`: search providers
- `tests/test_orchestrator.py`: worker behavior
- `tests/test_render.py`: audit/dossier rendering
- `tests/test_cli.py`: command wiring

## Current State

What already works well:

- resumable SQLite-backed run state
- fake model path for deterministic tests
- Ollama and OpenRouter model providers
- directory, Brave, and Tavily source discovery
- audit and dossier artifact generation
- model-call persistence and inspection

What is still the main frontier:

- source appendix / provenance rendering
- real branch synthesis instead of fallback branch capture
- duplicate child-summary suppression
- canonical findings and negative-result budgets
- moving from search snippets to fetched/chunked evidence

See the current checkpoint in
[`implementation_roadmap.md`](./implementation_roadmap.md) for the live
project status.

## Development Notes

- `AGENTS.md` is the repo-local operating guide for coding agents.
- `dev.ps1` and `dev.sh` are the fastest local task runners for day-to-day
  development.
- Output wording is product behavior in this repo, not just presentation.
- Keep prompts, schemas, model clients, rendering, and tests in sync when
  changing structured outputs.
