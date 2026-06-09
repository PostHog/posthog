//! Event-driven Stage 2 composition: the store I/O around the pure [`evaluator`](crate::stage2::evaluator).
//!
//! When Stage 1 flips a leaf, [`compose_stage2`] re-evaluates each `Stage2Composable` cohort owning
//! it — reads the cohort's leaves' Stage 1 state, folds them through [`evaluate_tree`], diffs against
//! the stored `cf_stage2` bit, and emits a per-cohort [`CohortMembershipChange`] on a flip.
//!
//! ## Correctness
//!
//! - **Read-your-writes within a sub-batch.** Each call commits its own `cf_stage2` batch before
//!   returning, so a later event in the same sub-batch sees this event's bits. `process_event` commits
//!   the Stage 1 writes this reads before it returns the transitions, so `multi_get_stage1` sees them.
//! - **At-most-once, self-healing.** Stage 1 and Stage 2 commit in two independent batches, both
//!   before the worker produces. A crash between them drops a flip; `evaluate_tree` recomputes the
//!   whole cohort each event, so a stored-bit mismatch emits a correcting flip on the person's next
//!   event.

use std::collections::{BTreeSet, HashMap};

use metrics::counter;
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::tree::{CohortTree, FilterNode};
use crate::filters::CohortId;
use crate::observability::metrics::{
    STAGE2_COHORTS_EVALUATED, STAGE2_STATE_DECODE_ERROR, STAGE2_TRANSITIONS,
};
use crate::producer::{CohortMembershipChange, MembershipStatus};
use crate::stage1::key::{LeafStateKey, Stage1Key};
use crate::stage1::state::{Stage1State, StatefulRecord};
use crate::stage1::transition::LeafTransition;
use crate::stage2::evaluator::{evaluate_tree, leaf_membership};
use crate::stage2::state::Stage2State;
use crate::store::{CohortStore, Stage2Key, StoreError};

/// Re-evaluate every `Stage2Composable` cohort owning a leaf that flipped in `transitions`, emitting
/// the per-cohort membership changes that flipped and committing their new `cf_stage2` bits.
///
/// `event_ms` stamps `last_evaluated_at_ms` on the bits it writes; `last_updated` is the shared
/// sub-batch timestamp threaded onto each [`CohortMembershipChange`]. A [`StoreError`] (a RocksDB
/// read/commit failure) aborts the whole call with nothing committed — the worker logs and skips, and
/// the affected bits self-heal on the persons' next events.
pub fn compose_stage2(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    transitions: &[LeafTransition],
    event_ms: i64,
    last_updated: &str,
) -> Result<Vec<CohortMembershipChange>, StoreError> {
    // One event can flip several leaves of one cohort, but the cohort composes once per person; the
    // `BTreeSet` dedups and gives a deterministic `(cohort, person)` output order.
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
        // The composable index and `cohorts` are one freeze, so the tree is always present; skip a
        // `None` defensively rather than panic.
        let Some(tree) = filters.cohorts.get(&cohort_id) else {
            continue;
        };
        let team_id = tree.team_id.0 as u64;

        let new_bit = evaluate_cohort(partition_id, team_id, person_id, tree, filters, store)?;
        evaluated += 1;

        let stage2_key = Stage2Key {
            partition_id,
            team_id,
            cohort_id: cohort_id.0 as u64,
            person_id,
        };
        let prior_bit = read_stage2_bit(store, &stage2_key)?;
        if new_bit == prior_bit {
            continue;
        }

        let status = if new_bit {
            MembershipStatus::Entered
        } else {
            MembershipStatus::Left
        };
        changes.push(CohortMembershipChange {
            team_id: tree.team_id.0,
            cohort_id: cohort_id.0,
            person_id: person_id.to_string(),
            last_updated: last_updated.to_string(),
            status,
        });
        // On a `Left`, write `in_cohort = false` rather than deleting: an absent `cf_stage2` entry
        // means "never evaluated", so the explicit false bit keeps absence unambiguous.
        pending.push((
            stage2_key,
            Stage2State {
                in_cohort: new_bit,
                last_evaluated_at_ms: event_ms,
            },
        ));
    }

    // One batch per call so a later event in the same sub-batch reads its own writes.
    if !pending.is_empty() {
        store.write_batch(|batch| {
            for (key, state) in &pending {
                batch.put_stage2(key, &state.encode());
            }
        })?;
    }

    // Count post-commit: a failed write returns above, so a dropped batch never inflates the counters.
    counter!(STAGE2_COHORTS_EVALUATED).increment(evaluated);
    for change in &changes {
        counter!(STAGE2_TRANSITIONS, "kind" => change.status.as_str()).increment(1);
    }

    Ok(changes)
}

