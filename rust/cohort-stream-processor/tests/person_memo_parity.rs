//! Differential parity for the person-property memo: the same event sequence with the memo ON and
//! OFF must yield byte-identical `cf_stage1` and the same leaf transitions (a multiset — apply order
//! is non-deterministic). Covers a hit, a property change (fingerprint miss), a generation bump
//! (re-eval, no stale serve), an out-of-order stale event, and a second person.

use std::collections::BTreeMap;

use chrono_tz::UTC;
use cohort_stream_processor::consumers::CohortStreamEvent;
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, Generation, TeamFilters, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::partitions::{OffsetTracker, ShuffleMessage};
use cohort_stream_processor::producer::{CaptureSink, MembershipStatus};
use cohort_stream_processor::stage1::{LeafTransition, TransitionKind};
use cohort_stream_processor::store::{CohortStore, StoreConfig};
use cohort_stream_processor::workers::{
    process_event_with_memo, EventNameGating, EventOutcome, MergeWorkerDeps, PersonMemo,
    PersonMemoConfig, Stage1Worker,
};
use serde_json::{json, Value};
use tempfile::TempDir;
use tokio::sync::mpsc;
use uuid::Uuid;

const TEAM: i32 = 7;
const PARTITION: u16 = 0;

// Distinct 16-byte condition hashes. `email` sorts before `plan`, so the email predicate is bit 0 in
// both catalogs — the position a stale cross-generation serve would misread.
const EMAIL_ALICE: &str = "emailAlice000001";
const EMAIL_BOB: &str = "emailBob00000002";
const PLAN_PRO: &str = "planPro000000003";
const BEH_PAGEVIEW: &str = "pageviewbeh00004";

const PROPS_PRO: &str = r#"{"email":"alice@p.com","plan":"pro"}"#;
const PROPS_FREE: &str = r#"{"email":"alice@p.com","plan":"free"}"#;
const PROPS_ENTERPRISE: &str = r#"{"email":"alice@p.com","plan":"enterprise"}"#;
const PROPS_BOB: &str = r#"{"email":"bob@p.com","plan":"pro"}"#;

fn person_leaf(key: &str, value: &str, hash: &str) -> Value {
    json!({
        "type": "person",
        "key": key,
        "value": value,
        "operator": "exact",
        "conditionHash": hash,
        "bytecode": ["_H", 1, 32, value, 32, key, 32, "properties", 32, "person", 1, 3, 11],
    })
}

fn behavioral_leaf(hash: &str) -> Value {
    json!({
        "type": "behavioral",
        "value": "performed_event",
        "key": "$pageview",
        "time_value": 7,
        "time_interval": "day",
        "conditionHash": hash,
        "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
    })
}

fn team_filters(values: Vec<Value>) -> TeamFilters {
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(
            CohortId(1),
            TeamId(TEAM),
            &json!({ "properties": { "type": "AND", "values": values } }),
        )
        .unwrap();
    builder.freeze(UTC)
}

/// C1: alice's email, a plan, and a behavioral leaf.
fn catalog_v1() -> TeamFilters {
    team_filters(vec![
        person_leaf("email", "alice@p.com", EMAIL_ALICE),
        person_leaf("plan", "pro", PLAN_PRO),
        behavioral_leaf(BEH_PAGEVIEW),
    ])
}

/// C2: the email predicate is flipped to bob (a *new* condition hash); plan + behavioral unchanged.
fn catalog_v2() -> TeamFilters {
    team_filters(vec![
        person_leaf("email", "bob@p.com", EMAIL_BOB),
        person_leaf("plan", "pro", PLAN_PRO),
        behavioral_leaf(BEH_PAGEVIEW),
    ])
}

