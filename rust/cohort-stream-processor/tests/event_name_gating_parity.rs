//! Differential parity for the event-name fan-out gate: the same event sequence with gating ON
//! (evaluate only the event's name bucket) and OFF (full behavioral sweep) must yield byte-identical
//! `cf_stage1` and the same leaf transitions. Covers a matching name, a non-matching name, and
//! numeric-looking names (`"0"` vs `"0.0"`) that must not cross-match.

// This test drives the store directly through `CohortStore` for seeding and assertions — the
// sanctioned direct-store surface for tests.
#![allow(clippy::disallowed_methods)]

use std::collections::BTreeMap;

use chrono_tz::UTC;
use cohort_stream_processor::consumers::CohortStreamEvent;
use cohort_stream_processor::filters::{
    CohortId, Generation, TeamFilters, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::stage1::LeafTransition;
use cohort_stream_processor::store::{CohortStore, StoreConfig};
use cohort_stream_processor::workers::{
    process_event_with_memo, EventNameGating, EventOutcome, PersonMemo,
};
use serde_json::{json, Value};
use tempfile::TempDir;
use uuid::Uuid;

const TEAM: i32 = 7;
const PARTITION: u16 = 0;

const PAGEVIEW_HASH: [u8; 16] = *b"pageviewhash0001";
const PURCHASE_HASH: [u8; 16] = *b"purchasehash0002";
const ZERO_HASH: [u8; 16] = *b"zerohash00000003";
const ZERODOT_HASH: [u8; 16] = *b"zerodothash00004";
const PAGEVIEW_MULTIPLE_HASH: [u8; 16] = *b"pageviewmult0006";

/// A `performed_event` leaf whose bytecode roots at `event == <event_name>`.
fn behavioral_leaf(event_name: &str, hash: &str) -> Value {
    json!({
        "type": "behavioral",
        "value": "performed_event",
        "key": event_name,
        "time_value": 7,
        "time_interval": "day",
        "conditionHash": hash,
        "bytecode": ["_H", 1, 32, event_name, 32, "event", 1, 1, 11],
    })
}

/// A `performed_event_multiple` leaf on `event_name`: the same `event == <name>` matcher bytecode,
/// but a count window that drives the `BehavioralDailyBuckets` write path rather than
/// `BehavioralSingle`. `gte 1` makes a single matching event flip it to member.
fn behavioral_multiple_leaf(event_name: &str, hash: &str) -> Value {
    json!({
        "type": "behavioral",
        "value": "performed_event_multiple",
        "key": event_name,
        "time_value": 7,
        "time_interval": "day",
        "operator": "gte",
        "operator_value": 1,
        "conditionHash": hash,
        "bytecode": ["_H", 1, 32, event_name, 32, "event", 1, 1, 11],
    })
}

/// A `plan == "pro"` person leaf, so the gate is shown not to disturb the person path.
fn person_leaf() -> Value {
    json!({
        "type": "person",
        "key": "plan",
        "value": "pro",
        "operator": "exact",
        "conditionHash": "planhash00000005",
        "bytecode": ["_H", 1, 32, "pro", 32, "plan", 32, "properties", 32, "person", 1, 3, 11],
    })
}

/// Four behavioral leaves across distinct event names (two numeric-looking) plus a person leaf.
fn catalog() -> TeamFilters {
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(
            CohortId(1),
            TeamId(TEAM),
            &json!({
                "properties": {
                    "type": "AND",
                    "values": [
                        behavioral_leaf("$pageview", "pageviewhash0001"),
                        behavioral_leaf("purchase", "purchasehash0002"),
                        behavioral_leaf("0", "zerohash00000003"),
                        behavioral_leaf("0.0", "zerodothash00004"),
                        person_leaf(),
                    ],
                }
            }),
        )
        .unwrap();
    builder.freeze(UTC)
}

/// A `$pageview` bucket holding two distinct behavioral leaves — a `performed_event`
/// (`BehavioralSingle`) and a `performed_event_multiple` (`BehavioralDailyBuckets`) — so one event
/// name maps to 2 conditionHashes across 2 write paths.
fn multi_condition_catalog() -> TeamFilters {
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(
            CohortId(1),
            TeamId(TEAM),
            &json!({
                "properties": {
                    "type": "AND",
                    "values": [
                        behavioral_leaf("$pageview", "pageviewhash0001"),
                        behavioral_multiple_leaf("$pageview", "pageviewmult0006"),
                    ],
                }
            }),
        )
        .unwrap();
    builder.freeze(UTC)
}

fn event(person: Uuid, event_name: &str, offset: i64, timestamp: &str) -> CohortStreamEvent {
    CohortStreamEvent {
        team_id: TEAM,
        person_id: person.to_string(),
        distinct_id: "d".to_string(),
        uuid: format!("uuid-{offset}"),
        event: event_name.to_string(),
        timestamp: timestamp.to_string(),
        properties: Some("{}".to_string()),
        // Never matches the `pro` person leaf, so the person path writes state but flips nothing.
        person_properties: Some(r#"{"plan":"free"}"#.to_string()),
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

/// The partition's full `cf_stage1`, keyed by encoded key bytes. Two byte-identical runs compare
/// equal regardless of write order.
fn dump_stage1(store: &CohortStore) -> BTreeMap<Vec<u8>, Vec<u8>> {
    let mut out = BTreeMap::new();
    let mut cursor: Option<Vec<u8>> = None;
    loop {
        let page = store
            .scan_stage1(PARTITION, cursor.as_deref(), 4096)
            .unwrap();
        if page.is_empty() {
            break;
        }
        let page_len = page.len();
        cursor = page.last().map(|(key, _)| key.encode().to_vec());
        for (key, value) in page {
            out.insert(key.encode().to_vec(), value);
        }
        if page_len < 4096 {
            break;
        }
    }
    out
}

/// Sort transitions by debug form so two runs compare as multisets — the gated and full sweeps push
/// applies in different orders.
fn sorted_transitions(transitions: &[LeafTransition]) -> Vec<LeafTransition> {
    let mut sorted = transitions.to_vec();
    sorted.sort_by_cached_key(|t| format!("{t:?}"));
    sorted
}

/// Feeds each event to two independent stores — gating ON and OFF — and asserts parity after every
/// step. The memo is disabled on both so the gate is the only varying axis.
struct GatingParity {
    _on_dir: TempDir,
    _off_dir: TempDir,
    on_store: CohortStore,
    off_store: CohortStore,
}

impl GatingParity {
    fn new() -> Self {
        let (on_dir, on_store) = temp_store();
        let (off_dir, off_store) = temp_store();
        Self {
            _on_dir: on_dir,
            _off_dir: off_dir,
            on_store,
            off_store,
        }
    }

    fn feed(
        &mut self,
        filters: &TeamFilters,
        event: &CohortStreamEvent,
        label: &str,
    ) -> EventOutcome {
        let on = process_event_with_memo(
            PARTITION,
            &self.on_store,
            filters,
            Generation(1),
            event,
            &mut PersonMemo::disabled(),
            EventNameGating::Enabled,
        )
        .unwrap();
        let off = process_event_with_memo(
            PARTITION,
            &self.off_store,
            filters,
            Generation(1),
            event,
            &mut PersonMemo::disabled(),
            EventNameGating::Disabled,
        )
        .unwrap();

        assert_eq!(on.skipped, off.skipped, "{label}: skip reason");
        assert_eq!(on.event_ms, off.event_ms, "{label}: event_ms");
        assert_eq!(
            sorted_transitions(&on.transitions),
            sorted_transitions(&off.transitions),
            "{label}: transitions",
        );
        let (mut on_sched, mut off_sched) = (on.schedules.clone(), off.schedules.clone());
        on_sched.sort_by_key(|(key, deadline)| (key.encode(), *deadline));
        off_sched.sort_by_key(|(key, deadline)| (key.encode(), *deadline));
        assert_eq!(on_sched, off_sched, "{label}: schedules");
        assert_eq!(
            dump_stage1(&self.on_store),
            dump_stage1(&self.off_store),
            "{label}: cf_stage1 bytes",
        );
        on
    }
}

#[test]
fn gating_matches_full_sweep_across_matching_missing_and_numeric_names() {
    let mut p = GatingParity::new();
    let alice = Uuid::from_u128(1);
    let filters = catalog();

    let s1 = p.feed(
        &filters,
        &event(alice, "$pageview", 0, "2026-05-26 10:00:00.000000"),
        "s1 $pageview",
    );
    assert_eq!(s1.transitions.len(), 1, "s1: only the $pageview leaf flips");
    assert_eq!(s1.transitions[0].condition_hash, PAGEVIEW_HASH);

    // `"0"` must not cross-match the `"0.0"` leaf: same-type string compare, no numeric coercion.
    let s2 = p.feed(
        &filters,
        &event(alice, "0", 1, "2026-05-26 11:00:00.000000"),
        "s2 numeric 0",
    );
    assert_eq!(
        s2.transitions.len(),
        1,
        "s2: \"0\" does not cross-match \"0.0\""
    );
    assert_eq!(s2.transitions[0].condition_hash, ZERO_HASH);

    let s3 = p.feed(
        &filters,
        &event(alice, "0.0", 2, "2026-05-26 12:00:00.000000"),
        "s3 numeric 0.0",
    );
    assert_eq!(
        s3.transitions.len(),
        1,
        "s3: \"0.0\" does not cross-match \"0\""
    );
    assert_eq!(s3.transitions[0].condition_hash, ZERODOT_HASH);

    let s4 = p.feed(
        &filters,
        &event(alice, "purchase", 3, "2026-05-26 13:00:00.000000"),
        "s4 purchase",
    );
    assert_eq!(s4.transitions.len(), 1);
    assert_eq!(s4.transitions[0].condition_hash, PURCHASE_HASH);

    let s5 = p.feed(
        &filters,
        &event(alice, "no_such_event", 4, "2026-05-26 14:00:00.000000"),
        "s5 unmatched",
    );
    assert!(
        s5.transitions.is_empty(),
        "s5: an unmatched event name flips nothing",
    );
}

#[test]
fn gating_matches_full_sweep_on_a_multi_condition_event_name_bucket() {
    // A hot event like `$pageview` is referenced by many cohorts, so its real bucket holds several
    // conditionHashes. The single-leaf-per-name catalog above never exercises a 2+ condition bucket,
    // so a gate that dropped or double-counted a hash within one bucket would diverge from the full
    // sweep silently. Feed a `$pageview` into a bucket holding both a `BehavioralSingle` and a
    // `BehavioralDailyBuckets` leaf: `feed` asserts byte-identical `cf_stage1` (covering the
    // daily-bucket write path), and both leaves must flip.
    let filters = multi_condition_catalog();
    assert_eq!(
        filters.behavioral_by_event_name["$pageview"].len(),
        2,
        "the $pageview bucket holds both conditionHashes",
    );

    let mut p = GatingParity::new();
    let alice = Uuid::from_u128(1);
    let outcome = p.feed(
        &filters,
        &event(alice, "$pageview", 0, "2026-05-26 10:00:00.000000"),
        "multi-condition $pageview",
    );

    let mut got: Vec<[u8; 16]> = outcome
        .transitions
        .iter()
        .map(|t| t.condition_hash)
        .collect();
    got.sort_unstable();
    let mut expected = [PAGEVIEW_HASH, PAGEVIEW_MULTIPLE_HASH];
    expected.sort_unstable();
    assert_eq!(
        got,
        expected.to_vec(),
        "both leaves in the bucket flip — the single and the daily-bucket write paths",
    );
}
