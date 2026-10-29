use chrono::{DateTime, Utc};
use personhog_common::query_tag;
use sqlx::FromRow;
use uuid::Uuid;

use crate::config::IdentityTables;
use crate::lifecycle::engine::Tx;

pub const KIND_CREATE: &str = "create";
pub const KIND_ATTACH: &str = "attach";
pub const KIND_MERGE_OP: &str = "merge_op";
pub const KIND_DELETE_OP: &str = "delete_op";

/// One claimed outbox row. A mapping row carries `person_uuid`,
/// `distinct_id` and `version`; a pointer carries `op_id` and its cursor.
/// The CHECK constraint on the table keeps the two shapes exclusive.
#[derive(Debug, Clone, FromRow)]
pub struct ClaimedRow {
    pub id: i64,
    pub team_id: i32,
    pub kind: String,
    pub person_uuid: Option<Uuid>,
    pub distinct_id: Option<String>,
    pub version: Option<i64>,
    pub op_id: Option<Uuid>,
    pub cursor_person_id: i64,
    pub cursor_mapping_ordinal: i64,
    pub attempts: i32,
    pub created_at: DateTime<Utc>,
}

impl ClaimedRow {
    pub fn is_pointer(&self) -> bool {
        self.op_id.is_some()
    }
}

/// Built from a format string instead of the mirrored sqlx macros so the
/// plan test can EXPLAIN the statement the drain really runs. The table
/// name is one of the two validated sets, never user input.
pub fn claim_sql(outbox: &str) -> String {
    format!(
        r#"
        SELECT id, team_id, kind, person_uuid, distinct_id, version, op_id,
               cursor_person_id, cursor_mapping_ordinal, attempts, created_at
        FROM {outbox}
        WHERE given_up_at IS NULL
        ORDER BY id
        LIMIT $1
        FOR UPDATE SKIP LOCKED
        "#
    )
}

pub async fn claim(
    tx: &mut Tx<'_>,
    tables: &IdentityTables,
    limit: i64,
) -> Result<Vec<ClaimedRow>, sqlx::Error> {
    sqlx::query_as(&query_tag!(
        "publish_claim",
        claim_sql(&tables.person_publish_outbox)
    ))
    .bind(limit)
    .fetch_all(&mut **tx)
    .await
}
