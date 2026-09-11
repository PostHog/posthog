//! Stage 2 composition: re-evaluates multi-leaf cohorts when Stage 1 flips a leaf.
//!
//! [`compose_stage2`] reads each affected cohort's leaf states, evaluates the tree, diffs against the
//! stored `cf_stage2` bit, and emits membership changes on a flip. At-most-once: a crash between
//! the Stage 1 and Stage 2 commits drops a flip, but `evaluate_tree` recomputes the whole cohort
//! each event, so a mismatch self-heals on the person's next event.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use cohort_core::seed::RunId;
use metrics::counter;
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::tree::{CohortLeaf, CohortTree, FilterNode};
use crate::filters::CohortId;
use crate::observability::metrics::{
    SEED_REGISTER_REPAIRS_TOTAL, STAGE2_COHORTS_EVALUATED, STAGE2_STATE_DECODE_ERROR,
    STAGE2_TRANSITIONS,
};
use crate::producer::{ChangeOrigin, CohortMembershipChange, MembershipStatus};
use crate::stage1::key::LeafStateKey;
use crate::stage1::person_record::PersonRecord;
use crate::stage1::state::{Stage1State, StateVariant, StatefulRecord};
use crate::stage2::evaluator::{evaluate_tree, leaf_membership};
use crate::stage2::state::{Stage2Ownership, Stage2State};
use crate::store::{
    BehavioralKey, PersonRecordKey, ReadLane, Stage2Key, StagedBatch, StoreError, StoreHandle,
};
use crate::workers::composition_inputs::ReferenceSource;

/// `affected_leaves` is the touched `(leaf, person)` set; `lane` is the read lane every recompute
/// read runs on. Every caller passes `Event`: the seed paths, which read on `Maintenance`, go
/// through [`recompute_stage2_by_person`](super::stage2_person_inputs::recompute_stage2_by_person)
/// instead, whose store sections draw the maintenance permit.
pub async fn compose_stage2(
    partition_id: u16,
    handle: &StoreHandle,
    filters: &TeamFilters,
    affected_leaves: &[(LeafStateKey, Uuid)],
    event_ms: i64,
    last_updated: &str,
    lane: ReadLane,
) -> Result<Vec<CohortMembershipChange>, StoreError> {
    let recompute = recompute_stage2(
        partition_id,
        handle,
        filters,
        affected_leaves,
        event_ms,
        last_updated,
        lane,
    )
    .await?;
    commit_stage2_writes(handle, &recompute.writes).await?;
    recompute.record_metrics();
    Ok(recompute.changes)
}

/// Uncommitted recompute result: the flips and their pending `cf_stage2` writes. Lets
/// produce-before-state callers commit only after their produces ack, so a failed produce is
/// re-derived on replay.
#[derive(Default)]
pub(crate) struct Stage2Recompute {
    pub changes: Vec<CohortMembershipChange>,
    pub writes: Vec<(Stage2Key, Stage2State)>,
    evaluated: u64,
    /// Composed flips only. `changes` also carries the single-leaf changes a register diff folds
    /// in, so counting over it would report those as Stage 2 transitions.
    composed: StatusCounts,
    /// Single-leaf changes a register diff derived with no stage-1 transition behind them.
    repairs: RepairCounts,
}

impl Stage2Recompute {
    /// Call only once the writes committed, so a failed commit's redelivery cannot double-count.
    pub(crate) fn record_metrics(&self) {
        counter!(STAGE2_COHORTS_EVALUATED).increment(self.evaluated);
        self.composed.record(STAGE2_TRANSITIONS);
        self.repairs.record(SEED_REGISTER_REPAIRS_TOTAL);
    }

    /// Fold a sibling recompute in, so one produce and one commit cover both halves.
    pub(crate) fn extend(&mut self, other: Self) {
        self.changes.extend(other.changes);
        self.writes.extend(other.writes);
        self.evaluated += other.evaluated;
        self.composed.add(other.composed);
        self.repairs.add(other.repairs);
    }

    /// Both recompute orders call this, so what a composed evaluation emits cannot depend on
    /// whether the caller walked cohorts or persons.
    pub(super) fn record_pair(
        &mut self,
        pair: RecomputedPair,
        diff: &RecomputeDiff,
        event_ms: i64,
        last_updated: &str,
    ) {
        self.evaluated += 1;
        if diff.flipped() {
            self.composed.count(diff.status());
            self.changes.push(CohortMembershipChange {
                team_id: pair.team_id,
                cohort_id: pair.cohort_id.0,
                person_id: pair.person_id.to_string(),
                last_updated: last_updated.to_string(),
                status: diff.status(),
                origin: None,
                run_id: None,
            });
        }
        if diff.requires_write() {
            // Write `false` rather than deleting so the retracted pair stays enumerable by the
            // reconcile scan. A no-flip transferred fallback is rewritten once so receiver
            // evaluation claims ownership.
            self.writes.push((
                diff.stage2_key,
                Stage2State {
                    in_cohort: diff.new_bit,
                    last_evaluated_at_ms: event_ms,
                },
            ));
        }
    }
}

#[cfg(test)]
impl Stage2Recompute {
    /// Pairs composed, which is what `STAGE2_COHORTS_EVALUATED` reports. A pair that flips nothing
    /// leaves no other trace for a test to compare.
    pub(super) fn evaluated(&self) -> u64 {
        self.evaluated
    }
}

pub(super) struct RecomputedPair {
    pub team_id: i32,
    pub cohort_id: CohortId,
    pub person_id: Uuid,
}

/// Per-status flip counts, kept so [`Stage2Recompute::record_metrics`] can attribute each half of a
/// folded recompute to its own metric without re-walking `changes`.
#[derive(Debug, Default, Clone, Copy)]
struct StatusCounts {
    entered: u64,
    left: u64,
}

impl StatusCounts {
    fn count(&mut self, status: MembershipStatus) {
        match status {
            MembershipStatus::Entered => self.entered += 1,
            MembershipStatus::Left => self.left += 1,
        }
    }

    fn add(&mut self, other: Self) {
        self.entered += other.entered;
        self.left += other.left;
    }

    /// A zero count emits nothing, so a path that cannot move the metric never creates its series.
    fn record(self, metric: &'static str) {
        for (count, status) in self.non_zero() {
            counter!(metric, "kind" => status.as_str()).increment(count);
        }
    }

    fn record_found(self, metric: &'static str, found: &'static str) {
        for (count, status) in self.non_zero() {
            counter!(metric, "kind" => status.as_str(), "found" => found).increment(count);
        }
    }

    fn non_zero(self) -> impl Iterator<Item = (u64, MembershipStatus)> {
        [
            (self.entered, MembershipStatus::Entered),
            (self.left, MembershipStatus::Left),
        ]
        .into_iter()
        .filter(|(count, _)| *count > 0)
    }
}

/// Register repairs split by what the diff found in the row. The split is what the read observed,
/// not why the row got that way: a row can disagree with the truth because a produce failed and
/// was redelivered, because the cohort was edited and its leaf key moved, or because a transfer
/// left a fallback behind, and nothing persisted tells those apart.
#[derive(Debug, Default, Clone, Copy)]
struct RepairCounts {
    /// No row at all — the register predates this apply.
    absent: StatusCounts,
    /// A row that did not decode; also counted on `STAGE2_STATE_DECODE_ERROR` at the read.
    corrupt: StatusCounts,
    /// A row that decoded and disagreed with the truth.
    mismatch: StatusCounts,
}

impl RepairCounts {
    fn add(&mut self, other: Self) {
        self.absent.add(other.absent);
        self.corrupt.add(other.corrupt);
        self.mismatch.add(other.mismatch);
    }

    fn record(self, metric: &'static str) {
        self.absent.record_found(metric, "absent");
        self.corrupt.record_found(metric, "corrupt");
        self.mismatch.record_found(metric, "mismatch");
    }
}

/// The read-only half of [`compose_stage2`]: one cohort at a time, in `(cohort, person)` order.
/// The seed paths use
/// [`recompute_stage2_by_person`](super::stage2_person_inputs::recompute_stage2_by_person) instead.
pub(super) async fn recompute_stage2(
    partition_id: u16,
    handle: &StoreHandle,
    filters: &TeamFilters,
    affected_leaves: &[(LeafStateKey, Uuid)],
    event_ms: i64,
    last_updated: &str,
    lane: ReadLane,
) -> Result<Stage2Recompute, StoreError> {
    let mut affected: BTreeSet<(CohortId, Uuid)> = BTreeSet::new();
    for &(leaf_state_key, person_id) in affected_leaves {
        if let Some(cohorts) = filters.by_lsk_to_composable_cohorts.get(&leaf_state_key) {
            for &cohort_id in cohorts {
                affected.insert((cohort_id, person_id));
            }
        }
    }

    let mut recompute = Stage2Recompute::default();
    for (cohort_id, person_id) in affected {
        let Some(tree) = filters.cohorts.get(&cohort_id) else {
            continue;
        };

        let diff = recompute_and_diff(partition_id, person_id, tree, filters, handle, lane).await?;
        recompute.record_pair(
            RecomputedPair {
                team_id: tree.team_id.0,
                cohort_id,
                person_id,
            },
            &diff,
            event_ms,
            last_updated,
        );
    }

    Ok(recompute)
}

/// One leaf a seed run folded, with the membership its resulting state implies. The caller holds
/// that truth already, so the register diff never re-reads `cf_behavioral`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct FoldedLeaf {
    pub leaf_state_key: LeafStateKey,
    pub person_id: Uuid,
    pub in_cohort: bool,
    /// Whether the run *net* flipped this leaf's membership against the state its read pass saw.
    /// Only the fold knows it, and it is what separates an ordinary flip from a register repair in
    /// the metrics. A run that enters then leaves the same leaf mints nothing.
    pub minted_transition: bool,
    /// The run that last touched this leaf, stamped onto every change the diff emits for it.
    pub run_id: RunId,
}

/// What the single-leaf register diff decided for one apply.
#[must_use]
#[derive(Default)]
pub(crate) struct RegisterDiff {
    /// Changes to emit and the rows to commit after the ack; folds into the composed recompute.
    pub recompute: Stage2Recompute,
    /// Rows recording what downstream holds before this apply's emission. The caller stages them
    /// in stage 1, so a produce that then fails leaves the row disagreeing with the truth and the
    /// redelivery re-emits.
    pub stage1_writes: Vec<(Stage2Key, Stage2State)>,
}

impl RegisterDiff {
    /// Fold another team's diff in, so a multi-team run still commits and produces once.
    pub(crate) fn extend(&mut self, other: Self) {
        self.recompute.extend(other.recompute);
        self.stage1_writes.extend(other.stage1_writes);
    }
}

