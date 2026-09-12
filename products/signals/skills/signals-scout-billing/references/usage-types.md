# Billing field mechanics and where each usage type hands off

Read this when a meter has cleared the gates and you need to price it, quote a projection, or name the handoff.

## The billing period is the unit

`billing-overview-get` returns it as `billing_period` (`current_period_start` / `current_period_end`).
Every tiered product meters cumulatively **within** a period and resets at the boundary, so:

1. **Never compare spend across a period boundary day-for-day.** Identical usage bills higher early in a period, because the cheaper high-volume tiers have not been reached yet. Compare usage instead, or compare spend only at matched positions within a period.
2. **A spend move with flat usage is a tier crossing** until proven otherwise.
3. **Anything you cached from the overview goes stale at the rollover.** Store the period boundaries alongside any cached period figure and re-derive when `current_period_start` advances.
4. **Periods are not the same length.** Comparing a 31-day period's projected total against a 28-day period's actual shows a ~11% rise at an unchanged daily rate. Normalize both sides to a daily run rate — total ÷ days in that period — before treating a period-over-period difference as a trajectory finding.

The overview reflects the current period only. For history, use `billing-usage-get` / `billing-spend-get` with explicit dates.

## Three vocabularies for one meter

The same meter is named three ways across the tools, and none of them is a prefix of another:

- `billing-usage-get` keys series by **usage type** (`recording_count_in_period`) — the names in the routing table below.
- `billing-spend-get` with a `type` breakdown, and `billing-overview-get`'s `products[].type`, key by **product** (`session_replay`).
- `billing-overview-get`'s `products[].usage_key` and `usage_summary` key by a **short name** (`recordings`).
- `custom_limits_usd` takes **either**: look the product up by `type` first, then by `usage_key`, the order the billing UI resolves them. Checking only `type` misses the organizations whose limits are stored under the short name.

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
| `data_pipelines`                                 | `data_pipelines` (deprecated add-on)                        | —                       |

A usage type missing from this table is a new meter: route it by its `label`, and do not price it until the overview carries a product for it.

## Deriving the free tier — not just `free_allocation`

`free_allocation` is the free threshold only for **unsubscribed** products.
For a **subscribed** product with a tier schedule, the free threshold is the upper bound of the first tier when that tier is free — the product's `tiers[0].up_to` where `tiers[0].unit_amount_usd` **parses to zero**, and zero when the first tier is priced.
Compare the number, not the string: prices come back as decimal strings and a free tier ships as `"0.00"`, so a literal match against `"0"` reads it as paid and prices an entirely free spike as billable.
This matters: a subscribed product can ship `free_allocation: 0` while its first million units are free, so reading `free_allocation` alone classifies an entirely free usage jump as billable and files a false alarm.

```text
subscribed and float(tiers[0].unit_amount_usd) == 0  ->  free threshold = tiers[0].up_to
subscribed and tiers[0] is priced                    ->  free threshold = 0
not subscribed                                       ->  free threshold = free_allocation
```

**The marginal tier** — the one an extra unit is charged at right now — is the tier period-to-date usage currently sits in, not the first paid tier and not an average.
Each tier carries its own `current_usage` and `projected_usage`, so the marginal tier is the one with non-zero `current_usage` and headroom below `up_to`.

## Pricing a usage delta — a difference of two prices, not a multiplication

**Never price a delta as `delta × marginal rate`.** That is right only when the whole delta sits inside one tier, carries no discount, and is not capped — and it overstates the invoice impact whenever it does not, which is how a meter that adds $0 clears the materiality gate.

Price it as a difference:

```text
daily_step     = latest_day − same_weekday_median
days_observed  = complete days the step has already held (one, on the day you first see it)
days_remaining = days from the latest complete day to billing_period.current_period_end
with_step      = projected_usage
without_step   = max(0, projected_usage − daily_step × (days_observed + days_remaining))
impact         = price(with_step) − price(without_step)
```

where `price(units)` walks the tier schedule and charges each tier's `unit_amount_usd` for the units falling inside it (plus any `flat_amount_usd`), and `projected_usage` is the product's own forecast from the overview.

