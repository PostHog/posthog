//! Filter catalog: the in-memory view of realtime cohorts (TDD §2.7).
//!
//! Loads `posthog_cohort` filters, parses each cohort's tree (without the SQL-only
//! sibling-merge optimization), derives each leaf's `LeafStateKey`, and builds the
//! `condition_hash` reverse indices — refreshed every 5 min (±1 min jitter) with an atomic
//! `Arc<FilterCatalog>` swap. Submodules:
//! - `manager`         — 5-min refresh + atomic catalog swap (PR 1.3)
//! - `loader`          — `SELECT id, team_id, filters FROM posthog_cohort …` (PR 1.3)
//! - `tree`            — parsed per-cohort filter tree (PR 1.3)
//! - `reverse_index`   — `condition_hash → [LeafStateKey]` and `→ [cohort_id]` (PR 1.3)
//! - `leaf_classifier` — person | behavioral | cohort; skips cohort at Stage 1 (PR 1.3)
//! - `cohort_graph`    — reference graph + Tarjan SCC cycle detection (PR 3.3, deferred)

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

/// Team identifier — matches the `posthog_cohort.team_id` integer column and sibling crates.
/// (`Stage1Key.team_id` is `u64` per §4.1.0 and is converted at the store boundary in PR 1.6.)
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct TeamId(pub i32);

/// Cohort identifier — matches the `posthog_cohort.id` integer column.
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
