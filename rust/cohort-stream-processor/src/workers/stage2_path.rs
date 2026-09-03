//! Stage 2 composition: re-evaluates multi-leaf cohorts when Stage 1 flips a leaf.
//!
//! [`compose_stage2`] reads each affected cohort's leaf states, evaluates the tree, diffs against the
//! stored `cf_stage2` bit, and emits membership changes on a flip. At-most-once: a crash between
//! the Stage 1 and Stage 2 commits drops a flip, but `evaluate_tree` recomputes the whole cohort
//! each event, so a mismatch self-heals on the person's next event.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use metrics::counter;
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::tree::{CohortLeaf, CohortTree, FilterNode};
use crate::filters::CohortId;
use crate::observability::metrics::{
    SEED_REGISTER_REPAIRS_TOTAL, STAGE2_COHORTS_EVALUATED, STAGE2_STATE_DECODE_ERROR,
    STAGE2_TRANSITIONS,
};
use crate::producer::{CohortMembershipChange, MembershipStatus};
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
    repairs: StatusCounts,
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

    /// Nothing to emit and nothing to commit.
    pub(crate) fn is_empty(&self) -> bool {
        self.changes.is_empty() && self.writes.is_empty()
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
        for (count, status) in [
            (self.entered, MembershipStatus::Entered),
            (self.left, MembershipStatus::Left),
        ] {
            if count > 0 {
                counter!(metric, "kind" => status.as_str()).increment(count);
            }
        }
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
            // Write `false` rather than deleting so absence means "never evaluated". A no-flip
            // transferred fallback is rewritten once so receiver evaluation claims ownership.
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
        repairs: StatusCounts::default(),
    })
}

/// One leaf a seed apply folded, with the membership its resulting state implies. The caller holds
/// that truth already, so the register diff never re-reads `cf_behavioral`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct FoldedLeaf {
    pub leaf_state_key: LeafStateKey,
    pub person_id: Uuid,
    pub in_cohort: bool,
    /// Whether stage 1 minted a transition for this leaf in this apply. Only the fold knows it, and
    /// it is what separates an ordinary flip from a register repair in the metrics.
    pub minted_transition: bool,
}

impl FoldedLeaf {
    pub(crate) fn pair(self) -> (LeafStateKey, Uuid) {
        (self.leaf_state_key, self.person_id)
    }
}

/// What the single-leaf register diff decided for one apply.
#[must_use]
#[derive(Default)]
pub(crate) struct RegisterDiff {
    /// Changes to emit and the rows to commit after the ack; folds into the composed recompute.
    pub recompute: Stage2Recompute,
    /// `false` rows for `(cohort, person)` pairs that had no row; the caller stages them in stage 1.
    pub placeholders: Vec<(Stage2Key, Stage2State)>,
}

/// Derive each single-leaf cohort's membership change by diffing the folded leaf's truth against
/// the persisted register row, which on the seed paths records what downstream was last told.
///
/// The register bit lags the truth exactly when an earlier apply committed stage 1 and then failed
/// to produce, so the diff re-detects that lag on redelivery and re-emits, using the same protocol
/// the composed bits and the cascade path already use. A row with no prior value counts as "never
/// told", so an entry is emitted and a `false` placeholder is staged for the reconcile scan to
/// enumerate.
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
            wanted.insert(
                Stage2Key {
                    partition_id,
                    team_id: tree.team_id.0 as u64,
                    cohort_id: cohort_id.0 as u64,
                    person_id: leaf.person_id,
                },
                WantedRegister {
                    team_id: tree.team_id.0,
                    cohort_id: *cohort_id,
                    in_cohort: leaf.in_cohort,
                    minted_transition: leaf.minted_transition,
                },
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
    let mut placeholders: Vec<(Stage2Key, Stage2State)> = Vec::new();
    let mut repairs = StatusCounts::default();
    for ((key, want), bytes) in wanted.into_iter().zip(stored) {
        let state = Stage2State {
            in_cohort: want.in_cohort,
            last_evaluated_at_ms: evaluated_at_ms,
        };
        let (emits, rewrites) = match read_register(bytes) {
            // A no-flip transferred fallback is still rewritten once, so receiver evaluation claims
            // the row the way the composed path claims its own.
            Some(prior) if prior.in_cohort == want.in_cohort => (
                false,
                prior.ownership == Stage2Ownership::TransferredFallback,
            ),
            Some(_) => (true, true),
            None => {
                // An absent row cannot prove what downstream holds, so a transition stage 1 minted
                // this apply is authoritative: without this, a `Left` over a row an earlier apply
                // never wrote is swallowed and the stale entry outlives the state behind it.
                let emits = want.in_cohort || want.minted_transition;
                // The placeholder is what downstream is taken to hold before this emission, which
                // is the opposite of the truth being emitted. That keeps the change re-derivable:
                // if the produce fails, the redelivery diffs against this row and re-emits.
                placeholders.push((
                    key,
                    Stage2State {
                        in_cohort: emits && !want.in_cohort,
                        last_evaluated_at_ms: evaluated_at_ms,
                    },
                ));
                (emits, emits)
            }
        };
        if emits {
            let status = membership_status(want.in_cohort);
            if !want.minted_transition {
                repairs.count(status);
            }
            changes.push(CohortMembershipChange {
                team_id: want.team_id,
                cohort_id: want.cohort_id.0,
                person_id: key.person_id.to_string(),
                last_updated: last_updated.to_string(),
                status,
                origin: None,
                run_id: None,
            });
        }
        if rewrites {
            writes.push((key, state));
        }
    }

    Ok(RegisterDiff {
        recompute: Stage2Recompute {
            changes,
            writes,
            // The register diff evaluates nothing, so `STAGE2_COHORTS_EVALUATED` keeps meaning
            // composed evaluations.
            evaluated: 0,
            composed: StatusCounts::default(),
            repairs,
        },
        placeholders,
    })
}

