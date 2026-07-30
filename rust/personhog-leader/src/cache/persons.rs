use std::hash::Hash;
use std::sync::Arc;

use foyer::{Cache, CacheBuilder, Event, EventListener};
use metrics::counter;
use personhog_proto::personhog::types::v1::Person;

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

/// Decodes a changelog `Person` record into cache form. The only fallible
/// step is parsing the properties JSON; callers add their own context
/// (offset, partition) to the error.
impl TryFrom<Person> for CachedPerson {
    type Error = serde_json::Error;

    fn try_from(person: Person) -> Result<Self, Self::Error> {
        Ok(Self {
            id: person.id,
            uuid: person.uuid,
            team_id: person.team_id,
            properties: serde_json::from_slice(&person.properties)?,
            created_at: person.created_at,
            version: person.version,
            is_identified: person.is_identified,
        })
    }
}

/// Counts entries leaving the cache, by reason. Evictions are the
/// operationally interesting ones: evicting a recently written person is
/// exactly what the dirty index + changelog recovery exist to make safe,
/// and a sustained eviction rate is the early signal that the configured
/// capacity is undersized for the working set.
struct CacheEventMetrics;

impl EventListener for CacheEventMetrics {
    type Key = PersonCacheKey;
    type Value = Arc<CachedPerson>;

    fn on_leave(&self, reason: Event, _key: &Self::Key, _value: &Self::Value) {
        let reason = match reason {
            Event::Evict => "evict",
            Event::Remove => "remove",
            Event::Clear => "clear",
            // Every successful update overwrites its cache entry, so
            // Replace fires once per write — pure hot-path noise that
            // would drown the signal this metric exists for.
            Event::Replace => return,
        };
        counter!("personhog_leader_cache_entries_left_total", "reason" => reason).increment(1);
    }
}

/// In-memory person cache backed by Foyer.
///
/// Foyer evicts freely under capacity pressure; that is safe because the
/// service's miss path never trusts a stale source. Persons in the dirty
/// index (acked but not yet applied to PG by the writer) recover from
/// their changelog record; everyone else's PG fallback row is current.
/// A hybrid (disk+memory) tier remains a possible capacity optimization
/// by switching to `HybridCache`.
pub struct PersonCache {
    inner: Cache<PersonCacheKey, Arc<CachedPerson>>,
}

impl PersonCache {
    pub fn new(capacity: usize) -> Self {
        let cache = CacheBuilder::new(capacity)
            .with_event_listener(Arc::new(CacheEventMetrics))
            .build();
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
