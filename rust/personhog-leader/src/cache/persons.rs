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

/// Fixed per-entry overhead charged on top of the serialized-properties
/// estimate: the struct's scalar fields, the uuid, the key, and foyer's
/// record bookkeeping.
const PERSON_ENTRY_OVERHEAD_BYTES: usize = 256;

/// The weight an entry contributes to the cache's byte capacity, from
/// the serialized size of its properties at whichever boundary the
/// person entered through. An estimate for eviction accounting — the
/// point is that weight scales with document size, not that it matches
/// the allocator byte for byte.
pub fn approx_person_bytes(properties_serialized_len: usize) -> usize {
    PERSON_ENTRY_OVERHEAD_BYTES + properties_serialized_len
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
    /// Byte weight charged against the cache capacity; see
    /// [`approx_person_bytes`].
    pub approx_bytes: usize,
    // TODO: Add properties_last_updated_at and properties_last_operation
}

/// Decodes a changelog `Person` record into cache form. The only fallible
/// step is parsing the properties JSON; callers add their own context
/// (offset, partition) to the error.
impl TryFrom<Person> for CachedPerson {
    type Error = serde_json::Error;

    fn try_from(person: Person) -> Result<Self, Self::Error> {
        let approx_bytes = approx_person_bytes(person.properties.len());
        Ok(Self {
            id: person.id,
            uuid: person.uuid,
            team_id: person.team_id,
            properties: serde_json::from_slice(&person.properties)?,
            created_at: person.created_at,
            version: person.version,
            is_identified: person.is_identified,
            approx_bytes,
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
    /// `capacity_bytes` bounds the cache by the entries' byte weights
    /// (see [`approx_person_bytes`]), not their count — person documents
    /// vary by orders of magnitude and grow in place across writes, so
    /// an entry-count bound cannot bound memory.
    pub fn new(capacity_bytes: usize) -> Self {
        let cache = CacheBuilder::new(capacity_bytes)
            .with_weighter(|_key: &PersonCacheKey, value: &Arc<CachedPerson>| value.approx_bytes)
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

    /// Resident weight in bytes — the sum of entries' `approx_bytes` as
    /// foyer accounts it against the capacity.
    pub fn usage_bytes(&self) -> usize {
        self.inner.usage()
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
            approx_bytes: approx_person_bytes(64),
        }
    }

    /// An entry-count capacity cannot bound memory: documents grow in
    /// place and vary by orders of magnitude. This pins the byte
    /// denomination — sustained inserts whose combined weight far
    /// exceeds the byte capacity must evict most, but not all, of them.
    /// Foyer splits capacity across eight shards and evicts lazily on
    /// later inserts to the same shard, so entries are sized well under
    /// the per-shard budget (admission must succeed for eviction to be
    /// what's under test) and the bound is asserted with per-shard
    /// slack rather than exactly.
    #[test]
    fn byte_weights_evict_under_capacity_pressure() {
        // 64 KiB capacity → ~8 KiB per shard; ~2 KiB entries fit a
        // shard several times over, and 128 of them (~224 KiB) overrun
        // the total capacity by more than 3x.
        let cache = PersonCache::new(64 * 1024);
        let blob = "x".repeat(1536);
        for person_id in 0..128 {
            let mut person = test_person();
            person.id = person_id;
            person.properties = serde_json::json!({ "blob": blob.clone() });
            person.approx_bytes = approx_person_bytes(1536);
            cache.put(
                PersonCacheKey {
                    team_id: 42,
                    person_id,
                },
                person,
            );
        }
        let resident = (0..128)
            .filter(|id| {
                cache
                    .get(&PersonCacheKey {
                        team_id: 42,
                        person_id: *id,
                    })
                    .is_some()
            })
            .count();
        assert!(
            resident > 0,
            "every entry fits its shard several times over, so admission must retain some"
        );
        assert!(
            resident <= 64,
            "224KiB of inserts against a 64KiB byte capacity retained {resident} \
             of 128 entries — byte weights are not driving eviction"
        );
    }

    #[test]
    fn cache_put_get_roundtrip() {
        let cache = PersonCache::new(1 << 20);
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
        let cache = PersonCache::new(1 << 20);
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
        let cache = PersonCache::new(1 << 20);
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
