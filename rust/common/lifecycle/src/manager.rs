//! Lifecycle manager: signal trapping, component registration, graceful shutdown, readiness/liveness probes.

use std::collections::HashMap;
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use tokio::sync::{mpsc, oneshot};
use tokio_util::sync::CancellationToken;
use tracing::{debug, info, warn};

use crate::error::LifecycleError;
use crate::handle::{ComponentEvent, Handle, HandleInner};
use crate::liveness::{HealthStrategy, LivenessComponentRef, LivenessHandler};
use crate::metrics;
use crate::readiness::ReadinessHandler;
use crate::signals;

/// Options for creating a lifecycle manager.
#[derive(Clone, Debug)]
pub struct ManagerOptions {
    pub name: String,
    /// Global ceiling on shutdown duration (caps sum of component timeouts).
    pub global_shutdown_timeout: Duration,
    /// Install SIGINT/SIGTERM handlers (default: true).
    pub trap_signals: bool,
    /// Enable /tmp/shutdown file check for K8s pre-stop (default: true).
    pub enable_prestop_check: bool,
    /// Liveness strategy: All (every component must be healthy) or Any (at least one).
    pub liveness_strategy: HealthStrategy,
}

impl Default for ManagerOptions {
    fn default() -> Self {
        Self {
            name: "app".to_string(),
            global_shutdown_timeout: Duration::from_secs(60),
            trap_signals: true,
            enable_prestop_check: true,
            liveness_strategy: HealthStrategy::All,
        }
    }
}

/// Options for a registered component; use builder methods with any duration type that implements `TryInto<Duration>`.
#[derive(Clone, Debug)]
pub struct ComponentOptions {
    pub graceful_shutdown: Option<Duration>,
    pub liveness_deadline: Option<Duration>,
}

impl ComponentOptions {
    /// No graceful shutdown timeout, no liveness deadline.
    pub fn new() -> Self {
        Self {
            graceful_shutdown: None,
            liveness_deadline: None,
        }
    }

    /// Max time this component gets for cleanup after shutdown begins.
    pub fn with_graceful_shutdown<D>(mut self, d: D) -> Self
    where
        D: TryInto<Duration>,
    {
        self.graceful_shutdown = d.try_into().ok();
        self
    }

    /// Liveness heartbeat deadline; component must call [`Handle::report_healthy`](crate::Handle::report_healthy) within this interval.
    pub fn with_liveness_deadline<D>(mut self, d: D) -> Self
    where
        D: TryInto<Duration>,
    {
        self.liveness_deadline = d.try_into().ok();
        self
    }
}

impl Default for ComponentOptions {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ShutdownPhase {
    Running,
    ShuttingDown,
    Completed,
    TimedOut,
    Died,
}

struct ComponentState {
    graceful_shutdown: Option<Duration>,
    phase: ShutdownPhase,
}

/// Lifecycle manager: registers components, runs monitor on a dedicated OS thread, provides readiness/liveness handlers and shutdown signal.
pub struct Manager {
    name: String,
    options: ManagerOptions,
    shutdown_token: CancellationToken,
    event_tx: mpsc::Sender<ComponentEvent>,
    event_rx: Option<mpsc::Receiver<ComponentEvent>>,
    components: HashMap<String, ComponentState>,
    liveness_components: Vec<LivenessComponentRef>,
}

impl Manager {
    /// Create a new manager with the given options.
    pub fn new(options: ManagerOptions) -> Self {
        let (event_tx, event_rx) = mpsc::channel(64);
        Self {
            name: options.name.clone(),
            options,
            shutdown_token: CancellationToken::new(),
            event_tx,
            event_rx: Some(event_rx),
            components: HashMap::new(),
            liveness_components: Vec::new(),
        }
    }

    /// Register a component; returns an RAII handle. Drop without [`Handle::work_completed`](crate::Handle::work_completed) signals "died".
    pub fn register(&mut self, tag: &str, options: ComponentOptions) -> Handle {
        let healthy_until_ms = Arc::new(AtomicI64::new(0));
        let tag_owned = tag.to_string();
        let deadline = options.liveness_deadline;

        if let Some(d) = options.liveness_deadline {
            self.liveness_components.push(LivenessComponentRef {
                tag: tag_owned.clone(),
                healthy_until_ms: healthy_until_ms.clone(),
                deadline: d,
            });
        }

        self.components.insert(
            tag_owned.clone(),
            ComponentState {
                graceful_shutdown: options.graceful_shutdown,
                phase: ShutdownPhase::Running,
            },
        );

        debug!(
            component = %tag_owned,
            graceful_shutdown_secs = options.graceful_shutdown.map(|d| d.as_secs_f64()),
            liveness_deadline_secs = deadline.map(|d| d.as_secs_f64()),
            "Lifecycle: component registered"
        );

        let inner = Arc::new(HandleInner {
            tag: tag_owned,
            shutdown_token: self.shutdown_token.clone(),
            event_tx: self.event_tx.clone(),
            healthy_until_ms,
            liveness_deadline: options.liveness_deadline,
            completed: std::sync::atomic::AtomicBool::new(false),
        });

        Handle { inner }
    }

