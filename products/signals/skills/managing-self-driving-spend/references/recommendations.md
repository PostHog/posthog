# Recommendation rules

Go through every control in [controls.md](controls.md) and decide whether it applies to this project.
A good recommendation names the specific item to change (a scanner, a signal type, a scout, an evaluation), the evidence from the queries, the monthly saving in dollars, and what the user loses.
"Reduce replay spend" is not a recommendation. "Turn off inbox findings for the 'Checkout errors' scanner: 3 of 140 reports resolved, saves about $40 a month" is.

Let the project's data decide what to keep. Do not assume that one signal type, scanner, or scout is always worth more than another.
Skip any change that saves less than about $10 a month, unless the user asked about that item.

## Estimate monthly spend

Use non-exempt recorded usage from complete UTC days after the project's first receipt (see "First receipt" in queries-spend.md).
Estimate a month as `(5 * weekday_average + 2 * weekend_average) / 7 * days_in_month`.
If the sample has no weekend day, use the average of all days and say that the figure can run high.
Scale each item's period spend by the same ratio, so the items and the total agree.
Label the result as an estimate, not an invoice forecast, and do not double-count overlapping controls.

## Judge yield

Base every yield judgment on settled reports (see "Yield" in queries-yield.md), not on reports still waiting for a fix.
Settled rate shows how often an item's reports get resolved, and cost per resolved shows what each fix costs. Use them together:

| Settled rate against the baseline | Cost per resolved against the baseline | What it supports                                       |
| --------------------------------- | -------------------------------------- | ------------------------------------------------------ |
| Low                               | Higher                                 | Recommend turning it down or off                       |
| Low, with none resolved           | No estimate possible                   | Recommend turning it down or off                       |
| Low                               | Same or lower                          | Worth a look. The fixes are cheap, so the user decides |
| Same or higher                    | Higher                                 | Worth a look if the saving is large                    |
| Same or higher                    | Same or lower                          | No change                                              |

- A low rate is under about two thirds of the baseline's settled rate.
- Compare sources with the source baseline and scouts with the scout baseline (see "Baselines" in queries-yield.md).
- Fewer than 20 settled reports means the yield is too new to judge. Recommend no cut that rests on it.
- Fewer than about 3 expected resolved reports (`reports_created * settled_rate`) makes cost per resolved too unstable to use. Say so, and judge on the settled rate and raw spend.
- Running something less often is a lighter cut than turning it off. A low rate alone can support it.

For a scout that is too new, read "Outcomes of reports too new to settle" in queries-yield.md.
A large share already resolved is a reason to leave it alone. A large share dismissed is a reason to look closer, not a reason to cut.

## Know what a scout is for

Yield only measures a scout whose job is to find problems for people to fix.
Before you judge a scout, read its description, `output_destinations`, `structured_output_schema`, and `scout_role` from `posthog:scout-config-list`, and read "What a quiet scout does" in queries-yield.md.

| Kind of scout     | How to recognize it                                                                             | How to judge it                                                                                                                                |
| ----------------- | ----------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Finder            | Reports for people to act on. Includes scouts that sweep a codebase or list in pages            | Use yield. Running a sweep less often makes each pass through the code or list take longer. Say so                                             |
| Watchdog          | Watches for rare events such as abuse or failures. Its summaries show checks that found nothing | Quiet runs are the expected result. Prefer a pre-check, which keeps detection time. Run it less often only when detection time does not matter |
| Measurement       | Has a `structured_output_schema`, and its description says it records, measures, or judges      | Yield does not apply. Ask how many samples are needed, and check whether alerts or dashboards read the series before you run it less often     |
| Digest or handoff | `inbox` is false, delivers to Slack or a canvas, or hands work to a named person or team        | Yield does not apply. Ask its owner how fresh it must be. Run it less often before you suggest a pause                                         |
| Operational       | `scout_role` is `operational`. Watches Self-driving itself                                      | Do not recommend pausing it                                                                                                                    |

## What to check