**Both scenarios hang off the same forecast — do not add the step back on top of it.** `projected_usage` extrapolates period-to-date usage, which already contains the step, so adding `daily_step × days_remaining` to it counts the step twice and slides _both_ endpoints up the tier curve together. The unit gap between them stays right, but its placement does not: a real 900 → 1,100 forecast priced as 1,000 → 1,200 charges 200 units above a 1,000-unit free threshold instead of 100, and manufactures invoice impact out of the shift alone. Take the service's forecast as the with-step endpoint and remove the step from it for every day it covers, observed and remaining.

**A falling meter has a negative `daily_step`, and the arithmetic has to survive it.** Clamp the without-step counterfactual at zero units — a negative unit count is not a quantity `price()` can charge — and test the **absolute** impact against the materiality floor, keeping the sign in the report. Otherwise a meter going dark produces a negative impact, fails a positive floor, and the capture-outage shape this scout promises to surface is silently suppressed.
This prices the move the way the report frames it — what the invoice does if the step persists — and the tier walk means a delta that crosses a boundary is charged at each tier's own rate. Then adjust in this order:

1. **Discount.** Apply `discount_percent`. At 100% the impact is $0 no matter how large the usage move — real, and a legitimate reason not to report.
2. **Spending cap.** If the product's `usage_limit` (its spending limit expressed in units — see below) already binds, the incremental usage is not billed at all. Cap the impact at the remaining headroom under that limit, which can be $0.

Report the adjusted figure. Keep **limit-risk reporting separate**: a meter whose impact is capped to $0 is not a materiality finding, but the fact that it is now pinned against a spending limit belongs in the trajectory lane.

Cache the tier schedule as `pattern:billing:tiers:<usage_type>` and re-derive when the plan changes.

**`usage_limit` is not the free tier either**, and it is not proof of a customer-set spending limit.
When the customer has set one, it is that `custom_limits_usd` amount converted into units at the tier schedule (a $50 events limit reads as `usage_limit: 2000000`), and `percentage_usage` is `current_usage / usage_limit`.
But a subscribed product can carry a plan or default `usage_limit` while `custom_limits_usd` is empty — the shipped discounted-billing fixture does exactly that — so **look the product up in `custom_limits_usd` before calling the ceiling a customer choice**.
Resolve the key the way the billing UI does: `custom_limits_usd[products[].type]` first, falling back to `custom_limits_usd[usage_key]`, since some organizations' limits are stored under the short name (`{"events": 200}`). Treat `0` as a real limit, not as absent.
Use them for the limit-crossing check in the trajectory lane; no `usage_limit` means no ceiling to check.

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

- `trial` — the newer object, with `status`, `type`, and `expires_at`. Prefer it when present; it carries the richer metadata.
- `free_trial_until` — the legacy timestamp. An organization on this representation has an active trial whenever the timestamp is in the future.

Checking only `trial` means organizations on the legacy field never get the trial-end warning.

**Forecast a post-trial charge only when the trial will actually convert into one.** A dollar forecast needs `trial.status` of `active` and `trial.type` of `autosubscribe` — that is the only shape where expiry automatically creates the paid subscription. A `standard` trial ends in a subscribe-or-lose-access choice, so frame its expiry as a decision the customer has coming, not an invoice. A cancelled or already-converted `trial` object is history, not a forecast.

## Where each usage type hands off

Your report names the owning scout and the drilldown surface. You do not run the drilldown yourself.

