#!/usr/bin/env bash

set -euo pipefail

task="${1:-help}"
if [[ $# -gt 0 ]]; then
  shift
fi

python_exe() {
  if [[ -x ".venv/Scripts/python.exe" ]]; then
    printf '%s\n' ".venv/Scripts/python.exe"
  else
    printf '%s\n' "python"
  fi
}

run_python() {
  local py
  py="$(python_exe)"
  "$py" "$@"
}

run_pytest() {
  run_python -m pytest "$@"
}

run_research() {
  run_python -m app.cli "$@"
}

show_help() {
  cat <<'EOF'
Developer workflow shortcuts

Usage:
  ./dev.sh <task> [args...]

Common tasks:
  help                 Show this message
  test                 Run full test suite
  test-llm             Run llm tests
  test-orch            Run orchestrator + render tests
  test-search          Run search + cli tests
  test-cli             Run cli tests
  lint                 Run ruff
  init-db              Initialize SQLite database
  run <company>        Run fake-model research
  resume <run_id>      Resume fake-model run
  render <run_id>      Render dossier for a run
  audit <run_id>       Render audit for a run
  model-calls <run_id> Summarize model calls
  model-call <call_id> Inspect one model call
  ollama-smoke         Smoke-test Ollama structured output
  ollama-run ...       Pass through to app.cli ollama-run
  openrouter-run ...   Pass through to app.cli openrouter-run

Examples:
  ./dev.sh test-llm
  ./dev.sh run "Example Company"
  ./dev.sh ollama-run "Microsoft" --profile ollama_local --model gemma4:latest
  ./dev.sh openrouter-run "Microsoft" --profile openrouter_fast --model openai/gpt-4.1
EOF
}

case "${task,,}" in
  help)
    show_help
    ;;
  test)
    run_pytest tests -q "$@"
    ;;
  test-llm)
    run_pytest tests/test_llm.py -q "$@"
    ;;
  test-orch)
    run_pytest tests/test_orchestrator.py tests/test_render.py -q "$@"
    ;;
  test-search)
    run_pytest tests/test_search.py tests/test_cli.py -q "$@"
    ;;
  test-cli)
    run_pytest tests/test_cli.py -q "$@"
    ;;
  lint)
    run_python -m ruff check . "$@"
    ;;
  init-db)
    run_research init-db "$@"
    ;;
  run)
    if [[ $# -eq 0 ]]; then
      echo "run requires a company name." >&2
      exit 1
    fi
    run_research run "$@"
    ;;
  resume)
    if [[ $# -eq 0 ]]; then
      echo "resume requires a run id." >&2
      exit 1
    fi
    run_research resume "$@"
    ;;
  render)
    if [[ $# -eq 0 ]]; then
      echo "render requires a run id." >&2
      exit 1
    fi
    run_research render "$@"
    ;;
  audit)
    if [[ $# -eq 0 ]]; then
      echo "audit requires a run id." >&2
      exit 1
    fi
    run_research audit "$@"
    ;;
  model-calls)
    if [[ $# -eq 0 ]]; then
      echo "model-calls requires a run id." >&2
      exit 1
    fi
    run_research model-calls "$@"
    ;;
  model-call)
    if [[ $# -eq 0 ]]; then
      echo "model-call requires a call id." >&2
      exit 1
    fi
    run_research model-call "$@"
    ;;
  ollama-smoke)
    run_research ollama-smoke "$@"
    ;;
  ollama-run)
    if [[ $# -eq 0 ]]; then
      echo "ollama-run requires a company name and any desired options." >&2
      exit 1
    fi
    run_research ollama-run "$@"
    ;;
  openrouter-run)
    if [[ $# -eq 0 ]]; then
      echo "openrouter-run requires a company name and any desired options." >&2
      exit 1
    fi
    run_research openrouter-run "$@"
    ;;
  *)
    echo "Unknown task '$task'. Run ./dev.sh help" >&2
    exit 1
    ;;
esac
