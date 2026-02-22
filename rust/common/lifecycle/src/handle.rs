//! Component handle and lifecycle events.

use std::sync::atomic::{AtomicBool, AtomicI64, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

/// Sentinel: component registered but hasn't called report_healthy() yet.
pub(crate) const HEALTH_STARTING: i64 = 0;
/// Sentinel: component explicitly marked unhealthy via report_unhealthy().
pub(crate) const HEALTH_UNHEALTHY: i64 = -1;

#[derive(Debug)]
pub(crate) enum ComponentEvent {
    Failure { tag: String, reason: String },
    ShutdownRequested { tag: String },
    WorkCompleted { tag: String },
    Died { tag: String },
}

/// RAII handle for a registered component. Clone-able and safe to pass by reference
/// into child methods — child methods can freely call any handle API without
/// interfering with the drop guard or process scope guard.
///
/// # Drop guard
///
/// When the last clone is dropped:
/// - **During shutdown** → treated as normal completion. Just return.
///   (see test `direct_handle_drop_during_shutdown_is_completion`)
/// - **Not during shutdown** → signals "component died", triggers global shutdown.
///   Catches panics and accidental early returns.
///   (see test `handle_drop_during_normal_operation_signals_died`)
///
/// # Struct-held handles
///
/// If your struct owns the handle and has a `process()` method, use
/// [`process_scope`](Handle::process_scope) so the manager is notified when
/// `process()` returns — not when the struct is eventually dropped.
/// (see tests `component_a_clean_shutdown`, `component_b_clean_shutdown_with_do_work`)
#[derive(Clone)]
pub struct Handle {
    pub(crate) inner: Arc<HandleInner>,
}

pub(crate) struct HandleInner {
    pub(crate) tag: String,
    pub(crate) shutdown_token: CancellationToken,
    pub(crate) event_tx: mpsc::Sender<ComponentEvent>,
    pub(crate) healthy_until_ms: Arc<AtomicI64>,
    pub(crate) liveness_deadline: Option<Duration>,
    pub(crate) completed: AtomicBool,
    pub(crate) process_scope_signalled: AtomicBool,
}

impl Handle {
    /// Future that resolves when global shutdown begins (any trigger: signal, pre-stop,
    /// [`signal_failure`](Handle::signal_failure), or [`request_shutdown`](Handle::request_shutdown)).
    /// Use in `tokio::select!` to break out of work loops.
    pub fn shutdown_recv(&self) -> tokio_util::sync::WaitForCancellationFuture<'_> {
        self.inner.shutdown_token.cancelled()
    }

    /// Returns true if shutdown has been initiated.
    pub fn is_shutting_down(&self) -> bool {
        self.inner.shutdown_token.is_cancelled()
    }

    /// Signal a fatal error; triggers global shutdown. Just return after calling this —
    /// the manager records the failure immediately and the subsequent handle/guard drop
    /// during shutdown is harmlessly ignored.
    /// (see tests `direct_signal_failure_then_drop`, `component_b_do_work_signals_failure`)
    pub fn signal_failure(&self, reason: impl Into<String>) {
        if let Err(e) = self.inner.event_tx.try_send(ComponentEvent::Failure {
            tag: self.inner.tag.clone(),
            reason: reason.into(),
        }) {
            tracing::debug!(error = %e, "lifecycle event channel full, event dropped");
        }
    }

    /// Request a clean global shutdown (non-fatal). All components see it via
    /// [`shutdown_recv`](Handle::shutdown_recv). Readiness flips to 503 so K8s
    /// stops routing traffic; liveness is unaffected.
    /// (see test `component_a_and_b_multi_component_shutdown`)
    pub fn request_shutdown(&self) {
        if let Err(e) = self
            .inner
            .event_tx
            .try_send(ComponentEvent::ShutdownRequested {
                tag: self.inner.tag.clone(),
            })
        {
            tracing::debug!(error = %e, "lifecycle event channel full, event dropped");
        }
    }

    /// Mark this component as finished during normal operation. Use for one-shot/finite
    /// work (e.g. migration runner) — prevents the handle drop from signaling "died".
    /// Not needed for long-running components (drop during shutdown is completion) or
    /// after [`signal_failure`](Handle::signal_failure) (manager already recorded the failure).
    /// (see test `direct_work_completed_prevents_died_on_drop`)
    pub fn work_completed(&self) {
        self.inner.completed.store(true, Ordering::SeqCst);
        if let Err(e) = self.inner.event_tx.try_send(ComponentEvent::WorkCompleted {
            tag: self.inner.tag.clone(),
        }) {
            tracing::debug!(error = %e, "lifecycle event channel full, event dropped");
        }
    }

    /// Liveness heartbeat. Must be called more often than the configured `liveness_deadline`.
    /// If not called in time, the health monitor considers this component stalled. After
    /// `stall_threshold` consecutive stalled checks, the manager triggers global shutdown.
    /// (see tests `stall_triggers_shutdown`, `component_b_reports_healthy_from_process`)
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

    /// Mark this component as explicitly unhealthy. The health monitor treats this the
    /// same as a stalled heartbeat — after `stall_threshold` consecutive checks, the
    /// manager triggers global shutdown. Call [`report_healthy`](Handle::report_healthy)
    /// to recover and reset the stall counter. For immediate shutdown, use
    /// [`signal_failure`](Handle::signal_failure) instead.
    /// (see test `report_unhealthy_triggers_stall`)
    pub fn report_unhealthy(&self) {
        self.inner
            .healthy_until_ms
            .store(HEALTH_UNHEALTHY, Ordering::Relaxed);
    }

    /// Create a drop guard tied to your `process()` method's scope. When the guard is
    /// dropped (process returns), the manager is notified once. The handle itself stays
    /// on the struct and can be passed by ref or clone into child methods — child calls
    /// to `report_healthy()`, `signal_failure()`, etc. do not affect the guard.
    /// (see tests `component_b_clean_shutdown_with_do_work`,
    /// `process_scope_prevents_double_signal_from_struct`)
    pub fn process_scope(&self) -> ProcessScopeGuard {
        ProcessScopeGuard {
            inner: self.inner.clone(),
        }
    }
}

