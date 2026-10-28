---
name: managing-self-driving-spend
description: >
  Explain and control what Self-driving (Inbox) costs. Use when the user asks what they spent on
  Self-driving, which signal sources or scouts drive that spend, how spend changes day to day,
  how many reports a source or scout produced, or how to lower or cap the spend. Breaks spend
  down by signal source, scout, and day, links it to the reports it produced, recommends changes
  ranked by savings, and applies them only after the user confirms each one. Trigger terms:
  inbox spend, self-driving cost, scout cost, why is my bill high, reduce inbox spend, billing
  limit, daily report limit, turn off a source, pause a scout.
---

# Managing Self-driving spend

Self-driving spend is shown in dollars. Do not assume a free tier.

Spend lives in two places. Together they make up the total you can measure.

| Where                                               | What it covers                                                                                 | How to read it                        |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------- |
| Signal metadata (`document_embeddings`)             | Everything done for a signal from a source: processing it, grouping it, researching its report | `total_spend` in cents on each signal |
| Scout runs (`system.scout_runs`, `scout-runs-list`) | Each scheduled scout run, including runs that find nothing                                     | `total_spend` in cents on each run    |

Divide cents by 100 and show dollars.
Spend on pull requests that Self-driving opens automatically is not in either place yet.
When you recommend a change to automatic pull requests, say that its saving is not measured.

## Workflow

1. **Scope.** Confirm the project and the date range. Default to the current billing period.
   Read the spend limit and current spend with `billing-limits-get`.
2. **Inventory.** List sources with `inbox-source-configs-list` and scouts with `scout-config-list`.
   Only discuss sources and scouts the project actually has turned on.
3. **By source.** Run "Spend by signal source" in [references/queries.md](references/queries.md).
4. **By scout.** Run "Spend by scout".
   Add "Signals created by scouts" to charge scout-emitted signals back to the scout.
5. **By day.** Run both daily queries and add them together.
   Look for spikes, then find the source or scout behind each one.
6. **Yield.** Run "Yield by signal source" and "Yield by scout".
   Yield is the share of settled reports that were resolved, and cost per resolved report matters more than raw spend.
7. **Inside each large source.** Run "Breakdown inside a source" for every source that holds more than 10% of signal spend.
   This finds the specific scanners, signal types, evaluations, alerts, or channels behind the spend, which is where most recommendations come from.
8. **Recommend.** Go through every control in [references/controls.md](references/controls.md) and decide whether it applies, using [references/recommendations.md](references/recommendations.md).
   Name the specific item to change, give a dollar figure, say what the user loses, and say whether you can apply it.
9. **Apply.** Change nothing without an explicit yes for that specific change.
   [references/controls.md](references/controls.md) lists the tool for each control, or where to change it in the app when no tool exists.
   Read the setting back after you change it.

Present the result with [references/report-template.md](references/report-template.md).

## Rules

- Read one embedding model only (`text-embedding-3-small-1536`) and `rendering = 'plain'`.
  Each signal is stored once per model, so reading every row counts its spend twice.
- Take the latest version of each signal with `argMax(..., inserted_at)` grouped by `document_id`.
  A signal's spend grows as its report is researched, and each update writes a new row.
- Leave out the `health_checks` and `engineering_analytics` sources. They have no spend.
- Spend from the last day or two can still grow. Say that the latest days are provisional.
- Reports need about 14 days to resolve, so measure yield on settled reports: reports first shown at least 14 days ago.
  Take them from the last 60 days, even when the spend period is shorter.
  When a source or scout has fewer than 20 settled reports, call its yield too new to judge, and recommend no cut that rests on it.
- A signal or run with entries in `spend_accounting_failed_stages` has incomplete spend.
  Report how many there are.
- A daily view buckets a signal's spend on the day the signal arrived and a run's spend on the day the run started.
  Totals over a whole period still add up.
- A scout that rarely creates reports can still be useful if it edits existing ones.
  Check `edited_report_ids` before you recommend pausing it.
- Never turn off error tracking ingestion or lower its rate limits to save Self-driving spend.
  That drops exception data permanently. Change the Self-driving source instead.
