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

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::Arc;
use std::time::Instant;

use cohort_core::seed::{PersonSeed, ReconcileTile, RunId, SeedTile};
use metrics::{counter, histogram};
use tracing::warn;
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::{FilterCatalog, TeamId};
use crate::merge::tombstone_redirect::{self, Resolution};
use crate::observability::metrics::{
    COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH, OUTPUT_TRANSITIONS_UNMAPPED,
    PERSON_SEEDS_APPLIED_TOTAL, PERSON_SEEDS_DROPPED_TOTAL, PERSON_SEEDS_SKIPPED_TOTAL,
    PERSON_SEEDS_UNCHANGED_TOTAL, PERSON_SEED_REKEYED_TOTAL,
    PERSON_SEED_REKEY_PRODUCE_FAILURE_TOTAL, RECONCILE_JOBS_ENQUEUED_TOTAL,
    RECONCILE_JOBS_SUPERSEDED_TOTAL, SEED_APPLY_RUNS_HELD_TOTAL, SEED_APPLY_RUN_DURATION_SECONDS,
    SEED_APPLY_RUN_SIZE, SEED_HELD_OFFSET_GAUGE, SEED_REKEYED_TOTAL,
    SEED_REKEY_PRODUCE_FAILURE_TOTAL, SEED_TILES_APPLIED_TOTAL, SEED_TILES_DROPPED_TOTAL,
    SEED_TILES_SKIPPED_TOTAL, SEED_TILES_UNCHANGED_TOTAL, STAGE1_TRANSITIONS,
};
use crate::partitions::offset_tracker::MarkOutcome;
use crate::partitions::offset_tracker::OffsetTracker;
use crate::producer::{ChangeOrigin, CohortMembershipChange, LastUpdatedClock, MembershipSink};
use crate::stage1::key::LeafStateKey;
use crate::stage1::transition::LeafTransition;
use crate::store::{BehavioralKey, ReadLane, StagedBatch, StoreError, StoreHandle};
use crate::sweep::EvictionQueue;
use crate::workers::merge_path::MergeWorkerDeps;
use crate::workers::reconcile::{ReconcileQueue, SupersedeOutcome};
use crate::workers::seed_run::{Admitted, OffsetSpan, SeedGroup, SeedKind, SeedOffset, SeedRun};
use crate::workers::stage2_path::{
    commit_stage2_writes, diff_single_leaf_registers, recompute_stage2, FoldedLeaf, RegisterDiff,
    Stage2Recompute,
};
use crate::workers::worker::{
    first_cascades, produce_cascades, produce_membership, transition_metric_label,
};

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

pub(crate) async fn resolve_run_persons(
    deps: ApplyDeps<'_>,
    mut persons: Vec<(TeamId, Uuid)>,
) -> Result<HashMap<(TeamId, Uuid), Resolution>, SeedHold> {
    persons.sort_unstable();
    persons.dedup();
    let resolved = tombstone_redirect::resolve_batch_offloaded(
        deps.handle,
        deps.partition_id,
        &persons,
        deps.merge.partition_count,
        ReadLane::Maintenance,
    )
    .await
    .map_err(SeedHold::store(ApplyStage::Resolve))?;
    SeedHold::check_read(ApplyStage::Resolve, persons.len(), resolved.len())?;
    Ok(resolved)
}

pub(crate) fn record_stage1_transition(
    tally: &mut Tally,
    filters: &TeamFilters,
    transition: &LeafTransition,
) {
    if let Some(kind) = transition_metric_label(filters, transition) {
        tally.add(Outcome::Stage1Transition(kind));
    }
    if filters
        .by_lsk_to_single_leaf_cohorts
        .get(&transition.leaf_state_key)
        .is_none_or(Vec::is_empty)
        && !filters
            .by_lsk_to_composable_cohorts
            .contains_key(&transition.leaf_state_key)
    {
        tally.add(Outcome::UnmappedTransition);
    }
}

