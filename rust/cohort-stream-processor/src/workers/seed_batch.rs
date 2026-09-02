//! Batched seed apply: a channel batch's seeds become same-kind runs, and each run reaches exactly
//! one mark or one hold.
//!
//! Applying seeds one at a time costs one awaited produce per seed that flips anything, so a worker
//! spends its time waiting on Kafka instead of folding. A run amortizes that: one read pass, one
//! produce of the fold's own output, one stage-1 commit, one stage-2 recompute over the
//! deduplicated leaves, one produce of the composed flips, one produce of the cascades, one stage-2
//! commit, one mark. Every produce acks before the state it reports commits, so a failed leg holds
//! the run's *first* offset with its durable effects either absent or idempotently re-appliable,
//! and the redelivery replays the whole run.
//!
//! This module owns the run boundaries and the vocabulary both pipelines share (offsets, spans,
//! stages, holds, the produce legs). Each fold lives with its seed kind: tiles in
//! [`seed_path`](super::seed_path), person seeds in [`person_seed_path`](super::person_seed_path).

use std::collections::{BTreeMap, BTreeSet};
use std::num::NonZeroUsize;
use std::sync::Arc;
use std::time::Instant;

use cohort_core::seed::{PersonSeed, ReconcileTile, RunId, SeedTile};
use metrics::{counter, histogram};
use uuid::Uuid;

use crate::cascade::CascadeMessage;
use crate::consumers::seeds::{SeedSkipReason, SeedWork};
use crate::filters::manager::CatalogHandle;
use crate::filters::reverse_index::TeamFilters;
use crate::filters::{FilterCatalog, TeamId};
use crate::observability::metrics::{
    PERSON_SEED_REKEYED_TOTAL, PERSON_SEED_REKEY_PRODUCE_FAILURE_TOTAL,
    SEED_APPLY_BATCHES_CLOSED_TOTAL, SEED_APPLY_BATCHES_HELD_TOTAL,
    SEED_APPLY_BATCH_DURATION_SECONDS, SEED_APPLY_BATCH_SIZE, SEED_REKEYED_TOTAL,
    SEED_REKEY_PRODUCE_FAILURE_TOTAL, SEED_TILES_SKIPPED_TOTAL,
};
use crate::producer::{CohortMembershipChange, LastUpdatedClock, MembershipSink};
use crate::stage1::key::LeafStateKey;
use crate::stage2::state::Stage2State;
use crate::store::{BehavioralKey, ReadLane, Stage2Key, StoreError, StoreHandle};
use crate::sweep::EvictionQueue;
use crate::workers::merge_path::MergeWorkerDeps;
use crate::workers::person_seed_path::apply_person_batch;
use crate::workers::reconcile::ReconcileQueue;
use crate::workers::seed_path::{
    admit_reconcile, apply_tile_batch, hold, mark_processed, tag_seed,
};
use crate::workers::stage2_path::{recompute_stage2, Stage2Recompute};
use crate::workers::worker::{produce_cascades, produce_membership};

/// One message's offset on `cohort_stream_seed_events`. Distinct from every other topic's offsets,
/// which the seed tracker must never see.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) struct SeedOffset(pub i64);

/// The offsets a run must act on: `first` is what a failure holds, `last` is what a success marks.
/// Marking `last` releases every offset in between, which is exactly what a run that either wholly
/// succeeds or wholly replays needs.
///
/// `first` is the run's *lowest* offset, not its leading one. The seed consumer delivers in offset
/// order, but a hold above the true minimum would pin the commit floor past a seed that was never
/// applied, so the span is derived rather than assumed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct OffsetSpan {
    pub first: SeedOffset,
    pub last: SeedOffset,
}

/// One seed with the offset that must be marked or held for it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct Admitted<T> {
    pub work: T,
    pub offset: SeedOffset,
}

/// A non-empty run of one seed kind, applied as one unit. Construction is the only place emptiness
/// is checked, so [`span`](Self::span) can never be asked about a run with no offsets.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct SeedRun<T> {
    items: Vec<Admitted<T>>,
    span: OffsetSpan,
}

impl<T> SeedRun<T> {
    /// `None` for an empty run: a group with no offsets could neither mark nor hold.
    pub(crate) fn new(items: Vec<Admitted<T>>) -> Option<Self> {
        let first = items.iter().map(|item| item.offset).min()?;
        let last = items
            .iter()
            .map(|item| item.offset)
            .max()
            .expect("a run with a lowest offset has a highest one too");
        Some(Self {
            items,
            span: OffsetSpan { first, last },
        })
    }

