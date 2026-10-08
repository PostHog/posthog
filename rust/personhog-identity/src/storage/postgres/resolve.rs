use std::collections::HashMap;

use chrono::{DateTime, Utc};
use common_sqlx_macros::mirrored_query_as;
use uuid::Uuid;

use crate::config::IdentityTables;
use crate::pools::{IdentityPools, Lane};
use crate::storage::error::StorageResult;
use crate::storage::types::Person;

struct ResolvedRow {
    key_team_id: i32,
    key_distinct_id: String,
    id: i64,
    uuid: Uuid,
    team_id: i64,
    created_at: DateTime<Utc>,
    version: Option<i64>,
    is_identified: bool,
    is_user_id: Option<bool>,
    last_seen_at: Option<DateTime<Utc>>,
}

/// Batch-resolve (team_id, distinct_id) keys to their live persons on the
/// primary. Tombstoned mappings and persons are invisible; unresolved keys
/// are absent from the result.
pub(super) async fn resolve_distinct_ids(
    pools: &IdentityPools,
    tables: &IdentityTables,
    keys: &[(i64, String)],
) -> StorageResult<HashMap<(i64, String), Person>> {
    if keys.is_empty() {
        return Ok(HashMap::new());
    }

    let team_ids: Vec<i32> = keys.iter().map(|(t, _)| *t as i32).collect();
    let distinct_ids: Vec<String> = keys.iter().map(|(_, d)| d.clone()).collect();

    let mut conn = pools.acquire(Lane::Fast).await?;
    let rows = mirrored_query_as!(
        ResolvedRow,
        tables.is_validation(),
        op = "resolve_persons",
        r#"
        SELECT k.team_id AS "key_team_id!", k.distinct_id AS "key_distinct_id!",
               p.id, p.uuid, p.team_id::bigint AS "team_id!", p.created_at, p.version,
               p.is_identified,
               CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END AS is_user_id,
               p.last_seen_at
        FROM unnest($1::int[], $2::text[]) AS k(team_id, distinct_id)
        JOIN {posthog_persondistinctid|personhog_persondistinctid_tmp} pdi
          ON pdi.team_id = k.team_id AND pdi.distinct_id = k.distinct_id
         AND pdi.is_deleted = false
        JOIN {posthog_person|personhog_person_tmp} p
          ON p.team_id = pdi.team_id AND p.id = pdi.person_id
         AND p.team_id = ANY($1::int[])
         AND p.is_deleted = false
        "#,
        &team_ids,
        &distinct_ids
        => fetch_all(&mut *conn)
    )?;

    let mut resolved = HashMap::with_capacity(rows.len());
    for row in rows {
        resolved.insert(
            (i64::from(row.key_team_id), row.key_distinct_id),
            Person {
                id: row.id,
                uuid: row.uuid,
                team_id: row.team_id,
                properties: None,
                properties_last_updated_at: None,
                properties_last_operation: None,
                created_at: row.created_at,
                version: row.version,
                is_identified: row.is_identified,
                is_user_id: row.is_user_id,
                last_seen_at: row.last_seen_at,
            },
        );
    }
    Ok(resolved)
}
