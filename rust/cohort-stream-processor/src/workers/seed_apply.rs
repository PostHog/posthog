//! The apply pipeline a seed run runs through, shared by both seed kinds.
//!
//! Applying seeds one at a time costs one awaited produce per seed that flips anything, so a
//! worker spends its time waiting on Kafka instead of folding. A run amortizes that: one read
//! pass, one register diff, one stage-1 commit, one recompute, one joined produce round trip, one
//! stage-2 commit, one mark.
//!
//! Each stage is a struct whose one method consumes `self` and returns the next stage or
//! [`SeedHold`], so the compiler enforces the order: register diff → stage-1 commit → schedule →
//! recompute → produce → stage-2 commit → settle. Kind-specific work lives in the *head* — route,
//! read, fold — which produces a [`Folded`]; everything after that is shared. The heads are
//! [`seed_path`](super::seed_path) for tiles and [`person_seed_path`](super::person_seed_path) for
//! person seeds.
//!
//! Every produce acks before the state it reports commits, so a failed leg holds the run's *first*
//! offset with its durable effects either absent or idempotently re-appliable, and the redelivery
//! replays the whole run.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use std::time::Instant;

use cohort_core::seed::{PersonSeed, RunId, SeedTile};
use metrics::{counter, histogram};
use tracing::warn;
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::{FilterCatalog, TeamId};
use crate::observability::metrics::{
    PERSON_SEEDS_APPLIED_TOTAL, PERSON_SEEDS_DROPPED_TOTAL, PERSON_SEEDS_SKIPPED_TOTAL,
    PERSON_SEEDS_UNCHANGED_TOTAL, PERSON_SEED_REKEYED_TOTAL,
    PERSON_SEED_REKEY_PRODUCE_FAILURE_TOTAL, SEED_APPLY_RUNS_HELD_TOTAL,
    SEED_APPLY_RUN_DURATION_SECONDS, SEED_APPLY_RUN_SIZE, SEED_REKEYED_TOTAL,
    SEED_REKEY_PRODUCE_FAILURE_TOTAL, SEED_TILES_APPLIED_TOTAL, SEED_TILES_DROPPED_TOTAL,
    SEED_TILES_SKIPPED_TOTAL, SEED_TILES_UNCHANGED_TOTAL, STAGE1_TRANSITIONS,
};
use crate::partitions::offset_tracker::OffsetTracker;
use crate::producer::{CohortMembershipChange, LastUpdatedClock, MembershipSink};
use crate::stage1::key::LeafStateKey;
use crate::store::{BehavioralKey, ReadLane, StagedBatch, StoreError, StoreHandle};
use crate::sweep::EvictionQueue;
use crate::workers::merge_path::MergeWorkerDeps;
use crate::workers::reconcile::ReconcileQueue;
use crate::workers::seed_path::{admit_reconcile, hold, mark_processed, tag_seed};
use crate::workers::seed_run::{Admitted, OffsetSpan, SeedGroup, SeedKind, SeedOffset, SeedRun};
use crate::workers::stage2_path::{
    commit_stage2_writes, diff_single_leaf_registers, recompute_stage2, FoldedLeaf, RegisterDiff,
    Stage2Recompute,
};
use crate::workers::worker::{first_cascades, produce_cascades, produce_membership};

/// The ordered steps every run takes. Doubles as the `stage` metric label, so the duration
/// histogram and the held counter can never name a step the pipeline does not have.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ApplyStage {
    /// Tombstone resolution and cross-partition routing.
    Resolve,
    /// The batched state read that seeds the overlay.
    Read,
    /// The pure fold of every seed into the overlay. No I/O, so it never holds.
    Fold,
    RegisterDiff,
    Stage1Commit,
    Recompute,
    Produce,
    Stage2Commit,
}

impl ApplyStage {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Resolve => "resolve",
            Self::Read => "read",
            Self::Fold => "fold",
            Self::RegisterDiff => "register_diff",
            Self::Stage1Commit => "stage1_commit",
            Self::Recompute => "recompute",
            Self::Produce => "produce",
            Self::Stage2Commit => "stage2_commit",
        }
    }
}

impl std::fmt::Display for ApplyStage {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Which output a run's produce failed on. All three legs are issued together, so the leg names
/// the topic for the operator where the stage alone could not.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ProduceLeg {
    Membership,
    Cascade,
    /// The cross-partition hand-off back onto the seed topic.
    ReKey,
}

impl std::fmt::Display for ProduceLeg {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            Self::Membership => "membership",
            Self::Cascade => "cascade",
            Self::ReKey => "re-key",
        })
    }
}

