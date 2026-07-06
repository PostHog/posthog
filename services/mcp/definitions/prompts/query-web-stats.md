Run a web analytics breakdown table query — top pages, UTMs, devices, browsers, countries, etc. — with visitors and pageviews per row, plus optional bounce rate / average time on page. Mirrors the in-product **Web analytics** scene's table tiles.

# When to use this vs `query-trends` / `query-paths`

Pick this tool only when the answer needs **session-level math**. Session aggregation is more expensive than per-event queries — only pay for it when needed.

Use `query-web-stats` when the breakdown or metric is session-derived:

- `includeBounceRate=true` or `includeAvgTimeOnPage=true` (per-session metrics)
- Initial / first-touch breakdowns: `InitialPage`, `InitialChannelType`, `InitialReferringDomain`, `InitialUTMSource`/`Medium`/`Campaign`/`Term`/`Content`
- `ExitPage` (last event in a session)

Use `query-trends` (with a breakdown) for per-event counts by an event property — no session boundaries needed. Faster.

Use `query-paths` for navigation between arbitrary events when you don't need bounce rate or session-level metrics.

# `breakdownBy` cheat-sheet

- **Path-style** (pair with `includeBounceRate`/`includeAvgTimeOnPage`): `Page`, `InitialPage`, `ExitPage`, `PreviousPage`
- **Marketing**: `InitialChannelType`, `InitialReferringDomain`, `InitialReferringURL`, `InitialUTMSource`, `InitialUTMMedium`, `InitialUTMCampaign`, `InitialUTMTerm`, `InitialUTMContent`, `InitialUTMSourceMediumCampaign`
- **Audience / device**: `Browser`, `OS`, `Viewport`, `DeviceType`, `Country`, `Region`, `City`, `Timezone`, `Language`
- **Other**: `ScreenName`, `ExitClick`, `FrustrationMetrics` (these don't combine with `includeBounceRate` / `includeAvgTimeOnPage`)

# Inputs

Same filter set as `query-web-overview` (`dateRange`, `compareFilter`, `properties`, `filterTestAccounts`, `doPathCleaning`, `conversionGoal`). Plus `breakdownBy` (required), `includeBounceRate`, `includeAvgTimeOnPage`, `includeHost`, `limit`, `offset`. Default `dateRange` is last 7 days.

Performance hints:

- Leave `compareFilter` off unless the user asks for period-over-period — enabling it roughly doubles query cost.
- `limit` is capped at 200 by the wrapper. Prefer 10–25 unless the user explicitly asks for more.

Use `read-data-schema` to validate property names/values when needed.

# Example

Top 20 pages by bounce rate, last 7 days:

```json
{
  "kind": "WebStatsTableQuery",
  "breakdownBy": "Page",
  "includeBounceRate": true,
  "limit": 20,
  "dateRange": { "date_from": "-7d" }
}
```

# Out of scope

`conversionGoal` is supported as an input on this tool. Goal-funnel breakdowns (`WebGoalsQuery`), web vitals, and external clicks aren't exposed as separate query modes — fall back to `execute-sql` for those.
