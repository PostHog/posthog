//! The drain against real Postgres with recording and failing sinks: what
//! one claim transaction publishes, keeps, advances, or gives up. Every
//! test that commits outbox rows holds the drain lock (see
//! `common::TestContext::hold_drain_lock`) because the claim is not scoped
//! to a team.

mod common;

use std::collections::HashMap;
use std::sync::atomic::{AtomicI64, Ordering};

use chrono::{DateTime, Utc};
use common::{FailingSink, RecordingSink, TestContext};
use serde_json::{json, Value};
use uuid::Uuid;

use personhog_identity::publish::claim::claim_sql;
use personhog_identity::publish::config::MergeEventsAllowlist;
use personhog_identity::publish::messages::{DistinctIdRow, PersonMergeEvent};
use personhog_identity::publish::{DrainError, PassReport};

impl TestContext {
    async fn insert_completed_op(&self, op_type: &str) -> Uuid {
        let op_id = Uuid::now_v7();
        sqlx::query(
            r#"
            INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request, outcome, completed_at)
            VALUES ($1, $2, $3, 'completed', '{}'::jsonb, '{}'::jsonb, now())
            "#,
        )
        .bind(op_id)
        .bind(op_type)
        .bind(self.team_id as i32)
        .execute(&self.pool)
        .await
        .expect("insert op");
        op_id
    }

    async fn insert_op_person(
        &self,
        op_id: Uuid,
        person_id: i64,
        person_uuid: Uuid,
        role: &str,
        moved: Option<Value>,
    ) {
        let status = if role == "target" {
            "cleared"
        } else {
            "deleted"
        };
        sqlx::query(
            r#"
            INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status, moved)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            "#,
        )
        .bind(op_id)
        .bind(self.team_id as i32)
        .bind(person_id)
        .bind(person_uuid)
        .bind(role)
        .bind(status)
        .bind(moved)
        .execute(&self.pool)
        .await
        .expect("insert op person");
    }

    async fn insert_pointer(&self, op_id: Uuid, kind: &str) -> i64 {
        sqlx::query_scalar(
            "INSERT INTO person_publish_outbox (team_id, kind, op_id) VALUES ($1, $2, $3) RETURNING id",
        )
        .bind(self.team_id as i32)
        .bind(kind)
        .bind(op_id)
        .fetch_one(&self.pool)
        .await
        .expect("insert pointer")
    }

    async fn insert_mapping_row(&self, person_uuid: Uuid, distinct_id: &str, version: i64) -> i64 {
        sqlx::query_scalar(
            r#"
            INSERT INTO person_publish_outbox (team_id, kind, person_uuid, distinct_id, version)
            VALUES ($1, 'create', $2, $3, $4) RETURNING id
            "#,
        )
        .bind(self.team_id as i32)
        .bind(person_uuid)
        .bind(distinct_id)
        .bind(version)
        .fetch_one(&self.pool)
        .await
        .expect("insert mapping row")
    }

    /// A completed merge op with one source whose `moved` is `source_moved`
    /// and, unless `with_target` is false, one target whose `moved` is its
    /// claim record, an object, as the merge saga writes it. Returns the
    /// op id and its pointer's outbox id.
    async fn insert_merge_pointer(
        &self,
        target_uuid: Uuid,
        source_moved: Option<Value>,
        with_target: bool,
    ) -> (Uuid, i64) {
        let op_id = self.insert_completed_op("merge").await;
        if with_target {
            self.insert_op_person(
                op_id,
                next_person_id(),
                target_uuid,
                "target",
                Some(json!({"dispositions": []})),
            )
            .await;
        }
        self.insert_op_person(
            op_id,
            next_person_id(),
            Uuid::now_v7(),
            "source",
            source_moved,
        )
        .await;
        let outbox_id = self.insert_pointer(op_id, "merge_op").await;
        (op_id, outbox_id)
    }

    fn row(
        &self,
        person_id: Uuid,
        distinct_id: &str,
        version: i64,
        is_deleted: u8,
    ) -> DistinctIdRow {
        DistinctIdRow {
            person_id,
            team_id: self.team_id,
            distinct_id: distinct_id.to_string(),
            version,
            is_deleted,
        }
    }
}

fn moved(entries: &[(&str, i64)]) -> Value {
    Value::Array(
        entries
            .iter()
            .map(|(distinct_id, version)| json!({"distinct_id": distinct_id, "version": version}))
            .collect(),
    )
}

