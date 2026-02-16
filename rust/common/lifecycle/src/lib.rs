//! Unified app lifecycle: signal trapping, component registration with RAII drop guards,
//! coordinated graceful shutdown, heartbeat-based liveness, K8s readiness/liveness probes,
//! and metrics. The monitor runs on a dedicated OS thread with an isolated tokio runtime
//! so it stays responsive regardless of app workload.

mod error;
mod handle;
mod liveness;
mod manager;
mod metrics;
mod readiness;
mod signals;

pub use error::LifecycleError;
pub use handle::Handle;
pub use liveness::{ComponentLiveness, HealthStrategy, LivenessHandler, LivenessStatus};
pub use manager::{ComponentOptions, Manager, ManagerOptions, MonitorGuard};
pub use readiness::ReadinessHandler;
