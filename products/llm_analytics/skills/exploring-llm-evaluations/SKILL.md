---
name: exploring-llm-evaluations
description: >
  Investigate LLM analytics evaluations of both types — `hog` (deterministic
  code-based) and `llm_judge` (LLM-prompt-based). Find existing evaluations,
  inspect their configuration, run them against specific generations, query
  individual pass/fail results, and generate AI-powered summaries of patterns
  across many runs. Use when the user asks to debug why an evaluation is
  failing, surface common failure modes, compare results across filters,
  dry-run a Hog evaluator, prototype a new LLM-judge prompt, or manage the
  evaluation lifecycle (create, update, enable/disable, delete).
---

# Exploring LLM evaluations

PostHog evaluations score `$ai_generation` events. Each evaluation is one of two types,
both first-class:

- **`hog`** — deterministic Hog code that returns `true`/`false` (and optionally N/A).
  Best for objective rule-based checks: format validation (JSON parses, schema matches),
  length limits, keyword presence/absence, regex patterns, structural assertions, latency
  thresholds, cost guards. Cheap, fast, reproducible — no LLM call per run. Prefer this
  when the criterion can be expressed as code.
- **`llm_judge`** — an LLM scores generations against a prompt you write. Best for
  subjective or fuzzy checks: tone, helpfulness, hallucination detection, off-topic
  drift, instruction-following. Costs an LLM call per run and requires AI data
  processing approval at the org level.

Results from both types land in ClickHouse as `$ai_evaluation` events with the same
schema, so the read/query/summary workflows are identical regardless of evaluator type —
the only thing that changes is whether `$ai_evaluation_reasoning` was written by Hog
code or by an LLM.

This skill covers the full lifecycle: list/inspect/manage evaluation configs (Hog or
LLM judge), run them on specific generations, query individual results, and get an
AI-generated summary of pass/fail/N/A patterns across many runs.

## Tools

| Tool                                     | Purpose                                                        |
| ---------------------------------------- | -------------------------------------------------------------- |
| `posthog:llma-evaluation-list`           | List/search evaluation configs (filter by name, enabled flag)  |
| `posthog:llma-evaluation-get`            | Get a single evaluation config by UUID                         |
| `posthog:llma-evaluation-create`         | Create a new `llm_judge` or `hog` evaluation                   |
| `posthog:llma-evaluation-update`         | Update an existing evaluation (name, prompt, enabled, …)       |
| `posthog:llma-evaluation-delete`         | Soft-delete an evaluation                                      |
| `posthog:llma-evaluation-run`            | Run an evaluation against a specific `$ai_generation` event    |
| `posthog:llma-evaluation-test-hog`       | Dry-run Hog source against recent generations (no save)        |
| `posthog:llma-evaluation-summary-create` | AI-powered summary of pass/fail/N/A patterns across runs       |
| `posthog:execute-sql`                    | Ad-hoc HogQL over `$ai_evaluation` events                      |
| `posthog:query-llm-trace`                | Drill into the underlying generation that an evaluation scored |

All `llma-evaluation-*` tools are defined in `products/llm_analytics/mcp/tools.yaml`.

## Event schema

Every run of an evaluation emits an `$ai_evaluation` event. Key properties:

| Property                    | Meaning                                                  |
| --------------------------- | -------------------------------------------------------- |
| `$ai_evaluation_id`         | UUID of the evaluation config                            |
| `$ai_evaluation_name`       | Human-readable name                                      |
| `$ai_target_event_id`       | UUID of the `$ai_generation` event being scored          |
| `$ai_trace_id`              | Parent trace ID (for jumping to the trace UI)            |
| `$ai_evaluation_result`     | `true` = pass, `false` = fail                            |
| `$ai_evaluation_reasoning`  | Free-text explanation (set by the LLM judge or Hog code) |
| `$ai_evaluation_applicable` | `false` when the evaluator decided the generation is N/A |

When `$ai_evaluation_applicable = false`, the run counts as N/A regardless of `$ai_evaluation_result`.
For evaluations that don't support N/A, this property may be `null` — treat null as "applicable".

## Workflow: investigate why an evaluation is failing

Works the same way for `llm_judge` and `hog` evaluations — the differences only matter
when you eventually go to fix the evaluator (edit the prompt vs. edit the Hog source).

