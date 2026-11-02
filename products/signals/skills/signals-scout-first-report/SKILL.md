---
name: signals-scout-first-report
scout-display-name: First report
description: >
  Runs once after Self-Driving activation to find one valuable, actionable finding
  in a project's existing product and warehouse data.
allowed_tools:
  - emit_report
metadata:
  owner_team: signals
---

# Find the first useful report

Run one bounded investigation of this project's existing data. Publish at most one report that helps the customer take a worthwhile action now. Returning no report is a successful outcome when the evidence does not justify one. Aim to finish within five minutes; the run has a 20-minute ceiling.

## Orient and decide whether there is enough data

Start from the ranked PostHog sources in the First-report project context at the end of the run prompt. Configured sources do not prove usable data, and unlisted sources are not proven empty. Verify a promising unknown with a bounded query. Fetch the full project profile only if missing or stale context blocks an investigation. When warehouse tables are connected, discover relevant tables on demand; a new connection may contain substantial history, and a warehouse-only project is worth investigating.

A handful of isolated observations without useful history usually calls for `insufficient_data`. Confirm any promising alternative source, then finish with the specific missing evidence. Missing pageviews, identities, sessions, or downstream events in a small sample do not prove broken tracking. Intentional server-side capture or limited instrumentation can explain them. Small samples can establish a directly observed defect, such as failed deliveries with an explicit error, but cannot establish a population-wide conversion or retention regression.

This one-time investigation takes precedence over recurring patrol and watchlist guidance. This scout has no future scheduled run. Do not build watchlists, maintain the fleet, or wait for another scout. Specialist ownership does not restrict this investigation. Give brief progress updates when you check a lead, validate it, or change direction; present unverified leads as questions, without invented completion percentages or time estimates.

## Choose a finding that is worth acting on

Prioritize available sources by their likely usefulness:

1. **Error tracking:** high-impact issues, failing user flows, and affected users.
2. **Logs, traces, and metrics:** unnoticed failures, diagnostic evidence, and reliability or performance regressions.
3. **Product analytics and dashboards:** meaningful outcome changes and data drops. Use activity logs to find analyses the team has been creating or changing, then inspect their queries and results to understand which workflows matter.
4. **AI observability:** unusual agent behavior, failed or repeated tool calls, and unexpected cost or latency.
5. **Session recordings:** UX/UI struggles. Recordings can consume many tokens, so start with aggregates and inspect a small, targeted sample when it can answer a concrete question.

This order is a starting point, not a requirement to exhaust each source. Follow the strongest evidence. When a lead looks promising, combine sources to validate it and establish impact: connect an error to logs or traces, measure affected users and outcomes in product analytics, or inspect relevant recordings to understand the user experience. Match users, sessions, trace IDs, and time windows where available; coincident changes alone do not establish causation. Use connected warehouse data when it can establish business impact. A persistent problem can be valuable without a recent anomaly.

Rank evidence of impact ahead of the size of a percentage change. Prefer a directly observed user-facing failure with affected users or worse outcomes over an unexplained volume cliff. When both coexist, investigate the failure; the data gap may limit what you can say about recovery.

**An unexplained data pattern is not enough to publish.** A stream ending, missing optional metadata, an unusual cohort, or a suggestive property name does not establish a defect. For a tracking or data-quality report, directly verify a broken expectation and a concrete affected workflow: for example, an enabled delivery repeatedly failing, or a required input preventing an active analysis from running. Merely finding a saved chart that uses an event does not prove the event stream is wrong. If the only next step is to identify the source or ask whether the traffic was intentional, record that uncertainty in the close-out and publish nothing. Do not recommend excluding users just because their metadata is unusual.

Stop exploring once one candidate is validated. If the strongest leads do not survive validation, finish without a report instead of expanding into a general instrumentation audit.

## Establish a small set of facts

Before writing, collect the few facts needed to explain the finding: population, period, measured outcome, denominator, comparison, and a source the customer can inspect.

- For a conversion claim, use a supported funnel or build the entry cohort first and count those same users' later successes within a defined follow-up window. Exclude entries that have not had the full window. Ratios of independent success and entry counts are not funnels.
- Keep events, users, sessions, and attempts separate. An attempt failure rate requires recorded attempts and outcomes; otherwise report error counts or affected users. Check whether affected users also succeeded.
- Compare complete, comparable windows in the project's timezone. Compare retention and cumulative activity at equal cohort ages. For a change, check the same segment before it and an unaffected segment where available; consider traffic mix, experiments, launches, and ingestion completeness.
- Match every sentence to the exact scope of its supporting query. An all-project statistic cannot become a statistic about one browser or cohort in the prose. Recompute percentages, differences, and ranges from the returned values.
- Separate the observation from its explanation. A release association or stack frame identifies a place to investigate. It does not prove a code cause or exclude other causes. State only observed recovery and retries within the queried window.

Search for an existing report covering the candidate before emitting. A useful next step can be a targeted reproduction, an operational decision, or a product decision; a code fix and GitHub access are not prerequisites. Respect the customer's implementation settings.

## Publish a short, factual report

Keep the report body to **250 words**, including its table. Use this structure:

1. **Observed result:** one sentence stating the measured problem, affected population, and period. Use that same observation for the title. A measured decline or a count of affected users is enough; do not add an unverified cause to make it sound decisive.
2. **Evidence:** a compact comparison table or a few bullets containing the verified counts, denominators, windows, and inspectable sources. Include relevant successful outcomes. Attach a chart when it helps explain the finding.
3. **Limit:** the most important uncertainty or missing observation that affects interpretation.
4. **Next action:** one specific check or action justified by those facts. When the cause is unknown, name what to reproduce or inspect, without prescribing a speculative repair.

Include only facts needed for this one finding. Omit secondary discoveries, imagined business losses, and an account of the investigation. Check the exact title and body against the evidence before publishing: no universal failure claim when successes exist, no borrowed statistic from another population, and no follow-up beyond the available history. Remove unsupported claims; a caveat later in the report does not repair them. If removing them leaves no worthwhile finding, publish nothing. The first saved report is already visible to the customer.

## Finish explicitly

Always return the harness's structured close-out, including when no report was created. Prose alone leaves the customer's investigation incomplete.

- `report_created`: the report tool returned a persisted report. The server checks visibility before showing success.
- `insufficient_data`: observations or history cannot support a reliable finding; name the missing evidence in `missing_data`.
- `no_actionable_finding`: you completed the investigation with enough data, but no finding met the quality threshold.
- `incomplete`: access, failed queries, or the time budget prevented a conclusion. Do not describe these as insufficient customer data.

For example, an insufficient-data close-out has this shape. Replace the text and products with what you actually checked, and choose the outcome that matches the investigation:

```json
{
  "summary": "Recorded activity is too sparse to validate a useful finding. No report was created.",
  "first_report_result": {
    "outcome": "insufficient_data",
    "checked_products": ["product_analytics"],
    "missing_data": ["More observations of the entry step and subsequent outcomes over comparable periods"]
  }
}
```

Keep the close-out factual and concise. Do not emit a placeholder report to explain an empty result.
