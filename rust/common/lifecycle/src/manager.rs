//! Lifecycle manager: signal trapping, component registration, graceful shutdown, readiness/liveness probes.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::{Arc, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const DEFAULT_PRESTOP_PATH: &str = "/tmp/shutdown";
const DEFAULT_OBSERVABILITY_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(1);

use tokio::sync::{mpsc, oneshot};
use tokio_util::sync::CancellationToken;
use tracing::{debug, info, warn};

use crate::error::LifecycleError;
use crate::handle::{ComponentEvent, Handle, HandleInner, HEALTH_STARTING, HEALTH_UNHEALTHY};
use crate::liveness::{LivenessComponentRef, LivenessHandler};
use crate::metrics;
use crate::readiness::ReadinessHandler;
use crate::signals;

/// Builder for [`Manager`]. Start with [`Manager::builder("name")`](Manager::builder),
/// chain `.with_*()` calls, then call [`.build()`](ManagerBuilder::build).
#[derive(Debug)]
pub struct ManagerBuilder {
    name: String,
    global_shutdown_timeout: Duration,
    trap_signals: bool,
    enable_prestop_check: bool,
    prestop_path: PathBuf,
    health_poll_interval: Duration,
    external_shutdown_token: Option<CancellationToken>,
}

impl ManagerBuilder {
    /// Override the hard ceiling on total shutdown duration. If all components
    /// haven't finished within this window, monitor returns
    /// [`LifecycleError::ShutdownTimeout`]. Default: 60s.
    pub fn with_global_shutdown_timeout(mut self, d: Duration) -> Self {
        self.global_shutdown_timeout = d;
        self
    }

    /// Install SIGINT/SIGTERM handlers. Default: true. Set false in tests.
    pub fn with_trap_signals(mut self, enabled: bool) -> Self {
        self.trap_signals = enabled;
        self
    }

    /// Poll for pre-stop shutdown file (K8s pre-stop hook pattern). Default: true.
    pub fn with_prestop_check(mut self, enabled: bool) -> Self {
        self.enable_prestop_check = enabled;
        self
    }

    /// Override the pre-stop file path. Default: `/tmp/shutdown`.
    pub fn with_prestop_path(mut self, path: impl Into<PathBuf>) -> Self {
        self.prestop_path = path.into();
        self
    }

    /// Override how often the health monitor polls component heartbeats.
    /// The health monitor is automatically active when any component is
    /// registered with `with_liveness_deadline`. Default: 5s.
    /// Lower values detect stalls faster but use more CPU.
    pub fn with_health_poll_interval(mut self, d: Duration) -> Self {
        self.health_poll_interval = d;
        self
    }

    /// Use an external shutdown token. The caller controls when shutdown begins by calling
    /// `token.cancel()`. Use in tests for deterministic shutdown control.
    pub fn with_shutdown_token(mut self, token: CancellationToken) -> Self {
        self.external_shutdown_token = Some(token);
        self
    }

    /// Consume the builder and produce a [`Manager`].
    pub fn build(self) -> Manager {
        Manager {
            name: self.name,
            global_shutdown_timeout: self.global_shutdown_timeout,
            trap_signals: self.trap_signals,
            enable_prestop_check: self.enable_prestop_check,
            prestop_path: self.prestop_path,
            health_poll_interval: self.health_poll_interval,
            shutdown_token: self.external_shutdown_token.unwrap_or_default(),
            observability_shutdown_token: CancellationToken::new(),
            event_tx_slot: Arc::new(OnceLock::new()),
            components: HashMap::new(),
            observability_components: HashMap::new(),
            liveness_components: Vec::new(),
        }
    }
}

/// Per-component options set at registration time.
#[derive(Clone, Debug)]
pub struct ComponentOptions {
    graceful_shutdown: Option<Duration>,
    liveness_deadline: Option<Duration>,
    stall_threshold: u32,
    pub(crate) is_observability: bool,
    config_errors: Vec<String>,
}

