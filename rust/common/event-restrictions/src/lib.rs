//! Event ingestion restriction policy (drop / DLQ / force-overflow /
//! skip-person-processing / redirect), promoted out of `capture` so both capture
//! and the ingestion consumer share one Rust implementation. Mirrors Django's
//! `EventIngestionRestrictionConfig` and the Node `RestrictionMap`.

mod manager;
mod repository;
mod types;

// Re-export public API
pub use manager::{EventRestrictionService, RestrictionManager};
pub use repository::{EventRestrictionsRepository, RedisRestrictionsRepository, RestrictionEntry};
pub use types::{
    AppliedRestrictions, EventContext, Pipeline, Restriction, RestrictionFilters, RestrictionScope,
    RestrictionType,
};

#[cfg(test)]
pub use repository::testing::MockRestrictionsRepository;
