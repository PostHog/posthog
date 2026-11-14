# Insight sense check

A live, viewed insight can be measuring something other than what its name, description, or series labels say.
The chart looks fine and the numbers are real, but a reader comes away with the wrong idea.
The common case: a series labelled "Users with X" counts every X event (`math: total`), so one person stuck in a loop reads as a jump in affected users.

This lens asks one question of a few insights per run: **would someone reading this chart be misled about what it measures?**
The heuristics below only point at where to look.
None of them is a finding on its own; the counterfactual query decides.

## Gate and rotation

- Run the lens at most once every 7 days, behind a `pattern:observability_gaps:insight-sense-check` scratchpad entry.
  The entry holds the last run date and a rolling log of checked insights as `short_id: date, verdict` (`ok`, `watch`, `reported`, `skip`), newest first, capped at about 60 lines.
- Pick up to 5 candidates from `insights-trending-retrieve` (`days=30`), most-viewed first, skipping any `short_id` the log checked in the last 60 days.
  The trending payload is large; ask for `limit` 20 or fewer.
- Only `TrendsQuery` insights are in scope, including formulas.
  Funnels, retention, and other insight kinds are out of scope, and so are SQL (`DataVisualizationNode` / HogQL) insights, because reading intent from free SQL is guesswork.
  Log out-of-scope candidates as `skip` so the rotation moves past them.
- No viewed trends insights means no lens this run.

## Read the insight

`insight-get` on each candidate, and read the full query, not the `system.insights` text (the MCP truncates long JSON).
Note the name, the description, each series' `custom_name`, `event`, `math`, and properties, the global `properties`, the `formulaNodes`, `aggregationAxisFormat`, `filterTestAccounts`, the dashboards it sits on, and `last_modified_by`.

## Hints worth a counterfactual

1. **Unit mismatch.** The name, description, or a series label names one unit (users, people, customers, organizations, accounts, sessions) and the series math counts another.
   The usual shape is a "users" label on `math: total`.
   The counterfactual swaps the math to the unit the label names: `dau` (or `weekly_active` / `monthly_active` if the label says so) for people, `unique_session` for sessions, `unique_group` with the right `math_group_type_index` for organizations or accounts.
2. **Ratio of totals.** A formula divides one `math: total` series by another and the axis format is a percentage, or the label reads as a share ("% of users who ...").
   A heavy individual on the numerator moves the ratio without anyone else being affected.
   The counterfactual swaps both sides to the people math.
3. **Share that can pass 100%.** A percentage formula whose numerator and denominator do not nest (different events, both on `total`), so the chart can show more than 100% of anything.
   Check the recent values; any bucket above 100 on a "% of" chart confirms the mismatch.
4. **Description contradicts the query.** The description states a date range, filter, event, or breakdown that the query does not apply.
   No counterfactual is needed, but quote both texts side by side.
5. **One person drives the series.** In the recent window, a single `person_id` contributes most of a series' events inside the insight's own filters.
   Check with `execute-sql`: events per day, distinct persons per day, and the top person's events per day, with the insight's event and property filters translated into the `WHERE` clause.
   Test the share within the insight's filters, not across the whole event; a widespread event can look healthy overall and still be dominated by one user on the page the insight filters to.

Labels that name the event itself ("Shown to user", an event called `user_invited`) are not a unit claim.
Read the label as a reader would, not as a keyword match.

## The counterfactual decides

Run one `query-trends` call that holds the insight's filters, interval, and date range, and adds the counterfactual series and formula next to the original.
Name the formulas so the result table reads directly (for example `as_built` and `unique_users`).
`query-trends` takes `properties` as a flat array, so lift the property filters out of nested `AND` groups, and an `ActionsNode` series needs its `name` as well as its `id`.

- **The two curves agree** (same shape and level within about 20% on every complete bucket): the label is loose but the chart does not mislead.
  An event that fires once per person, such as a signup, lands here, and that is the expected outcome for most insights.
  Log `ok`.
- **The curves diverge** in a way a reader would act on: one spikes or trends where the other is flat, or the levels differ by more than about 1.5x and the label claims the other unit.
  That is a candidate finding.
- **Unclear** (too few buckets, a partial current bucket doing the work, or divergence only on a single day): log `watch` with the observation that would settle it, and re-check on a later rotation.

## Report

Bundle a run's findings into one report under `report:observability_gaps:insight-sense-check`, and add later finds to it with `append_evidence` while it is live.
Per insight, state:

- what the insight says it measures (the name, description, or label, quoted) and what the query actually computes, in plain words ("exception events per pageview, not the share of users with an exception");
- the as-built and counterfactual values for the recent complete buckets, with the counterfactual attached as a chart;
- the smallest fix that makes chart and label agree: change the math, or rename the series and description to say what is counted.
  Never recommend deleting the insight.

Use P3, `actionability=requires_human_input`, `repository=NO_REPO`.
Route `suggested_reviewers` to the insight's `last_modified_by` (else `created_by`) when that person is in `scout-members-list`.
Phrase the finding as "this chart measures X, its label says Y", never as the author's mistake.

## Sibling courtesy

A spike or drop on the insight itself is the anomaly-detection scout's territory.
This lens never reports the movement, only whether the chart's definition matches its label.
When a live inbox report already cites the insight, link that report in your finding, because the people reading it are the ones being misled.
