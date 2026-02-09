mod lock;
mod process;
mod service;
mod state;
mod types;

#[cfg(test)]
mod testing;

pub use lock::{InMemoryLockService, LockError, LockService};
pub use process::{MergeContext, ProcessResult, Processable};
pub use service::{MergeExecutor, PersonMergeService};
pub use state::{
    CompletedState, DistinctIdsMergedState, InMemoryMergeStateRepository, MergeState,
    MergeStateRepository, MergeStep, PropertiesMergedState, SourcesMarkedState, StartedState,
    TargetClearedState, TargetMarkedState,
};
pub use types::{
    DistinctIdInfo, GetPersonsForMergeResult, MergeConflict, MergeResult, MergeStatus, Person,
    PersonDistinctIdsApi, PersonPropertiesApi, SetMergingSourceResult, SetMergingTargetResult,
    VersionedProperty,
};

#[cfg(test)]
pub use testing::{Breakpoint, CallGuard, ExpectedCall, MockMethod, SequenceExecutor};

#[cfg(test)]
pub use state::breakpointed::{
    BreakpointedRepository, InjectedError, OperationBreakpoint, RepositoryOperation,
};

#[cfg(test)]
pub use lock::{BreakpointedLockService, InjectedLockError, LockBreakpoint, LockOperation};
