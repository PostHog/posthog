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
use crate::stage2::CohortEligibility;
use crate::store::{
    BehavioralKey, PersonRecordKey, ReadLane, Stage2Key, StagedBatch, StoreError, StoreHandle,
};

/// `affected_leaves` is the touched `(leaf, person)` set; `lane` is the read lane every recompute
/// read runs on (`Maintenance` on the seed path, so backfill never contends with live reads).
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

/// The read-only half of [`compose_stage2`].
pub(crate) async fn recompute_stage2(
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

    let mut changes = Vec::new();
    let mut writes: Vec<(Stage2Key, Stage2State)> = Vec::new();
    let mut evaluated: u64 = 0;
    let mut composed = StatusCounts::default();

    for (cohort_id, person_id) in affected {
        let Some(tree) = filters.cohorts.get(&cohort_id) else {
            continue;
        };

        let diff = recompute_and_diff(partition_id, person_id, tree, filters, handle, lane).await?;
        evaluated += 1;
        if diff.flipped() {
            composed.count(diff.status());
            changes.push(CohortMembershipChange {
                team_id: tree.team_id.0,
                cohort_id: cohort_id.0,
                person_id: person_id.to_string(),
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
            writes.push((
                diff.stage2_key,
                Stage2State {
                    in_cohort: diff.new_bit,
                    last_evaluated_at_ms: event_ms,
                },
            ));
        }
    }

    Ok(Stage2Recompute {
        changes,
        writes,
        evaluated,
        composed,
        ..Default::default()
    })
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
/// Shared by Stage 2 composition and the cascade handler so the two recompute paths cannot diverge.
pub(crate) struct RecomputeDiff {
    pub new_bit: bool,
    pub prior_bit: bool,
    pub stage2_key: Stage2Key,
    settles_transfer_fallback: bool,
}

impl RecomputeDiff {
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
    let prior = read_prior_stage2_state(handle, &stage2_key, lane).await?;
    Ok(RecomputeDiff {
        new_bit,
        prior_bit: prior.in_cohort,
        stage2_key,
        settles_transfer_fallback: prior.ownership == Stage2Ownership::TransferredFallback,
    })
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
        match filters.eligibility.get(&ref_id) {
            Some(CohortEligibility::SingleLeaf(lsk)) => single_leaf_refs.push((ref_id, *lsk)),
            Some(elig) if elig.writes_cf_stage2() => composable_refs.push(ref_id),
            // Excluded, cyclic, or absent from the catalog: non-member.
            _ => {
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
fn decode_stage1_state(bytes: Option<Vec<u8>>) -> Option<Stage1State> {
    let bytes = bytes?;
    match StatefulRecord::decode(&bytes) {
        Ok(record) => Some(record.state),
        Err(_) => {
            counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
            None
        }
    }
}

#[derive(Clone, Copy)]
struct PriorStage2State {
    in_cohort: bool,
    ownership: Stage2Ownership,
}

/// Decode both the logical prior bit and its ownership. Missing or corrupt rows keep the existing
/// fail-closed `false` behavior and are never mistaken for a transferred fallback.
async fn read_prior_stage2_state(
    handle: &StoreHandle,
    key: &Stage2Key,
    lane: ReadLane,
) -> Result<PriorStage2State, StoreError> {
    let Some(bytes) = handle.get_stage2(key, lane).await? else {
        return Ok(PriorStage2State {
            in_cohort: false,
            ownership: Stage2Ownership::Local,
        });
    };
    match Stage2State::decode_with_ownership(&bytes) {
        Ok((state, ownership)) => Ok(PriorStage2State {
            in_cohort: state.in_cohort,
            ownership,
        }),
        Err(_) => {
            counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
            Ok(PriorStage2State {
                in_cohort: false,
                ownership: Stage2Ownership::Local,
            })
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
fn collect_leaf_state_keys(node: &FilterNode, out: &mut Vec<LeafStateKey>) {
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
fn collect_cohort_refs(node: &FilterNode, out: &mut Vec<CohortId>) {
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
        let cohort = json!({ "properties": { "type": "AND", "values": values } });
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(TEAM as i32), &cohort)
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
}
