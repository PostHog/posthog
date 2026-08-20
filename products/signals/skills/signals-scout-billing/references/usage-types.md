# Usage types, tier mechanics, and where each handoff goes

Read this when a pair has cleared the gates and you need to size it in dollars or name the handoff.

## Tier and period mechanics

The billing period, not the calendar month, is the unit. `billing-overview-get` returns it as `billing_period`.

Every tiered product meters cumulatively **within** a period and resets at the boundary:

- The first tier is usually free (`free_allocation`). Usage inside it bills at zero, so a large percentage move there is worth nothing.
- Paid tiers step **down** in unit price as volume climbs. The same extra 1M events costs more in a period's first week than in its last.
- `products[].percentage_usage` is progress against `usage_limit`; `custom_limits_usd` is a spending cap the customer set themselves, and crossing it means PostHog stops ingesting that product's data.

Three consequences for scoring:

1. **Never compare spend across a period boundary day-for-day.** Compare usage, or compare same-day-of-period.
2. **A spend move with flat usage is a tier crossing** until proven otherwise. Check `tiers` before calling it anything else.
3. **Size a step at the org's current tier position**, not at list price. A pair sitting deep in a cheap tier moves the invoice far less than its percentage suggests.

The overview response is the current period only. For anything historical, use `billing-usage-get` / `billing-spend-get` with explicit dates.

## Where each usage type hands off

Your report names the owning scout and the drilldown surface. You do not run the drilldown yourself.

| Usage type                                                          | Reads as                       | Hand off to                                                                                    |
| ------------------------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------ |
| `event_count_in_period`                                             | Events                         | `signals-scout-product-analytics`. Drilldown: top event names on the affected project and day, compared against a same-weekday baseline. A rising share for one event is a source-mix change; a stable share on higher totals is traffic growth |
| `enhanced_persons_event_count_in_period`                            | Identified events              | Same as events, but the raw event-name breakdown does not cleanly explain the identified/anonymous split — say so rather than implying it does |
| `group_analytics`                                                   | Group analytics attribution    | Same as identified events. This is a product-specific view of that usage, not a separate stream |
| `recording_count_in_period`, `mobile_recording_count_in_period`     | Session recordings             | `signals-scout-session-replay`. Look for a sampling-rate or SDK config change before anything else |
| `billable_feature_flag_requests_count_in_period`                    | `/flags` API requests          | `signals-scout-feature-flags`. The billable unit is the API request, **not** the `$feature_flag_called` event — never suggest suppressing that event to cut the bill |
| `exceptions_captured_in_period`                                     | Exceptions                     | `signals-scout-error-tracking`. One dominant new issue usually explains the whole step         |
| `survey_responses_count_in_period`                                  | Survey responses               | `signals-scout-surveys`. Separate reach (`survey shown`) from response rate (`survey sent`)    |
| `ai_event_count_in_period`, `ai_credits_used_in_period`             | AI observability / PostHog AI  | `signals-scout-ai-observability`. Break down by model and provider                              |
| `rows_synced_in_period`                                             | Warehouse synced rows          | `signals-scout-data-warehouse`. Check for a newly enabled schema, a source switched off incremental, or a backfill |
| `free_historical_rows_synced_in_period`                             | Historical synced rows         | Backfill activity by definition. Record the window; this is rarely a finding                    |
| `rows_exported_in_period`                                           | Batch export rows              | `signals-scout-data-pipelines`. Look for a newly enabled export or a changed destination        |
| `cdp_billable_invocations_in_period`                                | Destination trigger events     | `signals-scout-data-pipelines`. A filter widened on a destination is the usual cause            |
| `workflow_emails_sent_in_period`, `workflow_billable_invocations_in_period` | Workflow sends / dispatches | `signals-scout-data-pipelines`. Keep email volume separate from destination dispatches       |
| `logs_mb_in_period`, `logs_retention_30d_mb_in_period`              | Logs ingested (MB)             | `signals-scout-logs`. A log level turned up in a deploy is the classic overnight step; retention tier is a setting, not extra content |
| `signals_credits_used_in_period`                                    | Inbox credits                  | The Signals inbox — which includes this scout. Surface the loop once, plainly                   |
| `replay_vision_credits_used_in_period`                              | Replay Vision credits          | `signals-scout-replay-vision`. Credits come from scanner observations, so check scanner scope and sampling |
| `posthog_code_credits_used_in_period`, `posthog_code_token_credits_used_in_period`, `sandbox_compute_*` | PostHog Desktop / sandbox compute | `signals-scout-tasks`. Sandbox CPU and memory meters are diagnostics, rarely the headline |
| `data_pipelines`                                                    | Legacy attribution view        | Route by whichever surface actually produced the usage                                          |

Two rules that hold across every row: check the inbox before naming a handoff — the owning scout may already have the root-cause report, in which case your billing angle is an `append_note` on theirs — and never suggest disabling instrumentation to cut a bill without saying what visibility that costs.
