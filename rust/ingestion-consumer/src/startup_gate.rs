//! The consumer's `/_readiness` answer: lifecycle's drain check, AND the
//! startup gate that opens right before the Kafka subscribe.
//!
//! The gate covers what the consumer waits for before it subscribes: the
//! first peer list (aperture routing) and at least one worker. It never
//! covers self being in the peer list (that list only gains self once this
//! pod is ready), partition assignment, or worker health: those flap, and
//! every readiness flip reshuffles every peer's ring arc.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use axum::http::StatusCode;
use k8s_awareness::PeerTracker;
use lifecycle::{Handle, ReadinessHandler};
use tracing::info;

const PEER_LIST_POLL: Duration = Duration::from_millis(250);
const PEER_LIST_LOG_EVERY: u32 = 40;

/// Wait until `tracker` has its first peer list, or shutdown. No timeout:
/// without the list there is no ring slice, and the first batch would open a
/// stream to every worker.
pub async fn wait_for_peer_list(tracker: &PeerTracker, service: &str, shutdown: &Handle) {
    let mut polls: u32 = 0;
    while !tracker.is_synced() {
        if polls.is_multiple_of(PEER_LIST_LOG_EVERY) {
            info!(service, "Waiting for the first peer list before consuming");
        }
        polls = polls.wrapping_add(1);
        tokio::select! {
            _ = shutdown.shutdown_recv() => {
                info!("Shutdown received while waiting for the peer list");
                return;
            }
            _ = tokio::time::sleep(PEER_LIST_POLL) => {}
        }
    }
}

#[derive(Clone)]
pub struct ConsumerReadiness {
    drain: ReadinessHandler,
    started: Arc<AtomicBool>,
}

impl ConsumerReadiness {
    pub fn new(drain: ReadinessHandler) -> Self {
        Self {
            drain,
            started: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn open(&self) {
        self.started.store(true, Ordering::Release);
    }

    pub fn is_ready(&self) -> bool {
        self.started.load(Ordering::Acquire) && self.drain.is_ready()
    }

    pub async fn check(&self) -> StatusCode {
        if self.is_ready() {
            StatusCode::OK
        } else {
            StatusCode::SERVICE_UNAVAILABLE
        }
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use std::collections::HashSet;

    use lifecycle::{ComponentOptions, Manager};

    use super::*;

    fn test_manager() -> Manager {
        Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .with_global_shutdown_timeout(Duration::from_secs(5))
            .build()
    }

    #[tokio::test]
    async fn the_peer_wait_holds_until_the_first_list_even_an_empty_one() {
        let mut manager = test_manager();
        let handle = manager.register("consumer", ComponentOptions::new());
        let tracker = PeerTracker::new("10.0.0.2".parse().unwrap());

        let held = tokio::time::timeout(
            Duration::from_millis(600),
            wait_for_peer_list(&tracker, "svc", &handle),
        )
        .await;
        assert!(held.is_err());

        tracker.set_peers(&HashSet::new());
        tokio::time::timeout(
            Duration::from_secs(2),
            wait_for_peer_list(&tracker, "svc", &handle),
        )
        .await
        .expect("the wait ends once the list is known");
    }

    #[tokio::test]
    async fn the_peer_wait_ends_on_shutdown() {
        let mut manager = test_manager();
        let handle = manager.register("consumer", ComponentOptions::new());
        let tracker = PeerTracker::new("10.0.0.2".parse().unwrap());

        let _guard = manager.monitor_background();
        handle.request_shutdown();
        tokio::time::timeout(
            Duration::from_secs(2),
            wait_for_peer_list(&tracker, "svc", &handle),
        )
        .await
        .expect("shutdown ends the wait");
    }

    #[tokio::test]
    async fn readiness_waits_for_the_gate_and_drops_on_drain() {
        let mut manager = test_manager();
        let handle = manager.register("consumer", ComponentOptions::new());
        let readiness = ConsumerReadiness::new(manager.readiness_handler());

        assert_eq!(readiness.check().await, StatusCode::SERVICE_UNAVAILABLE);
        readiness.open();
        assert_eq!(readiness.check().await, StatusCode::OK);

        let guard = manager.monitor_background();
        handle.request_shutdown();
        drop(handle);
        tokio::time::timeout(Duration::from_secs(10), guard.wait())
            .await
            .expect("timed out")
            .unwrap();
        assert_eq!(readiness.check().await, StatusCode::SERVICE_UNAVAILABLE);
    }
}
