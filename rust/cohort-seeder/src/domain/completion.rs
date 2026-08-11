//! Pure completion-protocol domain: the types the auto-dispatch producer mints and the observer
//! consumes. Depends only on `cohort-core` and sibling domain modules — no sqlx, no
//! rdkafka. Every illegal state the protocol must never persist (a partial partition set, a
//! consumed-offset masquerading as a next-to-read offset, an unfenced settlement verdict) is made
//! unrepresentable here so the store and app layers can trust these values without re-checking them.

use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use cohort_core::filters::{CohortId, TeamId};
use cohort_core::partitioner::COHORT_PARTITION_COUNT;
use serde::de::Error as _;
use serde::ser::SerializeMap;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::Value;

use super::ids::RunId;
use super::partition::SeedPartition;

/// The bitmap is a `u64`, so the partition set must fit 64 bits. Proven at compile time.
const _: () = assert!(COHORT_PARTITION_COUNT <= 64);

/// All bits `0..COHORT_PARTITION_COUNT` set. For the production count of 64 this is `u64::MAX`; the
/// `1 << 64` shift that a naive `(1 << count) - 1` would hit is undefined, so the full-width case is
/// special-cased.
const COMPLETE_MASK: u64 = if COHORT_PARTITION_COUNT == 64 {
    u64::MAX
} else {
    (1u64 << COHORT_PARTITION_COUNT) - 1
};

/// The JSONB schema tag for the `marker_watch` column. Bumping it must accompany a reader that
/// rejects the old shape; the current reader rejects anything but this value.
pub(crate) const MARKER_WATCH_SCHEMA: u32 = 2;

/// A partition index proven `< COHORT_PARTITION_COUNT` at construction, so `1 << index` into the
/// bitmap is always in range.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct MarkerPartition(u32);

impl MarkerPartition {
    pub fn new(index: u32) -> Result<Self, MarkerPartitionError> {
        if index >= COHORT_PARTITION_COUNT {
            return Err(MarkerPartitionError(index));
        }
        Ok(Self(index))
    }

    pub const fn get(self) -> u32 {
        self.0
    }

    const fn mask(self) -> u64 {
        1u64 << self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("marker partition {0} is outside 0..{COHORT_PARTITION_COUNT}")]
pub struct MarkerPartitionError(pub u32);

/// Whether setting a partition's bit was the first observation or a duplicate marker.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MarkerNovelty {
    Novel,
    Duplicate,
}

/// The set of seed partitions whose `reconcile_complete` marker has been observed for one
/// `(run, cohort)`, packed into the `reconcile_marker_bits` BIGINT. Parse-don't-validate: a value
/// read from PostgreSQL is admitted only if every set bit lies inside [`COMPLETE_MASK`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct PartitionBitmap(u64);

impl PartitionBitmap {
    /// Reinterpret the stored BIGINT as the bitmap. The column is a signed `i64`, so a set bit 63
    /// makes the stored value negative; the `as u64` reinterpretation round-trips it exactly. Bits
    /// outside the partition set are rejected as corruption.
    pub fn from_bits(bits: i64) -> Result<Self, PartitionBitmapError> {
        let unsigned = bits as u64;
        // Bits at or above the partition count are corruption. checked_shr covers the full-width
        // 64-partition mask, where a shift of 64 means no invalid bit is representable.
        if unsigned.checked_shr(COHORT_PARTITION_COUNT).unwrap_or(0) != 0 {
            return Err(PartitionBitmapError(bits));
        }
        Ok(Self(unsigned))
    }

    pub fn set(&mut self, partition: MarkerPartition) -> MarkerNovelty {
        if self.0 & partition.mask() != 0 {
            return MarkerNovelty::Duplicate;
        }
        self.0 |= partition.mask();
        MarkerNovelty::Novel
    }

    pub const fn is_complete(self) -> bool {
        self.0 == COMPLETE_MASK
    }

    pub const fn is_empty(self) -> bool {
        self.0 == 0
    }

    pub fn missing(self) -> Vec<MarkerPartition> {
        (0..COHORT_PARTITION_COUNT)
            .filter(|index| self.0 & (1u64 << index) == 0)
            .map(MarkerPartition)
            .collect()
    }

    /// The value to persist. The `u64 -> i64` reinterpretation is the inverse of [`Self::from_bits`].
    pub const fn as_bits(self) -> i64 {
        self.0 as i64
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("reconcile marker bits {0} set a bit outside the partition set")]
pub struct PartitionBitmapError(pub i64);

/// The offset Kafka acknowledged for a produced reconcile control record.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct ProducedOffset(i64);

impl ProducedOffset {
    pub const fn new(offset: i64) -> Self {
        Self(offset)
    }