    pub(crate) fn span(&self) -> OffsetSpan {
        self.span
    }

    pub(crate) fn len(&self) -> usize {
        self.items.len()
    }

    pub(crate) fn items(&self) -> &[Admitted<T>] {
        &self.items
    }
}

/// A channel batch's seeds, split so each group is applied by exactly one handler.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum SeedGroup {
    Tiles(SeedRun<SeedTile>),
    Persons(SeedRun<PersonSeed>),
    /// Control tiles stay single: admission defers one offset and orders one queue entry, which a
    /// run of them could not express.
    Reconcile(Admitted<ReconcileTile>),
    /// Consume-side skips stay single: each one commits its own offset and does no work.
    Skip(Admitted<SeedSkipReason>),
}

/// The two ceilings on one apply run. Both bound the unit of work a hold replays: `max_seeds` the
/// messages, `max_fanout` the leaf reads and recomputes they expand to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SeedBatchLimits {
    /// Seeds per run. `1` restores the per-seed apply, which is the hatch if batching misbehaves.
    pub max_seeds: NonZeroUsize,
    /// Fan-out units per run, as [`seed_fanout`] weighs them. A run closes before the seed that
    /// would exceed it; a seed heavier than the whole budget still runs alone.
    pub max_fanout: NonZeroUsize,
}

impl Default for SeedBatchLimits {
    /// Mirrors the `COHORT_SEED_APPLY_BATCH_MAX*` defaults, for deps built without explicit config.
    fn default() -> Self {
        Self {
            max_seeds: NonZeroUsize::new(256).expect("256 > 0"),
            max_fanout: NonZeroUsize::new(4096).expect("4096 > 0"),
        }
    }
}

/// How much work one seed expands to: one unit per leaf its condition reaches, plus one per cohort
/// each leaf backs (a single-leaf register write or a stage-2 recompute).
///
/// Pure. A seed the catalog cannot place weighs one, so a run of them is still bounded by the count
/// cap rather than by nothing. Control and skip seeds weigh nothing: they are always their own
/// group.
pub(crate) fn seed_fanout(catalog: &FilterCatalog, work: &SeedWork) -> usize {
    let reached = match work {
        SeedWork::Tile(tile) => catalog.team(tile.team_id()).map_or(0, |filters| {
            condition_fanout(filters, &tile.condition_hash().as_bytes())
        }),
        SeedWork::Person(seed) => catalog.team(seed.team_id()).map_or(0, |filters| {
            seed.evaluated()
                .iter()
                .map(|hash| hash.as_bytes())
                .filter(|hash| filters.person_property_conditions.contains(hash))
                .map(|hash| condition_fanout(filters, &hash))
                .sum()
        }),
        SeedWork::Reconcile(_) | SeedWork::Skip(_) => return 0,
    };
    reached.max(1)
}

fn condition_fanout(filters: &TeamFilters, condition_hash: &[u8; 16]) -> usize {
    let cohorts_backed = |lsk: &LeafStateKey| {
        filters
            .by_lsk_to_single_leaf_cohorts
            .get(lsk)
            .map_or(0, Vec::len)
            + filters
                .by_lsk_to_composable_cohorts
                .get(lsk)
                .map_or(0, Vec::len)
    };
    filters
        .by_condition_to_lsk
        .get(condition_hash)
        .map_or(0, |lsks| {
            lsks.iter().map(|lsk| 1 + cohorts_backed(lsk)).sum()
        })
}

/// Why a run closed. `count` should dominate; a `fanout` rate says the catalog fans seeds out far
/// wider than the defaults assume.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum CloseCause {
    Count,
    Fanout,
    /// The next seed is of another kind, or a control seed.
    KindChange,
    /// The channel batch ran out.
    End,
}

impl CloseCause {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Count => "count",
            Self::Fanout => "fanout",
            Self::KindChange => "kind_change",
            Self::End => "end",
        }
    }
}

