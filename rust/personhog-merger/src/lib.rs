mod lock;
mod service;
mod state;
mod types;

#[cfg(test)]
mod testing;

pub use lock::{InMemoryLockService, LockError, LockService};
pub use service::PersonMergeService;
pub use state::{
    InMemoryMergeStateRepository, MergeState, MergeStateRepository, MergeStep, SourcesMarkedData,
    StartedData, TargetMarkedData,
};
pub use types::{
    DistinctIdInfo, GetPersonsForMergeResult, MergeConflict, MergeResult, MergeStatus, Person,
    PersonDistinctIdsApi, PersonPropertiesApi, SetMergingSourceResult, SetMergingTargetResult,
    VersionedProperty,
};

#[cfg(test)]
pub use testing::{Breakpoint, SequenceExecutor};

#[cfg(test)]
pub use state::breakpointed::{
    BreakpointedRepository, InjectedError, OperationBreakpoint, RepositoryOperation,
};

#[cfg(test)]
pub use lock::{BreakpointedLockService, InjectedLockError, LockBreakpoint, LockOperation};
