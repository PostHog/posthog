# Data warehouse retention: dual-builder for strict-calendar-date, direct retrofit for 24-hour-window

We're adding data warehouse series support to two retention time modes with deliberately different rollout strategies.

- **Strict-calendar-date retention** (`RetentionFixedIntervalBaseQueryBuilder`, the default mode) uses a **dual-builder approach**. The legacy `build_base_query_legacy` (events-only, unchanged) and the new DWH-capable `build_base_query_dwh` live side by side. Events-only routing through the DWH path is gated per team by the `retention-fixed-interval-base-query-dwh-variant` feature flag, and `RetentionBaseQueryVariantComparisonMixin` runs both branches against every supported test input and asserts result parity. Once parity is verified for every supported query shape, `build_base_query_legacy` is deleted.
- **24-hour-window retention** (`RetentionRollingIntervalBaseQueryBuilder`, gated by `timeWindowMode == "24_hour_windows"`) is **retrofitted directly** — DWH support is added in place, with no parallel implementation, feature flag, or parity comparison harness.

The asymmetry exists because the two legacy implementations have very different blast radius. Strict-calendar-date retention is ~700 lines including memory-sensitive `groupArrayIf` paths over millions of events and is the highest-traffic retention insight; a behavior regression there is expensive to roll back without a parallel implementation. The 24-hour-window legacy is ~100 lines, not memory-sensitive, and carries comparatively little traffic — a parity-flag scaffold buys less than it costs.

## Consequences

- The variant flag is the **only** parity gate for the strict-calendar-date variant. Closing a parity gap (breakdowns, first-time retention types, `minimumOccurrences > 1`, sampling) and forgetting to remove the corresponding branch from `_query_uses_known_retention_base_query_variant_gap` silently re-disables parity testing for that shape. Reviewers must check this on every gap-closure PR.
- Deletion criteria for `build_base_query_legacy`: (a) the variant flag is enabled at 100% for ≥ 2 weeks with no parity-related incident, AND (b) `_query_uses_known_retention_base_query_variant_gap` returns `False` for every input — i.e. all known gaps are closed.
- 24-hour-window retention has no rollback hatch. The retrofit must be covered by tests pre-merge; any regression ships to production immediately when the PR merges.
- Data warehouse series with global property filters, test-account filters, or `samplingFactor` continue to be rejected by `DisallowUnsupportedDataWarehouseSettings`. Sampling for events-only retention through the variant is closed as a parity gap; sampling on a DWH series stays rejected.

## Considered alternatives

- **Direct rewrite of strict-calendar-date `build_base_query`** (no parallel implementation). Rejected: too risky given the legacy's traffic share and memory profile. A bug that only manifests in production data shape would have no easy rollback.
- **Dual-builder for 24-hour-window too.** Rejected: the dual-implementation tax is not justified by the legacy's size or traffic, and the existing comparison harness is structured around the strict-calendar-date builder's per-side UNION ALL shape — reusing it for 24-hour-window would force a non-trivial generalization.
- **Translate DWH sources into synthetic `events`-shaped subqueries to keep the legacy path unchanged.** Rejected: forces every DWH retention query to wrap a UNION or CTE around the source table even for simple single-table cases, blowing up query plans and hiding the actual table read in execution traces.
