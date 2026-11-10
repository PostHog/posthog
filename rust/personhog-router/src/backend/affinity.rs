use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::net::SocketAddr;
use std::sync::RwLock;

use tonic::transport::Channel;

/// One lazily connected channel per discovered pod, so a key keeps reaching the same pod.
#[derive(Default)]
pub struct PodChannels {
    pods: RwLock<Vec<(SocketAddr, Channel)>>,
}

impl PodChannels {
    pub fn insert(&self, addr: SocketAddr, channel: Channel) {
        let mut pods = self.pods.write().expect("pod channels lock poisoned");
        pods.retain(|(existing, _)| *existing != addr);
        pods.push((addr, channel));
    }

    pub fn remove(&self, addr: SocketAddr) {
        self.pods
            .write()
            .expect("pod channels lock poisoned")
            .retain(|(existing, _)| *existing != addr);
    }

    pub fn pick(&self, key: &[u8]) -> Option<Channel> {
        let pods = self.pods.read().expect("pod channels lock poisoned");
        let index = rendezvous(key, pods.iter().map(|(addr, _)| addr))?;
        Some(pods[index].1.clone())
    }
}

/// Highest-random-weight hashing: adding or removing a pod moves only the keys that pod wins,
/// and every router agrees on the winner.
fn rendezvous<'a>(key: &[u8], addrs: impl Iterator<Item = &'a SocketAddr>) -> Option<usize> {
    addrs
        .enumerate()
        .max_by_key(|(_, addr)| {
            let mut hasher = DefaultHasher::new();
            key.hash(&mut hasher);
            addr.hash(&mut hasher);
            hasher.finish()
        })
        .map(|(index, _)| index)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn addrs(count: u8) -> Vec<SocketAddr> {
        (1..=count)
            .map(|n| SocketAddr::from(([10, 0, 0, n], 50051)))
            .collect()
    }

    fn winner(key: &str, pods: &[SocketAddr]) -> SocketAddr {
        pods[rendezvous(key.as_bytes(), pods.iter()).unwrap()]
    }

    #[test]
    fn a_key_lands_on_the_same_pod_whatever_the_discovery_order() {
        let pods = addrs(8);
        let mut reversed = pods.clone();
        reversed.reverse();

        for key in ["1:alice", "1:bob", "42:carol"] {
            assert_eq!(winner(key, &pods), winner(key, &reversed), "key {key}");
        }
    }

    #[test]
    fn a_new_pod_takes_keys_only_from_the_pods_it_beats() {
        let before = addrs(8);
        let after = addrs(9);
        let added = after[8];

        let keys: Vec<String> = (0..2000).map(|n| format!("1:user-{n}")).collect();
        let moved: Vec<&String> = keys
            .iter()
            .filter(|key| winner(key, &before) != winner(key, &after))
            .collect();

        assert!(moved.iter().all(|key| winner(key, &after) == added));
        assert!(!moved.is_empty());
    }

    #[test]
    fn no_pods_means_no_pick() {
        assert!(rendezvous(b"1:alice", std::iter::empty()).is_none());
    }
}