/// Derive each single-leaf cohort's membership change from the folded leaf's truth and the
/// persisted register row, which on the seed paths records what downstream was last told.
///
/// An apply emits when stage 1 minted a transition, as the transition-derived paths do, or when
/// the stored bit disagrees with the truth, which is what a produce that never acked leaves
/// behind. An absent row says nothing, so it reads as "never told": an entry is emitted, a
/// non-member is not. A row that agrees with the truth never vetoes a minted transition: it can be
/// a stage-1 guess (the pre-write below) or the leftover of an apply that acked and then held
/// before its post-ack commit, and emitting on a transition is at worst a duplicate the LWW sink
/// absorbs.
///
/// Before an emission the row must read the opposite of the truth, so a failed produce is
/// re-derivable on redelivery; when it does not, stage 1 writes it. A silent apply leaves an
/// agreeing row alone, so an active reconcile scan is not dirtied, and does not write an absent
/// one, because nothing downstream needs a row for a person it was never told about. A corrupt row
/// is replaced with a readable bit even on a silent apply so it does not fail every later decode.
///
/// One batched `cf_stage2` read on `lane`. Leaves with no single-leaf cohort keyed on them cost
/// nothing.
pub(crate) async fn diff_single_leaf_registers(
    partition_id: u16,
    handle: &StoreHandle,
    filters: &TeamFilters,
    folded: &[FoldedLeaf],
    evaluated_at_ms: i64,
    last_updated: &str,
    lane: ReadLane,
) -> Result<RegisterDiff, StoreError> {
    // Ordered and deduplicated, so the read is one batch and the writes are deterministic.
    let mut wanted: BTreeMap<Stage2Key, WantedRegister> = BTreeMap::new();
    for leaf in folded {
        let Some(cohort_ids) = filters
            .by_lsk_to_single_leaf_cohorts
            .get(&leaf.leaf_state_key)
        else {
            continue;
        };
        for cohort_id in cohort_ids {
            let Some(tree) = filters.cohorts.get(cohort_id) else {
                continue;
            };
            let key = Stage2Key {
                partition_id,
                team_id: tree.team_id.0 as u64,
                cohort_id: cohort_id.0 as u64,
                person_id: leaf.person_id,
            };
            let want = WantedRegister {
                team_id: tree.team_id.0,
                cohort_id: *cohort_id,
                in_cohort: leaf.in_cohort,
                minted_transition: leaf.minted_transition,
                run_id: leaf.run_id,
            };
            let previous = wanted.insert(key, want);
            // A single-leaf cohort resolves to one leaf, so one run reaches each row exactly once.
            // A duplicate is the overlay-dedup bug that would silently drop a net transition, and
            // this is its only guard — hence the whole-value compare rather than the bit alone.
            debug_assert!(
                previous.is_none_or(|prior| prior == want),
                "one run folded {key:?} to two different register verdicts",
            );
        }
    }
    if wanted.is_empty() {
        return Ok(RegisterDiff::default());
    }

    let keys: Vec<Stage2Key> = wanted.keys().copied().collect();
    let stored = handle.multi_get_stage2(keys, lane).await?;

    let mut changes = Vec::new();
    let mut writes: Vec<(Stage2Key, Stage2State)> = Vec::new();
    let mut stage1_writes: Vec<(Stage2Key, Stage2State)> = Vec::new();
    let mut repairs = RepairCounts::default();
    for ((key, want), bytes) in wanted.into_iter().zip(stored) {
        let truth = want.in_cohort;
        let stored = read_register(bytes);
        let stored_bit = match stored {
            StoredRegister::Present(prior) => Some(prior.in_cohort),
            StoredRegister::Absent | StoredRegister::Corrupt => None,
        };
        let emits = want.minted_transition || stored_bit.map_or(truth, |bit| bit != truth);
        // What downstream is taken to hold before this apply: the value an emission retires, or
        // the truth when nothing is emitted.
        let before = if emits { !truth } else { truth };
        let records_before = match stored {
            StoredRegister::Present(prior) => prior.in_cohort != before,
            StoredRegister::Corrupt => true,
            StoredRegister::Absent => emits,
        };
        if records_before {
            stage1_writes.push((
                key,
                Stage2State {
                    in_cohort: before,
                    last_evaluated_at_ms: evaluated_at_ms,
                },
            ));
        }
        // A no-flip transferred fallback is still rewritten once, so receiver evaluation claims
        // the row the way the composed path claims its own.
        let claims_fallback = matches!(
            stored,
            StoredRegister::Present(prior) if prior.ownership == Stage2Ownership::TransferredFallback
        );
        if emits || claims_fallback {
            writes.push((
                key,
                Stage2State {
                    in_cohort: truth,
                    last_evaluated_at_ms: evaluated_at_ms,
                },
            ));
        }
        if !emits {
            continue;
        }
        let status = membership_status(truth);
        if !want.minted_transition {
            match stored {
                StoredRegister::Absent => repairs.absent.count(status),
                StoredRegister::Corrupt => repairs.corrupt.count(status),
                StoredRegister::Present(_) => repairs.mismatch.count(status),
            }
        }
        changes.push(CohortMembershipChange {
            team_id: want.team_id,
            cohort_id: want.cohort_id.0,
            person_id: key.person_id.to_string(),
            last_updated: last_updated.to_string(),
            status,
            // Stamped from the leaf, so only the composed half still needs `tag_seed`.
            origin: Some(ChangeOrigin::Seed),
            run_id: Some(want.run_id),
        });
    }

    Ok(RegisterDiff {
        recompute: Stage2Recompute {
            changes,
            writes,
            // The register diff evaluates nothing, so `STAGE2_COHORTS_EVALUATED` keeps meaning
            // composed evaluations.
            evaluated: 0,
            repairs,
            ..Default::default()
        },
        stage1_writes,
    })
}

/// One `(single-leaf cohort, person)` the fold decided, before its stored row is read.
#[derive(Clone, Copy, PartialEq, Eq)]
struct WantedRegister {
    team_id: i32,
    cohort_id: CohortId,
    in_cohort: bool,
    minted_transition: bool,
    run_id: RunId,
}

fn membership_status(in_cohort: bool) -> MembershipStatus {
    if in_cohort {
        MembershipStatus::Entered
    } else {
        MembershipStatus::Left
    }
}

/// What the store holds for one register row. Absence stays distinct from a stored `false`,
/// because the diff has to tell "never told" from "told `false`".
#[derive(Clone, Copy)]
enum StoredRegister {
    Absent,
    /// A row that exists but does not decode. It cannot say what downstream was told, so it reads
    /// as absent and is replaced with a decodable bit; counted on `STAGE2_STATE_DECODE_ERROR`.
    Corrupt,
    Present(PriorStage2State),
}

fn read_register(bytes: Option<Vec<u8>>) -> StoredRegister {
    let Some(bytes) = bytes else {
        return StoredRegister::Absent;
    };
    match Stage2State::decode_with_ownership(&bytes) {
        Ok((state, ownership)) => StoredRegister::Present(PriorStage2State {
            in_cohort: state.in_cohort,
            ownership,
        }),
        Err(_) => {
            counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
            StoredRegister::Corrupt
        }
    }
}

/// Commit recomputed `cf_stage2` bits.
pub(crate) async fn commit_stage2_writes(
    handle: &StoreHandle,
    writes: &[(Stage2Key, Stage2State)],
) -> Result<(), StoreError> {
    if writes.is_empty() {
        return Ok(());
    }
    let mut staged = StagedBatch::default();
    for (key, state) in writes {
        staged.put_stage2(key, &state.encode());
    }
    handle.commit(staged).await
}

/// One cohort's recomputed membership for one person, diffed against the stored `cf_stage2` bit.
/// Shared by Stage 2 composition, the cascade handler and reconcile's page reader, so those
/// recompute paths cannot diverge on what a diff means.
pub(crate) struct RecomputeDiff {
    pub new_bit: bool,
    pub prior_bit: bool,
    pub stage2_key: Stage2Key,
    settles_transfer_fallback: bool,
}

impl RecomputeDiff {
    pub(super) fn new(new_bit: bool, prior: PriorStage2State, stage2_key: Stage2Key) -> Self {
        Self {
            new_bit,
            prior_bit: prior.in_cohort,
            stage2_key,
            settles_transfer_fallback: prior.ownership == Stage2Ownership::TransferredFallback,
        }
    }

    pub fn flipped(&self) -> bool {
        self.new_bit != self.prior_bit
    }

    pub fn status(&self) -> MembershipStatus {
        if self.new_bit {
            MembershipStatus::Entered
        } else {
            MembershipStatus::Left
        }
    }

    /// A receiver evaluation must rewrite a transferred fallback even when the logical bit is
    /// unchanged, making source provenance observably stale without touching ordinary no-flip rows.
    pub fn requires_write(&self) -> bool {
        self.flipped() || self.settles_transfer_fallback
    }
}

/// Recompute one cohort's membership and diff against the stored `cf_stage2` bit. Reads only — the
/// caller stages the write, so it owns the produce/commit ordering.
pub(crate) async fn recompute_and_diff(
    partition_id: u16,
    person_id: Uuid,
    tree: &CohortTree,
    filters: &TeamFilters,
    handle: &StoreHandle,
    lane: ReadLane,
) -> Result<RecomputeDiff, StoreError> {
    let team_id = tree.team_id.0 as u64;
    let new_bit = evaluate_cohort(
        partition_id,
        team_id,
        person_id,
        tree,
        filters,
        handle,
        lane,
    )
    .await?;
    let stage2_key = Stage2Key {
        partition_id,
        team_id,
        cohort_id: tree.cohort_id.0 as u64,
        person_id,
    };
    let prior = read_prior_stage2(handle.get_stage2(&stage2_key, lane).await?);
    Ok(RecomputeDiff::new(new_bit, prior, stage2_key))
}

/// Compose one cohort for one person. A leaf with absent or undecodable state reads as non-member;
/// a cohort-reference leaf reads the referenced cohort's stored membership (see [`resolve_ref_membership`]).
#[allow(clippy::too_many_arguments)]
async fn evaluate_cohort(
    partition_id: u16,
    team_id: u64,
    person_id: Uuid,
    tree: &CohortTree,
    filters: &TeamFilters,
    handle: &StoreHandle,
    lane: ReadLane,
) -> Result<bool, StoreError> {
    let mut lsks = Vec::new();
    collect_leaf_state_keys(&tree.root, &mut lsks);

    let resolver =
        LeafMembershipResolver::new(partition_id, team_id, person_id, filters, handle, lane);
    let membership = resolver.resolve(&lsks).await?;

    let ref_membership = resolve_ref_membership(
        partition_id,
        team_id,
        person_id,
        tree,
        filters,
        handle,
        lane,
    )
    .await?;

    Ok(evaluate_tree(&tree.root, &membership, &ref_membership))
}

