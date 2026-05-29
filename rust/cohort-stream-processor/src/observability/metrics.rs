//! Prometheus recorder setup and the service's metric vocabulary. The ~35 application
//! metrics (TDD §8.1) are registered by the pipeline modules as they are built; this
//! installs the global recorder, returns the render handle consumed by `GET /metrics`,
//! and owns the metric-name constants so every emitter uses the same series.

use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};

// ── Filter catalog (PR 1.3) ───────────────────────────────────────────────────
/// Teams with ≥1 realtime cohort in the current catalog snapshot (gauge).
pub const FILTER_CATALOG_TEAMS: &str = "filter_catalog_teams";
/// Distinct `conditionHash`es across all teams in the current snapshot (gauge).
pub const FILTER_CATALOG_UNIQUE_CONDITIONS: &str = "filter_catalog_unique_conditions";
/// Leaves dropped during parse, labelled by `reason` (counter).
pub const FILTER_CATALOG_SKIPPED_LEAVES: &str = "filter_catalog_skipped_leaves_total";
/// Cohorts skipped because their filter tree failed to parse (counter).
pub const FILTER_CATALOG_COHORT_PARSE_ERRORS: &str = "filter_catalog_cohort_parse_errors_total";

// ── Store (PR 1.2) ─────────────────────────────────────────────────────────────
/// RocksDB batch commits (multi-CF `WriteBatch`, `delete_partition`, …), labelled by
/// `op` (counter).
pub const STORE_WRITE_BATCH_TOTAL: &str = "store_write_batch_total";
/// Latency of a committed RocksDB write, labelled by `op` (histogram, seconds).
pub const STORE_WRITE_DURATION_SECONDS: &str = "store_write_duration_seconds";
/// RocksDB operations that returned an error, labelled by `op` (counter).
pub const STORE_ERRORS_TOTAL: &str = "store_errors_total";
/// Malformed inputs the `cf_person_index` merge operator skipped instead of panicking
/// (a panic on a compaction thread is FFI UB), labelled by `kind` (counter).
pub const STORE_MERGE_MALFORMED_TOTAL: &str = "store_merge_malformed_total";

/// Install the global Prometheus recorder. Call once at startup.
///
/// # Panics
/// Panics if a global metrics recorder has already been installed.
pub fn install_recorder() -> PrometheusHandle {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("failed to install Prometheus recorder")
}