/// One `(single-leaf cohort, person)` the fold decided, before its stored row is read.
struct WantedRegister {
    team_id: i32,
    cohort_id: CohortId,
    in_cohort: bool,
    minted_transition: bool,
}

fn membership_status(in_cohort: bool) -> MembershipStatus {
    if in_cohort {
        MembershipStatus::Entered
    } else {
        MembershipStatus::Left
    }
}

/// Decode a register row, keeping absence distinct from a stored `false`, because the diff has to
/// tell "never told" from "told `false`". A corrupt row reads as absent and is counted, so the
/// placeholder overwrites it with a decodable bit.
fn read_register(bytes: Option<Vec<u8>>) -> Option<PriorStage2State> {
    let bytes = bytes?;
    match Stage2State::decode_with_ownership(&bytes) {
        Ok((state, ownership)) => Some(PriorStage2State {
            in_cohort: state.in_cohort,
            ownership,
        }),
        Err(_) => {
            counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
            None
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

    /// `minted_transition` only labels the repair metric, so the diff tests leave it false.
    fn folded(leaf_state_key: LeafStateKey, person_id: Uuid, in_cohort: bool) -> FoldedLeaf {
        FoldedLeaf {
            leaf_state_key,
            person_id,
            in_cohort,
            minted_transition: false,
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

    /// The diff's whole rule set, one row per `(stored register, folded truth)` pair. Each row
    /// states what downstream must be told and what may be written before versus after the ack.
    #[tokio::test]
    async fn register_diff_derives_a_change_exactly_when_the_register_lags_the_truth() {
        let cases = [
            (
                None,
                true,
                Some(MembershipStatus::Entered),
                Some(true),
                true,
            ),
            (None, false, None, None, true),
            (
                Some(false),
                true,
                Some(MembershipStatus::Entered),
                Some(true),
                false,
            ),
            (
                Some(true),
                false,
                Some(MembershipStatus::Left),
                Some(false),
                false,
            ),
            (Some(true), true, None, None, false),
            (Some(false), false, None, None, false),
        ];
        for (stored, in_cohort, want_change, want_write, want_placeholder) in cases {
            let why = format!("stored {stored:?}, truth {in_cohort}");
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
                &[folded(lsk, alice, in_cohort)],
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
                diff.recompute
                    .writes
                    .iter()
                    .map(|(_, state)| state.in_cohort)
                    .collect::<Vec<_>>(),
                want_write.into_iter().collect::<Vec<_>>(),
                "{why}",
            );
            assert_eq!(
                diff.placeholders
                    .iter()
                    .map(|(_, state)| state.in_cohort)
                    .collect::<Vec<_>>(),
                if want_placeholder {
                    vec![false]
                } else {
                    vec![]
                },
                "{why}: the placeholder must always be `false` because it means \"never told\"",
            );
        }
    }

    /// An absent row cannot prove downstream was never told, so a transition stage 1 minted this
    /// apply is emitted anyway, and the placeholder records the entry it retires so a failed
    /// produce is still re-derivable.
    #[tokio::test]
    async fn a_minted_transition_is_emitted_over_an_absent_register_row() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7)]);
        let lsk = single_leaf_lsk(&filters, 1);
        let alice = person(1);

        let diff = diff_single_leaf_registers(
            PARTITION,
            &handle(&store),
            &filters,
            &[FoldedLeaf {
                leaf_state_key: lsk,
                person_id: alice,
                in_cohort: false,
                minted_transition: true,
            }],
            EVENT_MS,
            TS,
            ReadLane::Maintenance,
        )
        .await
        .unwrap();

        assert_eq!(diff.recompute.changes.len(), 1);
        assert_eq!(diff.recompute.changes[0].status, MembershipStatus::Left);
        assert!(
            diff.placeholders[0].1.in_cohort,
            "the placeholder holds the entry the `Left` retires",
        );
        assert!(!diff.recompute.writes[0].1.in_cohort, "the post-ack bit");
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
        assert_eq!(diff.placeholders[0].0.cohort_id, 1);
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
        assert!(diff.placeholders.is_empty());
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
        assert!(diff.placeholders.is_empty(), "the row exists");
        assert_eq!(
            diff.recompute.writes,
            vec![(key, state)],
            "the fallback is claimed locally",
        );
    }

    /// An undecodable row cannot say what downstream was told, so it is treated as absent: the
    /// placeholder overwrites it with a readable bit and the entry is re-emitted.
    #[tokio::test]
    async fn a_corrupt_register_row_reads_as_never_told() {
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
            &[folded(lsk, alice, true)],
            EVENT_MS,
            TS,
            ReadLane::Maintenance,
        )
        .await
        .unwrap();

        assert_eq!(diff.recompute.changes.len(), 1);
        assert_eq!(diff.recompute.changes[0].status, MembershipStatus::Entered);
        assert_eq!(diff.placeholders.len(), 1);
        assert!(!diff.placeholders[0].1.in_cohort);
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
        assert_eq!(diff.placeholders.len(), 1, "only cohort 2 had no row");
    }
}
