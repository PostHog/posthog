//! `cohort-core`: the evaluation kernel shared by the Behavioral Cohorts stream processor and the
//! backfill seeder. It owns the pieces whose result must be byte-for-byte identical across every
//! process that computes cohort membership: HogVM configuration, timezone calendar-day bucketing,
//! `condition_hash` / leaf-state-key derivation, the filter catalog, and the metric surface.
//!
//! ## Load-bearing contracts
//!
//! 1. **Parity is frozen against the Node reference.** The HogVM execution config (stack/step
//!    ceilings, coercing comparisons), the tz calendar-day bucketing, and `condition_hash` handling
//!    reproduce the TS/Python/ClickHouse oracle exactly. Changing any of them silently diverges
//!    membership from production and must be treated as a wire break.
//! 2. **Every linking process evaluates identically by construction.** The processor and the seeder
//!    share these types rather than reimplementing them, so a leaf that matches in one matches in the
//!    other. New consumers route through this crate, never a private copy.
//! 3. **Metrics are emitted by this crate itself** (see [`metrics`]): any process that links
//!    `cohort-core` emits the same counters, so dashboards must scope by a job/service label rather
//!    than assume a single emitter.
//!
//! ## Facade
//!
//! The [`pub use`](self) block below is the API of record for new code: prefer `cohort_core::Foo`
//! over the deeper module path. The modules stay `pub` because the processor shims re-export whole
//! modules under their historical paths.

pub mod bucket_tz;
pub mod eligibility;
pub mod events;
pub mod filters;
pub mod fingerprint;
pub mod hogvm;
pub mod leaf_state;
pub mod metrics;
pub mod partitioner;
pub mod seed;
pub mod timestamp;

pub use bucket_tz::{
    day_idx_in_tz, day_idx_of_naive_date, resolve_tz_or_utc, start_of_day_ms_in_tz, DayIdx,
};
pub use eligibility::{classify, CohortEligibility, CohortParseFlags, ExcludedReason};
pub use events::CohortStreamEvent;
pub use filters::{
    CohortId, FilterCatalog, FilterError, Generation, TeamFilters, TeamFiltersBuilder, TeamId,
};
pub use fingerprint::CatalogFingerprint;
pub use hogvm::{
    build_behavioral_globals, classify_vm_error, evaluate_detailed, CohortEvaluator, EvalOutcome,
    VmErrorClass,
};
pub use leaf_state::{EvictionWindow, LeafStateKey, StateVariant};
pub use partitioner::{partition_for, COHORT_PARTITION_COUNT};
pub use timestamp::clickhouse_timestamp_to_millis;