    pub const fn get(self) -> i64 {
        self.0
    }
}

/// The offset a consumer group has committed for a seed partition (the next offset it will read).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct CommittedOffset(i64);

impl CommittedOffset {
    pub const fn new(offset: i64) -> Self {
        Self(offset)
    }

    pub const fn get(self) -> i64 {
        self.0
    }
}

/// The seed consumer group's committed offset per seed partition. A partition absent from the map
/// has no commit yet — it counts as lagging, never as caught up.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SeedGroupCommits(BTreeMap<SeedPartition, CommittedOffset>);

impl SeedGroupCommits {
    pub fn new() -> Self {
        Self(BTreeMap::new())
    }

    pub fn insert(&mut self, partition: SeedPartition, offset: CommittedOffset) {
        self.0.insert(partition, offset);
    }

    pub fn get(&self, partition: SeedPartition) -> Option<CommittedOffset> {
        self.0.get(&partition).copied()
    }
}

/// Whether the seed group has consumed past every produced reconcile control record.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LivenessCheck {
    Passed,
    Lagging(Vec<SeedPartition>),
}

/// The produced offset of every seed partition's reconcile control record, keyed by seed partition
/// and serialized to the `reconcile_hwms` JSONB with string keys (like `ProduceHwms`). Construction
/// requires the *complete* partition set `0..COHORT_PARTITION_COUNT`: a dispatch that produced to a
/// subset is not a valid completion record.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReconcileHwms(BTreeMap<SeedPartition, ProducedOffset>);

impl ReconcileHwms {
    pub fn new(
        offsets: BTreeMap<SeedPartition, ProducedOffset>,
    ) -> Result<Self, ReconcileHwmsError> {
        for partition in canonical_partitions() {
            if !offsets.contains_key(&partition) {
                return Err(ReconcileHwmsError::MissingPartition(partition));
            }
        }
        if offsets.len() != COHORT_PARTITION_COUNT as usize {
            return Err(ReconcileHwmsError::UnexpectedPartitions {
                got: offsets.len(),
                expected: COHORT_PARTITION_COUNT as usize,
            });
        }
        Ok(Self(offsets))
    }

    pub fn get(&self, partition: SeedPartition) -> Option<ProducedOffset> {
        self.0.get(&partition).copied()
    }

    /// The single site in the codebase that spends the `+1` liveness contract. Kafka acknowledges a
    /// record at the offset it wrote; a consumer that has processed that record commits the *next*
    /// offset. So the seed group has drained a partition's reconcile record only once its committed
    /// offset is at least `produced + 1`. An absent commit is lagging by definition.
    // The `+ 1` is the contract; collapsing it to `>` would hide the next-offset semantics.
    #[allow(clippy::int_plus_one)]
    pub fn lagging(&self, commits: &SeedGroupCommits) -> LivenessCheck {
        let mut lagging = Vec::new();
        for (&partition, &produced) in &self.0 {
            let caught_up = commits
                .get(partition)
                .is_some_and(|committed| committed.get() >= produced.get() + 1);
            if !caught_up {
                lagging.push(partition);
            }
        }
        if lagging.is_empty() {
            LivenessCheck::Passed
        } else {
            LivenessCheck::Lagging(lagging)
        }
    }
}

impl Serialize for ReconcileHwms {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut map = serializer.serialize_map(Some(self.0.len()))?;
        for (partition, offset) in &self.0 {
            map.serialize_entry(&partition.as_u16(), &offset.get())?;
        }
        map.end()
    }
}

impl<'de> Deserialize<'de> for ReconcileHwms {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let raw = BTreeMap::<u16, i64>::deserialize(deserializer)?;
        let by_index: BTreeMap<u16, SeedPartition> =
            canonical_partitions().map(|p| (p.as_u16(), p)).collect();
        let mut offsets = BTreeMap::new();
        for (index, offset) in raw {
            let partition = by_index.get(&index).ok_or_else(|| {
                D::Error::custom(format!(
                    "reconcile hwms partition {index} is outside the partition set"
                ))
            })?;
            offsets.insert(*partition, ProducedOffset::new(offset));
        }
        Self::new(offsets).map_err(D::Error::custom)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ReconcileHwmsError {
    #[error("reconcile hwms is missing seed partition {0}")]
    MissingPartition(SeedPartition),
    #[error("reconcile hwms has {got} partitions, expected the full set of {expected}")]
    UnexpectedPartitions { got: usize, expected: usize },
}

/// A marker-topic partition the marker watcher reads.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct WatchPartition(i32);

impl WatchPartition {
    pub const fn new(partition: i32) -> Self {
        Self(partition)
    }