/// Compose one cohort for one person: batch-read its leaves' Stage 1 state, fold each to a member bit
/// via [`leaf_membership`], and evaluate the tree. A leaf with absent or undecodable state reads as a
/// non-member.
fn evaluate_cohort(
    partition_id: u16,
    team_id: u64,
    person_id: Uuid,
    tree: &CohortTree,
    filters: &TeamFilters,
    store: &CohortStore,
) -> Result<bool, StoreError> {
    let mut lsks = Vec::new();
    collect_leaf_state_keys(&tree.root, &mut lsks);

    let keys: Vec<Stage1Key> = lsks
        .iter()
        .map(|&lsk| Stage1Key {
            partition_id,
            team_id,
            leaf_state_key: lsk,
            person_id,
        })
        .collect();
    let raw = store.multi_get_stage1(&keys)?;

    let mut membership: HashMap<LeafStateKey, bool> = HashMap::with_capacity(lsks.len());
    for (lsk, bytes) in lsks.iter().zip(raw) {
        // A leaf missing from `by_lsk` is a catalog desync (the tree and `by_lsk` are one freeze);
        // leave it out of the map so `evaluate_tree` reads it as false.
        let Some(meta) = filters.by_lsk.get(lsk) else {
            continue;
        };
        let state = decode_stage1_state(bytes);
        membership.insert(*lsk, leaf_membership(state.as_ref(), meta));
    }

    Ok(evaluate_tree(&tree.root, &membership))
}

/// Decode a `cf_stage1` value to its [`Stage1State`], or [`None`] for an absent or undecodable row. A
/// decode failure (a corrupt prior leaf record) counts [`STAGE2_STATE_DECODE_ERROR`] and reads as a
/// non-member.
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

/// The stored `cf_stage2` membership bit for `key` — `false` when absent (never evaluated) or
/// undecodable (counts [`STAGE2_STATE_DECODE_ERROR`]; a corrupt bit recomputes to a correcting flip).
fn read_stage2_bit(store: &CohortStore, key: &Stage2Key) -> Result<bool, StoreError> {
    let Some(bytes) = store.get_stage2(key)? else {
        return Ok(false);
    };
    match Stage2State::decode(&bytes) {
        Ok(state) => Ok(state.in_cohort),
        Err(_) => {
            counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
            Ok(false)
        }
    }
}

