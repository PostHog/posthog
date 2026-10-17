use std::collections::{BTreeMap, HashSet};
use std::net::SocketAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, PoisonError, RwLock};

use tokio::sync::mpsc::Sender;
use tonic::transport::{Channel, Endpoint};
use tower::discover::Change;

pub const UNKNOWN_ZONE: &str = "unknown";

const ZONE_CHANNEL_BUFFER: usize = 256;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ZoneAffinity {
    Same,
    Cross,
    Unknown,
}

impl ZoneAffinity {
    pub fn label(self) -> &'static str {
        match self {
            ZoneAffinity::Same => "true",
            ZoneAffinity::Cross => "false",
            ZoneAffinity::Unknown => "unknown",
        }
    }

    pub fn between(local: Option<&str>, remote: &str) -> Self {
        match local {
            Some(local) if remote != UNKNOWN_ZONE => {
                if local == remote {
                    ZoneAffinity::Same
                } else {
                    ZoneAffinity::Cross
                }
            }
            _ => ZoneAffinity::Unknown,
        }
    }
}

/// One balanced channel per backend zone, picked per request in proportion
/// to each zone's endpoint count, so load spreads like one flat balancer
/// while the zone of every call is known.
pub struct ZoneBalancer {
    local_zone: Option<Arc<str>>,
    slots: RwLock<Arc<Vec<ZoneSlot>>>,
    cursor: AtomicUsize,
}

#[derive(Clone)]
struct ZoneSlot {
    zone: Arc<str>,
    endpoints: usize,
    channel: Channel,
}

impl ZoneBalancer {
    pub fn new(local_zone: Option<String>) -> Self {
        Self {
            local_zone: local_zone.map(Arc::from),
            slots: RwLock::new(Arc::new(Vec::new())),
            cursor: AtomicUsize::new(0),
        }
    }

    pub fn local_zone(&self) -> Option<&str> {
        self.local_zone.as_deref()
    }

    pub fn pick(&self) -> Option<(Channel, ZoneAffinity)> {
        let slots = Arc::clone(&self.slots.read().unwrap_or_else(PoisonError::into_inner));
        let total: usize = slots.iter().map(|slot| slot.endpoints).sum();
        if total == 0 {
            return None;
        }
        let mut index = self.cursor.fetch_add(1, Ordering::Relaxed) % total;
        for slot in slots.iter() {
            if index < slot.endpoints {
                let affinity = ZoneAffinity::between(self.local_zone(), &slot.zone);
                return Some((slot.channel.clone(), affinity));
            }
            index -= slot.endpoints;
        }
        None
    }

    pub fn endpoint_counts(&self) -> Vec<(Arc<str>, usize)> {
        self.slots
            .read()
            .unwrap_or_else(PoisonError::into_inner)
            .iter()
            .map(|slot| (Arc::clone(&slot.zone), slot.endpoints))
            .collect()
    }

    fn publish(&self, slots: Vec<ZoneSlot>) {
        *self.slots.write().unwrap_or_else(PoisonError::into_inner) = Arc::new(slots);
    }
}

pub struct ZoneFeeds {
    balancer: Arc<ZoneBalancer>,
    feeds: BTreeMap<Arc<str>, ZoneFeed>,
}

struct ZoneFeed {
    channel: Channel,
    tx: Sender<Change<SocketAddr, Endpoint>>,
    endpoints: HashSet<SocketAddr>,
}

impl ZoneFeeds {
    pub fn new(balancer: Arc<ZoneBalancer>) -> Self {
        Self {
            balancer,
            feeds: BTreeMap::new(),
        }
    }

    pub fn balancer(&self) -> &ZoneBalancer {
        &self.balancer
    }

    pub async fn insert(&mut self, zone: &str, addr: SocketAddr, endpoint: Endpoint) -> bool {
        let feed = self.feeds.entry(Arc::from(zone)).or_insert_with(|| {
            let (channel, tx) = Channel::balance_channel(ZONE_CHANNEL_BUFFER);
            ZoneFeed {
                channel,
                tx,
                endpoints: HashSet::new(),
            }
        });
        if feed.tx.send(Change::Insert(addr, endpoint)).await.is_err() {
            return false;
        }
        feed.endpoints.insert(addr);
        true
    }

