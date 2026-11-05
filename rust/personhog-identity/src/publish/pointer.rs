//! Resolving an op pointer against the saga's own records. A merge or
//! delete op records every repointed or tombstoned mapping in
//! `lifecycle_op_person.moved` in the same commit that moved it, so the
//! pointer carries nothing but the op id and a keyset cursor over those
//! records.
//!
//! Only `source` (merge) and `victim` (delete) rows hold mappings. A merge
//! target's `moved` holds the per-distinct-id claim dispositions, an
//! object, and must never be read as repoints.

use chrono::{DateTime, Utc};
use common_sqlx_macros::{mirrored_query_as, mirrored_query_scalar};
use serde_json::Value;
use uuid::Uuid;

use crate::config::IdentityTables;
use crate::lifecycle::engine::Tx;

/// The last `(person_id, mapping ordinal)` already published for a
/// pointer. `(0, 0)` is before every row: person ids are positive and
/// ordinality starts at 1. `moved` never changes after its commit, so the
/// order is stable across claims.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Cursor {
    pub person_id: i64,
    pub mapping_ordinal: i64,
}

impl Cursor {
    pub const START: Cursor = Cursor {
        person_id: 0,
        mapping_ordinal: 0,
    };
}

#[derive(Debug, Clone)]
pub struct PointerOp {
    pub op_type: String,
    pub completed_at: Option<DateTime<Utc>>,
    /// Rows with `role = 'target'`. A merge has exactly one; more would
    /// fan the resolution join out and repeat every source entry under
    /// the same cursor key.
    pub target_rows: i64,
    /// The target row's uuid: the `new_person_uuid` of a merge event.
    pub target_uuid: Option<Uuid>,
    /// Source or victim rows whose `moved` is not a JSON array. The
    /// resolution query skips them, so a count above zero is the only way
    /// to see the corruption instead of silently publishing nothing.
    pub malformed_moved_rows: i64,
}

/// A pointer's op row, or `None` when the op is gone, which GC must never
/// cause while the pointer exists and is therefore corrupt state.
pub async fn load_op(
    tx: &mut Tx<'_>,
    tables: &IdentityTables,
    op_id: Uuid,
) -> Result<Option<PointerOp>, sqlx::Error> {
    mirrored_query_as!(
        PointerOp,
        tables.is_validation(),
        op = "publish_load_op",
        r#"
        SELECT op.op_type, op.completed_at,
               (SELECT count(*) FROM {lifecycle_op_person} lop
                WHERE lop.op_id = op.op_id AND lop.role = 'target') AS "target_rows!",
               (SELECT lop.person_uuid FROM {lifecycle_op_person} lop
                WHERE lop.op_id = op.op_id AND lop.role = 'target'
                ORDER BY lop.person_id LIMIT 1) AS target_uuid,
               (SELECT count(*) FROM {lifecycle_op_person} lop
                WHERE lop.op_id = op.op_id
                  AND lop.role IN ('source', 'victim')
                  AND lop.moved IS NOT NULL
                  AND jsonb_typeof(lop.moved) <> 'array') AS "malformed_moved_rows!"
        FROM {lifecycle_op} op
        WHERE op.op_id = $1
        "#,
        op_id
        => fetch_optional(&mut **tx)
    )
}

/// The recorded outcome's `results` array, which names the merged sources
/// a merge event is owed for. Read apart from [`load_op`] and only on the
/// chunk that produces the events: the outcome carries the survivor
/// document, and even a subfield read detoasts the whole datum.
pub async fn load_outcome_results(
    tx: &mut Tx<'_>,
    tables: &IdentityTables,
    op_id: Uuid,
) -> Result<Option<Value>, sqlx::Error> {
    let results: Option<Option<Value>> = mirrored_query_scalar!(
        tables.is_validation(),
        op = "publish_load_outcome_results",
        r#"SELECT outcome -> 'results' AS "results: Value" FROM {lifecycle_op} WHERE op_id = $1"#,
        op_id
        => fetch_optional(&mut **tx)
    )?;
    Ok(results.flatten())
}

/// One `moved` entry, positioned for the cursor. The payload columns are
/// nullable on purpose: the query extracts them without casting anything
/// that could raise, so a malformed entry reaches Rust as `None` and gives
/// the pointer up instead of aborting the claim transaction.
#[derive(Debug, Clone)]
pub struct ResolvedRow {
    pub person_id: i64,
    pub mapping_ordinal: i64,
    pub owner_uuid: Option<Uuid>,
    pub distinct_id: Option<String>,
    pub version: Option<i64>,
    pub is_deleted: bool,
}

impl ResolvedRow {
    pub fn cursor(&self) -> Cursor {
        Cursor {
            person_id: self.person_id,
            mapping_ordinal: self.mapping_ordinal,
        }
    }
}

