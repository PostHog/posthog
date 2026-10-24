//! Bounds the operations a pod runs against one pool, and stops sending them while that pool's
//! database is unavailable.
//!
//! A semaphore the size of the pool caps the operations in flight. A caller waits for a slot at
//! most `max_wait`, much shorter than the pool's acquire timeout, so a stall fails fast instead
//! of queueing every request behind the stuck connections.
//!
//! A per-pod circuit breaker watches availability failures: a slot wait past `max_wait`, a failed
//! or abandoned connection acquire. Query errors do not count, because a bad query says nothing
//! about whether the database is reachable. When the failure rate in the window passes the
//! threshold, the breaker opens and rejects every operation without touching the pool. After the
//! open period, a few real operations go through as trials. If they all succeed, the breaker
//! closes. If one fails, the breaker opens again for double the period, with jitter so that pods
//! do not probe in step.

use std::{
    sync::{Arc, Mutex},
    time::Duration,
};

use rand::Rng;
use thiserror::Error;
use tokio::{
    sync::{OwnedSemaphorePermit, Semaphore},
    time::Instant,
};

/// Operations the gate rejected, labeled `pool` and `reason` (`open`, `half_open_busy`,
/// `saturated`).
pub const DB_GATE_REJECTED_COUNTER: &str = "db_gate_rejected_total";

/// Breaker state per `pool`: 0 closed, 1 half-open, 2 open.
pub const DB_GATE_BREAKER_STATE_GAUGE: &str = "db_gate_breaker_state";

/// Breaker transitions, labeled `pool` and `to` (`closed`, `half_open`, `open`).
pub const DB_GATE_BREAKER_TRANSITIONS_COUNTER: &str = "db_gate_breaker_transitions_total";

/// The window is split into this many buckets, so old calls leave it in steps of
/// `window / WINDOW_BUCKETS`.
const WINDOW_BUCKETS: usize = 10;

#[derive(Debug, Clone)]
pub struct OperationGateConfig {
    /// Most operations in flight. Set it to the pool's `max_connections`.
    pub max_concurrent: usize,
    /// Longest time an operation waits for a slot before it fails.
    pub max_wait: Duration,
    /// Time span over which the breaker counts calls and failures.
    pub window: Duration,
    /// Fewest calls in the window before the breaker can open. This keeps a few failures on a
    /// quiet pool from opening it.
    pub min_calls: u32,
    /// Fraction of failed calls in the window, from 0.0 to 1.0, that opens the breaker.
    pub failure_rate_threshold: f64,
    /// Open period after the first trip. Each failed trial doubles it, up to `max_open`.
    pub base_open: Duration,
    pub max_open: Duration,
    /// Fraction of the open period added or removed at random, from 0.0 to 1.0.
    pub open_jitter: f64,
    /// Trial operations allowed while half-open. All of them must succeed to close the breaker.
    pub half_open_trials: u32,
    /// Labels the gate's metrics.
    pub pool_name: Arc<str>,
}

impl Default for OperationGateConfig {
    fn default() -> Self {
        Self {
            max_concurrent: 10,
            max_wait: Duration::from_millis(100),
            window: Duration::from_secs(10),
            min_calls: 50,
            failure_rate_threshold: 0.5,
            base_open: Duration::from_secs(1),
            max_open: Duration::from_secs(30),
            open_jitter: 0.2,
            half_open_trials: 3,
            pool_name: Arc::from("unknown"),
        }
    }
}

#[derive(Error, Debug, Clone, Copy, PartialEq, Eq)]
pub enum GateRejection {
    #[error("circuit breaker is open")]
    Open,
    #[error("circuit breaker is half-open and all trial slots are in use")]
    HalfOpenBusy,
    #[error("no operation slot became free within the wait cap")]
    Saturated,
}

