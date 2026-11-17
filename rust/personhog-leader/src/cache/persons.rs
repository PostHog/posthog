use std::collections::HashSet;
use std::hash::Hash;
use std::sync::{Arc, Mutex, PoisonError};

use foyer::{Cache, CacheBuilder, Event, EventListener};
use metrics::counter;
use personhog_proto::personhog::types::v1::Person;

use super::codec::PropertiesCodec;
use super::stored::StoredPerson;

/// Key for person cache lookups: (team_id, person_id).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PersonCacheKey {
    pub team_id: i64,
    pub person_id: i64,
}

/// Cached person state, with properties held in serialized JSON form.
///
/// Serialized rather than parsed for memory accounting: the cache weighs
/// entries by byte length, and holding the bytes makes the charged
/// weight the real allocation. Readers that need the map parse on
/// access via [`CachedPerson::parse_properties`]; readers that need the
/// wire form (proto responses, changelog records) take the bytes as
/// they are.
#[derive(Debug, Clone)]
pub struct CachedPerson {
    pub id: i64,
    pub uuid: String,
    pub team_id: i64,
    /// Properties as serialized JSON, validated at construction.
    pub properties: Vec<u8>,
    pub created_at: i64,
    pub version: i64,
    pub is_identified: bool,
    /// True when this entry is a recovered death document: the person was
    /// destroyed and this version closes its stream. Cached while its
    /// dirty mark stands (the writer may not have tombstoned the PG row
    /// yet); the prune-time settle drops it, and PG answers after.
    pub is_deleted: bool,
    /// Epoch milliseconds of the person's last observed activity, when
    /// known (matching `created_at`'s unit). Max-merged on update — the
    /// value only ever advances — and deliberately not a change by itself.
    pub last_seen_at: Option<i64>,
    // TODO: Add properties_last_updated_at and properties_last_operation
}

impl CachedPerson {
    /// Parse the stored properties into a JSON value. Construction
    /// validates the bytes, so a failure here means the cache holds a
    /// document no constructor produced.
    pub fn parse_properties(&self) -> serde_json::Result<serde_json::Value> {
        if self.properties.is_empty() {
            return Ok(serde_json::Value::Object(serde_json::Map::new()));
        }
        serde_json::from_slice(&self.properties)
    }

    /// Identity creates and revives a person with no properties, and the
    /// first write through the leader sets them.
    pub fn has_no_properties(&self) -> bool {
        self.properties.is_empty() || self.properties == b"{}"
    }
}

/// Decodes a changelog `Person` record into cache form. The only fallible
/// step is validating the properties JSON — validated without building
/// the tree, and stored as the record's own bytes.
impl TryFrom<Person> for CachedPerson {
    type Error = serde_json::Error;

