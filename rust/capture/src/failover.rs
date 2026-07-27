//! Automatic failover / circuit-breaker machinery, dark-launched.
//!
//! The [`FailoverController`] generalizes the outputs layer's reactive
//! failover policy toward *autonomous* operation. Where the advisory mode
//! fails over only reactively (a retriable publish error, or an advisory
//! lifecycle handle going unhealthy), the controller drives a circuit
//! breaker: it tracks primary publish outcomes over an error-ratio window,
//! trips **open** when the primary looks broken, serves the secondary while
//! open, and periodically probes the primary (**half-open**) to recover —
//! all inside the failover output; no other layer knows.
//!
//! ## Dark launch
//!
//! The controller is constructed only when `CAPTURE_FAILOVER_ENABLED` is set
//! (defaults **off**). While off, the failover output runs its reactive
//! advisory mode and behavior is byte-identical to today. Nothing in this
//! module is reachable in production until the flag is flipped.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use metrics::{counter, gauge};

/// Injectable monotonic clock so breaker transitions are testable without
/// sleeps. Production uses [`SystemClock`]; tests use a manual clock.
pub trait Clock: Send + Sync {
    fn now(&self) -> Instant;
}

/// Real monotonic clock.
pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> Instant {
        Instant::now()
    }
}

/// The circuit-breaker states. `Closed` = serve primary; `Open` = serve
/// secondary (primary presumed broken); `HalfOpen` = send a probe to the
/// primary to test recovery.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BreakerState {
    Closed,
    Open,
    HalfOpen,
}

impl BreakerState {
    /// Static metric label — never allocate a `String` for these (rust/CLAUDE.md).
    fn as_label(self) -> &'static str {
        match self {
            BreakerState::Closed => "closed",
            BreakerState::Open => "open",
            BreakerState::HalfOpen => "half_open",
        }
    }

    fn as_gauge(self) -> f64 {
        match self {
            BreakerState::Closed => 0.0,
            BreakerState::HalfOpen => 1.0,
            BreakerState::Open => 2.0,
        }
    }
}

/// Where a single publish attempt should go. Chosen by the breaker; opaque to
/// callers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Route {
    Primary,
    Fallback,
}

/// The primary attempt's outcome as the breaker scores it. Only retriable
/// failures count as breaker errors — a rejected-payload fatal is the event's
/// fault, not the primary's.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AttemptOutcome {
    Success,
    Retriable,
    Fatal,
}

/// Tuning for the breaker. Deliberately not env-configurable in the skeleton —
/// the dark launch pins conservative defaults; knobs graduate to `Config` when
/// the feature leaves dark mode.
#[derive(Debug, Clone, Copy)]
pub struct BreakerConfig {
    /// Sliding window over which the primary error ratio is measured.
    pub window: Duration,
    /// Minimum primary attempts in the window before the ratio can trip the breaker.
    pub min_samples: usize,
    /// Error ratio in `[0, 1]` at or above which a closed breaker trips open.
    pub error_ratio_threshold: f64,
    /// How long the breaker stays open before allowing a half-open probe.
    pub open_cooldown: Duration,
    /// Consecutive successful probes needed to close a half-open breaker.
    pub half_open_required_successes: u32,
}

impl Default for BreakerConfig {
    fn default() -> Self {
        Self {
            window: Duration::from_secs(30),
            min_samples: 20,
            error_ratio_threshold: 0.5,
            open_cooldown: Duration::from_secs(5),
            half_open_required_successes: 3,
        }
    }
}

/// The pure breaker state machine. Kept free of I/O and of `Instant::now()` (the
/// clock is passed in) so every transition is unit-testable with an injected
/// clock and injected outcomes.
pub struct Breaker {
    config: BreakerConfig,
    state: BreakerState,
    /// `(timestamp, is_error)` of recent *primary* attempts, oldest first.
    window: VecDeque<(Instant, bool)>,
    /// When the breaker last tripped open (drives the half-open cooldown).
    opened_at: Option<Instant>,
    /// Consecutive successful probes accumulated while half-open.
    probe_successes: u32,
}

