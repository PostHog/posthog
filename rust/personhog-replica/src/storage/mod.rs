pub mod error;
pub mod postgres;
pub mod traits;
pub mod types;

pub use error::{StorageError, StorageResult};

pub use types::{
    CohortMembership, DistinctIdMapping, DistinctIdWithVersion, Group, GroupIdentifier, GroupKey,
    GroupTypeMapping, HashKeyOverride, Person, PersonIdWithOverrideKeys, PersonIdWithOverrides,
};

pub use traits::{CohortStorage, DistinctIdLookup, FeatureFlagStorage, GroupStorage, PersonLookup};

/// Combined storage trait that includes all sub-traits.
/// Use this when you need access to all storage operations.
pub trait FullStorage:
    PersonLookup + DistinctIdLookup + GroupStorage + CohortStorage + FeatureFlagStorage
{
}

// Blanket implementation: anything that implements all sub-traits automatically implements FullStorage
impl<T> FullStorage for T where
    T: PersonLookup + DistinctIdLookup + GroupStorage + CohortStorage + FeatureFlagStorage
{
}