/// Split `seeds` into same-kind runs in offset order, each within `limits` under `weigh`.
///
/// Pure and total: every input seed lands in exactly one group, and the groups' offsets stay in the
/// order they arrived, which is what keeps a reconcile tile behind its run's data tiles.
pub(crate) fn group_seeds(
    seeds: Vec<Admitted<SeedWork>>,
    limits: SeedBatchLimits,
    weigh: impl Fn(&SeedWork) -> usize,
) -> Vec<SeedGroup> {
    let mut groups = Vec::new();
    let mut tiles = OpenRun::new(SeedKind::Tile, SeedGroup::Tiles);
    let mut persons = OpenRun::new(SeedKind::Person, SeedGroup::Persons);

    for Admitted { work, offset } in seeds {
        let weight = weigh(&work);
        match work {
            SeedWork::Tile(tile) => {
                persons.close(CloseCause::KindChange, &mut groups);
                tiles.admit(Admitted { work: tile, offset }, weight, limits, &mut groups);
            }
            SeedWork::Person(seed) => {
                tiles.close(CloseCause::KindChange, &mut groups);
                persons.admit(Admitted { work: seed, offset }, weight, limits, &mut groups);
            }
            SeedWork::Reconcile(tile) => {
                tiles.close(CloseCause::KindChange, &mut groups);
                persons.close(CloseCause::KindChange, &mut groups);
                groups.push(SeedGroup::Reconcile(Admitted { work: tile, offset }));
            }
            SeedWork::Skip(reason) => {
                tiles.close(CloseCause::KindChange, &mut groups);
                persons.close(CloseCause::KindChange, &mut groups);
                groups.push(SeedGroup::Skip(Admitted {
                    work: reason,
                    offset,
                }));
            }
        }
    }

    tiles.close(CloseCause::End, &mut groups);
    persons.close(CloseCause::End, &mut groups);
    groups
}

/// A run of one kind still accepting seeds, with the fan-out it has admitted so far.
struct OpenRun<T> {
    kind: SeedKind,
    into: fn(SeedRun<T>) -> SeedGroup,
    items: Vec<Admitted<T>>,
    fanout: usize,
}

impl<T> OpenRun<T> {
    fn new(kind: SeedKind, into: fn(SeedRun<T>) -> SeedGroup) -> Self {
        Self {
            kind,
            into,
            items: Vec::new(),
            fanout: 0,
        }
    }

    /// Admit one seed, closing the run around it as the limits demand: before, when its weight
    /// would overflow the fan-out budget; after, when it fills the count.
    ///
    /// An empty run always admits, so a seed heavier than the whole budget still applies alone
    /// instead of never being marked or held.
    fn admit(
        &mut self,
        item: Admitted<T>,
        weight: usize,
        limits: SeedBatchLimits,
        groups: &mut Vec<SeedGroup>,
    ) {
        let overflows = self.fanout.saturating_add(weight) > limits.max_fanout.get();
        if overflows && !self.items.is_empty() {
            self.close(CloseCause::Fanout, groups);
        }
        self.items.push(item);
        self.fanout = self.fanout.saturating_add(weight);
        if self.items.len() >= limits.max_seeds.get() {
            self.close(CloseCause::Count, groups);
        }
    }

    /// Close the run, if non-empty, as one group.
    fn close(&mut self, cause: CloseCause, groups: &mut Vec<SeedGroup>) {
        let Some(run) = SeedRun::new(std::mem::take(&mut self.items)) else {
            return;
        };
        self.fanout = 0;
        counter!(
            SEED_APPLY_BATCHES_CLOSED_TOTAL,
            "kind" => self.kind.as_str(),
            "cause" => cause.as_str(),
        )
        .increment(1);
        groups.push((self.into)(run));
    }
}

/// Which apply pipeline a batch metric belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum SeedKind {
    Tile,
    Person,
}

impl SeedKind {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Tile => "tile",
            Self::Person => "person",
        }
    }
}

/// The ordered steps every seed batch takes. Doubles as the `stage` metric label, so the histogram
/// and the held counter can never name a step the pipeline does not have.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ApplyStage {
    /// Tombstone resolution and cross-partition routing.
    Resolve,
    /// The batched state read that seeds the overlay.
    Read,
    /// The pure fold of every seed into the overlay.
    Fold,
    /// Leg 1: the fold's single-leaf changes and the run's re-keys, before anything commits.
    ProduceLeaf,
    Stage1Commit,
    Recompute,
    /// Leg 2: the recompose's composed flips, before their bits commit.
    ProduceComposed,
    /// Leg 3: first-hop cascades for every change the run emitted, after both membership legs
    /// acked.
    ProduceCascades,
    Stage2Commit,
}

impl ApplyStage {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Resolve => "resolve",
            Self::Read => "read",
            Self::Fold => "fold",
            Self::ProduceLeaf => "produce_leaf",
            Self::Stage1Commit => "stage1_commit",
            Self::Recompute => "recompute",
            Self::ProduceComposed => "produce_composed",
            Self::ProduceCascades => "produce_cascades",
            Self::Stage2Commit => "stage2_commit",
        }
    }
}