    pub async fn remove(&mut self, zone: &str, addr: SocketAddr) -> bool {
        let Some(feed) = self.feeds.get_mut(zone) else {
            return false;
        };
        if !feed.endpoints.remove(&addr) {
            return false;
        }
        feed.tx.send(Change::Remove(addr)).await.is_ok()
    }

    pub fn publish(&self) -> usize {
        let slots: Vec<ZoneSlot> = self
            .feeds
            .iter()
            .map(|(zone, feed)| ZoneSlot {
                zone: Arc::clone(zone),
                endpoints: feed.endpoints.len(),
                channel: feed.channel.clone(),
            })
            .collect();
        let total = slots.iter().map(|slot| slot.endpoints).sum();
        self.balancer.publish(slots);
        total
    }

    pub fn endpoint_counts(&self) -> impl Iterator<Item = (&str, usize)> {
        self.feeds
            .iter()
            .map(|(zone, feed)| (zone.as_ref(), feed.endpoints.len()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn addr(last_octet: u8) -> SocketAddr {
        format!("10.0.0.{last_octet}:50051").parse().unwrap()
    }

    fn endpoint(addr: SocketAddr) -> Endpoint {
        Endpoint::from_shared(format!("http://{addr}")).unwrap()
    }

    async fn feeds_with(
        local_zone: Option<&str>,
        members: &[(&str, u8)],
    ) -> (Arc<ZoneBalancer>, ZoneFeeds) {
        let balancer = Arc::new(ZoneBalancer::new(local_zone.map(str::to_string)));
        let mut feeds = ZoneFeeds::new(Arc::clone(&balancer));
        for (zone, octet) in members {
            assert!(
                feeds
                    .insert(zone, addr(*octet), endpoint(addr(*octet)))
                    .await
            );
        }
        (balancer, feeds)
    }

    fn tally(balancer: &ZoneBalancer, picks: usize) -> (usize, usize, usize) {
        let mut tally = (0, 0, 0);
        for _ in 0..picks {
            match balancer.pick().expect("endpoints published").1 {
                ZoneAffinity::Same => tally.0 += 1,
                ZoneAffinity::Cross => tally.1 += 1,
                ZoneAffinity::Unknown => tally.2 += 1,
            }
        }
        tally
    }

    #[test]
    fn between_labels_same_cross_and_unknown() {
        assert_eq!(ZoneAffinity::between(Some("a"), "a"), ZoneAffinity::Same);
        assert_eq!(ZoneAffinity::between(Some("a"), "b"), ZoneAffinity::Cross);
        assert_eq!(
            ZoneAffinity::between(Some("a"), UNKNOWN_ZONE),
            ZoneAffinity::Unknown
        );
        assert_eq!(ZoneAffinity::between(None, "a"), ZoneAffinity::Unknown);
    }

    #[tokio::test]
    async fn pick_spreads_by_endpoint_count_and_labels_zone() {
        let (balancer, feeds) = feeds_with(Some("a"), &[("a", 1), ("a", 2), ("b", 3)]).await;
        assert!(balancer.pick().is_none(), "nothing picked before publish");

        assert_eq!(feeds.publish(), 3);
        assert_eq!(tally(&balancer, 300), (200, 100, 0));
    }

    #[tokio::test]
    async fn pick_is_unknown_without_a_local_zone() {
        let (balancer, feeds) = feeds_with(None, &[("a", 1), ("b", 2)]).await;
        feeds.publish();
        assert_eq!(tally(&balancer, 10), (0, 0, 10));
    }

    #[tokio::test]
    async fn remove_empties_a_zone_and_pick_skips_it() {
        let (balancer, mut feeds) = feeds_with(Some("a"), &[("a", 1), ("b", 2)]).await;
        assert!(feeds.remove("b", addr(2)).await);
        assert!(
            !feeds.remove("b", addr(2)).await,
            "second remove is a no-op"
        );
        assert!(!feeds.remove("c", addr(9)).await, "unknown zone is a no-op");

        assert_eq!(feeds.publish(), 1);
        assert_eq!(
            balancer.endpoint_counts(),
            vec![(Arc::from("a"), 1), (Arc::from("b"), 0)]
        );
        assert_eq!(tally(&balancer, 5), (5, 0, 0));

        assert!(feeds.remove("a", addr(1)).await);
        assert_eq!(feeds.publish(), 0);
        assert!(balancer.pick().is_none());
    }
}