/// The next `limit` moved entries after `cursor`, in `(person_id, element
/// ordinal)` order. A repointed mapping's owner is the merge target's uuid;
/// a tombstoned mapping keeps its victim's uuid and is flagged deleted.
///
/// Nothing in this statement can raise on data. `distinct_id` is taken
/// only from a JSON string, `version` only from a JSON number that is an
/// integer inside the `bigint` range (checked as `numeric`, which holds
/// any JSON number, because a decimal or an out-of-range number would fail
/// the `bigint` cast), and persons before the cursor are not expanded at
/// all, so a large op does not pay for its finished persons on every
/// chunk.
pub async fn resolve_chunk(
    tx: &mut Tx<'_>,
    tables: &IdentityTables,
    op_id: Uuid,
    cursor: Cursor,
    limit: i64,
) -> Result<Vec<ResolvedRow>, sqlx::Error> {
    mirrored_query_as!(
        ResolvedRow,
        tables.is_validation(),
        op = "publish_resolve_pointer",
        r#"
        WITH moved_rows AS (
            SELECT lop.person_id, lop.role, lop.person_uuid,
                   CASE WHEN jsonb_typeof(e.value -> 'distinct_id') = 'string'
                        THEN e.value ->> 'distinct_id' END AS distinct_id,
                   CASE WHEN jsonb_typeof(e.value -> 'version') = 'number'
                         AND (e.value ->> 'version')::numeric = trunc((e.value ->> 'version')::numeric)
                         AND (e.value ->> 'version')::numeric BETWEEN -9223372036854775808 AND 9223372036854775807
                        THEN (e.value ->> 'version')::bigint END AS version,
                   e.ordinality AS mapping_ordinal
            FROM {lifecycle_op_person} lop
            CROSS JOIN LATERAL jsonb_array_elements(lop.moved) WITH ORDINALITY AS e(value, ordinality)
            WHERE lop.op_id = $1
              AND lop.role IN ('source', 'victim')
              AND lop.moved IS NOT NULL
              AND jsonb_typeof(lop.moved) = 'array'
              AND lop.person_id >= $2
        )
        SELECT m.person_id AS "person_id!",
               m.mapping_ordinal AS "mapping_ordinal!",
               CASE m.role WHEN 'victim' THEN m.person_uuid ELSE t.person_uuid END AS owner_uuid,
               m.distinct_id,
               m.version,
               (m.role = 'victim') AS "is_deleted!"
        FROM moved_rows m
        LEFT JOIN {lifecycle_op_person} t ON t.op_id = $1 AND t.role = 'target'
        WHERE (m.person_id, m.mapping_ordinal) > ($2, $3)
        ORDER BY m.person_id, m.mapping_ordinal
        LIMIT $4
        "#,
        op_id,
        cursor.person_id,
        cursor.mapping_ordinal,
        limit
        => fetch_all(&mut **tx)
    )
}

/// A source person a merge op deleted: the `old_person_uuid` of one merge
/// event. The primary key `(op_id, person_id)` holds one row per source
/// person however many of its distinct ids the request named, which is how
/// one event per merged person falls out.
#[derive(Debug, Clone)]
pub struct MergedSource {
    pub person_id: i64,
    pub person_uuid: Uuid,
}

pub async fn merged_sources(
    tx: &mut Tx<'_>,
    tables: &IdentityTables,
    op_id: Uuid,
) -> Result<Vec<MergedSource>, sqlx::Error> {
    mirrored_query_as!(
        MergedSource,
        tables.is_validation(),
        op = "publish_merged_sources",
        r#"
        SELECT person_id, person_uuid FROM {lifecycle_op_person}
        WHERE op_id = $1 AND role = 'source' AND status = 'deleted'
        ORDER BY person_id
        "#,
        op_id
        => fetch_all(&mut **tx)
    )
}

/// Pending and given-up rows, and the age of the oldest pending one, for
/// the gauges. The age is one index probe and is measured on the database
/// clock, so a skewed publisher clock cannot fake or hide lag; it is the
/// alerting signal. The counts scan at most `GAUGE_SCAN_CAP` rows and
/// saturate there, so a backlog of millions does not turn every refresh
/// into a full scan.
pub struct OutboxDepth {
    pub pending: i64,
    pub given_up: i64,
    pub lag_seconds: f64,
}

pub const GAUGE_SCAN_CAP: i64 = 1_000_000;

pub async fn outbox_depth(
    pool: &sqlx::PgPool,
    tables: &IdentityTables,
) -> Result<OutboxDepth, sqlx::Error> {
    let counts = mirrored_query_as!(
        Counts,
        tables.is_validation(),
        op = "publish_outbox_counts",
        r#"
        SELECT count(*) FILTER (WHERE given_up_at IS NULL) AS "pending!",
               count(*) FILTER (WHERE given_up_at IS NOT NULL) AS "given_up!"
        FROM (SELECT given_up_at FROM {person_publish_outbox} LIMIT $1) AS scanned
        "#,
        GAUGE_SCAN_CAP
        => fetch_one(pool)
    )?;
    let lag_seconds = mirrored_query_scalar!(
        tables.is_validation(),
        op = "publish_outbox_oldest",
        r#"
        SELECT EXTRACT(EPOCH FROM now() - created_at)::float8 AS "lag_seconds!"
        FROM {person_publish_outbox}
        WHERE given_up_at IS NULL ORDER BY id LIMIT 1
        "#
        => fetch_optional(pool)
    )?;
    Ok(OutboxDepth {
        pending: counts.pending,
        given_up: counts.given_up,
        lag_seconds: lag_seconds.unwrap_or(0.0).max(0.0),
    })
}

struct Counts {
    pending: i64,
    given_up: i64,
}
