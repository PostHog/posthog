Run a web analytics overview query — high-level KPIs over a period: visitors, pageviews, sessions, average session duration, and bounce rate. Returns a small list of metric tuples with optional period-over-period comparison. Mirrors the in-product **Web analytics** scene.

# When to use this vs `query-trends`

Pick this tool only when the answer needs **session-level math**. Session aggregation is more expensive than per-event queries — only pay for it when needed.

Use `query-web-overview` when the question references just the aggregate values across the period instead of time series for those session-level values: bounce rate, session duration, sessions as a count, or entry/initial values (entry page, initial channel, initial UTM).

Use `query-trends` instead for per-event counts — pageviews, sign-ups, button clicks. Faster.

# Inputs

- `dateRange` — defaults to last 7 days when omitted. Keep ranges short — there is no enforced upper bound and large windows on the slow path can be expensive.
- `compareFilter: { compare: true }` — return prior-period values for change %. **Roughly doubles query cost** because it runs the same aggregation over the previous period — leave it off unless the user explicitly asks for a comparison.
- `properties` — event/person/session/cohort filters. Same operator semantics as `query-trends` — see that prompt. Defaults to `[]`.
- `filterTestAccounts` — exclude internal/test users.
- `doPathCleaning` — apply team's path-cleaning rules.
- `conversionGoal` — pass an `actionId` (must belong to the current project) or a `customEventName`. Only set when the user asks about a conversion.

Use `read-data-schema` to validate property names/values when needed.

# Example

```json
{
  "kind": "WebOverviewQuery",
  "dateRange": { "date_from": "-7d" }
}
```

# Out of scope

`conversionGoal` is supported as an input on this tool. Goal-funnel breakdowns (`WebGoalsQuery`), web vitals, and external clicks aren't exposed as separate query modes — fall back to `execute-sql` for those.