impl ComponentOptions {
    /// No graceful shutdown timeout, no liveness deadline, stall threshold 1.
    pub fn new() -> Self {
        Self {
            graceful_shutdown: None,
            liveness_deadline: None,
            stall_threshold: 1,
            is_observability: false,
            config_errors: Vec::new(),
        }
    }

    /// Mark this component as an observability handle (e.g. metrics server).
    /// Observability handles are shut down *after* all standard components finish,
    /// ensuring metrics flow during the entire graceful shutdown process.
    /// Observability handles do not participate in active health monitoring;
    /// combining `is_observability(true)` with `with_liveness_deadline` will panic.
    /// (see test `observability_handle_shuts_down_after_standard_handles`)
    pub fn is_observability(mut self, enabled: bool) -> Self {
        self.is_observability = enabled;
        self
    }

    /// Max time this component gets for cleanup after shutdown begins. If exceeded,
    /// the manager marks the component as timed out and moves on.
    /// (see test `component_timeout_then_late_drop_preserves_timeout`)
    pub fn with_graceful_shutdown<D>(mut self, d: D) -> Self
    where
        D: TryInto<Duration>,
        D::Error: std::fmt::Debug,
    {
        match d.try_into() {
            Ok(dur) => self.graceful_shutdown = Some(dur),
            Err(e) => self
                .config_errors
                .push(format!("invalid graceful_shutdown duration: {e:?}")),
        }
        self
    }

    /// Liveness heartbeat deadline. The component must call [`Handle::report_healthy`](crate::Handle::report_healthy)
    /// within this interval or the health monitor considers it stalled. After
    /// `stall_threshold` consecutive stalled checks, the manager triggers global shutdown.
    /// (see test `stall_triggers_shutdown`)
    pub fn with_liveness_deadline<D>(mut self, d: D) -> Self
    where
        D: TryInto<Duration>,
        D::Error: std::fmt::Debug,
    {
        match d.try_into() {
            Ok(dur) => self.liveness_deadline = Some(dur),
            Err(e) => self
                .config_errors
                .push(format!("invalid liveness_deadline duration: {e:?}")),
        }
        self
    }

    /// Number of consecutive stalled health checks before the manager triggers
    /// global shutdown. Default: 1 (immediate). Set higher for tolerance of
    /// transient hiccups.
    /// (see test `stall_threshold_allows_recovery`)
    pub fn with_stall_threshold(mut self, n: u32) -> Self {
        self.stall_threshold = n.max(1);
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
    global_shutdown_timeout: Duration,
    trap_signals: bool,
    enable_prestop_check: bool,
    prestop_path: PathBuf,
    health_poll_interval: Duration,
    shutdown_token: CancellationToken,
    observability_shutdown_token: CancellationToken,
    event_tx_slot: Arc<OnceLock<mpsc::Sender<ComponentEvent>>>,
    components: HashMap<String, ComponentState>,
    observability_components: HashMap<String, ComponentState>,
    liveness_components: Vec<LivenessComponentRef>,
}

impl Manager {
    /// Start building a manager with the given service name. The name is emitted
    /// as the `service_name` label on all lifecycle metrics — use your K8s service
    /// name or logical app name for dashboard filtering.
    pub fn builder(name: impl Into<String>) -> ManagerBuilder {
        ManagerBuilder {
            name: name.into(),
            global_shutdown_timeout: Duration::from_secs(60),
            trap_signals: true,
            enable_prestop_check: true,
            prestop_path: PathBuf::from(DEFAULT_PRESTOP_PATH),
            health_poll_interval: Duration::from_secs(5),
            external_shutdown_token: None,
        }
    }

