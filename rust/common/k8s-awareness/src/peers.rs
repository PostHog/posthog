//! Peer awareness: the ready members of a pod's own Service, in a canonical
//! order every replica agrees on, plus this pod's position among them.
//!
//! A thin consumer of [`crate::watch_service_members`]: each replica follows
//! its own Service's membership and maintains a [`PeerSet`] snapshot — the
//! sorted ready peer IPs and this pod's index within them (located via its own
//! pod IP). Because every replica sees the same EndpointSlices and applies the
//! same ordering, `(self_index, peer_count)` is a coordination-free agreement,
//! usable for deterministic subsetting, ring slicing, or any scheme where
//! replicas must partition work without talking to each other.
//!
//! Snapshots are read from hot paths, so they sit behind an `Arc` swap in a
//! `std::sync::RwLock`: readers clone an `Arc` and never block on the watcher.

use std::collections::HashSet;
use std::net::IpAddr;
use std::sync::{Arc, RwLock};

use kube::Client;
use metrics::gauge;
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

/// Point-in-time view of a Service's ready members.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct PeerSet {
    /// Ready peer pod IPs, sorted — the canonical order all replicas agree on.
    pub peers: Vec<IpAddr>,
    /// This pod's position in `peers`. `None` until this pod is itself a ready
    /// endpoint (e.g. during startup, or while failing readiness probes).
    pub self_index: Option<usize>,
}

impl PeerSet {
    pub fn peer_count(&self) -> usize {
        self.peers.len()
    }
}

/// Tracks the ready members of one Service. Construct with the pod's own IP,
/// then drive it from the shared membership watch via [`PeerTracker::watch`],
/// or apply membership directly with [`PeerTracker::set_peers`] (tests,
/// non-K8s setups).
pub struct PeerTracker {
    self_ip: IpAddr,
    current: RwLock<Arc<PeerSet>>,
}

impl PeerTracker {
    pub fn new(self_ip: IpAddr) -> Arc<Self> {
        Arc::new(Self {
            self_ip,
            current: RwLock::new(Arc::new(PeerSet::default())),
        })
    }

    /// The current peer set. Cheap (one `Arc` clone); safe on hot paths.
    pub fn snapshot(&self) -> Arc<PeerSet> {
        Arc::clone(&self.current.read().unwrap())
    }

    /// Replace the peer membership with `addrs`, recomputing order and self
    /// index.
    pub fn set_peers(&self, addrs: &HashSet<IpAddr>) {
        let mut peers: Vec<IpAddr> = addrs.iter().copied().collect();
        peers.sort_unstable();
        let self_index = peers.iter().position(|ip| *ip == self.self_ip);
        *self.current.write().unwrap() = Arc::new(PeerSet { peers, self_index });
    }

    /// Watch `service_name`'s EndpointSlices in `namespace` and keep this
    /// tracker in sync until `cancel` fires.
    pub fn watch(
        self: &Arc<Self>,
        client: Client,
        namespace: String,
        service_name: String,
        cancel: CancellationToken,
    ) -> JoinHandle<()> {
        let (members, _watch_task) =
            crate::watch_service_members(client, namespace, service_name.clone(), cancel.clone());
        self.follow(members, service_name, cancel)
    }

    /// Apply every update from a membership receiver until `cancel` fires or
    /// the sender goes away. Split from [`PeerTracker::watch`] so tests can
    /// drive the loop with a plain channel.
    pub fn follow(
        self: &Arc<Self>,
        mut members: watch::Receiver<HashSet<IpAddr>>,
        service_name: String,
        cancel: CancellationToken,
    ) -> JoinHandle<()> {
        let tracker = Arc::clone(self);
        tokio::spawn(async move {
            let service_label: Arc<str> = Arc::from(service_name.as_str());
            loop {
                tokio::select! {
                    _ = cancel.cancelled() => return,
                    changed = members.changed() => {
                        if changed.is_err() {
                            return;
                        }
                        let addrs = members.borrow_and_update().clone();
                        tracker.set_peers(&addrs);
                        let set = tracker.snapshot();
                        gauge!(
                            "k8s_awareness_peer_count",
                            "service" => Arc::clone(&service_label),
                        )
                        .set(set.peer_count() as f64);
                        // -1 means "self not (yet) a ready member".
                        gauge!(
                            "k8s_awareness_peer_index",
                            "service" => Arc::clone(&service_label),
                        )
                        .set(set.self_index.map_or(-1.0, |i| i as f64));
                    }
                }
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use tokio::sync::watch as tokio_watch;

    use super::*;

    fn ip(s: &str) -> IpAddr {
        s.parse().unwrap()
    }

    #[test]
    fn test_set_peers_sorts_canonically_and_locates_self() {
        // Insertion order must not matter: two replicas fed the same set in a
        // different order have to agree on every peer's index.
        let tracker = PeerTracker::new(ip("10.0.0.5"));
        tracker.set_peers(&HashSet::from([
            ip("10.0.0.9"),
            ip("10.0.0.5"),
            ip("10.0.0.1"),
        ]));

        let set = tracker.snapshot();
        assert_eq!(
            set.peers,
            vec![ip("10.0.0.1"), ip("10.0.0.5"), ip("10.0.0.9")]
        );
        assert_eq!(set.self_index, Some(1));
        assert_eq!(set.peer_count(), 3);
    }

    #[test]
    fn test_self_index_none_until_self_is_ready() {
        let tracker = PeerTracker::new(ip("10.0.0.5"));
        tracker.set_peers(&HashSet::from([ip("10.0.0.1"), ip("10.0.0.9")]));
        assert_eq!(tracker.snapshot().self_index, None);

        // Self becomes a ready endpoint → gains an index.
        tracker.set_peers(&HashSet::from([
            ip("10.0.0.1"),
            ip("10.0.0.9"),
            ip("10.0.0.5"),
        ]));
        assert_eq!(tracker.snapshot().self_index, Some(1));
    }

    #[tokio::test]
    async fn test_follow_applies_membership_updates() {
        let tracker = PeerTracker::new(ip("10.0.0.2"));
        let (tx, rx) = tokio_watch::channel(HashSet::new());
        let cancel = CancellationToken::new();
        let handle = tracker.follow(rx, "svc".to_string(), cancel.clone());

        tx.send(HashSet::from([ip("10.0.0.2"), ip("10.0.0.1")]))
            .unwrap();
        // The follower runs on the runtime; wait for the update to land.
        for _ in 0..100 {
            if tracker.snapshot().peer_count() == 2 {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(5)).await;
        }
        let set = tracker.snapshot();
        assert_eq!(set.peers, vec![ip("10.0.0.1"), ip("10.0.0.2")]);
        assert_eq!(set.self_index, Some(1));

        cancel.cancel();
        handle.await.unwrap();
    }
}