- **Spend limit.** Compare the current limit with billed spend from `posthog:billing-limits-get` and with the monthly estimate, keeping recorded usage separate.
  Billing periods need not match UTC months, so read the period from `posthog:billing-usage-summary-get`. It also shows whether PostHog is limiting the product now.
  If the limit is below the estimate, put this first and say on which day of the period the limit would be reached.
  If billed spend is far below recorded usage, for example $0.00, do not call the limit reached. Say the day is hypothetical, say that billed spend and recorded usage disagree, and ask whether the limit is meant to apply.
  Otherwise put it last, and suggest about 1.2 times the expected monthly spend after the other changes.
  Explain that once the limit is reached, new signals are dropped for the rest of the period, not held until it resets.
- **Parts of a large source.** For each source over 10% of signal spend, run "Breakdown inside a source" in queries-source-parts.md.
  Recommend turning down the specific parts that "Judge yield" supports: a scanner's inbox findings or sampling rate, an error tracking signal type, an evaluation report, an alert's investigation.
  Prefer this to turning off the whole source.
- **Source steering.** When a kind of record inside a source does poorly, and the source reads `steering` (see controls.md), suggest a rule that names that kind of record.
  This drops records before they become signals, so it can reduce processing and research. You cannot estimate the saving in advance, so give no dollar figure and check it again after two weeks.
- **Whole sources.** Recommend turning off a source only when "Judge yield" supports it and neither a narrowing setting nor source steering applies.
  When its yield is too new to judge, use other evidence such as how many of its reports anyone opened, and say that resolution is not known yet.
- **Scouts with no output.** Finder scouts with at least 20 runs in the period that created and edited no reports. Fewer runs prove little.
  Group them into one recommendation with their total spend, name the largest ones, and recommend a pre-check or a slower schedule before a pause.
  Check their history first: a scout with a strong settled rate may have finished its backlog.
- **Frequent scouts with low yield.** Finder scouts that run hourly or more often and have a low settled rate.
  Recommend a pre-check or a slower schedule before a pause, and give the saving for the new schedule.
  A scout that edits many reports keeps them current. Run it less often, do not pause it.
- **Scout pre-checks.** Scouts with `precheck_query_source` of `off` and high `empty_run_credits` in "Spend by scout" in queries-spend.md.
  When a query can tell that nothing new arrived, prefer a pre-check to a slower schedule, because findings do not arrive later.
  Read the scout's description and recent summaries, write a query, and dry-run it with `posthog:scout-config-precheck-test` so you recommend a query that works. The dry run changes nothing and shows only what the query finds now.
  Say "up to" and give `empty_run_credits`, scaled to a month, as the saving: some empty runs will still start, because the query can find new data that is not worth a report.
  For a measurement scout, gate only on whether new samples exist. Its empty runs can still record data, so its `empty_run_credits` overstates waste.
  Do not count this saving together with a slower schedule for the same scout.
- **Research steering.** When one kind of report has a low settled rate and neither a setting nor source steering selects it, suggest research instructions that name it.
  Give no dollar figure.
- **Automatic pull requests.** Compare pull requests linked and merged, by source and by scout (see queries-controls.md).
  When an item has many and few merge, suggest a higher priority threshold.
  Use implementation receipts for the affected reports to estimate savings; do not assume all implementation spend would disappear.
  A person who then starts one of those fixes by hand moves its cost to PostHog AI usage, so say that the saving can be partly offset.
- **Daily report limit.** Run "Reports shown per day" in queries-controls.md. Recommend a limit only when a few days hold much more than the rest, near the 75th percentile of daily reports.
  Say that signals past the limit are dropped, so a real incident on a spike day can be missed.

## How to present them

Split the list in three parts:

1. **Recommended.** Changes with a clear case, ranked by monthly saving.
2. **Worth a look.** Changes with a real saving and a real cost, where the user has to decide. Say what decides it.
3. **Checked, no change.** Controls you looked at that need no change, each with one line on why.
   This shows the user that you went through all of them.
   Say which settings you could not read.

For each recommendation, end with "I can apply this" or with where the user changes it in the app.