impl std::fmt::Display for ApplyStage {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Which output a batch's produce failed on. The leg names the topic for the operator and the
/// stage for the metric, so one failure can never be filed under the wrong step.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ProduceLeg {
    /// Single-leaf membership, minted by the fold.
    LeafMembership,
    /// Composed membership, minted by the stage-2 recompose.
    ComposedMembership,
    Cascade,
    /// The cross-partition hand-off back onto the seed topic.
    ReKey,
}

impl ProduceLeg {
    pub(crate) fn stage(self) -> ApplyStage {
        match self {
            Self::LeafMembership | Self::ReKey => ApplyStage::ProduceLeaf,
            Self::ComposedMembership => ApplyStage::ProduceComposed,
            Self::Cascade => ApplyStage::ProduceCascades,
        }
    }
}

impl std::fmt::Display for ProduceLeg {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            Self::LeafMembership => "leaf membership",
            Self::ComposedMembership => "composed membership",
            Self::Cascade => "cascade",
            Self::ReKey => "re-key",
        })
    }
}

/// A failure that must not commit. Every pipeline step that can leave durable state half-written
/// returns this, so the `Ok ⇒ mark, Err ⇒ hold` decision lives at one site per pipeline.
#[derive(Debug, thiserror::Error)]
pub(crate) enum SeedHold {
    #[error("{stage}: {source}")]
    Store {
        stage: ApplyStage,
        source: StoreError,
    },
    #[error("{leg} produce: {errors} message(s) failed")]
    Produce { leg: ProduceLeg, errors: usize },
    /// A batched read did not answer every key it was asked about. RocksDB answers one slot per
    /// key, so this is a backend contract break rather than a data problem — and pairing a slot
    /// with the wrong key would fold one person's tile onto another person's state, so the run
    /// holds instead.
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
            Self::Produce { leg, .. } => leg.stage(),
        }
    }
}

/// Splits one batch's wall clock into per-stage samples: each [`mark`](Self::mark) records the time
/// since the previous one. A batch that holds records no sample for the failed stage — the held
/// counter carries that instead, so the histogram stays a picture of completed work.
pub(crate) struct StageClock {
    kind: SeedKind,
    last: Instant,
}

impl StageClock {
    pub(crate) fn start(kind: SeedKind, size: usize) -> Self {
        histogram!(SEED_APPLY_BATCH_SIZE, "kind" => kind.as_str()).record(size as f64);
        Self {
            kind,
            last: Instant::now(),
        }
    }

    pub(crate) fn mark(&mut self, stage: ApplyStage) {
        let now = Instant::now();
        histogram!(
            SEED_APPLY_BATCH_DURATION_SECONDS,
            "kind" => self.kind.as_str(),
            "stage" => stage.as_str(),
        )
        .record(now.duration_since(self.last).as_secs_f64());
        self.last = now;
    }
}

/// Everything an apply pipeline borrows for a whole channel batch. All shared, so the worker stays
/// the single owner of its mutable state (eviction queue, reconcile queue, output clock).
#[derive(Clone, Copy)]
pub(crate) struct SeedApplyDeps<'a> {
    pub partition_id: u16,
    pub handle: &'a StoreHandle,
    pub catalog: &'a CatalogHandle,
    pub sink: &'a Arc<dyn MembershipSink>,
    pub merge: &'a MergeWorkerDeps,
}

/// A batch's cross-partition hand-offs. One kind per batch, because a group is one kind.
#[derive(Debug)]
pub(crate) enum SeedReKeys {
    Tiles(Vec<SeedTile>),
    Persons(Vec<PersonSeed>),
}

/// Leg 1: produce the fold's single-leaf changes and the run's re-keys together, before anything
/// commits.
///
/// Both are minted by the pure fold, so a failure here leaves the store untouched and the
/// redelivery re-folds the same seeds and re-emits them. The two topics are independent, so issuing
/// them together costs one round trip instead of two.
pub(crate) async fn produce_leaf_output(
    deps: &SeedApplyDeps<'_>,
    changes: Vec<CohortMembershipChange>,
    re_keys: SeedReKeys,
) -> Result<(), SeedHold> {
    let (membership_errors, re_key_errors) = tokio::join!(
        produce_membership_if_any(deps.sink, changes),
        produce_re_keys(deps.merge, re_keys),
    );
    require_acked(ProduceLeg::LeafMembership, membership_errors)?;
    require_acked(ProduceLeg::ReKey, re_key_errors)
}

/// Leg 2: produce the recompose's composed flips, after the stage-1 commit and before the stage-2
/// commit, so a failure leaves their bits unwritten and the redelivery re-derives them.
pub(crate) async fn produce_composed_output(
    deps: &SeedApplyDeps<'_>,
    changes: Vec<CohortMembershipChange>,
) -> Result<(), SeedHold> {
    let errors = produce_membership_if_any(deps.sink, changes).await;
    require_acked(ProduceLeg::ComposedMembership, errors)
}

