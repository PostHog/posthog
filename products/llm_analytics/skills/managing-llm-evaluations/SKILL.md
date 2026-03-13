---
name: managing-llm-evaluations
description: >
  Guides agents through creating, running, and analyzing LLM evaluation results in PostHog.
  Use when a user wants to set up quality checks on AI generations, understand evaluation
  pass/fail rates, debug failing evaluations, write Hog evaluation code, or query
  $ai_evaluation event data. Covers both LLM-as-a-judge and code-based (Hog) evaluation types.
---

# Managing LLM evaluations

Evaluations automatically score AI generations for quality, safety, relevance, and other criteria.
There are two types:

- **LLM judge** — sends each generation to an LLM with a scoring prompt (subjective checks like helpfulness, hallucination, tone)
- **Hog code** — runs deterministic code against each generation (rule-based checks like length limits, keyword detection, format validation)

## Workflow

### 1. Discover existing evaluations

List what's already set up. Check which are enabled and what type they are.

```text
evaluations-get (optionally with search or enabled filter)
```

### 2. Choose the right evaluation type

| Use case                                         | Type        | Why                                              |
| ------------------------------------------------ | ----------- | ------------------------------------------------ |
| Subjective quality (helpfulness, accuracy, tone) | `llm_judge` | Needs LLM reasoning                              |
| Hallucination detection                          | `llm_judge` | Requires comparing output to input context       |
| Format validation (JSON, markdown, length)       | `hog`       | Deterministic, free, instant                     |
| Keyword/regex checks                             | `hog`       | No LLM needed                                    |
| Cost/token thresholds                            | `hog`       | Simple property comparison                       |
| Content safety                                   | Either      | LLM judge for nuance, Hog for keyword blocklists |

### 3. Create an evaluation

For **LLM judge**, you need a prompt and model configuration:

```json
{
  "name": "Helpfulness check",
  "evaluation_type": "llm_judge",
  "evaluation_config": {
    "prompt": "Evaluate if the AI response is helpful and addresses the user's question. Return true if helpful, false if not."
  },
  "output_type": "boolean",
  "output_config": { "allows_na": true },
  "model_configuration": {
    "provider": "openai",
    "model": "gpt-4o"
  }
}
```

For **Hog code**, provide source code (see [Hog code examples](./references/hog-code-examples.md)):

```json
{
  "name": "Output length check",
  "evaluation_type": "hog",
  "evaluation_config": {
    "source": "let len := length(output)\nif (len < 10) { return false }\nreturn true"
  },
  "output_type": "boolean",
  "output_config": { "allows_na": false }
}
```

### 4. Enable the evaluation

Evaluations are disabled by default. Enable to start scoring new generations:

```text
evaluation-update with { "enabled": true }
```

### 5. Query evaluation results

Results are stored as `$ai_evaluation` events.
See [event schema](./references/event-schema.md) for the full property reference
and [query examples](./references/query-examples.md) for ready-made HogQL patterns.

Quick pass rate check:

```sql
SELECT
    countIf(properties.$ai_evaluation_result = true AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as pass_count,
    countIf(properties.$ai_evaluation_result = false AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as fail_count,
    round(if(pass_count + fail_count = 0, null, pass_count / (pass_count + fail_count) * 100), 1) as pass_rate
FROM events
WHERE event = '$ai_evaluation'
    AND properties.$ai_evaluation_id = '<evaluation_uuid>'
    AND timestamp > now() - interval 7 day
```

### 6. Debug failing evaluations

To understand why generations are failing:

```sql
SELECT
    properties.$ai_target_event_id as generation_id,
    properties.$ai_evaluation_result as result,
    properties.$ai_evaluation_reasoning as reasoning,
    timestamp
FROM events
WHERE event = '$ai_evaluation'
    AND properties.$ai_evaluation_id = '<evaluation_uuid>'
    AND properties.$ai_evaluation_result = false
    AND timestamp > now() - interval 7 day
ORDER BY timestamp DESC
LIMIT 20
```

Then use the generation_id to look up the original generation's input/output.

## References

- [Event schema](./references/event-schema.md) — `$ai_evaluation` event properties
- [Query examples](./references/query-examples.md) — HogQL patterns for evaluation analysis
- [Hog code examples](./references/hog-code-examples.md) — common Hog evaluation patterns