pub(crate) fn admit_reconcile(
    partition_id: u16,
    merge: &MergeWorkerDeps,
    queue: &mut ReconcileQueue,
    marks: &mut BatchMarks,
    tile: &ReconcileTile,
    offset: SeedOffset,
) {
    if !merge.reconcile.enabled {
        counter!(SEED_TILES_SKIPPED_TOTAL, "reason" => "reconcile_disabled").increment(1);
        warn!(
            partition_id,
            team_id = tile.team_id().0,
            cohort_id = tile.cohort_id().0,
            run_id = %tile.run_id().0,
            "reconcile seed skipped while reconcile is disabled; re-dispatch after enabling",
        );
        marks.mark(offset);
        return;
    }

    let kind = tile.scope().kind();
    let deferred = match queue.supersede_if_newer(tile.team_id(), tile.cohort_id(), kind, offset.0)
    {
        SupersedeOutcome::NoQueuedJob => merge.seed_tracker.defer(partition_id as i32, offset.0),
        SupersedeOutcome::Replaced(superseded) => {
            let (replacement, outcome) = merge
                .seed_tracker
                .replace_deferred(superseded, offset.0)
                .expect("a queued reconcile must retain its deferred offset in the current tenure");
            if let MarkOutcome::CappedAheadOfDispatch = outcome {
                counter!(COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH).increment(1);
                warn!(
                    partition_id,
                    "superseded reconcile completion exceeded the seed dispatch ceiling",
                );
            }
            counter!(RECONCILE_JOBS_SUPERSEDED_TOTAL, "kind" => kind.as_str()).increment(1);
            replacement
        }
        SupersedeOutcome::RetainedNewerOrEqual => {
            counter!(SEED_TILES_SKIPPED_TOTAL, "reason" => "reconcile_stale_replay").increment(1);
            tracing::debug!(
                partition_id,
                team_id = tile.team_id().0,
                cohort_id = tile.cohort_id().0,
                run_id = %tile.run_id().0,
                offset = offset.0,
                "replayed reconcile seed retained the newer or equal queued job",
            );
            marks.mark(offset);
            return;
        }
    };

    queue.enqueue(tile.clone(), deferred);
    counter!(RECONCILE_JOBS_ENQUEUED_TOTAL, "kind" => kind.as_str()).increment(1);
}

pub(crate) fn tag_seed(changes: &mut [CohortMembershipChange], run_id: RunId) {
    for change in changes {
        change.origin = Some(ChangeOrigin::Seed);
        change.run_id = Some(run_id);
    }
}

/// Advance the seed tracker past `offset`. A mark beyond the dispatch ceiling is capped and counted.
pub(crate) fn mark_processed(tracker: &OffsetTracker, partition_id: u16, offset: SeedOffset) {
    if let MarkOutcome::CappedAheadOfDispatch =
        tracker.mark_processed(partition_id as i32, offset.0 + 1)
    {
        counter!(COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH).increment(1);
        warn!(
            partition_id,
            next_offset = offset.0 + 1,
            "seed offset mark exceeded the dispatch ceiling and was capped (F1 invariant violation)",
        );
    }
}

