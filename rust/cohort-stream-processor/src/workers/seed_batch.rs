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
use crate::filters::{FilterCatalog, TeamId};
use crate::observability::metrics::{
    PERSON_SEED_REKEYED_TOTAL, PERSON_SEED_REKEY_PRODUCE_FAILURE_TOTAL,
    SEED_APPLY_BATCHES_HELD_TOTAL, SEED_APPLY_BATCH_DURATION_SECONDS, SEED_APPLY_BATCH_SIZE,
    SEED_REKEYED_TOTAL, SEED_REKEY_PRODUCE_FAILURE_TOTAL, SEED_TILES_SKIPPED_TOTAL,
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

/// Split `seeds` into same-kind runs in offset order, capping each run at `max`.
///
/// Pure and total: every input seed lands in exactly one group, and the groups' offsets stay in the
/// order they arrived, which is what keeps a reconcile tile behind its run's data tiles.
pub(crate) fn group_seeds(seeds: Vec<Admitted<SeedWork>>, max: NonZeroUsize) -> Vec<SeedGroup> {
    let mut groups = Vec::new();
    let mut tiles: Vec<Admitted<SeedTile>> = Vec::new();
    let mut persons: Vec<Admitted<PersonSeed>> = Vec::new();

    for Admitted { work, offset } in seeds {
        match work {
            SeedWork::Tile(tile) => {
                flush(&mut persons, SeedGroup::Persons, &mut groups);
                tiles.push(Admitted { work: tile, offset });
                if tiles.len() >= max.get() {
                    flush(&mut tiles, SeedGroup::Tiles, &mut groups);
                }
            }
            SeedWork::Person(seed) => {
                flush(&mut tiles, SeedGroup::Tiles, &mut groups);
                persons.push(Admitted { work: seed, offset });
                if persons.len() >= max.get() {
                    flush(&mut persons, SeedGroup::Persons, &mut groups);
                }
            }
            SeedWork::Reconcile(tile) => {
                flush(&mut tiles, SeedGroup::Tiles, &mut groups);
                flush(&mut persons, SeedGroup::Persons, &mut groups);
                groups.push(SeedGroup::Reconcile(Admitted { work: tile, offset }));
            }
            SeedWork::Skip(reason) => {
                flush(&mut tiles, SeedGroup::Tiles, &mut groups);
                flush(&mut persons, SeedGroup::Persons, &mut groups);
                groups.push(SeedGroup::Skip(Admitted {
                    work: reason,
                    offset,
                }));
            }
        }
    }

    flush(&mut tiles, SeedGroup::Tiles, &mut groups);
    flush(&mut persons, SeedGroup::Persons, &mut groups);
    groups
}

/// Close the run accumulated in `items`, if any, as one group.
fn flush<T>(
    items: &mut Vec<Admitted<T>>,
    into: fn(SeedRun<T>) -> SeedGroup,
    groups: &mut Vec<SeedGroup>,
) {
    if let Some(run) = SeedRun::new(std::mem::take(items)) {
        groups.push(into(run));
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

    use crate::filters::{CohortId, TeamId};

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

    fn max(n: usize) -> NonZeroUsize {
        NonZeroUsize::new(n).unwrap()
    }

    /// A run that leaked across a kind boundary would hand tiles to the person fold, or hand a
    /// reconcile tile's offset to a batch that marks past it.
    #[test]
    fn runs_break_at_every_kind_change_and_control_seeds_stay_single() {
        let groups = group_seeds(
            vec![
                admitted(SeedWork::Tile(tile()), 0),
                admitted(SeedWork::Tile(tile()), 1),
                admitted(SeedWork::Person(person()), 2),
                admitted(SeedWork::Reconcile(reconcile()), 3),
                admitted(SeedWork::Tile(tile()), 4),
                admitted(SeedWork::Skip(SeedSkipReason::UnknownKind), 5),
                admitted(SeedWork::Tile(tile()), 6),
            ],
            max(256),
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
        let seeds: Vec<_> = (0..7)
            .map(|offset| admitted(SeedWork::Tile(tile()), offset))
            .collect();

        let groups = group_seeds(seeds, max(3));

        assert_eq!(groups.len(), 3);
        assert_eq!(spans(&groups), vec![(0, 2), (3, 5), (6, 6)]);
    }

    /// The zero-cost hatch: `COHORT_SEED_APPLY_BATCH_MAX=1` must reproduce the per-seed apply.
    #[test]
    fn a_cap_of_one_yields_one_group_per_seed() {
        let seeds: Vec<_> = (0..3)
            .map(|offset| admitted(SeedWork::Tile(tile()), offset))
            .collect();

        let groups = group_seeds(seeds, max(1));

        assert_eq!(spans(&groups), vec![(0, 0), (1, 1), (2, 2)]);
    }

    #[test]
    fn an_empty_batch_yields_no_groups() {
        assert!(group_seeds(Vec::new(), max(256)).is_empty());
    }

    #[test]
    fn an_empty_run_has_no_span_so_it_cannot_become_a_group() {
        assert!(SeedRun::<SeedTile>::new(Vec::new()).is_none());
    }
}
