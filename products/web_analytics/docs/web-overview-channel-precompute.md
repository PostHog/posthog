# Web overview channel precompute

Web overview can reuse lazy precomputation for session `$channel_type` filters,
including custom channel rules. Event and person filters can accompany the channel
filter. Other session properties and cohorts retain their existing fallback.
The channel path accepts up to 366 whole days; other web precompute paths retain
their existing range limits. Feature enrollment, per-query opt-out, sampling,
conversion goals, timezone eligibility, and property access controls still apply.

## Exact range boundaries

Daily jobs store full session aggregates. A session starting near midnight can
include pageviews after the requested end. Reading its cached total would count
those pageviews incorrectly.

The channel path reads complete UTC days from the cache, excluding the leading
partial day and the trailing session forward-pad interval (24 hours, rounded back
to a UTC day). It computes those boundary sessions from events with the original
query's exact timestamp predicate. Cached and boundary aggregate states merge in
ClickHouse, preserving distinct visitor counts across both sources. Short ranges
without complete interior days use only the boundary query.

Comparison periods are read separately, while their boundary event filters retain
the live query's union of both periods. Session IDs are converted to non-null
strings in the aggregate state, matching the preaggregation table in both string
and UUID join modes. Custom channel rules participate in the job hash, so a rule
change cannot reuse results computed with a different classification.

## Cache misses and operational limits

User-facing requests do not backfill missing jobs inline. The existing background
warming and stale revalidation mechanisms build interior jobs. Missing or failed
jobs still fall back to the live query, so enabling this path alone does not make
a cold annual query fast. Existing shape limits, insert resource limits, and OOM
window capping continue to apply.

This path covers overview metrics only. Other dashboard tables and tiles have
independent precompute eligibility and performance characteristics. Correctness
with synthetic data does not establish production latency or memory usage.