impl GateRejection {
    pub fn as_label(&self) -> &'static str {
        match self {
            GateRejection::Open => "open",
            GateRejection::HalfOpenBusy => "half_open_busy",
            GateRejection::Saturated => "saturated",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BreakerState {
    Closed,
    HalfOpen,
    Open,
}

impl BreakerState {
    fn as_label(&self) -> &'static str {
        match self {
            BreakerState::Closed => "closed",
            BreakerState::HalfOpen => "half_open",
            BreakerState::Open => "open",
        }
    }

    fn as_gauge(&self) -> f64 {
        match self {
            BreakerState::Closed => 0.0,
            BreakerState::HalfOpen => 1.0,
            BreakerState::Open => 2.0,
        }
    }
}

#[derive(Default, Clone, Copy)]
struct Bucket {
    /// Index of the bucket period that these counts belong to.
    period: u64,
    calls: u32,
    failures: u32,
}

struct Breaker {
    state: BreakerState,
    /// Changes on each transition. An outcome from an operation admitted under an older epoch
    /// cannot change the current state.
    epoch: u64,
    buckets: [Bucket; WINDOW_BUCKETS],
    /// The breaker reopens for this long after a failed trial, before doubling.
    open_period: Duration,
    open_until: Instant,
    trials_admitted: u32,
    trials_succeeded: u32,
}

/// Cheap to clone; clones share one state.
#[derive(Clone)]
pub struct OperationGate {
    inner: Arc<Inner>,
}

struct Inner {
    config: OperationGateConfig,
    started: Instant,
    semaphore: Arc<Semaphore>,
    breaker: Mutex<Breaker>,
}

/// Holds an operation slot. Report how the operation went with `record_success` or
/// `record_failure`. A permit dropped with no outcome counts as a failure, because a caller that
/// abandons an operation, for example at a deadline, did so because the database did not answer.
pub struct GatePermit {
    gate: OperationGate,
    epoch: u64,
    trial: bool,
    recorded: bool,
    _slot: OwnedSemaphorePermit,
}

impl GatePermit {
    pub fn record_success(&mut self) {
        self.record(true);
    }

    pub fn record_failure(&mut self) {
        self.record(false);
    }

    fn record(&mut self, success: bool) {
        if self.recorded {
            return;
        }
        self.recorded = true;
        self.gate.record_outcome(self.epoch, self.trial, success);
    }
}

impl Drop for GatePermit {
    fn drop(&mut self) {
        self.record(false);
    }
}

impl OperationGate {
    pub fn new(config: OperationGateConfig) -> Self {
        let now = Instant::now();
        let gate = Self {
            inner: Arc::new(Inner {
                semaphore: Arc::new(Semaphore::new(config.max_concurrent.max(1))),
                started: now,
                breaker: Mutex::new(Breaker {
                    state: BreakerState::Closed,
                    epoch: 0,
                    buckets: [Bucket::default(); WINDOW_BUCKETS],
                    open_period: config.base_open,
                    open_until: now,
                    trials_admitted: 0,
                    trials_succeeded: 0,
                }),
                config,
            }),
        };
        gate.emit_state(BreakerState::Closed);
        gate
    }

    pub fn state(&self) -> BreakerState {
        self.lock().state
    }

    /// Admits an operation, or rejects it without touching the pool.
    pub async fn enter(&self) -> Result<GatePermit, GateRejection> {
        let (epoch, trial) = match self.admit() {
            Ok(admitted) => admitted,
            Err(rejection) => {
                self.count_rejection(rejection);
                return Err(rejection);
            }
        };

        let slot = tokio::time::timeout(
            self.inner.config.max_wait,
            Arc::clone(&self.inner.semaphore).acquire_owned(),
        )
        .await;
        match slot {
            Ok(Ok(slot)) => Ok(GatePermit {
                gate: self.clone(),
                epoch,
                trial,
                recorded: false,
                _slot: slot,
            }),
            // The semaphore is never closed, so only the timeout reaches here in practice.
            _ => {
                self.record_outcome(epoch, trial, false);
                self.count_rejection(GateRejection::Saturated);
                Err(GateRejection::Saturated)
            }
        }
    }

    fn admit(&self) -> Result<(u64, bool), GateRejection> {
        let now = Instant::now();
        let mut breaker = self.lock();
        if breaker.state == BreakerState::Open {
            if now < breaker.open_until {
                return Err(GateRejection::Open);
            }
            self.transition(&mut breaker, BreakerState::HalfOpen);
        }
        match breaker.state {
            BreakerState::Closed => Ok((breaker.epoch, false)),
            BreakerState::HalfOpen if breaker.trials_admitted < self.trials() => {
                breaker.trials_admitted += 1;
                Ok((breaker.epoch, true))
            }
            BreakerState::HalfOpen => Err(GateRejection::HalfOpenBusy),
            BreakerState::Open => Err(GateRejection::Open),
        }
    }