### Step 1 — Find the evaluation

```json
posthog:llma-evaluation-list
{ "search": "hallucination", "enabled": true }
```

Look at the returned `id`, `name`, `evaluation_type`, and either:

- `evaluation_config.prompt` for an `llm_judge`
- `evaluation_config.source` for a `hog` evaluator

The Hog source is the ground truth for why a hog evaluator passes or fails — read it
before assuming the failure is in the generation.

### Step 2 — Get the AI-generated summary

```json
posthog:llma-evaluation-summary-create
{
  "evaluation_id": "<uuid>",
  "filter": "fail"
}
```

Returns:

- `overall_assessment` — natural-language summary
- `fail_patterns` — grouped patterns with `title`, `description`, `frequency`, and `example_generation_ids`
- `pass_patterns` and `na_patterns` — same shape, populated when `filter` includes them
- `recommendations` — actionable next steps
- `statistics` — `total_analyzed`, `pass_count`, `fail_count`, `na_count`

The endpoint analyses the most recent ~250 runs (`EVALUATION_SUMMARY_MAX_RUNS`).
Results are cached for one hour per `(evaluation_id, filter, set_of_generation_ids)`.
Pass `force_refresh: true` to recompute.

**Compare filters in two calls** to spot what's distinctive about failures vs passes:

```json
posthog:llma-evaluation-summary-create
{ "evaluation_id": "<uuid>", "filter": "pass" }
```

Then diff the `pass_patterns` against the `fail_patterns` from Step 2.

### Step 3 — Drill into example failing runs

Each pattern surfaces `example_generation_ids`. Pull the underlying trace for the most
representative example:

```json
posthog:query-llm-trace
{ "traceId": "<trace_id>", "dateRange": {"date_from": "-30d"} }
```

(If you only have a generation ID, query for it via `execute-sql` first to find the
parent trace ID — see below.)

### Step 4 — Verify the pattern with raw SQL

The summary is LLM-generated and should be verified. Use `execute-sql` to count and
spot-check:

```sql
posthog:execute-sql
SELECT
    properties.$ai_target_event_id AS generation_id,
    properties.$ai_trace_id AS trace_id,
    properties.$ai_evaluation_reasoning AS reasoning,
    timestamp
FROM events
WHERE event = '$ai_evaluation'
    AND properties.$ai_evaluation_id = '<evaluation_uuid>'
    AND properties.$ai_evaluation_result = false
    AND (
        properties.$ai_evaluation_applicable IS NULL
        OR properties.$ai_evaluation_applicable != false
    )
    AND timestamp >= now() - INTERVAL 7 DAY
ORDER BY timestamp DESC
LIMIT 25
```

The N/A guard (`IS NULL OR != false`) is important — it matches the same logic the
backend uses to bucket runs.

## Workflow: run an evaluation against a specific generation

Use this when the user pastes a trace/generation URL and asks "what would evaluation X
say about this?".

```json
posthog:llma-evaluation-run
{
  "evaluationId": "<eval_uuid>",
  "target_event_id": "<generation_event_uuid>",
  "timestamp": "2026-04-01T19:39:20Z",
  "event": "$ai_generation"
}
```

The `timestamp` is required for an efficient ClickHouse lookup of the target event.
Pass `distinct_id` if you have it — it speeds up the lookup further.

## Workflow: build and test a new evaluator

### Hog evaluator (deterministic, code-based)

Reach for this first when the criterion is rule-based — it's cheaper, faster, and
reproducible. Prototype with `llma-evaluation-test-hog` (no save):

```json
posthog:llma-evaluation-test-hog
{
  "source": "return event.properties.$ai_output_choices[1].content contains 'sorry';",
  "sample_count": 5,
  "allows_na": false
}
```

The handler returns the boolean result for each of the most recent N `$ai_generation`
events. Iterate on the source until it behaves as expected, then promote it via
`llma-evaluation-create`:

```json
posthog:llma-evaluation-create
{
  "name": "Output is valid JSON",
  "description": "Fails when the assistant message can't be parsed as JSON",
  "evaluation_type": "hog",
  "evaluation_config": {
    "source": "let raw := event.properties.$ai_output_choices[1].content; try { jsonParseStr(raw); return true; } catch { return false; }"
  },
  "output_type": "boolean",
  "enabled": true
}
```