| Usage type                                                                                              | Reads as                          | Hand off to                                                                                                                                                                                                                                                                                                                                                        |
| ------------------------------------------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `event_count_in_period`                                                                                 | Events                            | `signals-scout-product-analytics`. Drilldown: top event names on the affected day, compared against a same-weekday baseline. A rising share for one event is a source-mix change; a stable share on higher totals is traffic growth                                                                                                                                |
| `enhanced_persons_event_count_in_period`                                                                | Identified events                 | Same as events, but the raw event-name breakdown does not cleanly explain the identified/anonymous split — say so rather than implying it does                                                                                                                                                                                                                     |
| `group_analytics`                                                                                       | Group analytics attribution       | Same as identified events. This is a product-specific view of that usage, not a separate stream                                                                                                                                                                                                                                                                    |
| `recording_count_in_period`, `mobile_recording_count_in_period`                                         | Session recordings                | `signals-scout-session-replay`. Look for a sampling-rate or SDK config change before anything else                                                                                                                                                                                                                                                                 |
| `billable_feature_flag_requests_count_in_period`                                                        | `/flags` API requests             | `signals-scout-feature-flags`. The billable unit is the API request, **not** the `$feature_flag_called` event — never suggest suppressing that event to cut the bill                                                                                                                                                                                               |
| `exceptions_captured_in_period`                                                                         | Exceptions                        | `signals-scout-error-tracking`. One dominant new issue usually explains the whole step                                                                                                                                                                                                                                                                             |
| `survey_responses_count_in_period`                                                                      | Survey responses                  | `signals-scout-surveys`. Separate reach (`survey shown`) from response rate (`survey sent`)                                                                                                                                                                                                                                                                        |
| `ai_event_count_in_period`                                                                              | AI observability                  | `signals-scout-ai-observability`. This is the customer's own `$ai_*` telemetry in their project. Break down by model and provider                                                                                                                                                                                                                                  |
| `ai_credits_used_in_period`                                                                             | PostHog AI (Max) credits          | **No sibling scout owns this** — these credits are metered from PostHog's own regional projects, not from the customer's `$ai_*` events, so the AI-observability scout would close out finding nothing. Attribute it by project from the billing breakdown, name the people-using-Max explanation in the report yourself, and point at the billing usage dashboard |
| `rows_synced_in_period`                                                                                 | Warehouse synced rows             | `signals-scout-data-warehouse`. Check for a newly enabled schema, a source switched off incremental, or a backfill                                                                                                                                                                                                                                                 |
| `free_historical_rows_synced_in_period`                                                                 | Historical synced rows            | Backfill activity by definition. Record the window; this is rarely a finding                                                                                                                                                                                                                                                                                       |
| `rows_exported_in_period`                                                                               | Batch export rows                 | `signals-scout-data-pipelines`. Look for a newly enabled export or a changed destination                                                                                                                                                                                                                                                                           |
| `cdp_billable_invocations_in_period`                                                                    | Destination trigger events        | `signals-scout-data-pipelines`. A filter widened on a destination is the usual cause                                                                                                                                                                                                                                                                               |
| `workflow_emails_sent_in_period`, `workflow_billable_invocations_in_period`                             | Workflow sends / dispatches       | `signals-scout-data-pipelines`. Keep email volume separate from destination dispatches                                                                                                                                                                                                                                                                             |
| `logs_mb_in_period`, `logs_retention_30d_mb_in_period`                                                  | Logs ingested (MB)                | `signals-scout-logs`. A log level turned up in a deploy is the classic overnight step; retention tier is a setting, not extra content                                                                                                                                                                                                                              |
| `signals_credits_used_in_period`                                                                        | Inbox credits                     | The Signals inbox — which includes this scout. Surface the loop once, plainly                                                                                                                                                                                                                                                                                      |
| `replay_vision_credits_used_in_period`                                                                  | Replay Vision credits             | `signals-scout-replay-vision`. Credits come from scanner observations, so check scanner scope and sampling                                                                                                                                                                                                                                                         |
| `posthog_code_credits_used_in_period`, `posthog_code_token_credits_used_in_period`, `sandbox_compute_*` | PostHog Desktop / sandbox compute | `signals-scout-tasks`. Sandbox CPU and memory meters are diagnostics, rarely the headline                                                                                                                                                                                                                                                                          |
| `data_pipelines`                                                                                        | Legacy attribution view           | Route by whichever surface actually produced the usage                                                                                                                                                                                                                                                                                                             |

Two rules hold across every row: check the inbox before naming a handoff — the owning scout may already have the root-cause report, in which case your billing angle is an `append_note` on theirs — and never suggest disabling instrumentation to cut a bill without saying what visibility that costs.
