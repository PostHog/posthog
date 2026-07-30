//! The freshness decision table driven through the real event fold against a live RocksDB store.
//!
//! `stage1/person_record.rs` unit-tests the pure `decide` / `apply_*` core; these tests exercise the
//! wiring in `event_path::fold_person` — that each decision-table row stages (or does not stage) the
//! right record, advances the stamp where it is load-bearing, and emits the right transitions — plus
//! the two cross-cutting equivalences the PersonRecord collapse must uphold:
//!
//! - the record-level argMax must agree with the old per-leaf last-write-wins rule, and
//! - the fingerprint-match fast path (`SkipEval`) must be indistinguishable from a full re-evaluation.

// Tests seed and assert through `CohortStore` directly — the sanctioned direct-store test surface.
#![allow(clippy::disallowed_methods)]

use chrono_tz::UTC;
use cohort_stream_processor::consumers::CohortStreamEvent;
use cohort_stream_processor::filters::{CohortId, TeamFilters, TeamFiltersBuilder, TeamId};
use cohort_stream_processor::stage1::person_record::{
    CatalogFingerprint, PersonRecord, PropsFingerprint,
};
use cohort_stream_processor::stage1::time::clickhouse_timestamp_to_millis;
use cohort_stream_processor::stage1::{AppliedOffsets, LeafTransition, TransitionKind};
use cohort_stream_processor::store::{CohortStore, PersonRecordKey, PersonRecords, StoreConfig};
use cohort_stream_processor::workers::{process_event, EventOutcome};
use serde_json::{json, Value};
use tempfile::TempDir;
use uuid::Uuid;

const TEAM: i32 = 7;
const PARTITION: u16 = 0;

// Two distinct person-condition hashes. `email` sorts before `plan`.
const EMAIL_HASH: [u8; 16] = *b"emailhash0000001";
const PLAN_HASH: [u8; 16] = *b"planhash00000002";