/// Leg 3: produce the first-hop cascades of every change the run emitted, once both membership
/// legs have acked, so a referrer can never learn of a flip before the membership topic does.
pub(crate) async fn produce_cascade_output(
    deps: &SeedApplyDeps<'_>,
    cascades: Vec<CascadeMessage>,
) -> Result<(), SeedHold> {
    let errors = produce_cascades(deps.merge, cascades).await;
    require_acked(ProduceLeg::Cascade, errors)
}

fn require_acked(leg: ProduceLeg, errors: usize) -> Result<(), SeedHold> {
    if errors == 0 {
        return Ok(());
    }
    Err(SeedHold::Produce { leg, errors })
}

async fn produce_membership_if_any(
    sink: &Arc<dyn MembershipSink>,
    changes: Vec<CohortMembershipChange>,
) -> usize {
    if changes.is_empty() {
        return 0;
    }
    produce_membership(sink, changes).await
}

/// Re-produce a batch's hand-offs, awaiting exactly one `Ok` per seed. A re-keyed seed has no other
/// copy, so a short ack vector is a failure, never a vacuous success.
async fn produce_re_keys(merge: &MergeWorkerDeps, re_keys: SeedReKeys) -> usize {
    match re_keys {
        SeedReKeys::Tiles(tiles) => {
            if tiles.is_empty() {
                return 0;
            }
            let expected = tiles.len();
            let acks = merge.seed_tile_sink.produce(tiles).await;
            let errors = ack_errors(&acks, expected);
            if errors > 0 {
                counter!(SEED_REKEY_PRODUCE_FAILURE_TOTAL).increment(errors as u64);
            } else {
                counter!(SEED_REKEYED_TOTAL).increment(expected as u64);
            }
            errors
        }
        SeedReKeys::Persons(seeds) => {
            if seeds.is_empty() {
                return 0;
            }
            let expected = seeds.len();
            let acks = merge.seed_tile_sink.produce_person(seeds).await;
            let errors = ack_errors(&acks, expected);
            if errors > 0 {
                counter!(PERSON_SEED_REKEY_PRODUCE_FAILURE_TOTAL).increment(errors as u64);
            } else {
                counter!(PERSON_SEED_REKEYED_TOTAL).increment(expected as u64);
            }
            errors
        }
    }
}

fn ack_errors<E>(acks: &[Result<(), E>], expected: usize) -> usize {
    acks.iter().filter(|result| result.is_err()).count() + acks.len().abs_diff(expected)
}

/// The persons a batch touched: which leaves each one needs recomposed, and the run of the last
/// seed that touched them, which is the provenance its recomposed changes carry.
///
/// Keeping a person whole matters: splitting their leaves across two recompose calls would evaluate
/// the same cohort twice against the same uncommitted bit and emit the flip twice.
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
        touch.run = run;
        touch.leaves.insert(leaf);
    }

    pub(crate) fn is_empty(&self) -> bool {
        self.per_person.is_empty()
    }

    /// One recompose call per `(team, run)`: the team owns the catalog that composes the leaves, the
    /// run owns their provenance tag.
    fn groups(self) -> BTreeMap<(TeamId, RunId), Vec<(LeafStateKey, Uuid)>> {
        let mut groups: BTreeMap<(TeamId, RunId), Vec<(LeafStateKey, Uuid)>> = BTreeMap::new();
        for ((team_id, person), touch) in self.per_person {
            let group = groups.entry((team_id, touch.run)).or_default();
            group.extend(touch.leaves.into_iter().map(|leaf| (leaf, person)));
        }
        groups
    }
}

/// A batch's stage-2 recompose, uncommitted: the flips to produce and the `cf_stage2` writes that
/// may land only once those produces ack.
#[derive(Default)]
pub(crate) struct BatchRecompose {
    pub changes: Vec<CohortMembershipChange>,
    pub writes: Vec<(Stage2Key, Stage2State)>,
    recomputes: Vec<Stage2Recompute>,
}

impl BatchRecompose {
    /// Call only once the writes committed, so a failed commit's redelivery cannot double-count.
    pub(crate) fn record_metrics(&self) {
        for recompute in &self.recomputes {
            recompute.record_metrics();
        }
    }
}

