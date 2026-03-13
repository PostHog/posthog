# Evaluation event schema

Evaluation results are stored as `$ai_evaluation` events in PostHog.
Each event represents one evaluation run against one generation.

## Event properties

| Property                    | Type          | Description                                                                                                           |
| --------------------------- | ------------- | --------------------------------------------------------------------------------------------------------------------- |
| `$ai_evaluation_id`         | string (UUID) | The evaluation definition UUID                                                                                        |
| `$ai_evaluation_name`       | string        | Name of the evaluation                                                                                                |
| `$ai_evaluation_type`       | string        | `"online"` (automatic, runs on new generations) or `"offline"` (manual/batch run)                                     |
| `$ai_evaluation_runtime`    | string        | `"llm_judge"` or `"hog"` — the execution runtime used                                                                 |
| `$ai_evaluation_result`     | boolean       | `true` = pass, `false` = fail                                                                                         |
| `$ai_evaluation_reasoning`  | string        | Explanation of the verdict (LLM judge: from the LLM; Hog: captured from `print()` output)                             |
| `$ai_evaluation_applicable` | boolean       | `false` means N/A — the evaluation wasn't applicable to this generation. When `false`, ignore `$ai_evaluation_result` |
| `$ai_evaluation_model`      | string        | LLM model used (only present for `llm_judge` type)                                                                    |
| `$ai_target_event_id`       | string (UUID) | The generation event UUID that was evaluated                                                                          |
| `$ai_trace_id`              | string (UUID) | The trace this generation belongs to                                                                                  |

## Relationships

```text
$ai_generation event (uuid)
    ↓ evaluated by
$ai_evaluation event (properties.$ai_target_event_id → generation uuid)
    ↑ defined by
Evaluation definition (properties.$ai_evaluation_id → evaluation uuid)
```

## Interpreting results

- `$ai_evaluation_result = true` AND `$ai_evaluation_applicable != false` → **pass**
- `$ai_evaluation_result = false` AND `$ai_evaluation_applicable != false` → **fail**
- `$ai_evaluation_applicable = false` → **N/A** (ignore the result field)
- `$ai_evaluation_applicable` is NULL → evaluation doesn't support N/A, treat result as-is

## Joining evaluations to generations

To see the original generation input/output alongside the evaluation result:

```sql
SELECT
    e.properties.$ai_evaluation_name as eval_name,
    e.properties.$ai_evaluation_result as result,
    e.properties.$ai_evaluation_reasoning as reasoning,
    g.properties.$ai_input as generation_input,
    g.properties.$ai_output_choices as generation_output,
    g.properties.$ai_model as model
FROM events e
JOIN events g ON g.uuid = e.properties.$ai_target_event_id
WHERE e.event = '$ai_evaluation'
    AND e.properties.$ai_evaluation_id = '<evaluation_uuid>'
    AND e.timestamp > now() - interval 7 day
    AND g.event = '$ai_generation'
ORDER BY e.timestamp DESC
LIMIT 20
```

**Warning:** `$ai_input` and `$ai_output_choices` can be very large. Dump results to a file if needed.