impl Breaker {
    pub fn new(config: BreakerConfig) -> Self {
        Self {
            config,
            state: BreakerState::Closed,
            window: VecDeque::new(),
            opened_at: None,
            probe_successes: 0,
        }
    }

    pub fn state(&self) -> BreakerState {
        self.state
    }

    fn trip_open(&mut self, now: Instant) -> Option<BreakerState> {
        self.transition(BreakerState::Open, now)
    }

    /// Apply a state change, resetting the bookkeeping the destination state
    /// owns. Returns the new state if it actually changed, so the caller can
    /// emit a transition metric.
    fn transition(&mut self, next: BreakerState, now: Instant) -> Option<BreakerState> {
        if self.state == next {
            return None;
        }
        self.state = next;
        match next {
            BreakerState::Open => {
                self.opened_at = Some(now);
                self.probe_successes = 0;
            }
            BreakerState::HalfOpen => {
                self.probe_successes = 0;
            }
            BreakerState::Closed => {
                self.opened_at = None;
                self.probe_successes = 0;
                self.window.clear();
            }
        }
        Some(next)
    }

    /// Decide where the next batch should go, advancing any time-driven
    /// transition (open → half-open once the cooldown elapses) and honoring the
    /// self-perspective health signal (unhealthy forces open). Returns the route
    /// plus any transition that fired.
    fn poll(&mut self, now: Instant, self_healthy: bool) -> (Route, Option<BreakerState>) {
        // Self-perspective health is a hard override: a primary the control
        // plane / advisory handle reports unhealthy trips the breaker open
        // regardless of the observed error ratio.
        if !self_healthy && self.state != BreakerState::Open {
            let t = self.trip_open(now);
            return (Route::Fallback, t);
        }

        match self.state {
            BreakerState::Closed => (Route::Primary, None),
            BreakerState::HalfOpen => (Route::Primary, None),
            BreakerState::Open => {
                let cooled = self
                    .opened_at
                    .map(|o| now.duration_since(o) >= self.config.open_cooldown)
                    .unwrap_or(true);
                if self_healthy && cooled {
                    let t = self.transition(BreakerState::HalfOpen, now);
                    (Route::Primary, t)
                } else {
                    (Route::Fallback, None)
                }
            }
        }
    }

    /// Record the outcome of a *primary* attempt and drive state transitions.
    /// Returns any transition that fired. Fatal outcomes are not counted as
    /// breaker errors — a rejected-payload fatal is the event's fault, not the
    /// primary's, and must not trip failover (mirrors the reactive mode, which
    /// fails over only on retriable).
    fn record(&mut self, now: Instant, outcome: AttemptOutcome) -> Option<BreakerState> {
        match self.state {
            BreakerState::Closed => {
                let is_error = matches!(outcome, AttemptOutcome::Retriable);
                self.window.push_back((now, is_error));
                self.evict_expired(now);
                if self.ratio_trips() {
                    self.trip_open(now)
                } else {
                    None
                }
            }
            BreakerState::HalfOpen => match outcome {
                AttemptOutcome::Success => {
                    self.probe_successes += 1;
                    if self.probe_successes >= self.config.half_open_required_successes {
                        self.transition(BreakerState::Closed, now)
                    } else {
                        None
                    }
                }
                // A probe failure (retriable or fatal) reopens the breaker: while
                // half-open every attempt is a deliberate health probe.
                AttemptOutcome::Retriable | AttemptOutcome::Fatal => self.trip_open(now),
            },
            // Open never routes to the primary, so it records no primary outcome.
            BreakerState::Open => None,
        }
    }

    fn evict_expired(&mut self, now: Instant) {
        while let Some(&(ts, _)) = self.window.front() {
            if now.duration_since(ts) > self.config.window {
                self.window.pop_front();
            } else {
                break;
            }
        }
    }

    fn ratio_trips(&self) -> bool {
        let total = self.window.len();
        if total < self.config.min_samples {
            return false;
        }
        let errors = self.window.iter().filter(|(_, e)| *e).count();
        (errors as f64 / total as f64) >= self.config.error_ratio_threshold
    }