    fn try_from(person: Person) -> Result<Self, Self::Error> {
        if !person.properties.is_empty() {
            serde_json::from_slice::<serde::de::IgnoredAny>(&person.properties)?;
        }
        Ok(Self {
            id: person.id,
            uuid: person.uuid,
            team_id: person.team_id,
            properties: person.properties,
            created_at: person.created_at,
            version: person.version,
            is_identified: person.is_identified,
            is_deleted: person.is_deleted,
            last_seen_at: person.last_seen_at,
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub struct CachedVersion {
    pub version: i64,
    pub is_deleted: bool,
}

/// Counts entries leaving the cache, by reason. Evictions are the
/// operationally interesting ones: evicting a recently written person is
/// exactly what the dirty index + changelog recovery exist to make safe,
/// and a sustained eviction rate is the early signal that the configured
/// capacity is undersized for the working set.
struct CacheEventMetrics;

impl EventListener for CacheEventMetrics {
    type Key = PersonCacheKey;
    type Value = StoredPerson;

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
    inner: Cache<PersonCacheKey, StoredPerson>,
    codec: Arc<PropertiesCodec>,
    capacity_bytes: usize,
    /// Present while a fill is pending.
    put_keys: Mutex<Option<PutTracking>>,
}

/// The pending fill's token and every key put since it was armed.
struct PutTracking {
    token: u64,
    keys: HashSet<PersonCacheKey>,
    /// Tracking stops past this many keys, which ends the fill.
    max_keys: usize,
}

/// What became of a record a fill offered.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FillOutcome {
    Inserted,
    /// The key was put since tracking began, so the cache holds newer state.
    AlreadyPut,
    /// A death document: nothing is inserted, and older records for the key are refused.
    Dead,
    /// This cache has no pending fill, or one that holds a different token.
    NotTracking,
}

impl PersonCache {
    /// `capacity_bytes` bounds the cache by the entries' byte weights
    /// (see `StoredPerson::weight`), not their count. Person documents
    /// vary by orders of magnitude and grow in place across writes, so
    /// an entry-count bound cannot bound memory.
    pub(super) fn new(capacity_bytes: usize, codec: Arc<PropertiesCodec>) -> Self {
        let cache = CacheBuilder::new(capacity_bytes)
            .with_weighter(|_key: &PersonCacheKey, value: &StoredPerson| value.weight())
            .with_event_listener(Arc::new(CacheEventMetrics))
            .build();
        Self {
            inner: cache,
            codec,
            capacity_bytes,
            put_keys: Mutex::new(None),
        }
    }

    /// Start recording put keys, for the fill that will hold `token`.
    pub(super) fn track_puts(&self, token: u64, max_keys: usize) {
        *self.put_keys.lock().unwrap_or_else(PoisonError::into_inner) = Some(PutTracking {
            token,
            keys: HashSet::new(),
            max_keys,
        });
    }

    pub(super) fn fill_token(&self) -> Option<u64> {
        self.put_keys
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .as_ref()
            .map(|tracking| tracking.token)
    }

    pub(super) fn stop_tracking_puts(&self, token: u64) {
        let mut put_keys = self.put_keys.lock().unwrap_or_else(PoisonError::into_inner);
        if put_keys
            .as_ref()
            .is_some_and(|tracking| tracking.token == token)
        {
            *put_keys = None;
        }
    }

    /// Insert unless the key was put since tracking began; a put records its key first.
    pub(super) fn fill(
        &self,
        token: u64,
        key: PersonCacheKey,
        person: CachedPerson,
    ) -> FillOutcome {
        let is_deleted = person.is_deleted;
        let stored = StoredPerson::new(person, &self.codec);
        let mut put_keys = self.put_keys.lock().unwrap_or_else(PoisonError::into_inner);
        let Some(tracking) = put_keys.as_mut().filter(|tracking| tracking.token == token) else {
            return FillOutcome::NotTracking;
        };
        if !tracking.keys.insert(key.clone()) {
            return FillOutcome::AlreadyPut;
        }
        if tracking.keys.len() > tracking.max_keys {
            *put_keys = None;
            return FillOutcome::NotTracking;
        }
        if is_deleted {
            return FillOutcome::Dead;
        }
        self.inner.insert(key, stored);
        FillOutcome::Inserted
    }

    /// Whether the resident weight is below `fraction` of the capacity.
    pub(super) fn has_room(&self, fraction: f64) -> bool {
        (self.inner.usage() as f64) < self.capacity_bytes as f64 * fraction
    }

    pub fn get(&self, key: &PersonCacheKey) -> Option<CachedPerson> {
        self.lookup(key)
    }

    /// A read for bookkeeping passes such as the death-document settle.
    /// It does not copy or decompress the properties. It still promotes
    /// the entry's recency, which is harmless for those passes.
    pub fn peek(&self, key: &PersonCacheKey) -> Option<CachedVersion> {
        self.inner
            .get(key)
            .map(|entry| entry.value().cached_version())
    }

    /// An entry that fails to decode is dropped and reads as absent.
    fn lookup(&self, key: &PersonCacheKey) -> Option<CachedPerson> {
        let entry = self.inner.get(key)?;
        match entry.value().to_cached(&self.codec) {
            Ok(person) => Some(person),
            Err(reason) => {
                // Safe to drop: the miss path recovers from the changelog or Postgres.
                counter!("personhog_leader_cache_decode_failures_total").increment(1);
                tracing::error!(
                    team_id = key.team_id,
                    person_id = key.person_id,
                    reason,
                    "dropping cache entry whose properties failed to decode"
                );
                self.inner.remove(key);
                None
            }
        }
    }

    pub fn put(&self, key: PersonCacheKey, person: CachedPerson) {
        let stored = StoredPerson::new(person, &self.codec);
        let properties = stored.properties();
        counter!("personhog_leader_cache_properties_put_bytes_total", "form" => "raw")
            .increment(properties.raw_len() as u64);
        counter!("personhog_leader_cache_properties_put_bytes_total", "form" => "stored")
            .increment(properties.stored_len() as u64);
        let mut put_keys = self.put_keys.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some(tracking) = put_keys.as_mut() {
            tracking.keys.insert(key.clone());
            if tracking.keys.len() > tracking.max_keys {
                *put_keys = None;
            }
        }
        drop(put_keys);
        self.inner.insert(key, stored);
    }

    pub fn remove(&self, key: &PersonCacheKey) {
        self.inner.remove(key);
    }

    /// Resident weight in bytes: the sum of entries' weights as foyer
    /// accounts it against the capacity.
    pub fn usage_bytes(&self) -> usize {
        self.inner.usage()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cache::codec::tests::{person_properties, trained_codec};

    /// Proto3 encodes an absent bytes field as empty, and every leader
    /// write path serializes at least `{}` — so empty properties can
    /// only arrive from records that predate this store, and rejecting
    /// them would fail the warm over a document that is simply
    /// property-less. This pins the lenient reading in both directions:
    /// decode accepts, and parse yields the empty map.
    #[test]
    fn empty_properties_bytes_read_as_the_empty_map() {
        let record = Person {
            uuid: "00000000-0000-0000-0000-000000000001".to_string(),
            properties: Vec::new(),
            ..Default::default()
        };
        let cached = CachedPerson::try_from(record).expect("empty properties decode");
        assert!(cached.properties.is_empty());
        assert_eq!(
            cached.parse_properties().unwrap(),
            serde_json::Value::Object(serde_json::Map::new())
        );
    }

    #[test]
    fn only_an_empty_document_has_no_properties() {
        for (properties, expected) in [
            (&b""[..], true),
            (&b"{}"[..], true),
            (&br#"{"email":"test@example.com"}"#[..], false),
        ] {
            let person = CachedPerson {
                properties: properties.to_vec(),
                ..test_person()
            };
            assert_eq!(person.has_no_properties(), expected, "{properties:?}");
        }
    }

    const TOKEN: u64 = 7;

    fn tracking_cache() -> (PersonCache, PersonCacheKey) {
        let cache = PersonCache::new(1024 * 1024, Arc::new(PropertiesCodec::disabled()));
        cache.track_puts(TOKEN, 1000);
        let key = PersonCacheKey {
            team_id: 42,
            person_id: 1,
        };
        (cache, key)
    }

    fn at_version(version: i64) -> CachedPerson {
        CachedPerson {
            version,
            ..test_person()
        }
    }

    #[test]
    fn a_fill_inserts_a_key_once_and_refuses_older_records_for_it() {
        let (cache, key) = tracking_cache();
        assert_eq!(
            cache.fill(TOKEN, key.clone(), at_version(5)),
            FillOutcome::Inserted
        );
        assert_eq!(
            cache.fill(TOKEN, key.clone(), at_version(4)),
            FillOutcome::AlreadyPut
        );
        assert_eq!(cache.get(&key).unwrap().version, 5);
    }

    #[test]
    fn a_fill_never_replaces_a_key_put_since_tracking_began() {
        let (cache, key) = tracking_cache();
        cache.put(key.clone(), at_version(6));
        cache.remove(&key);
        assert_eq!(
            cache.fill(TOKEN, key.clone(), at_version(5)),
            FillOutcome::AlreadyPut
        );
        assert!(cache.get(&key).is_none());
    }

    #[test]
    fn a_death_document_keeps_older_records_of_its_person_out() {
        let (cache, key) = tracking_cache();
        let death = CachedPerson {
            is_deleted: true,
            ..at_version(6)
        };
        assert_eq!(cache.fill(TOKEN, key.clone(), death), FillOutcome::Dead);
        assert_eq!(
            cache.fill(TOKEN, key.clone(), at_version(5)),
            FillOutcome::AlreadyPut
        );
        assert!(cache.get(&key).is_none());
    }

    #[test]
    fn a_fill_holding_another_builds_token_inserts_nothing() {
        let (cache, key) = tracking_cache();
        assert_eq!(
            cache.fill(TOKEN + 1, key.clone(), at_version(5)),
            FillOutcome::NotTracking
        );
        cache.stop_tracking_puts(TOKEN + 1);
        assert_eq!(
            cache.fill(TOKEN, key.clone(), at_version(5)),
            FillOutcome::Inserted
        );
    }

    #[test]
    fn tracking_stops_once_it_holds_more_keys_than_its_bound() {
        let cache = PersonCache::new(1024 * 1024, Arc::new(PropertiesCodec::disabled()));
        cache.track_puts(TOKEN, 2);
        for person_id in 1..=3 {
            let key = PersonCacheKey {
                team_id: 42,
                person_id,
            };
            cache.put(key, at_version(1));
        }
        assert_eq!(cache.fill_token(), None);
    }

    #[test]
    fn a_fill_stops_tracking_once_its_own_inserts_pass_the_bound() {
        let cache = PersonCache::new(1024 * 1024, Arc::new(PropertiesCodec::disabled()));
        cache.track_puts(TOKEN, 1);
        let key = |person_id| PersonCacheKey {
            team_id: 42,
            person_id,
        };
        assert_eq!(
            cache.fill(TOKEN, key(1), at_version(1)),
            FillOutcome::Inserted
        );
        assert_eq!(
            cache.fill(TOKEN, key(2), at_version(1)),
            FillOutcome::NotTracking
        );
        assert!(cache.get(&key(2)).is_none());
    }

    #[test]
    fn a_fill_inserts_nothing_once_tracking_stops() {
        let (cache, key) = tracking_cache();
        cache.stop_tracking_puts(TOKEN);
        assert_eq!(
            cache.fill(TOKEN, key.clone(), at_version(5)),
            FillOutcome::NotTracking
        );
        assert!(cache.get(&key).is_none());
    }

    fn test_person() -> CachedPerson {
        CachedPerson {
            id: 1,
            uuid: "abc-123".to_string(),
            team_id: 42,
            properties: serde_json::to_vec(&serde_json::json!({"email": "test@example.com"}))
                .unwrap(),
            created_at: 1700000000,
            version: 1,
            is_identified: false,
            is_deleted: false,
            last_seen_at: None,
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
        let cache = PersonCache::new(64 * 1024, Arc::new(PropertiesCodec::disabled()));
        let blob = "x".repeat(1536);
        for person_id in 0..128 {
            let mut person = test_person();
            person.id = person_id;
            person.properties =
                serde_json::to_vec(&serde_json::json!({ "blob": blob.clone() })).unwrap();
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
        let cache = PersonCache::new(1 << 20, Arc::new(PropertiesCodec::disabled()));
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
        assert_eq!(
            cached.parse_properties().unwrap()["email"],
            "test@example.com"
        );
    }

    #[test]
    fn compressed_entries_read_back_whole_and_weigh_less() {
        let key = PersonCacheKey {
            team_id: 42,
            person_id: 1,
        };
        let mut person = test_person();
        person.properties = person_properties(10_001);
        let raw = PersonCache::new(1 << 20, Arc::new(PropertiesCodec::disabled()));
        let compressed = PersonCache::new(1 << 20, Arc::new(trained_codec()));

        for cache in [&raw, &compressed] {
            cache.put(key.clone(), person.clone());
            assert_eq!(cache.get(&key).unwrap().properties, person.properties);
        }
        assert!(compressed.usage_bytes() < raw.usage_bytes());
    }

    #[test]
    fn an_entry_that_fails_to_decode_reads_as_a_miss_and_leaves_the_cache() {
        let cache = PersonCache::new(1 << 20, Arc::new(PropertiesCodec::disabled()));
        let key = PersonCacheKey {
            team_id: 42,
            person_id: 1,
        };
        let mut person = test_person();
        person.properties = person_properties(10_001);
        // A codec without a dictionary cannot decode a compressed frame, which stands in for a corrupt entry.
        cache
            .inner
            .insert(key.clone(), StoredPerson::new(person, &trained_codec()));

        assert!(cache.get(&key).is_none());
        assert!(cache.peek(&key).is_none());
    }

    #[test]
    fn cache_remove() {
        let cache = PersonCache::new(1 << 20, Arc::new(PropertiesCodec::disabled()));
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
        let cache = PersonCache::new(1 << 20, Arc::new(PropertiesCodec::disabled()));
        let key = PersonCacheKey {
            team_id: 42,
            person_id: 1,
        };

        cache.put(key.clone(), test_person());

        let mut updated = test_person();
        updated.version = 2;
        updated.properties =
            serde_json::to_vec(&serde_json::json!({"email": "new@example.com"})).unwrap();
        cache.put(key.clone(), updated);

        let cached = cache.get(&key).unwrap();
        assert_eq!(cached.version, 2);
        assert_eq!(
            cached.parse_properties().unwrap()["email"],
            "new@example.com"
        );
    }
}
