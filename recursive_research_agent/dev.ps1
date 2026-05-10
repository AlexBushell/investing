param(
    [Parameter(Position = 0)]
    [string]$Task = "help",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"

function Get-PythonExe {
    $venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    return "python"
}

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    $pythonExe = Get-PythonExe
    & $pythonExe @Args
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Invoke-Pytest {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    Invoke-Python -Args @("-m", "pytest") + $Args
}

function Invoke-Research {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    Invoke-Python -Args @("-m", "app.cli") + $Args
}

function Show-Help {
    @"
Developer workflow shortcuts

Usage:
  .\dev.ps1 <task> [args...]

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
  .\dev.ps1 test-llm
  .\dev.ps1 run "Example Company"
  .\dev.ps1 ollama-run "Microsoft" --profile ollama_local --model gemma4:latest
  .\dev.ps1 openrouter-run "Microsoft" --profile openrouter_fast --model openai/gpt-4.1
"@ | Write-Host
}

switch ($Task.ToLowerInvariant()) {
    "help" {
        Show-Help
    }
    "test" {
        Invoke-Pytest -Args @("tests", "-q") + $Rest
    }
    "test-llm" {
        Invoke-Pytest -Args @("tests\test_llm.py", "-q") + $Rest
    }
    "test-orch" {
        Invoke-Pytest -Args @("tests\test_orchestrator.py", "tests\test_render.py", "-q") + $Rest
    }
    "test-search" {
        Invoke-Pytest -Args @("tests\test_search.py", "tests\test_cli.py", "-q") + $Rest
    }
    "test-cli" {
        Invoke-Pytest -Args @("tests\test_cli.py", "-q") + $Rest
    }
    "lint" {
        Invoke-Python -Args @("-m", "ruff", "check", ".") + $Rest
    }
    "init-db" {
        Invoke-Research -Args @("init-db") + $Rest
    }
    "run" {
        if (-not $Rest -or $Rest.Count -eq 0) {
            throw "run requires a company name."
        }
        Invoke-Research -Args @("run") + $Rest
    }
    "resume" {
        if (-not $Rest -or $Rest.Count -eq 0) {
            throw "resume requires a run id."
        }
        Invoke-Research -Args @("resume") + $Rest
    }
    "render" {
        if (-not $Rest -or $Rest.Count -eq 0) {
            throw "render requires a run id."
        }
        Invoke-Research -Args @("render") + $Rest
    }
    "audit" {
        if (-not $Rest -or $Rest.Count -eq 0) {
            throw "audit requires a run id."
        }
        Invoke-Research -Args @("audit") + $Rest
    }
    "model-calls" {
        if (-not $Rest -or $Rest.Count -eq 0) {
            throw "model-calls requires a run id."
        }
        Invoke-Research -Args @("model-calls") + $Rest
    }
    "model-call" {
        if (-not $Rest -or $Rest.Count -eq 0) {
            throw "model-call requires a call id."
        }
        Invoke-Research -Args @("model-call") + $Rest
    }
    "ollama-smoke" {
        Invoke-Research -Args @("ollama-smoke") + $Rest
    }
    "ollama-run" {
        if (-not $Rest -or $Rest.Count -eq 0) {
            throw "ollama-run requires a company name and any desired options."
        }
        Invoke-Research -Args @("ollama-run") + $Rest
    }
    "openrouter-run" {
        if (-not $Rest -or $Rest.Count -eq 0) {
            throw "openrouter-run requires a company name and any desired options."
        }
        Invoke-Research -Args @("openrouter-run") + $Rest
    }
    default {
        throw "Unknown task '$Task'. Run .\dev.ps1 help"
    }
}