    /// Current observed primary error ratio over the window, `0.0` when empty.
    /// Reported up to the control plane so peers can reason about this instance's
    /// self-perspective health.
    pub fn error_ratio(&self) -> f64 {
        let total = self.window.len();
        if total == 0 {
            return 0.0;
        }
        let errors = self.window.iter().filter(|(_, e)| *e).count();
        errors as f64 / total as f64
    }
}

/// Control-plane interface: where the primary should route, and a sink for this
/// instance's self-perspective health. Stubbed in the skeleton — the static
/// impl resolves to the locally-configured primary and swallows health reports.
/// A real impl would resolve broker hosts from a control plane and report health
/// so peers can make coordinated failover decisions. Publishers never see this
/// trait: it is an implementation detail of the failover output.
pub trait ControlPlane: Send + Sync {
    /// Resolve the current primary route. The skeleton only consumes
    /// `primary_available`; `primary_host` is carried for the eventual
    /// host-resolution impl.
    fn resolve(&self) -> RouteResolution;

    /// Publish this instance's self-perspective view of the primary path.
    fn report_health(&self, report: HealthReport);
}

/// A control plane's answer to "where does the primary produce right now?".
#[derive(Debug, Clone, Default)]
pub struct RouteResolution {
    /// Whether the control plane believes the primary path is usable at all. A
    /// `false` here trips the breaker open just like an unhealthy advisory handle.
    pub primary_available: bool,
    /// Control-plane-resolved primary host, if any. `None` = use the locally
    /// configured broker. Unused in the skeleton (the primary sink is already
    /// bound to its cluster); reserved for dynamic host resolution.
    pub primary_host: Option<String>,
}

/// This instance's self-perspective health, reported up to the control plane.
#[derive(Debug, Clone, Copy)]
pub struct HealthReport {
    pub state: BreakerState,
    pub error_ratio: f64,
}

/// No-op control plane: primary is always available and health reports are
/// dropped. There is **no** external service behind this — it is the static
/// stand-in that keeps the controller self-contained during dark launch.
pub struct StaticControlPlane;

impl ControlPlane for StaticControlPlane {
    fn resolve(&self) -> RouteResolution {
        RouteResolution {
            primary_available: true,
            primary_host: None,
        }
    }

    fn report_health(&self, _report: HealthReport) {}
}

/// The breaker-driven failover runtime the failover output drives when the
/// dark-launch flag is on: the breaker behind a mutex, the control plane, the
/// clock, and the half-open single-probe permit.
pub struct FailoverController {
    breaker: Mutex<Breaker>,
    control_plane: Arc<dyn ControlPlane>,
    clock: Arc<dyn Clock>,
    /// Bounds concurrent half-open probes to one in flight: while a probe is
    /// testing the primary, other batches route to the secondary rather than
    /// flooding a still-flaky primary with recovery traffic.
    probe_in_flight: AtomicBool,
}

impl FailoverController {
    /// Production defaults: static control plane, real clock, default breaker
    /// tuning. This is what `setup.rs` wires behind the dark flag.
    pub fn new() -> Self {
        Self::with_parts(
            Arc::new(StaticControlPlane),
            Arc::new(SystemClock),
            BreakerConfig::default(),
        )
    }

    /// Fully-injected constructor — the seam tests drive with a manual clock,
    /// a programmable control plane, and a chosen `BreakerConfig`.
    pub fn with_parts(
        control_plane: Arc<dyn ControlPlane>,
        clock: Arc<dyn Clock>,
        breaker_config: BreakerConfig,
    ) -> Self {
        gauge!("capture_failover_breaker_state").set(BreakerState::Closed.as_gauge());
        Self {
            breaker: Mutex::new(Breaker::new(breaker_config)),
            control_plane,
            clock,
            probe_in_flight: AtomicBool::new(false),
        }
    }

    /// Whether the control plane believes the primary path is usable. Folded
    /// into the self-perspective health input alongside the advisory handle.
    pub(crate) fn primary_available(&self) -> bool {
        self.control_plane.resolve().primary_available
    }

