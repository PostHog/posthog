---
name: managing-self-driving-spend
description: >
  Explains and controls what Self-driving (Inbox) costs. Use when the user asks what they spent on
  Self-driving, which signal sources or scouts drive that spend, how spend changes day to day,
  how many reports a source or scout produced, or how to lower or cap the spend. Breaks spend
  down by signal source, scout, and day, links it to the reports it produced, recommends changes
  ranked by savings, and applies them only after the user confirms each one. Trigger terms:
  inbox spend, self-driving cost, scout cost, why is my bill high, reduce inbox spend, billing
  limit, daily report limit, turn off a source, pause a scout, scout pre-check, scout schedule,
  run a scout less often, trigger a scout from a workflow.
---

# Managing Self-driving spend

Start with `posthog:inbox-usage-get` for monthly recorded usage, including processing, research, repository selection, scout execution, and automatic report implementation.
Pass `month: "YYYY-MM"`, or omit it for this month; history starts no earlier than October 2026, and a project's first receipt can be later.
Show amounts as AI credits, with the USD value next to them: multiply decimal credits by the returned `pricing.usd_per_credit`.
Recorded usage includes exempt work and is not an invoice; use `posthog:billing-limits-get` for the billing spend and limit.
On a large project these tools can return more than fits in your context. If yours saves the output to a file, parse the file with a script, and keep the fields you need.

## Workflow

1. **Scope.** Use the selected project and requested dates, defaulting to this UTC calendar month.
   Read `posthog:inbox-usage-get` and `posthog:billing-limits-get`.
   Use the returned canonical `project_id` for SQL reconciliation; child environments resolve to their parent and require access there.
2. **Inventory.** List sources with `posthog:inbox-source-configs-list` and scouts with `posthog:scout-config-list`.
   Explain historical spend even for disabled items; recommend controls only where they still apply.
3. **By source and scout.** Use the monthly tool's `sources` and `scouts`; their `total_credits` sum to the overall total.
   Sources include downstream research and implementation; scouts contain execution only, including runs with no reports.
4. **Drill down.** Use `posthog:execute-sql` with [references/queries.md](references/queries.md) for custom dates, individual runs or reports, and finer source breakdowns.
   If the monthly tool is unavailable, use the SQL ledger subject to its access controls; report credits if no verified USD conversion is available.
5. **By day.** Run "First receipt" and "Spend by day" in [references/queries-spend.md](references/queries-spend.md), and investigate spikes by source, scout, or `kind`.
6. **Yield.** Run "Baselines", "Yield by signal source", and "Yield by scout" in [references/queries-yield.md](references/queries-yield.md).
   Yield is the share of settled reports that were resolved. Compare each item with its baseline on both settled rate and cost per resolved.
7. **Inside each large source.** Run "Breakdown inside a source" in [references/queries-source-parts.md](references/queries-source-parts.md) for every source that holds more than 10% of signal spend.
   This finds the specific scanners, signal types, evaluations, alerts, or channels behind the spend, which is where most recommendations come from.
8. **Recommend.** Go through every control in [references/controls.md](references/controls.md) and decide whether it applies, using [references/recommendations.md](references/recommendations.md).
   Before you judge a scout, find out what kind of scout it is. A quiet run or an unresolved report is not always waste.
   Name the specific item to change, give a dollar figure, say what the user loses, and say whether you can apply it.
9. **Apply.** Change nothing without an explicit yes for that specific change.
   [references/controls.md](references/controls.md) lists the tool for each control, or where to change it in the app when no tool exists.
   Read the setting back after you change it.

Present the result with [references/report-template.md](references/report-template.md).

## Rules

- Sum each `system.signal_spend` record once. Signal `metadata.total_spend`, scout `spend_credits`, and report detail totals are copies or overlapping views, not additional charges.
- Filter finalized usage by `finalized_at` with inclusive start and exclusive end in UTC. Work started earlier can finalize in this period.
- Show `exempt_credits` as a subset, not an additional cost. Use receipt exemptions rather than excluding named sources or scouts; non-exempt usage is still not necessarily invoiced usage.
- Report `unsettled_credits`, `untracked_scout_run_count`, and any row with `incomplete` true. Unsettled credits cover work created in the requested month, exclude finalized totals, and are not the outstanding balance across all months. Missing receipts mean unknown cost.
- Explain the two summary flags by their cause. `incomplete` is true when any work is unsettled, any scout run is untracked, or any row is incomplete, so it is usually true while Self-driving is running. `attribution_incomplete` is true when any spend has no source, which is the null-source row.
- Preserve unattributed costs, including implementation for deleted reports. Implementation is attributed to the report's current triggering signal, which can change.
- Implementation usage covers automatic runs only. A fix that a person starts from a report is metered as PostHog AI, so it has no receipt here. Do not present implementation usage as the total cost of fixing reports, and do not estimate fix cost from pull request counts.
- Use latest signal metadata only for attribution, with one embedding model and rendering. Do not filter metadata by signal arrival date when attributing period spend.
- Reports need about 14 days to resolve, so measure yield on settled reports: reports first shown at least 14 days ago.
  Take them from the last 60 days, even when the spend period is shorter.
  When a source or scout has fewer than 20 settled reports, call its yield too new to judge, and recommend no cut that rests on it.
- Do not treat a low resolved share as waste for a scout that measures, digests, or hands off work. [references/recommendations.md](references/recommendations.md) says how to judge each kind.
- Private scout trials are excluded from the SQL tables. Scout report counts can overlap; deduplicate IDs for project totals, and never add shared scout costs across report details.
- A scout that rarely creates reports can still be useful if it edits existing ones.
  Check `edited_report_ids` before you recommend pausing it.
- A scout with a pre-check can have few runs on purpose, because a skipped run leaves no run row.
  Read `last_precheck_at` and `last_precheck_outcome` before you call its runs missing.
- Scout spend follows the number of runs. Before you recommend a pause, check the three controls that cut runs and keep the scout: a pre-check, a slower or cron schedule, and a workflow trigger with a backstop schedule. [references/controls.md](references/controls.md) says when each one fits.
- Turn off a source only after you check its narrowing settings and source steering. [references/controls.md](references/controls.md) lists which sources read `steering`.
- Never turn off error tracking ingestion or lower its rate limits to save Self-driving spend.
  That drops exception data permanently. Change the Self-driving source instead.