    /// Register a component and return a [`Handle`]. The handle's drop guard (or
    /// [`process_scope`](crate::Handle::process_scope) guard) notifies the manager when
    /// the component exits. Register all components before calling [`monitor`](Manager::monitor)
    /// or [`monitor_background`](Manager::monitor_background).
    pub fn register(&mut self, tag: &str, options: ComponentOptions) -> Handle {
        assert!(
            options.config_errors.is_empty(),
            "component '{}': {}",
            tag,
            options.config_errors.join("; ")
        );
        assert!(
            !self.components.contains_key(tag) && !self.observability_components.contains_key(tag),
            "component '{}' registered more than once",
            tag
        );
        assert!(
            !(options.is_observability && options.liveness_deadline.is_some()),
            "component '{}': observability handles cannot use liveness_deadline",
            tag
        );

        let healthy_until_ms = Arc::new(AtomicI64::new(HEALTH_STARTING));
        let tag_owned = tag.to_string();
        let is_obs = options.is_observability;

        if let Some(deadline) = options.liveness_deadline {
            let labels = [
                ("service_name".to_string(), self.name.clone()),
                ("component".to_string(), tag_owned.clone()),
            ];
            let health_gauge = ::metrics::gauge!("lifecycle_component_healthy", &labels);

            self.liveness_components.push(LivenessComponentRef {
                tag: tag_owned.clone(),
                healthy_until_ms: healthy_until_ms.clone(),
                stall_threshold: options.stall_threshold,
                health_gauge,
            });

            debug!(
                component = %tag_owned,
                graceful_shutdown_secs = options.graceful_shutdown.map(|d| d.as_secs_f64()),
                liveness_deadline_secs = deadline.as_secs_f64(),
                stall_threshold = options.stall_threshold,
                "Lifecycle: component registered"
            );
        } else {
            debug!(
                component = %tag_owned,
                observability = is_obs,
                graceful_shutdown_secs = options.graceful_shutdown.map(|d| d.as_secs_f64()),
                "Lifecycle: component registered"
            );
        }

        let target_map = if is_obs {
            &mut self.observability_components
        } else {
            &mut self.components
        };
        target_map.insert(
            tag_owned.clone(),
            ComponentState {
                graceful_shutdown: options.graceful_shutdown,
                phase: ShutdownPhase::Running,
            },
        );

        let shutdown_token = if is_obs {
            self.observability_shutdown_token.clone()
        } else {
            self.shutdown_token.clone()
        };

        let inner = Arc::new(HandleInner {
            tag: tag_owned,
            shutdown_token,
            event_tx: self.event_tx_slot.clone(),
            healthy_until_ms,
            liveness_deadline: options.liveness_deadline,
            completed: std::sync::atomic::AtomicBool::new(false),
            process_scope_signalled: std::sync::atomic::AtomicBool::new(false),
        });

        Handle { inner }
    }

    /// Readiness probe handler (`/_readiness`). Returns 200 while running, 503 after shutdown
    /// begins. K8s uses this to stop routing traffic to the pod.
    /// (see test `readiness_200_until_shutdown_then_503`)
    pub fn readiness_handler(&self) -> ReadinessHandler {
        ReadinessHandler::new(self.shutdown_token.clone())
    }

    /// Liveness probe handler (`/_liveness`). **Intentionally always returns 200** — the
    /// lifecycle library handles health monitoring internally and triggers coordinated
    /// graceful shutdown on stall, rather than delegating to K8s liveness probes.
    pub fn liveness_handler(&self) -> LivenessHandler {
        LivenessHandler::new()
    }

