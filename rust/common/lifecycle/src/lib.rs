//! Unified app lifecycle: signal trapping, component registration with RAII drop guards,
//! coordinated graceful shutdown, internal health monitoring, K8s readiness/liveness probes,
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
pub use handle::{Handle, ProcessScopeGuard};
pub use liveness::{LivenessHandler, LivenessStatus};
pub use manager::{ComponentOptions, Manager, ManagerBuilder, MonitorGuard};
pub use readiness::ReadinessHandler;
