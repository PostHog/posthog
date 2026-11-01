Get paid and organic search recommendations for the project's Google Ads accounts, built from synced Google Ads and Google Search Console warehouse tables. Mirrors the recommendations in the in-product **Marketing analytics** scene.

# When to use

Use this tool when the user asks where to cut ad spend, which campaigns to scale or review, which search terms waste money, or how paid and organic search overlap.

Do not use it for attribution, conversion goals, or channel performance. Use `marketing-analytics-diagnose` when the data looks missing or wrong.

# Inputs

- `dateRange` — pass `{ "date_from": "-30d" }` unless the user asks for another period. Short ranges give few recommendations, because the rules need enough clicks and spend to compare.
- Leave everything else out. The tool reads every synced Google Ads and Google Search Console source in the project.

# Output

Each result has:

- `rule` — the check that produced it, for example `spend_without_conversions`, `brand_leak`, `budget_constrained`, `scale_campaign`, `review_campaign`, `brand_overlap`, `content_gap`, `keyword_gap`, `striking_distance` or `policy_limited`.
- `level` — `campaign` or `search_term`. `subject` is the campaign name or the search term, and `campaign` is the campaign a search term belongs to.
- `action` and `reason` — what to do and the numbers behind it. Quote them instead of inventing your own advice.
- `impact` — the monthly money impact in `currency`, or null. `impactDirection` says how to read it: `save` is spend to cut, `invest` is extra budget to add, `gain` is value to win, and `keep` is spend to protect.
- `impactType` — `measured` comes straight from the data. `estimated` is a projection, so present it as an estimate.

Totals in different currencies come from different ad accounts. Never add them together.

Present the results as suggestions for the user to evaluate, not as instructions. Always show the response's `disclaimer` text with them. Do not change campaigns, budgets, bids or keywords on the user's behalf.

An empty result means no rule fired, or the project has no synced Google Ads `campaign` and `campaign_stats` tables. Call `marketing-analytics-data-sources` to tell the two apart.

# Example

```json
{
  "kind": "MarketingAnalyticsRecommendationsQuery",
  "dateRange": { "date_from": "-30d" }
}
```
