use std::sync::{Arc, Mutex};

use tokio::sync::Notify;

#[derive(Clone, Debug)]
pub struct LoadSnapshot {
    pub in_flight: u32,
    pub degraded: bool,
    pub draining: bool,
    /// Remaining in-flight headroom before the degraded threshold
    /// (`threshold - in_flight`, saturating). `0` once degraded or when the
    /// signal is disabled, which callers treat as "no suggestion".
    pub suggested_batch_size: u32,
}

/// Tracks in-flight item processing and flips `degraded` once the count
/// reaches `degraded_threshold`. Concurrency itself is bounded elsewhere (the
/// item limiter); this only produces the load signal callers spill over on.
/// A `degraded_threshold` of `0` disables the signal (never degraded).
#[derive(Clone, Debug)]
pub struct LoadMonitor {
    state: Arc<Mutex<LoadState>>,
    notify: Arc<Notify>,
    degraded_threshold: u32,
}

#[derive(Clone, Copy, Debug, Default)]
struct LoadState {
    in_flight: u32,
    degraded: bool,
    draining: bool,
}

impl LoadMonitor {
    pub fn new(degraded_threshold: u32) -> Self {
        Self {
            state: Arc::new(Mutex::new(LoadState::default())),
            notify: Arc::new(Notify::new()),
            degraded_threshold,
        }
    }

    pub fn set_in_flight(&self, in_flight: u32) {
        self.update_state(|state| state.in_flight = in_flight);
    }

    pub fn increment_in_flight(&self) {
        self.update_state(|state| state.in_flight = state.in_flight.saturating_add(1));
    }

    pub fn decrement_in_flight(&self) {
        self.update_state(|state| state.in_flight = state.in_flight.saturating_sub(1));
    }

    pub fn set_draining(&self, draining: bool) {
        self.update_state(|state| state.draining = draining);
    }

    pub async fn notified(&self) {
        self.notify.notified().await;
    }

    pub fn snapshot(&self) -> LoadSnapshot {
        let state = self.lock_state();
        LoadSnapshot {
            in_flight: state.in_flight,
            degraded: state.degraded,
            draining: state.draining,
            suggested_batch_size: self.degraded_threshold.saturating_sub(state.in_flight),
        }
    }

    fn update_state(&self, update: impl FnOnce(&mut LoadState)) {
        let should_notify = {
            let mut state = self.lock_state();
            let old_degraded = state.degraded;
            let old_draining = state.draining;

            update(&mut state);
            state.degraded =
                self.degraded_threshold > 0 && state.in_flight >= self.degraded_threshold;

            old_degraded != state.degraded || old_draining != state.draining
        };

        if should_notify {
            self.notify.notify_waiters();
        }
    }

    fn lock_state(&self) -> std::sync::MutexGuard<'_, LoadState> {
        self.state.lock().expect("load monitor state poisoned")
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    #[tokio::test]
    async fn notifies_when_in_flight_crosses_degraded_threshold() {
        let monitor = LoadMonitor::new(3);
        monitor.set_in_flight(2);
        let waiter_monitor = monitor.clone();
        let waiter = tokio::spawn(async move {
            waiter_monitor.notified().await;
        });
        tokio::task::yield_now().await;

        monitor.set_in_flight(3);
        tokio::time::timeout(Duration::from_secs(1), waiter)
            .await
            .expect("threshold crossing should notify")
            .expect("waiter should not panic");
        assert!(monitor.snapshot().degraded);

        let waiter_monitor = monitor.clone();
        let waiter = tokio::spawn(async move {
            waiter_monitor.notified().await;
        });
        tokio::task::yield_now().await;

        monitor.set_in_flight(2);
        tokio::time::timeout(Duration::from_secs(1), waiter)
            .await
            .expect("recovery crossing should notify")
            .expect("waiter should not panic");
        assert!(!monitor.snapshot().degraded);
    }

    #[tokio::test]
    async fn increment_and_decrement_track_in_flight_lifecycle() {
        let monitor = LoadMonitor::new(2);
        monitor.increment_in_flight();
        assert_eq!(monitor.snapshot().in_flight, 1);

        monitor.decrement_in_flight();
        assert_eq!(monitor.snapshot().in_flight, 0);
    }

    #[test]
    fn suggested_batch_size_is_headroom_below_threshold_and_zero_otherwise() {
        let monitor = LoadMonitor::new(4);
        monitor.set_in_flight(1);
        assert_eq!(monitor.snapshot().suggested_batch_size, 3);

        monitor.set_in_flight(4);
        let snapshot = monitor.snapshot();
        assert!(snapshot.degraded);
        assert_eq!(snapshot.suggested_batch_size, 0);
    }

    #[test]
    fn zero_threshold_disables_degraded_signal() {
        let monitor = LoadMonitor::new(0);
        monitor.set_in_flight(100);
        let snapshot = monitor.snapshot();
        assert!(!snapshot.degraded);
        assert_eq!(snapshot.suggested_batch_size, 0);
    }
}