/// Recompose stage 2 for everything the batch touched, once per `(team, run)`.
///
/// The changes carry one batch-final `last_updated`, newer than every single-leaf change the fold
/// minted, so a composed flip wins LWW against the leaf flip that caused it.
pub(crate) async fn recompose_batch(
    deps: &SeedApplyDeps<'_>,
    snapshot: &FilterCatalog,
    touched: TouchedPersons,
    now_ms: i64,
    clock: &mut LastUpdatedClock,
) -> Result<BatchRecompose, SeedHold> {
    if touched.is_empty() {
        return Ok(BatchRecompose::default());
    }
    let last_updated = clock.next();

    let mut recomposed = BatchRecompose::default();
    for ((team_id, run), leaves) in touched.groups() {
        // Only teams this same snapshot already resolved reach here, so the miss arm is dead; it
        // degrades to skipping one team's recompose rather than killing the partition worker.
        let Some(filters) = snapshot.team(team_id) else {
            continue;
        };
        let mut recompute = recompute_stage2(
            deps.partition_id,
            deps.handle,
            filters,
            &leaves,
            now_ms,
            &last_updated,
            ReadLane::Maintenance,
        )
        .await
        .map_err(SeedHold::store(ApplyStage::Recompute))?;

        // The changes are cloned rather than moved: `record_metrics` counts them after the commit.
        let mut changes = recompute.changes.clone();
        tag_seed(&mut changes, run);
        recomposed.changes.extend(changes);
        recomposed
            .writes
            .extend(std::mem::take(&mut recompute.writes));
        recomposed.recomputes.push(recompute);
    }
    Ok(recomposed)
}

/// Settle one batch: mark its whole span, or hold its first offset and count the failed stage.
pub(crate) fn settle(
    deps: &SeedApplyDeps<'_>,
    kind: SeedKind,
    span: OffsetSpan,
    outcome: Result<(), SeedHold>,
) {
    match outcome {
        Ok(()) => mark_processed(&deps.merge.seed_tracker, deps.partition_id, span.last),
        Err(held) => {
            counter!(
                SEED_APPLY_BATCHES_HELD_TOTAL,
                "kind" => kind.as_str(),
                "stage" => held.stage().as_str(),
            )
            .increment(1);
            tracing::warn!(
                partition_id = deps.partition_id,
                kind = kind.as_str(),
                first_offset = span.first.0,
                last_offset = span.last.0,
                error = %held,
                "seed batch apply failed; holding the batch's first seed offset for redelivery",
            );
            hold(&deps.merge.seed_tracker, deps.partition_id, span.first);
        }
    }
}