/// Turns a person's leaf-state keys into per-leaf membership bits, partitioned by the leaf's
/// [`StateVariant`]: behavioral leaves resolve from `cf_behavioral` rows via [`leaf_membership`] (so
/// each leaf's comparator applies), person-property leaves from the durable
/// [`PersonRecord`](crate::stage1::PersonRecord) — a person LSK *is* its condition hash, so membership
/// is `record.matched.contains(hash)`. Keys whose leaf is absent from the frozen catalog are
/// non-member.
struct LeafMembershipResolver<'a> {
    partition_id: u16,
    team_id: u64,
    person_id: Uuid,
    filters: &'a TeamFilters,
    handle: &'a StoreHandle,
    lane: ReadLane,
}

impl<'a> LeafMembershipResolver<'a> {
    fn new(
        partition_id: u16,
        team_id: u64,
        person_id: Uuid,
        filters: &'a TeamFilters,
        handle: &'a StoreHandle,
        lane: ReadLane,
    ) -> Self {
        Self {
            partition_id,
            team_id,
            person_id,
            filters,
            handle,
            lane,
        }
    }

    async fn resolve(
        &self,
        lsks: &[LeafStateKey],
    ) -> Result<HashMap<LeafStateKey, bool>, StoreError> {
        let mut behavioral_lsks = Vec::new();
        let mut person_lsks = Vec::new();
        for &lsk in lsks {
            match self.filters.by_lsk.get(&lsk).map(|meta| meta.variant) {
                None => continue,
                Some(StateVariant::PersonProperty) => person_lsks.push(lsk),
                // Exhaustive (no wildcard) so a future membership source resolving from another store
                // fails to compile here instead of being silently misrouted into `cf_behavioral`.
                Some(
                    StateVariant::BehavioralSingle
                    | StateVariant::BehavioralDailyBuckets
                    | StateVariant::BehavioralCompressedHistory,
                ) => behavioral_lsks.push(lsk),
            }
        }

        let mut membership = HashMap::with_capacity(behavioral_lsks.len() + person_lsks.len());
        self.read_behavioral_into(&behavioral_lsks, &mut membership)
            .await?;
        self.read_person_into(&person_lsks, &mut membership).await?;
        Ok(membership)
    }

    async fn read_behavioral_into(
        &self,
        lsks: &[LeafStateKey],
        out: &mut HashMap<LeafStateKey, bool>,
    ) -> Result<(), StoreError> {
        if lsks.is_empty() {
            return Ok(());
        }
        let keys: Vec<BehavioralKey> = lsks
            .iter()
            .map(|&lsk| BehavioralKey::new(self.partition_id, self.team_id, self.person_id, lsk))
            .collect();
        let raw = self.handle.multi_get_behavioral(keys, self.lane).await?;
        for (&lsk, bytes) in lsks.iter().zip(raw) {
            let Some(meta) = self.filters.by_lsk.get(&lsk) else {
                continue;
            };
            let state = decode_stage1_state(bytes);
            out.insert(lsk, leaf_membership(state.as_ref(), meta));
        }
        Ok(())
    }

    /// Resolve person-property `lsks` from the person's one durable record via a single point read: a
    /// person LSK is its condition hash, so its bit is `record.matched.contains(hash)`. An absent or
    /// corrupt record reads every person leaf as non-member (a corrupt record counts
    /// `STAGE2_STATE_DECODE_ERROR`).
    async fn read_person_into(
        &self,
        lsks: &[LeafStateKey],
        out: &mut HashMap<LeafStateKey, bool>,
    ) -> Result<(), StoreError> {
        if lsks.is_empty() {
            return Ok(());
        }
        let key = PersonRecordKey::new(self.partition_id, self.team_id, self.person_id);
        let matched = match self.handle.get_person_record(&key, self.lane).await? {
            None => None,
            Some(bytes) => match PersonRecord::decode(&bytes) {
                Ok(record) => Some(record.matched),
                Err(_) => {
                    counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
                    None
                }
            },
        };
        for &lsk in lsks {
            let member = matched
                .as_ref()
                .is_some_and(|matched| matched.contains(&lsk.0));
            out.insert(lsk, member);
        }
        Ok(())
    }
}

/// Resolve each referenced cohort's membership for one person, keyed by referenced cohort id.
/// A `SingleLeaf` referent is read from `cf_behavioral` via [`leaf_membership`] (so its comparator
/// applies); a composable referent from its stored `cf_stage2` bit; anything else as non-member.
/// One batched read per store.
#[allow(clippy::too_many_arguments)]
async fn resolve_ref_membership(
    partition_id: u16,
    team_id: u64,
    person_id: Uuid,
    tree: &CohortTree,
    filters: &TeamFilters,
    handle: &StoreHandle,
    lane: ReadLane,
) -> Result<HashMap<CohortId, bool>, StoreError> {
    let mut ref_ids = Vec::new();
    collect_cohort_refs(&tree.root, &mut ref_ids);
    if ref_ids.is_empty() {
        return Ok(HashMap::new());
    }
    ref_ids.sort_unstable();
    ref_ids.dedup();

    let mut ref_membership: HashMap<CohortId, bool> = HashMap::with_capacity(ref_ids.len());
    let mut single_leaf_refs: Vec<(CohortId, LeafStateKey)> = Vec::new();
    let mut composable_refs: Vec<CohortId> = Vec::new();
    for ref_id in ref_ids {
        match ReferenceSource::classify(filters, ref_id) {
            ReferenceSource::Leaf(lsk) => single_leaf_refs.push((ref_id, lsk)),
            ReferenceSource::Stored => composable_refs.push(ref_id),
            ReferenceSource::NonMember => {
                ref_membership.insert(ref_id, false);
            }
        }
    }

    if !single_leaf_refs.is_empty() {
        // Resolve single-leaf referents through the same seam as the cohort's own leaves, so both
        // apply the leaf's comparator identically.
        let resolver =
            LeafMembershipResolver::new(partition_id, team_id, person_id, filters, handle, lane);
        let lsks: Vec<LeafStateKey> = single_leaf_refs.iter().map(|(_, lsk)| *lsk).collect();
        let membership = resolver.resolve(&lsks).await?;
        for (ref_id, lsk) in &single_leaf_refs {
            ref_membership.insert(*ref_id, membership.get(lsk).copied().unwrap_or(false));
        }
    }

    if !composable_refs.is_empty() {
        let keys: Vec<Stage2Key> = composable_refs
            .iter()
            .map(|ref_id| Stage2Key {
                partition_id,
                team_id,
                cohort_id: ref_id.0 as u64,
                person_id,
            })
            .collect();
        let raw = handle.multi_get_stage2(keys, lane).await?;
        for (ref_id, bytes) in composable_refs.iter().zip(raw) {
            ref_membership.insert(*ref_id, decode_stage2_bit(bytes));
        }
    }

    Ok(ref_membership)
}

/// Decode a `cf_behavioral` value, or [`None`] for absent/undecodable rows.
pub(super) fn decode_stage1_state(bytes: Option<Vec<u8>>) -> Option<Stage1State> {
    let bytes = bytes?;
    match StatefulRecord::decode(&bytes) {
        Ok(record) => Some(record.state),
        Err(_) => {
            counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
            None
        }
    }
}

/// One stored `cf_stage2` row as composition reads it. [`Default`] is the fail-closed reading for
/// an absent or corrupt row.
#[derive(Debug, Clone, Copy, Default)]
pub(super) struct PriorStage2State {
    pub in_cohort: bool,
    ownership: Stage2Ownership,
}

/// Decode both the logical prior bit and its ownership. Missing or corrupt rows keep the existing
/// fail-closed `false` behavior and are never mistaken for a transferred fallback.
pub(super) fn read_prior_stage2(bytes: Option<Vec<u8>>) -> PriorStage2State {
    let Some(bytes) = bytes else {
        return PriorStage2State::default();
    };
    match Stage2State::decode_with_ownership(&bytes) {
        Ok((state, ownership)) => PriorStage2State {
            in_cohort: state.in_cohort,
            ownership,
        },
        Err(_) => {
            counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
            PriorStage2State::default()
        }
    }
}

/// Decode a `cf_stage2` value into its membership bit, `false` when absent or undecodable.
fn decode_stage2_bit(bytes: Option<Vec<u8>>) -> bool {
    let Some(bytes) = bytes else {
        return false;
    };
    match Stage2State::decode(&bytes) {
        Ok(state) => state.in_cohort,
        Err(_) => {
            counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
            false
        }
    }
}

/// Collect every state-keyed leaf's [`LeafStateKey`] in pre-order.
pub(super) fn collect_leaf_state_keys(node: &FilterNode, out: &mut Vec<LeafStateKey>) {
    match node {
        FilterNode::Group { children, .. } => {
            for child in children {
                collect_leaf_state_keys(child, out);
            }
        }
        FilterNode::Leaf(leaf) => {
            if let Some(lsk) = leaf.leaf_state_key() {
                out.push(lsk);
            }
        }
    }
}

/// Collect referenced cohort ids (with duplicates; the caller dedups). Negation is left to
/// `evaluate_tree`, so a referent referenced twice with opposite negation reads one bit.
pub(super) fn collect_cohort_refs(node: &FilterNode, out: &mut Vec<CohortId>) {
    match node {
        FilterNode::Group { children, .. } => {
            for child in children {
                collect_cohort_refs(child, out);
            }
        }
        FilterNode::Leaf(CohortLeaf::CohortRef(config)) => out.push(config.referenced_cohort_id),
        FilterNode::Leaf(_) => {}
    }
}

