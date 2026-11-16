Get paid and organic search recommendations for the project's Google Ads accounts, built from synced Google Ads and Google Search Console warehouse tables. Mirrors the recommendations in the in-product **Marketing analytics** scene.

# When to use

Use this tool when the user asks where to cut ad spend, which campaigns to scale or review, which search terms waste money, or how paid and organic search overlap.

Do not use it for attribution, conversion goals, or channel performance. Use `marketing-analytics-diagnose` when the data looks missing or wrong.

# Inputs

- `dateRange` — pass `{ "date_from": "-30d" }` unless the user asks for another period. Short ranges give few recommendations, because the rules need enough clicks and spend to compare.
- `conversionActions` — pass it only when the user names the Google Ads conversion actions that count. Omit it to count the account's primary conversion actions. It takes resource names like `customers/123/conversionActions/456`, not action names. Look them up with SQL on the account's `campaign_conversion_action_stats` table: `SELECT DISTINCT segments_conversion_action, segments_conversion_action_name`. Each ad account only uses the resource names under its own customer ID.
- Leave everything else out. The tool reads every synced Google Ads and Google Search Console source in the project.

# Output

Each result has:

- `rule` — the check that produced it, for example `spend_without_conversions`, `brand_leak`, `budget_constrained`, `scale_campaign`, `review_campaign`, `brand_overlap`, `content_gap`, `keyword_gap`, `striking_distance`, `policy_limited` or `keyword_tracking`. `keyword_tracking` means the project's Google Ads sessions arrive without `utm_term`, so PostHog conversions cannot be tied to keywords until the account passes `utm_term={keyword}`.
- `level` — `account`, `campaign` or `search_term`. `subject` is the ad account name, the campaign name or the search term, and `campaign` is the campaign a search term belongs to. For `keyword_gap`, `campaign` is the campaign to add the keyword to, because the search is not bought yet.
- `action` and `reason` — what to do and the numbers behind it. Quote them instead of inventing your own advice.
- `impact` — the monthly money impact in `currency`, or null. `impactDirection` says how to read it: `save` is spend to cut, `invest` is extra budget to add, `gain` is value to win, and `keep` is spend to protect.
- `impactType` — `measured` comes straight from the data. `estimated` is a projection, so present it as an estimate.
- `steps` — how to apply the recommendation, in order. A step's `copyValue` is the exact text to paste, such as a campaign name, a keyword in match type syntax (`[term]` is exact match, `"term"` is phrase match) or a page URL. A step's `url` opens what `linkText` names: a Google Ads section for the whole account, Google Search Console, or the page on the user's site that ranks for the search. When the user asks how to make a change, walk them through these steps. Some rules have no steps yet.
- `cpa` — `value` is the subject's cost per conversion, `benchmark` is the CPA benchmark (rules that judge a CPA compare it with this value, and other rules show it for context), `benchmarkSource` says where that benchmark comes from (`target_cpa`: the campaign's target CPA in Google Ads, compared with the campaign's total CPA; `campaign`: the campaign's own non-brand CPA, used for its search terms once it has enough non-brand conversions; `account`: the account's non-brand CPA), and `bestCampaign` and `worstCampaign` are the lowest and highest non-brand CPAs of the account's non-brand Search campaigns. Use them to say whether to scale or cut.

`dataGaps` lists data the rules could not read. Mention each gap's `message`, because the CPAs it names count the primary conversion actions instead of the selected ones.

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
