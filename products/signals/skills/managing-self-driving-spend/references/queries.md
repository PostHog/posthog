# Queries

Use `posthog:inbox-usage-get` for the monthly overview; run these drilldowns with `posthog:execute-sql` in its returned `project_id`.
Read the `querying-posthog-data` skill's Self-driving usage reference for schema and access details.
Replace `{date_from}` and `{date_to}` with inclusive/exclusive UTC bounds, for example `toDateTime('2026-10-01 00:00:00', 'UTC')` and `toDateTime('2026-11-01 00:00:00', 'UTC')`.
Replace `{yield_from}` with the start of the last 60 days, in the same format.
Multiply credits by the monthly tool's `pricing.usd_per_credit`; do not assume credits are cents.

## Which file to read

| Question                                                    | File                                               | Sections                                                                                                                 |
| ----------------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| What was spent, by day, source, or scout?                   | [queries-spend.md](queries-spend.md)               | First receipt, Spend by day, Spend by signal source, Spend by scout                                                      |
| Is a source or scout worth what it costs?                   | [queries-yield.md](queries-yield.md)               | Yield, Baselines, Yield by signal source, Yield by scout, Outcomes of reports too new to settle, What a quiet scout does |
| Which part of a large source drives its spend?              | [queries-source-parts.md](queries-source-parts.md) | Breakdown inside a source                                                                                                |
| Should a daily report limit or a priority threshold change? | [queries-controls.md](queries-controls.md)         | Reports shown per day, Pull requests linked and merged                                                                   |

## HogQL rules for these tables

These rules prevent errors and wrong numbers. Keep them when you change a query.

- **Join on strings from subqueries.** A join between these tables on their UUID columns fails with `Invalid JOIN ON expression`, and HogQL does not allow a function call in a join condition. Convert each key with `toString()` inside a subquery and join the aliases.
- **Bucket days in UTC.** `toDate()` takes one argument and uses the project timezone. Write `toDate(toTimeZone(finalized_at, 'UTC'))`, or days do not match the monthly tool.
- **Test a join match with a marker.** A missed `LEFT JOIN` can return NULL, and HogQL treats `NULL != ''` as true. Select `1 AS matched` in the joined subquery and test `ifNull(matched, 0) = 1`.
- **Expect the project timezone in results.** Timestamps display in the project timezone even when your bounds are UTC.
- **Test merged pull requests with `state`.** `merged_at` is empty on many merged pull requests, so `state = 'merged'` is the reliable test.
- **Date pull requests by their report.** A pull request's `created_at`, and its link's, can be the date of an import. Neither table stores when the pull request was opened.
