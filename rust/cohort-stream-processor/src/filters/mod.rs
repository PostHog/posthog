//! Filter catalog: the in-memory view of realtime cohorts.
//!
//! Loads `posthog_cohort` filters, parses each cohort's tree (without the SQL-only sibling-merge
//! optimization, so Stage 2 can re-walk the original leaves), derives each leaf's `LeafStateKey`,
//! and builds the `condition_hash` reverse indices — refreshed every 5 min (±1 min jitter) with an
//! atomic `Arc<FilterCatalog>` swap.

pub mod leaf_classifier;
pub mod loader;
pub mod manager;
pub mod reverse_index;
pub mod tree;

use thiserror::Error;

pub use leaf_classifier::{classify_leaf, LeafClass, LeafDropReason};
pub use loader::{build_catalog_from_rows, load_realtime_cohorts, CohortRow, REALTIME_COHORTS_SQL};
pub use manager::{run_refresh_loop, CatalogHandle, CatalogStats, FilterCatalog};
pub use reverse_index::{TeamFilters, TeamFiltersBuilder};
pub use tree::{
    parse_cohort_tree, BehavioralLeafConfig, BehavioralValue, BoolOp, CohortLeaf,
    CohortRefLeafConfig, CohortTree, FilterNode, LeafSink, PersonLeafConfig,
};

/// Team identifier (`posthog_cohort.team_id`). `Stage1Key.team_id` is `u64`, converted at the store
/// boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct TeamId(pub i32);

/// Cohort identifier (`posthog_cohort.id`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct CohortId(pub i32);

/// Errors from loading or parsing the filter catalog.
#[derive(Debug, Error)]
pub enum FilterError {
    #[error("querying posthog_cohort: {0}")]
    Query(#[from] sqlx::Error),

    #[error("cohort {cohort_id} filters has no `properties`")]
    MissingProperties { cohort_id: i32 },

    #[error("cohort {cohort_id} is malformed: {detail}")]
    Malformed { cohort_id: i32, detail: String },
}