    /// Decide the route for the next batch, emitting any transition metric.
    /// Returns the route and the breaker state that made the decision.
    pub(crate) fn poll(&self, self_healthy: bool) -> (Route, BreakerState, f64) {
        let (route, transition, state, error_ratio) = {
            let mut breaker = self.breaker.lock().expect("breaker mutex poisoned");
            let (route, transition) = breaker.poll(self.clock.now(), self_healthy);
            (route, transition, breaker.state(), breaker.error_ratio())
        };
        if let Some(t) = transition {
            Self::emit_transition(t);
        }
        (route, state, error_ratio)
    }

    /// Try to win the half-open single-probe permit.
    pub(crate) fn try_acquire_probe(&self) -> bool {
        self.probe_in_flight
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
    }

    pub(crate) fn release_probe(&self) {
        self.probe_in_flight.store(false, Ordering::Release);
    }

    /// Record a primary attempt's outcome, emitting any transition metric, and
    /// report self-perspective health to the control plane.
    pub(crate) fn record(&self, outcome: AttemptOutcome, polled_state: BreakerState) {
        let (transition, error_ratio) = {
            let mut breaker = self.breaker.lock().expect("breaker mutex poisoned");
            let t = breaker.record(self.clock.now(), outcome);
            (t, breaker.error_ratio())
        };
        if let Some(t) = transition {
            Self::emit_transition(t);
        }
        self.control_plane.report_health(HealthReport {
            state: transition.unwrap_or(polled_state),
            error_ratio,
        });
    }

    /// Report health on a batch the breaker routed to the secondary (no primary
    /// attempt to record).
    pub(crate) fn report_routed_to_fallback(&self, state: BreakerState, error_ratio: f64) {
        self.control_plane
            .report_health(HealthReport { state, error_ratio });
    }

    fn emit_transition(state: BreakerState) {
        counter!("capture_failover_breaker_transitions_total", "to" => state.as_label())
            .increment(1);
        gauge!("capture_failover_breaker_state").set(state.as_gauge());
    }
}

impl Default for FailoverController {
    fn default() -> Self {
        Self::new()
    }
}

/// Deterministic test doubles shared with the outputs-layer failover tests.
#[cfg(test)]
pub(crate) mod testing {
    use super::*;

    /// Manual monotonic clock: deterministic, no sleeps.
    pub(crate) struct ManualClock {
        base: Instant,
        elapsed: Mutex<Duration>,
    }

    impl ManualClock {
        pub(crate) fn new() -> Arc<Self> {
            Arc::new(Self {
                base: Instant::now(),
                elapsed: Mutex::new(Duration::ZERO),
            })
        }
        pub(crate) fn advance(&self, by: Duration) {
            *self.elapsed.lock().unwrap() += by;
        }
    }

    impl Clock for ManualClock {
        fn now(&self) -> Instant {
            self.base + *self.elapsed.lock().unwrap()
        }
    }

