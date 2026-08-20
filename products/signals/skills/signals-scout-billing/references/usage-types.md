# Billing field mechanics and where each usage type hands off

Read this when a meter has cleared the gates and you need to price it, quote a projection, or name the handoff.

## The billing period is the unit

`billing-overview-get` returns it as `billing_period` (`current_period_start` / `current_period_end`).
Every tiered product meters cumulatively **within** a period and resets at the boundary, so:

1. **Never compare spend across a period boundary day-for-day.** Identical usage bills higher early in a period, because the cheaper high-volume tiers have not been reached yet. Compare usage instead, or compare spend only at matched positions within a period.
2. **A spend move with flat usage is a tier crossing** until proven otherwise.
3. **Anything you cached from the overview goes stale at the rollover.** Store the period boundaries alongside any cached period figure and re-derive when `current_period_start` advances.

The overview reflects the current period only. For history, use `billing-usage-get` / `billing-spend-get` with explicit dates.

## Three vocabularies for one meter

The same meter is named three ways across the tools, and none of them is a prefix of another:

- `billing-usage-get` keys series by **usage type** (`recording_count_in_period`) — the names in the routing table below.
- `billing-spend-get` with a `type` breakdown, and `billing-overview-get`'s `products[].type` and `custom_limits_usd`, key by **product** (`session_replay`).
- `billing-overview-get`'s `products[].usage_key` and `usage_summary` key by a **short name** (`recordings`).

Match a usage type to its product through this table before pricing it or reading its spending limit. Add-on meters (identified events, group analytics, mobile recordings, 30-day log retention, historical rows) live under the parent product's `addons[]` in the overview and as their own product key in spend.

| Usage type                                       | Product key (spend, `products[].type`, `custom_limits_usd`) | `usage_key`             |
| ------------------------------------------------ | ----------------------------------------------------------- | ----------------------- |
| `event_count_in_period`                          | `product_analytics`                                         | `events`                |
| `enhanced_persons_event_count_in_period`         | `enhanced_persons` (add-on)                                 | —                       |
| `group_analytics`                                | `group_analytics` (add-on)                                  | —                       |
| `recording_count_in_period`                      | `session_replay`                                            | `recordings`            |
| `mobile_recording_count_in_period`               | `mobile_replay` (add-on)                                    | `mobile_recordings`     |
| `billable_feature_flag_requests_count_in_period` | `feature_flags`                                             | `feature_flag_requests` |
| `exceptions_captured_in_period`                  | `error_tracking`                                            | `exceptions`            |
| `survey_responses_count_in_period`               | `surveys`                                                   | `survey_responses`      |
| `ai_event_count_in_period`                       | `llm_analytics`                                             | `llm_events`            |
| `ai_credits_used_in_period`                      | `posthog_ai`                                                | `ai_credits`            |
| `rows_synced_in_period`                          | `data_warehouse`                                            | `rows_synced`           |
| `free_historical_rows_synced_in_period`          | `data_warehouse_historical` (add-on)                        | —                       |
| `rows_exported_in_period`                        | `batch_exports`                                             | `rows_exported`         |
| `cdp_billable_invocations_in_period`             | `realtime_destinations`                                     | `cdp_trigger_events`    |
| `workflow_emails_sent_in_period`                 | `workflows_emails`                                          | `workflow_emails`       |
| `workflow_billable_invocations_in_period`        | `workflows_destinations` (add-on)                           | —                       |
| `logs_mb_in_period`                              | `logs`                                                      | `logs_mb_ingested`      |
| `logs_retention_30d_mb_in_period`                | `logs_retention_30d` (add-on)                               | —                       |
| `signals_credits_used_in_period`                 | `inbox`                                                     | `signals_credits`       |
| `replay_vision_credits_used_in_period`           | `replay_vision`                                             | `replay_vision_credits` |
| `posthog_code_credits_used_in_period`            | `posthog_code_usage`                                        | `posthog_code_credits`  |