    fn record_outcome(&self, epoch: u64, trial: bool, success: bool) {
        let now = Instant::now();
        let mut breaker = self.lock();
        if breaker.epoch != epoch {
            return;
        }
        match breaker.state {
            BreakerState::Closed if !trial => {
                let period = self.bucket_period(now);
                let bucket = &mut breaker.buckets[period as usize % WINDOW_BUCKETS];
                if bucket.period != period {
                    *bucket = Bucket {
                        period,
                        ..Bucket::default()
                    };
                }
                bucket.calls += 1;
                if !success {
                    bucket.failures += 1;
                }
                if !success && self.window_should_trip(&breaker, period) {
                    breaker.open_period = self.inner.config.base_open;
                    self.open(&mut breaker, now);
                }
            }
            BreakerState::HalfOpen if trial => {
                if !success {
                    let doubled = breaker.open_period.saturating_mul(2);
                    breaker.open_period = doubled.min(self.inner.config.max_open);
                    self.open(&mut breaker, now);
                    return;
                }
                breaker.trials_succeeded += 1;
                if breaker.trials_succeeded >= self.trials() {
                    breaker.open_period = self.inner.config.base_open;
                    breaker.buckets = [Bucket::default(); WINDOW_BUCKETS];
                    self.transition(&mut breaker, BreakerState::Closed);
                }
            }
            _ => {}
        }
    }

    fn window_should_trip(&self, breaker: &Breaker, current_period: u64) -> bool {
        let oldest = current_period.saturating_sub(WINDOW_BUCKETS as u64 - 1);
        let (calls, failures) = breaker
            .buckets
            .iter()
            .filter(|b| b.period >= oldest && b.period <= current_period)
            .fold((0u32, 0u32), |(c, f), b| (c + b.calls, f + b.failures));
        calls >= self.inner.config.min_calls
            && calls > 0
            && f64::from(failures) / f64::from(calls) >= self.inner.config.failure_rate_threshold
    }

    fn open(&self, breaker: &mut Breaker, now: Instant) {
        breaker.open_until = now + self.jittered(breaker.open_period);
        self.transition(breaker, BreakerState::Open);
    }

    fn jittered(&self, period: Duration) -> Duration {
        let jitter = self.inner.config.open_jitter.clamp(0.0, 1.0);
        if jitter == 0.0 {
            return period;
        }
        let factor = rand::thread_rng().gen_range((1.0 - jitter)..=(1.0 + jitter));
        period.mul_f64(factor)
    }

    fn transition(&self, breaker: &mut Breaker, to: BreakerState) {
        breaker.state = to;
        breaker.epoch += 1;
        breaker.trials_admitted = 0;
        breaker.trials_succeeded = 0;
        metrics::counter!(
            DB_GATE_BREAKER_TRANSITIONS_COUNTER,
            "pool" => self.inner.config.pool_name.clone(),
            "to" => to.as_label()
        )
        .increment(1);
        self.emit_state(to);
    }

    fn emit_state(&self, state: BreakerState) {
        metrics::gauge!(DB_GATE_BREAKER_STATE_GAUGE, "pool" => self.inner.config.pool_name.clone())
            .set(state.as_gauge());
    }

    fn count_rejection(&self, rejection: GateRejection) {
        metrics::counter!(
            DB_GATE_REJECTED_COUNTER,
            "pool" => self.inner.config.pool_name.clone(),
            "reason" => rejection.as_label()
        )
        .increment(1);
    }

    fn bucket_period(&self, now: Instant) -> u64 {
        let bucket =
            (self.inner.config.window / WINDOW_BUCKETS as u32).max(Duration::from_millis(1));
        (now.duration_since(self.inner.started).as_nanos() / bucket.as_nanos()) as u64
    }

