//! Public-API integration tests for the filter catalog. The exhaustive per-field discrimination
//! matrix and classifier edge cases live in the in-crate `#[cfg(test)]` modules.

use cohort_stream_processor::filters::{
    build_catalog_from_rows, CohortId, CohortLeaf, CohortRow, FilterCatalog, FilterNode, TeamId,
};
use cohort_stream_processor::stage2::{CohortEligibility, ExcludedReason};
use serde_json::{json, Value};

fn build_catalog(rows: Vec<CohortRow>) -> FilterCatalog {
    build_catalog_from_rows(rows, false)
}

const BEHAVIORAL_HASH: [u8; 16] = *b"0123456789abcdef";
const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";

fn row(id: i32, team_id: i32, filters: Value) -> CohortRow {
    CohortRow {
        id,
        team_id,
        filters,
        timezone: "UTC".to_string(),
    }
}

fn behavioral_bytecode() -> Value {
    json!(["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11])
}

/// HogVM `RETURN` opcode, appended to stored bytecode by the catalog loader.
const OP_RETURN: i64 = 38;

/// The stored form of [`behavioral_bytecode`]: the loader appends a trailing `RETURN` (opcode 38).
fn behavioral_bytecode_loaded() -> Vec<Value> {
    let mut bc = behavioral_bytecode().as_array().unwrap().clone();
    bc.push(json!(OP_RETURN));
    bc
}

/// The conditionHash encodes the event matcher, not the `time_value` window — same hash, any window.
fn behavioral_performed_event(time_value: i64) -> Value {
    json!({
        "type": "behavioral",
        "value": "performed_event",
        "key": "$pageview",
        "time_value": time_value,
        "time_interval": "day",
        "conditionHash": "0123456789abcdef",
        "bytecode": behavioral_bytecode(),
    })
}

fn person_leaf() -> Value {
    json!({
        "type": "person",
        "key": "email",
        "value": "a@b.com",
        "operator": "exact",
        "conditionHash": "fedcba9876543210",
        "bytecode": ["_H", 1, 32, "a@b.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
    })
}

fn cohort_ref(id: i32) -> Value {
    json!({ "type": "cohort", "value": id, "negation": false })
}

fn cohort(values: Vec<Value>) -> Value {
    json!({ "properties": { "type": "AND", "values": values } })
}

#[test]
fn same_hash_different_windows_produce_distinct_leaf_state_keys() {
    let catalog = build_catalog(vec![
        row(1, 7, cohort(vec![behavioral_performed_event(7)])),
        row(2, 7, cohort(vec![behavioral_performed_event(30)])),
    ]);

    let team = catalog.team(TeamId(7)).expect("team 7 present");

    assert_eq!(team.by_condition_to_lsk[&BEHAVIORAL_HASH].len(), 2);
    assert_eq!(
        team.by_condition_to_cohorts[&BEHAVIORAL_HASH],
        vec![CohortId(1), CohortId(2)],
    );
    // One conditionHash → one HogVM bytecode evaluation, despite two distinct windows.
    assert_eq!(team.unique_condition_hashes.len(), 1);
}

#[test]
fn behavioral_and_person_indexed_cohort_ref_kept_in_tree_only() {
    let catalog = build_catalog(vec![row(
        1,
        7,
        cohort(vec![
            behavioral_performed_event(7),
            person_leaf(),
            cohort_ref(99),
        ]),
    )]);

    let team = catalog.team(TeamId(7)).expect("team 7 present");

    assert_eq!(team.unique_condition_hashes.len(), 2);
    assert!(team.by_condition_to_lsk.contains_key(&BEHAVIORAL_HASH));
    assert!(team.by_condition_to_lsk.contains_key(&PERSON_HASH));
    assert_eq!(team.by_condition_to_lsk.len(), 2);

    // Cohort ref is kept in the parsed tree (no conditionHash, so not in the index).
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
    // Drop cases: missing conditionHash, unsupported behavioral value, action-keyed (int key).
    let catalog = build_catalog(vec![row(
        1,
        7,
        cohort(vec![
            behavioral_performed_event(7),
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
    assert_eq!(team.unique_condition_hashes.len(), 1);
    assert_eq!(team.by_condition_to_lsk[&BEHAVIORAL_HASH].len(), 1);
}

#[test]
fn bytecode_is_captured_and_deduped_by_condition_hash() {
    let catalog = build_catalog(vec![
        row(
            1,
            7,
            cohort(vec![behavioral_performed_event(7), person_leaf()]),
        ),
        row(2, 7, cohort(vec![behavioral_performed_event(30)])),
    ]);

    let team = catalog.team(TeamId(7)).expect("team 7 present");
    assert_eq!(team.by_condition_to_bytecode.len(), 2);
    assert_eq!(
        team.by_condition_to_bytecode[&BEHAVIORAL_HASH].as_ref(),
        &behavioral_bytecode_loaded(),
    );
    assert!(team.by_condition_to_bytecode.contains_key(&PERSON_HASH));
}

#[test]
fn leaf_without_bytecode_is_dropped() {
    // A conditionHash without inline bytecode is not realtime-executable.
    let no_bytecode = json!({
        "type": "behavioral",
        "value": "performed_event_multiple",
        "key": "$pageview",
        "time_value": 7,
        "time_interval": "day",
        "operator": "gte",
        "operator_value": 3,
        "conditionHash": "0123456789abcdef",
    });
    let catalog = build_catalog(vec![row(1, 7, cohort(vec![no_bytecode]))]);

    let team = catalog.team(TeamId(7)).expect("team 7 present");
    assert!(team.unique_condition_hashes.is_empty());
    assert!(team.by_condition_to_bytecode.is_empty());
    assert!(team.by_condition_to_lsk.is_empty());
}

#[test]
fn teams_are_isolated() {
    let catalog = build_catalog(vec![
        row(1, 7, cohort(vec![behavioral_performed_event(7)])),
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
        "bytecode": ["_H", 1, 32, "x", 32, "name", 32, "properties", 32, "person", 1, 3, 11],
    });
    let catalog = build_catalog(vec![row(
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

#[test]
fn cycle_of_realtime_cohorts_is_excluded_cycle_detected() {
    let catalog = build_catalog(vec![
        row(1, 7, cohort(vec![cohort_ref(2)])),
        row(2, 7, cohort(vec![cohort_ref(3)])),
        row(3, 7, cohort(vec![cohort_ref(1)])),
        row(
            4,
            7,
            cohort(vec![behavioral_performed_event(7), person_leaf()]),
        ),
    ]);
    let team = catalog.team(TeamId(7)).expect("team 7 present");

    for id in [1, 2, 3] {
        assert_eq!(
            team.eligibility[&CohortId(id)],
            CohortEligibility::Excluded(ExcludedReason::CycleDetected),
            "cohort {id} is a cycle member",
        );
    }
    assert_eq!(
        team.eligibility[&CohortId(4)],
        CohortEligibility::Stage2Composable,
        "the composable sibling is untouched by the cycle",
    );
}

#[test]
fn self_referencing_cohort_is_cycle_detected() {
    let catalog = build_catalog(vec![row(1, 7, cohort(vec![cohort_ref(1)]))]);
    let team = catalog.team(TeamId(7)).expect("team 7 present");
    assert_eq!(
        team.eligibility[&CohortId(1)],
        CohortEligibility::Excluded(ExcludedReason::CycleDetected),
    );
}

#[test]
fn ref_to_unloaded_cohort_is_unresolved_ref() {
    let catalog = build_catalog(vec![row(1, 7, cohort(vec![cohort_ref(99)]))]);
    let team = catalog.team(TeamId(7)).expect("team 7 present");
    assert_eq!(
        team.eligibility[&CohortId(1)],
        CohortEligibility::Excluded(ExcludedReason::UnresolvedRef),
    );
}

#[test]
fn ref_to_another_teams_cohort_is_unresolved_ref() {
    // Reference graph is team-scoped: cohort 2 exists only in team 8, so from team 7's view it is missing.
    let catalog = build_catalog(vec![
        row(1, 7, cohort(vec![cohort_ref(2)])),
        row(2, 8, cohort(vec![person_leaf()])),
    ]);
    assert_eq!(
        catalog.team(TeamId(7)).expect("team 7").eligibility[&CohortId(1)],
        CohortEligibility::Excluded(ExcludedReason::UnresolvedRef),
    );
    assert!(matches!(
        catalog.team(TeamId(8)).expect("team 8").eligibility[&CohortId(2)],
        CohortEligibility::SingleLeaf(_),
    ));
}

#[test]
fn resolvable_ref_stays_has_cohort_ref_and_contributes_no_emit_mapping() {
    // Cohort 1 → cohort 2 (resolvable): stays `HasCohortRef` (transport-sizing class), appears in
    // neither emit map — it drives no single-leaf or composable membership.
    let catalog = build_catalog(vec![
        row(1, 7, cohort(vec![cohort_ref(2)])),
        row(2, 7, cohort(vec![behavioral_performed_event(7)])),
    ]);
    let team = catalog.team(TeamId(7)).expect("team 7 present");

    assert_eq!(
        team.eligibility[&CohortId(1)],
        CohortEligibility::Excluded(ExcludedReason::HasCohortRef),
    );
    assert!(matches!(
        team.eligibility[&CohortId(2)],
        CohortEligibility::SingleLeaf(_),
    ));

    let in_single = team
        .by_lsk_to_single_leaf_cohorts
        .values()
        .any(|owners| owners.contains(&CohortId(1)));
    let in_composable = team
        .by_lsk_to_composable_cohorts
        .values()
        .any(|owners| owners.contains(&CohortId(1)));
    assert!(
        !in_single,
        "a ref-bearing cohort drives no single-leaf membership",
    );
    assert!(
        !in_composable,
        "a ref-bearing cohort is not composable, so it owns no composable mapping",
    );
}
