mod service;
mod types;

#[cfg(test)]
mod testing;

pub use service::PersonMergeService;
pub use types::{
    DistinctIdInfo, GetPersonsForMergeResult, MergeConflict, MergeResult, MergeStatus, Person,
    PersonDistinctIdsApi, PersonPropertiesApi, SetMergingSourceResult, SetMergingTargetResult,
    VersionedProperty,
};

#[cfg(test)]
pub use testing::{Breakpoint, SequenceExecutor};
