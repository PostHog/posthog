use std::sync::{Arc, Mutex};

use tokio::sync::Notify;

const SERVER_IN_FLIGHT_ITEMS: &str = "cymbal_remote_resolution_server_in_flight_items";

#[derive(Clone, Debug)]
pub struct LoadSnapshot {
    pub in_flight: u32,
    pub max_in_flight: u32,
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
        let should_notify = {
            let mut state = self.lock_state();
            if state.in_flight >= self.max_in_flight {
                return false;
            }

            let old_load_bucket = load_bucket(state.in_flight, self.max_in_flight);
            state.in_flight = state.in_flight.saturating_add(1);
            record_in_flight(state.in_flight);
            old_load_bucket != load_bucket(state.in_flight, self.max_in_flight)
        };

        if should_notify {
            self.notify.notify_waiters();
        }

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
            max_in_flight: self.max_in_flight,
            draining: state.draining,
        }
    }

    fn update_state(&self, update: impl FnOnce(&mut LoadState)) {
        let should_notify = {
            let mut state = self.lock_state();
            let old_draining = state.draining;
            let old_load_bucket = load_bucket(state.in_flight, self.max_in_flight);

            update(&mut state);
            record_in_flight(state.in_flight);

            old_draining != state.draining
                || old_load_bucket != load_bucket(state.in_flight, self.max_in_flight)
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

fn load_bucket(in_flight: u32, max_in_flight: u32) -> u8 {
    if in_flight == 0 {
        return 0;
    }

    let pct = (u64::from(in_flight) * 100) / u64::from(max_in_flight.max(1));
    match pct {
        0..=24 => 1,
        25..=49 => 2,
        50..=74 => 3,
        75..=89 => 4,
        90..=99 => 5,
        _ => 6,
    }
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
    async fn notifies_when_load_crosses_thresholds() {
        let monitor = LoadMonitor::new(4);
        let waiter_monitor = monitor.clone();
        let waiter = tokio::spawn(async move {
            waiter_monitor.notified().await;
        });
        tokio::task::yield_now().await;

        monitor.set_in_flight(1);

        tokio::time::timeout(Duration::from_secs(1), waiter)
            .await
            .expect("load threshold change should notify")
            .expect("waiter should not panic");
    }

    #[tokio::test]
    async fn does_not_notify_for_load_changes_within_one_threshold_bucket() {
        let monitor = LoadMonitor::new(100);
        monitor.set_in_flight(1);

        let waiter_monitor = monitor.clone();
        let waiter = tokio::spawn(async move {
            waiter_monitor.notified().await;
        });
        tokio::task::yield_now().await;

        monitor.set_in_flight(2);

        assert!(tokio::time::timeout(Duration::from_millis(20), waiter)
            .await
            .is_err());
    }

    #[tokio::test]
    async fn increment_and_decrement_track_in_flight_lifecycle() {
        let monitor = LoadMonitor::new(2);
        monitor.increment_in_flight();
        assert_eq!(monitor.snapshot().in_flight, 1);
        assert_eq!(monitor.snapshot().max_in_flight, 2);

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

    #[test]
    fn load_bucket_uses_coarse_thresholds() {
        assert_eq!(load_bucket(0, 100), 0);
        assert_eq!(load_bucket(1, 100), 1);
        assert_eq!(load_bucket(24, 100), 1);
        assert_eq!(load_bucket(25, 100), 2);
        assert_eq!(load_bucket(50, 100), 3);
        assert_eq!(load_bucket(75, 100), 4);
        assert_eq!(load_bucket(90, 100), 5);
        assert_eq!(load_bucket(100, 100), 6);
    }
}
