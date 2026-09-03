use std::sync::Arc;

use dashmap::DashMap;
use metrics::counter;

#[cfg(test)]
use super::persons::approx_person_bytes;
use super::persons::{CachedPerson, PersonCache, PersonCacheKey};

/// Result of a cache lookup that distinguishes partition ownership from person existence.
pub enum CacheLookup {
    Found(Arc<CachedPerson>),
    PersonNotFound,
    PartitionNotOwned,
}

/// Per-partition cache manager. Each partition gets its own independent
/// Foyer cache so that releasing a partition drops all its entries cleanly.
pub struct PartitionedCache {
    partitions: DashMap<u32, PersonCache>,
    /// Partitions mid-warm: built here record by record — evicting under
    /// the same per-partition byte budget as a serving cache — and moved
    /// to `partitions` in a single insert when the warm's range
    /// completes. Entirely invisible to readers: `get`/`has_partition`
    /// consult `partitions` only, so a partition under construction
    /// answers `PartitionNotOwned` on every path.
    warming: DashMap<u32, PersonCache>,
    per_partition_capacity: usize,
}

impl PartitionedCache {
    pub fn new(per_partition_capacity: usize) -> Self {
        Self {
            partitions: DashMap::new(),
            warming: DashMap::new(),
            per_partition_capacity,
        }
    }

    /// Create a new cache for the given partition. Called during warm-up.
    pub fn create_partition(&self, partition: u32) {
        self.partitions
            .insert(partition, PersonCache::new(self.per_partition_capacity));
    }

    /// Atomically install a fully-populated partition cache. The records
    /// are inserted into a fresh `PersonCache` *before* the partition is
    /// added to the shared `DashMap`, so any thread that observes
    /// `has_partition(partition) == true` will also see every record —
    /// no observer can land in the window where the partition exists
    /// but its keys haven't been put yet. Used by warming so reads that
    /// arrive immediately after a handoff Complete don't fall through
    /// to PG and return stale values for records that the writer hasn't
    /// yet persisted.
    pub fn install_warmed_partition(
        &self,
        partition: u32,
        records: impl IntoIterator<Item = (PersonCacheKey, CachedPerson)>,
    ) {
        self.begin_warm_partition(partition);
        for (key, person) in records {
            self.warm_put(partition, key, person);
        }
        self.publish_warmed_partition(partition);
    }

    /// Start building a partition's cache without publishing it. The
    /// warm inserts record by record with `warm_put` — bounded by the
    /// per-partition budget, evicting as it goes — and publishes the
    /// finished cache with `publish_warmed_partition`. Re-entrant: a
    /// retried warm begins fresh, replacing any half-built predecessor.
    pub fn begin_warm_partition(&self, partition: u32) {
        self.warming
            .insert(partition, PersonCache::new(self.per_partition_capacity));
    }

    /// Insert one record into a partition cache under construction.
    pub fn warm_put(&self, partition: u32, key: PersonCacheKey, person: CachedPerson) {
        self.warming
            .get(&partition)
            .expect("warm_put before begin_warm_partition")
            .put(key, person);
    }

    /// Publish a fully-built partition cache: one `DashMap` insert flips
    /// the partition from invisible to fully observable, preserving the
    /// no-partial-window property `install_warmed_partition` documents.
    pub fn publish_warmed_partition(&self, partition: u32) {
        let (_, cache) = self
            .warming
            .remove(&partition)
            .expect("publish_warmed_partition before begin_warm_partition");
        self.partitions.insert(partition, cache);
    }

    /// Discard a partition cache under construction (a warm that failed
    /// mid-range). Nothing was ever observable.
    pub fn abort_warm_partition(&self, partition: u32) {
        self.warming.remove(&partition);
    }

    /// Resident weight of a build in flight — what the warm retained of
    /// its range under the budget.
    pub fn warm_usage_bytes(&self, partition: u32) -> usize {
        self.warming
            .get(&partition)
            .map(|c| c.usage_bytes())
            .unwrap_or(0)
    }

    /// Drop the cache for the given partition, evicting all entries —
    /// including a build in flight, so a release racing a warm leaves
    /// nothing behind.
    pub fn drop_partition(&self, partition: u32) {
        self.partitions.remove(&partition);
        self.warming.remove(&partition);
    }

