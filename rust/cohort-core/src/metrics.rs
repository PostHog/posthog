//! Metric-name constants for the cohort evaluation surface.
//!
//! These counters are emitted by `cohort-core` itself, from any process that links it (both the
//! stream processor and the backfill seeder do). A dashboard cannot assume a single emitter: scope
//! every query by the job/service label to attribute a series to the process that produced it.

/// Leaves dropped during parse, labelled by `reason` (counter).
pub const FILTER_CATALOG_SKIPPED_LEAVES: &str = "filter_catalog_skipped_leaves_total";
/// Cohorts skipped because their filter tree failed to parse (counter).
pub const FILTER_CATALOG_COHORT_PARSE_ERRORS: &str = "filter_catalog_cohort_parse_errors_total";
/// Teams whose timezone did not parse as an IANA zone and fell back to UTC (counter).
pub const FILTER_CATALOG_TZ_FALLBACK: &str = "filter_catalog_tz_fallback_total";
/// Cohorts classified by composition eligibility at freeze, labelled by `class` (counter).
pub const COHORT_ELIGIBILITY_TOTAL: &str = "cohort_eligibility_total";
/// Cohorts excluded because they sit in a cohort-reference cycle (counter).
pub const COHORT_IN_CYCLE_TOTAL: &str = "cohort_in_cycle_total";
/// Cohort bytecode invoked a symbol with no registered native (counter).
pub const STAGE1_HOGVM_UNKNOWN_FUNCTION: &str = "stage1_hogvm_unknown_function_total";
/// Other VM/program failures during cohort evaluation, labelled by bounded `reason` values.
pub const STAGE1_HOGVM_ERROR: &str = "stage1_hogvm_error_total";
/// `properties`/`person_properties` JSON parse failures, labelled by `field` (counter).
pub const STAGE1_GLOBALS_PARSE_ERROR: &str = "stage1_globals_parse_error_total";
