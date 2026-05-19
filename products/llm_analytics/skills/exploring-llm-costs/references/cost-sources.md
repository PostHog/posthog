# How costs get set: SDK, custom pricing, ingestion

Costs can arrive on the event in three ways; ingestion applies them in this
precedence (see [Calculating LLM costs](https://posthog.com/docs/llm-analytics/calculating-costs)
for the authoritative rules):

1. **Pre-calculated** — the SDK / manual capture sets `$ai_input_cost_usd`,
   `$ai_output_cost_usd`, `$ai_request_cost_usd`, `$ai_web_search_cost_usd`
   directly. Ingestion preserves them and fills `$ai_total_cost_usd` as the
   sum. Use when the caller already knows the cost.
2. **Custom pricing** — the SDK sets `$ai_input_token_price` /
   `$ai_output_token_price` (required pair) plus optionally
   `$ai_cache_read_token_price`, `$ai_cache_write_token_price`,
   `$ai_request_price`, `$ai_web_search_price`. Ingestion multiplies by the
   token counts. Token prices are **per token**, not per million.
3. **Automatic model matching** — ingestion looks up pricing by
   `$ai_model` + `$ai_provider` (OpenRouter first, manual fallback).

Three metadata properties tell you which path was taken — read them whenever
a cost looks wrong:

| Property                  | Meaning                                                                     |
| ------------------------- | --------------------------------------------------------------------------- |
| `$ai_model_cost_used`     | Canonical model id the pricing lookup matched (may differ from `$ai_model`) |
| `$ai_cost_model_source`   | `openrouter` \| `manual` \| `custom` \| `passthrough`                       |
| `$ai_cost_model_provider` | Provider the lookup used                                                    |

## Diagnostic: zero or null cost by model and source

When `$ai_total_cost_usd` is null or zero for a model, group by model
**and** `$ai_cost_model_source` so you can see, per model, how many of
its zero-cost calls came from each ingestion path. A model that has only
`source = NULL` rows means ingestion never matched a pricing entry (fix:
add custom pricing or correct `$ai_model` / `$ai_provider`); a model
with `source = 'custom'` and zero cost is an explicitly-zero custom
price (usually a misconfigured `$ai_input_token_price` / `$ai_output_token_price`).
Without the source grouping the two look the same.

```sql
posthog:execute-sql
SELECT
    properties.$ai_model AS model,
    properties.$ai_cost_model_source AS source,
    count() AS calls,
    countIf(toFloat(properties.$ai_total_cost_usd) = 0 OR properties.$ai_total_cost_usd IS NULL) AS zero_cost_calls
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY model, source
ORDER BY zero_cost_calls DESC
```