    /// Axum-compatible handler for `/_readiness`; returns 200 if running, 503 if shutdown has begun.
    pub fn readiness_handler(&self) -> ReadinessHandler {
        ReadinessHandler::new(self.shutdown_token.clone())
    }

    /// Axum-compatible handler for `/_liveness`; returns 200 if healthy per strategy, 500 with per-component detail otherwise.
    pub fn liveness_handler(&self) -> LivenessHandler {
        LivenessHandler::new(
            Arc::new(self.liveness_components.clone()),
            self.options.liveness_strategy.clone(),
        )
    }

    /// Future that resolves when shutdown begins; pass to `axum::serve(..., with_graceful_shutdown(shutdown_signal()))`.
    pub fn shutdown_signal(&self) -> impl std::future::Future<Output = ()> + Send + 'static {
        let token = self.shutdown_token.clone();
        async move {
            token.cancelled().await;
        }
    }

    fn spawn_monitor_thread(mut self) -> oneshot::Receiver<Result<(), LifecycleError>> {
        let (tx, rx) = oneshot::channel();
        let event_rx = self
            .event_rx
            .take()
            .expect("monitor already started or event_rx taken");

        thread::Builder::new()
            .name("lifecycle-monitor".into())
            .spawn(move || {
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("failed to build lifecycle runtime");
                let result = rt.block_on(self.run_monitor_loop(event_rx));
                drop(tx.send(result));
            })
            .expect("failed to spawn lifecycle monitor thread");

        rx
    }

    /// Spawn the monitor on a dedicated OS thread and await completion; returns when all components finish or time out.
    pub async fn monitor(self) -> Result<(), LifecycleError> {
        let rx = self.spawn_monitor_thread();
        rx.await.map_err(|_| LifecycleError::MonitorPanicked)?
    }

    /// Same as [`monitor`](Manager::monitor) but returns immediately with a guard; await the guard after the HTTP server exits.
    pub fn monitor_background(self) -> MonitorGuard {
        MonitorGuard {
            rx: self.spawn_monitor_thread(),
        }
    }