fn as_refs(entries: &[(String, i64)]) -> Vec<(&str, i64)> {
    entries.iter().map(|(d, v)| (d.as_str(), *v)).collect()
}

/// Person ids for per-person rows. The fixtures never touch the person
/// table, so any id works; they only need to be distinct within an op and
/// increasing within a test so the keyset order is the insertion order.
fn next_person_id() -> i64 {
    static NEXT: AtomicI64 = AtomicI64::new(0);
    let base = i64::from(std::process::id()) << 20;
    base + NEXT.fetch_add(1, Ordering::Relaxed)
}

#[tokio::test]
async fn a_failed_send_leaves_every_claimed_row_in_place_for_the_next_pass() {
    let ctx = TestContext::new().await;
    let _drain_lock = ctx.hold_drain_lock().await;
    let created = Uuid::now_v7();
    let target = Uuid::now_v7();
    let mapping_id = ctx.insert_mapping_row(created, "did-created", 0).await;
    let (_, pointer_id) = ctx
        .insert_merge_pointer(target, Some(moved(&[("did-x", 1), ("did-y", 2)])), true)
        .await;
    let before = ctx.outbox_rows().await;
    assert_eq!(before.len(), 2);

    let err = ctx
        .publisher(FailingSink, 5)
        .drain_once()
        .await
        .expect_err("a sink failure fails the pass");
    assert!(matches!(err, DrainError::Publish(_)), "{err}");
    assert_eq!(
        ctx.outbox_rows().await,
        before,
        "nothing deleted, no cursor moved, no attempt counted"
    );

    let sink = RecordingSink::default();
    ctx.publisher(sink.clone(), 5)
        .drain_once()
        .await
        .expect("the next pass publishes");
    assert_eq!(
        sink.rows_for_team(ctx.team_id),
        vec![
            ctx.row(created, "did-created", 0, 0),
            ctx.row(target, "did-x", 1, 0),
            ctx.row(target, "did-y", 2, 0),
        ],
        "claim order: the mapping row ({mapping_id}) then the pointer ({pointer_id})"
    );
    assert!(ctx.outbox_rows().await.is_empty());

    ctx.cleanup().await.expect("cleanup");
}

