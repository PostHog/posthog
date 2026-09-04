use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use common_redis::{Client, CustomRedisError, RedisErrorKind};

/// Minimum time between heal-task spawns per gate. This only bounds task
/// creation — the client's own cooldown governs how often a dial actually
/// happens.
const HEAL_SPAWN_DEBOUNCE: Duration = Duration::from_secs(1);

/// Bounds heal-task spawns for one Redis client to a single in-flight task,
/// plus a debounce between spawns. Spawned tasks park on the client's heal
/// mutex while a dial is in flight, so without this an outage's failure storm
/// (hundreds of failing commands per batch) would pile up detached tasks
/// without bound — and a dial slower than the debounce would still queue them.
#[derive(Clone, Default)]
pub struct HealGate(Arc<Mutex<GateState>>);

#[derive(Default)]
struct GateState {
    last_spawn: Option<Instant>,
    in_flight: bool,
}

impl HealGate {
    pub fn new() -> Self {
        Self::default()
    }

    /// Run `heal` in a background task, unless one is already in flight or a
    /// spawn happened within the debounce window.
    pub(crate) fn spawn_heal<F>(&self, heal: F)
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        if !self.try_claim(Instant::now()) {
            return;
        }
        let gate = self.clone();
        tokio::spawn(async move {
            heal.await;
            gate.release();
        });
    }

    fn try_claim(&self, now: Instant) -> bool {
        let mut state = self.0.lock().unwrap();
        if state.in_flight
            || state
                .last_spawn
                .is_some_and(|t| now.duration_since(t) < HEAL_SPAWN_DEBOUNCE)
        {
            return false;
        }
        state.last_spawn = Some(now);
        state.in_flight = true;
        true
    }

    fn release(&self) {
        self.0.lock().unwrap().in_flight = false;
    }
}

/// True when the error means the shared Redis connection is broken (or points
/// at the wrong node) and rebuilding it can help. Timeouts deliberately don't
/// count: they are ambiguous with a slow-but-healthy Redis, and healing on
/// them would churn connections exactly when Redis is under load. The cost is
/// that a connection failing only with timeouts (a blackholed socket that
/// never resets) stays until a hard error surfaces — the same trade-off
/// capture's heal wiring makes.
pub fn is_connection_error(err: &CustomRedisError) -> bool {
    match err {
        // ReadOnly: after a failover the old primary can stay alive as a
        // replica, and only a redial (re-resolving the primary endpoint)
        // heals the writes. redis-rs maps it to `RetryMethod::NoRetry`, so
        // `is_unrecoverable_error()` alone would miss it.
        CustomRedisError::Redis(e) => {
            e.is_unrecoverable_error() || e.kind() == RedisErrorKind::ReadOnly
        }
        _ => false,
    }
}

/// Kick [`Client::heal`] in a background task when `err` is connection-class,
/// so the fail-open caller never waits on the redial. The gate bounds task
/// creation; heal attempts themselves are serialized and cooldown-bounded by
/// the client.
///
/// The underlying connection is shared by every user of the client, so one
/// healed call site repairs them all — only a hot path per client needs
/// wiring, not every error branch.
pub fn heal_on_connection_error(
    gate: &HealGate,
    redis: &Arc<dyn Client + Send + Sync>,
    err: &CustomRedisError,
) {
    if !is_connection_error(err) {
        return;
    }
    let redis = redis.clone();
    gate.spawn_heal(async move { redis.heal().await });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_connection_class_errors_heal() {
        let readonly = CustomRedisError::from_redis_kind(RedisErrorKind::ReadOnly, "READONLY");
        assert!(is_connection_error(&readonly));

        let dropped = CustomRedisError::from(redis_error(std::io::ErrorKind::BrokenPipe));
        assert!(is_connection_error(&dropped));

        // From<RedisError> maps IO timeouts to CustomRedisError::Timeout.
        let timeout = CustomRedisError::from(redis_error(std::io::ErrorKind::TimedOut));
        assert!(matches!(timeout, CustomRedisError::Timeout));
        assert!(!is_connection_error(&timeout));

        let app_error = CustomRedisError::from_redis_kind(RedisErrorKind::TypeError, "WRONGTYPE");
        assert!(!is_connection_error(&app_error));
        assert!(!is_connection_error(&CustomRedisError::NotFound));
    }

    fn redis_error(kind: std::io::ErrorKind) -> redis::RedisError {
        redis::RedisError::from(std::io::Error::new(kind, "test"))
    }

    // A failure storm must not spawn a heal task per failing command, and a
    // dial outlasting the debounce window must not queue further tasks.
    #[test]
    fn gate_allows_one_in_flight_heal_per_debounce_window() {
        let now = Instant::now();
        let gate = HealGate::new();
        assert!(gate.try_claim(now));
        for i in 0..10 {
            assert!(!gate.try_claim(now + i * HEAL_SPAWN_DEBOUNCE));
        }
        gate.release();
        assert!(!gate.try_claim(now));
        assert!(gate.try_claim(now + HEAL_SPAWN_DEBOUNCE));
    }
}