fn event(person: Uuid, props: &str, offset: i64, timestamp: &str) -> CohortStreamEvent {
    CohortStreamEvent {
        team_id: TEAM,
        person_id: person.to_string(),
        distinct_id: "d".to_string(),
        uuid: format!("uuid-{offset}"),
        event: "$pageview".to_string(),
        timestamp: timestamp.to_string(),
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

/// The partition's full `cf_stage1`, keyed by encoded key bytes (`Stage1Key` is not `Ord`). Two runs
/// with byte-identical state produce equal maps regardless of write order.
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

/// Sort transitions by their debug form so two runs compare as multisets — apply order differs
/// between the ordered (memo) and unordered (sweep) person loops, but the set is identical.
fn sorted_transitions(transitions: &[LeafTransition]) -> Vec<LeafTransition> {
    let mut sorted = transitions.to_vec();
    sorted.sort_by_cached_key(|t| format!("{t:?}"));
    sorted
}

/// Runs each event through two independent stores — memo on and memo off — and asserts parity after
/// every step. The memo persists across the whole sequence.
struct Parity {
    _on_dir: TempDir,
    _off_dir: TempDir,
    on_store: CohortStore,
    off_store: CohortStore,
    on_memo: PersonMemo,
    off_memo: PersonMemo,
}

impl Parity {
    fn new() -> Self {
        let (on_dir, on_store) = temp_store();
        let (off_dir, off_store) = temp_store();
        Self {
            _on_dir: on_dir,
            _off_dir: off_dir,
            on_store,
            off_store,
            on_memo: PersonMemo::new(PersonMemoConfig {
                enabled: true,
                capacity: 16,
            }),
            off_memo: PersonMemo::disabled(),
        }
    }

    /// Feed one event to both stores, assert outcome + state parity, and return the memo-on outcome.
    fn feed(
        &mut self,
        filters: &TeamFilters,
        generation: Generation,
        event: &CohortStreamEvent,
        label: &str,
    ) -> EventOutcome {
        let on = process_event_with_memo(
            PARTITION,
            &self.on_store,
            filters,
            generation,
            event,
            &mut self.on_memo,
            EventNameGating::Disabled,
        )
        .unwrap();
        let off = process_event_with_memo(
            PARTITION,
            &self.off_store,
            filters,
            generation,
            event,
            &mut self.off_memo,
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

fn transition_kinds(outcome: &EventOutcome) -> Vec<TransitionKind> {
    let mut kinds: Vec<TransitionKind> = outcome.transitions.iter().map(|t| t.kind).collect();
    kinds.sort_by_key(|k| matches!(k, TransitionKind::Left));
    kinds
}

#[test]
fn memo_matches_full_sweep_across_hit_miss_gen_bump_and_stale_events() {
    let mut p = Parity::new();
    let alice = Uuid::from_u128(1);
    let bob = Uuid::from_u128(2);
    let c1 = catalog_v1();
    let c2 = catalog_v2();

    // 1. First sighting (miss): email + plan + behavioral all match → three Entered.
    let s1 = p.feed(
        &c1,
        Generation(1),
        &event(alice, PROPS_PRO, 0, "2026-05-26 10:00:00.000000"),
        "s1 miss",
    );
    assert_eq!(s1.transitions.len(), 3, "s1: three leaves entered");
    assert!(s1
        .transitions
        .iter()
        .all(|t| t.kind == TransitionKind::Entered));

    // 2. Identical props (memo hit): no membership change, state advances identically.
    let s2 = p.feed(
        &c1,
        Generation(1),
        &event(alice, PROPS_PRO, 1, "2026-05-26 11:00:00.000000"),
        "s2 hit",
    );
    assert!(
        s2.transitions.is_empty(),
        "s2: a repeat event flips nothing"
    );

    // 3. Plan changes free (fingerprint miss → re-eval): the plan leaf leaves.
    let s3 = p.feed(
        &c1,
        Generation(1),
        &event(alice, PROPS_FREE, 2, "2026-05-26 12:00:00.000000"),
        "s3 fp miss",
    );
    assert_eq!(
        transition_kinds(&s3),
        vec![TransitionKind::Left],
        "s3: plan left"
    );

    // 4. Catalog generation bumps and the email predicate flips to bob. The stale gen-1 entry must NOT
    //    be served: alice no longer matches the email leaf, and the plan leaf re-enters (pro again).
    let s4 = p.feed(
        &c2,
        Generation(2),
        &event(alice, PROPS_PRO, 3, "2026-05-26 13:00:00.000000"),
        "s4 gen bump",
    );
    assert_eq!(
        transition_kinds(&s4),
        vec![TransitionKind::Entered],
        "s4: only the plan re-enters; the flipped email leaf does not match alice",
    );

    // 5. An out-of-order, older event (enterprise plan): argMax rejects every leaf in both runs.
    let s5 = p.feed(
        &c2,
        Generation(2),
        &event(alice, PROPS_ENTERPRISE, 5, "2026-05-26 09:00:00.000000"),
        "s5 stale",
    );
    assert!(s5.transitions.is_empty(), "s5: a stale event flips nothing");

    // 6. A second person under the same generation: a distinct memo key, evaluated fresh (merge analog).
    let s6 = p.feed(
        &c2,
        Generation(2),
        &event(bob, PROPS_BOB, 4, "2026-05-26 14:00:00.000000"),
        "s6 new person",
    );
    assert_eq!(
        s6.transitions.len(),
        3,
        "s6: bob enters email + plan + behavioral"
    );
    assert!(s6
        .transitions
        .iter()
        .all(|t| t.kind == TransitionKind::Entered));
}

/// Drive an enter → hit → leave sequence for one person through a spawned worker, returning the
/// membership statuses and final `cf_stage1`. The `TempDir` is returned so its store outlives the scan.
async fn run_worker_sequence(
    filters: TeamFilters,
    person: Uuid,
    memo: PersonMemoConfig,
) -> (Vec<MembershipStatus>, BTreeMap<Vec<u8>, Vec<u8>>, TempDir) {
    let (dir, store) = temp_store();
    let catalog = std::sync::Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([(
        TeamId(TEAM),
        filters,
    )])));
    let sink = CaptureSink::new();
    let tracker = std::sync::Arc::new(OffsetTracker::new());
    let (tx, rx) = mpsc::channel(16);
    let worker = Stage1Worker::spawn_with_memo(
        PARTITION,
        rx,
        store.clone(),
        catalog,
        std::sync::Arc::new(sink.clone()),
        tracker.clone(),
        MergeWorkerDeps::capture(),
        false,
        memo,
        EventNameGating::Disabled,
    );

    let sequence = [
        (PROPS_PRO, 0, "2026-05-26 10:00:00.000000"), // enter
        (PROPS_PRO, 1, "2026-05-26 11:00:00.000000"), // hit, no change
        (r#"{"email":"x@p.com"}"#, 2, "2026-05-26 12:00:00.000000"), // miss, leave
    ];
    for (props, offset, ts) in sequence {
        tracker.mark_dispatched(PARTITION as i32, offset + 1);
        tx.send(vec![ShuffleMessage::Event {
            event: Box::new(event(person, props, offset, ts)),
            cse_offset: offset,
        }])
        .await
        .unwrap();
    }
    drop(tx);
    worker.join().await.unwrap();

    let statuses = sink.changes().iter().map(|c| c.status).collect();
    (statuses, dump_stage1(&store), dir)
}

/// End-to-end through a spawned worker with the memo enabled vs disabled: the membership output and
/// `cf_stage1` must be identical across an enter → hit → leave sequence, covering `run_worker`'s memo
/// construction and the `snapshot.generation()` threading in `handle_event`.
#[tokio::test]
async fn memo_enabled_worker_matches_a_disabled_worker_end_to_end() {
    // `TeamFilters` is not `Clone`, so build it fresh for each run.
    let single_email = || team_filters(vec![person_leaf("email", "alice@p.com", EMAIL_ALICE)]);
    let alice = Uuid::from_u128(1);

    let (on_statuses, on_state, _on_dir) = run_worker_sequence(
        single_email(),
        alice,
        PersonMemoConfig {
            enabled: true,
            capacity: 16,
        },
    )
    .await;
    let (off_statuses, off_state, _off_dir) =
        run_worker_sequence(single_email(), alice, PersonMemoConfig::DISABLED).await;

    assert_eq!(
        on_statuses,
        vec![MembershipStatus::Entered, MembershipStatus::Left],
        "enabled worker: enter then leave",
    );
    assert_eq!(on_statuses, off_statuses, "membership output parity");
    assert_eq!(on_state, off_state, "cf_stage1 parity");
}
