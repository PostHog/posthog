//! Component handle and lifecycle events.

use std::sync::atomic::{AtomicBool, AtomicI64, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

#[derive(Debug)]
pub(crate) enum ComponentEvent {
    Failure { tag: String, reason: String },
    ShutdownRequested { tag: String },
    WorkCompleted { tag: String },
    Died { tag: String },
}

/// RAII handle for a registered component. Clone and pass to tasks; drop without
/// [`work_completed`](Handle::work_completed) signals "died" to the manager.
#[derive(Clone)]
pub struct Handle {
    pub(crate) inner: Arc<HandleInner>,
}

pub struct HandleInner {
    pub(crate) tag: String,
    pub(crate) shutdown_token: CancellationToken,
    pub(crate) event_tx: mpsc::Sender<ComponentEvent>,
    pub(crate) healthy_until_ms: Arc<AtomicI64>,
    pub(crate) liveness_deadline: Option<Duration>,
    pub(crate) completed: AtomicBool,
}

impl Handle {
    /// Future that resolves when shutdown begins. Use in `tokio::select!` to detect shutdown.
    pub fn shutdown_recv(&self) -> tokio_util::sync::WaitForCancellationFuture<'_> {
        self.inner.shutdown_token.cancelled()
    }

    /// Clone of the underlying cancellation token for passing to sub-tasks.
    pub fn cancellation_token(&self) -> CancellationToken {
        self.inner.shutdown_token.clone()
    }

    /// Returns true if shutdown has been initiated.
    pub fn is_shutting_down(&self) -> bool {
        self.inner.shutdown_token.is_cancelled()
    }

    /// Signal a fatal error; triggers global shutdown.
    pub fn signal_failure(&self, reason: impl Into<String>) {
        drop(self.inner.event_tx.try_send(ComponentEvent::Failure {
            tag: self.inner.tag.clone(),
            reason: reason.into(),
        }));
    }

    /// Request a clean shutdown (non-fatal).
    pub fn request_shutdown(&self) {
        drop(
            self.inner
                .event_tx
                .try_send(ComponentEvent::ShutdownRequested {
                    tag: self.inner.tag.clone(),
                }),
        );
    }

    /// Mark this component as finished; suppresses "died" when the handle is dropped.
    pub fn work_completed(&self) {
        self.inner.completed.store(true, Ordering::SeqCst);
        drop(self.inner.event_tx.try_send(ComponentEvent::WorkCompleted {
            tag: self.inner.tag.clone(),
        }));
    }

    /// Report healthy; must be called more often than the configured liveness deadline.
    pub fn report_healthy(&self) {
        if let Some(deadline) = self.inner.liveness_deadline {
            let now_ms = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as i64;
            let until = now_ms.saturating_add(deadline.as_millis() as i64);
            self.inner.healthy_until_ms.store(until, Ordering::Relaxed);
        }
    }

    /// Report this component as unhealthy for liveness.
    pub fn report_unhealthy(&self) {
        self.inner.healthy_until_ms.store(0, Ordering::Relaxed);
    }

    /// Same as [`report_healthy`](Handle::report_healthy); safe to call from sync/blocking contexts (e.g. rdkafka callbacks).
    pub fn report_healthy_blocking(&self) {
        self.report_healthy();
    }
}

impl Drop for HandleInner {
    fn drop(&mut self) {
        if !self.completed.load(Ordering::SeqCst) {
            drop(self.event_tx.try_send(ComponentEvent::Died {
                tag: self.tag.clone(),
            }));
        }
    }
}
