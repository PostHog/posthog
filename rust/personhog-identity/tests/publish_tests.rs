//! The drain against real Postgres with recording and failing sinks: what
//! one claim transaction publishes, keeps, advances, or gives up. Every
//! test that commits outbox rows holds the drain lock (see
//! `common::TestContext::hold_drain_lock`) because the claim is not scoped
//! to a team.

mod common;

use std::collections::HashMap;
use std::sync::atomic::{AtomicI64, Ordering};

use common::{FailingSink, RecordingSink, TestContext};
use serde_json::{json, Value};
use uuid::Uuid;

use personhog_identity::publish::claim::claim_sql;
use personhog_identity::publish::messages::DistinctIdRow;
use personhog_identity::publish::DrainError;

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

// Every shape here is state the sagas cannot write. Each must park its own
// pointer with a reason and leave the rest of the batch alone; a raise in
// the resolution SQL would instead fail the pass and, since the poisoned
// row stays the oldest, every pass after it.
#[tokio::test]
async fn a_poisoned_pointer_is_given_up_while_the_rest_of_its_batch_publishes() {
    let ctx = TestContext::new().await;
    let _drain_lock = ctx.hold_drain_lock().await;
    let target = Uuid::now_v7();

    let (healthy, _) = ctx
        .insert_merge_pointer(target, Some(moved(&[("did-h", 3)])), true)
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
    ctx.publisher(sink.clone(), 5)
        .drain_once()
        .await
        .expect("the pass commits");
    assert_eq!(
        sink.rows_for_team(ctx.team_id),
        vec![ctx.row(target, "did-h", 3, 0)],
        "only the healthy pointer publishes"
    );
    let left: HashMap<Uuid, (bool, String)> = ctx
        .outbox_rows()
        .await
        .into_iter()
        .map(|r| {
            (
                r.op_id.unwrap(),
                (r.given_up, r.last_error.unwrap_or_default()),
            )
        })
        .collect();
    assert!(
        !left.contains_key(&healthy) && !left.contains_key(&empty),
        "healthy and empty pointers are deleted: {left:?}"
    );
    assert_eq!(left.len(), expected_errors.len(), "{left:?}");
    for (op_id, (label, error_fragment)) in &expected_errors {
        let (given_up, last_error) = &left[op_id];
        assert!(*given_up, "{label}: not given up");
        assert!(
            last_error.contains(error_fragment),
            "{label}: last_error {last_error:?} lacks {error_fragment:?}"
        );
    }

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