/// A failure that must not commit. Every step that can leave durable state half-written returns
/// this, so the `Ok ⇒ mark, Err ⇒ hold` decision lives at one site.
#[derive(Debug, thiserror::Error)]
pub(crate) enum SeedHold {
    #[error("{stage}: {source}")]
    Store {
        stage: ApplyStage,
        source: StoreError,
    },
    #[error("{leg} produce: {errors} message(s) failed")]
    Produce { leg: ProduceLeg, errors: usize },
    /// A batched read answered fewer slots than keys. Pairing a slot with the wrong key would fold
    /// one person's seed onto another's state, so the run holds instead.
    #[error("{stage}: batched read answered {answered} of {asked} keys")]
    ShortRead {
        stage: ApplyStage,
        asked: usize,
        answered: usize,
    },
}

impl SeedHold {
    /// `map_err` adapter that labels a store failure with the step that hit it.
    pub(crate) fn store(stage: ApplyStage) -> impl FnOnce(StoreError) -> Self {
        move |source| Self::Store { stage, source }
    }

    /// `Ok` when a batched read answered every key; the run's hold otherwise.
    pub(crate) fn check_read(stage: ApplyStage, asked: usize, answered: usize) -> Result<(), Self> {
        if asked == answered {
            return Ok(());
        }
        Err(Self::ShortRead {
            stage,
            asked,
            answered,
        })
    }

    pub(crate) fn stage(&self) -> ApplyStage {
        match self {
            Self::Store { stage, .. } | Self::ShortRead { stage, .. } => *stage,
            Self::Produce { .. } => ApplyStage::Produce,
        }
    }
}

/// What every stage borrows. `Copy`, so a stage can hand it on without ceremony. `catalog` is one
/// snapshot per channel batch, where the per-seed apply loaded its own per seed.
#[derive(Clone, Copy)]
pub(crate) struct ApplyDeps<'a> {
    pub partition_id: u16,
    pub handle: &'a StoreHandle,
    pub catalog: &'a FilterCatalog,
    pub sink: &'a Arc<dyn MembershipSink>,
    pub merge: &'a MergeWorkerDeps,
}

impl<'a> ApplyDeps<'a> {
    pub(crate) fn team(&self, team_id: TeamId) -> Option<&'a TeamFilters> {
        self.catalog.team(team_id).map(|filters| &**filters)
    }
}

/// The one clock reading and the one output version a whole run shares.
///
/// `now_ms` is taken once, after every member was fenced individually at admission, so the newest
/// seed applies up to one run duration after its fence check — which only widens its eviction
/// window. Each `(cohort, person)` appears at most once in a run's output, so one `last_updated`
/// needs no intra-run ordering and the next run's stamp is strictly newer.
pub(crate) struct RunStamp {
    pub now_ms: i64,
    pub last_updated: String,
}

// ---- The overlay: read-your-writes within a run ----

/// One key's state through a run: what the read pass saw, and what the fold made of it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct Slot<V> {
    /// What the read pass saw — the run-start truth the net-transition rule diffs against.
    before: Option<V>,
    /// The fold's fixed point, once some seed changed the bytes.
    advanced: Option<V>,
    /// Whether any seed folded into this slot, advancing it or not. An all-`Unchanged` slot skips
    /// its row write but still takes part in the register diff and the recompute.
    touched: bool,
    /// The row existed but did not decode. The tile fold refuses such a slot; the person fold
    /// rebuilds from the absent baseline, as its per-seed apply does.
    prior_corrupt: bool,
}

impl<V> Slot<V> {
    /// What the next seed folds against: the run's own writes first, then the read pass.
    pub(crate) fn current(&self) -> Option<&V> {
        self.advanced.as_ref().or(self.before.as_ref())
    }

    pub(crate) fn before(&self) -> Option<&V> {
        self.before.as_ref()
    }

    pub(crate) fn advanced(&self) -> Option<&V> {
        self.advanced.as_ref()
    }

    pub(crate) fn prior_corrupt(&self) -> bool {
        self.prior_corrupt
    }

    /// Record a fold that changed the bytes.
    pub(crate) fn advance(&mut self, value: V) {
        self.advanced = Some(value);
        self.touched = true;
    }

    /// Record a fold that left the bytes alone.
    pub(crate) fn touch(&mut self) {
        self.touched = true;
    }
}

/// One stored row of a batched read, decoded. Absence is not a variant: the read reports it, and
/// no keyspace here stores a value that means "absent".
pub(crate) enum Decoded<V> {
    Value(V),
    /// The row exists but does not decode. Counted once per row, not once per seed that touches it.
    Corrupt,
}

/// Read-your-writes within a run (RocksDB's `WriteBatchWithIndex` idea, in memory): a later seed
/// for the same key folds onto the earlier seed's result, not onto the bytes the read pass saw.
#[derive(Debug, Default)]
pub(crate) struct Overlay<K: Ord, V> {
    slots: BTreeMap<K, Slot<V>>,
}

