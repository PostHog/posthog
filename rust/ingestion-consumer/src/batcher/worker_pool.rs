use std::sync::Arc;

use k8s_awareness::PeerTracker;

use crate::aperture;
use crate::routing::{Candidate, RoutingStrategy};
use crate::worker_registry::{WorkerId, WorkerRegistry};

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
        let position = tracker.snapshot().position?;
        aperture::ring_slice(ring, healthy, Some(position.index), position.count, *width)
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

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use rstest::rstest;

    use super::*;
    use crate::worker_registry::WorkerRegistryConfig;

    fn worker_url(n: usize) -> String {
        format!("http://10.1.0.{n}:6738")
    }

    fn six_workers() -> WorkerRegistry {
        let urls: Vec<String> = (1..=6).map(worker_url).collect();
        WorkerRegistry::new(
            &urls,
            WorkerRegistryConfig {
                probe_interval: Duration::from_millis(50),
                dead_declaration: Duration::from_millis(100),
                passive_window: Duration::from_millis(500),
                passive_error_threshold: 0.5,
                passive_min_samples: 5,
                degraded_hold: Duration::from_millis(50),
                min_state_duration: Duration::ZERO,
                probe_failure_threshold: 2,
                drain_timeout: Duration::from_secs(5),
            },
        )
    }

    #[rstest]
    #[case::not_a_ready_peer(&["10.0.0.1", "10.0.0.3"])]
    #[case::a_ready_peer(&["10.0.0.1", "10.0.0.2", "10.0.0.3"])]
    fn a_consumer_gets_the_slice_of_its_place_among_its_peers(#[case] ready_peers: &[&str]) {
        let tracker = PeerTracker::new("10.0.0.2".parse().unwrap());
        tracker.set_peers(&ready_peers.iter().map(|ip| ip.parse().unwrap()).collect());
        let mut source = WorkerPoolSource::new(Arc::new(six_workers()), RoutingStrategy::Aperture);
        source.set_aperture(tracker, 1);

        let slice: Vec<WorkerId> = source.candidates().into_iter().map(|c| c.worker).collect();

        let second_third = [worker_url(3), worker_url(4)].map(|url| WorkerId::from(url.as_str()));
        assert_eq!(slice, second_third);
    }
}
