//! Application layer: wires `store`, `clickhouse`, `kafka`, and `config` into the seeder's poll loop.
//! Depends on every lower layer; nothing below depends on it, so this is where the arrows terminate.

pub mod completion;
mod deliver;
mod execute;
pub mod observe;
mod orchestrator;
mod person_execute;
mod person_plan;
mod prepare;
pub mod prime;
pub mod reconcile_dispatch;
pub mod settings;
pub mod watch;

pub use completion::{
    AutoDispatchPolicy, AutoDispatchPolicyError, CompletionDriver, ObservePolicy,
    ObservePolicyError,
};
pub use observe::{KafkaCommittedOffsets, KafkaTopicOffsets};
pub use orchestrator::{
    fail_exhausted_runs_of_kind, PersonComponents, SeederOrchestrator,
    ORCHESTRATOR_LIVENESS_DEADLINE,
};
pub use prime::prime_zero_series;
pub use settings::{OrchestratorSettings, PersonSettings};
pub use watch::{MarkerWatchTask, PgMarkerFlush, WatchDirectives, MARKER_WATCH_LIVENESS_DEADLINE};

/// Fail a claimed chunk through the executor's recovery path, and report the wait it drew.
///
/// The store's `fail` takes the delay as an argument, so a test that calls it directly pins nothing
/// about where the delay comes from. This drives the one production call site instead: the resolver
/// that reads the chunk's attempt count and asks the policy for a wait.
///
/// It lives here rather than in `test_support` because [`execute`]'s recovery types are
/// `pub(super)`. Reaching them from a crate-root sibling means `pub(crate)`, which would let any
/// module drive the recovery matrix directly, a wider contract than one test needs.
#[cfg(feature = "pg-test-support")]
#[doc(hidden)]
pub async fn fail_via_recovery(
    store: &crate::store::chunks::PgChunkStore,
    chunk: crate::domain::ClaimedChunk,
    message: &str,
    retry_backoff: crate::domain::RetryBackoffPolicy,
) -> Option<std::time::Duration> {
    #[derive(Debug, thiserror::Error)]
    #[error("{0}")]
    struct RecoveryTestError(String);

    let halt = crate::domain::Halted::failed(chunk, RecoveryTestError(message.to_owned()));
    // Not cancelled: a pre-mark halt during shutdown unclaims instead of failing, which draws no
    // wait at all.
    let shutdown = tokio_util::sync::CancellationToken::new();
    match execute::resolve_halt(store, halt, &shutdown, retry_backoff).await {
        execute::ChunkOutcome::Failed { retry_delay, .. } => Some(retry_delay),
        _ => None,
    }
}