/// Drop guard returned by [`Handle::process_scope`]. When dropped, notifies the manager once
/// (WorkCompleted if shutdown, Died if not). Subsequent drops of additional guards or the
/// handle itself will not send duplicate events.
pub struct ProcessScopeGuard {
    inner: Arc<HandleInner>,
}

impl Drop for ProcessScopeGuard {
    fn drop(&mut self) {
        if self
            .inner
            .process_scope_signalled
            .swap(true, Ordering::SeqCst)
        {
            return;
        }
        let event = if self.inner.shutdown_token.is_cancelled() {
            ComponentEvent::WorkCompleted {
                tag: self.inner.tag.clone(),
            }
        } else {
            ComponentEvent::Died {
                tag: self.inner.tag.clone(),
            }
        };
        // Intentionally ignore send errors in Drop — tracing may already be torn down
        // during process exit, and logging here could panic.
        drop(self.inner.event_tx.try_send(event));
    }
}

impl Drop for HandleInner {
    fn drop(&mut self) {
        if self.process_scope_signalled.load(Ordering::SeqCst) {
            return;
        }
        if self.completed.load(Ordering::SeqCst) {
            return;
        }
        let event = if self.shutdown_token.is_cancelled() {
            ComponentEvent::WorkCompleted {
                tag: self.tag.clone(),
            }
        } else {
            ComponentEvent::Died {
                tag: self.tag.clone(),
            }
        };
        // Intentionally ignore send errors in Drop — tracing may already be torn down
        // during process exit, and logging here could panic.
        drop(self.event_tx.try_send(event));
    }
}
