//! Stage 2 composition: re-evaluates multi-leaf cohorts when Stage 1 flips a leaf.
//!
//! [`compose_stage2`] reads each affected cohort's leaf states, evaluates the tree, diffs against the
//! stored `cf_stage2` bit, and emits membership changes on a flip. At-most-once: a crash between
//! the Stage 1 and Stage 2 commits drops a flip, but `evaluate_tree` recomputes the whole cohort
//! each event, so a mismatch self-heals on the person's next event.

use std::collections::{BTreeSet, HashMap};

use metrics::counter;
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::tree::{CohortLeaf, CohortTree, FilterNode};
use crate::filters::CohortId;
use crate::observability::metrics::{
    STAGE2_COHORTS_EVALUATED, STAGE2_STATE_DECODE_ERROR, STAGE2_TRANSITIONS,
};
use crate::producer::{CohortMembershipChange, MembershipStatus};
use crate::stage1::key::LeafStateKey;
use crate::stage1::person_record::PersonRecord;
use crate::stage1::state::{Stage1State, StateVariant, StatefulRecord};
use crate::stage1::transition::LeafTransition;
use crate::stage2::evaluator::{evaluate_tree, leaf_membership};
use crate::stage2::state::Stage2State;
use crate::stage2::CohortEligibility;
use crate::store::{
    BehavioralKey, PersonRecordKey, ReadLane, Stage2Key, StagedBatch, StoreError, StoreHandle,
};

pub async fn compose_stage2(
    partition_id: u16,
    handle: &StoreHandle,
    filters: &TeamFilters,
    transitions: &[LeafTransition],
    event_ms: i64,
    last_updated: &str,
) -> Result<Vec<CohortMembershipChange>, StoreError> {
    let mut affected: BTreeSet<(CohortId, Uuid)> = BTreeSet::new();
    for transition in transitions {
        if let Some(cohorts) = filters
            .by_lsk_to_composable_cohorts
            .get(&transition.leaf_state_key)
        {
            for &cohort_id in cohorts {
                affected.insert((cohort_id, transition.person_id));
            }
        }
    }
    if affected.is_empty() {
        return Ok(Vec::new());
    }

    let mut changes = Vec::new();
    let mut pending: Vec<(Stage2Key, Stage2State)> = Vec::new();
    let mut evaluated: u64 = 0;

    for (cohort_id, person_id) in affected {
        let Some(tree) = filters.cohorts.get(&cohort_id) else {
            continue;
        };

        let diff = recompute_and_diff(partition_id, person_id, tree, filters, handle).await?;
        evaluated += 1;
        if !diff.flipped() {
            continue;
        }

        changes.push(CohortMembershipChange {
            team_id: tree.team_id.0,
            cohort_id: cohort_id.0,
            person_id: person_id.to_string(),
            last_updated: last_updated.to_string(),
            status: diff.status(),
        });
        // Write `false` rather than deleting so absence means "never evaluated".
        pending.push((
            diff.stage2_key,
            Stage2State {
                in_cohort: diff.new_bit,
                last_evaluated_at_ms: event_ms,
            },
        ));
    }

    if !pending.is_empty() {
        let mut staged = StagedBatch::default();
        for (key, state) in &pending {
            staged.put_stage2(key, &state.encode());
        }
        handle.commit(staged).await?;
    }

    counter!(STAGE2_COHORTS_EVALUATED).increment(evaluated);
    for change in &changes {
        counter!(STAGE2_TRANSITIONS, "kind" => change.status.as_str()).increment(1);
    }

    Ok(changes)
}

/// One cohort's recomputed membership for one person, diffed against the stored `cf_stage2` bit.
/// Shared by Stage 2 composition and the cascade handler so the two recompute paths cannot diverge.
pub(crate) struct RecomputeDiff {
    pub new_bit: bool,
    pub prior_bit: bool,
    pub stage2_key: Stage2Key,
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
}

