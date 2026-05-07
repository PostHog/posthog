use std::sync::Arc;

use dashmap::DashMap;
use metrics::counter;

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
    per_partition_capacity: usize,
}

impl PartitionedCache {
    pub fn new(per_partition_capacity: usize) -> Self {
        Self {
            partitions: DashMap::new(),
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
        let cache = PersonCache::new(self.per_partition_capacity);
        for (key, person) in records {
            cache.put(key, person);
        }
        self.partitions.insert(partition, cache);
    }

    /// Drop the cache for the given partition, evicting all entries.
    pub fn drop_partition(&self, partition: u32) {
        self.partitions.remove(&partition);
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
            properties: json!({"email": "test@example.com"}),
            created_at: 1700000000,
            version: 1,
            is_identified: false,
        }
    }

    #[test]
    fn get_returns_partition_not_owned_for_unknown_partition() {
        let cache = PartitionedCache::new(100);
        assert!(matches!(
            cache.get(0, &test_key()),
            CacheLookup::PartitionNotOwned
        ));
    }

    #[test]
    fn create_and_use_partition() {
        let cache = PartitionedCache::new(100);
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
        let cache = PartitionedCache::new(100);
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
        let cache = PartitionedCache::new(100);
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
        let cache = PartitionedCache::new(100);
        cache.put(99, test_key(), test_person());
        assert!(matches!(
            cache.get(99, &test_key()),
            CacheLookup::PartitionNotOwned
        ));
    }
}
