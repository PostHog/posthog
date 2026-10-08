use std::hash::{Hash, Hasher};

use chrono::{DateTime, Utc};
use metrics::Counter;
use quick_cache::{sync, DefaultHashBuilder, Equivalent, Lifecycle, UnitWeighter};

use crate::{
    metrics_consts::{
        CACHE_EVICTIONS, CACHE_HITS, CACHE_MISSES, CACHE_REPLACEMENTS, UPDATES_CACHE,
    },
    types::{EventProperty, GroupType, PropertyParentType, PropertyValueType, Update},
};

// Per-subcache eviction observer. The `stats` feature of quick_cache is not
// enabled, so all cache hit/miss/eviction signal in this service comes from
// explicit metrics emitted here and in `contains_key`.
//
// quick_cache also calls `on_evict` with the old entry when `insert` finds the
// key already resident, so this counter includes the in-place replacements
// `Cache::insert` makes on purpose. Those are counted separately as
// CACHE_REPLACEMENTS; capacity evictions are the difference.
//
// Counter handles are resolved once at construction and reused: these paths run
// per update (and `on_evict` runs under the shard write lock), so a registry
// lookup per increment is measurable CPU. The metrics recorder must be installed
// before `Cache::new`, because a handle resolved earlier is a no-op forever.
#[derive(Clone)]
struct EvictingLifecycle {
    evictions: Counter,
}

impl<K, V> Lifecycle<K, V> for EvictingLifecycle {
    type RequestState = ();

    fn begin_request(&self) -> Self::RequestState {}

    fn on_evict(&self, _state: &mut Self::RequestState, _key: K, _val: V) {
        self.evictions.increment(1);
    }
}

type SubCache<K, V> = sync::Cache<K, V, UnitWeighter, DefaultHashBuilder, EvictingLifecycle>;

struct SubCacheEntry<K: Eq + Hash + Clone, V: Clone> {
    cache: SubCache<K, V>,
    hits: Counter,
    misses: Counter,
    replacements: Counter,
}

impl<K: Eq + Hash + Clone, V: Clone> SubCacheEntry<K, V> {
    // Writes exactly what a plain `insert` would, and reports whether the write
    // replaced a resident entry. quick_cache `replace` with `soft: false` takes
    // the same `insert_existing` path as `insert` on a resident key (same
    // segment, same `referenced` bump, same `on_evict`), and only differs by
    // failing when the key is not resident. That failure is how a concurrent
    // remove between the caller's peek and this write stays uncounted: the
    // value then goes in through `insert`, as it would have anyway.
    fn write(&self, key: K, value: V, peeked_resident: bool) -> InsertOutcome {
        if !peeked_resident {
            self.cache.insert(key, value);
            return InsertOutcome::Inserted;
        }
        match self.cache.replace(key, value, false) {
            Ok(()) => {
                self.replacements.increment(1);
                InsertOutcome::Replaced
            }
            Err((key, value)) => {
                self.cache.insert(key, value);
                InsertOutcome::Inserted
            }
        }
    }
}

/// What `Cache::insert` did with an update. Only `Unchanged` skips the write,
/// and it does so on exactly the guards that predate this bookkeeping.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum InsertOutcome {
    /// The row identity was not resident and is now.
    Inserted,
    /// The identity was resident and quick_cache replaced the entry in place,
    /// whether or not the value differs.
    Replaced,
    /// A guard rejected the update before any write: an older or equal eventdef
    /// bucket, or an untyped property over a typed one.
    Unchanged,
}

fn build_subcache<K: Eq + Hash + Clone, V: Clone>(
    capacity: usize,
    label: &'static str,
) -> SubCacheEntry<K, V> {
    let cache = sync::Cache::with(
        capacity,
        capacity as u64,
        UnitWeighter,
        DefaultHashBuilder::default(),
        EvictingLifecycle {
            evictions: metrics::counter!(CACHE_EVICTIONS, &[("cache", label)]),
        },
    );
    SubCacheEntry {
        cache,
        hits: metrics::counter!(CACHE_HITS, &[("cache", label)]),
        misses: metrics::counter!(CACHE_MISSES, &[("cache", label)]),
        replacements: metrics::counter!(CACHE_REPLACEMENTS, &[("cache", label)]),
    }
}

// Cache keys carry only the row identity Postgres enforces uniqueness on, and
// everything else about an update lives in the cache VALUE. Keying on the full
// update struct made every field variation a separate entry: a property whose
// detected type flips (null values, a stray "true", a date-looking string)
// occupied one slot per variant, and every event definition abandoned a dead
// entry each time its floored last_seen bucket rolled over.

/// Identity of a `posthog_eventdefinition` row. The floored `last_seen_at`
/// bucket is the cache value, so a rollover replaces it in place.
#[derive(Clone, Debug, Hash, Eq, PartialEq)]
struct EventDefKey {
    team_id: i32,
    project_id: i64,
    name: String,
}

