# Fixing `invalid_ai_token_property`

An AI event (`$ai_generation`, `$ai_span`, …) carried a token property that wasn't a valid number — `$ai_input_tokens`, `$ai_output_tokens`, or a similar count sent as a string, object, or malformed value.
The event was ingested but the property was **nulled**.
Category `event`, severity `warning`: token usage and cost analytics silently lose that data point.

## What it means in your code

Token counts must arrive as plain numbers. The usual sources of bad values:

- string formatting: `"1204"`, `"1,204"`, `"1204 tokens"`,
- passing the provider's usage **object** instead of a field (`usage` instead of `usage.total_tokens`),
- `NaN`/`undefined` from a missing usage block on streamed or failed responses.

## Diagnose

1. `posthog:ingestion-warnings-list` with `type: invalid_ai_token_property`. The sample details name the exact `property`, the received `value`, and its `valueType` — that's usually the whole diagnosis.
2. Find where the LLM provider's usage data is mapped onto the `$ai_*` properties (manual capture or instrumentation wrapper) and check the types.

## Fix

Send numbers:

```js
posthog.capture({
  distinctId,
  event: '$ai_generation',
  properties: {
    $ai_input_tokens: response.usage.prompt_tokens, // number
    $ai_output_tokens: response.usage.completion_tokens, // number
  },
})
```

Guard the missing-usage case (streamed/failed responses): omit the property rather than sending `undefined` or a placeholder. Prefer PostHog's LLM analytics SDK integrations over hand-mapping usage fields — they handle provider differences.

## Verify

Re-run a generation, re-query `posthog:ingestion-warnings-list` with a post-fix `since` — no new occurrences — and confirm token counts and costs appear for new traces (`posthog:query-llm-traces-list`).