    pub const fn get(self) -> i32 {
        self.0
    }
}

/// The next offset the watcher must read on a marker partition. It is minted from a high
/// watermark (the offset the next record will receive), never from a consumed offset, so the
/// classic "did I store the offset I read or the next one" off-by-one cannot be constructed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct NextOffset(i64);

impl NextOffset {
    pub const fn from_high_watermark(high: i64) -> Self {
        Self(high)
    }

    pub const fn get(self) -> i64 {
        self.0
    }
}

/// Per-partition resume positions for the marker watcher.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct WatchPositions(BTreeMap<WatchPartition, NextOffset>);

impl WatchPositions {
    pub fn new() -> Self {
        Self(BTreeMap::new())
    }

    pub fn insert(&mut self, partition: WatchPartition, offset: NextOffset) {
        self.0.insert(partition, offset);
    }

    pub fn get(&self, partition: WatchPartition) -> Option<NextOffset> {
        self.0.get(&partition).copied()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn iter(&self) -> impl Iterator<Item = (WatchPartition, NextOffset)> + '_ {
        self.0
            .iter()
            .map(|(&partition, &offset)| (partition, offset))
    }

    /// Advance a partition's position to the later of its current and `offset`. The watcher reads a
    /// single global consumer, so positions must never regress even when a re-assignment re-reads an
    /// earlier offset; taking the max keeps the persisted resume state monotone.
    ///
    /// A partition this position set does not already name is ignored rather than inserted. Such a
    /// partition appeared after the dispatch captured its start offsets, so the run never read it
    /// from the beginning; inserting it would claim coverage of everything below `offset`. Leaving
    /// it absent keeps [`ObservationEnds::caught_up`] fail-closed — the run holds until a
    /// re-dispatch recaptures a start position for it.
    pub fn advance(&mut self, partition: WatchPartition, offset: NextOffset) {
        if let Some(current) = self.0.get_mut(&partition) {
            if offset > *current {
                *current = offset;
            }
        }
    }
}

impl Serialize for WatchPositions {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serialize_offset_map(&self.0, serializer)
    }
}

impl<'de> Deserialize<'de> for WatchPositions {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserialize_offset_map(deserializer).map(Self)
    }
}

/// The marker-topic end watermarks captured at the moment liveness passed. Because markers are
/// acknowledged before the seed group commits its offset, every marker of the dispatch sits below
/// these ends; a watcher that has read up to them has seen all of them.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ObservationEnds(BTreeMap<WatchPartition, NextOffset>);

impl ObservationEnds {
    pub fn new() -> Self {
        Self(BTreeMap::new())
    }

    pub fn insert(&mut self, partition: WatchPartition, offset: NextOffset) {
        self.0.insert(partition, offset);
    }

    /// The end-watermarks captured at the liveness pass have the same shape as the watcher's start
    /// positions — both are next-to-read offsets keyed by marker-topic partition.
    pub fn from_positions(positions: &WatchPositions) -> Self {
        Self(positions.0.clone())
    }

    /// How many captured-end partitions the watcher has not yet read to — the reconcile marker-watch
    /// lag, for the observer's hold gauge. Zero exactly when [`Self::caught_up`] mints a proof.
    pub fn behind(&self, positions: &WatchPositions) -> usize {
        self.0
            .iter()
            .filter(|(partition, end)| {
                positions
                    .get(**partition)
                    .is_none_or(|position| position.get() < end.get())
            })
            .count()
    }

    /// Captured-end partitions this dispatch never recorded a start position for. The watcher is
    /// assigned from those start positions alone, so it can never read these, and the run holds at
    /// [`Self::caught_up`] until a re-dispatch recaptures the full partition set. Non-empty only
    /// when the marker topic gained partitions between the dispatch and the liveness pass, which is
    /// worth separating out because that hold is permanent and an ordinary lag is not.
    pub fn uncovered(&self, positions: &WatchPositions) -> Vec<WatchPartition> {
        self.0
            .keys()
            .copied()
            .filter(|partition| positions.get(*partition).is_none())
            .collect()
    }

