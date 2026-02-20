mod manager;
mod repository;
mod types;

// Re-export public API
pub use manager::{EventRestrictionService, RestrictionManager};
pub use repository::{EventRestrictionsRepository, RedisRestrictionsRepository, RestrictionEntry};
pub use types::{
    AppliedRestrictions, EventContext, Restriction, RestrictionFilters, RestrictionScope,
    RestrictionSet, RestrictionType,
};

#[cfg(test)]
pub use repository::testing::MockRestrictionsRepository;
