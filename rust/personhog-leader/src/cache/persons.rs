use std::hash::Hash;
use std::sync::Arc;

use foyer::{Cache, CacheBuilder};
use metrics::counter;

/// Key for person cache lookups: (team_id, person_id).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PersonCacheKey {
    pub team_id: i64,
    pub person_id: i64,
}

/// Cached person state with properties as a JSON map.
#[derive(Debug, Clone)]
pub struct CachedPerson {
    pub id: i64,
    pub uuid: String,
    pub team_id: i64,
    pub properties: serde_json::Value,
    pub created_at: i64,
    pub version: i64,
    pub is_identified: bool,
    // TODO: Add properties_last_updated_at and properties_last_operation
}

/// In-memory person cache backed by Foyer.
///
/// For the PoC we use Foyer's in-memory cache. The hybrid (disk+memory)
/// layer can be added later by switching to `HybridCache`.
///
/// TODO: Foyer is an eviction-based cache, but the leader is the source of truth
/// for its partitions. A cache miss currently returns NotFound, losing the person.
/// Add a Postgres fallback on cache miss so eviction degrades to a slower read
/// rather than data loss.
pub struct PersonCache {
    inner: Cache<PersonCacheKey, Arc<CachedPerson>>,
}

impl PersonCache {
    pub fn new(capacity: usize) -> Self {
        let cache = CacheBuilder::new(capacity).build();
        Self { inner: cache }
    }

    pub fn get(&self, key: &PersonCacheKey) -> Option<Arc<CachedPerson>> {
        match self.inner.get(key) {
            Some(entry) => {
                counter!("personhog_leader_cache_hits_total").increment(1);
                Some(entry.value().clone())
            }
            None => {
                counter!("personhog_leader_cache_misses_total").increment(1);
                None
            }
        }
    }

    pub fn put(&self, key: PersonCacheKey, person: CachedPerson) {
        self.inner.insert(key, Arc::new(person));
    }

    pub fn remove(&self, key: &PersonCacheKey) {
        self.inner.remove(key);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_person() -> CachedPerson {
        CachedPerson {
            id: 1,
            uuid: "abc-123".to_string(),
            team_id: 42,
            properties: serde_json::json!({"email": "test@example.com"}),
            created_at: 1700000000,
            version: 1,
            is_identified: false,
        }
    }

    #[test]
    fn cache_put_get_roundtrip() {
        let cache = PersonCache::new(100);
        let key = PersonCacheKey {
            team_id: 42,
            person_id: 1,
        };

        assert!(cache.get(&key).is_none());

        cache.put(key.clone(), test_person());

        let cached = cache.get(&key).unwrap();
        assert_eq!(cached.id, 1);
        assert_eq!(cached.uuid, "abc-123");
        assert_eq!(cached.team_id, 42);
        assert_eq!(cached.properties["email"], "test@example.com");
    }

    #[test]
    fn cache_remove() {
        let cache = PersonCache::new(100);
        let key = PersonCacheKey {
            team_id: 42,
            person_id: 1,
        };

        cache.put(key.clone(), test_person());
        assert!(cache.get(&key).is_some());

        cache.remove(&key);
        assert!(cache.get(&key).is_none());
    }

    #[test]
    fn cache_overwrite() {
        let cache = PersonCache::new(100);
        let key = PersonCacheKey {
            team_id: 42,
            person_id: 1,
        };

        cache.put(key.clone(), test_person());

        let mut updated = test_person();
        updated.version = 2;
        updated.properties = serde_json::json!({"email": "new@example.com"});
        cache.put(key.clone(), updated);

        let cached = cache.get(&key).unwrap();
        assert_eq!(cached.version, 2);
        assert_eq!(cached.properties["email"], "new@example.com");
    }
}
