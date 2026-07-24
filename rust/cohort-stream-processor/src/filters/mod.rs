//! Filter catalog: the in-memory view of realtime cohorts.

pub mod manager;

pub use cohort_core::filters::{
    build_catalog_from_rows, load_realtime_cohorts, CohortRow, REALTIME_COHORTS_SQL,
};
pub use cohort_core::filters::{leaf_classifier, loader, reverse_index, tree};
pub use cohort_core::filters::{
    BehavioralLeafConfig, BehavioralValue, BoolOp, CohortId, CohortLeaf, CohortRefLeafConfig,
    CohortTree, FilterError, FilterNode, PersonLeafConfig, TeamId,
};
pub use cohort_core::filters::{FilterCatalog, Generation};
pub use cohort_core::filters::{TeamFilters, TeamFiltersBuilder};

pub use manager::{run_refresh_loop, CatalogHandle, CatalogStats};