    /// Total resident weight in bytes across all owned partitions,
    /// builds in flight included — the gauge tells the truth during
    /// warms rather than hiding the construction cost.
    pub fn usage_bytes(&self) -> usize {
        self.partitions
            .iter()
            .map(|c| c.usage_bytes())
            .sum::<usize>()
            + self.warming.iter().map(|c| c.usage_bytes()).sum::<usize>()
    }

    /// Check if a partition cache exists (i.e., the partition is owned).
    pub fn has_partition(&self, partition: u32) -> bool {
        self.partitions.contains_key(&partition)
    }

    /// Look up a person in the partition's cache with a single DashMap lock acquisition.
    pub fn get(&self, partition: u32, key: &PersonCacheKey) -> CacheLookup {
        match self.partitions.get(&partition) {
            Some(cache) => match cache.get(key) {
                Some(person) => CacheLookup::Found(person),
                None => CacheLookup::PersonNotFound,
            },
            None => {
                counter!("personhog_leader_unowned_partition_total").increment(1);
                CacheLookup::PartitionNotOwned
            }
        }
    }

    /// Insert or update a person in the partition's cache.
    pub fn put(&self, partition: u32, key: PersonCacheKey, person: CachedPerson) {
        if let Some(cache) = self.partitions.get(&partition) {
            cache.put(key, person);
        }
    }

    /// Remove a single person from the partition's cache. Only tests call
    /// this, to force a deterministic eviction — production evictions come
    /// from Foyer's capacity policy. Safe regardless: the miss path
    /// recovers the person from the changelog or PG on next access.
    pub fn remove(&self, partition: u32, key: &PersonCacheKey) {
        if let Some(cache) = self.partitions.get(&partition) {
            cache.remove(key);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn test_key() -> PersonCacheKey {
        PersonCacheKey {
            team_id: 42,
            person_id: 1,
        }
    }

    fn test_person() -> CachedPerson {
        CachedPerson {
            id: 1,
            uuid: "abc-123".to_string(),
            team_id: 42,
            properties: serde_json::to_vec(&json!({"email": "test@example.com"})).unwrap(),
            created_at: 1700000000,
            version: 1,
            is_identified: false,
            is_deleted: false,
            last_seen_at: None,
            approx_bytes: approx_person_bytes(64),
        }
    }

    #[test]
    fn get_returns_partition_not_owned_for_unknown_partition() {
        let cache = PartitionedCache::new(1 << 20);
        assert!(matches!(
            cache.get(0, &test_key()),
            CacheLookup::PartitionNotOwned
        ));
    }

    #[test]
    fn create_and_use_partition() {
        let cache = PartitionedCache::new(1 << 20);
        cache.create_partition(0);
        assert!(cache.has_partition(0));

        cache.put(0, test_key(), test_person());
        let CacheLookup::Found(person) = cache.get(0, &test_key()) else {
            panic!("expected Found");
        };
        assert_eq!(person.id, 1);
    }

    #[test]
    fn drop_partition_evicts_all_entries() {
        let cache = PartitionedCache::new(1 << 20);
        cache.create_partition(0);
        cache.put(0, test_key(), test_person());

        cache.drop_partition(0);
        assert!(!cache.has_partition(0));
        assert!(matches!(
            cache.get(0, &test_key()),
            CacheLookup::PartitionNotOwned
        ));
    }

    #[test]
    fn partitions_are_isolated() {
        let cache = PartitionedCache::new(1 << 20);
        cache.create_partition(0);
        cache.create_partition(1);

        cache.put(0, test_key(), test_person());

        assert!(matches!(cache.get(0, &test_key()), CacheLookup::Found(_)));
        assert!(matches!(
            cache.get(1, &test_key()),
            CacheLookup::PersonNotFound
        ));
    }

    #[test]
    fn put_to_unknown_partition_is_noop() {
        let cache = PartitionedCache::new(1 << 20);
        cache.put(99, test_key(), test_person());
        assert!(matches!(
            cache.get(99, &test_key()),
            CacheLookup::PartitionNotOwned
        ));
    }
}