    /// Breaker tuning small enough to drive transitions with a handful of
    /// batches.
    pub(crate) fn test_breaker_config() -> BreakerConfig {
        BreakerConfig {
            window: Duration::from_secs(30),
            min_samples: 4,
            error_ratio_threshold: 0.5,
            open_cooldown: Duration::from_secs(5),
            half_open_required_successes: 2,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::testing::ManualClock;
    use super::*;

    fn cfg() -> BreakerConfig {
        BreakerConfig {
            window: Duration::from_secs(30),
            min_samples: 4,
            error_ratio_threshold: 0.5,
            open_cooldown: Duration::from_secs(5),
            half_open_required_successes: 2,
        }
    }

    #[test]
    fn closed_stays_closed_below_min_samples() {
        let clock = ManualClock::new();
        let mut b = Breaker::new(cfg());
        for _ in 0..3 {
            b.record(clock.now(), AttemptOutcome::Retriable);
        }
        assert_eq!(b.state(), BreakerState::Closed);
    }

    #[test]
    fn closed_trips_open_when_ratio_exceeds_threshold() {
        let clock = ManualClock::new();
        let mut b = Breaker::new(cfg());
        b.record(clock.now(), AttemptOutcome::Success);
        b.record(clock.now(), AttemptOutcome::Retriable);
        b.record(clock.now(), AttemptOutcome::Retriable);
        assert_eq!(b.state(), BreakerState::Closed);
        let t = b.record(clock.now(), AttemptOutcome::Retriable);
        assert_eq!(t, Some(BreakerState::Open));
        assert_eq!(b.state(), BreakerState::Open);
    }

    #[test]
    fn fatal_outcomes_do_not_trip_the_breaker() {
        let clock = ManualClock::new();
        let mut b = Breaker::new(cfg());
        for _ in 0..8 {
            b.record(clock.now(), AttemptOutcome::Fatal);
        }
        assert_eq!(
            b.state(),
            BreakerState::Closed,
            "fatal outcomes are the event's fault and must not trip failover"
        );
    }

    #[test]
    fn expired_samples_leave_the_window() {
        let clock = ManualClock::new();
        let mut b = Breaker::new(cfg());
        for _ in 0..3 {
            b.record(clock.now(), AttemptOutcome::Retriable);
        }
        // Age the errors out of the window, then add fresh successes: the old
        // errors must not count toward the ratio.
        clock.advance(Duration::from_secs(31));
        for _ in 0..4 {
            b.record(clock.now(), AttemptOutcome::Success);
        }
        assert_eq!(b.state(), BreakerState::Closed);
        assert_eq!(b.error_ratio(), 0.0);
    }

    #[test]
    fn open_transitions_to_half_open_after_cooldown() {
        let clock = ManualClock::new();
        let mut b = Breaker::new(cfg());
        for _ in 0..4 {
            b.record(clock.now(), AttemptOutcome::Retriable);
        }
        assert_eq!(b.state(), BreakerState::Open);

        // Before the cooldown: still open, still routing to the fallback.
        let (route, t) = b.poll(clock.now(), true);
        assert_eq!(route, Route::Fallback);
        assert!(t.is_none());

        // After the cooldown: half-open, probe goes to the primary.
        clock.advance(Duration::from_secs(6));
        let (route, t) = b.poll(clock.now(), true);
        assert_eq!(route, Route::Primary);
        assert_eq!(t, Some(BreakerState::HalfOpen));
    }

    #[test]
    fn half_open_closes_after_required_successes() {
        let clock = ManualClock::new();
        let mut b = Breaker::new(cfg());
        for _ in 0..4 {
            b.record(clock.now(), AttemptOutcome::Retriable);
        }
        clock.advance(Duration::from_secs(6));
        b.poll(clock.now(), true);
        assert_eq!(b.state(), BreakerState::HalfOpen);

        assert!(b.record(clock.now(), AttemptOutcome::Success).is_none());
        let t = b.record(clock.now(), AttemptOutcome::Success);
        assert_eq!(t, Some(BreakerState::Closed));
        assert_eq!(b.error_ratio(), 0.0, "closing resets the window");
    }

    #[test]
    fn half_open_reopens_on_probe_failure() {
        let clock = ManualClock::new();
        let mut b = Breaker::new(cfg());
        for _ in 0..4 {
            b.record(clock.now(), AttemptOutcome::Retriable);
        }
        clock.advance(Duration::from_secs(6));
        b.poll(clock.now(), true);
        assert_eq!(b.state(), BreakerState::HalfOpen);

        let t = b.record(clock.now(), AttemptOutcome::Retriable);
        assert_eq!(t, Some(BreakerState::Open));
    }

    #[test]
    fn unhealthy_self_perspective_forces_open() {
        let clock = ManualClock::new();
        let mut b = Breaker::new(cfg());
        assert_eq!(b.state(), BreakerState::Closed);
        let (route, t) = b.poll(clock.now(), false);
        assert_eq!(route, Route::Fallback);
        assert_eq!(t, Some(BreakerState::Open));
    }
}