    fn trials(&self) -> u32 {
        self.inner.config.half_open_trials.max(1)
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Breaker> {
        // A panic while the lock is held leaves only counters behind, which stay usable.
        self.inner
            .breaker
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> OperationGateConfig {
        OperationGateConfig {
            max_concurrent: 2,
            max_wait: Duration::from_millis(50),
            window: Duration::from_secs(10),
            min_calls: 4,
            failure_rate_threshold: 0.5,
            base_open: Duration::from_secs(1),
            max_open: Duration::from_secs(4),
            open_jitter: 0.0,
            half_open_trials: 2,
            pool_name: Arc::from("test"),
        }
    }

    async fn run(gate: &OperationGate, success: bool) -> Result<(), GateRejection> {
        let mut permit = gate.enter().await?;
        if success {
            permit.record_success();
        } else {
            permit.record_failure();
        }
        Ok(())
    }

    async fn trip(gate: &OperationGate) {
        for _ in 0..4 {
            run(gate, false).await.unwrap();
        }
        assert_eq!(gate.state(), BreakerState::Open);
    }

    #[tokio::test(start_paused = true)]
    async fn stays_closed_below_min_calls() {
        let gate = OperationGate::new(config());
        for _ in 0..3 {
            run(&gate, false).await.unwrap();
        }
        assert_eq!(gate.state(), BreakerState::Closed);
    }

    #[tokio::test(start_paused = true)]
    async fn stays_closed_below_failure_rate() {
        let gate = OperationGate::new(config());
        for success in [true, true, true, false, true, false] {
            run(&gate, success).await.unwrap();
        }
        assert_eq!(gate.state(), BreakerState::Closed);
    }

    #[tokio::test(start_paused = true)]
    async fn failures_leave_the_window() {
        let gate = OperationGate::new(config());
        for _ in 0..3 {
            run(&gate, false).await.unwrap();
        }
        tokio::time::advance(Duration::from_secs(11)).await;
        run(&gate, false).await.unwrap();
        assert_eq!(gate.state(), BreakerState::Closed);
    }

    #[tokio::test(start_paused = true)]
    async fn open_breaker_rejects_until_the_period_ends() {
        let gate = OperationGate::new(config());
        trip(&gate).await;
        assert_eq!(run(&gate, true).await, Err(GateRejection::Open));

        tokio::time::advance(Duration::from_secs(1)).await;
        run(&gate, true).await.unwrap();
        assert_eq!(gate.state(), BreakerState::HalfOpen);
    }

    #[tokio::test(start_paused = true)]
    async fn half_open_admits_only_the_trials_and_closes_when_they_succeed() {
        let gate = OperationGate::new(config());
        trip(&gate).await;
        tokio::time::advance(Duration::from_secs(1)).await;

        let mut first = gate.enter().await.unwrap();
        let mut second = gate.enter().await.unwrap();
        assert_eq!(gate.enter().await.err(), Some(GateRejection::HalfOpenBusy));

        first.record_success();
        second.record_success();
        assert_eq!(gate.state(), BreakerState::Closed);
    }

    #[tokio::test(start_paused = true)]
    async fn failed_trial_doubles_the_open_period_up_to_the_cap() {
        let gate = OperationGate::new(config());
        trip(&gate).await;

        let mut wait = Duration::from_secs(1);
        for next_open_secs in [2, 4, 4] {
            tokio::time::advance(wait).await;
            run(&gate, false).await.unwrap();
            assert_eq!(gate.state(), BreakerState::Open);

            let almost = Duration::from_secs(next_open_secs) - Duration::from_millis(1);
            tokio::time::advance(almost).await;
            assert_eq!(run(&gate, true).await, Err(GateRejection::Open));
            wait = Duration::from_millis(1);
        }
        tokio::time::advance(wait).await;
        run(&gate, true).await.unwrap();
        assert_eq!(gate.state(), BreakerState::HalfOpen);
    }

    #[tokio::test(start_paused = true)]
    async fn dropped_permit_counts_as_failure() {
        let gate = OperationGate::new(config());
        for _ in 0..4 {
            drop(gate.enter().await.unwrap());
        }
        assert_eq!(gate.state(), BreakerState::Open);
    }

    #[tokio::test(start_paused = true)]
    async fn full_slots_reject_after_the_wait_cap_and_count_as_failures() {
        let gate = OperationGate::new(config());
        let held = [gate.enter().await.unwrap(), gate.enter().await.unwrap()];
        for _ in 0..4 {
            assert_eq!(gate.enter().await.err(), Some(GateRejection::Saturated));
        }
        assert_eq!(gate.state(), BreakerState::Open);
        drop(held);
    }

    #[tokio::test(start_paused = true)]
    async fn outcomes_from_before_a_trip_do_not_affect_half_open() {
        let gate = OperationGate::new(config());
        let mut late = gate.enter().await.unwrap();
        trip(&gate).await;
        tokio::time::advance(Duration::from_secs(1)).await;
        let mut trial = gate.enter().await.unwrap();
        late.record_failure();
        assert_eq!(gate.state(), BreakerState::HalfOpen);
        trial.record_success();
        assert_eq!(gate.state(), BreakerState::HalfOpen);
    }
}