// Borrowed lookup forms. `contains_key` runs per update, so building an owned
// key (two String allocations) per lookup is measurable; these hash and compare
// identically to their owned counterparts. Field order must match the owned
// struct declaration, because the derived Hash hashes fields in that order.
struct EventDefKeyRef<'a> {
    team_id: i32,
    project_id: i64,
    name: &'a str,
}

impl Hash for EventDefKeyRef<'_> {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.team_id.hash(state);
        self.project_id.hash(state);
        self.name.hash(state);
    }
}

impl Equivalent<EventDefKey> for EventDefKeyRef<'_> {
    fn equivalent(&self, key: &EventDefKey) -> bool {
        self.team_id == key.team_id && self.project_id == key.project_id && self.name == key.name
    }
}

/// Identity of a `posthog_propertydefinition` row: the ON CONFLICT key of the
/// upsert. Group types are keyed by name so the Unresolved form the producer
/// caches and the Resolved form the writer works with address the same entry.
/// The detected property type is the cache value: `None` upgrades to `Some`
/// with one write (mirroring the guarded DO UPDATE), any other flip is a no-op
/// for Postgres and stays a cache hit.
#[derive(Clone, Debug, Hash, Eq, PartialEq)]
struct PropDefKey {
    team_id: i32,
    project_id: i64,
    name: String,
    event_type: PropertyParentType,
    group_name: Option<String>,
}

struct PropDefKeyRef<'a> {
    team_id: i32,
    project_id: i64,
    name: &'a str,
    event_type: PropertyParentType,
    group_name: Option<&'a str>,
}

impl Hash for PropDefKeyRef<'_> {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.team_id.hash(state);
        self.project_id.hash(state);
        self.name.hash(state);
        self.event_type.hash(state);
        self.group_name.hash(state);
    }
}

impl Equivalent<PropDefKey> for PropDefKeyRef<'_> {
    fn equivalent(&self, key: &PropDefKey) -> bool {
        self.team_id == key.team_id
            && self.project_id == key.project_id
            && self.name == key.name
            && self.event_type == key.event_type
            && self.group_name == key.group_name.as_deref()
    }
}

fn group_name(group: &GroupType) -> &str {
    match group {
        GroupType::Unresolved(name) | GroupType::Resolved(name, _) => name,
    }
}

pub struct Cache {
    eventdefs: SubCacheEntry<EventDefKey, DateTime<Utc>>,
    eventprops: SubCacheEntry<EventProperty, ()>,
    propdefs: SubCacheEntry<PropDefKey, Option<PropertyValueType>>,
    removed: Counter,
    not_cached: Counter,
}

// TODO: next iter, try using unsync::Cache(s) here and manage sync access to each
// manually. This enables implementing new batch insert/remove APIs on this wrapper,
// since we rarely want to work with just one cache entry at a time in propdefs. I
// suspect small-batch updates would further reduce internal cache lock contention
// that can slow down our batch write threads, esp. when a write fails and we evict
impl Cache {
    pub fn new(
        eventdefs_capacity: usize,
        eventprops_capacity: usize,
        propdefs_capacity: usize,
    ) -> Self {
        Self {
            eventdefs: build_subcache(eventdefs_capacity, "eventdefs"),
            eventprops: build_subcache(eventprops_capacity, "eventprops"),
            propdefs: build_subcache(propdefs_capacity, "propdefs"),
            removed: metrics::counter!(UPDATES_CACHE, &[("action", "removed")]),
            not_cached: metrics::counter!(UPDATES_CACHE, &[("action", "not_cached")]),
        }
    }

    pub fn eventdefs_len(&self) -> usize {
        self.eventdefs.cache.len()
    }

    pub fn eventprops_len(&self) -> usize {
        self.eventprops.cache.len()
    }

    pub fn propdefs_len(&self) -> usize {
        self.propdefs.cache.len()
    }

