//! Application layer: wires `store`, `clickhouse`, `kafka`, and `config` into the seeder's poll loop.
//! Depends on every lower layer; nothing below depends on it, so this is where the arrows terminate.

pub mod completion;
mod deliver;
mod execute;
pub mod observe;
mod orchestrator;
mod prepare;
pub mod reconcile_dispatch;
pub mod settings;
pub mod watch;

pub use completion::{
    AutoDispatchPolicy, AutoDispatchPolicyError, CompletionDriver, ObservePolicy,
    ObservePolicyError,
};
pub use observe::{KafkaCommittedOffsets, KafkaTopicOffsets};
pub use orchestrator::{SeederOrchestrator, ORCHESTRATOR_LIVENESS_DEADLINE};
pub use settings::OrchestratorSettings;
pub use watch::{MarkerWatchTask, PgMarkerFlush, WatchDirectives, MARKER_WATCH_LIVENESS_DEADLINE};