/// Collect every state-keyed leaf's [`LeafStateKey`] in pre-order (cohort-ref leaves have none).
/// Duplicates are kept — the `membership` map collapses them — so the walk stays trivial.
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

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::{json, Value};
    use tempfile::TempDir;
    use uuid::Uuid;

    use crate::filters::{CohortId, TeamFiltersBuilder, TeamId};
    use crate::stage1::state::AppliedOffsets;
    use crate::stage1::transition::TransitionKind;
    use crate::store::StoreConfig;

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

    fn behavioral_leaf(window_days: i64) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event", "key": "$pageview",
            "time_value": window_days, "time_interval": "day",
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    /// A `performed_event_multiple` (daily-bucket) leaf — routes leaf membership through the count
    /// comparator rather than the op-less single bit.
    fn daily_leaf(window_days: i64, op: &str, value: i64) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event_multiple", "key": "$pageview",
            "time_value": window_days, "time_interval": "day",
            "operator": op, "operator_value": value,
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    /// A daily-bucket state (7-day window → 8 buckets) holding `count` matches on its "now" day.
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

    /// Freeze a single team cohort `AND(values)` under cohort id 1.
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

    fn person_state(matches: bool) -> Stage1State {
        Stage1State::PersonProperty {
            matches,
            last_updated_at_ms: EVENT_MS,
            last_updated_offset: 0,
        }
    }

    fn write_stage1(store: &CohortStore, lsk: LeafStateKey, who: Uuid, state: Stage1State) {
        let key = Stage1Key {
            partition_id: PARTITION,
            team_id: TEAM,
            leaf_state_key: lsk,
            person_id: who,
        };
        let record = StatefulRecord {
            state,
            applied_offsets: AppliedOffsets::default(),
        };
        store
            .write_batch(|b| b.put_stage1(&key, &record.encode()))
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

    /// The behavioral + person LSKs of an `AND(behavioral_leaf, person_leaf)` cohort.
    fn and_leaf_keys(filters: &TeamFilters) -> (LeafStateKey, LeafStateKey) {
        (
            filters.by_condition_to_lsk[&HASH][0],
            LeafStateKey::for_person_property(&PERSON_HASH),
        )
    }

    #[test]
    fn entered_when_the_and_is_satisfied() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), person_leaf()]);
        let (beh_lsk, per_lsk) = and_leaf_keys(&filters);
        let alice = person(1);

        // Both leaves already true in cf_stage1; the behavioral flip triggers the recompose.
        write_stage1(&store, beh_lsk, alice, behavioral_match());
        write_stage1(&store, per_lsk, alice, person_state(true));

        let changes = compose_stage2(
            PARTITION,
            &store,
            &filters,
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
        )
        .unwrap();

        assert_eq!(changes.len(), 1);
        assert_eq!(changes[0].cohort_id, 1);
        assert_eq!(changes[0].team_id, TEAM as i32);
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(changes[0].person_id, alice.to_string());
        assert_eq!(changes[0].last_updated, TS);
        assert_eq!(stage2_bit(&store, 1, alice), Some(true), "bit committed");
    }

    #[test]
    fn no_emit_until_the_second_leaf_flips() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), person_leaf()]);
        let (beh_lsk, per_lsk) = and_leaf_keys(&filters);
        let alice = person(1);

        // Phase A: only the behavioral leaf is true; the person leaf is still absent.
        write_stage1(&store, beh_lsk, alice, behavioral_match());
        let phase_a = compose_stage2(
            PARTITION,
            &store,
            &filters,
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
        )
        .unwrap();
        assert!(phase_a.is_empty(), "one leaf does not satisfy the AND");
        assert_eq!(
            stage2_bit(&store, 1, alice),
            None,
            "no bit written on a non-flip"
        );

        // Phase B: the person leaf flips true → the AND is satisfied.
        write_stage1(&store, per_lsk, alice, person_state(true));
        let phase_b = compose_stage2(
            PARTITION,
            &store,
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
        .unwrap();
        assert_eq!(phase_b.len(), 1);
        assert_eq!(phase_b[0].status, MembershipStatus::Entered);
        assert_eq!(stage2_bit(&store, 1, alice), Some(true));
    }

    #[test]
    fn left_when_a_leaf_drops() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), person_leaf()]);
        let (beh_lsk, per_lsk) = and_leaf_keys(&filters);
        let alice = person(1);

        // Establish membership: both leaves true → Entered.
        write_stage1(&store, beh_lsk, alice, behavioral_match());
        write_stage1(&store, per_lsk, alice, person_state(true));
        let entered = compose_stage2(
            PARTITION,
            &store,
            &filters,
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
        )
        .unwrap();
        assert_eq!(entered.len(), 1);
        assert_eq!(entered[0].status, MembershipStatus::Entered);

        // The person leaf flips false → the AND fails → Left.
        write_stage1(&store, per_lsk, alice, person_state(false));
        let left = compose_stage2(
            PARTITION,
            &store,
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
        .unwrap();
        assert_eq!(left.len(), 1);
        assert_eq!(left[0].status, MembershipStatus::Left);
        assert_eq!(
            stage2_bit(&store, 1, alice),
            Some(false),
            "a Left writes the false bit, it does not delete the row",
        );
    }

    #[test]
    fn idempotent_re_evaluation_emits_once() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), person_leaf()]);
        let (beh_lsk, per_lsk) = and_leaf_keys(&filters);
        let alice = person(1);
        write_stage1(&store, beh_lsk, alice, behavioral_match());
        write_stage1(&store, per_lsk, alice, person_state(true));

        let first = compose_stage2(
            PARTITION,
            &store,
            &filters,
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
        )
        .unwrap();
        assert_eq!(first.len(), 1, "the first evaluation enters");

        // Same inputs, unchanged state: the stored bit already agrees, so nothing is emitted.
        let second = compose_stage2(
            PARTITION,
            &store,
            &filters,
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
        )
        .unwrap();
        assert!(
            second.is_empty(),
            "a re-evaluation with no change emits nothing"
        );
    }

    #[test]
    fn dedups_when_one_event_flips_two_leaves_of_one_cohort() {
        // AND of a 7d and a 30d performed_event on the same matcher: one $pageview flips both windows,
        // so two transitions arrive for one cohort+person — the cohort must compose once, emit once.
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7), behavioral_leaf(30)]);
        let lsks = &filters.by_condition_to_lsk[&HASH];
        assert_eq!(lsks.len(), 2, "two windows fan out to two LSKs");
        let alice = person(1);
        write_stage1(&store, lsks[0], alice, behavioral_match());
        write_stage1(&store, lsks[1], alice, behavioral_match());

        let changes = compose_stage2(
            PARTITION,
            &store,
            &filters,
            &[
                transition(lsks[0], alice, HASH, TransitionKind::Entered),
                transition(lsks[1], alice, HASH, TransitionKind::Entered),
            ],
            EVENT_MS,
            TS,
        )
        .unwrap();

        assert_eq!(
            changes.len(),
            1,
            "two leaf flips of one cohort dedup to a single Entered",
        );
        assert_eq!(changes[0].status, MembershipStatus::Entered);
    }

    #[test]
    fn composes_a_performed_event_multiple_leaf_via_variant_dispatch() {
        // A `performed_event_multiple` leaf must route through its count comparator: count 2 satisfies
        // `gte 2`, so the AND with a true person leaf composes one Entered.
        let (_dir, store) = temp_store();
        let filters = freeze(vec![daily_leaf(7, "gte", 2), person_leaf()]);
        let beh_lsk = filters.by_condition_to_lsk[&HASH][0];
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let alice = person(1);
        write_stage1(&store, beh_lsk, alice, daily_state(2));
        write_stage1(&store, per_lsk, alice, person_state(true));

        let changes = compose_stage2(
            PARTITION,
            &store,
            &filters,
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
        )
        .unwrap();
        assert_eq!(
            changes.len(),
            1,
            "count 2 ≥ gte 2 → the multiple leaf is a member"
        );
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(changes[0].cohort_id, 1);

        // And a count below the threshold is not a member, so the AND stays unsatisfied.
        let (_dir2, store2) = temp_store();
        write_stage1(&store2, beh_lsk, alice, daily_state(1)); // 1 < gte 2
        write_stage1(&store2, per_lsk, alice, person_state(true));
        let below = compose_stage2(
            PARTITION,
            &store2,
            &filters,
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
        )
        .unwrap();
        assert!(
            below.is_empty(),
            "count 1 fails gte 2, so the multiple leaf is not a member and the AND is unsatisfied",
        );
    }

    #[test]
    fn transitions_touching_no_composable_cohort_emit_nothing() {
        // A single-leaf cohort's leaf is not in the composable index, so a flip on it composes nothing.
        let (_dir, store) = temp_store();
        let filters = freeze(vec![behavioral_leaf(7)]); // single-leaf cohort
        let beh_lsk = filters.by_condition_to_lsk[&HASH][0];
        let alice = person(1);
        write_stage1(&store, beh_lsk, alice, behavioral_match());

        let changes = compose_stage2(
            PARTITION,
            &store,
            &filters,
            &[transition(beh_lsk, alice, HASH, TransitionKind::Entered)],
            EVENT_MS,
            TS,
        )
        .unwrap();
        assert!(
            changes.is_empty(),
            "a single-leaf cohort is handled by map_transition, not Stage 2",
        );
    }
}
