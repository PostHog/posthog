use std::sync::{Arc, Mutex};

use tokio::sync::Notify;

const SERVER_IN_FLIGHT_ITEMS: &str = "cymbal_remote_resolution_server_in_flight_items";

#[derive(Clone, Debug)]
pub struct LoadSnapshot {
    pub in_flight: u32,
    pub draining: bool,
}

/// Tracks in-flight item processing and admits work up to `max_in_flight`.
/// Overload is reported only as per-item Resolve outcomes, not through the
/// Subscribe stream.
#[derive(Clone, Debug)]
pub struct LoadMonitor {
    state: Arc<Mutex<LoadState>>,
    notify: Arc<Notify>,
    max_in_flight: u32,
}

#[derive(Clone, Copy, Debug, Default)]
struct LoadState {
    in_flight: u32,
    draining: bool,
}

impl LoadMonitor {
    pub fn new(max_in_flight: u32) -> Self {
        Self {
            state: Arc::new(Mutex::new(LoadState::default())),
            notify: Arc::new(Notify::new()),
            max_in_flight: max_in_flight.max(1),
        }
    }

    pub fn try_admit(&self) -> bool {
        let mut state = self.lock_state();
        if state.in_flight >= self.max_in_flight {
            return false;
        }

        state.in_flight = state.in_flight.saturating_add(1);
        record_in_flight(state.in_flight);
        true
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
            draining: state.draining,
        }
    }

    fn update_state(&self, update: impl FnOnce(&mut LoadState)) {
        let should_notify = {
            let mut state = self.lock_state();
            let old_draining = state.draining;

            update(&mut state);
            record_in_flight(state.in_flight);

            old_draining != state.draining
        };

        if should_notify {
            self.notify.notify_waiters();
        }
    }

    fn lock_state(&self) -> std::sync::MutexGuard<'_, LoadState> {
        self.state.lock().expect("load monitor state poisoned")
    }
}

fn record_in_flight(in_flight: u32) {
    metrics::gauge!(SERVER_IN_FLIGHT_ITEMS).set(in_flight as f64);
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    #[tokio::test]
    async fn notifies_when_draining_changes() {
        let monitor = LoadMonitor::new(3);
        let waiter_monitor = monitor.clone();
        let waiter = tokio::spawn(async move {
            waiter_monitor.notified().await;
        });
        tokio::task::yield_now().await;

        monitor.set_draining(true);
        tokio::time::timeout(Duration::from_secs(1), waiter)
            .await
            .expect("draining change should notify")
            .expect("waiter should not panic");
        assert!(monitor.snapshot().draining);
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
    fn try_admit_checks_and_increments_under_one_lock() {
        let monitor = LoadMonitor::new(2);

        assert!(monitor.try_admit());
        assert!(monitor.try_admit());
        assert!(!monitor.try_admit());
        assert_eq!(monitor.snapshot().in_flight, 2);

        monitor.decrement_in_flight();
        assert!(monitor.try_admit());
        assert_eq!(monitor.snapshot().in_flight, 2);
    }
}
