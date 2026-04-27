# Common causes of metric changes

Use this taxonomy to generate hypotheses once the affected segment is known from the
metric-type-specific playbook. Each entry pairs a cause with the confirming query.

When writing the findings report, rank hypotheses by how many pieces of evidence support them.

## Release / deploy / flag rollout

A new version, feature flag, or experiment shipped near the start of the anomaly window and
introduced a regression or change in behavior.

**Discover candidates** in SKILL.md Step 2.3 (feature flags via `feature-flag-get-all`,
experiments via `experiment-get-all`, deploys via `annotations-list`).

**Confirm with:**

- `posthog:query-trends` with a breakdown on `properties.app_version` / `properties.$lib_version` —
  a metric shift concentrated in one version is strong evidence of a release regression.
- For a flag rollout: breakdown on `properties.$feature/<flag_key>` separates exposed from
  control users cleanly.

**Remediation**: share the identified version / flag / experiment with the owning team. For a
deploy-related cause without an existing annotation, offer to create one via
`posthog:annotation-create` so future investigations find it faster. For a flag rollout,
suggest pausing or reverting the variant split.

## Marketing campaign or traffic-source shift

A campaign started or ended, or a traffic source changed, moving the mix of users entering
the funnel.

**Confirm with:**

- `posthog:query-trends` breakdown on `properties.utm_source`, `utm_medium`, `utm_campaign`, or
  `$referring_domain`.
- If the shift is a composition change (same users, different source labels), overall count may
  be stable while conversions move because of source mix. Run the conversion metric with a
  `utm_source` breakdown to confirm.

**Remediation**: flag to the marketing team. Offer to save a by-source insight for ongoing
monitoring.

## Tracking regression

The metric didn't change — the measurement did. An event was renamed, removed, or started
firing under different conditions.

**Confirm with:**

- Sanity check: total event count vs. unique users triggering the event. If unique users are
  stable but event count fell, the event fire condition changed, not user behavior.
- `posthog:query-trends` on an adjacent event (e.g., `$pageview` for a pageview-dependent
  metric). If the adjacent event is stable while the target fell, the target's tracking
  changed.
- Breakdown on `properties.$lib_version`. A drop concentrated in one SDK version points to
  tracking code changes.
- `posthog:event-definitions-list` for recently added / deprecated events with similar names.

**Remediation**: flag to engineering — this is probably a tracking bug, not a product issue.

## Cohort / lifecycle shift

The product is fine — the mix of users is different. E.g., a surge of new users inflated DAU
but dragged down engagement metrics that skew toward returning users.

**Confirm with:**

- `posthog:query-lifecycle` on the affected metric. A cohort shift appears as a change in the
  new / returning / resurrecting / dormant mix, not a uniform move across all statuses.
- `posthog:query-retention` comparing the affected-period cohorts to prior cohorts.

**Remediation**: split the metric into per-lifecycle-status series in the report so the mix
effect is transparent. Offer to save the lifecycle view for ongoing monitoring.

## Seasonality or day-of-week artifact

The change is not anomalous — it's a normal pattern (weekend drop, holiday trough, end-of-quarter
spike). Common trap when comparing two adjacent short windows.

**Confirm with:**

- `posthog:query-trends` with `compareFilter: {"compare": true}` to show the previous period
  alongside the current one.
- Extend the date range to at least 3–4× the interval and check for cyclical patterns.

**Remediation**: explain the pattern with the side-by-side comparison. Offer a "vs. last period"
version of the insight so the reassessment is built in.

## Platform / device / browser-specific issue

Something broke on one platform — a JS error on a Safari update, a mobile app crash on a
specific OS version, a CDN issue in one region.

**Confirm with:**

- `posthog:query-trends` breakdown on `$browser`, `$browser_version`, `$os`, `$os_version`,
  `$device_type`, or `$geoip_country_code`. Look for one breakdown value absorbing most of
  the delta.
- `posthog:error-tracking-issues-list` for errors in the same window. If error-tracking
  corroborates, link the issue in the report.

**Remediation**: hand off to the platform owner. Link the error issue if available.

## Rate limit or quota

For API-heavy products, a consumer hitting a quota or an upstream dependency outage can cause
correlated drops.

**Confirm with:**

- `posthog:query-trends` on API error events or 4xx/5xx response events.
- `posthog:query-logs` for a surge of error logs in the window, if logs are captured.

**Remediation**: surface the error rate alongside the metric. Suggest alerting on the error
metric going forward.

## Upstream data integration changed

For data-warehouse-dependent metrics: a source table schema changed, a pipeline failed, or a
data-modeling endpoint was altered, shifting the metric without any user-facing change.

This category is hard for the agent to confirm directly — the investigation tools focus on
product events, not pipeline health. If the metric is backed by a data-warehouse view and no
product-side cause fits, flag this as a candidate and recommend the user check pipeline
health / view modification dates manually.
