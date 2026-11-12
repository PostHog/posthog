//! Death-document residency maintenance: the prune tick and the settle
//! that drops a death document once the writer has applied its record.

use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::time::{Duration, Instant};

use dashmap::DashMap;
use metrics::{counter, histogram};
use personhog_coordination::types::{ChangelogConfig, ClusterEndpoint};
use tokio::sync::Mutex;

use crate::cache::{
    CachedVersion, DirtyIndex, DirtyMark, PartitionedCache, PersonCacheKey, Stream,
};
use crate::warming::{fetch_writer_committed_offsets, WarmClientPools};

type MarkedTopic = (Option<Arc<ClusterEndpoint>>, Vec<u32>);

/// A topic listed neither live nor draining was retired, which proves the config's
/// writer group applied it. The proof covers this leader only when that group is its own.
pub fn retired_topic(live: &ChangelogConfig, writer_group: &str, topic: &str) -> bool {
    live.writer_group == writer_group
        && live.topic != topic
        && live.draining.iter().all(|g| g.topic != topic)
}

/// A SlateDB reader trails the writer by up to a poll, so marks outlive their commit by `delay`.
pub struct CommitDelay {
    delay: Duration,
    pending: HashMap<Stream, VecDeque<(Instant, i64)>>,
    settled: HashMap<Stream, i64>,
}

impl CommitDelay {
    pub fn new(delay: Duration) -> Self {
        Self {
            delay,
            pending: HashMap::new(),
            settled: HashMap::new(),
        }
    }

    pub fn effective(&mut self, stream: &Stream, committed: i64, now: Instant) -> Option<i64> {
        if self.delay.is_zero() {
            return Some(committed);
        }
        let pending = self.pending.entry(stream.clone()).or_default();
        if pending
            .back()
            .is_none_or(|&(_, offset)| offset != committed)
        {
            pending.push_back((now, committed));
        }
        while let Some(&(observed_at, offset)) = pending.front() {
            if now.duration_since(observed_at) < self.delay {
                break;
            }
            self.settled.insert(stream.clone(), offset);
            pending.pop_front();
        }
        self.settled.get(stream).copied()
    }
}

/// One prune pass over the published partitions: fetch committed offsets per
/// topic, prune the applied marks and settle their death documents. A retired
/// stream settles without a fetch; a failed fetch leaves its topic's marks waiting.
pub async fn prune_and_settle_tick(
    dirty_index: &DirtyIndex,
    cache: &PartitionedCache,
    locks: &DashMap<PersonCacheKey, Arc<Mutex<()>>>,
    pools: &WarmClientPools,
    offsets_timeout: Duration,
    commit_delay: &mut CommitDelay,
    retired: impl Fn(&str) -> bool,
) -> Vec<StreamLag> {
    let targets = dirty_index.streams_with_marks();
    if targets.is_empty() {
        return Vec::new();
    }
    // Judged after the listing: a stream seen with marks was captured under a config this read covers.
    let mut retired_topics: HashMap<Arc<str>, bool> = HashMap::new();
    for (_, stream) in &targets {
        retired_topics
            .entry(Arc::clone(&stream.topic))
            .or_insert_with(|| retired(&stream.topic));
    }
    // One OffsetFetch per topic a live mark lives on.
    let mut by_topic: HashMap<Arc<str>, MarkedTopic> = HashMap::new();
    for (_, stream) in &targets {
        if retired_topics[&stream.topic] {
            continue;
        }
        let (_, partitions) = by_topic
            .entry(Arc::clone(&stream.topic))
            .or_insert_with(|| (stream.cluster.clone(), Vec::new()));
        if !partitions.contains(&stream.partition) {
            partitions.push(stream.partition);
        }
    }
    let mut committed: HashMap<Arc<str>, HashMap<u32, i64>> = HashMap::new();
    for (topic, (cluster, partitions)) in by_topic {
        let offsets_pool = &pools.on(cluster.as_deref()).offsets;
        match fetch_writer_committed_offsets(offsets_pool, &topic, &partitions, offsets_timeout)
            .await
        {
            Ok(offsets) => {
                committed.insert(topic, offsets);
            }
            Err(e) => {
                counter!("personhog_leader_prune_offset_fetch_failures_total").increment(1);
                tracing::warn!(error = %e, topic = %topic, "dirty-index prune offset fetch failed; its marks wait");
            }
        }
    }

    // Prune chunk by chunk, settling each chunk's death pairs before the
    // next, so a catch-up never materializes more than one chunk.
    let started = Instant::now();
    let mut removed_total = 0u64;
    let mut retired_total = 0u64;
    let mut lags = Vec::with_capacity(targets.len());
    for (partition, stream) in targets {
        let on_retired = retired_topics[&stream.topic];
        let offset = if on_retired {
            Some(i64::MAX)
        } else {
            committed
                .get(&stream.topic)
                .and_then(|offsets| offsets.get(&stream.partition))
                .copied()
        };
        let prune_through =
            offset.and_then(|offset| commit_delay.effective(&stream, offset, Instant::now()));
        if let Some(prune_through) = prune_through {
            if cache.is_published(partition) {
                loop {
                    let (pruned, exhausted) =
                        dirty_index.prune_chunk(partition, &stream, prune_through);
                    removed_total += pruned.removed as u64;
                    if on_retired {
                        retired_total += pruned.removed as u64;
                    }
                    if !pruned.death_marks.is_empty() {
                        drop_settled_death_documents(cache, locks, &pruned.death_marks).await;
                    }
                    if exhausted {
                        break;
                    }
                }
            }
        }
        if !on_retired {
            lags.push(StreamLag {
                partition,
                stream,
                committed: offset,
            });
        }
    }
    if removed_total > 0 {
        counter!("personhog_leader_dirty_index_pruned_total").increment(removed_total);
    }
    if retired_total > 0 {
        counter!("personhog_leader_dirty_index_retired_stream_marks_total")
            .increment(retired_total);
    }
    // A long tick means the settle parked on per-key locks, not an idle
    // pass.
    histogram!("personhog_leader_prune_tick_duration_ms")
        .record(started.elapsed().as_secs_f64() * 1000.0);
    lags
}

