# Common causes

Hypothesis taxonomy with confirming queries. Rank by evidence count when writing findings.

## Release / deploy / flag rollout

A version, flag, or experiment shipped near the anomaly start.

- Breakdown on `app_version` / `$lib_version` — shift concentrated in one version is
  strong evidence.
- For a flag: breakdown on `$feature/<flag_key>` separates exposed from control.

Suggest pausing or reverting; offer `posthog:annotation-create` if no annotation exists.

## Marketing / traffic-source shift

A campaign started or ended, or source mix changed.

- Breakdown on `utm_source`, `utm_medium`, `utm_campaign`, `$referring_domain`.
- A composition change can leave overall count stable while conversion moves —
  break the conversion metric down by source.

## Tracking regression

The measurement changed, not the metric.

- Total events vs. unique users — stable users + falling events = fire condition changed.
- An adjacent stable event while the target fell = target's tracking changed.
- Breakdown on `$lib_version` — concentrated drop = SDK regression.
- `posthog:read-data-schema` (`kind: "events"`) for recently renamed / deprecated events.

## Cohort / lifecycle shift

Same product, different mix of users. New-user influx pulls engagement metrics down.

- `posthog:query-lifecycle` — change in new / returning / resurrecting / dormant mix.
- `posthog:query-retention` comparing affected-period cohorts to prior.

Split the metric per lifecycle status in findings.

## Seasonality / day-of-week artifact

Weekend dip, holiday trough, end-of-quarter spike. The
[`compare_to_prior_periods.py`](../scripts/compare_to_prior_periods.py) script catches
this directly.

## Platform / device / browser-specific

JS error on a Safari release, mobile crash on a specific OS, regional CDN issue.

- Breakdown on `$browser`, `$browser_version`, `$os`, `$device_type`, `$geoip_country_code`.
- Cross-check with `posthog:error-tracking-issues-list`.

## Rate limit / upstream outage

A consumer hit a quota or an upstream dependency degraded.

- `posthog:query-trends` on API error events.
- `posthog:query-logs` for an error surge in the window.

## Upstream data integration

For warehouse-backed metrics: schema change, pipeline failure, view altered. The
investigation tools can't confirm this directly — flag as a candidate when no product-side
cause fits and recommend the user check pipeline health.