/// `email == "a@p.com"`.
fn email_leaf() -> Value {
    json!({
        "type": "person", "key": "email", "value": "a@p.com", "operator": "exact",
        "conditionHash": "emailhash0000001",
        "bytecode": ["_H", 1, 32, "a@p.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
    })
}

/// `plan == "pro"`.
fn plan_leaf() -> Value {
    json!({
        "type": "person", "key": "plan", "value": "pro", "operator": "exact",
        "conditionHash": "planhash00000002",
        "bytecode": ["_H", 1, 32, "pro", 32, "plan", 32, "properties", 32, "person", 1, 3, 11],
    })
}

fn filters(leaves: Vec<Value>) -> TeamFilters {
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(
            CohortId(1),
            TeamId(TEAM),
            &json!({ "properties": { "type": "AND", "values": leaves } }),
        )
        .unwrap();
    builder.freeze(UTC)
}

fn event(person: Uuid, props: &str, offset: i64, ts: &str) -> CohortStreamEvent {
    CohortStreamEvent {
        team_id: TEAM,
        person_id: person.to_string(),
        distinct_id: "d".to_string(),
        uuid: format!("uuid-{offset}"),
        event: "$pageview".to_string(),
        timestamp: ts.to_string(),
        properties: Some("{}".to_string()),
        person_properties: Some(props.to_string()),
        elements_chain: None,
        source_offset: offset,
        source_partition: 0,
        redirected_from: None,
        redirect_hops: 0,
    }
}

fn temp_store() -> (TempDir, CohortStore) {
    let dir = TempDir::new().unwrap();
    let store = CohortStore::open(&StoreConfig {
        path: dir.path().join("db"),
        ..StoreConfig::default()
    })
    .unwrap();
    (dir, store)
}

fn person(n: u128) -> Uuid {
    Uuid::from_u128(n)
}

fn applied(entries: &[(i32, i64)]) -> AppliedOffsets {
    let mut a = AppliedOffsets::default();
    for &(partition, offset) in entries {
        a.record(partition, offset);
    }
    a
}

fn feed(store: &CohortStore, filters: &TeamFilters, event: &CohortStreamEvent) -> EventOutcome {
    process_event(PARTITION, store, filters, event).unwrap()
}

fn record(store: &CohortStore, who: Uuid) -> Option<PersonRecord> {
    store
        .get_person_record(&PersonRecordKey::new(PARTITION, TEAM as u64, who))
        .unwrap()
        .map(|bytes| PersonRecord::decode(&bytes).unwrap())
}

fn is_member(store: &CohortStore, who: Uuid, hash: [u8; 16]) -> bool {
    record(store, who).is_some_and(|r| r.matched.contains(&hash))
}

/// Sort a transition list by its condition hash + kind so two folds compare as multisets.
fn sorted(transitions: &[LeafTransition]) -> Vec<([u8; 16], TransitionKind)> {
    let mut out: Vec<_> = transitions
        .iter()
        .map(|t| (t.condition_hash, t.kind))
        .collect();
    out.sort_by_key(|(h, k)| (*h, matches!(k, TransitionKind::Left)));
    out
}

const PRO: &str = r#"{"email":"a@p.com","plan":"pro"}"#;
const FREE: &str = r#"{"email":"a@p.com","plan":"free"}"#;
const NO_EMAIL: &str = r#"{"email":"x@p.com","plan":"pro"}"#;

// --- Decision-table rows through the fold ---

#[test]
fn row0_inactive_person_side_neither_reads_nor_writes_the_record() {
    // No person conditions at all in the catalog: any event's person side is inactive.
    let (_dir, store) = temp_store();
    let f = filters(vec![email_leaf()]);
    let alice = person(1);

    // An event whose person_properties are empty is inactive even with person conditions present.
    let inactive = CohortStreamEvent {
        person_properties: Some(String::new()),
        ..event(alice, PRO, 0, "2026-05-26 10:00:00.000000")
    };
    let out = feed(&store, &f, &inactive);
    assert_eq!(
        out.skipped, None,
        "an empty-props event is a processed no-op"
    );
    assert!(out.transitions.is_empty());
    assert!(record(&store, alice).is_none(), "row 0 writes no record");
}

#[test]
fn row4b_first_eval_enters_true_conditions_and_writes_the_record() {
    let (_dir, store) = temp_store();
    let f = filters(vec![email_leaf(), plan_leaf()]);
    let alice = person(1);

    // First sighting: absent prior ⇒ Eval. Both conditions true ⇒ two Entered.
    let out = feed(
        &store,
        &f,
        &event(alice, PRO, 0, "2026-05-26 10:00:00.000000"),
    );
    assert_eq!(
        sorted(&out.transitions),
        vec![
            (EMAIL_HASH, TransitionKind::Entered),
            (PLAN_HASH, TransitionKind::Entered),
        ],
    );
    let r = record(&store, alice).unwrap();
    assert!(r.matched.contains(&EMAIL_HASH) && r.matched.contains(&PLAN_HASH));
    assert!(
        r.applied_offsets.is_replay(0, 0),
        "the event offset advanced dedup"
    );
}

#[test]
fn row1_replay_of_an_applied_offset_stages_nothing() {
    let (_dir, store) = temp_store();
    let f = filters(vec![email_leaf(), plan_leaf()]);
    let alice = person(1);

    feed(
        &store,
        &f,
        &event(alice, PRO, 0, "2026-05-26 10:00:00.000000"),
    );
    let before = record(&store, alice).unwrap();

    // Replay the same offset: is_replay(0, 0) ⇒ skip, nothing changes.
    let out = feed(
        &store,
        &f,
        &event(alice, FREE, 0, "2026-05-26 11:00:00.000000"),
    );
    assert!(out.transitions.is_empty(), "a replay flips nothing");
    assert_eq!(
        record(&store, alice).unwrap(),
        before,
        "a replay leaves the record byte-identical"
    );
}

#[test]
fn row4a_fingerprint_match_skips_eval_but_advances_the_stamp() {
    let (_dir, store) = temp_store();
    let f = filters(vec![email_leaf(), plan_leaf()]);
    let alice = person(1);

    feed(
        &store,
        &f,
        &event(alice, PRO, 0, "2026-05-26 10:00:00.000000"),
    );
    let stamp_before = record(&store, alice).unwrap().stamp;

    // Identical props + catalog, newer event: fingerprints match ⇒ SkipEval. No transition, but the
    // stamp advances (load-bearing so a later out-of-order event cannot wrongly win argMax).
    let out = feed(
        &store,
        &f,
        &event(alice, PRO, 1, "2026-05-26 12:00:00.000000"),
    );
    assert!(
        out.transitions.is_empty(),
        "a fingerprint-match event flips nothing"
    );
    let after = record(&store, alice).unwrap();
    assert!(
        after.stamp > stamp_before,
        "SkipEval adopts the fresh stamp"
    );
    assert!(after.applied_offsets.is_replay(0, 1), "and advances dedup");
    assert!(after.matched.contains(&EMAIL_HASH) && after.matched.contains(&PLAN_HASH));
}

#[test]
fn row4b_props_change_re_evaluates_and_leaves_the_false_condition() {
    let (_dir, store) = temp_store();
    let f = filters(vec![email_leaf(), plan_leaf()]);
    let alice = person(1);

    feed(
        &store,
        &f,
        &event(alice, PRO, 0, "2026-05-26 10:00:00.000000"),
    );
    // plan → free: props fingerprint mismatch ⇒ Eval. plan leaves; email stays.
    let out = feed(
        &store,
        &f,
        &event(alice, FREE, 1, "2026-05-26 11:00:00.000000"),
    );
    assert_eq!(
        sorted(&out.transitions),
        vec![(PLAN_HASH, TransitionKind::Left)],
    );
    assert!(is_member(&store, alice, EMAIL_HASH));
    assert!(!is_member(&store, alice, PLAN_HASH));
}

#[test]
fn row3_argmax_stale_event_advances_dedup_and_last_seen_but_not_membership() {
    let (_dir, store) = temp_store();
    let f = filters(vec![email_leaf(), plan_leaf()]);
    let alice = person(1);

    // Newest first (offset 0, ts 13:00): both enter.
    feed(
        &store,
        &f,
        &event(alice, PRO, 0, "2026-05-26 13:00:00.000000"),
    );
    let before = record(&store, alice).unwrap();

    // An older event (ts 12:00) on a new source partition. It is argMax-stale, so membership and the
    // stamp are unchanged — but it still records its offset (a genuine first sighting of partition 9).
    let older = CohortStreamEvent {
        source_partition: 9,
        ..event(alice, NO_EMAIL, 5, "2026-05-26 12:00:00.000000")
    };
    let out = feed(&store, &f, &older);
    assert!(out.transitions.is_empty(), "a stale event flips nothing");
    let after = record(&store, alice).unwrap();
    assert_eq!(after.stamp, before.stamp, "argMax kept the newer stamp");
    assert_eq!(
        after.matched, before.matched,
        "membership unchanged by a stale event"
    );
    assert!(
        after.applied_offsets.is_replay(9, 5),
        "the stale event still recorded its offset (row 2 precedes row 3)",
    );
    assert_eq!(
        after.last_seen_ms, before.last_seen_ms,
        "an older event never lowers last_seen"
    );
}

/// The stamp-advance counterexample: without row 4a advancing the stamp, an out-of-order event landing
/// between the old and new stamps would wrongly win argMax. Because 4a advances it, that middle event
/// is stale.
#[test]
fn row4a_stamp_advance_makes_an_intervening_out_of_order_event_stale() {
    let (_dir, store) = temp_store();
    let f = filters(vec![email_leaf(), plan_leaf()]);
    let alice = person(1);

    // t0 at 10:00 (enter).
    feed(
        &store,
        &f,
        &event(alice, PRO, 0, "2026-05-26 10:00:00.000000"),
    );
    // t2 at 14:00, identical props ⇒ SkipEval, stamp advances to 14:00.
    feed(
        &store,
        &f,
        &event(alice, PRO, 1, "2026-05-26 14:00:00.000000"),
    );

    // t1 at 12:00 (between t0 and t2), plan → free. Its ms (12:00) < the advanced stamp (14:00) ⇒
    // stale ⇒ plan must NOT leave. Had 4a not advanced the stamp, t1 would beat t0's 10:00 and wrongly
    // flip plan.
    let out = feed(
        &store,
        &f,
        &event(alice, FREE, 2, "2026-05-26 12:00:00.000000"),
    );
    assert!(
        out.transitions.is_empty(),
        "the intervening older event is stale"
    );
    assert!(
        is_member(&store, alice, PLAN_HASH),
        "plan stayed TRUE because 4a advanced the stamp past the intervening event",
    );
}

/// The replay-advance counterexample: an argMax-stale event still advances dedup, so a later replay of
/// it is skipped.
#[test]
fn a_stale_event_advances_dedup_so_its_replay_is_then_skipped() {
    let (_dir, store) = temp_store();
    let f = filters(vec![email_leaf(), plan_leaf()]);
    let alice = person(1);

    feed(
        &store,
        &f,
        &event(alice, PRO, 0, "2026-05-26 13:00:00.000000"),
    );
    let stale = CohortStreamEvent {
        source_partition: 9,
        ..event(alice, FREE, 5, "2026-05-26 12:00:00.000000")
    };
    feed(&store, &f, &stale); // argMax-stale, but records (9, 5)
    let after_stale = record(&store, alice).unwrap();

    // Replay the stale event: now a replay via the advanced dedup ⇒ skip, no change.
    let out = feed(&store, &f, &stale);
    assert!(out.transitions.is_empty());
    assert_eq!(
        record(&store, alice).unwrap(),
        after_stale,
        "the replay changed nothing"
    );
}

// --- Record-vs-per-leaf argMax equivalence ---

/// The old per-leaf rule: each condition's `matches` is the value of the argMax-latest event by
/// `(event_ms, source_offset)`. This oracle computes the final membership set that rule would produce
/// for a sequence of (props, event_ms, offset) events, and asserts the record's matched set equals it.
#[test]
fn record_argmax_matches_the_old_per_leaf_last_write_wins_rule() {
    let (_dir, store) = temp_store();
    let f = filters(vec![email_leaf(), plan_leaf()]);
    let alice = person(1);

    // Out-of-order events (offset == arrival order; ms drives argMax). Each row: (props, ms_suffix,
    // offset). All same partition 0. `email` is TRUE iff props has email a@p.com; `plan` iff plan pro.
    let seq: &[(&str, &str, i64)] = &[
        (PRO, "12:00:00", 0),      // enter both
        (FREE, "14:00:00", 1),     // newest so far: plan false
        (PRO, "13:00:00", 2),      // older than offset-1: stale, ignored
        (NO_EMAIL, "15:00:00", 3), // newest: email false, plan true
        (FREE, "13:30:00", 4),     // older than offset-3: stale
    ];

    // Oracle: the winning event per the argMax key is the one with the max (ms, offset).
    let base = "2026-05-26 ";
    let ms =
        |suffix: &str| clickhouse_timestamp_to_millis(&format!("{base}{suffix}.000000")).unwrap();
    let winner = seq
        .iter()
        .max_by_key(|(_, suffix, offset)| (ms(suffix), *offset))
        .unwrap();
    let email_expected = winner.0.contains("a@p.com");
    let plan_expected = winner.0.contains("\"plan\":\"pro\"");

    for (props, suffix, offset) in seq {
        feed(
            &store,
            &f,
            &event(alice, props, *offset, &format!("{base}{suffix}.000000")),
        );
    }

    assert_eq!(
        is_member(&store, alice, EMAIL_HASH),
        email_expected,
        "email membership matches the argMax-winning event",
    );
    assert_eq!(
        is_member(&store, alice, PLAN_HASH),
        plan_expected,
        "plan membership matches the argMax-winning event",
    );
}

// --- Record-skip parity (successor of person_memo_parity) ---

/// Feed the same event stream two ways: once normally (the fingerprint fast path `SkipEval` fires on
/// repeats), once with the stored record's fingerprints zeroed between events so every event takes the
/// full-evaluation arm. The emitted transitions (multiset), the final matched set + stamp, and the
/// event outcomes must be identical — proving `SkipEval` is indistinguishable from a re-evaluation.
#[test]
fn skip_eval_is_indistinguishable_from_a_full_re_evaluation() {
    let seq: &[(&str, i64, &str)] = &[
        (PRO, 0, "2026-05-26 10:00:00.000000"),  // enter both
        (PRO, 1, "2026-05-26 11:00:00.000000"),  // repeat (SkipEval on the normal run)
        (FREE, 2, "2026-05-26 12:00:00.000000"), // plan leaves
        (FREE, 3, "2026-05-26 13:00:00.000000"), // repeat
        (PRO, 4, "2026-05-26 14:00:00.000000"),  // plan re-enters
    ];
    let alice = person(1);

    // Normal run.
    let (_dir_a, store_a) = temp_store();
    let f_a = filters(vec![email_leaf(), plan_leaf()]);
    let mut normal_transitions: Vec<([u8; 16], TransitionKind)> = Vec::new();
    for (props, offset, ts) in seq {
        let out = feed(&store_a, &f_a, &event(alice, props, *offset, ts));
        normal_transitions.extend(sorted(&out.transitions));
    }

    // Forced-re-eval run: zero the record's fingerprints before each event so the decision table can
    // never take the SkipEval fast path — it must re-evaluate every time.
    let (_dir_b, store_b) = temp_store();
    let f_b = filters(vec![email_leaf(), plan_leaf()]);
    let mut forced_transitions: Vec<([u8; 16], TransitionKind)> = Vec::new();
    for (props, offset, ts) in seq {
        if let Some(mut r) = record(&store_b, alice) {
            r.props_fingerprint = PropsFingerprint(0);
            r.catalog_fingerprint = CatalogFingerprint(0);
            store_b
                .write_batch(|b| {
                    b.put::<PersonRecords>(
                        &PersonRecordKey::new(PARTITION, TEAM as u64, alice),
                        &r.encode(),
                    )
                })
                .unwrap();
        }
        let out = feed(&store_b, &f_b, &event(alice, props, *offset, ts));
        forced_transitions.extend(sorted(&out.transitions));
    }

    assert_eq!(
        normal_transitions, forced_transitions,
        "SkipEval must emit the same transitions as a forced re-evaluation",
    );
    // Final membership must agree.
    assert_eq!(
        record(&store_a, alice).unwrap().matched,
        record(&store_b, alice).unwrap().matched,
        "final matched set identical",
    );
    assert_eq!(
        record(&store_a, alice).unwrap().stamp,
        record(&store_b, alice).unwrap().stamp,
        "final stamp identical",
    );
}

// --- Catalog add / remove / re-add retention through the fold ---

/// A condition removed from the catalog leaves no `Left` (the hash is retained as an orphan); re-added
/// while still true emits no duplicate `Entered`; re-added then false emits `Left`.
#[test]
fn catalog_remove_readd_retention_through_the_fold() {
    let alice = person(1);

    // Start with both conditions; alice matches both.
    let (_dir, store) = temp_store();
    let with_both = filters(vec![email_leaf(), plan_leaf()]);
    let out = feed(
        &store,
        &with_both,
        &event(alice, PRO, 0, "2026-05-26 10:00:00.000000"),
    );
    assert_eq!(out.transitions.len(), 2, "both enter");

    // Remove the plan condition from the catalog. A fresh event under the reduced catalog re-evaluates
    // (catalog fingerprint changed) but must NOT emit Left for plan — its hash is a retained orphan.
    let email_only = filters(vec![email_leaf()]);
    let out = feed(
        &store,
        &email_only,
        &event(alice, PRO, 1, "2026-05-26 11:00:00.000000"),
    );
    assert!(
        out.transitions.is_empty(),
        "removing a condition emits no Left (retained orphan)",
    );
    // The orphan hash is still in the stored matched set.
    assert!(
        record(&store, alice).unwrap().matched.contains(&PLAN_HASH),
        "the removed condition's hash is retained, not dropped",
    );

    // Re-add plan while alice still matches it: no duplicate Entered (the hash never left the set).
    let out = feed(
        &store,
        &with_both,
        &event(alice, PRO, 2, "2026-05-26 12:00:00.000000"),
    );
    assert!(
        out.transitions.is_empty(),
        "re-adding a still-true retained condition does not re-Enter",
    );

    // Re-add plan but now alice is false for it: Left fires (a genuine departure).
    let out = feed(
        &store,
        &with_both,
        &event(alice, FREE, 3, "2026-05-26 13:00:00.000000"),
    );
    assert_eq!(
        sorted(&out.transitions),
        vec![(PLAN_HASH, TransitionKind::Left)],
        "the re-added condition going false emits Left",
    );
}

/// A person with a redirect-dedup ancestor whose main-map offsets are distinct: the fold never
/// confuses the two maps. (Guards the `DedupCoords` wiring in `fold_person`.)
#[test]
fn direct_and_redirected_events_use_distinct_dedup_maps() {
    let (_dir, store) = temp_store();
    let f = filters(vec![email_leaf()]);
    let p_new = person(2);
    let ancestor = person(1);

    // Seed a member record with main {5:50} and an ancestor entry {5:100}.
    let mut seed = PersonRecord::absent();
    seed.matched = [EMAIL_HASH].into_iter().collect();
    seed.applied_offsets = applied(&[(5, 50)]);
    seed.redirect_dedup.insert(ancestor, applied(&[(5, 100)]));
    store
        .write_batch(|b| {
            b.put::<PersonRecords>(
                &PersonRecordKey::new(PARTITION, TEAM as u64, p_new),
                &seed.encode(),
            )
        })
        .unwrap();

    // A direct event on source partition 5 at offset 60 (> main's 50) folds even though 60 < the
    // ancestor's 100 — the main map gates direct events, not the ancestor entry.
    let direct = CohortStreamEvent {
        source_partition: 5,
        ..event(p_new, PRO, 60, "2026-05-26 10:00:00.000000")
    };
    let out = feed(&store, &f, &direct);
    assert!(out.transitions.is_empty(), "already a member; no re-enter");
    let after = record(&store, p_new).unwrap();
    assert!(
        after.applied_offsets.is_replay(5, 60),
        "the main map advanced"
    );
    assert!(
        after.redirect_dedup[&ancestor].is_replay(5, 100)
            && !after.redirect_dedup[&ancestor].is_replay(5, 101),
        "the ancestor entry is untouched by a direct event",
    );
}