/// The writer's committed offset on a stream, if it has one.
pub struct StreamLag {
    pub partition: u32,
    pub stream: Stream,
    pub committed: Option<i64>,
}

/// Drop death documents whose marks the writer settled: past the mark,
/// PG answers for the person — tombstoned or revived. A revival cannot
/// precede the applied tombstone (stub creation revives only
/// `is_deleted = true` rows), so the miss after the drop serves truth.
pub async fn drop_settled_death_documents(
    cache: &PartitionedCache,
    locks: &DashMap<PersonCacheKey, Arc<Mutex<()>>>,
    pruned: &[(PersonCacheKey, DirtyMark)],
) {
    for (key, mark) in pruned {
        // Skip lock-free only on a live or newer entry. An absent entry
        // must take the lock: a recovery holding it may be about to
        // install this very death document.
        let settled = |entry: CachedVersion| entry.is_deleted && entry.version == mark.version;
        if cache
            .peek(mark.partition, key)
            .is_some_and(|entry| !settled(entry))
        {
            continue;
        }
        {
            let mutex = locks.entry(key.clone()).or_default().value().clone();
            let _guard = mutex.lock().await;
            // Re-proved under the lock so a concurrent commit's newer entry
            // is never dropped.
            if cache.peek(mark.partition, key).is_some_and(settled) {
                cache.remove(mark.partition, key);
                counter!("personhog_leader_death_documents_settled_total").increment(1);
            }
        }
        // Drop the just-minted lock so a delete storm cannot pile idle
        // entries between sweeps; strong_count == 1 means the map alone holds it.
        locks.remove_if(key, |_, m| Arc::strong_count(m) == 1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cache::CachedPerson;
    use personhog_coordination::types::Generation;

    #[test]
    fn a_commit_prunes_only_once_it_is_older_than_the_delay() {
        let stream = Stream {
            topic: Arc::from("changelog"),
            cluster: None,
            partition: 3,
        };
        let start = Instant::now();
        let at = |secs: u64| start + Duration::from_secs(secs);
        let mut delay = CommitDelay::new(Duration::from_secs(2));

        assert_eq!(delay.effective(&stream, 10, at(0)), None);
        assert_eq!(delay.effective(&stream, 20, at(1)), None);
        assert_eq!(delay.effective(&stream, 20, at(2)), Some(10));
        assert_eq!(delay.effective(&stream, 30, at(3)), Some(20));
        assert_eq!(delay.effective(&stream, 30, at(4)), Some(20));
        assert_eq!(delay.effective(&stream, 30, at(5)), Some(30));
    }

    #[test]
    fn a_topic_is_retired_only_when_the_config_vouches_for_the_writer() {
        let config = |topic: &str, writer_group: &str, draining: &[&str]| ChangelogConfig {
            topic: topic.to_string(),
            partitions: 8,
            epoch: 2,
            writer_group: writer_group.to_string(),
            retire_groups: vec![],
            cluster: None,
            draining: draining
                .iter()
                .map(|t| Generation {
                    cluster: None,
                    topic: t.to_string(),
                    partitions: 4,
                    epoch: 1,
                })
                .collect(),
        };
        let cases = [
            (
                "the live topic",
                config("live", "writer", &[]),
                "live",
                false,
            ),
            (
                "a draining topic",
                config("live", "writer", &["old"]),
                "old",
                false,
            ),
            (
                "a topic listed nowhere",
                config("live", "writer", &["old"]),
                "gone",
                true,
            ),
            (
                "another writer group",
                config("live", "other", &[]),
                "gone",
                false,
            ),
            ("no writer group", config("", "", &[]), "gone", false),
        ];
        for (name, live, topic, expected) in cases {
            assert_eq!(retired_topic(&live, "writer", topic), expected, "{name}");
        }
    }

    fn death_person(version: i64) -> CachedPerson {
        CachedPerson {
            id: 1,
            uuid: "dead-1".to_string(),
            team_id: 7,
            properties: Vec::new(),
            created_at: 1_700_000_000,
            version,
            is_identified: true,
            is_deleted: true,
            last_seen_at: None,
        }
    }

    #[tokio::test]
    async fn settling_a_death_document_leaves_no_lock_entry() {
        let cache = PartitionedCache::new(16);
        cache.create_partition(0);
        let key = PersonCacheKey {
            team_id: 7,
            person_id: 1,
        };
        cache.put(0, key.clone(), death_person(5));

        let locks: DashMap<PersonCacheKey, Arc<Mutex<()>>> = DashMap::new();
        let pruned = vec![(
            key.clone(),
            DirtyMark {
                version: 5,
                offset: 0,
                partition: 0,
                stream: Stream {
                    topic: Arc::from("personhog_updates"),
                    cluster: None,
                    partition: 0,
                },
                is_deleted: true,
            },
        )];

        drop_settled_death_documents(&cache, &locks, &pruned).await;

        assert!(
            cache.peek(0, &key).is_none(),
            "settled death document should be dropped"
        );
        assert!(
            locks.is_empty(),
            "settle must not leave an idle lock entry in the map"
        );
    }
}