// Every shape here is state the sagas cannot write. Each must leave its own
// pointer pending with a reason and a counted attempt, leave the rest of the
// batch alone, and publish on its own once the state is repaired; a raise in
// the resolution SQL would instead fail the pass and, since the poisoned row
// stays the oldest, every pass after it.
#[tokio::test]
async fn a_poisoned_pointer_is_deferred_while_the_rest_of_its_batch_publishes() {
    let ctx = TestContext::new().await;
    let _drain_lock = ctx.hold_drain_lock().await;
    let target = Uuid::now_v7();

    let (healthy, _) = ctx
        .insert_merge_pointer(target, Some(moved(&[("did-h", 3)])), true)
        .await;
    // The largest version the mapping table can hold is healthy too.
    let (largest, _) = ctx
        .insert_merge_pointer(target, Some(moved(&[("did-max", i64::MAX)])), true)
        .await;
    // Moved nothing: a source with no live distinct ids.
    let (empty, _) = ctx.insert_merge_pointer(target, None, true).await;
    let vanished = Uuid::now_v7();
    ctx.insert_pointer(vanished, "delete_op").await;

    let poison: Vec<(&str, Option<Value>, bool, &str)> = vec![
        (
            "moved is a string",
            Some(json!("garbage")),
            true,
            "not an array",
        ),
        (
            "decimal version",
            Some(json!([{"distinct_id": "bad", "version": 1.5}])),
            true,
            "malformed",
        ),
        (
            // 1e20 lands in jsonb as a 21-digit integer, past bigint.
            "out-of-range version",
            Some(json!([{"distinct_id": "bad", "version": 1e20}])),
            true,
            "malformed",
        ),
        (
            "string version",
            Some(json!([{"distinct_id": "bad", "version": "3"}])),
            true,
            "malformed",
        ),
        (
            "numeric distinct_id",
            Some(json!([{"distinct_id": 7, "version": 1}])),
            true,
            "malformed",
        ),
        (
            "null distinct_id",
            Some(json!([{"distinct_id": null, "version": 1}])),
            true,
            "malformed",
        ),
        (
            "bare string element",
            Some(json!(["did-bare"])),
            true,
            "malformed",
        ),
        (
            "merge without a target row",
            Some(moved(&[("did-orphan", 1)])),
            false,
            "target rows",
        ),
    ];
    let mut expected_errors: HashMap<Uuid, (&str, &str)> = HashMap::new();
    for (label, source_moved, with_target, error_fragment) in &poison {
        let (op_id, _) = ctx
            .insert_merge_pointer(target, source_moved.clone(), *with_target)
            .await;
        expected_errors.insert(op_id, (label, error_fragment));
    }
    expected_errors.insert(vanished, ("vanished op", "no longer exists"));

    let sink = RecordingSink::default();
    let publisher = ctx.publisher(sink.clone(), 5);
    publisher.drain_once().await.expect("the pass commits");
    assert_eq!(
        sink.rows_for_team(ctx.team_id),
        vec![
            ctx.row(target, "did-h", 3, 0),
            ctx.row(target, "did-max", i64::MAX, 0)
        ],
        "only the healthy pointers publish"
    );
    let snapshot = |rows: Vec<common::OutboxRow>| -> HashMap<Uuid, (bool, i32, String)> {
        rows.into_iter()
            .map(|r| {
                (
                    r.op_id.unwrap(),
                    (r.given_up, r.attempts, r.last_error.unwrap_or_default()),
                )
            })
            .collect()
    };
    let left = snapshot(ctx.outbox_rows().await);
    assert!(
        !left.contains_key(&healthy) && !left.contains_key(&largest) && !left.contains_key(&empty),
        "healthy and empty pointers are deleted: {left:?}"
    );
    assert_eq!(left.len(), expected_errors.len(), "{left:?}");
    for (op_id, (label, error_fragment)) in &expected_errors {
        let (given_up, attempts, last_error) = &left[op_id];
        assert!(!given_up, "{label}: parked, but the publisher never parks");
        assert_eq!(*attempts, 1, "{label}: attempts");
        assert!(
            last_error.contains(error_fragment),
            "{label}: last_error {last_error:?} lacks {error_fragment:?}"
        );
    }

    publisher
        .drain_once()
        .await
        .expect("the second pass commits");
    assert_eq!(sink.rows_for_team(ctx.team_id).len(), 2);
    for (op_id, (_, attempts, _)) in snapshot(ctx.outbox_rows().await) {
        assert_eq!(attempts, 2, "{op_id}: attempts after the second pass");
    }

    let (repaired, _) = expected_errors
        .iter()
        .find(|(_, (label, _))| *label == "moved is a string")
        .expect("the string-moved op is in the table");
    sqlx::query("UPDATE lifecycle_op_person SET moved = $1 WHERE op_id = $2 AND role = 'source'")
        .bind(moved(&[("did-fixed", 2)]))
        .bind(repaired)
        .execute(&ctx.pool)
        .await
        .expect("repair moved");
    publisher
        .drain_once()
        .await
        .expect("the third pass commits");
    assert_eq!(
        sink.rows_for_team(ctx.team_id),
        vec![
            ctx.row(target, "did-h", 3, 0),
            ctx.row(target, "did-max", i64::MAX, 0),
            ctx.row(target, "did-fixed", 2, 0)
        ]
    );
    let left = snapshot(ctx.outbox_rows().await);
    assert!(
        !left.contains_key(repaired),
        "the repaired pointer is deleted"
    );
    assert_eq!(left.len(), expected_errors.len() - 1);

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_large_pointer_drains_in_cursor_chunks_without_a_gap_or_a_repeat() {
    let ctx = TestContext::new().await;
    let _drain_lock = ctx.hold_drain_lock().await;
    // Two victims, 5 and 7 tombstoned ids, drained 5 at a time: the first
    // person ends exactly at the limit, so the second chunk must start on
    // the next person without repeating the last entry or skipping the
    // first; the third chunk is short.
    let op_id = ctx.insert_completed_op("delete").await;
    let (victim_a, victim_b) = (Uuid::now_v7(), Uuid::now_v7());
    let (person_a, person_b) = (next_person_id(), next_person_id());
    let a_entries: Vec<(String, i64)> = (1..=5).map(|i| (format!("a-{i}"), i)).collect();
    let b_entries: Vec<(String, i64)> = (1..=7).map(|i| (format!("b-{i}"), 10 + i)).collect();
    ctx.insert_op_person(
        op_id,
        person_a,
        victim_a,
        "victim",
        Some(moved(&as_refs(&a_entries))),
    )
    .await;
    ctx.insert_op_person(
        op_id,
        person_b,
        victim_b,
        "victim",
        Some(moved(&as_refs(&b_entries))),
    )
    .await;
    ctx.insert_pointer(op_id, "delete_op").await;

    let sink = RecordingSink::default();
    let publisher = ctx.publisher(sink.clone(), 5);
    let cursor_after = |rows: Vec<common::OutboxRow>| {
        rows.into_iter()
            .map(|r| (r.cursor_person_id, r.cursor_mapping_ordinal, r.attempts))
            .collect::<Vec<_>>()
    };

    publisher.drain_once().await.expect("first chunk");
    assert_eq!(sink.rows_for_team(ctx.team_id).len(), 5);
    assert_eq!(
        cursor_after(ctx.outbox_rows().await),
        vec![(person_a, 5, 1)]
    );

    publisher.drain_once().await.expect("second chunk");
    assert_eq!(sink.rows_for_team(ctx.team_id).len(), 10);
    assert_eq!(
        cursor_after(ctx.outbox_rows().await),
        vec![(person_b, 5, 2)]
    );

    publisher.drain_once().await.expect("final chunk");
    assert_eq!(sink.rows_for_team(ctx.team_id).len(), 12);
    assert!(ctx.outbox_rows().await.is_empty());

    let expected: Vec<DistinctIdRow> = a_entries
        .iter()
        .map(|(d, v)| ctx.row(victim_a, d, *v, 1))
        .chain(b_entries.iter().map(|(d, v)| ctx.row(victim_b, d, *v, 1)))
        .collect();
    assert_eq!(sink.rows_for_team(ctx.team_id), expected);

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn the_row_budget_spans_claimed_rows_and_the_rest_wait_for_the_next_pass() {
    let ctx = TestContext::new().await;
    let _drain_lock = ctx.hold_drain_lock().await;
    // Three rows under a budget of 10: a merge of 6 ids takes 6, a second
    // merge of 6 gets the other 4 and advances, and the mapping row behind
    // them is left alone, attempts included, until the next pass.
    let (target_a, target_b) = (Uuid::now_v7(), Uuid::now_v7());
    let a_entries: Vec<(String, i64)> = (1..=6).map(|i| (format!("a-{i}"), i)).collect();
    let b_entries: Vec<(String, i64)> = (1..=6).map(|i| (format!("b-{i}"), 10 + i)).collect();
    ctx.insert_merge_pointer(target_a, Some(moved(&as_refs(&a_entries))), true)
        .await;
    let (_, pointer_b) = ctx
        .insert_merge_pointer(target_b, Some(moved(&as_refs(&b_entries))), true)
        .await;
    let late = Uuid::now_v7();
    let mapping = ctx.insert_mapping_row(late, "late", 0).await;

    let sink = RecordingSink::default();
    let publisher = ctx.publisher(sink.clone(), 10);

    let report = publisher.drain_once().await.expect("first pass");
    assert_eq!(
        report,
        PassReport {
            claimed: 3,
            finished: 1,
            advanced: 1,
            deferred: 0,
            unprocessed: 1,
            messages: 10,
        }
    );
    let left: Vec<(i64, i64, i32)> = ctx
        .outbox_rows()
        .await
        .into_iter()
        .map(|r| (r.id, r.cursor_mapping_ordinal, r.attempts))
        .collect();
    assert_eq!(left, vec![(pointer_b, 4, 1), (mapping, 0, 0)]);

    publisher.drain_once().await.expect("second pass");
    assert!(ctx.outbox_rows().await.is_empty());
    let expected: Vec<DistinctIdRow> = a_entries
        .iter()
        .map(|(d, v)| ctx.row(target_a, d, *v, 0))
        .chain(b_entries.iter().map(|(d, v)| ctx.row(target_b, d, *v, 0)))
        .chain([ctx.row(late, "late", 0, 0)])
        .collect();
    assert_eq!(sink.rows_for_team(ctx.team_id), expected);

    ctx.cleanup().await.expect("cleanup");
}

// A backlog must be claimed in id order through the pending partial index,
// bounded by LIMIT, never by sorting every pending row. The statement the
// drain really runs and the index have to agree on that: a claim ordered
// by a column the index does not cover, or a dropped or re-predicated
// index, turns every claim on a backlog into a sort of the whole backlog.
//
// The planner costs a sort's input by the heap's real page count and the
// index scan by the rows LIMIT needs, so on a heap of any size a sort plan
// loses whatever the row estimate says; it can win only while the heap is
// a few dozen pages, where sorting is as cheap as not. The burst here is
// large enough that the two plans diverge, and it is analyzed so the
// assertion does not hinge on whatever statistics an earlier test left.
//
// Everything runs in one transaction that is rolled back: the burst is
// never visible to another test's drain, the statistics revert, and a
// panic cannot leave rows behind, so no drain lock is needed.
#[tokio::test]
async fn an_analyzed_backlog_is_claimed_through_the_pending_index_without_a_sort() {
    let ctx = TestContext::new().await;
    let mut tx = ctx.pool.begin().await.expect("begin");
    sqlx::query(
        r#"
        INSERT INTO person_publish_outbox (team_id, kind, person_uuid, distinct_id, version)
        SELECT $1, 'create', gen_random_uuid(), 'burst-' || n, 0 FROM generate_series(1, 20000) AS n
        "#,
    )
    .bind(ctx.team_id as i32)
    .execute(&mut *tx)
    .await
    .expect("seed a burst");
    sqlx::query("ANALYZE person_publish_outbox")
        .execute(&mut *tx)
        .await
        .expect("analyze");
    let plan: Vec<String> =
        sqlx::query_scalar(&format!("EXPLAIN {}", claim_sql("person_publish_outbox")))
            .bind(1000i64)
            .fetch_all(&mut *tx)
            .await
            .expect("explain runs");
    tx.rollback().await.expect("rollback");

    let plan = plan.join("\n");
    assert!(
        plan.contains("Index Scan using person_publish_outbox_pending"),
        "claim plan:\n{plan}"
    );
    assert!(!plan.contains("Sort"), "claim plan:\n{plan}");
}

/// A completed merge op whose one source, `source_uuid`, merged into
/// `target_uuid` with `moved` repoints, recorded in the outcome the way
/// the merge saga writes it, plus its pointer. Returns the op id.
async fn insert_merged_op(
    ctx: &TestContext,
    target_uuid: Uuid,
    source_uuid: Uuid,
    moved: Value,
) -> Uuid {
    let source_person_id = next_person_id();
    let op_id = Uuid::now_v7();
    let outcome = json!({
        "aborted": false,
        "survivor": null,
        "results": [{"distinct_id": "merged-did", "outcome": "merged", "person_id": source_person_id}],
    });
    sqlx::query(
        r#"
        INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request, outcome, completed_at)
        VALUES ($1, 'merge', $2, 'completed', '{}'::jsonb, $3, now())
        "#,
    )
    .bind(op_id)
    .bind(ctx.team_id as i32)
    .bind(outcome)
    .execute(&ctx.pool)
    .await
    .expect("insert merged op");
    ctx.insert_op_person(
        op_id,
        next_person_id(),
        target_uuid,
        "target",
        Some(json!({"dispositions": []})),
    )
    .await;
    ctx.insert_op_person(op_id, source_person_id, source_uuid, "source", Some(moved))
        .await;
    ctx.insert_pointer(op_id, "merge_op").await;
    op_id
}

// The event has to go out with exactly one chunk, and the final chunk is
// the one the drain can tell apart without extra state, because it deletes
// the pointer in the same pass; per chunk would repeat the event on every
// pass. Twelve rows give a short final chunk; ten end exactly at the limit,
// so the final chunk is empty and the event rides a pass that resolves no
// row.
#[tokio::test]
async fn merge_events_go_out_once_with_the_final_chunk() {
    let ctx = TestContext::new().await;
    let _drain_lock = ctx.hold_drain_lock().await;
    for total in [12_i64, 10] {
        let (target, source) = (Uuid::now_v7(), Uuid::now_v7());
        let entries: Vec<(String, i64)> = (1..=total).map(|i| (format!("m-{i}"), i)).collect();
        let op_id = insert_merged_op(&ctx, target, source, moved(&as_refs(&entries))).await;
        let completed_at: DateTime<Utc> =
            sqlx::query_scalar("SELECT completed_at FROM lifecycle_op WHERE op_id = $1")
                .bind(op_id)
                .fetch_one(&ctx.pool)
                .await
                .expect("op row");

        let sink = RecordingSink::default();
        let publisher = ctx.publisher_with_merge_events(sink.clone(), 5, MergeEventsAllowlist::All);
        publisher.drain_once().await.expect("first chunk");
        publisher.drain_once().await.expect("second chunk");
        assert_eq!(sink.rows_for_team(ctx.team_id).len(), 10, "{total} rows");
        assert!(
            sink.merge_events_for_team(ctx.team_id).is_empty(),
            "{total} rows: no event before the final chunk"
        );

        publisher.drain_once().await.expect("final chunk");
        assert_eq!(sink.rows_for_team(ctx.team_id).len() as i64, total);
        assert_eq!(
            sink.merge_events_for_team(ctx.team_id),
            vec![PersonMergeEvent {
                team_id: ctx.team_id as i32,
                old_person_uuid: source,
                new_person_uuid: target,
                merged_at_ms: completed_at.timestamp_millis(),
                schema_version: 1,
            }],
            "{total} rows"
        );
        assert!(ctx.outbox_rows().await.is_empty(), "{total} rows");
    }

    ctx.cleanup().await.expect("cleanup");
}

// The outcome and the per-person rows are two records of the same merge;
// an event built from one while the other disagrees would name a person
// that was not merged, so the pointer stays pending instead, rows and all,
// and publishes on its own once the records agree again.
#[tokio::test]
async fn a_merge_op_whose_outcome_and_rows_disagree_is_deferred_until_repaired() {
    let ctx = TestContext::new().await;
    let _drain_lock = ctx.hold_drain_lock().await;
    let (target, source) = (Uuid::now_v7(), Uuid::now_v7());
    let op_id = insert_merged_op(&ctx, target, source, moved(&[("d-1", 1)])).await;
    let pool = &ctx.pool;
    let set_source_status = |status: &'static str| async move {
        sqlx::query(
            "UPDATE lifecycle_op_person SET status = $1 WHERE op_id = $2 AND role = 'source'",
        )
        .bind(status)
        .bind(op_id)
        .execute(pool)
        .await
        .expect("set the source status");
    };
    set_source_status("sealed").await;

    let sink = RecordingSink::default();
    let publisher = ctx.publisher_with_merge_events(sink.clone(), 100, MergeEventsAllowlist::All);
    publisher.drain_once().await.expect("the pass commits");
    assert!(
        sink.rows_for_team(ctx.team_id).is_empty(),
        "a deferred pointer publishes none of its rows"
    );
    assert!(sink.merge_events_for_team(ctx.team_id).is_empty());
    let rows = ctx.outbox_rows().await;
    assert_eq!(rows.len(), 1);
    assert!(!rows[0].given_up);
    assert_eq!(rows[0].attempts, 1);
    assert!(
        rows[0]
            .last_error
            .as_deref()
            .unwrap_or("")
            .contains("recorded merged sources"),
        "{:?}",
        rows[0].last_error
    );

    set_source_status("deleted").await;
    publisher.drain_once().await.expect("the pass commits");
    assert_eq!(
        sink.rows_for_team(ctx.team_id),
        vec![ctx.row(target, "d-1", 1, 0)]
    );
    let events = sink.merge_events_for_team(ctx.team_id);
    assert_eq!(events.len(), 1, "{events:?}");
    assert_eq!(
        (events[0].old_person_uuid, events[0].new_person_uuid),
        (source, target)
    );
    assert!(ctx.outbox_rows().await.is_empty());

    ctx.cleanup().await.expect("cleanup");
}

// A merge's events ride its final chunk, so a pass full of merge pointers
// could enqueue events past the row budget unless they count against it.
#[tokio::test]
async fn merge_events_count_against_the_pass_budget() {
    let ctx = TestContext::new().await;
    let _drain_lock = ctx.hold_drain_lock().await;
    let (target, source_a, source_b) = (Uuid::now_v7(), Uuid::now_v7(), Uuid::now_v7());
    insert_merged_op(&ctx, target, source_a, moved(&[("a-1", 1)])).await;
    insert_merged_op(&ctx, target, source_b, moved(&[("b-1", 1)])).await;

    let sink = RecordingSink::default();
    let publisher = ctx.publisher_with_merge_events(sink.clone(), 1, MergeEventsAllowlist::All);
    let first = publisher.drain_once().await.expect("first pass");
    assert_eq!((first.advanced, first.unprocessed), (1, 1));
    let second = publisher.drain_once().await.expect("second pass");
    assert_eq!(
        (second.finished, second.messages, second.unprocessed),
        (1, 1, 1)
    );
    assert_eq!(sink.merge_events_for_team(ctx.team_id).len(), 1);

    ctx.cleanup().await.expect("cleanup");
}
