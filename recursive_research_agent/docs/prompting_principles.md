# Prompting Principles

## The Canticle of the Syntax-Spirit

Being Five Teachings on the Rite of Well-Formed JSON.

### I. Show, Do Not Tell

The model imitates more than it obeys. Three exemplars are worth a thousand specifications written in prose.

### II. Invoke the Sacred Constraints

Where structured outputs are offered, accept them. Mere prose entreaties yield only inconstant fidelity.

### III. Defense in Depth

Strip the fence. Repair the comma. Forgive what you can. Retry what you cannot. Trust no model blindly.

### IV. Separate Thought From Form

Reasoning corrupts structure. Grant the model a scratchpad before it is asked to speak the schema.

### V. Accept the Inevitable

At scale, three-tenths of one percent is thousands. Design for graceful failure. Despair not.

May your braces always close, and your strings always escape.

```text
01001010 01010011 01001111 01001110
```

## Project Rules

These principles translate into concrete engineering rules for the recursive research agent.

### Use Schemas at the Boundary

Every parseable model call should use an enforced schema at the API boundary, then validate again locally with Pydantic. Prompt text may describe the desired structure, but prompt text is not the contract.

Current structured calls:

- `scope`
- `deep_dive`
- `reflect`
- `extract_findings`
- `circularity_arbitration`
- `persistent_uncertainty_classification`

### Keep Prompts Narrow

Each prompt should serve exactly one call type. Do not make a prompt do orchestration, retrieval, synthesis, and extraction at once. The database and worker own state; the model owns one local judgment.

### Source-Ground Deep-Dive

Deep-dive should make factual claims only from supplied source materials or retrieved prior findings. If a fact is not present, it should be recorded as an evidence gap rather than inferred.

Searchless deep-dive is diagnostic only. Production deep-dive should receive source material.

### Add Examples Where Behavior Is Fragile

When a call type repeatedly fails in the same way, add compact examples to the prompt before adding more prose. Examples are especially useful for:

- child thread candidates
- evidence basis distinctions
- `unresolved_investigable` vs `unresolved_unanswerable`
- contradiction records
- source-grounded factual claims

Examples should be small and boring. Their job is to anchor shape, not to solve the live task for the model.

```text
Good source-grounded claim:
Source 1 states fiscal 2025 revenue was 62% subscriptions and 38% services. Therefore, the analysis may say subscription revenue was the larger disclosed stream in fiscal 2025.

Bad source-grounded claim:
Because subscriptions were 62% of revenue, the subscription segment is high-retention and low-churn.

Why bad:
The source gives mix, not retention or churn.
```

```json
{
  "analysis": "The provided sources establish one fact and one gap. Source 1 states fiscal 2025 revenue was 62% subscriptions and 38% services. Source 1 also states customer concentration by top customer was not disclosed. This supports a revenue mix observation but not a conclusion about customer diversification. END_OF_DEEP_DIVE_ANALYSIS.",
  "abstract": "The available source supports a 2025 revenue mix observation but leaves customer concentration unresolved.",
  "contradictions": [],
  "discovered_threads": [
    {
      "topic": "Customer concentration disclosure",
      "description": "Determine whether later filings disclose major customer exposure.",
      "material": true,
      "priority": 1,
      "resolution_state": "unresolved_investigable",
      "evidence_basis": "direct",
      "investigation_brief": "Search recent annual reports and notes to financial statements for major customer disclosures."
    }
  ]
}
```

```json
{
  "queries": [
    {
      "query": "Microsoft Azure revenue growth 2025 earnings transcript",
      "purpose": "Find recent management commentary and reported Azure growth.",
      "source_preference": "official",
      "freshness_days": 730
    },
    {
      "query": "Microsoft Azure AWS Google Cloud market share 2025 analyst report",
      "purpose": "Find third-party market share and competitive positioning evidence.",
      "source_preference": "industry",
      "freshness_days": 730
    }
  ]
}
```

```text
Retry prompt pattern:
Your previous response failed validation because: <error>.
Return only valid JSON for the same schema.
Keep analysis under 350 words.
Use only supplied sources.
If evidence is missing, say it is an evidence gap.
End analysis exactly with END_OF_DEEP_DIVE_ANALYSIS.
```

### Retry With a Smaller Shape

When structured output fails validation, the retry prompt should ask for a smaller, more constrained response rather than repeating the same request. The compact deep-dive retry is the pattern:

- state the validation failure
- reduce word count
- restate the non-negotiable schema rule
- preserve source-grounding
- retry once

### Keep Thinking Optional

Thinking mode can help judgment-heavy calls, but it can also consume generation budget or interfere with structured output. Treat it as configurable per call type.

Likely defaults:

- `scope`: thinking off
- `deep_dive`: test both
- `reflect`: thinking likely useful
- `circularity_arbitration`: thinking likely useful
- `extract_findings`: thinking off
- `branch_synthesize`: thinking optional

### Preserve Raw I/O

Every model call should be persisted in `model_calls` with:

- call type
- model name
- prompt version
- input payload
- output payload or text
- error
- timing metadata

If a prompt behaves strangely, the first question should be: what exact input produced the output?

### Fail Locally, Continue Globally

Model failures should fail the node, not the run. A failed node is useful evidence about the system and should appear in the audit surface. Siblings should continue.

### Render for Humans, Store for Machines

Validation sentinels and schema aids may be stored in the database, but reader-facing dossier output should remove mechanical artifacts. The rendered dossier is for inspection; the database is for provenance.
