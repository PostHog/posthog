# Cost properties

All costs are USD, recorded per event at ingestion. PostHog derives them from the
model+provider and token counts — you cannot set them manually and trust them to
survive. Costs live on `$ai_generation` and `$ai_embedding` only.

| Property                          | Where                 | Meaning                                                                 |
| --------------------------------- | --------------------- | ----------------------------------------------------------------------- |
| `$ai_total_cost_usd`              | generation, embedding | Total cost for the call — **authoritative total**, use this for rollups |
| `$ai_input_cost_usd`              | generation, embedding | Cost attributable to input tokens                                       |
| `$ai_output_cost_usd`             | generation, embedding | Cost attributable to output tokens                                      |
| `$ai_request_cost_usd`            | generation, embedding | Per-request flat cost (e.g. Anthropic per-request fee); often `0`       |
| `$ai_web_search_cost_usd`         | generation, embedding | Cost of web-search tool calls inside the generation; often `0`          |
| `$ai_audio_cost_usd`              | generation            | Audio-modality cost when the model charges a separate rate; often `0`   |
| `$ai_image_cost_usd`              | generation            | Image-modality cost; often `0`                                          |
| `$ai_video_cost_usd`              | generation            | Video-modality cost; often `0`                                          |
| `$ai_input_tokens`                | generation, embedding | Tokens sent to the model (total across modalities)                      |
| `$ai_output_tokens`               | generation            | Tokens returned by the model (total across modalities)                  |
| `$ai_total_tokens`                | generation, embedding | Input + output tokens                                                   |
| `$ai_cache_read_input_tokens`     | generation            | Input tokens served from provider prompt cache                          |
| `$ai_cache_creation_input_tokens` | generation            | Input tokens written into provider prompt cache                         |
| `$ai_reasoning_tokens`            | generation            | Reasoning-model thinking tokens (charged as output)                     |
| `$ai_model`                       | generation, embedding | Primary breakdown dimension for cost                                    |
| `$ai_provider`                    | generation, embedding | Secondary breakdown (openai, anthropic, …)                              |
| `$ai_is_error`                    | generation            | Exclude/include failed calls in cost totals                             |
| `$ai_trace_id`                    | all `$ai_*` events    | Roll costs up to trace level                                            |
| `$ai_session_id`                  | all `$ai_*` events    | Roll costs up to session level (group sequences of related traces)      |

## Always sum `$ai_total_cost_usd`, not the components

At ingestion, `$ai_total_cost_usd = input + output + request + web_search` (plus
any modality costs). Summing only `$ai_input_cost_usd + $ai_output_cost_usd`
silently drops request and web-search fees — real and non-zero for Anthropic
request fees and any tool-augmented generation. The UI's cost cells sum
`$ai_total_cost_usd` over `event IN ('$ai_generation', '$ai_embedding')`;
mirror that. See [Calculating LLM costs](https://posthog.com/docs/llm-analytics/calculating-costs)
for the full derivation.

## Cache costs vary by provider reporting style

Providers that report cache tokens exclusively of `$ai_input_tokens` (e.g.
Anthropic) also surface cache-read/write spend outside `$ai_input_cost_usd`,
so `$ai_input_cost_usd` understates the true input-side spend there;
providers that report inclusively (e.g. OpenAI) bundle cache spend into
`$ai_input_cost_usd`. This varies by SDK version as well — see
[cache accounting](./cache-accounting.md) for the provider-aware formula.
`$ai_total_cost_usd` is always the authoritative total and already accounts
for whichever style the event used.

## Event-set rules for trace and evaluation events

`$ai_trace` and `$ai_span` events do **not** carry cost for rollup purposes.
To get a trace's total cost, sum `$ai_total_cost_usd` across its
`$ai_generation` and `$ai_embedding` events (matched by `$ai_trace_id`).
Some SDK wrappers duplicate `$ai_total_cost_usd` onto `$ai_trace` as a
convenience, but query runners still aggregate over
`event IN ('$ai_generation', '$ai_embedding')` — don't mix event sets or
you'll double-count.

`$ai_evaluation` events also emit cost properties (ingestion treats them
as costed alongside `$ai_generation` and `$ai_embedding`), but the stock
`/llm-analytics` rollups and the query runners **do not** include them
in cost totals. If the user wants "total spend including evaluations",
add `$ai_evaluation` to the event filter explicitly (e.g.
`event IN ('$ai_generation', '$ai_embedding', '$ai_evaluation')`) and
call out that it's an expanded definition; otherwise stick to the
generation + embedding set to match the UI.

## User dimension

`distinct_id` is the canonical user dimension — customers typically set it in
the SDK. Use person properties (e.g. `email`, `company_tier`) for richer
per-user breakdowns; discover what exists with `read-data-schema`.