A usage type missing from this table is a new meter: route it by its `label`, and do not price it until the overview carries a product for it.

## Deriving the free tier — not just `free_allocation`

`free_allocation` is the free threshold only for **unsubscribed** products.
For a **subscribed** product with a tier schedule, the free threshold is the upper bound of the first tier when that tier is free — the product's `tiers[0].up_to` where `tiers[0].unit_amount_usd` is `"0"`, and zero when the first tier is priced.
This matters: a subscribed product can ship `free_allocation: 0` while its first million units are free, so reading `free_allocation` alone classifies an entirely free usage jump as billable and files a false alarm.

```text
subscribed and tiers[0].unit_amount_usd == "0"  ->  free threshold = tiers[0].up_to
subscribed and tiers[0] is priced               ->  free threshold = 0
not subscribed                                   ->  free threshold = free_allocation
```

**The marginal rate** — what an extra unit actually costs right now — is the `unit_amount_usd` of the tier that period-to-date usage currently sits in, not the first paid tier and not an average.
Each tier carries its own `current_usage` and `projected_usage`, so the tier with non-zero `current_usage` and headroom below `up_to` is the marginal one.
Price a usage delta at that rate. Cache both the threshold and the marginal rate as `pattern:billing:tiers:<usage_type>` and re-derive when the plan changes.

**`usage_limit` is not the free tier either.** On a subscribed product it is the customer's `custom_limits_usd` spending limit converted into units at the tier schedule (a $50 events limit reads as `usage_limit: 2000000`), and `percentage_usage` is `current_usage / usage_limit`.
Use them for the limit-crossing check in the trajectory lane; `null` means no spending limit is set on that product.

## Which projection field to quote

The overview carries four projections. They are not interchangeable:

| Field                                                  | What it is                                                     |
| ------------------------------------------------------ | -------------------------------------------------------------- |
| `projected_total_amount_usd`                           | Uncapped, before discount                                      |
| `projected_total_amount_usd_after_discount`            | Uncapped, after discount                                       |
| `projected_total_amount_usd_with_limit`                | Capped by the customer's spending limits, before discount      |
| `projected_total_amount_usd_with_limit_after_discount` | Capped by spending limits, after discount — **the max charge** |

**Quote a `*_with_limit*` field when forecasting the invoice**, matching the discount case: the product's own billing summary shows the capped figure and tells customers it is the maximum they will be charged.
Where a spending limit applies, the uncapped projection is a hypothetical the customer will never be billed, so reporting it overstates their invoice.
Reserve the uncapped projection for limit-risk analysis — the gap between capped and uncapped _is_ the amount of usage a limit is about to cut off.

## What crossing a limit actually costs — say "may", not "will"

Exceeding a `custom_limits_usd` spending limit usually means PostHog stops ingesting that product's data, but not always: an organization flagged `never_drop_data` has exceeded limits ignored for every resource outside a small exempt set (AI credits, Signals credits, Replay Vision credits, PostHog Desktop credits), and trust-based grace periods can also defer the cut-off.

The billing MCP tool **strips `never_drop_data` from the overview response**, so a scout cannot tell which case an organization is in.
Write the consequence as a possibility — "may stop ingesting", "features may stop" — never as a certainty. Overstating it in a customer-facing report is worse than under-claiming.

## Trials come in two shapes

Both are supported and the older one is checked first elsewhere in the product:

- `trial` — the newer object, with `status` and `expires_at`. Prefer it when present; it carries the richer metadata.
- `free_trial_until` — the legacy timestamp. An organization on this representation has an active trial whenever the timestamp is in the future.

Checking only `trial` means organizations on the legacy field never get the trial-end warning.

## Where each usage type hands off

Your report names the owning scout and the drilldown surface. You do not run the drilldown yourself.