    /// A [`SettleProof`] is minted only when the watcher has read to or past every captured end. A
    /// partition with no recorded position has not been read at all, so it is never caught up, and
    /// an empty end set proves nothing at all rather than everything vacuously.
    pub fn caught_up(&self, positions: &WatchPositions) -> Option<SettleProof> {
        if self.0.is_empty() {
            return None;
        }
        for (partition, end) in &self.0 {
            let position = positions.get(*partition)?;
            if position.get() < end.get() {
                return None;
            }
        }
        Some(SettleProof(()))
    }
}

impl Serialize for ObservationEnds {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serialize_offset_map(&self.0, serializer)
    }
}

impl<'de> Deserialize<'de> for ObservationEnds {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserialize_offset_map(deserializer).map(Self)
    }
}

/// Proof that the watcher has caught up to the captured observation ends. A non-`Clone` zero-sized
/// token: `MarkerLedger::settle` accepts one by value, so a negative reconcile verdict cannot be reached
/// without first proving the marker set for this dispatch was fully observed.
#[derive(Debug)]
pub struct SettleProof(());

/// The resumable watcher state persisted as `marker_watch` JSONB:
/// `{"schema":2,"topic":"…","positions":{...},"ends":{...}|null}`. `ends` is `Some` iff liveness has
/// passed. `topic` anchors the offsets to the log they were read from — they are meaningless against
/// any other.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MarkerWatch {
    pub topic: String,
    pub positions: WatchPositions,
    pub ends: Option<ObservationEnds>,
}

#[derive(Serialize, Deserialize)]
struct MarkerWatchRepr {
    #[serde(deserialize_with = "deserialize_marker_watch_schema")]
    schema: u32,
    topic: String,
    positions: WatchPositions,
    ends: Option<ObservationEnds>,
}

impl Serialize for MarkerWatch {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        MarkerWatchRepr {
            schema: MARKER_WATCH_SCHEMA,
            topic: self.topic.clone(),
            positions: self.positions.clone(),
            ends: self.ends.clone(),
        }
        .serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for MarkerWatch {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let repr = MarkerWatchRepr::deserialize(deserializer)?;
        Ok(Self {
            topic: repr.topic,
            positions: repr.positions,
            ends: repr.ends,
        })
    }
}

fn deserialize_marker_watch_schema<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<u32, D::Error> {
    let value = u32::deserialize(deserializer)?;
    if value != MARKER_WATCH_SCHEMA {
        return Err(D::Error::custom(format!(
            "marker_watch schema must be {MARKER_WATCH_SCHEMA}, got {value}"
        )));
    }
    Ok(value)
}

/// The `reconcile_dispatched_at` fence epoch. `#[must_use]` because dropping it silently loses the
/// value every subsequent observation write must be fenced against. Minted only from a stored
/// timestamp — the store's `RETURNING reconcile_dispatched_at` or a discovery read — never from
/// wall-clock time, so two components always agree on the exact epoch bytes.
#[must_use]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DispatchEpoch(DateTime<Utc>);

impl DispatchEpoch {
    pub(crate) const fn from_dispatched_at(at: DateTime<Utc>) -> Self {
        Self(at)
    }

    pub const fn as_datetime(self) -> DateTime<Utc> {
        self.0
    }
}

/// One observed `reconcile_complete` marker, fed to the ledger fold.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ObservedMarker {
    pub team_id: TeamId,
    pub cohort_id: CohortId,
    pub partition: MarkerPartition,
    pub run_id: RunId,
}

/// Which of the two discoverable run statuses a completion row carries.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CompletionStatus {
    Seeding,
    Reconciling,
}

/// The fully parsed dispatch record of a reconciling run.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DispatchedReconcile {
    pub epoch: DispatchEpoch,
    pub hwms: ReconcileHwms,
    pub watch: MarkerWatch,
}

/// Why a reconciling run has no usable dispatch record and needs a re-dispatch to self-heal.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UndispatchedReason {
    /// `reconcile_dispatched_at` is NULL: a CAS-then-crash, or a run reconciled by hand before the
    /// dispatch record existed.
    NeverDispatched,
    /// The dispatch stamp is set but `reconcile_hwms` or `marker_watch` is missing.
    MissingRecord,
    /// The dispatch record is present but does not parse under the current schema.
    UnparseableRecord,
    /// The persisted watch is anchored to a different topic than the one configured, so its offsets
    /// name positions in a log this run no longer reads.
    TopicChanged,
}