impl<K: Ord + Copy, V> Overlay<K, V> {
    /// Pair each key with its answer. A short answer is a hold, never a silent absent: pairing a
    /// slot with the wrong key would fold one person's seed onto another's state.
    pub(crate) fn from_read(
        stage: ApplyStage,
        keys: Vec<K>,
        values: Vec<Option<Vec<u8>>>,
        decode: impl Fn(&[u8]) -> Decoded<V>,
    ) -> Result<Self, SeedHold> {
        SeedHold::check_read(stage, keys.len(), values.len())?;
        let mut slots = BTreeMap::new();
        for (key, bytes) in keys.into_iter().zip(values) {
            let (before, prior_corrupt) = match bytes.as_deref().map(&decode) {
                None => (None, false),
                Some(Decoded::Value(value)) => (Some(value), false),
                Some(Decoded::Corrupt) => (None, true),
            };
            slots.insert(
                key,
                Slot {
                    before,
                    advanced: None,
                    touched: false,
                    prior_corrupt,
                },
            );
        }
        Ok(Self { slots })
    }

    pub(crate) fn slot(&self, key: &K) -> Option<&Slot<V>> {
        self.slots.get(key)
    }

    pub(crate) fn slot_mut(&mut self, key: &K) -> Option<&mut Slot<V>> {
        self.slots.get_mut(key)
    }

    /// Rows that exist but did not decode, for the head to count once per row at the read.
    pub(crate) fn prior_corrupt_rows(&self) -> usize {
        self.slots
            .values()
            .filter(|slot| slot.prior_corrupt)
            .count()
    }

    /// Every slot some seed folded into, in key order.
    pub(crate) fn touched(&self) -> impl Iterator<Item = (&K, &Slot<V>)> {
        self.slots.iter().filter(|(_, slot)| slot.touched)
    }
}

// ---- What a head hands the shared pipeline ----

/// A run's cross-partition hand-offs. One kind per run, because a run is one kind.
#[derive(Debug)]
pub(crate) enum ReKeys {
    Tiles(Vec<SeedTile>),
    Persons(Vec<PersonSeed>),
}

impl ReKeys {
    fn is_empty(&self) -> bool {
        match self {
            Self::Tiles(tiles) => tiles.is_empty(),
            Self::Persons(seeds) => seeds.is_empty(),
        }
    }
}

/// The persons a run touched: which leaves each needs recomposed, and the run of the last seed
/// that touched them in offset order, which is the provenance their recomposed changes carry.
///
/// Keeping a person whole matters: splitting their leaves across two recompute calls would
/// evaluate the same cohort twice against the same uncommitted bit and emit the flip twice.
#[derive(Debug, Default)]
pub(crate) struct TouchedPersons {
    per_person: BTreeMap<(TeamId, Uuid), PersonTouch>,
}

#[derive(Debug)]
struct PersonTouch {
    run: RunId,
    leaves: BTreeSet<LeafStateKey>,
}

impl TouchedPersons {
    pub(crate) fn touch(&mut self, team_id: TeamId, person: Uuid, run: RunId, leaf: LeafStateKey) {
        let touch = self
            .per_person
            .entry((team_id, person))
            .or_insert_with(|| PersonTouch {
                run,
                leaves: BTreeSet::new(),
            });
        // Last call wins, and the heads call in offset order: the person stays in one recompose
        // group under the run of the last seed that touched them.
        touch.run = run;
        touch.leaves.insert(leaf);
    }

    fn is_empty(&self) -> bool {
        self.per_person.is_empty()
    }

    /// One recompute call per `(team, run)`: the team owns the catalog that composes the leaves,
    /// the run owns their provenance tag.
    fn groups(self) -> BTreeMap<(TeamId, RunId), Vec<(LeafStateKey, Uuid)>> {
        let mut groups: BTreeMap<(TeamId, RunId), Vec<(LeafStateKey, Uuid)>> = BTreeMap::new();
        for ((team_id, person), touch) in self.per_person {
            let group = groups.entry((team_id, touch.run)).or_default();
            group.extend(touch.leaves.into_iter().map(|leaf| (leaf, person)));
        }
        groups
    }
}

// ---- Deferred outcome counters ----

