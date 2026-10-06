use std::sync::Arc;

use k8s_awareness::PeerTracker;

use crate::aperture;
use crate::routing::RoutingStrategy;
use crate::worker_registry::{WorkerId, WorkerRegistry};

/// The routable workers for one action.
#[derive(Clone, Debug, Default)]
pub struct WorkerPool {
    pub healthy: Vec<WorkerId>,
    /// Candidates for fresh requests: the aperture ring slice when narrowing
    /// applies, otherwise the healthy pool.
    pub candidates: Vec<WorkerId>,
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
    /// `min_aperture` wide. Only consulted under [`RoutingStrategy::Aperture`].
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
    pub fn slice(&self, ring: &[WorkerId], healthy: &[WorkerId]) -> Option<Vec<WorkerId>> {
        if self.strategy != RoutingStrategy::Aperture {
            return None;
        }
        let (tracker, width) = self.aperture.as_ref()?;
        let peers = tracker.snapshot();
        aperture::ring_slice(ring, healthy, peers.self_index, peers.peer_count(), *width)
    }

    pub fn pool(&self) -> WorkerPool {
        let healthy = self.registry.healthy_workers();
        let candidates = self.narrow(&healthy).unwrap_or_else(|| healthy.clone());
        WorkerPool {
            healthy,
            candidates,
        }
    }

    pub fn candidates(&self) -> Vec<WorkerId> {
        let healthy = self.registry.healthy_workers();
        self.narrow(&healthy).unwrap_or(healthy)
    }

    fn narrow(&self, healthy: &[WorkerId]) -> Option<Vec<WorkerId>> {
        let ring = aperture::sorted_ring(self.registry.workers());
        // The fleet's slices tile the pool, so each consumer's requests
        // consolidate onto few workers.
        self.slice(&ring, healthy)
    }
}