/// Recompute one cohort's membership and diff against the stored `cf_stage2` bit. Reads only — the
/// caller stages the write, so it owns the produce/commit ordering.
pub(crate) async fn recompute_and_diff(
    partition_id: u16,
    person_id: Uuid,
    tree: &CohortTree,
    filters: &TeamFilters,
    handle: &StoreHandle,
) -> Result<RecomputeDiff, StoreError> {
    let team_id = tree.team_id.0 as u64;
    let new_bit = evaluate_cohort(partition_id, team_id, person_id, tree, filters, handle).await?;
    let stage2_key = Stage2Key {
        partition_id,
        team_id,
        cohort_id: tree.cohort_id.0 as u64,
        person_id,
    };
    let prior_bit = read_stage2_bit(handle, &stage2_key).await?;
    Ok(RecomputeDiff {
        new_bit,
        prior_bit,
        stage2_key,
    })
}

/// Compose one cohort for one person. A leaf with absent or undecodable state reads as non-member;
/// a cohort-reference leaf reads the referenced cohort's stored membership (see [`resolve_ref_membership`]).
async fn evaluate_cohort(
    partition_id: u16,
    team_id: u64,
    person_id: Uuid,
    tree: &CohortTree,
    filters: &TeamFilters,
    handle: &StoreHandle,
) -> Result<bool, StoreError> {
    let mut lsks = Vec::new();
    collect_leaf_state_keys(&tree.root, &mut lsks);

    let resolver = LeafMembershipResolver::new(partition_id, team_id, person_id, filters, handle);
    let membership = resolver.resolve(&lsks).await?;

    let ref_membership =
        resolve_ref_membership(partition_id, team_id, person_id, tree, filters, handle).await?;

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
}

impl<'a> LeafMembershipResolver<'a> {
    fn new(
        partition_id: u16,
        team_id: u64,
        person_id: Uuid,
        filters: &'a TeamFilters,
        handle: &'a StoreHandle,
    ) -> Self {
        Self {
            partition_id,
            team_id,
            person_id,
            filters,
            handle,
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
                Some(_) => behavioral_lsks.push(lsk),
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
        let raw = self
            .handle
            .multi_get_behavioral(keys, ReadLane::Event)
            .await?;
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
        let matched = match self.handle.get_person_record(&key).await? {
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
async fn resolve_ref_membership(
    partition_id: u16,
    team_id: u64,
    person_id: Uuid,
    tree: &CohortTree,
    filters: &TeamFilters,
    handle: &StoreHandle,
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
            LeafMembershipResolver::new(partition_id, team_id, person_id, filters, handle);
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
        let raw = handle.multi_get_stage2(keys).await?;
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

/// The stored `cf_stage2` membership bit for `key`, `false` when absent or undecodable.
async fn read_stage2_bit(handle: &StoreHandle, key: &Stage2Key) -> Result<bool, StoreError> {
    Ok(decode_stage2_bit(handle.get_stage2(key).await?))
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
    use crate::stage1::transition::TransitionKind;
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

    fn transition(
        lsk: LeafStateKey,
        who: Uuid,
        hash: [u8; 16],
        kind: TransitionKind,
    ) -> LeafTransition {
        LeafTransition {
            team_id: TeamId(TEAM as i32),
            leaf_state_key: lsk,
            person_id: who,
            condition_hash: hash,
            kind,
        }
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
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
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
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
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
            &[transition(
                per_lsk,
                alice,
                PERSON_HASH,
                TransitionKind::Entered,
            )],
            EVENT_MS,
            TS,
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
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
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
            &[transition(
                per_lsk,
                alice,
                PERSON_HASH,
                TransitionKind::Left,
            )],
            EVENT_MS,
            TS,
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
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
        )
        .await
        .unwrap();
        assert_eq!(first.len(), 1, "the first evaluation enters");

        let second = compose_stage2(
            PARTITION,
            &handle(&store),
            &filters,
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
        )
        .await
        .unwrap();
        assert!(
            second.is_empty(),
            "a re-evaluation with no change emits nothing"
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
            &[
                transition(lsks[0], alice, HASH, TransitionKind::Entered),
                transition(lsks[1], alice, HASH, TransitionKind::Entered),
            ],
            EVENT_MS,
            TS,
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
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
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
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
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
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
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
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
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
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
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
            &[transition(
                per_lsk,
                alice,
                PERSON_HASH,
                TransitionKind::Entered,
            )],
            EVENT_MS,
            TS,
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
            &[transition(
                per_lsk,
                who,
                PERSON_HASH,
                TransitionKind::Entered,
            )],
            EVENT_MS,
            TS,
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
}
