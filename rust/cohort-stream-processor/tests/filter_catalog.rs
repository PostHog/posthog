//! Public-API integration tests for the filter catalog (PR 1.3).
//!
//! These drive `build_catalog_from_rows` through the crate's re-exported surface, exactly as
//! the Stage 1 worker (PR 1.6) will consume it. The exhaustive per-field discrimination matrix
//! and classifier edge cases live in the in-crate `#[cfg(test)]` modules; this file pins the
//! headline acceptance behavior and the public API shape.

use cohort_stream_processor::filters::{
    build_catalog_from_rows, CohortId, CohortLeaf, CohortRow, FilterNode, TeamId,
};
use serde_json::{json, Value};

/// The shared `conditionHash` for the behavioral leaves (16 ASCII chars).
const BEHAVIORAL_HASH: [u8; 16] = *b"0123456789abcdef";
/// A distinct `conditionHash` for the person leaf.
const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";

fn row(id: i32, team_id: i32, filters: Value) -> CohortRow {
    CohortRow {
        id,
        team_id,
        filters,
    }
}

/// A `performed_event_multiple` leaf on `$pageview` with a fixed conditionHash and a tunable
/// window/threshold (the fields that the conditionHash does *not* encode).
fn behavioral_multiple(time_value: i64, operator_value: i64) -> Value {
    json!({
        "type": "behavioral",
        "value": "performed_event_multiple",
        "key": "$pageview",
        "time_value": time_value,
        "time_interval": "day",
        "operator": "gte",
        "operator_value": operator_value,
        "conditionHash": "0123456789abcdef",
    })
}

fn person_leaf() -> Value {
    json!({
        "type": "person",
        "key": "email",
        "value": "a@b.com",
        "operator": "exact",
        "conditionHash": "fedcba9876543210",
    })
}

fn cohort_ref(id: i32) -> Value {
    json!({ "type": "cohort", "value": id, "negation": false })
}

fn cohort(values: Vec<Value>) -> Value {
    json!({ "properties": { "type": "AND", "values": values } })
}

/// The explicit PR-1.3 acceptance test: two cohorts on the same team, both
/// `performed_event_multiple` on `$pageview` with the **same** conditionHash but different
/// windows/thresholds, must produce two distinct leaf state keys under one conditionHash.
#[test]
fn same_hash_different_windows_produce_distinct_leaf_state_keys() {
    let catalog = build_catalog_from_rows(vec![
        row(1, 7, cohort(vec![behavioral_multiple(7, 3)])),
        row(2, 7, cohort(vec![behavioral_multiple(30, 5)])),
    ]);

    let team = catalog.team(TeamId(7)).expect("team 7 present");

    // Two distinct LSKs under the single shared conditionHash (if equal, dedup would give 1).
    assert_eq!(team.by_condition_to_lsk[&BEHAVIORAL_HASH].len(), 2);
    // Both owning cohorts recorded against that conditionHash, sorted.
    assert_eq!(
        team.by_condition_to_cohorts[&BEHAVIORAL_HASH],
        vec![CohortId(1), CohortId(2)],
    );
    // Still a single conditionHash — the HogVM dedup unit is unchanged.
    assert_eq!(team.unique_condition_hashes.len(), 1);
}

#[test]
fn behavioral_and_person_indexed_cohort_ref_kept_in_tree_only() {
    let catalog = build_catalog_from_rows(vec![row(
        1,
        7,
        cohort(vec![
            behavioral_multiple(7, 3),
            person_leaf(),
            cohort_ref(99),
        ]),
    )]);

    let team = catalog.team(TeamId(7)).expect("team 7 present");

    // Behavioral + person are indexed; the cohort ref contributes no conditionHash.
    assert_eq!(team.unique_condition_hashes.len(), 2);
    assert!(team.by_condition_to_lsk.contains_key(&BEHAVIORAL_HASH));
    assert!(team.by_condition_to_lsk.contains_key(&PERSON_HASH));
    assert_eq!(team.by_condition_to_lsk.len(), 2);

    // All three leaves survive in the parsed tree (the cohort ref is kept for Stage 2).
    let tree = &team.cohorts[&CohortId(1)];
    let FilterNode::Group { children, .. } = &tree.root else {
        panic!("root should be a group");
    };
    assert_eq!(children.len(), 3, "cohort ref must remain a tree node");
    let cohort_refs = children
        .iter()
        .filter(|child| matches!(child, FilterNode::Leaf(CohortLeaf::CohortRef(_))))
        .count();
    assert_eq!(cohort_refs, 1);
}

#[test]
fn dropped_leaves_are_skipped_while_survivors_stay_indexed() {
    // A cohort mixing one valid behavioral leaf with three drop cases: missing conditionHash,
    // an unsupported behavioral value, and an action-keyed (integer key) behavioral leaf.
    let catalog = build_catalog_from_rows(vec![row(
        1,
        7,
        cohort(vec![
            behavioral_multiple(7, 3),
            json!({ "type": "behavioral", "value": "performed_event", "key": "$click" }),
            json!({
                "type": "behavioral",
                "value": "performed_event_sequence",
                "key": "$pageview",
                "conditionHash": "0123456789abcdef",
            }),
            json!({
                "type": "behavioral",
                "value": "performed_event",
                "key": 4242,
                "conditionHash": "0123456789abcdef",
            }),
        ]),
    )]);

    let team = catalog.team(TeamId(7)).expect("team 7 present");
    // Only the one valid leaf survives.
    assert_eq!(team.unique_condition_hashes.len(), 1);
    assert_eq!(team.by_condition_to_lsk[&BEHAVIORAL_HASH].len(), 1);
}

#[test]
fn teams_are_isolated() {
    let catalog = build_catalog_from_rows(vec![
        row(1, 7, cohort(vec![behavioral_multiple(7, 3)])),
        row(2, 8, cohort(vec![person_leaf()])),
    ]);

    let team7 = catalog.team(TeamId(7)).expect("team 7 present");
    assert!(team7.by_condition_to_lsk.contains_key(&BEHAVIORAL_HASH));
    assert!(!team7.by_condition_to_lsk.contains_key(&PERSON_HASH));

    let team8 = catalog.team(TeamId(8)).expect("team 8 present");
    assert!(team8.by_condition_to_lsk.contains_key(&PERSON_HASH));
    assert!(!team8.by_condition_to_lsk.contains_key(&BEHAVIORAL_HASH));

    assert_eq!(catalog.team_count(), 2);
}

#[test]
fn or_group_of_two_person_leaves_is_not_sibling_merged() {
    let other_person = json!({
        "type": "person",
        "key": "name",
        "value": "x",
        "operator": "exact",
        "conditionHash": "fedcba9876543210",
    });
    let catalog = build_catalog_from_rows(vec![row(
        1,
        7,
        json!({ "properties": { "type": "OR", "values": [person_leaf(), other_person] } }),
    )]);

    let tree = &catalog.team(TeamId(7)).unwrap().cohorts[&CohortId(1)];
    let FilterNode::Group { children, .. } = &tree.root else {
        panic!("root should be a group");
    };
    assert_eq!(
        children.len(),
        2,
        "single-property siblings must not be merged"
    );
}