/// Apply one channel batch's seed groups in order on the owning partition worker.
///
/// A group that holds pins the commit floor at its own first offset; later groups still run and
/// mark, and the floor keeps their marks from leapfrogging the hold — the same envelope as the
/// per-seed path, now at batch granularity.
pub(crate) async fn handle_seed_groups(
    deps: SeedApplyDeps<'_>,
    queue: &mut EvictionQueue<BehavioralKey>,
    reconcile_queue: &mut ReconcileQueue,
    clock: &mut LastUpdatedClock,
    groups: Vec<SeedGroup>,
) {
    for group in groups {
        match group {
            SeedGroup::Tiles(run) => apply_tile_batch(&deps, queue, clock, run).await,
            SeedGroup::Persons(run) => apply_person_batch(&deps, clock, run).await,
            SeedGroup::Reconcile(admitted) => admit_reconcile(
                deps.partition_id,
                deps.merge,
                reconcile_queue,
                &admitted.work,
                admitted.offset,
            ),
            SeedGroup::Skip(admitted) => {
                counter!(SEED_TILES_SKIPPED_TOTAL, "reason" => admitted.work.as_str()).increment(1);
                mark_processed(&deps.merge.seed_tracker, deps.partition_id, admitted.offset);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU32;

    use cohort_core::seed::{
        BehavioralShapeHash, ClaimEpoch, ConditionHash, ReconcileScope, RunId, SChunkMs,
        ScannedAtMs,
    };
    use uuid::Uuid;

    use serde_json::{json, Value};

    use crate::filters::{CohortId, TeamFiltersBuilder, TeamId};

    use super::*;

    const TEAM: TeamId = TeamId(7);

    fn hash() -> ConditionHash {
        ConditionHash::parse("0123456789abcdef").unwrap()
    }

    fn tile() -> SeedTile {
        SeedTile::new(
            TEAM,
            Uuid::from_u128(1),
            hash(),
            NonZeroU32::new(1).unwrap(),
            20_614,
            SChunkMs(1),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        )
    }

    fn person() -> PersonSeed {
        PersonSeed::new(
            TEAM,
            Uuid::from_u128(2),
            vec![hash()],
            vec![],
            ScannedAtMs(1),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        )
        .unwrap()
    }

    fn reconcile() -> ReconcileTile {
        ReconcileTile::new(
            TEAM,
            CohortId(1),
            ReconcileScope::Behavioral(BehavioralShapeHash::parse("0123456789abcdef").unwrap()),
            RunId(Uuid::nil()),
        )
    }

    fn admitted(work: SeedWork, offset: i64) -> Admitted<SeedWork> {
        Admitted {
            work,
            offset: SeedOffset(offset),
        }
    }

    /// The offsets each group would act on: `(first, last)` per group, in group order.
    fn spans(groups: &[SeedGroup]) -> Vec<(i64, i64)> {
        groups
            .iter()
            .map(|group| match group {
                SeedGroup::Tiles(run) => (run.span().first.0, run.span().last.0),
                SeedGroup::Persons(run) => (run.span().first.0, run.span().last.0),
                SeedGroup::Reconcile(admitted) => (admitted.offset.0, admitted.offset.0),
                SeedGroup::Skip(admitted) => (admitted.offset.0, admitted.offset.0),
            })
            .collect()
    }

    fn limits(max_seeds: usize, max_fanout: usize) -> SeedBatchLimits {
        SeedBatchLimits {
            max_seeds: NonZeroUsize::new(max_seeds).unwrap(),
            max_fanout: NonZeroUsize::new(max_fanout).unwrap(),
        }
    }

    /// Group under the count cap alone: every seed weighs one and the fan-out budget is unbounded.
    fn group_by_count(seeds: Vec<Admitted<SeedWork>>, max_seeds: usize) -> Vec<SeedGroup> {
        group_seeds(seeds, limits(max_seeds, usize::MAX), |_| 1)
    }

    fn tiles(offsets: std::ops::Range<i64>) -> Vec<Admitted<SeedWork>> {
        offsets
            .map(|offset| admitted(SeedWork::Tile(tile()), offset))
            .collect()
    }

    /// A run that leaked across a kind boundary would hand tiles to the person fold, or hand a
    /// reconcile tile's offset to a batch that marks past it.
    #[test]
    fn runs_break_at_every_kind_change_and_control_seeds_stay_single() {
        let groups = group_by_count(
            vec![
                admitted(SeedWork::Tile(tile()), 0),
                admitted(SeedWork::Tile(tile()), 1),
                admitted(SeedWork::Person(person()), 2),
                admitted(SeedWork::Reconcile(reconcile()), 3),
                admitted(SeedWork::Tile(tile()), 4),
                admitted(SeedWork::Skip(SeedSkipReason::UnknownKind), 5),
                admitted(SeedWork::Tile(tile()), 6),
            ],
            256,
        );

        assert!(matches!(groups[0], SeedGroup::Tiles(ref run) if run.len() == 2));
        assert!(matches!(groups[1], SeedGroup::Persons(ref run) if run.len() == 1));
        assert!(matches!(groups[2], SeedGroup::Reconcile(_)));
        assert!(matches!(groups[3], SeedGroup::Tiles(ref run) if run.len() == 1));
        assert!(matches!(groups[4], SeedGroup::Skip(_)));
        assert!(matches!(groups[5], SeedGroup::Tiles(ref run) if run.len() == 1));
        assert_eq!(
            spans(&groups),
            vec![(0, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6)],
            "every group holds its own first and marks its own last",
        );
    }

    #[test]
    fn a_run_longer_than_the_cap_splits_into_capped_groups() {
        let groups = group_by_count(tiles(0..7), 3);

        assert_eq!(groups.len(), 3);
        assert_eq!(spans(&groups), vec![(0, 2), (3, 5), (6, 6)]);
    }

    /// The zero-cost hatch: `COHORT_SEED_APPLY_BATCH_MAX=1` must reproduce the per-seed apply.
    #[test]
    fn a_cap_of_one_yields_one_group_per_seed() {
        let groups = group_by_count(tiles(0..3), 1);

        assert_eq!(spans(&groups), vec![(0, 0), (1, 1), (2, 2)]);
    }

    #[test]
    fn an_empty_batch_yields_no_groups() {
        assert!(group_by_count(Vec::new(), 256).is_empty());
    }

    /// The budget bounds what a run expands to, so it has to be checked before a seed is admitted:
    /// applied after, every run would overshoot by one seed's whole fan-out.
    #[test]
    fn a_run_closes_before_the_next_seed_would_exceed_the_fanout_budget() {
        let groups = group_seeds(tiles(0..5), limits(256, 10), |_| 4);

        assert_eq!(spans(&groups), vec![(0, 1), (2, 3), (4, 4)]);
    }

    /// A seed heavier than the whole budget can never fit, so an empty run must still admit it:
    /// refusing would leave the seed neither marked nor held, and the partition wedged behind it.
    #[test]
    fn a_seed_heavier_than_the_whole_budget_still_forms_a_run_of_one() {
        let groups = group_seeds(tiles(0..3), limits(256, 10), |_| 1000);

        assert_eq!(spans(&groups), vec![(0, 0), (1, 1), (2, 2)]);
    }

    /// The weight is the work a seed expands to: the leaves its condition reaches and the cohorts
    /// each leaf backs. Counting leaves alone would let a hash shared by many cohorts weigh one.
    #[test]
    fn seed_fanout_counts_the_cohorts_a_condition_reaches_not_its_leaves() {
        const SHARED: &str = "0123456789abcdef";
        const PAIRED: &str = "fedcba9876543210";
        const PERSON: &str = "person0000000001";
        let behavioral = |condition_hash: &str| {
            json!({
                "type": "behavioral", "value": "performed_event", "key": "$pageview",
                "time_value": 7, "time_interval": "day",
                "conditionHash": condition_hash,
                "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
            })
        };
        let person_property = json!({
            "type": "person", "key": "email", "value": "a@b.com", "operator": "exact",
            "conditionHash": PERSON,
            "bytecode": ["_H", 1, 32, "a@b.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        });
        let cohort =
            |leaves: Vec<Value>| json!({ "properties": { "type": "AND", "values": leaves } });
        let mut builder = TeamFiltersBuilder::default();
        // Three single-leaf cohorts and two composable ones share the leaf behind SHARED.
        for id in 1..=3 {
            builder
                .add_cohort(CohortId(id), TEAM, &cohort(vec![behavioral(SHARED)]))
                .unwrap();
        }
        for id in 4..=5 {
            builder
                .add_cohort(
                    CohortId(id),
                    TEAM,
                    &cohort(vec![behavioral(SHARED), behavioral(PAIRED)]),
                )
                .unwrap();
        }
        builder
            .add_cohort(CohortId(6), TEAM, &cohort(vec![person_property]))
            .unwrap();
        let catalog = FilterCatalog::from_teams([(TEAM, builder.freeze(chrono_tz::UTC))]);
        let tile_with = |team: TeamId, condition_hash: &str| {
            SeedWork::Tile(SeedTile::new(
                team,
                Uuid::from_u128(1),
                ConditionHash::parse(condition_hash).unwrap(),
                NonZeroU32::new(1).unwrap(),
                20_614,
                SChunkMs(1),
                RunId(Uuid::nil()),
                ClaimEpoch(1),
            ))
        };

        assert_eq!(
            seed_fanout(&catalog, &tile_with(TEAM, SHARED)),
            6,
            "one leaf, plus three single-leaf and two composable cohorts",
        );
        assert_eq!(
            seed_fanout(&catalog, &tile_with(TEAM, PAIRED)),
            3,
            "one leaf, plus the two composable cohorts alone",
        );
        assert_eq!(
            seed_fanout(&catalog, &tile_with(TEAM, "no_such_cond0000")),
            1,
            "a hash the catalog no longer resolves still weighs one",
        );
        assert_eq!(
            seed_fanout(&catalog, &tile_with(TeamId(99), SHARED)),
            1,
            "an unknown team still weighs one",
        );

        let person_seed = SeedWork::Person(
            PersonSeed::new(
                TEAM,
                Uuid::from_u128(2),
                // SHARED is behavioral, so the person path drops it before it can weigh anything.
                vec![
                    ConditionHash::parse(SHARED).unwrap(),
                    ConditionHash::parse(PERSON).unwrap(),
                ],
                vec![],
                ScannedAtMs(1),
                RunId(Uuid::nil()),
                ClaimEpoch(1),
            )
            .unwrap(),
        );
        assert_eq!(
            seed_fanout(&catalog, &person_seed),
            2,
            "the person leaf plus its one single-leaf cohort; the behavioral hash weighs nothing",
        );

        assert_eq!(seed_fanout(&catalog, &SeedWork::Reconcile(reconcile())), 0);
        assert_eq!(
            seed_fanout(&catalog, &SeedWork::Skip(SeedSkipReason::UnknownKind)),
            0
        );
    }

    #[test]
    fn an_empty_run_has_no_span_so_it_cannot_become_a_group() {
        assert!(SeedRun::<SeedTile>::new(Vec::new()).is_none());
    }
}