Hog evaluators have full access to the event and its properties — common patterns
include schema validation, length/token limits, regex matches, and tool-call shape
checks. Because they're deterministic, results are reproducible across reruns and
trivially diff-able.

### LLM-judge evaluator (subjective, prompt-based)

Use this when the criterion is fuzzy and a code rule would be brittle (tone, factuality,
helpfulness, on-topic-ness). There's no equivalent of `llma-evaluation-test-hog` for LLM
judges — the typical loop is to create the evaluator with `enabled: false`, run it
manually against a handful of representative generations via `llma-evaluation-run`, inspect
the results, refine the prompt with `llma-evaluation-update`, and then flip `enabled: true`
when you're satisfied:

```json
posthog:llma-evaluation-create
{
  "name": "Response stays on-topic",
  "description": "LLM judge — fails if the assistant changes topic from the user's question",
  "evaluation_type": "llm_judge",
  "evaluation_config": {
    "prompt": "You are evaluating whether the assistant's reply stays on-topic relative to the user's most recent question. Return true if it does, false if the assistant changed the subject. Return N/A if the user did not actually ask a question."
  },
  "output_type": "boolean",
  "output_config": { "allows_na": true },
  "model_configuration": {
    "provider": "openai",
    "model": "gpt-5-mini"
  },
  "enabled": false
}
```

Then dry-run against a known-good and a known-bad generation:

```json
posthog:llma-evaluation-run
{
  "evaluationId": "<new_eval_uuid>",
  "target_event_id": "<generation_uuid>",
  "timestamp": "2026-04-01T19:39:20Z"
}
```

LLM judges require organisation AI data processing approval. Hog evaluators do not.

## Workflow: manage the evaluation lifecycle

| Action                     | Tool                                                                                                                  |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Add a Hog evaluator        | `llma-evaluation-create` with `evaluation_type: "hog"` and `evaluation_config.source`                                 |
| Add an LLM-judge evaluator | `llma-evaluation-create` with `evaluation_type: "llm_judge"`, `evaluation_config.prompt`, and a `model_configuration` |
| Tweak the source or prompt | `llma-evaluation-update` (edits `evaluation_config.source` for Hog, `evaluation_config.prompt` for LLM judge)         |
| Toggle N/A handling        | `llma-evaluation-update` with `output_config.allows_na`                                                               |
| Disable temporarily        | `llma-evaluation-update` with `enabled: false`                                                                        |
| Remove                     | `llma-evaluation-delete` (soft-delete via PATCH `{deleted: true}`)                                                    |

`llm_judge` evaluations require AI data processing approval at the org level
(`is_ai_data_processing_approved`). The same gate applies to
`llma-evaluation-summary-create`. Hog evaluations do **not** require this gate
— they run as plain code on the ingestion pipeline.

## When to use Hog vs LLM judge

Reach for **Hog** by default. Switch to LLM judge only when the criterion can't be
expressed as code.

| Use Hog when…                                         | Use LLM judge when…                                     |
| ----------------------------------------------------- | ------------------------------------------------------- |
| The check is structural (JSON parses, schema matches) | The check is about meaning (on-topic, helpful, factual) |
| You need a deterministic, reproducible result         | A small amount of judgement variability is acceptable   |
| The criterion is cheap to compute                     | The criterion requires reading and understanding text   |
| You can't get AI data processing approval             | You have approval and the criterion is genuinely fuzzy  |
| You need to enforce a hard limit (length, cost, etc.) | You need to rate a quality dimension                    |
| You want sub-millisecond evaluation                   | A few hundred milliseconds + LLM cost are acceptable    |

A common pattern is to **layer them**: a Hog evaluator gates obvious format/length
violations cheaply, and an LLM-judge evaluator only fires on the generations that pass
the Hog gate (via `conditions`).

## Investigation patterns

The summarisation tool works the same way regardless of whether the evaluator is `hog`
or `llm_judge` — it analyses the resulting `$ai_evaluation` events, not the evaluator
itself. The fix path differs (edit Hog source vs. edit prompt) but the diagnosis is
identical.

### "Why is evaluation X suddenly failing more?"

1. `llma-evaluation-list` — confirm the evaluation is still enabled and unchanged
   (compare `evaluation_config.source` or `evaluation_config.prompt` to the version you
   expect)
