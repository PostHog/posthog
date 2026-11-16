//! The two feeds folded side by side and settled by watermark: an entry
//! waits until the slower feed has delivered past it by the grace, so a
//! lagging feed never reads as one-sided. Pure; the pipeline emits metrics.

use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use personhog_common::cdc_parity::{
    compare_mapping, compare_person, compare_survivor, DistinctIdKey, DistinctIdRow, FeedState,
    Mapping, MappingOutcome, MergeEvent, PersonFeed, PersonKey, PersonOutcome, PersonRow,
    PersonSnapshot, Side, SurvivorOutcome,
};
use personhog_common::partitioning::partition_for_key;
use serde_json::{json, Value};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Kind {
    DistinctIds,
    MergeEvents,
    Persons,
}

impl Kind {
    pub fn label(self) -> &'static str {
        match self {
            Kind::DistinctIds => "distinct_ids",
            Kind::MergeEvents => "merge_events",
            Kind::Persons => "persons",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Topic {
    pub side: Side,
    pub kind: Kind,
}

#[derive(Debug, Clone)]
pub enum Record {
    Mapping(DistinctIdRow),
    Merge(MergeEvent),
    Person(PersonRow),
}

#[derive(Debug, Clone)]
pub enum Event {
    /// The count places merge keys.
    Assigned { topic: Topic, partitions: u32 },
    Arrival {
        topic: Topic,
        partition: i32,
        timestamp_ms: i64,
        record: Record,
    },
    /// A row outside the person sample, which still moves the watermark.
    Skipped {
        topic: Topic,
        partition: i32,
        timestamp_ms: i64,
    },
}

impl Event {
    pub fn topic(&self) -> Topic {
        match self {
            Event::Assigned { topic, .. }
            | Event::Arrival { topic, .. }
            | Event::Skipped { topic, .. } => *topic,
        }
    }
}

#[derive(Debug, Clone)]
pub struct JoinConfig {
    pub grace: Duration,
    pub idle_partition: Duration,
    pub max_entries: usize,
    pub teams: Option<HashSet<i64>>,
    /// Covers the timestamp skew between a merge event and the rows it
    /// moved, so a settling merge still finds the rows naming its persons.
    pub mapping_lag: Duration,
    /// Entries older than the first watermark plus this are dropped
    /// unjudged, because a counterpart may predate the readers. Zero
    /// turns the warmup off.
    pub warmup: Duration,
    pub person_ignored_properties: HashSet<String>,
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct ObserveReport {
    pub filtered: bool,
    pub sampled_out: bool,
    pub version_tie: Option<Side>,
    pub merge_conflict: Option<Side>,
    /// Whether the merge event sits on the partition its key selects.
    pub placement: Option<(Side, bool)>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum PartitionAgreement {
    Same,
    Different,
}

impl PartitionAgreement {
    pub fn label(self) -> &'static str {
        match self {
            PartitionAgreement::Same => "same",
            PartitionAgreement::Different => "different",
        }
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct SweepReport {
    pub mapping_outcomes: BTreeMap<MappingOutcome, u64>,
    pub merge_outcomes: BTreeMap<SurvivorOutcome, u64>,
    pub merge_partitions: BTreeMap<PartitionAgreement, u64>,
    pub person_outcomes: BTreeMap<PersonOutcome, u64>,
    pub overflow_evictions: u64,
    pub warmup_evictions: u64,
    pub pending_mappings: usize,
    pub pending_merges: usize,
    pub pending_persons: usize,
    /// The global watermark the sweep settled against.
    pub watermark_ms: Option<i64>,
    /// Each feed's own watermark, indexed by [`side_index`].
    pub feed_watermarks_ms: [Option<i64>; 2],
    pub person_watermarks_ms: [Option<i64>; 2],
}

pub fn side_index(side: Side) -> usize {
    match side {
        Side::Node => 0,
        Side::Personhog => 1,
    }
}

/// Metrics carry only outcome labels; this is where an operator sees an example.
#[derive(Clone)]
pub struct SampleRing {
    inner: Arc<Mutex<VecDeque<Value>>>,
    capacity: usize,
}

impl SampleRing {
    pub fn new(capacity: usize) -> Self {
        Self {
            inner: Arc::new(Mutex::new(VecDeque::with_capacity(capacity))),
            capacity,
        }
    }

    fn push(&self, sample: Value) {
        if self.capacity == 0 {
            return;
        }
        let mut ring = self
            .inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if ring.len() == self.capacity {
            ring.pop_front();
        }
        ring.push_back(sample);
    }

    pub fn snapshot(&self) -> Vec<Value> {
        self.inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .iter()
            .cloned()
            .collect()
    }
}

struct PartitionProgress {
    max_timestamp_ms: i64,
    last_seen: Instant,
}

#[derive(Default)]
struct TopicProgress {
    partitions: HashMap<i32, PartitionProgress>,
    partition_count: Option<u32>,
}

impl TopicProgress {
    /// The slowest of the partitions that delivered within the idle window.
    fn active_min(&self, now: Instant, idle: Duration) -> Option<i64> {
        self.partitions
            .values()
            .filter(|progress| now.duration_since(progress.last_seen) <= idle)
            .map(|progress| progress.max_timestamp_ms)
            .min()
    }

    fn newest(&self) -> Option<i64> {
        self.partitions
            .values()
            .map(|progress| progress.max_timestamp_ms)
            .max()
    }

    /// The newest message, moved forward by the time since it arrived.
    fn newest_advanced(&self, now: Instant) -> Option<i64> {
        self.partitions
            .values()
            .map(|progress| {
                progress.max_timestamp_ms
                    + now.duration_since(progress.last_seen).as_millis() as i64
            })
            .max()
    }
}

struct MappingEntry {
    last_update_ms: i64,
}

struct PersonEntry {
    last_update_ms: i64,
}

struct MergeEntry {
    last_update_ms: i64,
    partitions: [Option<i32>; 2],
    /// Each feed's recorded target, released when the entry is evicted.
    targets: [Option<PersonKey>; 2],
    /// Judged already; kept while a pending merge still points at it.
    settled: bool,
}

pub struct Join {
    config: JoinConfig,
    node: FeedState,
    personhog: FeedState,
    mappings: HashMap<DistinctIdKey, MappingEntry>,
    merges: HashMap<PersonKey, MergeEntry>,
    node_persons: PersonFeed,
    personhog_persons: PersonFeed,
    persons: HashMap<PersonKey, PersonEntry>,
    /// How many merge entries point at each person on either feed.
    target_refs: HashMap<PersonKey, usize>,
    progress: HashMap<Topic, TopicProgress>,
    warmup_until_ms: Option<i64>,
    samples: SampleRing,
}

impl Join {
    pub fn new(config: JoinConfig, samples: SampleRing) -> Self {
        Self {
            config,
            node: FeedState::new(),
            personhog: FeedState::new(),
            mappings: HashMap::new(),
            merges: HashMap::new(),
            node_persons: PersonFeed::default(),
            personhog_persons: PersonFeed::default(),
            persons: HashMap::new(),
            target_refs: HashMap::new(),
            progress: HashMap::new(),
            warmup_until_ms: None,
            samples,
        }
    }

    fn feed(&self, side: Side) -> &FeedState {
        match side {
            Side::Node => &self.node,
            Side::Personhog => &self.personhog,
        }
    }

    fn feed_mut(&mut self, side: Side) -> &mut FeedState {
        match side {
            Side::Node => &mut self.node,
            Side::Personhog => &mut self.personhog,
        }
    }

    pub fn observe(&mut self, event: Event, now: Instant) -> ObserveReport {
        let mut report = ObserveReport::default();
        let (topic, partition, timestamp_ms, record) = match event {
            Event::Assigned { topic, partitions } => {
                self.progress.entry(topic).or_default().partition_count = Some(partitions);
                return report;
            }
            Event::Skipped {
                topic,
                partition,
                timestamp_ms,
            } => {
                self.record_progress(topic, partition, timestamp_ms, now);
                report.sampled_out = true;
                return report;
            }
            Event::Arrival {
                topic,
                partition,
                timestamp_ms,
                record,
            } => (topic, partition, timestamp_ms, record),
        };

        let partition_count = self.record_progress(topic, partition, timestamp_ms, now);

        let team_id = match &record {
            Record::Mapping(row) => row.team_id,
            Record::Merge(event) => event.team_id,
            Record::Person(row) => row.team_id,
        };
        if let Some(teams) = &self.config.teams {
            if !teams.contains(&team_id) {
                report.filtered = true;
                return report;
            }
        }

        match record {
            Record::Mapping(row) => {
                if self.feed_mut(topic.side).observe_mapping(&row).is_some() {
                    report.version_tie = Some(topic.side);
                }
                let key = DistinctIdKey::new(row.team_id, row.distinct_id);
                let entry = self.mappings.entry(key).or_insert(MappingEntry {
                    last_update_ms: timestamp_ms,
                });
                entry.last_update_ms = entry.last_update_ms.max(timestamp_ms);
            }
            Record::Merge(event) => {
                if let Some(count) = partition_count {
                    let expected = partition_for_key(event.key().as_bytes(), count) as i32;
                    report.placement = Some((topic.side, expected == partition));
                }
                let side = side_index(topic.side);
                if self.feed_mut(topic.side).observe_merge(&event).is_some() {
                    report.merge_conflict = Some(topic.side);
                }
                let old = PersonKey::new(event.team_id, event.old_person_uuid);
                let target = self
                    .feed(topic.side)
                    .merged_into(&old)
                    .map(|new| PersonKey::new(event.team_id, new));
                let entry = self.merges.entry(old).or_insert(MergeEntry {
                    last_update_ms: timestamp_ms,
                    partitions: [None, None],
                    targets: [None, None],
                    settled: false,
                });
                entry.last_update_ms = entry.last_update_ms.max(timestamp_ms);
                entry.partitions[side] = Some(partition);
                if let (None, Some(target)) = (entry.targets[side], target) {
                    entry.targets[side] = Some(target);
                    *self.target_refs.entry(target).or_default() += 1;
                }
            }
            Record::Person(row) => {
                let ignored = &self.config.person_ignored_properties;
                let feed = match topic.side {
                    Side::Node => &mut self.node_persons,
                    Side::Personhog => &mut self.personhog_persons,
                };
                if feed.observe(&row, ignored) {
                    report.version_tie = Some(topic.side);
                }
                let entry = self.persons.entry(row.key()).or_insert(PersonEntry {
                    last_update_ms: timestamp_ms,
                });
                entry.last_update_ms = entry.last_update_ms.max(timestamp_ms);
            }
        }
        report
    }

    /// Returns the topic's partition count, which places merge keys.
    fn record_progress(
        &mut self,
        topic: Topic,
        partition: i32,
        timestamp_ms: i64,
        now: Instant,
    ) -> Option<u32> {
        let progress = self.progress.entry(topic).or_default();
        let seen = progress
            .partitions
            .entry(partition)
            .or_insert(PartitionProgress {
                max_timestamp_ms: timestamp_ms,
                last_seen: now,
            });
        seen.max_timestamp_ms = seen.max_timestamp_ms.max(timestamp_ms);
        seen.last_seen = now;
        progress.partition_count
    }

    fn warmup_until(&mut self, watermark: i64) -> i64 {
        if self.config.warmup.is_zero() {
            return i64::MIN;
        }
        let warmup = self.config.warmup.as_millis() as i64;
        *self.warmup_until_ms.get_or_insert(watermark + warmup)
    }

    /// Merges settle first and mappings a little later, so a merge's
    /// verdict can still ask which persons each feed named. Entries the
    /// cap evicts are not counted: they never got their grace.
    pub fn settle(&mut self, now: Instant) -> SweepReport {
        let mut report = SweepReport {
            feed_watermarks_ms: self.feed_watermarks(Kind::DistinctIds, now),
            person_watermarks_ms: self.feed_watermarks(Kind::Persons, now),
            ..Default::default()
        };
        if let [Some(node), Some(personhog)] = report.feed_watermarks_ms {
            let watermark = node.min(personhog);
            report.watermark_ms = Some(watermark);
            let warmup_until = self.warmup_until(watermark);
            let merge_cutoff = watermark - self.config.grace.as_millis() as i64;
            let mapping_cutoff = merge_cutoff - self.config.mapping_lag.as_millis() as i64;
            let due: Vec<(PersonKey, i64)> = self
                .merges
                .iter()
                .filter(|(_, entry)| !entry.settled && entry.last_update_ms <= merge_cutoff)
                .map(|(old, entry)| (*old, entry.last_update_ms))
                .collect();
            for (old, last_update_ms) in due {
                if last_update_ms < warmup_until {
                    self.evict_merge(old);
                    report.warmup_evictions += 1;
                } else {
                    self.settle_merge(old, last_update_ms, &mut report);
                    self.release_merge(old);
                }
            }
            let due: Vec<(DistinctIdKey, i64)> = self
                .mappings
                .iter()
                .filter(|(_, entry)| entry.last_update_ms <= mapping_cutoff)
                .map(|(key, entry)| (key.clone(), entry.last_update_ms))
                .collect();
            for (key, last_update_ms) in due {
                if last_update_ms < warmup_until {
                    self.evict_mapping(&key);
                    report.warmup_evictions += 1;
                } else {
                    self.settle_mapping(&key, last_update_ms, &mut report);
                }
            }
        }
        if let [Some(node), Some(personhog)] = report.person_watermarks_ms {
            let watermark = node.min(personhog);
            let warmup_until = self.warmup_until(watermark);
            let cutoff = watermark - self.config.grace.as_millis() as i64;
            let due: Vec<(PersonKey, i64)> = self
                .persons
                .iter()
                .filter(|(_, entry)| entry.last_update_ms <= cutoff)
                .map(|(key, entry)| (*key, entry.last_update_ms))
                .collect();
            for (key, last_update_ms) in due {
                if last_update_ms < warmup_until {
                    self.evict_person(&key);
                    report.warmup_evictions += 1;
                } else {
                    self.settle_person(&key, last_update_ms, &mut report);
                }
            }
        }
        self.enforce_cap(&mut report);
        report.pending_persons = self.persons.len();
        report.pending_mappings = self.mappings.len();
        report.pending_merges = self.merges.values().filter(|entry| !entry.settled).count();
        report
    }

    /// Mappings and merges settle on the distinct id topics: the sparse
    /// merge topic would hold the watermark an idle window behind. Persons
    /// settle on the person topics. A quiet feed advances by the wall clock
    /// only while the other feed is quiet too; next to a live feed it has
    /// stalled, so its watermark holds and nothing settles.
    fn feed_watermarks(&self, kind: Kind, now: Instant) -> [Option<i64>; 2] {
        let idle = self.config.idle_partition;
        let progress =
            [Side::Node, Side::Personhog].map(|side| self.progress.get(&Topic { side, kind }));
        let active = progress.map(|topic| topic.and_then(|topic| topic.active_min(now, idle)));
        let both_quiet = active.iter().all(Option::is_none);
        let mut watermarks = [None, None];
        for index in 0..2 {
            watermarks[index] = match (active[index], progress[index]) {
                (Some(active), _) => Some(active),
                (None, Some(topic)) if both_quiet => topic.newest_advanced(now),
                (None, Some(topic)) => topic.newest(),
                (None, None) => None,
            };
        }
        watermarks
    }

    fn settle_mapping(
        &mut self,
        key: &DistinctIdKey,
        last_update_ms: i64,
        report: &mut SweepReport,
    ) {
        let (node, personhog) = (self.node.mapping(key), self.personhog.mapping(key));
        let outcome = compare_mapping(node, personhog);
        if outcome != MappingOutcome::Agree {
            self.samples.push(json!({
                "kind": "mapping",
                "team_id": key.team_id,
                "distinct_id": key.distinct_id,
                "outcome": outcome.label(),
                "last_update_ms": last_update_ms,
                "node": node.map(mapping_json),
                "personhog": personhog.map(mapping_json),
            }));
        }
        *report.mapping_outcomes.entry(outcome).or_default() += 1;
        self.evict_mapping(key);
    }

    fn settle_person(&mut self, key: &PersonKey, last_update_ms: i64, report: &mut SweepReport) {
        let (node, personhog) = (self.node_persons.get(key), self.personhog_persons.get(key));
        let outcome = compare_person(node, personhog);
        if outcome != PersonOutcome::Agree {
            let differing_keys = match (node, personhog) {
                (Some(node), Some(personhog)) => node.differing_keys(personhog),
                _ => Vec::new(),
            };
            self.samples.push(json!({
                "kind": "person",
                "team_id": key.team_id,
                "person_uuid": key.person_uuid.to_string(),
                "outcome": outcome.label(),
                "last_update_ms": last_update_ms,
                "differing_properties": differing_keys,
                "node": node.map(person_json),
                "personhog": personhog.map(person_json),
            }));
        }
        *report.person_outcomes.entry(outcome).or_default() += 1;
        self.evict_person(key);
    }

    fn evict_person(&mut self, key: &PersonKey) {
        self.node_persons.remove(key);
        self.personhog_persons.remove(key);
        self.persons.remove(key);
    }

    fn settle_merge(&mut self, old: PersonKey, last_update_ms: i64, report: &mut SweepReport) {
        let outcome = compare_survivor(&self.node, &self.personhog, old);
        let partitions = self
            .merges
            .get(&old)
            .map_or([None, None], |entry| entry.partitions);
        if let [Some(node), Some(personhog)] = partitions {
            if self.merge_topics_comparable() {
                let agreement = if node == personhog {
                    PartitionAgreement::Same
                } else {
                    PartitionAgreement::Different
                };
                *report.merge_partitions.entry(agreement).or_default() += 1;
            }
        }
        if outcome != SurvivorOutcome::Agree {
            self.samples.push(json!({
                "kind": "merge",
                "team_id": old.team_id,
                "old_person_uuid": old.person_uuid.to_string(),
                "outcome": outcome.label(),
                "last_update_ms": last_update_ms,
                "node": self.node.merged_into(&old).map(|new| new.to_string()),
                "personhog": self.personhog.merged_into(&old).map(|new| new.to_string()),
                "partitions": partitions,
            }));
        }
        *report.merge_outcomes.entry(outcome).or_default() += 1;
        if let Some(entry) = self.merges.get_mut(&old) {
            entry.settled = true;
        }
    }

    /// A settled merge keeps its edge while a pending merge still points at
    /// it: that merge's verdict follows the chain through it, and the sweep
    /// order must not decide the verdict.
    fn release_merge(&mut self, old: PersonKey) {
        if self.target_refs.get(&old).copied().unwrap_or(0) == 0 {
            self.evict_merge(old);
        }
    }

    /// Partition numbers only compare across topics with the same count.
    fn merge_topics_comparable(&self) -> bool {
        let counts = [Side::Node, Side::Personhog].map(|side| {
            self.progress
                .get(&Topic {
                    side,
                    kind: Kind::MergeEvents,
                })
                .and_then(|topic| topic.partition_count)
        });
        matches!(counts, [Some(node), Some(personhog)] if node == personhog)
    }

    fn evict_mapping(&mut self, key: &DistinctIdKey) {
        self.node.remove_mapping(key);
        self.personhog.remove_mapping(key);
        self.mappings.remove(key);
    }

    /// Releases the evicted entry's targets; a settled target nothing points
    /// at any more goes with it.
    fn evict_merge(&mut self, old: PersonKey) {
        let mut stack = vec![old];
        while let Some(old) = stack.pop() {
            let Some(entry) = self.merges.remove(&old) else {
                continue;
            };
            self.node.remove_merge(&old);
            self.personhog.remove_merge(&old);
            for target in entry.targets.into_iter().flatten() {
                let Some(refs) = self.target_refs.get_mut(&target) else {
                    continue;
                };
                *refs -= 1;
                if *refs == 0 {
                    self.target_refs.remove(&target);
                    if self.merges.get(&target).is_some_and(|entry| entry.settled) {
                        stack.push(target);
                    }
                }
            }
        }
    }

    /// Bounds retained rows and merges, not keys: a key that keeps receiving
    /// versions grows behind one entry. Trims to nine tenths of the cap, one
    /// pass per tenth rather than one per sweep, by key age; every key holds
    /// at least one row, so evicting as many keys as the excess suffices.
    fn enforce_cap(&mut self, report: &mut SweepReport) {
        let total = self.node.row_count()
            + self.personhog.row_count()
            + self.merges.len()
            + self.node_persons.len()
            + self.personhog_persons.len();
        if total <= self.config.max_entries {
            return;
        }
        let target = self.config.max_entries - self.config.max_entries / 10;
        let keys = self.mappings.len() + self.merges.len() + self.persons.len();
        let excess = (total - target).min(keys);
        let mut ages: Vec<i64> = self
            .mappings
            .values()
            .map(|entry| entry.last_update_ms)
            .chain(self.merges.values().map(|entry| entry.last_update_ms))
            .chain(self.persons.values().map(|entry| entry.last_update_ms))
            .collect();
        let (_, threshold, _) = ages.select_nth_unstable(excess - 1);
        let threshold = *threshold;
        let old_merges: Vec<PersonKey> = self
            .merges
            .iter()
            .filter(|(_, entry)| entry.last_update_ms <= threshold)
            .map(|(old, _)| *old)
            .collect();
        for old in old_merges {
            self.evict_merge(old);
            report.overflow_evictions += 1;
        }
        let old_mappings: Vec<DistinctIdKey> = self
            .mappings
            .iter()
            .filter(|(_, entry)| entry.last_update_ms <= threshold)
            .map(|(key, _)| key.clone())
            .collect();
        for key in old_mappings {
            self.evict_mapping(&key);
            report.overflow_evictions += 1;
        }
        let old_persons: Vec<PersonKey> = self
            .persons
            .iter()
            .filter(|(_, entry)| entry.last_update_ms <= threshold)
            .map(|(key, _)| *key)
            .collect();
        for key in old_persons {
            self.evict_person(&key);
            report.overflow_evictions += 1;
        }
    }
}

/// Property values stay out of samples; the differing keys name them.
fn person_json(person: &PersonSnapshot) -> Value {
    json!({
        "is_deleted": person.is_deleted,
        "is_identified": person.is_identified,
        "created_at": person.created_at,
        "version": person.version,
        "property_count": person.properties.len(),
    })
}

fn mapping_json(mapping: &Mapping) -> Value {
    json!({
        "person_uuid": mapping.person_uuid.to_string(),
        "is_deleted": mapping.is_deleted,
        "version": mapping.version,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    const TEAM: i64 = 5;
    const GRACE: Duration = Duration::from_secs(60);
    const IDLE: Duration = Duration::from_secs(30);
    const MAPPING_LAG: Duration = Duration::from_secs(2);

    fn uuid(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn join_with(max_entries: usize, teams: Option<HashSet<i64>>, warmup: Duration) -> Join {
        Join::new(
            JoinConfig {
                grace: GRACE,
                idle_partition: IDLE,
                max_entries,
                teams,
                mapping_lag: MAPPING_LAG,
                warmup,
                person_ignored_properties: HashSet::new(),
            },
            SampleRing::new(10),
        )
    }

    fn join(max_entries: usize, teams: Option<HashSet<i64>>) -> Join {
        join_with(max_entries, teams, Duration::ZERO)
    }

    fn topic(side: Side, kind: Kind) -> Topic {
        Topic { side, kind }
    }

    fn row_of_team(
        team_id: i64,
        side: Side,
        partition: i32,
        timestamp_ms: i64,
        distinct_id: &str,
        person: u128,
        version: i64,
    ) -> Event {
        Event::Arrival {
            topic: topic(side, Kind::DistinctIds),
            partition,
            timestamp_ms,
            record: Record::Mapping(DistinctIdRow {
                team_id,
                distinct_id: distinct_id.to_string(),
                person_uuid: uuid(person),
                version,
                is_deleted: false,
            }),
        }
    }

    fn row(
        side: Side,
        partition: i32,
        timestamp_ms: i64,
        distinct_id: &str,
        person: u128,
    ) -> Event {
        row_of_team(TEAM, side, partition, timestamp_ms, distinct_id, person, 0)
    }

    fn assigned(join: &mut Join, kind: Kind, counts: [u32; 2], at: Instant) {
        for (side, partitions) in [Side::Node, Side::Personhog].into_iter().zip(counts) {
            join.observe(
                Event::Assigned {
                    topic: topic(side, kind),
                    partitions,
                },
                at,
            );
        }
    }

    fn merge(side: Side, partition: i32, timestamp_ms: i64, old: u128, new: u128) -> Event {
        Event::Arrival {
            topic: topic(side, Kind::MergeEvents),
            partition,
            timestamp_ms,
            record: Record::Merge(MergeEvent {
                team_id: TEAM,
                old_person_uuid: uuid(old),
                new_person_uuid: uuid(new),
                merged_at_ms: timestamp_ms,
            }),
        }
    }

    fn mapping_outcomes(report: &SweepReport) -> Vec<(MappingOutcome, u64)> {
        report
            .mapping_outcomes
            .iter()
            .map(|(k, v)| (*k, *v))
            .collect()
    }

    fn both(
        join: &mut Join,
        partition: i32,
        timestamp_ms: i64,
        distinct_id: &str,
        person: u128,
        at: Instant,
    ) {
        for side in [Side::Node, Side::Personhog] {
            join.observe(row(side, partition, timestamp_ms, distinct_id, person), at);
        }
    }

    fn person(side: Side, timestamp_ms: i64, person: u128, properties: &str) -> Event {
        let payload = format!(
            r#"{{"id":"{}","created_at":"2023-11-14 22:13:20","properties":{},"team_id":{TEAM},"is_identified":1,"is_deleted":0,"version":1,"last_seen_at":null}}"#,
            uuid(person),
            serde_json::to_string(properties).unwrap(),
        );
        Event::Arrival {
            topic: topic(side, Kind::Persons),
            partition: 0,
            timestamp_ms,
            record: Record::Person(PersonRow::decode(payload.as_bytes()).unwrap()),
        }
    }

    // Persons settle against the person topics alone: a lagging person feed
    // holds back only person verdicts, and the mappings settle regardless.
    #[test]
    fn persons_settle_behind_their_own_slower_feed() {
        let t0 = Instant::now();
        let mut join = join(usize::MAX, None);
        join.observe(person(Side::Node, 1_000, 1, r#"{"a":1}"#), t0);
        join.observe(person(Side::Personhog, 1_000, 1, r#"{"a":1.0}"#), t0);
        join.observe(person(Side::Node, 1_000, 2, r#"{"a":1,"b":1}"#), t0);
        join.observe(person(Side::Personhog, 1_000, 2, r#"{"a":2}"#), t0);
        join.observe(person(Side::Node, 2_000, 3, "{}"), t0);
        join.observe(person(Side::Node, 70_000, 4, "{}"), t0);
        both(&mut join, 0, 1_000, "d", 9, t0);
        both(&mut join, 0, 70_000, "w", 9, t0);

        let report = join.settle(t0);
        assert_eq!(mapping_outcomes(&report), vec![(MappingOutcome::Agree, 1)]);
        assert_eq!(report.person_outcomes, BTreeMap::new());
        assert_eq!(report.pending_persons, 4);

        join.observe(person(Side::Personhog, 70_000, 4, "{}"), t0);
        let report = join.settle(t0);
        assert_eq!(
            report.person_outcomes,
            BTreeMap::from([
                (PersonOutcome::Agree, 1),
                (PersonOutcome::PropertiesMismatch, 1),
                (PersonOutcome::NodeOnly, 1),
            ])
        );
        assert_eq!(report.pending_persons, 1);
        let samples = join.samples.snapshot();
        let mismatch = samples
            .iter()
            .find(|s| s["outcome"] == "properties_mismatch")
            .expect("a properties sample");
        assert_eq!(mismatch["person_uuid"], uuid(2).to_string());
        assert_eq!(mismatch["differing_properties"], json!(["a", "b"]));
    }

    #[test]
    fn rows_outside_the_person_sample_still_move_the_watermark() {
        let t0 = Instant::now();
        let mut join = join(usize::MAX, None);
        join.observe(person(Side::Node, 1_000, 1, "{}"), t0);
        join.observe(person(Side::Node, 70_000, 2, "{}"), t0);
        let report = join.observe(
            Event::Skipped {
                topic: topic(Side::Personhog, Kind::Persons),
                partition: 0,
                timestamp_ms: 70_000,
            },
            t0,
        );
        assert!(report.sampled_out);

        let report = join.settle(t0);
        assert_eq!(
            report.person_outcomes,
            BTreeMap::from([(PersonOutcome::NodeOnly, 1)])
        );
    }

    // Nothing settles until the slower feed passes the grace; the merge
    // topics never count towards the watermark.
    #[test]
    fn entries_settle_behind_the_slower_feed_after_the_grace() {
        let t0 = Instant::now();
        let mut join = join(usize::MAX, None);
        assigned(&mut join, Kind::MergeEvents, [8, 8], t0);
        join.observe(row(Side::Node, 0, 1_000, "d", 1), t0);
        join.observe(row(Side::Node, 0, 2_000, "only", 2), t0);
        join.observe(row(Side::Node, 0, 70_000, "ahead", 3), t0);
        join.observe(merge(Side::Node, 3, 1_000, 7, 8), t0);
        join.observe(row(Side::Personhog, 0, 1_500, "d", 1), t0);
        join.observe(merge(Side::Personhog, 4, 1_200, 7, 8), t0);

        let report = join.settle(t0);
        assert_eq!(report.watermark_ms, Some(1_500));
        assert_eq!(report.mapping_outcomes, BTreeMap::new());
        assert_eq!(report.pending_mappings, 3);
        assert_eq!(report.pending_merges, 1);

        join.observe(row(Side::Personhog, 0, 70_000, "ahead", 3), t0);
        let report = join.settle(t0);
        assert_eq!(report.watermark_ms, Some(70_000));
        assert_eq!(
            mapping_outcomes(&report),
            vec![(MappingOutcome::Agree, 1), (MappingOutcome::NodeOnly, 1)]
        );
        assert_eq!(
            report.merge_outcomes,
            BTreeMap::from([(SurvivorOutcome::Agree, 1)])
        );
        assert_eq!(
            report.merge_partitions,
            BTreeMap::from([(PartitionAgreement::Different, 1)])
        );
        assert_eq!(report.pending_mappings, 1);
        assert_eq!(report.pending_merges, 0);
        assert_eq!(join.node.mapping_count(), 1);
        assert_eq!(join.personhog.mapping_count(), 1);
        assert_eq!(join.node.merge_count() + join.personhog.merge_count(), 0);
        let samples = join.samples.snapshot();
        assert_eq!(samples.len(), 1);
        assert_eq!(samples[0]["distinct_id"], "only");
        assert_eq!(samples[0]["outcome"], "node_only");
        assert_eq!(samples[0]["last_update_ms"], 2_000);
    }

    // Topics with different counts place the same key on different
    // partition numbers; only the per-feed placement check applies there.
    #[test]
    fn merge_partitions_compare_only_across_equal_counts() {
        let t0 = Instant::now();
        let mut join = join(usize::MAX, None);
        assigned(&mut join, Kind::MergeEvents, [1, 4], t0);
        join.observe(merge(Side::Node, 0, 1_000, 7, 8), t0);
        join.observe(merge(Side::Personhog, 3, 1_000, 7, 8), t0);
        both(&mut join, 0, 70_000, "w", 9, t0);

        let report = join.settle(t0);
        assert_eq!(
            report.merge_outcomes,
            BTreeMap::from([(SurvivorOutcome::Agree, 1)])
        );
        assert_eq!(report.merge_partitions, BTreeMap::new());
    }

    // A lull on both feeds walks the watermark forward.
    #[test]
    fn idle_partitions_release_the_watermark() {
        let t0 = Instant::now();
        let mut join = join(usize::MAX, None);
        both(&mut join, 0, 1_000, "a", 1, t0);
        let later = t0 + Duration::from_secs(40);
        both(&mut join, 1, 70_000, "b", 2, later);

        let report = join.settle(later);
        assert_eq!(report.watermark_ms, Some(70_000));
        assert_eq!(mapping_outcomes(&report), vec![(MappingOutcome::Agree, 1)]);

        let report = join.settle(later + Duration::from_secs(62));
        assert_eq!(report.watermark_ms, Some(132_000));
        assert_eq!(mapping_outcomes(&report), vec![(MappingOutcome::Agree, 1)]);
    }

    // A feed quiet next to a live one has stalled: its watermark holds, so
    // nothing settles against its absence.
    #[test]
    fn a_stalled_feed_holds_the_watermark() {
        let t0 = Instant::now();
        let mut join = join(usize::MAX, None);
        both(&mut join, 0, 1_000, "a", 1, t0);
        let stalled = t0 + Duration::from_secs(100);
        join.observe(
            row(Side::Node, 0, 70_000, "b", 2),
            t0 + Duration::from_secs(40),
        );
        join.observe(row(Side::Node, 0, 130_000, "c", 3), stalled);

        let report = join.settle(stalled);
        assert_eq!(report.feed_watermarks_ms, [Some(130_000), Some(1_000)]);
        assert_eq!(report.watermark_ms, Some(1_000));
        assert_eq!(report.mapping_outcomes, BTreeMap::new());
        assert_eq!(report.pending_mappings, 3);

        let resumed = stalled + Duration::from_secs(1);
        join.observe(row(Side::Personhog, 0, 70_000, "b", 2), resumed);
        join.observe(row(Side::Personhog, 0, 130_000, "c", 3), resumed);
        let report = join.settle(resumed);
        assert_eq!(report.watermark_ms, Some(130_000));
        assert_eq!(mapping_outcomes(&report), vec![(MappingOutcome::Agree, 1)]);
        assert_eq!(report.pending_mappings, 2);
    }

    // A counterpart may predate the readers; the first grace is not judged.
    #[test]
    fn the_warmup_drops_entries_whose_counterparts_may_predate_the_readers() {
        let t0 = Instant::now();
        let mut join = join_with(usize::MAX, None, GRACE);
        join.observe(row(Side::Node, 0, 1_000, "x", 1), t0);
        join.observe(row(Side::Personhog, 0, 1_000, "y", 2), t0);
        let report = join.settle(t0);
        assert_eq!(report.watermark_ms, Some(1_000));

        both(&mut join, 0, 130_000, "z", 3, t0);
        let report = join.settle(t0);
        assert_eq!(report.warmup_evictions, 2);
        assert_eq!(report.mapping_outcomes, BTreeMap::new());
        assert_eq!(report.pending_mappings, 1);
        assert_eq!(join.node.mapping_count(), 1);
        assert_eq!(join.personhog.mapping_count(), 1);
    }

    // Evicted entries never had their grace, so they get no verdict.
    #[test]
    fn the_cap_evicts_the_oldest_entries_without_settling_them() {
        let t0 = Instant::now();
        let mut join = join(3, None);
        join.observe(row(Side::Node, 0, 3_000, "newest", 1), t0);
        join.observe(row(Side::Node, 0, 1_000, "oldest", 2), t0);
        join.observe(merge(Side::Node, 0, 2_000, 7, 8), t0);
        join.observe(row(Side::Personhog, 0, 3_000, "newest", 1), t0);

        let report = join.settle(t0);
        assert_eq!(report.mapping_outcomes, BTreeMap::new());
        assert_eq!(report.overflow_evictions, 1);
        assert_eq!(report.pending_mappings, 1);
        assert_eq!(report.pending_merges, 1);
        assert!(join
            .mappings
            .contains_key(&DistinctIdKey::new(TEAM, "newest")));
        assert_eq!(join.node.mapping_count(), 1);

        // A key's history counts: three versions of one key weigh three rows.
        let mut hot = Join::new(
            JoinConfig {
                grace: GRACE,
                idle_partition: IDLE,
                max_entries: 4,
                teams: None,
                mapping_lag: MAPPING_LAG,
                warmup: Duration::ZERO,
                person_ignored_properties: HashSet::new(),
            },
            SampleRing::new(10),
        );
        for (version, person) in [(0, 1), (1, 2), (2, 3)] {
            let at = 1_000 + version * 100;
            hot.observe(
                row_of_team(TEAM, Side::Node, 0, at, "a", person, version),
                t0,
            );
        }
        hot.observe(row(Side::Personhog, 0, 1_000, "a", 3), t0);
        hot.observe(row(Side::Node, 0, 5_000, "b", 4), t0);
        let report = hot.settle(t0);
        assert_eq!(report.overflow_evictions, 1);
        assert!(hot.mappings.contains_key(&DistinctIdKey::new(TEAM, "b")));
        assert_eq!(hot.node.row_count(), 1);
    }

    // The lag keeps the rows a merge's verdict reads when they are older
    // than the merge; the order keeps them when both fall due in one sweep.
    #[test]
    fn mappings_outlive_the_merges_they_explain() {
        let t0 = Instant::now();
        let mut join = join(usize::MAX, None);
        join.observe(
            row_of_team(TEAM, Side::Personhog, 0, 1_000, "anon", 1, 0),
            t0,
        );
        join.observe(
            row_of_team(TEAM, Side::Personhog, 0, 1_000, "anon", 2, 1),
            t0,
        );
        join.observe(merge(Side::Personhog, 0, 1_500, 1, 2), t0);
        join.observe(row(Side::Node, 0, 1_000, "anon", 2), t0);
        join.observe(row_of_team(TEAM, Side::Personhog, 0, 1_000, "b", 3, 0), t0);
        join.observe(row_of_team(TEAM, Side::Personhog, 0, 1_000, "b", 4, 1), t0);
        join.observe(merge(Side::Personhog, 0, 1_500, 3, 4), t0);
        join.observe(row(Side::Node, 0, 1_000, "b", 4), t0);

        // The rows of `anon` are due for a lag of zero, the merge is not yet.
        both(&mut join, 0, 61_200, "w1", 9, t0);
        let report = join.settle(t0);
        assert_eq!(report.merge_outcomes, BTreeMap::new());
        assert_eq!(report.mapping_outcomes, BTreeMap::new());

        both(&mut join, 0, 61_600, "w2", 9, t0);
        let report = join.settle(t0);
        assert_eq!(
            report.merge_outcomes,
            BTreeMap::from([(SurvivorOutcome::PersonhogStub, 2)])
        );
        assert_eq!(report.mapping_outcomes, BTreeMap::new());

        both(&mut join, 0, 70_000, "w3", 9, t0);
        let report = join.settle(t0);
        assert_eq!(mapping_outcomes(&report), vec![(MappingOutcome::Agree, 2)]);
    }

    // Node merges A into C directly; personhog goes through its own B, whose
    // merge is older and settles first. A's verdict still reaches C.
    #[test]
    fn merge_edges_outlive_the_merges_that_depend_on_them() {
        let t0 = Instant::now();
        let mut join = join(usize::MAX, None);
        join.observe(merge(Side::Node, 0, 1_000, 1, 3), t0);
        join.observe(merge(Side::Personhog, 0, 500, 2, 3), t0);
        join.observe(merge(Side::Personhog, 0, 1_000, 1, 2), t0);

        both(&mut join, 0, 60_600, "w1", 9, t0);
        let report = join.settle(t0);
        assert_eq!(report.merge_outcomes.values().sum::<u64>(), 1);
        assert!(!report
            .merge_outcomes
            .contains_key(&SurvivorOutcome::Mismatch));
        assert_eq!(report.pending_merges, 1);
        assert_eq!(
            join.personhog.merged_into(&PersonKey::new(TEAM, uuid(2))),
            Some(uuid(3))
        );

        both(&mut join, 0, 61_100, "w2", 9, t0);
        let report = join.settle(t0);
        assert_eq!(
            report.merge_outcomes,
            BTreeMap::from([(SurvivorOutcome::Agree, 1)])
        );
        assert_eq!(join.node.merge_count() + join.personhog.merge_count(), 0);
        assert!(join.merges.is_empty());
        assert!(join.target_refs.is_empty());
    }

    #[test]
    fn observe_reports_filters_ties_conflicts_and_placement() {
        let t0 = Instant::now();
        let mut join = join(usize::MAX, Some(HashSet::from([TEAM])));
        assert!(
            join.observe(row_of_team(TEAM + 1, Side::Node, 0, 1_000, "f", 1, 0), t0)
                .filtered
        );
        assert_eq!(join.mappings.len(), 0);

        assert_eq!(
            join.observe(row(Side::Node, 0, 1_000, "d", 1), t0),
            ObserveReport::default()
        );
        assert_eq!(
            join.observe(row(Side::Node, 0, 1_000, "d", 2), t0)
                .version_tie,
            Some(Side::Node)
        );

        // Placement is only judged once the topic's partition count is known.
        let key = format!("{TEAM}:{}", uuid(7));
        let expected = partition_for_key(key.as_bytes(), 64) as i32;
        assert_eq!(
            join.observe(merge(Side::Node, expected, 1_000, 7, 8), t0)
                .placement,
            None
        );
        join.observe(
            Event::Assigned {
                topic: topic(Side::Personhog, Kind::MergeEvents),
                partitions: 64,
            },
            t0,
        );
        assert_eq!(
            join.observe(merge(Side::Personhog, expected, 1_000, 7, 8), t0)
                .placement,
            Some((Side::Personhog, true))
        );
        let report = join.observe(merge(Side::Personhog, expected + 1, 1_000, 7, 9), t0);
        assert_eq!(report.placement, Some((Side::Personhog, false)));
        assert_eq!(report.merge_conflict, Some(Side::Personhog));

        let old = (10..).find(|n| {
            let key = format!("{TEAM}:{}", uuid(*n));
            partition_for_key(key.as_bytes(), 64) != partition_for_key(key.as_bytes(), 128)
        });
        let old = old.expect("some key lands differently on 64 and 128 partitions");
        let key = format!("{TEAM}:{}", uuid(old));
        let expected = partition_for_key(key.as_bytes(), 128) as i32;
        join.observe(
            Event::Assigned {
                topic: topic(Side::Personhog, Kind::MergeEvents),
                partitions: 128,
            },
            t0,
        );
        assert_eq!(
            join.observe(merge(Side::Personhog, expected, 1_000, old, 11), t0)
                .placement,
            Some((Side::Personhog, true))
        );
    }
}