    async fn run_monitor_loop(
        mut self,
        mut event_rx: mpsc::Receiver<ComponentEvent>,
    ) -> Result<(), LifecycleError> {
        let _span = tracing::info_span!("lifecycle", app = %self.name).entered();
        let name = self.name.clone();
        let trap_signals = self.options.trap_signals;
        let enable_prestop = self.options.enable_prestop_check;
        let global_timeout = self.options.global_shutdown_timeout;
        let shutdown_token = self.shutdown_token.clone();

        if trap_signals {
            let token = shutdown_token.clone();
            tokio::spawn(async move {
                signals::wait_for_shutdown_signal().await;
                token.cancel();
            });
        }

        if enable_prestop {
            let token = shutdown_token.clone();
            tokio::spawn(async move {
                let mut interval = tokio::time::interval(Duration::from_secs(1));
                loop {
                    interval.tick().await;
                    if std::path::Path::new("/tmp/shutdown").exists() {
                        info!(
                            trigger_reason = "prestop",
                            "Lifecycle: shutdown initiated, prestop file detected"
                        );
                        token.cancel();
                        break;
                    }
                }
            });
        }

        let name_for_metrics = name.clone();
        let liveness_for_metrics = self.liveness_components.clone();
        let gauge_token = shutdown_token.clone();
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(Duration::from_secs(5));
            loop {
                tokio::select! {
                    _ = interval.tick() => {
                        let now_ms = SystemTime::now()
                            .duration_since(UNIX_EPOCH)
                            .unwrap_or_default()
                            .as_millis() as i64;
                        for comp in &liveness_for_metrics {
                            let until = comp.healthy_until_ms.load(Ordering::Relaxed);
                            let healthy = until > 0 && until > now_ms;
                            metrics::emit_component_healthy(&name_for_metrics, &comp.tag, healthy);
                        }
                    }
                    _ = gauge_token.cancelled() => break,
                }
            }
        });

        let mut first_failure: Option<LifecycleError> = None;

        loop {
            tokio::select! {
                biased;

                Some(event) = event_rx.recv() => {
                    match event {
                        ComponentEvent::Failure { tag, reason } => {
                            metrics::emit_shutdown_initiated(&name, &tag, "failure");
                            warn!(trigger_component = %tag, trigger_reason = "failure",
                                "Lifecycle: shutdown initiated: {reason:#}");
                            shutdown_token.cancel();
                            if let Some(s) = self.components.get_mut(&tag) {
                                s.phase = ShutdownPhase::Died;
                            }
                            first_failure = first_failure.or(Some(LifecycleError::ComponentFailure { tag, reason }));
                            break;
                        }
                        ComponentEvent::Died { tag } => {
                            metrics::emit_shutdown_initiated(&name, &tag, "died");
                            warn!(trigger_component = %tag, trigger_reason = "died",
                                "Lifecycle: shutdown initiated, component died unexpectedly");
                            shutdown_token.cancel();
                            if let Some(s) = self.components.get_mut(&tag) {
                                s.phase = ShutdownPhase::Died;
                            }
                            first_failure = first_failure.or(Some(LifecycleError::ComponentDied { tag }));
                            break;
                        }
                        ComponentEvent::ShutdownRequested { tag } => {
                            metrics::emit_shutdown_initiated(&name, &tag, "requested");
                            info!(trigger_component = %tag, trigger_reason = "requested",
                                "Lifecycle: shutdown requested by component");
                            shutdown_token.cancel();
                            break;
                        }
                        ComponentEvent::WorkCompleted { tag } => {
                            if let Some(s) = self.components.get_mut(&tag) {
                                s.phase = ShutdownPhase::Completed;
                            }
                            let done = self.components.values().all(|s| s.phase != ShutdownPhase::Running && s.phase != ShutdownPhase::ShuttingDown);
                            if done {
                                return self.finalize(Instant::now(), first_failure);
                            }
                        }
                    }
                }
                _ = shutdown_token.cancelled() => {
                    metrics::emit_shutdown_initiated(&name, "system", "signal");
                    info!(trigger_reason = "signal", "Lifecycle: shutdown initiated");
                    break;
                }
            }
        }

        for s in self.components.values_mut() {
            if s.phase == ShutdownPhase::Running {
                s.phase = ShutdownPhase::ShuttingDown;
            }
        }

        let all_done = self.components.values().all(|s| {
            s.phase == ShutdownPhase::Completed
                || s.phase == ShutdownPhase::Died
                || s.phase == ShutdownPhase::TimedOut
        });
        if all_done {
            return self.finalize(Instant::now(), first_failure);
        }

        let shutdown_clock = Instant::now();
        let global_deadline = shutdown_clock + global_timeout;
        let mut component_deadlines: Vec<(String, Instant)> = self
            .components
            .iter()
            .filter_map(|(tag, s)| {
                s.graceful_shutdown
                    .map(|d| (tag.clone(), shutdown_clock + d))
            })
            .collect();
        component_deadlines.sort_by(|a, b| a.1.cmp(&b.1));

        loop {
            let now = Instant::now();
            if now >= global_deadline {
                let remaining: Vec<String> = self
                    .components
                    .iter()
                    .filter(|(_, s)| {
                        s.phase != ShutdownPhase::Completed
                            && s.phase != ShutdownPhase::TimedOut
                            && s.phase != ShutdownPhase::Died
                    })
                    .map(|(t, _)| t.clone())
                    .collect();
                for tag in &remaining {
                    metrics::emit_component_shutdown_result(&name, tag, "timeout");
                }
                warn!(
                    total_duration_secs = global_timeout.as_secs_f64(),
                    remaining = ?remaining,
                    "Lifecycle: global shutdown timeout reached"
                );
                return Err(LifecycleError::ShutdownTimeout {
                    elapsed: global_timeout,
                    remaining,
                });
            }

            let next_component_timeout = component_deadlines
                .iter()
                .find(|(tag, _)| {
                    self.components
                        .get(tag)
                        .map(|s| s.phase == ShutdownPhase::ShuttingDown)
                        == Some(true)
                })
                .map(|(_, t)| *t);

            let wait_duration = [
                next_component_timeout.map(|t| t.saturating_duration_since(now)),
                Some(global_deadline.saturating_duration_since(now)),
            ]
            .into_iter()
            .flatten()
            .min()
            .unwrap_or(Duration::from_secs(1));

            tokio::select! {
                biased;

                Some(event) = event_rx.recv() => {
                    match event {
                        ComponentEvent::WorkCompleted { tag } => {
                            if let Some(s) = self.components.get_mut(&tag) {
                                if s.phase == ShutdownPhase::ShuttingDown {
                                    s.phase = ShutdownPhase::Completed;
                                    let elapsed = shutdown_clock.elapsed();
                                    metrics::emit_component_shutdown_duration(&name, &tag, "completed", elapsed.as_secs_f64());
                                    metrics::emit_component_shutdown_result(&name, &tag, "completed");
                                    info!(component = %tag,
                                        duration_secs = elapsed.as_secs_f64(),
                                        result = "completed",
                                        "Lifecycle: component completed shutdown");
                                } else {
                                    debug!(component = %tag, phase = ?s.phase,
                                        "Lifecycle: late WorkCompleted for already-finished component");
                                }
                            }
                        }
                        ComponentEvent::Died { tag } => {
                            if let Some(s) = self.components.get_mut(&tag) {
                                s.phase = ShutdownPhase::Died;
                                let elapsed = shutdown_clock.elapsed();
                                metrics::emit_component_shutdown_duration(&name, &tag, "died", elapsed.as_secs_f64());
                                metrics::emit_component_shutdown_result(&name, &tag, "died");
                                warn!(component = %tag,
                                    duration_secs = elapsed.as_secs_f64(),
                                    result = "died",
                                    "Lifecycle: component died during shutdown");
                            }
                        }
                        _ => {}
                    }
                    let all_done = self.components.values().all(|s| {
                        s.phase == ShutdownPhase::Completed || s.phase == ShutdownPhase::Died || s.phase == ShutdownPhase::TimedOut
                    });
                    if all_done {
                        return self.finalize(shutdown_clock, first_failure);
                    }
                }
                _ = tokio::time::sleep(wait_duration) => {
                    let now = Instant::now();
                    for (tag, deadline) in &component_deadlines {
                        if now >= *deadline {
                            if let Some(s) = self.components.get_mut(tag) {
                                if s.phase == ShutdownPhase::ShuttingDown {
                                    s.phase = ShutdownPhase::TimedOut;
                                    if let Some(d) = s.graceful_shutdown {
                                        metrics::emit_component_shutdown_duration(&name, tag, "timeout", d.as_secs_f64());
                                    }
                                    metrics::emit_component_shutdown_result(&name, tag, "timeout");
                                    warn!(component = %tag,
                                        duration_secs = s.graceful_shutdown.unwrap_or_default().as_secs_f64(),
                                        result = "timeout",
                                        "Lifecycle: component timed out during graceful shutdown");
                                }
                            }
                        }
                    }
                    let all_done = self.components.values().all(|s| {
                        s.phase == ShutdownPhase::Completed || s.phase == ShutdownPhase::Died || s.phase == ShutdownPhase::TimedOut
                    });
                    if all_done {
                        return self.finalize(shutdown_clock, first_failure);
                    }
                }
            }
        }
    }

    fn finalize(
        &self,
        shutdown_clock: Instant,
        first_failure: Option<LifecycleError>,
    ) -> Result<(), LifecycleError> {
        let total = shutdown_clock.elapsed();
        let clean = self
            .components
            .values()
            .all(|s| s.phase == ShutdownPhase::Completed);
        metrics::emit_shutdown_completed(&self.name, clean);
        if clean {
            info!(
                clean = true,
                total_duration_secs = total.as_secs_f64(),
                "Lifecycle: shutdown complete"
            );
        } else {
            warn!(
                clean = false,
                total_duration_secs = total.as_secs_f64(),
                "Lifecycle: shutdown complete with failures"
            );
        }
        first_failure.map_or(Ok(()), Err)
    }
}

/// Guard returned by [`Manager::monitor_background`]; await to get the monitor result.
pub struct MonitorGuard {
    rx: oneshot::Receiver<Result<(), LifecycleError>>,
}

impl MonitorGuard {
    /// Await the monitor thread's completion; returns the same `Result` as [`Manager::monitor`](Manager::monitor).
    pub async fn wait(self) -> Result<(), LifecycleError> {
        self.rx.await.map_err(|_| LifecycleError::MonitorPanicked)?
    }
}