/// One thing a run did, held as data until the run settles. Exhaustive, so a new outcome cannot be
/// counted mid-flight by accident.
///
/// Only work the run did is deferred. What a run *found* stays attempt-based, because a run that a
/// later hold keeps from settling must not hide it: corrupt rows, hop-capped redirects, dropped
/// hashes, produce failures, held runs, and `OUTPUT_MEMBERSHIP_CHANGES_EMITTED`, which fires inside
/// `produce_membership` before the stage-2 commit.
///
/// The payloads are the metric labels rather than the domain enums, because that is what a counter
/// takes and it keeps this key orderable without an `Ord` on types that have no order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum Outcome {
    /// `variant` label.
    TileApplied(&'static str),
    /// `variant` label.
    TileUnchanged(&'static str),
    /// `reason` label.
    TileDropped(&'static str),
    /// `verdict` label.
    PersonApplied(&'static str),
    PersonUnchanged,
    /// `reason` label.
    PersonSkipped(&'static str),
    /// `reason` label.
    PersonDropped(&'static str),
    /// `kind` label, as [`crate::workers::worker::transition_metric_label`] names it.
    Stage1Transition(&'static str),
    ReKeyed(SeedKind),
}

/// A run's non-failure counts, emitted only once the run settles, so a hold cannot double-count
/// them on replay.
#[derive(Debug, Default)]
pub(crate) struct Tally(BTreeMap<Outcome, u64>);

impl Tally {
    pub(crate) fn add(&mut self, outcome: Outcome) {
        *self.0.entry(outcome).or_default() += 1;
    }

    fn record(self) {
        for (outcome, count) in self.0 {
            match outcome {
                Outcome::TileApplied(variant) => {
                    counter!(SEED_TILES_APPLIED_TOTAL, "variant" => variant).increment(count);
                }
                Outcome::TileUnchanged(variant) => {
                    counter!(SEED_TILES_UNCHANGED_TOTAL, "variant" => variant).increment(count);
                }
                Outcome::TileDropped(reason) => {
                    counter!(SEED_TILES_DROPPED_TOTAL, "reason" => reason).increment(count);
                }
                Outcome::PersonApplied(verdict) => {
                    counter!(PERSON_SEEDS_APPLIED_TOTAL, "verdict" => verdict).increment(count);
                }
                Outcome::PersonUnchanged => {
                    counter!(PERSON_SEEDS_UNCHANGED_TOTAL).increment(count);
                }
                Outcome::PersonSkipped(reason) => {
                    counter!(PERSON_SEEDS_SKIPPED_TOTAL, "reason" => reason).increment(count);
                }
                Outcome::PersonDropped(reason) => {
                    counter!(PERSON_SEEDS_DROPPED_TOTAL, "reason" => reason).increment(count);
                }
                Outcome::Stage1Transition(kind) => {
                    counter!(STAGE1_TRANSITIONS, "kind" => kind).increment(count);
                }
                Outcome::ReKeyed(SeedKind::Tile) => {
                    counter!(SEED_REKEYED_TOTAL).increment(count);
                }
                Outcome::ReKeyed(SeedKind::Person) => {
                    counter!(PERSON_SEED_REKEYED_TOTAL).increment(count);
                }
            }
        }
    }
}

/// Splits one run's wall clock into per-stage samples: each [`mark`](Self::mark) records the time
/// since the previous one. A held run records no sample for the step that failed, so the histogram
/// stays a picture of completed work; [`SEED_APPLY_RUNS_HELD_TOTAL`] carries the failures.
pub(crate) struct StageClock {
    kind: SeedKind,
    last: Instant,
}

impl StageClock {
    fn start(kind: SeedKind, size: usize) -> Self {
        histogram!(SEED_APPLY_RUN_SIZE, "kind" => kind.as_str()).record(size as f64);
        Self {
            kind,
            last: Instant::now(),
        }
    }

    pub(crate) fn mark(&mut self, stage: ApplyStage) {
        let now = Instant::now();
        histogram!(
            SEED_APPLY_RUN_DURATION_SECONDS,
            "kind" => self.kind.as_str(),
            "stage" => stage.as_str(),
        )
        .record(now.duration_since(self.last).as_secs_f64());
        self.last = now;
    }
}

/// One collection's marks, published only once every group in it has run.
///
/// Groups do not partition the collection's offsets: one open run per kind means a tile run and a
/// person run interleave, so a tile run's `span.last` can sit above a person seed the pipeline has
/// not reached yet. The seed consumer commits from its own task off the shared tracker, so marking
/// mid-collection could commit past that person seed and lose it on the next tenure. Holds stay
/// immediate: a hold only ever lowers the floor, so publishing one early is always safe.
#[derive(Default)]
pub(crate) struct BatchMarks(Option<SeedOffset>);

impl BatchMarks {
    pub(crate) fn mark(&mut self, offset: SeedOffset) {
        self.0 = Some(self.0.map_or(offset, |seen| seen.max(offset)));
    }

    pub(crate) fn publish(self, tracker: &OffsetTracker, partition_id: u16) {
        if let Some(offset) = self.0 {
            mark_processed(tracker, partition_id, offset);
        }
    }
}

// ---- The pipeline ----

/// The head's output: the run's whole durable intent, nothing written yet.
#[must_use]
pub(crate) struct Folded {
    pub span: OffsetSpan,
    /// Stage-1 rows (`cf_behavioral` or `cf_person_records`), final state per key.
    pub records: StagedBatch,
    /// One entry per distinct `(team, leaf, person)` the run touched, with the run-final truth and
    /// the net transition. Grouped by team because the register diff is per catalog.
    pub leaves: BTreeMap<TeamId, Vec<FoldedLeaf>>,
    /// Persons whose composable cohorts must recompose, with the run that last touched them.
    pub recompose: TouchedPersons,
    /// Final eviction deadline per touched behavioral key. Empty for person seeds.
    pub schedules: Vec<(BehavioralKey, i64)>,
    pub re_keys: ReKeys,
    pub tally: Tally,
}

impl Folded {
    /// A run with no durable intent: the gate-off person run, which marks its span and does
    /// nothing else. Every later stage is a no-op on it.
    pub(crate) fn nothing(span: OffsetSpan, re_keys: ReKeys, tally: Tally) -> Self {
        Self {
            span,
            records: StagedBatch::default(),
            leaves: BTreeMap::new(),
            recompose: TouchedPersons::default(),
            schedules: Vec::new(),
            re_keys,
            tally,
        }
    }

    /// One [`diff_single_leaf_registers`] per team. Every person the diff emits a change or a write
    /// for joins `recompose`: a lagging register is its own reason to recompose, and nothing the
    /// fold saw would admit it — the redelivery of a failed produce mints no transition.
    async fn diff_registers(
        mut self,
        deps: ApplyDeps<'_>,
        stamp: &RunStamp,
    ) -> Result<Diffed, SeedHold> {
        let mut diff = RegisterDiff::default();
        for (&team_id, leaves) in &self.leaves {
            // Only teams the same snapshot already resolved reach here, so the miss arm is dead; it
            // degrades to skipping one team's diff rather than killing the partition worker.
            let Some(filters) = deps.team(team_id) else {
                continue;
            };
            let team_diff = diff_single_leaf_registers(
                deps.partition_id,
                deps.handle,
                filters,
                leaves,
                stamp.now_ms,
                &stamp.last_updated,
                ReadLane::Maintenance,
            )
            .await
            .map_err(SeedHold::store(ApplyStage::RegisterDiff))?;

            let lagging: BTreeSet<Uuid> = team_diff
                .recompute
                .writes
                .iter()
                .chain(team_diff.stage1_writes.iter())
                .map(|(key, _)| key.person_id)
                .collect();
            for leaf in leaves {
                if lagging.contains(&leaf.person_id) {
                    self.recompose
                        .touch(team_id, leaf.person_id, leaf.run_id, leaf.leaf_state_key);
                }
            }
            diff.extend(team_diff);
        }

        // One batch, so a register the diff pre-writes is never stranded without the stage-1 row
        // that justifies it.
        let mut records = self.records;
        for (key, state) in &diff.stage1_writes {
            records.put_stage2(key, &state.encode());
        }
        Ok(Diffed {
            span: self.span,
            records,
            recompute: diff.recompute,
            recompose: self.recompose,
            schedules: self.schedules,
            re_keys: self.re_keys,
            tally: self.tally,
        })
    }
}

#[must_use]
struct Diffed {
    span: OffsetSpan,
    records: StagedBatch,
    recompute: Stage2Recompute,
    recompose: TouchedPersons,
    schedules: Vec<(BehavioralKey, i64)>,
    re_keys: ReKeys,
    tally: Tally,
}

impl Diffed {
    async fn commit_stage1(self, deps: ApplyDeps<'_>) -> Result<Committed, SeedHold> {
        if !self.records.is_empty() {
            deps.handle
                .commit(self.records)
                .await
                .map_err(SeedHold::store(ApplyStage::Stage1Commit))?;
        }
        Ok(Committed {
            span: self.span,
            recompute: self.recompute,
            recompose: self.recompose,
            schedules: self.schedules,
            re_keys: self.re_keys,
            tally: self.tally,
        })
    }
}

#[must_use]
struct Committed {
    span: OffsetSpan,
    recompute: Stage2Recompute,
    recompose: TouchedPersons,
    schedules: Vec<(BehavioralKey, i64)>,
    re_keys: ReKeys,
    tally: Tally,
}

impl Committed {
    /// Infallible, and taken here rather than after the produce: the rows are already durable, so
    /// their deadlines are owed whatever follows. A deadline lost to a later hold is re-derived
    /// from `cf_behavioral` by `rebuild_eviction_queue` at the next tenure start.
    fn schedule(self, queue: &mut EvictionQueue<BehavioralKey>) -> Scheduled {
        for (key, deadline) in self.schedules {
            queue.schedule(key, deadline);
        }
        Scheduled {
            span: self.span,
            recompute: self.recompute,
            recompose: self.recompose,
            re_keys: self.re_keys,
            tally: self.tally,
        }
    }
}

#[must_use]
struct Scheduled {
    span: OffsetSpan,
    recompute: Stage2Recompute,
    recompose: TouchedPersons,
    re_keys: ReKeys,
    tally: Tally,
}

impl Scheduled {
    /// One recompute per `(team, run)`, folded into the register diff's half so one produce and
    /// one commit cover both.
    async fn recompute(
        mut self,
        deps: ApplyDeps<'_>,
        stamp: &RunStamp,
    ) -> Result<Recomputed, SeedHold> {
        if !self.recompose.is_empty() {
            for ((team_id, run), leaves) in self.recompose.groups() {
                let Some(filters) = deps.team(team_id) else {
                    continue;
                };
                let mut composed = recompute_stage2(
                    deps.partition_id,
                    deps.handle,
                    filters,
                    &leaves,
                    stamp.now_ms,
                    &stamp.last_updated,
                    ReadLane::Maintenance,
                )
                .await
                .map_err(SeedHold::store(ApplyStage::Recompute))?;
                // The register diff stamps its own changes from the leaf, so only the composed
                // half still needs the run tag.
                tag_seed(&mut composed.changes, run);
                self.recompute.extend(composed);
            }
        }
        let changes = std::mem::take(&mut self.recompute.changes);
        Ok(Recomputed {
            span: self.span,
            changes,
            stage2: self.recompute,
            re_keys: self.re_keys,
            tally: self.tally,
        })
    }
}

#[must_use]
struct Recomputed {
    span: OffsetSpan,
    /// Taken out of `stage2` so the produce moves them instead of cloning.
    changes: Vec<CohortMembershipChange>,
    stage2: Stage2Recompute,
    re_keys: ReKeys,
    tally: Tally,
}

impl Recomputed {
    /// One round trip for all three legs.
    ///
    /// After stage 1 committed, every membership change is re-derivable — single-leaf ones from the
    /// register the run has not advanced, composed ones from the stage-2 bits it has not written —
    /// so a failed leg holds the run and the replay re-emits the whole output. Duplicates are safe
    /// on every leg: membership is LWW downstream, a duplicate cascade re-evaluates a referrer from
    /// the store, and a duplicate re-keyed seed re-applies idempotently on its target.
    async fn produce(self, deps: ApplyDeps<'_>) -> Result<Produced, SeedHold> {
        let Self {
            span,
            changes,
            stage2,
            re_keys,
            tally,
        } = self;
        // Built from a borrow before `changes` moves: the cascade payload embeds the change.
        let cascades = first_cascades(deps.merge, &changes, span.last.0);
        let (membership, cascade, re_key) = tokio::join!(
            produce_membership_if_any(deps.sink, changes),
            produce_cascades(deps.merge, cascades),
            produce_re_keys(deps.merge, re_keys),
        );
        require_acked(ProduceLeg::Membership, membership)?;
        require_acked(ProduceLeg::Cascade, cascade)?;
        require_acked(ProduceLeg::ReKey, re_key)?;
        Ok(Produced {
            span,
            stage2,
            tally,
        })
    }
}

#[must_use]
struct Produced {
    span: OffsetSpan,
    stage2: Stage2Recompute,
    tally: Tally,
}

impl Produced {
    /// The composed bits and the single-leaf register bits commit only after the produce acks, so
    /// a failed produce is re-derived on replay instead of lost against a flipped bit.
    async fn commit_stage2(self, deps: ApplyDeps<'_>) -> Result<Settled, SeedHold> {
        commit_stage2_writes(deps.handle, &self.stage2.writes)
            .await
            .map_err(SeedHold::store(ApplyStage::Stage2Commit))?;
        Ok(Settled {
            span: self.span,
            stage2: self.stage2,
            tally: self.tally,
        })
    }
}

#[must_use]
struct Settled {
    span: OffsetSpan,
    stage2: Stage2Recompute,
    tally: Tally,
}

impl Settled {
    /// Everything the run counted, emitted once its offsets are safe to mark.
    fn record(self) -> OffsetSpan {
        self.stage2.record_metrics();
        self.tally.record();
        self.span
    }
}

// ---- Produce legs ----

async fn produce_membership_if_any(
    sink: &Arc<dyn MembershipSink>,
    changes: Vec<CohortMembershipChange>,
) -> usize {
    if changes.is_empty() {
        return 0;
    }
    produce_membership(sink, changes).await
}

/// Re-produce a run's hand-offs, awaiting exactly one `Ok` per seed. A re-keyed seed has no other
/// copy, so a short ack vector is a failure, never a vacuous success.
async fn produce_re_keys(merge: &MergeWorkerDeps, re_keys: ReKeys) -> usize {
    if re_keys.is_empty() {
        return 0;
    }
    let (errors, failure_metric) = match re_keys {
        ReKeys::Tiles(tiles) => {
            let expected = tiles.len();
            let acks = merge.seed_tile_sink.produce(tiles).await;
            (
                ack_errors(&acks, expected),
                SEED_REKEY_PRODUCE_FAILURE_TOTAL,
            )
        }
        ReKeys::Persons(seeds) => {
            let expected = seeds.len();
            let acks = merge.seed_tile_sink.produce_person(seeds).await;
            (
                ack_errors(&acks, expected),
                PERSON_SEED_REKEY_PRODUCE_FAILURE_TOTAL,
            )
        }
    };
    if errors > 0 {
        counter!(failure_metric).increment(errors as u64);
    }
    errors
}

fn ack_errors<E>(acks: &[Result<(), E>], expected: usize) -> usize {
    acks.iter().filter(|result| result.is_err()).count() + acks.len().abs_diff(expected)
}

fn require_acked(leg: ProduceLeg, errors: usize) -> Result<(), SeedHold> {
    if errors == 0 {
        return Ok(());
    }
    Err(SeedHold::Produce { leg, errors })
}

// ---- Driving a run ----

/// The kind-specific half of a run: route, read, fold. Exists only so [`apply`] is written once;
/// the two heads are ordinary modules.
pub(crate) trait SeedHead {
    type Seed;
    const KIND: SeedKind;

    async fn fold(
        deps: ApplyDeps<'_>,
        run: SeedRun<Self::Seed>,
        stamp: &RunStamp,
        clock: &mut StageClock,
    ) -> Result<Folded, SeedHold>;
}

/// Apply one run: fold it, then drive the shared pipeline, then mark or hold its whole span.
pub(crate) async fn apply<H: SeedHead>(
    deps: ApplyDeps<'_>,
    queue: &mut EvictionQueue<BehavioralKey>,
    clock: &mut LastUpdatedClock,
    marks: &mut BatchMarks,
    run: SeedRun<H::Seed>,
) {
    let span = run.span();
    let mut stages = StageClock::start(H::KIND, run.len());
    let stamp = RunStamp {
        now_ms: chrono::Utc::now().timestamp_millis(),
        last_updated: clock.next(),
    };
    let outcome = drive::<H>(deps, queue, run, &stamp, &mut stages).await;
    settle(deps, H::KIND, span, marks, outcome);
}

async fn drive<H: SeedHead>(
    deps: ApplyDeps<'_>,
    queue: &mut EvictionQueue<BehavioralKey>,
    run: SeedRun<H::Seed>,
    stamp: &RunStamp,
    stages: &mut StageClock,
) -> Result<OffsetSpan, SeedHold> {
    let folded = H::fold(deps, run, stamp, stages).await?;

    let diffed = folded.diff_registers(deps, stamp).await?;
    stages.mark(ApplyStage::RegisterDiff);

    let committed = diffed.commit_stage1(deps).await?;
    stages.mark(ApplyStage::Stage1Commit);

    let recomputed = committed.schedule(queue).recompute(deps, stamp).await?;
    stages.mark(ApplyStage::Recompute);

    let produced = recomputed.produce(deps).await?;
    stages.mark(ApplyStage::Produce);

    let settled = produced.commit_stage2(deps).await?;
    stages.mark(ApplyStage::Stage2Commit);

    Ok(settled.record())
}

/// Mark the run's whole span, or hold its first offset and count the failed stage.
fn settle(
    deps: ApplyDeps<'_>,
    kind: SeedKind,
    span: OffsetSpan,
    marks: &mut BatchMarks,
    outcome: Result<OffsetSpan, SeedHold>,
) {
    match outcome {
        Ok(marked) => marks.mark(marked.last),
        Err(held) => {
            counter!(
                SEED_APPLY_RUNS_HELD_TOTAL,
                "kind" => kind.as_str(),
                "stage" => held.stage().as_str(),
            )
            .increment(1);
            warn!(
                partition_id = deps.partition_id,
                kind = kind.as_str(),
                first_offset = span.first.0,
                last_offset = span.last.0,
                error = %held,
                "seed run apply failed; holding the run's first seed offset for redelivery",
            );
            hold(&deps.merge.seed_tracker, deps.partition_id, span.first);
        }
    }
}

/// Apply one channel batch's seed groups in order on the owning partition worker.
///
/// A group that holds pins the commit floor at its own first offset; later groups still run, and
/// the floor keeps the published mark from leapfrogging the hold — the same envelope as the
/// per-seed path, now at run granularity.
///
/// The mark itself is published once, after the last group, because groups' spans interleave (see
/// [`BatchMarks`]).
pub(crate) async fn handle_seed_groups(
    deps: ApplyDeps<'_>,
    queue: &mut EvictionQueue<BehavioralKey>,
    reconcile_queue: &mut ReconcileQueue,
    clock: &mut LastUpdatedClock,
    groups: Vec<SeedGroup>,
) {
    let mut marks = BatchMarks::default();
    for group in groups {
        match group {
            SeedGroup::Tiles(run) => {
                apply::<crate::workers::seed_path::TileHead>(deps, queue, clock, &mut marks, run)
                    .await;
            }
            SeedGroup::Persons(run) => {
                apply::<crate::workers::person_seed_path::PersonHead>(
                    deps, queue, clock, &mut marks, run,
                )
                .await;
            }
            SeedGroup::Reconcile(Admitted { work, offset }) => admit_reconcile(
                deps.partition_id,
                deps.merge,
                reconcile_queue,
                &mut marks,
                &work,
                offset,
            ),
            SeedGroup::Skip(Admitted { work, offset }) => {
                counter!(SEED_TILES_SKIPPED_TOTAL, "reason" => work.as_str()).increment(1);
                marks.mark(offset);
            }
        }
    }
    marks.publish(&deps.merge.seed_tracker, deps.partition_id);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn overlay_of(values: Vec<Option<&str>>) -> Overlay<u8, String> {
        let keys: Vec<u8> = (0..values.len() as u8).collect();
        let values: Vec<Option<Vec<u8>>> = values
            .into_iter()
            .map(|value| value.map(|value| value.as_bytes().to_vec()))
            .collect();
        Overlay::from_read(
            ApplyStage::Read,
            keys,
            values,
            |bytes| match std::str::from_utf8(bytes) {
                Ok("corrupt") | Err(_) => Decoded::Corrupt,
                Ok(value) => Decoded::Value(value.to_string()),
            },
        )
        .unwrap()
    }

    /// The whole point of the overlay: a second seed for one key must fold onto the first seed's
    /// result, or a run of two would apply both against the same run-start bytes.
    #[test]
    fn a_later_fold_sees_the_earlier_folds_result_but_before_stays_the_read() {
        let mut overlay = overlay_of(vec![Some("first")]);

        let slot = overlay.slot_mut(&0).unwrap();
        assert_eq!(slot.current().map(String::as_str), Some("first"));
        slot.advance("second".to_string());
        assert_eq!(slot.current().map(String::as_str), Some("second"));
        assert_eq!(
            slot.before().map(String::as_str),
            Some("first"),
            "the net-transition rule diffs against the read pass, not the last write",
        );
        assert!(slot.advanced().is_some());
    }

    /// An all-`Unchanged` slot writes no row but must still reach the register diff and the
    /// recompute, which is what heals a produce that failed after an earlier run committed.
    #[test]
    fn a_touched_but_unadvanced_slot_is_still_touched() {
        let mut overlay = overlay_of(vec![Some("stored")]);
        overlay.slot_mut(&0).unwrap().touch();

        let touched: Vec<_> = overlay.touched().collect();
        assert_eq!(touched.len(), 1);
        assert!(touched[0].1.advanced().is_none(), "no row to write");
    }

    #[test]
    fn an_unfolded_slot_is_not_touched() {
        let overlay = overlay_of(vec![Some("stored"), None]);
        assert_eq!(overlay.touched().count(), 0);
    }

    /// A corrupt row reads as absent with the flag set, so the tile fold can refuse it while the
    /// person fold rebuilds from the absent baseline.
    #[test]
    fn a_corrupt_row_reads_absent_and_flags_itself() {
        let mut overlay = overlay_of(vec![Some("corrupt")]);
        let slot = overlay.slot_mut(&0).unwrap();

        assert!(slot.prior_corrupt());
        assert!(slot.current().is_none());
        assert!(slot.before().is_none());
    }

    /// A short answer would pair one key's slot with another key's bytes.
    #[test]
    fn a_short_read_holds_the_run_rather_than_pairing_slots_wrongly() {
        let result = Overlay::<u8, String>::from_read(
            ApplyStage::Read,
            vec![0, 1, 2],
            vec![None, None],
            |_| Decoded::Corrupt,
        );

        assert!(matches!(
            result,
            Err(SeedHold::ShortRead {
                stage: ApplyStage::Read,
                asked: 3,
                answered: 2,
            }),
        ));
    }

    /// Counting mid-run would report a held run's work once per redelivery.
    #[test]
    fn a_tally_sums_repeats_of_one_outcome() {
        let mut tally = Tally::default();
        tally.add(Outcome::TileApplied("behavioral_single"));
        tally.add(Outcome::TileApplied("behavioral_single"));
        tally.add(Outcome::PersonUnchanged);

        assert_eq!(tally.0[&Outcome::TileApplied("behavioral_single")], 2);
        assert_eq!(tally.0[&Outcome::PersonUnchanged], 1);
    }

    /// Splitting a person across two recompute calls would evaluate the same cohort twice against
    /// the same uncommitted bit and emit the flip twice.
    #[test]
    fn a_person_touched_twice_stays_in_one_group_under_the_last_run() {
        let team = TeamId(7);
        let alice = Uuid::from_u128(1);
        let first = RunId(Uuid::from_u128(0xA));
        let last = RunId(Uuid::from_u128(0xB));
        let mut touched = TouchedPersons::default();
        touched.touch(team, alice, first, LeafStateKey([1; 16]));
        touched.touch(team, alice, last, LeafStateKey([2; 16]));

        let groups = touched.groups();
        assert_eq!(groups.len(), 1, "one call, not one per seed");
        assert_eq!(
            groups[&(team, last)],
            vec![
                (LeafStateKey([1; 16]), alice),
                (LeafStateKey([2; 16]), alice)
            ],
            "both leaves ride the last run that touched the person",
        );
    }
}
