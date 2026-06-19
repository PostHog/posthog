Characterize how a metric behaves in a suspicious window compared to a healthy baseline. This is the FIRST call to make when investigating "metric X is rising/dropping — why?": one call answers how big the change is, exactly when it started, and which label values moved.

Required: `metricName` (exact — discover via `metric-names-list` first) and `anomalyFrom` (when things started looking wrong; the alert fire time works). `anomalyTo` defaults to now. The baseline defaults to the equal-length window immediately before `anomalyFrom`; pass `baselineFrom`/`baselineTo` to compare against a known-good period instead (e.g. same time yesterday).

The aggregation is auto-picked from the metric's OTel type (counter -> rate, gauge -> avg, histogram -> p95); override with `aggregation` if you need a different lens. Use `filters` to scope to a service or region. `candidateKeys` controls which label keys are drilled into for the movers analysis — omit it to auto-discover.

Read the report in this order:

1. `direction` + `change_ratio` + `anomaly_peak`: how bad is it? (`flat` means the windows don't meaningfully differ — widen the anomaly window or check you have the right metric.)
2. `onset_time`: when it started. Use this exact timestamp as the pivot for cross-signal correlation.
3. `top_movers`: which label values changed. One label value moving alone (e.g. a single pod or shard) points at a localized culprit; everything moving together points at a shared cause upstream.
4. `series`: the full baseline+anomaly time series if you need to eyeball the shape.

Then correlate: query logs (`query-logs` with the same service and a window around `onset_time`, severity error first) and traces (APM span tools, same service/window) to find what broke and its blast radius. All parameters are nested inside a `query` object.