#[cfg(test)]
// Tests seed the store directly through `CohortStore`, the sanctioned direct-store surface for tests.
#[allow(clippy::disallowed_methods)]
mod tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::{json, Value};
    use tempfile::TempDir;
    use uuid::Uuid;

    use crate::filters::{CohortId, TeamFiltersBuilder, TeamId};
    use crate::stage1::person_record::{MatchedSet, PersonRecord};
    use crate::stage1::state::AppliedOffsets;
    use crate::store::{
        Behavioral, CohortStore, OffloadConfig, OffloadMode, PersonRecordKey, PersonRecords,
        StoreConfig,
    };

    const TEAM: u64 = 7;
    const PARTITION: u16 = 0;
    const HASH: [u8; 16] = *b"0123456789abcdef";
    const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";
    const TS: &str = "2026-05-26 12:34:56.789123";
    const EVENT_MS: i64 = 1_700_000_000_000;
    const RUN: RunId = RunId(Uuid::from_u128(0xBF));

    fn temp_store() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        (dir, store)
    }

    /// Wraps the store so the compose paths exercise the same blocking-pool transport as production.
    fn handle(store: &CohortStore) -> StoreHandle {
        StoreHandle::new(
            store.clone(),
            OffloadConfig {
                mode: OffloadMode::All,
                event_read_permits: 16,
                maintenance_permits: 6,
            },
        )
    }

    fn behavioral_leaf(window_days: i64) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event", "key": "$pageview",
            "time_value": window_days, "time_interval": "day",
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn daily_leaf(window_days: i64, op: &str, value: i64) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event_multiple", "key": "$pageview",
            "time_value": window_days, "time_interval": "day",
            "operator": op, "operator_value": value,
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn daily_state(count: u32) -> Stage1State {
        let mut buckets = vec![0u32; 8];
        buckets[7] = count;
        Stage1State::BehavioralDailyBuckets {
            buckets,
            window_start_day: 20_600,
            last_event_at_ms: EVENT_MS,
            earliest_eviction_at_ms: i64::MAX,
        }
    }

    fn person_leaf() -> Value {
        json!({
            "type": "person", "key": "email", "value": "u@p.com", "operator": "exact",
            "conditionHash": "fedcba9876543210",
            "bytecode": ["_H", 1, 32, "u@p.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    fn freeze(values: Vec<Value>) -> TeamFilters {
        freeze_for_team(TEAM as i32, values)
    }

    /// Freeze one cohort under an explicit team, so a test can prove state is keyed by team.
    fn freeze_for_team(team_id: i32, values: Vec<Value>) -> TeamFilters {
        let cohort = json!({ "properties": { "type": "AND", "values": values } });
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(team_id), &cohort)
            .unwrap();
        builder.freeze(UTC)
    }

    fn person(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn behavioral_match() -> Stage1State {
        Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms: EVENT_MS,
            earliest_eviction_at_ms: i64::MAX,
        }
    }

    fn write_behavioral(store: &CohortStore, lsk: LeafStateKey, who: Uuid, state: Stage1State) {
        let key = BehavioralKey::new(PARTITION, TEAM, who, lsk);
        let record = StatefulRecord::new(state, AppliedOffsets::default());
        store
            .write_batch(|b| b.put::<Behavioral>(&key, &record.encode()))
            .unwrap();
    }

    fn write_person_record(store: &CohortStore, who: Uuid, matched: &[[u8; 16]]) {
        let key = PersonRecordKey::new(PARTITION, TEAM, who);
        let mut record = PersonRecord::absent();
        record.matched = MatchedSet::from_iter(matched.iter().copied());
        store
            .write_batch(|b| b.put::<PersonRecords>(&key, &record.encode()))
            .unwrap();
    }

    /// Write bytes that fail `PersonRecord::decode` (byte 0 is not the format version) to the person's
    /// record key, so the compose read path takes its corrupt-record arm.
    fn write_corrupt_person_record(store: &CohortStore, who: Uuid) {
        let key = PersonRecordKey::new(PARTITION, TEAM, who);
        store
            .write_batch(|b| b.put::<PersonRecords>(&key, b"not a valid person record"))
            .unwrap();
    }

    fn stage2_bit(store: &CohortStore, cohort: u64, who: Uuid) -> Option<bool> {
        let key = Stage2Key {
            partition_id: PARTITION,
            team_id: TEAM,
            cohort_id: cohort,
            person_id: who,
        };
        store
            .get_stage2(&key)
            .unwrap()
            .map(|bytes| Stage2State::decode(&bytes).unwrap().in_cohort)
    }

    fn and_leaf_keys(filters: &TeamFilters) -> (LeafStateKey, LeafStateKey) {
        (
            filters.by_condition_to_lsk[&HASH][0],
            LeafStateKey::for_person_property(&PERSON_HASH),
        )
    }

    #[tokio::test]
    async fn entered_when_the_and_is_satisfied() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), person_leaf()]);
        let (beh_lsk, _per_lsk) = and_leaf_keys(&filters);
        let alice = person(1);

        write_behavioral(&store, beh_lsk, alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);

        let changes = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(beh_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();

        assert_eq!(changes.len(), 1);
        assert_eq!(changes[0].cohort_id, 1);
        assert_eq!(changes[0].team_id, TEAM as i32);
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(changes[0].person_id, alice.to_string());
        assert_eq!(changes[0].last_updated, TS);
        assert_eq!(stage2_bit(&store, 1, alice), Some(true), "bit committed");
    }

    #[tokio::test]
    async fn corrupt_person_record_composes_as_non_member() {
        // A record whose bytes fail to decode must read as non-member on the compose path (never a
        // stale/garbage bit), so the AND cannot enter. Sibling to `entered_when_the_and_is_satisfied`
        // with the person record corrupted; a regression here would silently drop a still-matching
        // member from every person-property cohort.
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), person_leaf()]);
        let (beh_lsk, _per_lsk) = and_leaf_keys(&filters);
        let alice = person(1);

        write_behavioral(&store, beh_lsk, alice, behavioral_match());
        write_corrupt_person_record(&store, alice);

        let changes = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(beh_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();

        assert!(
            changes.is_empty(),
            "a corrupt person record reads as non-member, so the AND does not enter",
        );
        assert_eq!(
            stage2_bit(&store, 1, alice),
            None,
            "no membership bit is written",
        );
    }

    #[tokio::test]
    async fn no_emit_until_the_second_leaf_flips() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), person_leaf()]);
        let (beh_lsk, per_lsk) = and_leaf_keys(&filters);
        let alice = person(1);

        write_behavioral(&store, beh_lsk, alice, behavioral_match());
        let phase_a = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(beh_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();
        assert!(phase_a.is_empty(), "one leaf does not satisfy the AND");
        assert_eq!(
            stage2_bit(&store, 1, alice),
            None,
            "no bit written on a non-flip"
        );

        write_person_record(&store, alice, &[PERSON_HASH]);
        let phase_b = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(per_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();
        assert_eq!(phase_b.len(), 1);
        assert_eq!(phase_b[0].status, MembershipStatus::Entered);
        assert_eq!(stage2_bit(&store, 1, alice), Some(true));
    }

    #[tokio::test]
    async fn left_when_a_leaf_drops() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), person_leaf()]);
        let (beh_lsk, per_lsk) = and_leaf_keys(&filters);
        let alice = person(1);

        write_behavioral(&store, beh_lsk, alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);
        let entered = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(beh_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();
        assert_eq!(entered.len(), 1);
        assert_eq!(entered[0].status, MembershipStatus::Entered);

        write_person_record(&store, alice, &[]);
        let left = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(per_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();
        assert_eq!(left.len(), 1);
        assert_eq!(left[0].status, MembershipStatus::Left);
        assert_eq!(
            stage2_bit(&store, 1, alice),
            Some(false),
            "a Left writes the false bit, it does not delete the row",
        );
    }

    #[tokio::test]
    async fn idempotent_re_evaluation_emits_once() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), person_leaf()]);
        let (beh_lsk, _per_lsk) = and_leaf_keys(&filters);
        let alice = person(1);
        write_behavioral(&store, beh_lsk, alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);

        let first = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(beh_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();
        assert_eq!(first.len(), 1, "the first evaluation enters");
        let key = Stage2Key {
            partition_id: PARTITION,
            team_id: TEAM,
            cohort_id: 1,
            person_id: alice,
        };
        let current = Stage2State::decode(&store.get_stage2(&key).unwrap().unwrap()).unwrap();
        store
            .write_batch(|batch| {
                batch.put_stage2(&key, &current.encode_transferred_fallback());
            })
            .unwrap();

        let second = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(beh_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();
        assert!(
            second.is_empty(),
            "a re-evaluation with no change emits nothing"
        );
        let bytes = store.get_stage2(&key).unwrap().unwrap();
        assert_eq!(
            Stage2State::decode_with_ownership(&bytes).unwrap().1,
            Stage2Ownership::Local,
            "the no-op evaluation still claims a transferred fallback",
        );
    }

    #[tokio::test]
    async fn dedups_when_one_event_flips_two_leaves_of_one_cohort() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), behavioral_leaf(30)]);
        let lsks = &filters.by_condition_to_lsk[&HASH];
        assert_eq!(lsks.len(), 2, "two windows fan out to two LSKs");
        let alice = person(1);
        write_behavioral(&store, lsks[0], alice, behavioral_match());
        write_behavioral(&store, lsks[1], alice, behavioral_match());

        let changes = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(lsks[0], alice), (lsks[1], alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();

        assert_eq!(
            changes.len(),
            1,
            "two leaf flips of one cohort dedup to a single Entered",
        );
        assert_eq!(changes[0].status, MembershipStatus::Entered);
    }

    #[tokio::test]
    async fn composes_a_performed_event_multiple_leaf_via_variant_dispatch() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![daily_leaf(7, "gte", 2), person_leaf()]);
        let beh_lsk = filters.by_condition_to_lsk[&HASH][0];
        let alice = person(1);
        write_behavioral(&store, beh_lsk, alice, daily_state(2));
        write_person_record(&store, alice, &[PERSON_HASH]);

        let changes = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(beh_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();
        assert_eq!(
            changes.len(),
            1,
            "count 2 ≥ gte 2 → the multiple leaf is a member"
        );
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(changes[0].cohort_id, 1);

        let (_dir2, store2) = temp_store();
        write_behavioral(&store2, beh_lsk, alice, daily_state(1)); // 1 < gte 2
        write_person_record(&store2, alice, &[PERSON_HASH]);
        let below = compose_stage2(
            PARTITION,
            &handle(&store2),
            &filters,
            &[(beh_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();
        assert!(
            below.is_empty(),
            "count 1 fails gte 2, so the multiple leaf is not a member and the AND is unsatisfied",
        );
    }

    #[tokio::test]
    async fn transitions_touching_no_composable_cohort_emit_nothing() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7)]);
        let beh_lsk = filters.by_condition_to_lsk[&HASH][0];
        let alice = person(1);
        write_behavioral(&store, beh_lsk, alice, behavioral_match());

        let changes = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(beh_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();
        assert!(
            changes.is_empty(),
            "a single-leaf cohort is handled by map_transition, not Stage 2",
        );
    }

    fn negated_person_leaf() -> Value {
        json!({
            "type": "person", "key": "email", "value": "u@p.com", "operator": "exact",
            "conditionHash": "fedcba9876543210",
            "bytecode": ["_H", 1, 32, "u@p.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
            "negation": true,
        })
    }

    #[tokio::test]
    async fn negated_leaf_absent_means_entered() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), negated_person_leaf()]);
        let (beh_lsk, _per_lsk) = and_leaf_keys(&filters);
        let alice = person(1);

        write_behavioral(&store, beh_lsk, alice, behavioral_match());

        let changes = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(beh_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();
        assert_eq!(changes.len(), 1);
        assert_eq!(changes[0].status, MembershipStatus::Entered);
    }

    #[tokio::test]
    async fn negated_leaf_present_means_left() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), negated_person_leaf()]);
        let (beh_lsk, per_lsk) = and_leaf_keys(&filters);
        let alice = person(1);

        write_behavioral(&store, beh_lsk, alice, behavioral_match());
        let entered = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(beh_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();
        assert_eq!(entered.len(), 1);
        assert_eq!(entered[0].status, MembershipStatus::Entered);

        write_person_record(&store, alice, &[PERSON_HASH]);
        let left = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[(per_lsk, alice)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap();
        assert_eq!(left.len(), 1);
        assert_eq!(left[0].status, MembershipStatus::Left);
    }

    use crate::stage2::CohortEligibility;

    fn cohort_ref(target: i32) -> Value {
        json!({ "type": "cohort", "value": target, "negation": false })
    }

    fn negated_cohort_ref(target: i32) -> Value {
        json!({ "type": "cohort", "value": target, "negation": true })
    }

    /// Freeze several `(cohort_id, leaves)` cohorts into one team with the cascade gate set.
    fn freeze_cascade(cohorts: Vec<(i32, Vec<Value>)>, cascade_enabled: bool) -> TeamFilters {
        let mut builder = TeamFiltersBuilder::default();
        for (id, values) in cohorts {
            let cohort = json!({ "properties": { "type": "AND", "values": values } });
            builder
                .add_cohort(CohortId(id), TeamId(TEAM as i32), &cohort)
                .unwrap();
        }
        builder.freeze_with(UTC, cascade_enabled)
    }

    fn write_stage2(store: &CohortStore, cohort: u64, who: Uuid, in_cohort: bool) {
        let key = Stage2Key {
            partition_id: PARTITION,
            team_id: TEAM,
            cohort_id: cohort,
            person_id: who,
        };
        let state = Stage2State {
            in_cohort,
            last_evaluated_at_ms: EVENT_MS,
        };
        store
            .write_batch(|b| b.put_stage2(&key, &state.encode()))
            .unwrap();
    }

    /// A leaf whose stage 1 minted nothing this apply, which is what a redelivery or a
    /// catalog-added cohort looks like.
    fn folded(leaf_state_key: LeafStateKey, person_id: Uuid, in_cohort: bool) -> FoldedLeaf {
        FoldedLeaf {
            leaf_state_key,
            person_id,
            in_cohort,
            minted_transition: false,
            run_id: RUN,
        }
    }

    fn single_leaf_lsk(filters: &TeamFilters, cohort: i32) -> LeafStateKey {
        match filters.eligibility[&CohortId(cohort)] {
            CohortEligibility::SingleLeaf(lsk) => lsk,
            other => panic!("cohort {cohort} should be SingleLeaf, got {other:?}"),
        }
    }

    /// Compose after flipping cohort 1's own person leaf.
    async fn compose_referrer_on_own_leaf(
        handle: &StoreHandle,
        filters: &TeamFilters,
        who: Uuid,
    ) -> Vec<CohortMembershipChange> {
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        compose_stage2(
            PARTITION,
            handle,
            filters,
            &[(per_lsk, who)],
            EVENT_MS,
            TS,
            ReadLane::Event,
        )
        .await
        .unwrap()
    }

    #[tokio::test]
    async fn composable_ref_reads_a_single_leaf_referent_from_cf_behavioral_via_its_op() {
        let filters = freeze_cascade(
            vec![
                (2, vec![daily_leaf(7, "gte", 2)]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        assert_eq!(
            filters.eligibility[&CohortId(1)],
            CohortEligibility::Stage2ComposableRef,
        );
        let ref2_lsk = single_leaf_lsk(&filters, 2);
        let alice = person(1);

        // Count 2 ≥ gte 2: referent 2 is a member.
        let (_dir, store) = temp_store();
        write_behavioral(&store, ref2_lsk, alice, daily_state(2));
        write_person_record(&store, alice, &[PERSON_HASH]);
        let entered = compose_referrer_on_own_leaf(&handle(&store), &filters, alice).await;
        assert_eq!(entered.len(), 1);
        assert_eq!(entered[0].cohort_id, 1);
        assert_eq!(entered[0].status, MembershipStatus::Entered);

        // Count 1 < gte 2: the referent's comparator applies, so it is a non-member.
        let (_dir2, store2) = temp_store();
        write_behavioral(&store2, ref2_lsk, alice, daily_state(1));
        write_person_record(&store2, alice, &[PERSON_HASH]);
        let below = compose_referrer_on_own_leaf(&handle(&store2), &filters, alice).await;
        assert!(
            below.is_empty(),
            "count 1 fails the referent's gte 2, so the referrer's AND is unsatisfied",
        );
    }

    #[tokio::test]
    async fn composable_ref_reads_a_composable_referent_from_cf_stage2_verbatim() {
        let filters = freeze_cascade(
            vec![
                // Two distinct leaves make cohort 2 composable, so its membership lives in cf_stage2.
                (2, vec![behavioral_leaf(7), daily_leaf(30, "gte", 1)]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        assert_eq!(
            filters.eligibility[&CohortId(2)],
            CohortEligibility::Stage2Composable,
        );
        let alice = person(1);

        let (_dir, store) = temp_store();
        // cohort 2's cf_behavioral is left absent: a recompute would read non-member, so Entered proves
        // the stored cf_stage2 bit is read.
        write_stage2(&store, 2, alice, true);
        write_person_record(&store, alice, &[PERSON_HASH]);

        let entered = compose_referrer_on_own_leaf(&handle(&store), &filters, alice).await;
        assert_eq!(entered.len(), 1);
        assert_eq!(entered[0].cohort_id, 1);
        assert_eq!(entered[0].status, MembershipStatus::Entered);
    }

    #[tokio::test]
    async fn composable_ref_absent_referent_reads_non_member() {
        let filters = freeze_cascade(
            vec![
                (2, vec![daily_leaf(7, "gte", 2)]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        let alice = person(1);

        let (_dir, store) = temp_store();
        write_person_record(&store, alice, &[PERSON_HASH]);
        let changes = compose_referrer_on_own_leaf(&handle(&store), &filters, alice).await;
        assert!(
            changes.is_empty(),
            "an absent referent reads as a non-member, so the AND is unsatisfied",
        );
    }

    #[tokio::test]
    async fn composable_ref_negated_absent_referent_enters() {
        let filters = freeze_cascade(
            vec![
                (2, vec![daily_leaf(7, "gte", 2)]),
                (1, vec![person_leaf(), negated_cohort_ref(2)]),
            ],
            true,
        );
        assert_eq!(
            filters.eligibility[&CohortId(1)],
            CohortEligibility::Stage2ComposableRef,
        );
        let alice = person(1);

        // Referent 2 absent → negated ref reads true → Entered.
        let (_dir, store) = temp_store();
        write_person_record(&store, alice, &[PERSON_HASH]);
        let entered = compose_referrer_on_own_leaf(&handle(&store), &filters, alice).await;
        assert_eq!(entered.len(), 1);
        assert_eq!(entered[0].cohort_id, 1);
        assert_eq!(entered[0].status, MembershipStatus::Entered);
    }

    #[tokio::test]
    async fn composable_ref_is_dormant_when_the_gate_is_off() {
        // Gate off: cohort 1 stays Excluded(HasCohortRef), is absent from the composable map, and
        // emits nothing even though both its own leaf and the referent are satisfied.
        let filters = freeze_cascade(
            vec![
                (2, vec![daily_leaf(7, "gte", 2)]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            false,
        );
        let ref2_lsk = single_leaf_lsk(&filters, 2);
        let alice = person(1);

        let (_dir, store) = temp_store();
        write_behavioral(&store, ref2_lsk, alice, daily_state(2));
        write_person_record(&store, alice, &[PERSON_HASH]);
        let changes = compose_referrer_on_own_leaf(&handle(&store), &filters, alice).await;
        assert!(
            changes.is_empty(),
            "gate off: the ref cohort is not in the composable map, so compose_stage2 skips it",
        );
        assert_eq!(
            stage2_bit(&store, 1, alice),
            None,
            "no cf_stage2 bit written when the gate is off",
        );
    }
    // --- Single-leaf register diff ---

    /// The diff's whole rule set, one row per `(stored register, folded truth, minted transition)`
    /// cell. Each row states what downstream is told, what stage 1 records first, and what the
    /// post-ack commit writes.
    #[tokio::test]
    async fn register_diff_emits_on_a_minted_transition_or_a_lagging_register() {
        use MembershipStatus::{Entered, Left};
        // (stored, truth, minted) -> (change, stage-1 write, post-ack write, repairs)
        let cases = [
            (
                None,
                true,
                false,
                Some(Entered),
                Some(false),
                Some(true),
                (1, 0, 0),
            ),
            (
                None,
                true,
                true,
                Some(Entered),
                Some(false),
                Some(true),
                (0, 0, 0),
            ),
            (None, false, false, None, None, None, (0, 0, 0)),
            (
                None,
                false,
                true,
                Some(Left),
                Some(true),
                Some(false),
                (0, 0, 0),
            ),
            (
                Some(false),
                true,
                false,
                Some(Entered),
                None,
                Some(true),
                (0, 0, 1),
            ),
            (
                Some(false),
                true,
                true,
                Some(Entered),
                None,
                Some(true),
                (0, 0, 0),
            ),
            (
                Some(true),
                false,
                false,
                Some(Left),
                None,
                Some(false),
                (0, 0, 1),
            ),
            (
                Some(true),
                false,
                true,
                Some(Left),
                None,
                Some(false),
                (0, 0, 0),
            ),
            (Some(true), true, false, None, None, None, (0, 0, 0)),
            (
                Some(true),
                true,
                true,
                Some(Entered),
                Some(false),
                Some(true),
                (0, 0, 0),
            ),
            (Some(false), false, false, None, None, None, (0, 0, 0)),
            (
                Some(false),
                false,
                true,
                Some(Left),
                Some(true),
                Some(false),
                (0, 0, 0),
            ),
        ];
        for (stored, in_cohort, minted, want_change, want_stage1, want_post_ack, want_repairs) in
            cases
        {
            let why = format!("stored {stored:?}, truth {in_cohort}, minted {minted}");
            let (_dir, store) = temp_store();
            let filters = freeze(vec![behavioral_leaf(7)]);
            let lsk = single_leaf_lsk(&filters, 1);
            let alice = person(1);
            if let Some(bit) = stored {
                write_stage2(&store, 1, alice, bit);
            }

            let diff = diff_single_leaf_registers(
                PARTITION,
                &handle(&store),
                &filters,
                &[FoldedLeaf {
                    leaf_state_key: lsk,
                    person_id: alice,
                    in_cohort,
                    minted_transition: minted,
                    run_id: RUN,
                }],
                EVENT_MS,
                TS,
                ReadLane::Maintenance,
            )
            .await
            .unwrap();

            assert_eq!(
                diff.recompute
                    .changes
                    .iter()
                    .map(|change| change.status)
                    .collect::<Vec<_>>(),
                want_change.into_iter().collect::<Vec<_>>(),
                "{why}",
            );
            assert_eq!(
                diff.stage1_writes
                    .iter()
                    .map(|(_, state)| state.in_cohort)
                    .collect::<Vec<_>>(),
                want_stage1.into_iter().collect::<Vec<_>>(),
                "{why}: stage 1 records what downstream held before the emission",
            );
            assert_eq!(
                diff.recompute
                    .writes
                    .iter()
                    .map(|(_, state)| state.in_cohort)
                    .collect::<Vec<_>>(),
                want_post_ack.into_iter().collect::<Vec<_>>(),
                "{why}",
            );
            assert_eq!(repair_totals(diff.recompute.repairs), want_repairs, "{why}");
            assert_eq!(
                (
                    diff.recompute.composed.entered,
                    diff.recompute.composed.left
                ),
                (0, 0),
                "{why}: register changes are not composed transitions",
            );
        }
    }

    /// A register that already agrees with the post-transition truth cannot prove downstream was
    /// told: it is the pre-write of a retraction whose produce failed, or the row an apply left
    /// behind when it acked its membership and then held on its cascade. The minted transition
    /// wins, and the pre-write keeps its emission re-derivable if this produce fails too.
    #[tokio::test]
    async fn a_minted_transition_is_emitted_over_an_agreeing_register() {
        for (stored, status) in [
            (false, MembershipStatus::Left),
            (true, MembershipStatus::Entered),
        ] {
            let (_dir, store) = temp_store();
            let filters = freeze(vec![behavioral_leaf(7)]);
            let lsk = single_leaf_lsk(&filters, 1);
            let alice = person(1);
            write_stage2(&store, 1, alice, stored);

            let diff = diff_single_leaf_registers(
                PARTITION,
                &handle(&store),
                &filters,
                &[FoldedLeaf {
                    leaf_state_key: lsk,
                    person_id: alice,
                    in_cohort: stored,
                    minted_transition: true,
                    run_id: RUN,
                }],
                EVENT_MS,
                TS,
                ReadLane::Maintenance,
            )
            .await
            .unwrap();

            assert_eq!(diff.recompute.changes.len(), 1, "register {stored}");
            assert_eq!(diff.recompute.changes[0].status, status);
            assert_eq!(
                diff.stage1_writes[0].1.in_cohort, !stored,
                "register {stored}: stage 1 first records the value this emission retires",
            );
            assert_eq!(
                diff.recompute.writes[0].1.in_cohort, stored,
                "the post-ack bit"
            );
        }
    }

    /// The change carries the cohort's own coordinates, not the leaf's, so it lands on the same
    /// row a transition-derived change would.
    #[tokio::test]
    async fn a_register_derived_change_addresses_the_single_leaf_cohort() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7)]);
        let lsk = single_leaf_lsk(&filters, 1);
        let alice = person(1);

        let diff = diff_single_leaf_registers(
            PARTITION,
            &handle(&store),
            &filters,
            &[folded(lsk, alice, true)],
            EVENT_MS,
            TS,
            ReadLane::Maintenance,
        )
        .await
        .unwrap();

        let change = &diff.recompute.changes[0];
        assert_eq!(change.cohort_id, 1);
        assert_eq!(change.team_id, TEAM as i32);
        assert_eq!(change.person_id, alice.to_string());
        assert_eq!(change.last_updated, TS);
        assert_eq!(diff.stage1_writes[0].0.cohort_id, 1);
        assert_eq!(diff.recompute.writes[0].0.person_id, alice);
    }

    /// A composable cohort's bit is `recompute_stage2`'s to own. Diffing it here too would emit
    /// every composed flip twice.
    #[tokio::test]
    async fn a_composable_cohorts_leaf_is_not_register_diffed() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), person_leaf()]);
        let (beh_lsk, _) = and_leaf_keys(&filters);
        let alice = person(1);

        let diff = diff_single_leaf_registers(
            PARTITION,
            &handle(&store),
            &filters,
            &[folded(beh_lsk, alice, true)],
            EVENT_MS,
            TS,
            ReadLane::Maintenance,
        )
        .await
        .unwrap();

        assert!(diff.recompute.changes.is_empty());
        assert!(diff.recompute.writes.is_empty());
        assert!(diff.stage1_writes.is_empty());
    }

    /// Mirrors the composed path: a merge-carried fallback is claimed by the first local
    /// evaluation even when the bit it holds is already right.
    #[tokio::test]
    async fn a_transferred_fallback_is_rewritten_without_an_emission() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7)]);
        let lsk = single_leaf_lsk(&filters, 1);
        let alice = person(1);
        let key = Stage2Key {
            partition_id: PARTITION,
            team_id: TEAM,
            cohort_id: 1,
            person_id: alice,
        };
        let state = Stage2State {
            in_cohort: true,
            last_evaluated_at_ms: EVENT_MS,
        };
        store
            .write_batch(|b| b.put_stage2(&key, &state.encode_transferred_fallback()))
            .unwrap();

        let diff = diff_single_leaf_registers(
            PARTITION,
            &handle(&store),
            &filters,
            &[folded(lsk, alice, true)],
            EVENT_MS,
            TS,
            ReadLane::Maintenance,
        )
        .await
        .unwrap();

        assert!(diff.recompute.changes.is_empty(), "the bit did not flip");
        assert!(diff.stage1_writes.is_empty(), "the row agrees");
        assert_eq!(
            diff.recompute.writes,
            vec![(key, state)],
            "the fallback is claimed locally",
        );
    }

    /// An undecodable row cannot say what downstream was told, so it reads as absent: an entry is
    /// emitted, a non-member is not, and either way stage 1 replaces the row with a readable bit.
    #[tokio::test]
    async fn a_corrupt_register_row_reads_as_never_told_and_is_replaced() {
        for (in_cohort, minted, want_changes, want_stage1, want_repairs) in [
            (true, false, 1, false, (0, 1, 0)),
            (false, false, 0, false, (0, 0, 0)),
            (true, true, 1, false, (0, 0, 0)),
            (false, true, 1, true, (0, 0, 0)),
        ] {
            let (_dir, store) = temp_store();
            let filters = freeze(vec![behavioral_leaf(7)]);
            let lsk = single_leaf_lsk(&filters, 1);
            let alice = person(1);
            let key = Stage2Key {
                partition_id: PARTITION,
                team_id: TEAM,
                cohort_id: 1,
                person_id: alice,
            };
            store
                .write_batch(|b| b.put_stage2(&key, b"not a stage 2 state"))
                .unwrap();

            let diff = diff_single_leaf_registers(
                PARTITION,
                &handle(&store),
                &filters,
                &[FoldedLeaf {
                    leaf_state_key: lsk,
                    person_id: alice,
                    in_cohort,
                    minted_transition: minted,
                    run_id: RUN,
                }],
                EVENT_MS,
                TS,
                ReadLane::Maintenance,
            )
            .await
            .unwrap();

            assert_eq!(
                diff.recompute.changes.len(),
                want_changes,
                "truth {in_cohort}, minted {minted}"
            );
            assert_eq!(
                diff.stage1_writes.len(),
                1,
                "truth {in_cohort}, minted {minted}: the row is replaced"
            );
            assert_eq!(diff.stage1_writes[0].1.in_cohort, want_stage1);
            assert_eq!(repair_totals(diff.recompute.repairs), want_repairs);
            assert_eq!(
                (
                    diff.recompute.composed.entered,
                    diff.recompute.composed.left
                ),
                (0, 0),
            );
        }
    }

    fn repair_totals(repairs: RepairCounts) -> (u64, u64, u64) {
        let total = |counts: StatusCounts| counts.entered + counts.left;
        (
            total(repairs.absent),
            total(repairs.corrupt),
            total(repairs.mismatch),
        )
    }

    /// Two single-leaf cohorts on one leaf both diff, and a leaf the catalog does not back costs
    /// nothing. Those are the two halves of the fan-out the seed paths depend on.
    #[tokio::test]
    async fn the_diff_fans_out_to_every_single_leaf_cohort_on_the_leaf() {
        let (_dir, store) = temp_store();
        let filters = freeze_cascade(
            vec![(1, vec![behavioral_leaf(7)]), (2, vec![behavioral_leaf(7)])],
            false,
        );
        let lsk = single_leaf_lsk(&filters, 1);
        let alice = person(1);
        write_stage2(&store, 1, alice, true);

        let diff = diff_single_leaf_registers(
            PARTITION,
            &handle(&store),
            &filters,
            &[
                folded(lsk, alice, true),
                folded(LeafStateKey([0xEE; 16]), alice, true),
            ],
            EVENT_MS,
            TS,
            ReadLane::Maintenance,
        )
        .await
        .unwrap();

        assert_eq!(
            diff.recompute
                .changes
                .iter()
                .map(|change| change.cohort_id)
                .collect::<Vec<_>>(),
            vec![2],
            "cohort 1's register was already true; the unbacked leaf contributes nothing",
        );
        assert_eq!(diff.stage1_writes.len(), 1, "only cohort 2 had no row");
    }

    // ---- Sharing one person's inputs across their cohorts ----
    //
    // Every test below holds `recompute_stage2_by_person` to the cohort-ordered path as an oracle
    // over the same store, then asserts what the shared read had to get right for the two to agree.

    use crate::workers::stage2_person_inputs::{recompute_stage2_by_person, READ_CHUNK_KEYS};

    /// Run both recompute orders over the same store and return the agreed result. Neither commits,
    /// so running them back to back reads the same durable state twice.
    async fn recompute_both_ways(
        store: &CohortStore,
        filters: &TeamFilters,
        team_id: i32,
        affected: &[(LeafStateKey, Uuid)],
    ) -> Stage2Recompute {
        let handle = handle(store);
        let cohort_ordered = recompute_stage2(
            PARTITION,
            &handle,
            filters,
            affected,
            EVENT_MS,
            TS,
            ReadLane::Maintenance,
        )
        .await
        .unwrap();
        let by_person = recompute_stage2_by_person(
            PARTITION,
            &handle,
            TeamId(team_id),
            filters,
            affected,
            EVENT_MS,
            TS,
        )
        .await
        .unwrap();

        assert_eq!(
            by_person.changes, cohort_ordered.changes,
            "sharing a person's inputs changed which flips the run emits",
        );
        assert_eq!(
            by_person.writes, cohort_ordered.writes,
            "sharing a person's inputs changed which cf_stage2 rows the run owes",
        );
        assert_eq!(
            by_person.evaluated(),
            cohort_ordered.evaluated(),
            "sharing a person's inputs changed how many pairs the run composed",
        );
        by_person
    }

    fn compressed_leaf(op: &str, value: i64) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event_multiple", "key": "$pageview",
            "time_value": 1, "time_interval": "year",
            "operator": op, "operator_value": value,
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn compressed_state(count: u32) -> Stage1State {
        Stage1State::BehavioralCompressedHistory {
            entries: vec![(20_607, count)],
            window_start_day: 20_600,
            last_event_at_ms: EVENT_MS,
            earliest_eviction_at_ms: i64::MAX,
        }
    }

    fn statuses(recompute: &Stage2Recompute) -> Vec<(i32, MembershipStatus)> {
        recompute
            .changes
            .iter()
            .map(|change| (change.cohort_id, change.status))
            .collect()
    }

    fn other_person_leaf() -> Value {
        json!({
            "type": "person", "key": "email", "value": "someone@example.com", "operator": "exact",
            "conditionHash": "0f0f0f0f0f0f0f0f",
            "bytecode": ["_H", 1, 32, "someone@example.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    /// Cohort 4 names a second person condition the record does not match, so a read that answered
    /// the record as one bit rather than per condition would enter it.
    #[tokio::test]
    async fn shared_inputs_compose_every_leaf_variant_from_one_read() {
        let (_dir, store) = temp_store();
        let filters = freeze_cascade(
            vec![
                (1, vec![behavioral_leaf(7), person_leaf()]),
                (2, vec![daily_leaf(7, "gte", 2), person_leaf()]),
                (3, vec![compressed_leaf("gte", 2), person_leaf()]),
                (4, vec![behavioral_leaf(7), other_person_leaf()]),
            ],
            false,
        );
        let single_lsk = filters.by_condition_to_lsk[&HASH]
            .iter()
            .copied()
            .find(|lsk| filters.by_lsk[lsk].variant == StateVariant::BehavioralSingle)
            .unwrap();
        let daily_lsk = filters.by_condition_to_lsk[&HASH]
            .iter()
            .copied()
            .find(|lsk| filters.by_lsk[lsk].variant == StateVariant::BehavioralDailyBuckets)
            .unwrap();
        let compressed_lsk = filters.by_condition_to_lsk[&HASH]
            .iter()
            .copied()
            .find(|lsk| filters.by_lsk[lsk].variant == StateVariant::BehavioralCompressedHistory)
            .unwrap();
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let alice = person(1);

        write_behavioral(&store, single_lsk, alice, behavioral_match());
        write_behavioral(&store, daily_lsk, alice, daily_state(2));
        write_behavioral(&store, compressed_lsk, alice, compressed_state(2));
        write_person_record(&store, alice, &[PERSON_HASH]);

        // Cohort 4 hangs off the shared behavioral leaf, not the person condition.
        let affected = [(single_lsk, alice), (per_lsk, alice)];
        let entered = recompute_both_ways(&store, &filters, TEAM as i32, &affected).await;
        assert_eq!(
            statuses(&entered),
            vec![
                (1, MembershipStatus::Entered),
                (2, MembershipStatus::Entered),
                (3, MembershipStatus::Entered),
            ],
            "each variant's comparator still decides its own leaf, and the unmatched person \
             condition keeps cohort 4 out of the same record's answers",
        );
        // Both orders build the change through one shared `record_pair`, so only a literal pins
        // which team the shared read stamped on it.
        assert!(entered
            .changes
            .iter()
            .all(|change| change.team_id == TEAM as i32));

        // The daily leaf now misses its threshold, and only that cohort may leave.
        write_behavioral(&store, daily_lsk, alice, daily_state(1));
        for cohort in [1, 2, 3] {
            write_stage2(&store, cohort, alice, true);
        }
        let left = recompute_both_ways(&store, &filters, TEAM as i32, &affected).await;
        assert_eq!(statuses(&left), vec![(2, MembershipStatus::Left)]);
    }

    /// The referrer must read the referent's *stored* bit, not the one this run is about to write,
    /// or it emits a cascade nothing has acknowledged.
    #[tokio::test]
    async fn a_referent_recomputed_in_the_same_call_is_still_read_from_the_store() {
        let (_dir, store) = temp_store();
        let filters = freeze_cascade(
            vec![
                (1, vec![person_leaf(), cohort_ref(2)]),
                (2, vec![behavioral_leaf(7), person_leaf()]),
            ],
            true,
        );
        let beh_lsk = filters.by_condition_to_lsk[&HASH][0];
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let alice = person(1);

        write_behavioral(&store, beh_lsk, alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);
        // Cohort 2 will recompute to `true` in this same call; the store still says `false`.
        write_stage2(&store, 2, alice, false);

        let recompute =
            recompute_both_ways(&store, &filters, TEAM as i32, &[(per_lsk, alice)]).await;

        assert_eq!(
            statuses(&recompute),
            vec![(2, MembershipStatus::Entered)],
            "cohort 1 read the stored `false` for its referent and did not enter",
        );
    }

    /// The one reference kind whose bit comes back through the behavioral batch. Resolving it from
    /// a stored membership row instead would read every referrer of a single-leaf cohort as a
    /// non-member.
    #[tokio::test]
    async fn a_single_leaf_referent_resolves_through_its_own_leaf_and_comparator() {
        let (_dir, store) = temp_store();
        let filters = freeze_cascade(
            vec![
                (1, vec![person_leaf(), cohort_ref(3)]),
                (3, vec![daily_leaf(7, "gte", 2)]),
            ],
            true,
        );
        assert!(
            matches!(
                filters.eligibility[&CohortId(3)],
                CohortEligibility::SingleLeaf(_)
            ),
            "cohort 3 has to be the single-leaf kind for this to be the case under test",
        );
        let referent_lsk = single_leaf_lsk(&filters, 3);
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let alice = person(1);
        write_person_record(&store, alice, &[PERSON_HASH]);

        // Below the referent's threshold: the referrer must not enter, even though the referent has
        // behavioral state and no cf_stage2 row of its own to read.
        write_behavioral(&store, referent_lsk, alice, daily_state(1));
        let below = recompute_both_ways(&store, &filters, TEAM as i32, &[(per_lsk, alice)]).await;
        assert!(
            below.changes.is_empty(),
            "the referent's own comparator says it is not a member",
        );

        write_behavioral(&store, referent_lsk, alice, daily_state(2));
        let above = recompute_both_ways(&store, &filters, TEAM as i32, &[(per_lsk, alice)]).await;
        assert_eq!(statuses(&above), vec![(1, MembershipStatus::Entered)]);
    }

    /// One referent named twice with opposite negation is one row and two consistent answers.
    #[tokio::test]
    async fn a_referent_named_twice_with_opposite_negation_reads_one_row() {
        let (_dir, store) = temp_store();
        let filters = freeze_cascade(
            vec![
                (1, vec![person_leaf(), cohort_ref(2), negated_cohort_ref(2)]),
                (2, vec![behavioral_leaf(7), person_leaf()]),
            ],
            true,
        );
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let alice = person(1);

        write_person_record(&store, alice, &[PERSON_HASH]);
        write_stage2(&store, 2, alice, true);

        let recompute =
            recompute_both_ways(&store, &filters, TEAM as i32, &[(per_lsk, alice)]).await;
        assert!(
            !recompute.changes.iter().any(|change| change.cohort_id == 1),
            "`ref AND NOT ref` over one bit cannot be satisfied",
        );
        assert_eq!(
            recompute.evaluated(),
            2,
            "both cohorts composed; cohort 1 just could not satisfy `ref AND NOT ref`",
        );
    }

    /// A transferred fallback is still settled on a pair that does not flip.
    #[tokio::test]
    async fn corrupt_rows_stay_non_member_and_a_transferred_fallback_still_settles() {
        let (_dir, store) = temp_store();
        let filters = freeze_cascade(
            vec![
                (1, vec![behavioral_leaf(7), person_leaf()]),
                (2, vec![daily_leaf(7, "gte", 2), person_leaf()]),
            ],
            false,
        );
        let beh_lsk = filters.by_condition_to_lsk[&HASH]
            .iter()
            .copied()
            .find(|lsk| filters.by_lsk[lsk].variant == StateVariant::BehavioralSingle)
            .unwrap();
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let alice = person(1);

        write_behavioral(&store, beh_lsk, alice, behavioral_match());
        write_corrupt_person_record(&store, alice);
        // Cohort 1's row is already `false` and carries a transfer fallback, so the receiver has to
        // claim it even though the bit does not move.
        let key = Stage2Key {
            partition_id: PARTITION,
            team_id: TEAM,
            cohort_id: 1,
            person_id: alice,
        };
        let fallback = Stage2State {
            in_cohort: false,
            last_evaluated_at_ms: EVENT_MS,
        };
        store
            .write_batch(|b| b.put_stage2(&key, &fallback.encode_transferred_fallback()))
            .unwrap();

        let recompute =
            recompute_both_ways(&store, &filters, TEAM as i32, &[(per_lsk, alice)]).await;

        assert!(
            recompute.changes.is_empty(),
            "a corrupt person record reads every person leaf as a non-member",
        );
        assert_eq!(
            recompute.writes,
            vec![(
                key,
                Stage2State {
                    in_cohort: false,
                    last_evaluated_at_ms: EVENT_MS,
                }
            )],
            "the fallback row is rewritten once, and the ordinary no-flip row is left alone",
        );
    }

    /// Sharing is per person, so neither may see the other's record or leaves.
    #[tokio::test]
    async fn two_persons_in_one_call_keep_their_own_inputs() {
        let (_dir, store) = temp_store();
        let filters = freeze_cascade(
            vec![
                (1, vec![behavioral_leaf(7), person_leaf()]),
                (2, vec![behavioral_leaf(7), person_leaf()]),
            ],
            false,
        );
        let beh_lsk = filters.by_condition_to_lsk[&HASH][0];
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let (alice, bob) = (person(1), person(2));

        write_behavioral(&store, beh_lsk, alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);
        // Bob matches the person condition but has no behavioral state.
        write_person_record(&store, bob, &[PERSON_HASH]);

        let recompute = recompute_both_ways(
            &store,
            &filters,
            TEAM as i32,
            &[(per_lsk, alice), (per_lsk, bob)],
        )
        .await;

        assert_eq!(
            recompute
                .changes
                .iter()
                .map(|change| (change.cohort_id, change.person_id.clone()))
                .collect::<Vec<_>>(),
            vec![(1, alice.to_string()), (2, alice.to_string()),],
            "changes stay in (cohort, person) order and Bob's missing leaf keeps him out",
        );
        assert_eq!(
            recompute.evaluated(),
            4,
            "both persons composed both cohorts"
        );
    }

    /// The same person and the same leaf under a different team must not see the first team's rows.
    #[tokio::test]
    async fn state_written_for_one_team_is_invisible_to_another() {
        let (_dir, store) = temp_store();
        let leaves = vec![behavioral_leaf(7), person_leaf()];
        let ours = freeze_for_team(TEAM as i32, leaves.clone());
        let theirs = freeze_for_team(TEAM as i32 + 1, leaves);
        let beh_lsk = ours.by_condition_to_lsk[&HASH][0];
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let alice = person(1);

        write_behavioral(&store, beh_lsk, alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);

        let ours_recompute =
            recompute_both_ways(&store, &ours, TEAM as i32, &[(per_lsk, alice)]).await;
        assert_eq!(
            statuses(&ours_recompute),
            vec![(1, MembershipStatus::Entered)]
        );

        let theirs_recompute =
            recompute_both_ways(&store, &theirs, TEAM as i32 + 1, &[(per_lsk, alice)]).await;
        assert!(
            theirs_recompute.changes.is_empty(),
            "the neighbouring team's keyspace holds none of this state",
        );
    }

    fn wide_behavioral_leaf(index: usize) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event", "key": "$pageview",
            "time_value": 7, "time_interval": "day",
            "conditionHash": format!("beh{index:013}"),
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn wide_behavioral_hash(index: usize) -> [u8; 16] {
        format!("beh{index:013}").as_bytes().try_into().unwrap()
    }

    /// Widths derived from the chunk size, so the tests sit on the boundary wherever it moves:
    /// exactly one chunk catches a `<` for `<=` slip, and one past it makes the second section run.
    const CHUNK_BOUNDARY_WIDTHS: [usize; 2] = [READ_CHUNK_KEYS, READ_CHUNK_KEYS + 1];

    /// A chunk the read skipped would leave its leaves non-member and break the AND, so the entry
    /// proves every chunk landed.
    #[tokio::test]
    async fn a_cohort_wider_than_one_chunk_reads_every_leaf() {
        for leaves in CHUNK_BOUNDARY_WIDTHS {
            let (_dir, store) = temp_store();
            let filters = freeze((0..leaves).map(wide_behavioral_leaf).collect());
            let lsks: Vec<LeafStateKey> = (0..leaves)
                .map(|index| filters.by_condition_to_lsk[&wide_behavioral_hash(index)][0])
                .collect();
            let alice = person(1);
            for &lsk in &lsks {
                write_behavioral(&store, lsk, alice, behavioral_match());
            }

            let entered =
                recompute_both_ways(&store, &filters, TEAM as i32, &[(lsks[0], alice)]).await;
            assert_eq!(
                statuses(&entered),
                vec![(1, MembershipStatus::Entered)],
                "{leaves} leaves",
            );

            // The `Entered` above proves every chunk landed. This half pins that the last leaf's
            // value is read, not just its key.
            write_behavioral(
                &store,
                lsks[leaves - 1],
                alice,
                Stage1State::BehavioralSingle {
                    has_match: false,
                    last_event_at_ms: EVENT_MS,
                    earliest_eviction_at_ms: i64::MAX,
                },
            );
            write_stage2(&store, 1, alice, true);
            let left =
                recompute_both_ways(&store, &filters, TEAM as i32, &[(lsks[0], alice)]).await;
            assert_eq!(
                statuses(&left),
                vec![(1, MembershipStatus::Left)],
                "{leaves} leaves",
            );
        }
    }

    /// The pair whose prior row already agrees is the last one, so only a read that reached the end
    /// of the key set stays silent.
    #[tokio::test]
    async fn a_person_in_more_cohorts_than_one_chunk_reads_every_prior_row() {
        for cohorts in CHUNK_BOUNDARY_WIDTHS {
            let last = cohorts as i32;
            let (_dir, store) = temp_store();
            let filters = freeze_cascade(
                (1..=last)
                    .map(|id| (id, vec![behavioral_leaf(7), person_leaf()]))
                    .collect(),
                false,
            );
            let beh_lsk = filters.by_condition_to_lsk[&HASH][0];
            let alice = person(1);
            write_behavioral(&store, beh_lsk, alice, behavioral_match());
            write_person_record(&store, alice, &[PERSON_HASH]);
            write_stage2(&store, last as u64, alice, true);

            let recompute =
                recompute_both_ways(&store, &filters, TEAM as i32, &[(beh_lsk, alice)]).await;

            assert_eq!(
                recompute.evaluated(),
                cohorts as u64,
                "every cohort on the leaf composed ({cohorts} cohorts)",
            );
            assert_eq!(
                recompute.changes.len(),
                cohorts - 1,
                "the one cohort whose stored bit already said `true` did not flip ({cohorts} cohorts)",
            );
            assert!(
                !recompute
                    .changes
                    .iter()
                    .any(|change| change.cohort_id == last),
                "and it is the last cohort, whose row sits at the end of the key set",
            );
        }
    }

    /// Wide fanout over mostly shared state, with per-cohort leaves big enough that re-reading them
    /// is not free. With `referencing`, every cohort also names two referents off the seeded leaf:
    /// a single-leaf cohort, resolved through the behavioral batch, and a composable one, resolved
    /// from its stored row. Those are the reads the cohort-ordered path pays extra offloads for.
    fn wide_fixture(
        store: &CohortStore,
        cohorts: usize,
        persons: usize,
        referencing: bool,
    ) -> (TeamFilters, Vec<(LeafStateKey, Uuid)>) {
        let shared = 0;
        let single_leaf_referent = cohorts as i32 + 1;
        let composable_referent = cohorts as i32 + 2;
        let mut definitions: Vec<(i32, Vec<Value>)> = (0..cohorts)
            .map(|index| {
                let mut leaves = vec![
                    wide_behavioral_leaf(shared),
                    wide_compressed_leaf(index + 1),
                    person_leaf(),
                ];
                if referencing {
                    leaves.push(cohort_ref(single_leaf_referent));
                    leaves.push(cohort_ref(composable_referent));
                }
                (index as i32 + 1, leaves)
            })
            .collect();
        if referencing {
            definitions.push((single_leaf_referent, vec![wide_compressed_leaf(0)]));
            definitions.push((
                composable_referent,
                vec![wide_compressed_leaf(0), person_leaf()],
            ));
        }
        let filters = freeze_cascade(definitions, referencing);
        let shared_lsk = filters.by_condition_to_lsk[&wide_behavioral_hash(shared)][0];

        let mut affected = Vec::with_capacity(persons);
        for index in 0..persons {
            let who = person(index as u128 + 1);
            write_behavioral(store, shared_lsk, who, behavioral_match());
            for cohort in 0..cohorts {
                let own = filters.by_condition_to_lsk[&wide_compressed_hash(cohort + 1)][0];
                write_behavioral(store, own, who, year_long_compressed_state());
            }
            if referencing {
                let referent = filters.by_condition_to_lsk[&wide_compressed_hash(0)][0];
                write_behavioral(store, referent, who, year_long_compressed_state());
                write_stage2(store, composable_referent as u64, who, true);
            }
            write_person_record(store, who, &[PERSON_HASH]);
            affected.push((shared_lsk, who));
        }
        (filters, affected)
    }

    fn wide_compressed_leaf(index: usize) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event_multiple", "key": "$pageview",
            "time_value": 1, "time_interval": "year",
            "operator": "gte", "operator_value": 1,
            "conditionHash": format!("cmp{index:013}"),
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn wide_compressed_hash(index: usize) -> [u8; 16] {
        format!("cmp{index:013}").as_bytes().try_into().unwrap()
    }

    /// One entry per day of the window, so each value is kilobytes rather than bytes.
    fn year_long_compressed_state() -> Stage1State {
        Stage1State::BehavioralCompressedHistory {
            entries: (0..365).map(|day| (20_600 + day, 1)).collect(),
            window_start_day: 20_600,
            last_event_at_ms: EVENT_MS,
            earliest_eviction_at_ms: i64::MAX,
        }
    }

    /// Benchmark, not a test. Run it in release:
    ///
    /// ```text
    /// cargo test -p cohort-stream-processor --release --lib \
    ///     recompute_orders_benchmark -- --ignored --nocapture
    /// ```
    ///
    /// It asserts agreement only, because a wall-time threshold would flake on a slower box. Reads
    /// per source and memory come from `cohort_seed_recompute_*` under real load.
    #[tokio::test]
    #[ignore = "benchmark; run in release with --ignored --nocapture"]
    async fn recompute_orders_benchmark() {
        use std::time::Instant;

        const PERSONS: usize = 500;

        println!(
            "{:>8}  {:>5}  {:>8}  {:>12}  {:>12}  {:>7}",
            "cohorts", "refs", "pairs", "by-cohort", "by-person", "ratio"
        );
        let shapes = [1, 4, 14]
            .into_iter()
            .flat_map(|cohorts| [(cohorts, false), (cohorts, true)]);
        for (cohorts, referencing) in shapes {
            let (_dir, store) = temp_store();
            let (filters, affected) = wide_fixture(&store, cohorts, PERSONS, referencing);
            let handle = handle(&store);
            let run_by_cohort = || {
                recompute_stage2(
                    PARTITION,
                    &handle,
                    &filters,
                    &affected,
                    EVENT_MS,
                    TS,
                    ReadLane::Maintenance,
                )
            };
            let run_by_person = || {
                recompute_stage2_by_person(
                    PARTITION,
                    &handle,
                    TeamId(TEAM as i32),
                    &filters,
                    &affected,
                    EVENT_MS,
                    TS,
                )
            };

            // Warm the block cache, so the timed pass measures the read shape and not the first
            // touch of every SST.
            let warm_by_cohort = run_by_cohort().await.unwrap();
            let warm_by_person = run_by_person().await.unwrap();
            assert_eq!(warm_by_person.changes, warm_by_cohort.changes);
            assert_eq!(warm_by_person.writes, warm_by_cohort.writes);

            let started = Instant::now();
            run_by_cohort().await.unwrap();
            let by_cohort = started.elapsed();

            let started = Instant::now();
            run_by_person().await.unwrap();
            let by_person = started.elapsed();

            println!(
                "{:>8}  {:>5}  {:>8}  {:>10.1?}  {:>10.1?}  {:>6.2}x",
                cohorts,
                if referencing { "yes" } else { "no" },
                cohorts * PERSONS,
                by_cohort,
                by_person,
                by_cohort.as_secs_f64() / by_person.as_secs_f64(),
            );
        }
    }
}
