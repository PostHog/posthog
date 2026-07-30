//! Application layer: wires `store`, `clickhouse`, `kafka`, and `config` into the seeder's poll loop.
//! Depends on every lower layer; nothing below depends on it, so this is where the arrows terminate.

mod deliver;
mod execute;
mod orchestrator;
mod prepare;
pub mod settings;

pub use orchestrator::{SeederOrchestrator, ORCHESTRATOR_LIVENESS_DEADLINE};
pub use settings::OrchestratorSettings;
