//! Lifecycle error types returned by the monitor.

use std::time::Duration;

use thiserror::Error;

/// Errors returned by [`Manager::monitor`](crate::Manager::monitor) or [`MonitorGuard::wait`](crate::MonitorGuard::wait).
#[derive(Debug, Error)]
pub enum LifecycleError {
    /// A component called [`Handle::signal_failure`](crate::Handle::signal_failure).
    #[error("component '{tag}' failed: {reason}")]
    ComponentFailure { tag: String, reason: String },

    /// A component's handle was dropped without calling [`Handle::work_completed`](crate::Handle::work_completed).
    #[error("component '{tag}' died unexpectedly")]
    ComponentDied { tag: String },

    /// Global shutdown timeout was reached with components still running.
    #[error("shutdown timed out after {elapsed:?}, components still running: {remaining:?}")]
    ShutdownTimeout {
        elapsed: Duration,
        remaining: Vec<String>,
    },

    /// OS signal (SIGINT/SIGTERM) was received.
    #[error("signal received: {0}")]
    Signal(String),

    /// The dedicated lifecycle monitor thread panicked.
    #[error("lifecycle monitor thread panicked")]
    MonitorPanicked,
}
