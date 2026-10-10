# What happens when an inbox report's issue recurs

When a new signal matches an existing report, the grouping stage decides whether the report absorbs it or a fresh report starts.
The source of truth is `products/signals/backend/recurrence.py` and `FIXED_DISMISSAL_REASONS` in `products/signals/backend/artefact_schemas.py`.
If this file and the code disagree, the code is right.

- **`resolved`, with any reason.** The report is terminal.
  A matching signal starts a fresh `potential` report with a `recurrence_of` link back to it, and the research agent gets the old report as context.
- **`suppressed` with a fixed reason** (`already_fixed`, `fixed_outside_posthog`, `pr_merged`).
  The reason claims the issue is gone, so a recurrence contradicts it and starts a fresh linked report, the same as `resolved`.
  Only the latest dismissal counts: a later `wontfix_*` on the same report overrides an earlier `already_fixed`.
- **`suppressed` with any other reason.** The report is a sink.
  Matching signals raise its signal count, but it never promotes again, no new report starts, and nobody is told.
  Pick one of these reasons only when that silence is the intended result, and say so to the user when you dismiss for them.
- **`potential` (snoozed).** The report keeps collecting signals and promotes itself again once it passes the weight threshold and any `snooze_for` count.
  It is the same report, not a new linked one.

## Example: a problem that stopped without a fix

For a problem that stopped without a fix and should come back as a new report if it returns, resolve with `other` and a note.
A suppress with `other` would absorb the recurrence silently.

```json
inbox-reports-set-state
{
  "id": "<report_uuid>",
  "state": "resolved",
  "dismissal_reason": "other",
  "dismissal_note": "Stopped without a fix: the error rate went back to baseline when the upstream outage ended. Resolved so that a recurrence opens a new report."
}
```
