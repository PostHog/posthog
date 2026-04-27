# Retention metrics playbook

For "week-1 retention regressed", "March cohort isn't coming back".

## 0. Config sanity check

- If `totalIntervals` exceeds the date range, the tail cells are always zero and look
  like a drop. Match `totalIntervals` to the range.
- The most recent cohort hasn't had its full retention window yet — note as partial
  rather than a regression.

## 1. Isolate the cohort

`targetEntity` / `returningEntity` use `{type: "events", name: "<event>"}` and nest in
`retentionFilter`. Compare affected cohort(s) to prior baselines side by side.

```json
posthog:query-retention
{
  "kind": "RetentionQuery",
  "dateRange": { "date_from": "-90d" },
  "retentionFilter": {
    "targetEntity": { "type": "events", "name": "$pageview" },
    "returningEntity": { "type": "events", "name": "$pageview" },
    "totalIntervals": 8,
    "period": "Week",
    "retentionType": "retention_first_time"
  }
}
```

## 2. Event vs. users

Is the drop in the activity event itself or in the cohort doing it? Create or reuse a
cohort for the affected period (`posthog:cohorts-create` / `-list`), then run
`posthog:query-trends` on the activity event filtered to that cohort.

## 3. Split the dropout

Run `posthog:query-lifecycle` scoped to the affected cohort to separate "never retained"
(new users who didn't return) from "lost later" (returning users who churned).