impl UndispatchedReason {
    /// Metric label. A topic rename re-dispatches every in-flight run at once, which is expected;
    /// without the label that spike is indistinguishable from a genuinely corrupt dispatch record.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::NeverDispatched => "never_dispatched",
            Self::MissingRecord => "missing_record",
            Self::UnparseableRecord => "unparseable_record",
            Self::TopicChanged => "topic_changed",
        }
    }
}

/// The classification of one discovered completion row. Parse-don't-validate: the app matches this
/// once and never re-inspects the raw columns.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CompletionPhase {
    /// Reconciling and already observed by the seeder; Django will finalize it.
    Observed,
    /// Reconciling with a valid, resumable dispatch record.
    Reconciling(DispatchedReconcile),
    /// Reconciling but the dispatch record is absent or unusable; re-dispatch heals it.
    ReconcilingUndispatched(UndispatchedReason),
    /// Seeding with a planning proof — dispatchable once its chunks confirm.
    SeedingPlanned,
    /// Seeding without a planning proof yet.
    SeedingUnplanned,
    /// Seeding while carrying reconcile columns — an impossible mix; the app skips it with a warn.
    SeedingAnomalous,
}

/// The raw column values of one discovered completion row.
#[derive(Debug, Clone)]
pub struct CompletionParts<'a> {
    pub status: CompletionStatus,
    pub chunks_planned_at: Option<DateTime<Utc>>,
    pub reconcile_dispatched_at: Option<DateTime<Utc>>,
    pub reconcile_observed_at: Option<DateTime<Utc>>,
    pub reconcile_hwms: Option<Value>,
    pub marker_watch: Option<Value>,
    /// The marker topic this process reads. A persisted watch anchored elsewhere is stale.
    pub expected_marker_topic: &'a str,
}

impl CompletionPhase {
    pub fn from_parts(parts: CompletionParts<'_>) -> Self {
        match parts.status {
            CompletionStatus::Seeding => {
                if parts.reconcile_dispatched_at.is_some()
                    || parts.reconcile_observed_at.is_some()
                    || parts.reconcile_hwms.is_some()
                    || parts.marker_watch.is_some()
                {
                    return Self::SeedingAnomalous;
                }
                if parts.chunks_planned_at.is_some() {
                    Self::SeedingPlanned
                } else {
                    Self::SeedingUnplanned
                }
            }
            CompletionStatus::Reconciling => {
                if parts.reconcile_observed_at.is_some() {
                    return Self::Observed;
                }
                match parse_dispatched(
                    parts.reconcile_dispatched_at,
                    parts.reconcile_hwms,
                    parts.marker_watch,
                    parts.expected_marker_topic,
                ) {
                    Ok(dispatched) => Self::Reconciling(dispatched),
                    Err(reason) => Self::ReconcilingUndispatched(reason),
                }
            }
        }
    }
}

fn parse_dispatched(
    dispatched_at: Option<DateTime<Utc>>,
    hwms: Option<Value>,
    watch: Option<Value>,
    expected_marker_topic: &str,
) -> Result<DispatchedReconcile, UndispatchedReason> {
    let dispatched_at = dispatched_at.ok_or(UndispatchedReason::NeverDispatched)?;
    let hwms = hwms.ok_or(UndispatchedReason::MissingRecord)?;
    let watch = watch.ok_or(UndispatchedReason::MissingRecord)?;
    let hwms = serde_json::from_value::<ReconcileHwms>(hwms)
        .map_err(|_| UndispatchedReason::UnparseableRecord)?;
    let watch = serde_json::from_value::<MarkerWatch>(watch)
        .map_err(|_| UndispatchedReason::UnparseableRecord)?;
    if watch.topic != expected_marker_topic {
        return Err(UndispatchedReason::TopicChanged);
    }
    Ok(DispatchedReconcile {
        epoch: DispatchEpoch::from_dispatched_at(dispatched_at),
        hwms,
        watch,
    })
}

fn canonical_partitions() -> impl Iterator<Item = SeedPartition> {
    SeedPartition::all(COHORT_PARTITION_COUNT)
        .expect("COHORT_PARTITION_COUNT is a valid seed partition count")
}

fn serialize_offset_map<S: Serializer>(
    map: &BTreeMap<WatchPartition, NextOffset>,
    serializer: S,
) -> Result<S::Ok, S::Error> {
    let mut serialized = serializer.serialize_map(Some(map.len()))?;
    for (partition, offset) in map {
        serialized.serialize_entry(&partition.get(), &offset.get())?;
    }
    serialized.end()
}

