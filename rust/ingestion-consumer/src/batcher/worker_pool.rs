use std::sync::Arc;
use std::time::{Duration, Instant};

use k8s_awareness::PeerTracker;
use tracing::{info, warn};

use crate::aperture;
use crate::routing::{Candidate, RoutingStrategy};
use crate::worker_registry::{WorkerId, WorkerRegistry};

const PEER_INDEX_POLL_INTERVAL: Duration = Duration::from_millis(100);

/// The routable workers for one action.
#[derive(Clone, Debug, Default)]
pub struct WorkerPool {
    pub healthy: Vec<WorkerId>,
    /// Candidates for fresh requests: the weighted aperture ring slice when
    /// narrowing applies, otherwise the healthy pool with uniform weights.
    pub candidates: Vec<Candidate>,
}

/// Captures a [`WorkerPool`] from the registry and the peer set.
#[derive(Clone)]
pub struct WorkerPoolSource {
    registry: Arc<WorkerRegistry>,
    strategy: RoutingStrategy,
    aperture: Option<(Arc<PeerTracker>, usize)>,
}

impl WorkerPoolSource {
    pub fn new(registry: Arc<WorkerRegistry>, strategy: RoutingStrategy) -> Self {
        Self {
            registry,
            strategy,
            aperture: None,
        }
    }

    /// Narrow fresh candidates to this consumer's slice of the worker ring,
    /// at least `min_aperture` wide. Only consulted under [`RoutingStrategy::Aperture`].
    pub fn set_aperture(&mut self, tracker: Arc<PeerTracker>, min_aperture: usize) {
        self.aperture = Some((tracker, min_aperture.max(1)));
    }

    pub fn registry(&self) -> &Arc<WorkerRegistry> {
        &self.registry
    }

    pub fn strategy(&self) -> RoutingStrategy {
        self.strategy
    }

    pub fn min_aperture(&self) -> Option<usize> {
        self.aperture.as_ref().map(|(_, width)| *width)
    }

    /// The ring slice of `healthy`, or `None` when narrowing does not apply.
    /// The slice falls back to `None` while the peer set is unknown, at
    /// startup or with peer awareness disabled.
    pub fn slice(&self, ring: &[WorkerId], healthy: &[WorkerId]) -> Option<Vec<Candidate>> {
        let (tracker, width) = self.active_aperture()?;
        let peers = tracker.snapshot();
        aperture::ring_slice(ring, healthy, peers.self_index, peers.peer_count(), *width)
    }

    pub async fn wait_for_peer_index(&self, timeout: Duration) {
        let Some((tracker, _)) = self.active_aperture() else {
            return;
        };
        info!("Waiting for this consumer's index among its peers");
        let started = Instant::now();
        let known = peer_index_known_within(tracker, timeout).await;
        let waited_ms = started.elapsed().as_millis() as u64;
        if known {
            info!(waited_ms, "Peer index known");
        } else {
            warn!(
                waited_ms,
                "No peer index before the timeout; requests go to the whole worker pool until the index is known"
            );
        }
    }

    pub fn pool(&self) -> WorkerPool {
        let healthy = self.registry.healthy_workers();
        let candidates = self
            .narrow(&healthy)
            .unwrap_or_else(|| uniform(healthy.iter().cloned()));
        WorkerPool {
            healthy,
            candidates,
        }
    }

    pub fn candidates(&self) -> Vec<Candidate> {
        let healthy = self.registry.healthy_workers();
        self.narrow(&healthy)
            .unwrap_or_else(|| uniform(healthy.into_iter()))
    }

    fn active_aperture(&self) -> Option<&(Arc<PeerTracker>, usize)> {
        if self.strategy == RoutingStrategy::Aperture {
            self.aperture.as_ref()
        } else {
            None
        }
    }

    fn narrow(&self, healthy: &[WorkerId]) -> Option<Vec<Candidate>> {
        self.active_aperture()?;
        let ring = aperture::sorted_ring(self.registry.members());
        self.slice(&ring, healthy)
    }
}

fn uniform(workers: impl Iterator<Item = WorkerId>) -> Vec<Candidate> {
    workers.map(Candidate::uniform).collect()
}

async fn peer_index_known_within(tracker: &PeerTracker, timeout: Duration) -> bool {
    let index_known = async {
        while tracker.snapshot().self_index.is_none() {
            tokio::time::sleep(PEER_INDEX_POLL_INTERVAL).await;
        }
    };
    tokio::time::timeout(timeout, index_known).await.is_ok()
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;
    use std::net::IpAddr;

    use super::*;

    const SELF_IP: &str = "10.0.0.2";
    const PEER_IP: &str = "10.0.0.1";
    const TIMEOUT: Duration = Duration::from_secs(30);

    fn ready_peers(ips: &[&str]) -> HashSet<IpAddr> {
        ips.iter().map(|ip| ip.parse().unwrap()).collect()
    }

    fn tracker_without_self() -> Arc<PeerTracker> {
        let tracker = PeerTracker::new(SELF_IP.parse().unwrap());
        tracker.set_peers(&ready_peers(&[PEER_IP]));
        tracker
    }

    #[tokio::test(start_paused = true)]
    async fn the_wait_ends_when_this_pod_becomes_a_ready_peer() {
        let tracker = tracker_without_self();
        let wait = tokio::spawn({
            let tracker = Arc::clone(&tracker);
            async move { peer_index_known_within(&tracker, TIMEOUT).await }
        });

        tokio::time::sleep(TIMEOUT / 2).await;
        assert!(!wait.is_finished(), "this pod is not a ready peer yet");

        tracker.set_peers(&ready_peers(&[PEER_IP, SELF_IP]));
        assert!(wait.await.unwrap());
    }

    #[tokio::test(start_paused = true)]
    async fn the_wait_gives_up_at_the_timeout() {
        let tracker = tracker_without_self();

        let waited = tokio::time::timeout(TIMEOUT * 2, peer_index_known_within(&tracker, TIMEOUT));

        assert!(matches!(waited.await, Ok(false)));
    }
}
