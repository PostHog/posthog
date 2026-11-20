//! Peer awareness: the ready members of a pod's own Service, in a canonical
//! order every replica agrees on, plus this pod's position among them.
//!
//! A thin consumer of [`crate::watch_service_members_with_sync`]: each replica follows
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
    /// Where this pod sorts among the ready peers, counting itself while it is not ready.
    /// `None` until the first full list of the Service completes.
    pub position: Option<PeerPosition>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PeerPosition {
    pub index: usize,
    pub count: usize,
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

    pub fn is_synced(&self) -> bool {
        self.snapshot().position.is_some()
    }

    /// Replace the peer membership with `addrs`, recomputing order and self
    /// index.
    pub fn set_peers(&self, addrs: &HashSet<IpAddr>) {
        let mut peers: Vec<IpAddr> = addrs.iter().copied().collect();
        peers.sort_unstable();
        let found = peers.binary_search(&self.self_ip);
        let position = match found {
            Ok(index) => PeerPosition {
                index,
                count: peers.len(),
            },
            Err(index) => PeerPosition {
                index,
                count: peers.len() + 1,
            },
        };
        *self.current.write().unwrap() = Arc::new(PeerSet {
            peers,
            self_index: found.ok(),
            position: Some(position),
        });
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
        let (members, synced, _watch_task) = crate::watch_service_members_with_sync(
            client,
            namespace,
            service_name.clone(),
            cancel.clone(),
        );
        self.follow(members, synced, service_name, cancel)
    }

    /// Apply every update from a membership receiver until `cancel` fires or
    /// the sender goes away. Updates before `synced` turns true are partial
    /// lists and are held back; the first sync applies the full list, even an
    /// empty one. Split from [`PeerTracker::watch`] so tests can drive the
    /// loop with plain channels.
    pub fn follow(
        self: &Arc<Self>,
        mut members: watch::Receiver<HashSet<IpAddr>>,
        mut synced: watch::Receiver<bool>,
        service_name: String,
        cancel: CancellationToken,
    ) -> JoinHandle<()> {
        let tracker = Arc::clone(self);
        tokio::spawn(async move {
            let service_label: Arc<str> = Arc::from(service_name.as_str());
            let mut is_synced = *synced.borrow_and_update();
            if is_synced {
                tracker.apply(&mut members, &service_label);
            }
            loop {
                tokio::select! {
                    _ = cancel.cancelled() => return,
                    changed = synced.changed(), if !is_synced => {
                        if changed.is_err() {
                            return;
                        }
                        is_synced = *synced.borrow_and_update();
                    }
                    changed = members.changed() => {
                        if changed.is_err() {
                            return;
                        }
                        if !is_synced {
                            // Mark it seen so `changed()` doesn't fire again
                            // for the same partial list.
                            members.borrow_and_update();
                        }
                    }
                }
                if is_synced {
                    tracker.apply(&mut members, &service_label);
                }
            }
        })
    }

    fn apply(&self, members: &mut watch::Receiver<HashSet<IpAddr>>, service_label: &Arc<str>) {
        let addrs = members.borrow_and_update().clone();
        self.set_peers(&addrs);
        let set = self.snapshot();
        gauge!(
            "k8s_awareness_peer_count",
            "service" => Arc::clone(service_label),
        )
        .set(set.peer_count() as f64);
        // -1 means "self not (yet) a ready member".
        gauge!(
            "k8s_awareness_peer_index",
            "service" => Arc::clone(service_label),
        )
        .set(set.self_index.map_or(-1.0, |i| i as f64));
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

    #[test]
    fn test_position_counts_self_before_self_is_ready() {
        let tracker = PeerTracker::new(ip("10.0.0.5"));
        assert_eq!(tracker.snapshot().position, None);

        tracker.set_peers(&HashSet::from([ip("10.0.0.1"), ip("10.0.0.9")]));
        let before_ready = tracker.snapshot().position;
        assert_eq!(before_ready, Some(PeerPosition { index: 1, count: 3 }));

        tracker.set_peers(&HashSet::from([
            ip("10.0.0.1"),
            ip("10.0.0.9"),
            ip("10.0.0.5"),
        ]));
        assert_eq!(tracker.snapshot().position, before_ready);
    }

    async fn eventually(tracker: &PeerTracker, done: impl Fn(&PeerSet) -> bool) {
        for _ in 0..200 {
            if done(&tracker.snapshot()) {
                return;
            }
            tokio::time::sleep(std::time::Duration::from_millis(5)).await;
        }
        panic!(
            "peer set never reached the expected state: {:?}",
            tracker.snapshot()
        );
    }

    #[tokio::test]
    async fn test_follow_applies_membership_updates() {
        let tracker = PeerTracker::new(ip("10.0.0.2"));
        let (tx, rx) = tokio_watch::channel(HashSet::new());
        let (synced_tx, synced_rx) = tokio_watch::channel(false);
        let cancel = CancellationToken::new();
        let handle = tracker.follow(rx, synced_rx, "svc".to_string(), cancel.clone());

        tx.send(HashSet::from([ip("10.0.0.1")])).unwrap();
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        assert!(!tracker.is_synced());

        tx.send(HashSet::from([ip("10.0.0.2"), ip("10.0.0.1")]))
            .unwrap();
        synced_tx.send(true).unwrap();
        eventually(&tracker, |set| set.peer_count() == 2).await;
        let set = tracker.snapshot();
        assert_eq!(set.peers, vec![ip("10.0.0.1"), ip("10.0.0.2")]);
        assert_eq!(set.self_index, Some(1));

        cancel.cancel();
        handle.await.unwrap();
    }

    #[tokio::test]
    async fn test_follow_takes_the_whole_ring_when_the_first_list_is_empty() {
        // A lone pod, or every pod restarting: the Service has no ready
        // endpoints, so the members channel never publishes. The sync alone
        // must still place this pod.
        let tracker = PeerTracker::new(ip("10.0.0.2"));
        let (tx, rx) = tokio_watch::channel(HashSet::new());
        let (synced_tx, synced_rx) = tokio_watch::channel(false);
        let cancel = CancellationToken::new();
        let handle = tracker.follow(rx, synced_rx, "svc".to_string(), cancel.clone());
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        assert!(!tracker.is_synced());

        synced_tx.send(true).unwrap();
        eventually(&tracker, |set| set.position.is_some()).await;
        assert!(tracker.is_synced());
        assert_eq!(
            tracker.snapshot().position,
            Some(PeerPosition { index: 0, count: 1 })
        );

        synced_tx.send(true).unwrap();
        tx.send(HashSet::from([ip("10.0.0.1"), ip("10.0.0.2")]))
            .unwrap();
        eventually(&tracker, |set| set.peer_count() == 2).await;
        assert_eq!(
            tracker.snapshot().position,
            Some(PeerPosition { index: 1, count: 2 })
        );

        cancel.cancel();
        handle.await.unwrap();
    }
}