2. `llma-evaluation-summary-create` with `filter: "fail"` — get the dominant
   failure patterns and example IDs
3. SQL count of fails per day to confirm the regression window:

   ```sql
   SELECT toDate(timestamp) AS day, count() AS fails
   FROM events
   WHERE event = '$ai_evaluation'
       AND properties.$ai_evaluation_id = '<uuid>'
       AND properties.$ai_evaluation_result = false
       AND timestamp >= now() - INTERVAL 30 DAY
   GROUP BY day
   ORDER BY day
   ```

4. Drill into a representative trace per pattern via `query-llm-trace`

### "Are passes and fails caused by the same root content?"

1. Generate two summaries: one with `filter: "pass"`, one with `filter: "fail"`
2. If `pass_patterns` and `fail_patterns` describe similar content:
   - For an `llm_judge`: the prompt or rubric is probably ambiguous — reword
     `evaluation_config.prompt` and use `llma-evaluation-update`
   - For a `hog` evaluator: the rule is probably under- or over-matching — read the
     source via `llma-evaluation-get`, narrow the predicate, and retest with
     `llma-evaluation-test-hog` before pushing the fix via `llma-evaluation-update`

### "Did a Hog evaluator regression after a code change?"

Hog evaluators are reproducible — if the source hasn't changed, identical inputs should
yield identical outputs. When fail rates jump for a Hog evaluator:

1. `llma-evaluation-get` — note the current source and `updated_at`
2. Spot-check the latest failing runs with the SQL query from Step 4 above
3. Re-run the source against those exact generations using `llma-evaluation-test-hog` with a
   modified `conditions` filter that targets them
4. If the test results match the live results, the change is in the _generations_, not
   the evaluator (a model upgrade, prompt change upstream, etc.) — investigate the
   producer
5. If they diverge, the evaluator was edited; check git history of the source field via
   the activity log

### "What kinds of generations does this evaluator skip as N/A?"

```json
posthog:llma-evaluation-summary-create
{ "evaluation_id": "<uuid>", "filter": "na" }
```

Inspect `na_patterns` to see whether the N/A logic is doing the right thing. If a
pattern in `na_patterns` looks like something that should have been scored:

- For an `llm_judge`: the applicability instruction in the prompt is too broad — narrow
  it
- For a `hog` evaluator with `output_config.allows_na: true`: the source is returning
  `null` (or whatever the N/A signal is) too eagerly — tighten the precondition

### "Score this single generation right now"

`llma-evaluation-run` with the trace's generation ID and timestamp. Useful for spot-checking
or wiring evaluations into a larger agent loop.

## Constructing UI links

- **Evaluations list**: `https://app.posthog.com/llm-analytics/evaluations`
- **Single evaluation**: `https://app.posthog.com/llm-analytics/evaluations/<evaluation_id>`
- **Underlying generation/trace**: see the `exploring-llm-traces` skill's URL conventions

Always surface the relevant link so the user can verify in the UI.

## Tips

- The summary tool is **rate-limited** (burst, sustained, daily) and **caches results
  for one hour** — repeated calls with the same `(evaluation_id, filter)` are cheap; use
  `force_refresh: true` only when you genuinely need fresh analysis
- Pass `generation_ids: [...]` to scope a summary to a specific cohort of runs (max 250)
- The `statistics` block in the summary response is computed from raw data, not the LLM
  — trust those counts even if a pattern's `frequency` field is qualitative
- For rich filtering not supported by `llma-evaluation-list` (e.g. by author or model
  configuration), fall back to `execute-sql` against the `evaluations` Postgres table or
  the `$ai_evaluation` ClickHouse events
- When showing failure patterns to the user, always include 1-2 example trace links so
  they can validate the pattern visually
- `llma-evaluation-*` tools use `evaluation:read` for read tools and `evaluation:write` for
  mutating tools; `llma-evaluation-summary-create` uses `llm_analytics:write`
- Hog evaluators are reproducible — if you suspect a regression, `llma-evaluation-test-hog`
  with the suspect source against the failing generations is the fastest way to bisect
  whether the change is in the evaluator or in the producer of the generations
- LLM-judge evaluators are non-deterministic across reruns; expect 1-5% noise even with
  a fixed prompt and model. If you're chasing a small regression in fail rate, prefer
  Hog or pin a deterministic provider/seed in the `model_configuration`