| Usage type                                                                                              | Reads as                          | Hand off to                                                                                                                                                                                                                         |
| ------------------------------------------------------------------------------------------------------- | --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `event_count_in_period`                                                                                 | Events                            | `signals-scout-product-analytics`. Drilldown: top event names on the affected day, compared against a same-weekday baseline. A rising share for one event is a source-mix change; a stable share on higher totals is traffic growth |
| `enhanced_persons_event_count_in_period`                                                                | Identified events                 | Same as events, but the raw event-name breakdown does not cleanly explain the identified/anonymous split — say so rather than implying it does                                                                                      |
| `group_analytics`                                                                                       | Group analytics attribution       | Same as identified events. This is a product-specific view of that usage, not a separate stream                                                                                                                                     |
| `recording_count_in_period`, `mobile_recording_count_in_period`                                         | Session recordings                | `signals-scout-session-replay`. Look for a sampling-rate or SDK config change before anything else                                                                                                                                  |
| `billable_feature_flag_requests_count_in_period`                                                        | `/flags` API requests             | `signals-scout-feature-flags`. The billable unit is the API request, **not** the `$feature_flag_called` event — never suggest suppressing that event to cut the bill                                                                |
| `exceptions_captured_in_period`                                                                         | Exceptions                        | `signals-scout-error-tracking`. One dominant new issue usually explains the whole step                                                                                                                                              |
| `survey_responses_count_in_period`                                                                      | Survey responses                  | `signals-scout-surveys`. Separate reach (`survey shown`) from response rate (`survey sent`)                                                                                                                                         |
| `ai_event_count_in_period`, `ai_credits_used_in_period`                                                 | AI observability / PostHog AI     | `signals-scout-ai-observability`. Break down by model and provider                                                                                                                                                                  |
| `rows_synced_in_period`                                                                                 | Warehouse synced rows             | `signals-scout-data-warehouse`. Check for a newly enabled schema, a source switched off incremental, or a backfill                                                                                                                  |
| `free_historical_rows_synced_in_period`                                                                 | Historical synced rows            | Backfill activity by definition. Record the window; this is rarely a finding                                                                                                                                                        |
| `rows_exported_in_period`                                                                               | Batch export rows                 | `signals-scout-data-pipelines`. Look for a newly enabled export or a changed destination                                                                                                                                            |
| `cdp_billable_invocations_in_period`                                                                    | Destination trigger events        | `signals-scout-data-pipelines`. A filter widened on a destination is the usual cause                                                                                                                                                |
| `workflow_emails_sent_in_period`, `workflow_billable_invocations_in_period`                             | Workflow sends / dispatches       | `signals-scout-data-pipelines`. Keep email volume separate from destination dispatches                                                                                                                                              |
| `logs_mb_in_period`, `logs_retention_30d_mb_in_period`                                                  | Logs ingested (MB)                | `signals-scout-logs`. A log level turned up in a deploy is the classic overnight step; retention tier is a setting, not extra content                                                                                               |
| `signals_credits_used_in_period`                                                                        | Inbox credits                     | The Signals inbox — which includes this scout. Surface the loop once, plainly                                                                                                                                                       |
| `replay_vision_credits_used_in_period`                                                                  | Replay Vision credits             | `signals-scout-replay-vision`. Credits come from scanner observations, so check scanner scope and sampling                                                                                                                          |
| `posthog_code_credits_used_in_period`, `posthog_code_token_credits_used_in_period`, `sandbox_compute_*` | PostHog Desktop / sandbox compute | `signals-scout-tasks`. Sandbox CPU and memory meters are diagnostics, rarely the headline                                                                                                                                           |
| `data_pipelines`                                                                                        | Legacy attribution view           | Route by whichever surface actually produced the usage                                                                                                                                                                              |

Two rules hold across every row: check the inbox before naming a handoff — the owning scout may already have the root-cause report, in which case your billing angle is an `append_note` on theirs — and never suggest disabling instrumentation to cut a bill without saying what visibility that costs.