/// Pin the seed commit floor at the failed offset so Kafka redelivers it; emit
/// [`SEED_HELD_OFFSET_GAUGE`] so the stall is visible.
pub(crate) fn hold(tracker: &OffsetTracker, partition_id: u16, offset: SeedOffset) {
    let floor = tracker.hold(partition_id as i32, offset.0);
    let partition: Arc<str> = Arc::from(partition_id.to_string());
    metrics::gauge!(SEED_HELD_OFFSET_GAUGE, "partition" => partition).set(floor as f64);
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
    fn entry(&mut self, team_id: TeamId, person: Uuid, run: RunId) -> &mut PersonTouch {
        self.per_person
            .entry((team_id, person))
            .or_insert_with(|| PersonTouch {
                run,
                leaves: BTreeSet::new(),
            })
    }

    pub(crate) fn touch(&mut self, team_id: TeamId, person: Uuid, run: RunId, leaf: LeafStateKey) {
        let touch = self.entry(team_id, person, run);
        // Last call wins, and the heads call in offset order: the person stays in one recompose
        // group under the run of the last seed that touched them.
        touch.run = run;
        touch.leaves.insert(leaf);
    }

    /// Admit a leaf the register diff found lagging. The person's provenance stays with the fold's
    /// last seed; the leaf's run counts only for a person the fold never admitted.
    pub(crate) fn touch_lagging(
        &mut self,
        team_id: TeamId,
        person: Uuid,
        run: RunId,
        leaf: LeafStateKey,
    ) {
        self.entry(team_id, person, run).leaves.insert(leaf);
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

/// One thing a run did, held as data until the boundary that makes it exactly-once. Exhaustive, so
/// a new outcome cannot be counted mid-flight by accident.
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
    UnmappedTransition,
    ReKeyed(SeedKind),
}

impl Outcome {
    /// Whether the stage-1 commit is this outcome's exactly-once boundary.
    ///
    /// These three say the run *advanced* durable state. Once that commit lands, a replay folds
    /// the same seeds to `Unchanged` over their own rows and mints nothing, so deferring them any
    /// further loses a held run's work for good. Every other outcome is re-derived identically by
    /// a replay — a drop drops again, an idempotent merge is unchanged again — so counting it
    /// before the run settles would count it once per attempt.
    fn durable_at_stage1(self) -> bool {
        matches!(
            self,
            Self::TileApplied(_)
                | Self::PersonApplied(_)
                | Self::Stage1Transition(_)
                | Self::UnmappedTransition
        )
    }
}

/// A run's non-failure counts, each held until the boundary that makes it exactly-once: the
/// stage-1 commit for work that moved durable state, the settled run for everything else.
#[derive(Debug, Default)]
pub(crate) struct Tally {
    durable: BTreeMap<Outcome, u64>,
    settled: BTreeMap<Outcome, u64>,
}

impl Tally {
    pub(crate) fn add(&mut self, outcome: Outcome) {
        let half = if outcome.durable_at_stage1() {
            &mut self.durable
        } else {
            &mut self.settled
        };
        *half.entry(outcome).or_default() += 1;
    }

    /// Publish the half the stage-1 commit just made durable. Call only once that commit returned
    /// `Ok`, so a hold before it re-mints these on replay instead of double-counting them.
    fn record_durable(&mut self) {
        record_outcomes(std::mem::take(&mut self.durable));
    }

    fn record(self) {
        debug_assert!(
            self.durable.is_empty(),
            "the stage-1 commit publishes the durable half",
        );
        record_outcomes(self.settled);
    }
}

fn record_outcomes(outcomes: BTreeMap<Outcome, u64>) {
    for (outcome, count) in outcomes {
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
            Outcome::UnmappedTransition => {
                counter!(OUTPUT_TRANSITIONS_UNMAPPED, "reason" => "no_emitting_cohort")
                    .increment(count);
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
                    self.recompose.touch_lagging(
                        team_id,
                        leaf.person_id,
                        leaf.run_id,
                        leaf.leaf_state_key,
                    );
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
        let mut tally = self.tally;
        // The run's advances are durable here, and a replay would fold them to `Unchanged` over
        // their own rows and mint nothing, so a later hold would drop these counts for good.
        tally.record_durable();
        Ok(Committed {
            span: self.span,
            recompute: self.recompute,
            recompose: self.recompose,
            schedules: self.schedules,
            re_keys: self.re_keys,
            tally,
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
    ///
    /// The two output legs decide the run here. The hand-off leg does not: it is carried past the
    /// stage-2 commit, because a run mixes local and redirected seeds and a hand-off that failed
    /// says nothing about what downstream was told.
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
        Ok(Produced {
            span,
            stage2,
            tally,
            re_key_errors: re_key,
        })
    }
}

#[must_use]
struct Produced {
    span: OffsetSpan,
    stage2: Stage2Recompute,
    tally: Tally,
    /// Hand-offs that did not ack. Held until after the stage-2 commit; see
    /// [`Produced::commit_stage2`].
    re_key_errors: usize,
}

impl Produced {
    /// The composed bits and the single-leaf register bits commit only after the produce acks, so
    /// a failed produce is re-derived on replay instead of lost against a flipped bit.
    ///
    /// A failed hand-off still holds the run, but only once these bits are committed. The
    /// membership leg acked, so downstream holds the new truth and the register has to say so: the
    /// cascade for that flip is co-partitioned and is consumed right after this run, and it reads
    /// the referenced cohort's *stored* bit. Leaving that bit unwritten makes the cascade read the
    /// referrer as unchanged and mark itself, and every referring cohort stays stale until the next
    /// tenure replays the run. The replay is clean either way: the local seeds fold to `Unchanged`
    /// over their own rows, the register agrees, and only the hand-off is produced again.
    async fn commit_stage2(self, deps: ApplyDeps<'_>) -> Result<Settled, SeedHold> {
        commit_stage2_writes(deps.handle, &self.stage2.writes)
            .await
            .map_err(SeedHold::store(ApplyStage::Stage2Commit))?;
        // Committed, so a redelivery cannot double-count these and a hold cannot lose them.
        self.stage2.record_metrics();
        Ok(Settled {
            span: self.span,
            tally: self.tally,
            re_key_errors: self.re_key_errors,
        })
    }
}

#[must_use]
struct Settled {
    span: OffsetSpan,
    tally: Tally,
    re_key_errors: usize,
}

impl Settled {
    /// Everything the run counted, emitted once its offsets are safe to mark.
    ///
    /// A failed hand-off holds the run here, after its stage-2 commit; see
    /// [`Produced::commit_stage2`] for why the commit must not wait on that leg.
    fn record(self) -> Result<OffsetSpan, SeedHold> {
        require_acked(ProduceLeg::ReKey, self.re_key_errors)?;
        self.tally.record();
        Ok(self.span)
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

    settled.record()
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
    use chrono_tz::UTC;
    use metrics_exporter_prometheus::PrometheusBuilder;

    use crate::filters::TeamFiltersBuilder;

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

        assert_eq!(tally.durable[&Outcome::TileApplied("behavioral_single")], 2);
        assert_eq!(tally.settled[&Outcome::PersonUnchanged], 1);
    }

    /// The split is what makes each half exactly-once. An advance the replay cannot re-mint has to
    /// publish at the stage-1 commit; anything a replay repeats has to wait for the run to settle,
    /// or a hold counts it once per attempt.
    #[test]
    fn a_tally_splits_advances_from_what_a_replay_repeats() {
        for outcome in [
            Outcome::TileApplied("behavioral_single"),
            Outcome::PersonApplied("fresh"),
            Outcome::Stage1Transition("entered"),
            Outcome::UnmappedTransition,
        ] {
            assert!(
                outcome.durable_at_stage1(),
                "{outcome:?} advanced durable state, so the replay mints nothing",
            );
        }
        for outcome in [
            Outcome::TileUnchanged("behavioral_single"),
            Outcome::TileDropped("corrupt_state"),
            Outcome::PersonUnchanged,
            Outcome::PersonSkipped("stale_vs_live"),
            Outcome::PersonDropped("team_absent"),
            Outcome::ReKeyed(SeedKind::Tile),
        ] {
            assert!(
                !outcome.durable_at_stage1(),
                "a replay derives {outcome:?} again",
            );
        }
    }

    /// A run held after its stage-1 commit must not publish the advances that commit already
    /// counted a second time when it settles.
    #[test]
    fn the_durable_half_publishes_once() {
        let mut tally = Tally::default();
        tally.add(Outcome::TileApplied("behavioral_single"));
        tally.add(Outcome::PersonUnchanged);
        tally.record_durable();

        assert!(tally.durable.is_empty(), "drained by the stage-1 commit");
        assert_eq!(
            tally.settled[&Outcome::PersonUnchanged],
            1,
            "what a replay repeats still waits for the run to settle",
        );
    }

    #[test]
    fn an_unmapped_transition_publishes_once_at_the_stage1_boundary() {
        let recorder = PrometheusBuilder::new().build_recorder();
        let handle = recorder.handle();
        let filters = TeamFiltersBuilder::default().freeze(UTC);
        let transition = LeafTransition {
            team_id: TeamId(7),
            leaf_state_key: LeafStateKey([0xEE; 16]),
            person_id: Uuid::from_u128(1),
            condition_hash: [0xDD; 16],
            kind: crate::stage1::transition::TransitionKind::Entered,
        };
        let mut tally = Tally::default();
        record_stage1_transition(&mut tally, &filters, &transition);

        metrics::with_local_recorder(&recorder, || {
            tally.record_durable();
            tally.record_durable();
            tally.record();
        });

        assert!(handle
            .render()
            .contains("output_transitions_unmapped_total{reason=\"no_emitting_cohort\"} 1"));
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
        touched.touch_lagging(team, alice, first, LeafStateKey([3; 16]));

        let groups = touched.groups();
        assert_eq!(groups.len(), 1, "one call, not one per seed");
        assert_eq!(
            groups[&(team, last)],
            vec![
                (LeafStateKey([1; 16]), alice),
                (LeafStateKey([2; 16]), alice),
                (LeafStateKey([3; 16]), alice),
            ],
            "every leaf rides the last seed's run; a lagging leaf joins without moving it",
        );
    }
}