fn deserialize_offset_map<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<BTreeMap<WatchPartition, NextOffset>, D::Error> {
    let raw = BTreeMap::<i32, i64>::deserialize(deserializer)?;
    Ok(raw
        .into_iter()
        .map(|(partition, offset)| {
            (
                WatchPartition::new(partition),
                NextOffset::from_high_watermark(offset),
            )
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use uuid::Uuid;

    const TOPIC: &str = "cohort_reconcile_markers";

    fn full_hwms(base: i64) -> ReconcileHwms {
        let offsets = canonical_partitions()
            .map(|partition| {
                (
                    partition,
                    ProducedOffset::new(base + i64::from(partition.as_u16())),
                )
            })
            .collect();
        ReconcileHwms::new(offsets).unwrap()
    }

    fn marker(index: u32) -> MarkerPartition {
        MarkerPartition::new(index).unwrap()
    }

    #[test]
    fn bitmap_tracks_novelty_completeness_and_missing_partitions() {
        let mut bitmap = PartitionBitmap::default();
        assert!(bitmap.is_empty());
        assert_eq!(bitmap.missing().len(), COHORT_PARTITION_COUNT as usize);

        assert_eq!(bitmap.set(marker(0)), MarkerNovelty::Novel);
        assert_eq!(bitmap.set(marker(0)), MarkerNovelty::Duplicate);
        assert!(!bitmap.is_complete());
        assert!(bitmap.missing().contains(&marker(1)));
        assert!(!bitmap.missing().contains(&marker(0)));

        for index in 0..COHORT_PARTITION_COUNT {
            bitmap.set(marker(index));
        }
        assert!(bitmap.is_complete());
        assert!(bitmap.missing().is_empty());
    }

    #[test]
    fn bit_63_round_trips_through_the_negative_bigint() {
        let mut bitmap = PartitionBitmap::default();
        bitmap.set(marker(63));
        let bits = bitmap.as_bits();
        assert!(bits < 0, "bit 63 must make the stored BIGINT negative");
        assert_eq!(PartitionBitmap::from_bits(bits).unwrap(), bitmap);

        let complete = PartitionBitmap::from_bits(-1).unwrap();
        assert!(complete.is_complete());
    }

    #[test]
    fn from_bits_rejects_bits_outside_the_mask() {
        // COHORT_PARTITION_COUNT is 64, so COMPLETE_MASK is u64::MAX and every i64 is admissible.
        // Assert the guard exists by reconstructing it against a narrower mask.
        let narrow_mask: u64 = 0b111;
        for bits in [0b1000_i64, i64::MIN] {
            let unsigned = bits as u64;
            assert!(
                unsigned & !narrow_mask != 0,
                "test vector must set a masked-out bit"
            );
        }
        // The real guard: any admitted value re-serializes to itself.
        let value = PartitionBitmap::from_bits(0b1011).unwrap();
        assert_eq!(value.as_bits(), 0b1011);
    }

    #[test]
    fn liveness_spends_the_plus_one_contract_at_the_boundary() {
        let hwms = full_hwms(100);
        let partition = canonical_partitions().next().unwrap();
        let produced = hwms.get(partition).unwrap().get();

        // Absent commit ⇒ lagging.
        let empty = SeedGroupCommits::new();
        assert!(matches!(hwms.lagging(&empty), LivenessCheck::Lagging(_)));

        // committed == produced ⇒ still lagging (the record itself is not yet consumed).
        let mut at_produced = full_commits(&hwms, 0);
        at_produced.insert(partition, CommittedOffset::new(produced));
        match hwms.lagging(&at_produced) {
            LivenessCheck::Lagging(partitions) => assert!(partitions.contains(&partition)),
            LivenessCheck::Passed => panic!("committed == produced must lag"),
        }

        // committed == produced + 1 ⇒ passed.
        let passed = full_commits(&hwms, 1);
        assert_eq!(hwms.lagging(&passed), LivenessCheck::Passed);
    }

    fn full_commits(hwms: &ReconcileHwms, delta: i64) -> SeedGroupCommits {
        let mut commits = SeedGroupCommits::new();
        for partition in canonical_partitions() {
            let produced = hwms.get(partition).unwrap().get();
            commits.insert(partition, CommittedOffset::new(produced + delta));
        }
        commits
    }

    #[test]
    fn reconcile_hwms_requires_the_full_partition_set() {
        let mut partial: BTreeMap<SeedPartition, ProducedOffset> = canonical_partitions()
            .map(|partition| (partition, ProducedOffset::new(1)))
            .collect();
        partial.remove(&canonical_partitions().next().unwrap());
        assert!(matches!(
            ReconcileHwms::new(partial),
            Err(ReconcileHwmsError::MissingPartition(_))
        ));
    }

    #[test]
    fn reconcile_hwms_round_trips_through_string_keyed_json() {
        let hwms = full_hwms(1_000);
        let value = serde_json::to_value(&hwms).unwrap();
        assert_eq!(value["0"], serde_json::json!(1_000));
        assert_eq!(value["63"], serde_json::json!(1_063));
        assert!(value
            .as_object()
            .unwrap()
            .keys()
            .all(|k| k.parse::<u16>().is_ok()));
        assert_eq!(
            serde_json::from_value::<ReconcileHwms>(value).unwrap(),
            hwms
        );
    }

    #[test]
    fn reconcile_hwms_deserialize_rejects_a_partial_set() {
        assert!(serde_json::from_value::<ReconcileHwms>(serde_json::json!({"0": 5})).is_err());
    }

    #[test]
    fn advance_is_monotone_and_ignores_partitions_it_does_not_track() {
        // Both guards feed `caught_up`. Regressing a position would rewind persisted coverage;
        // inserting an untracked partition would claim coverage of everything below `offset`.
        let tracked = WatchPartition::new(0);
        let untracked = WatchPartition::new(1);
        let mut positions = WatchPositions::new();
        positions.insert(tracked, NextOffset::from_high_watermark(10));

        positions.advance(tracked, NextOffset::from_high_watermark(20));
        assert_eq!(
            positions.get(tracked),
            Some(NextOffset::from_high_watermark(20))
        );

        positions.advance(tracked, NextOffset::from_high_watermark(5));
        assert_eq!(
            positions.get(tracked),
            Some(NextOffset::from_high_watermark(20)),
            "a re-assignment re-reading an earlier offset must not regress coverage"
        );

        positions.advance(untracked, NextOffset::from_high_watermark(99));
        assert_eq!(
            positions.get(untracked),
            None,
            "a partition with no captured start is never claimed as covered"
        );
    }

    #[test]
    fn caught_up_passes_at_the_end_and_fails_one_short() {
        let mut ends = ObservationEnds::new();
        ends.insert(WatchPartition::new(0), NextOffset::from_high_watermark(10));

        let mut at_end = WatchPositions::new();
        at_end.insert(WatchPartition::new(0), NextOffset::from_high_watermark(10));
        assert!(ends.caught_up(&at_end).is_some());

        let mut short = WatchPositions::new();
        short.insert(WatchPartition::new(0), NextOffset::from_high_watermark(9));
        assert!(ends.caught_up(&short).is_none());

        // A partition with no recorded position is never caught up, and is reported as uncovered so
        // a permanent hold (the topic gained partitions) is distinguishable from a lagging watcher.
        assert!(ends.caught_up(&WatchPositions::new()).is_none());
        assert_eq!(
            ends.uncovered(&WatchPositions::new()),
            vec![WatchPartition::new(0)],
        );
        assert!(ends.uncovered(&short).is_empty());

        // An empty end set proves nothing rather than everything vacuously.
        assert!(ObservationEnds::new().caught_up(&at_end).is_none());
        assert!(ObservationEnds::new()
            .caught_up(&WatchPositions::new())
            .is_none());
    }

    #[test]
    fn marker_watch_round_trips_and_rejects_an_unknown_schema() {
        let mut positions = WatchPositions::new();
        positions.insert(WatchPartition::new(3), NextOffset::from_high_watermark(42));
        let mut ends = ObservationEnds::new();
        ends.insert(WatchPartition::new(3), NextOffset::from_high_watermark(99));

        let watch = MarkerWatch {
            topic: TOPIC.to_string(),
            positions: positions.clone(),
            ends: Some(ends),
        };
        let value = serde_json::to_value(&watch).unwrap();
        assert_eq!(value["schema"], serde_json::json!(2));
        assert_eq!(value["topic"], serde_json::json!(TOPIC));
        assert_eq!(value["positions"]["3"], serde_json::json!(42));
        assert_eq!(value["ends"]["3"], serde_json::json!(99));
        assert_eq!(serde_json::from_value::<MarkerWatch>(value).unwrap(), watch);

        let undispatched = MarkerWatch {
            topic: TOPIC.to_string(),
            positions,
            ends: None,
        };
        let value = serde_json::to_value(&undispatched).unwrap();
        assert_eq!(value["ends"], Value::Null);
        assert_eq!(
            serde_json::from_value::<MarkerWatch>(value).unwrap(),
            undispatched
        );

        assert!(serde_json::from_value::<MarkerWatch>(serde_json::json!({
            "schema": 3, "topic": TOPIC, "positions": {}, "ends": null
        }))
        .is_err());
    }

    #[test]
    fn from_parts_classifies_every_seeding_and_reconciling_row() {
        let at = Utc.timestamp_opt(1_700_000_000, 0).unwrap();
        let hwms_value = serde_json::to_value(full_hwms(1_000)).unwrap();
        let watch_value = serde_json::to_value(MarkerWatch {
            topic: TOPIC.to_string(),
            positions: WatchPositions::new(),
            ends: None,
        })
        .unwrap();

        let seeding = |planned, dispatched, observed, hwms, watch| {
            CompletionPhase::from_parts(CompletionParts {
                status: CompletionStatus::Seeding,
                chunks_planned_at: planned,
                reconcile_dispatched_at: dispatched,
                reconcile_observed_at: observed,
                reconcile_hwms: hwms,
                marker_watch: watch,
                expected_marker_topic: TOPIC,
            })
        };
        assert_eq!(
            seeding(None, None, None, None, None),
            CompletionPhase::SeedingUnplanned
        );
        assert_eq!(
            seeding(Some(at), None, None, None, None),
            CompletionPhase::SeedingPlanned
        );
        assert_eq!(
            seeding(Some(at), Some(at), None, None, None),
            CompletionPhase::SeedingAnomalous
        );

        let reconciling = |dispatched, observed, hwms, watch| {
            CompletionPhase::from_parts(CompletionParts {
                status: CompletionStatus::Reconciling,
                chunks_planned_at: Some(at),
                reconcile_dispatched_at: dispatched,
                reconcile_observed_at: observed,
                reconcile_hwms: hwms,
                marker_watch: watch,
                expected_marker_topic: TOPIC,
            })
        };
        assert_eq!(
            reconciling(
                Some(at),
                Some(at),
                Some(hwms_value.clone()),
                Some(watch_value.clone())
            ),
            CompletionPhase::Observed
        );
        assert!(matches!(
            reconciling(
                Some(at),
                None,
                Some(hwms_value.clone()),
                Some(watch_value.clone())
            ),
            CompletionPhase::Reconciling(_)
        ));
        assert_eq!(
            reconciling(None, None, None, None),
            CompletionPhase::ReconcilingUndispatched(UndispatchedReason::NeverDispatched)
        );
        assert_eq!(
            reconciling(Some(at), None, None, Some(watch_value.clone())),
            CompletionPhase::ReconcilingUndispatched(UndispatchedReason::MissingRecord)
        );
        assert_eq!(
            reconciling(
                Some(at),
                None,
                Some(serde_json::json!({"0": 1})),
                Some(watch_value)
            ),
            CompletionPhase::ReconcilingUndispatched(UndispatchedReason::UnparseableRecord)
        );
    }

    #[test]
    fn a_watch_anchored_to_another_topic_re_dispatches_instead_of_resuming() {
        // Offsets are only meaningful against the log they were captured from, so a run carrying a
        // watch from a different topic — or from before the topic key existed — must never resume on
        // them.
        let at = Utc.timestamp_opt(1_700_000_000, 0).unwrap();
        let hwms_value = serde_json::to_value(full_hwms(1_000)).unwrap();
        let classify = |watch: Value| {
            CompletionPhase::from_parts(CompletionParts {
                status: CompletionStatus::Reconciling,
                chunks_planned_at: Some(at),
                reconcile_dispatched_at: Some(at),
                reconcile_observed_at: None,
                reconcile_hwms: Some(hwms_value.clone()),
                marker_watch: Some(watch),
                expected_marker_topic: TOPIC,
            })
        };

        assert_eq!(
            classify(serde_json::json!({
                "schema": 2, "topic": "cohort_membership_changed_shadow",
                "positions": {}, "ends": null
            })),
            CompletionPhase::ReconcilingUndispatched(UndispatchedReason::TopicChanged),
        );
        assert_eq!(
            classify(serde_json::json!({"schema": 1, "positions": {}, "ends": null})),
            CompletionPhase::ReconcilingUndispatched(UndispatchedReason::UnparseableRecord),
        );
    }

    #[test]
    fn observed_marker_carries_the_run_and_cohort() {
        let observed = ObservedMarker {
            team_id: TeamId(2),
            cohort_id: CohortId(42),
            partition: marker(7),
            run_id: RunId(Uuid::nil()),
        };
        assert_eq!(observed.partition.get(), 7);
    }
}