    /// True when the cached state already covers this update, meaning the write
    /// it stands for would change nothing in Postgres.
    ///
    /// Lookups go through quick_cache `peek`, which does not mark the entry
    /// referenced. Identity keys keep the working set within capacity and the
    /// reader-side batch filter drops rows Postgres already has, so eviction
    /// recency cannot change outcomes and a cache miss costs a filtered probe,
    /// not a useless write. Marking every probe only adds S3-FIFO promotion
    /// work under the shard locks on the hottest path in the service. If a
    /// subcache pins at full again with an eroding hit rate, grow its capacity
    /// instead of re-adding per-probe marking.
    pub fn contains_key(&self, key: &Update) -> bool {
        let (covered, hits, misses) = match key {
            Update::Event(def) => {
                let lookup = EventDefKeyRef {
                    team_id: def.team_id,
                    project_id: def.project_id,
                    name: &def.name,
                };
                // Only a bucket newer than the cached one demands a re-issue.
                // Producers interleave, so an update from the previous bucket
                // can be checked after a rollover was cached; the newer write
                // already refreshed the row, so the older update stays covered.
                let covered = self
                    .eventdefs
                    .cache
                    .peek(&lookup)
                    .is_some_and(|bucket| bucket >= def.last_seen_at);
                (covered, &self.eventdefs.hits, &self.eventdefs.misses)
            }
            Update::EventProperty(ep) => (
                self.eventprops.cache.peek(ep).is_some(),
                &self.eventprops.hits,
                &self.eventprops.misses,
            ),
            Update::Property(def) => {
                let lookup = PropDefKeyRef {
                    team_id: def.team_id,
                    project_id: def.project_id,
                    name: &def.name,
                    event_type: def.event_type,
                    group_name: def.group_type_index.as_ref().map(group_name),
                };
                let covered = match self.propdefs.cache.peek(&lookup) {
                    // An untyped cached row upgrades once when a typed sighting
                    // arrives; every other combination cannot change the row.
                    Some(cached) => !(cached.is_none() && def.property_type.is_some()),
                    None => false,
                };
                (covered, &self.propdefs.hits, &self.propdefs.misses)
            }
        };
        if covered {
            hits.increment(1);
        } else {
            misses.increment(1);
        }
        covered
    }

    // Both valued subcaches only move forward: a newer last_seen bucket, or a
    // None to Some type upgrade. Concurrent producers interleave their
    // contains_key/insert pairs, so an insert can arrive after another producer
    // cached fresher state; replacing that state would make the next sighting
    // miss and re-issue a write Postgres treats as a no-op. The peek-then-insert
    // pairs below race too, but losing that race costs one redundant upsert.
    //
    // Every write that reaches quick_cache here is the same write with or
    // without the outcome bookkeeping: an equal value re-inserted over a
    // resident key still goes through, so the entry keeps the `referenced`
    // credit quick_cache grants on that path. The peek only decides whether
    // the write is issued as a `replace` (counted) or an `insert`.
    //
    // The peek and the write are separate lock acquisitions. A concurrent
    // producer can insert the same new key in between, which makes the second
    // write an uncounted replacement. That race is the one already measured by
    // DUPLICATES_IN_BATCH and is far too rare to move the replacement counter.
    pub fn insert(&self, key: Update) -> InsertOutcome {
        match key {
            Update::Event(def) => {
                let lookup = EventDefKeyRef {
                    team_id: def.team_id,
                    project_id: def.project_id,
                    name: &def.name,
                };
                let cached = self.eventdefs.cache.peek(&lookup);
                if cached.is_some_and(|bucket| bucket >= def.last_seen_at) {
                    return InsertOutcome::Unchanged;
                }
                let key = EventDefKey {
                    team_id: def.team_id,
                    project_id: def.project_id,
                    name: def.name,
                };
                self.eventdefs
                    .write(key, def.last_seen_at, cached.is_some())
            }
            Update::EventProperty(ep) => {
                let resident = self.eventprops.cache.peek(&ep).is_some();
                self.eventprops.write(ep, (), resident)
            }
            Update::Property(def) => {
                let lookup = PropDefKeyRef {
                    team_id: def.team_id,
                    project_id: def.project_id,
                    name: &def.name,
                    event_type: def.event_type,
                    group_name: def.group_type_index.as_ref().map(group_name),
                };
                let cached = self.propdefs.cache.peek(&lookup);
                if def.property_type.is_none() && matches!(cached, Some(Some(_))) {
                    return InsertOutcome::Unchanged;
                }
                let key = PropDefKey {
                    team_id: def.team_id,
                    project_id: def.project_id,
                    name: def.name,
                    event_type: def.event_type,
                    group_name: def.group_type_index.map(|g| match g {
                        GroupType::Unresolved(name) | GroupType::Resolved(name, _) => name,
                    }),
                };
                self.propdefs
                    .write(key, def.property_type, cached.is_some())
            }
        }
    }

    // we don't return the retrieved KV since propdefs doesn't require it
    pub fn remove(&self, key: &Update) {
        let removed = match key {
            Update::Event(def) => self
                .eventdefs
                .cache
                .remove(&EventDefKeyRef {
                    team_id: def.team_id,
                    project_id: def.project_id,
                    name: &def.name,
                })
                .is_some(),
            Update::EventProperty(ep) => self.eventprops.cache.remove(ep).is_some(),
            Update::Property(def) => self
                .propdefs
                .cache
                .remove(&PropDefKeyRef {
                    team_id: def.team_id,
                    project_id: def.project_id,
                    name: &def.name,
                    event_type: def.event_type,
                    group_name: def.group_type_index.as_ref().map(group_name),
                })
                .is_some(),
        };

        if removed {
            self.removed.increment(1);
        } else {
            self.not_cached.increment(1);
        }
    }
}