    fn spawn_monitor_thread(self) -> oneshot::Receiver<Result<(), LifecycleError>> {
        let (tx, rx) = oneshot::channel();

        let total_components = self.components.len() + self.observability_components.len();
        let channel_size = total_components * 2 + 2;
        let (event_tx, event_rx) = mpsc::channel(channel_size);
        self.event_tx_slot
            .set(event_tx)
            .expect("lifecycle monitor already started");

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

    /// Look up which component map a tag belongs to and return a mutable reference.
    fn get_component_mut(&mut self, tag: &str) -> Option<&mut ComponentState> {
        self.components
            .get_mut(tag)
            .or_else(|| self.observability_components.get_mut(tag))
    }

    fn is_observability_tag(&self, tag: &str) -> bool {
        self.observability_components.contains_key(tag)
    }

    async fn run_monitor_loop(
        mut self,
        mut event_rx: mpsc::Receiver<ComponentEvent>,
    ) -> Result<(), LifecycleError> {
        let _span = tracing::info_span!("lifecycle", app = %self.name).entered();
        let name = self.name.clone();
        let trap_signals = self.trap_signals;
        let enable_prestop = self.enable_prestop_check;
        let health_poll_interval = self.health_poll_interval;
        let global_timeout = self.global_shutdown_timeout;
        let shutdown_token = self.shutdown_token.clone();
        let has_liveness_components = !self.liveness_components.is_empty();

        debug!(
            global_shutdown_timeout_secs = global_timeout.as_secs_f64(),
            "Lifecycle: global shutdown timeout configured"
        );

        if trap_signals {
            let token = shutdown_token.clone();
            tokio::spawn(async move {
                signals::wait_for_shutdown_signal().await;
                token.cancel();
            });
        }

        if enable_prestop {
            let token = shutdown_token.clone();
            let prestop_path = self.prestop_path.clone();
            tokio::spawn(async move {
                let mut interval = tokio::time::interval(Duration::from_secs(1));
                loop {
                    interval.tick().await;
                    if prestop_path.exists() {
                        info!(
                            trigger_reason = "prestop",
                            path = %prestop_path.display(),
                            "Lifecycle: shutdown initiated, prestop file detected"
                        );
                        token.cancel();
                        break;
                    }
                }
            });
        }

        if has_liveness_components {
            let liveness_for_health = self.liveness_components.clone();
            let health_token = shutdown_token.clone();
            let health_event_tx = self
                .event_tx_slot
                .get()
                .expect("event channel not initialized")
                .clone();
            tokio::spawn(async move {
                let mut stall_counts: Vec<u32> = vec![0; liveness_for_health.len()];
                let mut interval = tokio::time::interval(health_poll_interval);
                loop {
                    tokio::select! {
                        _ = interval.tick() => {
                            let now_ms = SystemTime::now()
                                .duration_since(UNIX_EPOCH)
                                .unwrap_or_default()
                                .as_millis() as i64;
                            for (i, comp) in liveness_for_health.iter().enumerate() {
                                let until = comp.healthy_until_ms.load(Ordering::Relaxed);
                                let (healthy, status) = if until == HEALTH_UNHEALTHY {
                                    (false, "unhealthy")
                                } else if until == HEALTH_STARTING {
                                    continue;
                                } else if until > now_ms {
                                    (true, "healthy")
                                } else {
                                    (false, "stalled")
                                };

                                comp.health_gauge.set(if healthy { 1.0 } else { 0.0 });

                                if healthy {
                                    stall_counts[i] = 0;
                                } else {
                                    stall_counts[i] += 1;
                                    if stall_counts[i] >= comp.stall_threshold {
                                        warn!(
                                            component = %comp.tag,
                                            status,
                                            stall_count = stall_counts[i],
                                            stall_threshold = comp.stall_threshold,
                                            "Lifecycle: health stall threshold reached"
                                        );
                                        drop(health_event_tx.try_send(ComponentEvent::Failure {
                                            tag: comp.tag.clone(),
                                            reason: format!("health check {status} (stall count {}/{})", stall_counts[i], comp.stall_threshold),
                                        }));
                                        return;
                                    }
                                }
                            }
                        }
                        _ = health_token.cancelled() => break,
                    }
                }
            });
        }

        let mut first_failure: Option<LifecycleError> = None;

        // --- Phase 1: Normal operation ---
        // Events from both standard and observability components trigger shutdown.
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
                            if let Some(s) = self.get_component_mut(&tag) {
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
                            if let Some(s) = self.get_component_mut(&tag) {
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
                            if let Some(s) = self.get_component_mut(&tag) {
                                s.phase = ShutdownPhase::Completed;
                            }
                            if self.all_finished() {
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

        // --- Phase 2: Standard component drain ---
        let shutdown_clock = Instant::now();
        let global_deadline = shutdown_clock + global_timeout;

        for s in self.components.values_mut() {
            if s.phase == ShutdownPhase::Running {
                s.phase = ShutdownPhase::ShuttingDown;
            }
        }

        if !self.all_standard_finished() {
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
                    return self.emit_global_timeout(&name, global_timeout);
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
                                if let Some(s) = self.get_component_mut(&tag) {
                                    if s.phase == ShutdownPhase::ShuttingDown {
                                        s.phase = ShutdownPhase::Completed;
                                        if !self.is_observability_tag(&tag) {
                                            let elapsed = shutdown_clock.elapsed();
                                            metrics::emit_component_shutdown_duration(&name, &tag, "completed", elapsed.as_secs_f64());
                                            metrics::emit_component_shutdown_result(&name, &tag, "completed");
                                            info!(component = %tag,
                                                duration_secs = elapsed.as_secs_f64(),
                                                result = "completed",
                                                "Lifecycle: component completed shutdown");
                                        }
                                    } else {
                                        debug!(component = %tag, phase = ?s.phase,
                                            "Lifecycle: late WorkCompleted for already-finished component");
                                    }
                                }
                            }
                            ComponentEvent::Died { tag } => {
                                if let Some(s) = self.get_component_mut(&tag) {
                                    s.phase = ShutdownPhase::Died;
                                    if !self.is_observability_tag(&tag) {
                                        let elapsed = shutdown_clock.elapsed();
                                        metrics::emit_component_shutdown_duration(&name, &tag, "died", elapsed.as_secs_f64());
                                        metrics::emit_component_shutdown_result(&name, &tag, "died");
                                        warn!(component = %tag,
                                            duration_secs = elapsed.as_secs_f64(),
                                            result = "died",
                                            "Lifecycle: component died during shutdown");
                                    }
                                }
                            }
                            ComponentEvent::Failure { tag, reason } => {
                                if let Some(s) = self.get_component_mut(&tag) {
                                    s.phase = ShutdownPhase::Died;
                                    if !self.is_observability_tag(&tag) {
                                        let elapsed = shutdown_clock.elapsed();
                                        metrics::emit_component_shutdown_duration(&name, &tag, "died", elapsed.as_secs_f64());
                                        metrics::emit_component_shutdown_result(&name, &tag, "died");
                                        warn!(component = %tag,
                                            duration_secs = elapsed.as_secs_f64(),
                                            result = "died",
                                            "Lifecycle: component failed during shutdown");
                                    }
                                }
                                first_failure = first_failure.or(Some(LifecycleError::ComponentFailure { tag, reason }));
                            }
                            ComponentEvent::ShutdownRequested { .. } => {}
                        }
                        if self.all_standard_finished() {
                            break;
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
                        if self.all_standard_finished() {
                            break;
                        }
                    }
                }
            }
        }

        // --- Phase 3: Observability component drain ---
        if self.observability_components.is_empty() {
            return self.finalize_all(first_failure);
        }

        info!("Lifecycle: standard components finished, draining observability components");
        self.observability_shutdown_token.cancel();

        for s in self.observability_components.values_mut() {
            if s.phase == ShutdownPhase::Running {
                s.phase = ShutdownPhase::ShuttingDown;
            }
        }

        if !self.all_observability_finished() {
            let obs_clock = Instant::now();

            let mut obs_deadlines: Vec<(String, Instant)> = self
                .observability_components
                .iter()
                .map(|(tag, s)| {
                    let timeout = s
                        .graceful_shutdown
                        .unwrap_or(DEFAULT_OBSERVABILITY_SHUTDOWN_TIMEOUT);
                    (tag.clone(), obs_clock + timeout)
                })
                .collect();
            obs_deadlines.sort_by(|a, b| a.1.cmp(&b.1));

            loop {
                let now = Instant::now();
                if now >= global_deadline {
                    return self.emit_global_timeout(&name, global_timeout);
                }

                let next_obs_timeout = obs_deadlines
                    .iter()
                    .find(|(tag, _)| {
                        self.observability_components
                            .get(tag)
                            .map(|s| s.phase == ShutdownPhase::ShuttingDown)
                            == Some(true)
                    })
                    .map(|(_, t)| *t);

                let wait_duration = [
                    next_obs_timeout.map(|t| t.saturating_duration_since(now)),
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
                                if let Some(s) = self.observability_components.get_mut(&tag) {
                                    if s.phase == ShutdownPhase::ShuttingDown {
                                        s.phase = ShutdownPhase::Completed;
                                        info!(component = %tag,
                                            result = "completed",
                                            "Lifecycle: observability component completed shutdown");
                                    } else {
                                        debug!(component = %tag, phase = ?s.phase,
                                            "Lifecycle: late WorkCompleted for already-finished observability component");
                                    }
                                }
                            }
                            ComponentEvent::Died { tag } => {
                                if let Some(s) = self.observability_components.get_mut(&tag) {
                                    s.phase = ShutdownPhase::Died;
                                    warn!(component = %tag,
                                        result = "died",
                                        "Lifecycle: observability component died during shutdown");
                                }
                            }
                            ComponentEvent::Failure { tag, reason } => {
                                if let Some(s) = self.observability_components.get_mut(&tag) {
                                    s.phase = ShutdownPhase::Died;
                                    warn!(component = %tag,
                                        result = "died",
                                        "Lifecycle: observability component failed during shutdown: {reason}");
                                }
                                first_failure = first_failure.or(Some(LifecycleError::ComponentFailure { tag, reason }));
                            }
                            ComponentEvent::ShutdownRequested { .. } => {}
                        }
                        if self.all_observability_finished() {
                            break;
                        }
                    }
                    _ = tokio::time::sleep(wait_duration) => {
                        let now = Instant::now();
                        for (tag, deadline) in &obs_deadlines {
                            if now >= *deadline {
                                if let Some(s) = self.observability_components.get_mut(tag) {
                                    if s.phase == ShutdownPhase::ShuttingDown {
                                        s.phase = ShutdownPhase::TimedOut;
                                        warn!(component = %tag,
                                            duration_secs = s.graceful_shutdown
                                                .unwrap_or(DEFAULT_OBSERVABILITY_SHUTDOWN_TIMEOUT)
                                                .as_secs_f64(),
                                            result = "timeout",
                                            "Lifecycle: observability component timed out during shutdown");
                                    }
                                }
                            }
                        }
                        if self.all_observability_finished() {
                            break;
                        }
                    }
                }
            }
        }

        self.finalize_all(first_failure)
    }

    fn all_standard_finished(&self) -> bool {
        self.components.values().all(|s| {
            matches!(
                s.phase,
                ShutdownPhase::Completed | ShutdownPhase::Died | ShutdownPhase::TimedOut
            )
        })
    }

    fn all_observability_finished(&self) -> bool {
        self.observability_components.values().all(|s| {
            matches!(
                s.phase,
                ShutdownPhase::Completed | ShutdownPhase::Died | ShutdownPhase::TimedOut
            )
        })
    }

    fn all_finished(&self) -> bool {
        self.all_standard_finished() && self.all_observability_finished()
    }

    fn remaining_tags(&self) -> Vec<String> {
        self.components
            .iter()
            .chain(self.observability_components.iter())
            .filter(|(_, s)| {
                !matches!(
                    s.phase,
                    ShutdownPhase::Completed | ShutdownPhase::TimedOut | ShutdownPhase::Died
                )
            })
            .map(|(t, _)| t.clone())
            .collect()
    }

    fn emit_global_timeout(
        &self,
        service_name: &str,
        global_timeout: Duration,
    ) -> Result<(), LifecycleError> {
        let remaining = self.remaining_tags();
        for tag in &remaining {
            if !self.is_observability_tag(tag) {
                metrics::emit_component_shutdown_result(service_name, tag, "timeout");
            }
        }
        warn!(
            total_duration_secs = global_timeout.as_secs_f64(),
            remaining = ?remaining,
            "Lifecycle: global shutdown timeout reached"
        );
        Err(LifecycleError::ShutdownTimeout {
            elapsed: global_timeout,
            remaining,
        })
    }

    fn finalize_all(&self, first_failure: Option<LifecycleError>) -> Result<(), LifecycleError> {
        self.finalize(Instant::now(), first_failure)
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
            .chain(self.observability_components.values())
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
