# Judging a quiet internal destination

An `internal_destination` is a hog function whose filters carry `source: "internal-events"`.
It never consumes captured customer events.
It consumes product lifecycle actions PostHog publishes on its own internal stream — an error tracking issue opening, an alert firing, a batch export run failing, an activity-log entry landing.
Those actions are not ingested into ClickHouse, so they are absent from the project's event taxonomy and `execute-sql` against `events` cannot see them.

Read this before judging any internal destination whose `triggered` sits at ~zero.

## Why an events count proves nothing here

The internal stream matches in two stages.
The consumer first drops every function whose filters don't name the incoming event id, recording no metric for those.
Only functions that matched by event id run the full filter, and only that stage records `filtered`.
Two consequences:

- **An `events` count on the filter's event id returns zero every time** — for a healthy destination and a starved one alike. Reading that zero as "the upstream event stopped firing" files a report on a destination that is working.
- **The captured-event starvation shape never reproduces.** When the lifecycle action stops, `triggered` and `filtered` fall to zero together; `filtered` does not keep flowing. A quiet internal destination looks identical whether the action stopped happening or the delivery path broke.

The inverse is useful. `filtered` above zero **is** lifecycle evidence: the event id matched, so the action fired and a property filter rejected it. That destination is not starving.

## The procedure

For an enabled internal destination with `triggered` ~zero over the window:

1. Read the event ids from `filters.events[].id` (`cdp-functions-retrieve`). The id names the product action.
2. Establish whether that action happened in the same window, from the product's own read-only surface (table below).
3. Compare the action's time against `triggered` and `succeeded`:
   - Action happened, `triggered` stayed at zero → a real delivery gap. The destination is armed and the platform never invoked it. Report it.
   - Action did not happen → baseline quiet. Skip; nothing is broken.
   - Neither confirmable → scratchpad memory, not a report.
   - Action happened, `triggered` rose, `succeeded` did not follow → not starvation at all. That is the delivery-failure path; read the logs and report the error class.

Most internal destinations carry alert and notification routing, so a confirmed gap means people were not told something PostHog knew.
P2 by default, P1 when the silent stream is an alert path the team is on call for.

## Lifecycle evidence per event

| Filter event id                                                                                                     | Product action                              | Read-only evidence                                                    |
| ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- | --------------------------------------------------------------------- |
| `$error_tracking_issue_created` / `_reopened` / `_spiking`                                                          | An issue opened, reopened, or began spiking | `query-error-tracking-issues-list` — first/last seen in window        |
| `$error_tracking_issue_resolved` / `_suppressed` / `_assigned` / `_unassigned` / `_merged` / `_split`               | Someone triaged an issue                    | `advanced-activity-logs-list` on the error tracking scopes            |
| `$insight_alert_firing`, and any `$<product>_alert_firing` / `_resolved` / `_errored` / `_auto_disabled` / `_match` | An alert check breached or cleared          | `alerts-list`, then `alert-get` for the firing checks                 |
| `$logs_alert_firing` / `_resolved` / `_errored` / `_auto_disabled`                                                  | A log alert changed state                   | `logs-alerts-list`, `logs-alerts-events-list`                         |
| `$health_check_issue_firing` / `_resolved`                                                                          | A health check opened or cleared an issue   | `health-issues-summary`, `health-issues-list`                         |
| `$activity_log_entry_created`                                                                                       | An audited config change landed             | `advanced-activity-logs-list`, scoped to the `scope` the filter names |
| `$discussion_mention_created`                                                                                       | Someone was mentioned in a comment          | `comments-list`                                                       |
| `$batch_export_run_failed` / `_completed` / `_cancelled` / `_failed_billing`, `$batch_export_paused`                | A batch export run ended                    | `batch-export-get` — the `latest_runs` you already read               |
| `$experiment_metric_significant`                                                                                    | An experiment metric reached significance   | `experiment-get-all`, `experiment-get`                                |
| `$early_access_feature_updated`                                                                                     | An early access feature changed stage       | `early-access-feature-list`                                           |

An event id missing from this table follows the same rule: the id names a product surface, so reach for that product's own read-only list tool.
Some actions originate outside PostHog and have no such surface — `$slack_message_received` and `$github_event_received` are inbound third-party deliveries, unprovable from inside a run. Remember those, never report them.
