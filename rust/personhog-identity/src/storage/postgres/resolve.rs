use std::collections::HashMap;

use sqlx::postgres::PgPool;

use crate::storage::error::StorageResult;
use crate::storage::types::Person;

/// Batch-resolve (team_id, distinct_id) keys to their live persons on the
/// primary. Tombstoned mappings and persons are invisible; unresolved keys
/// are absent from the result.
pub(super) async fn resolve_distinct_ids(
    pool: &PgPool,
    keys: &[(i64, String)],
) -> StorageResult<HashMap<(i64, String), Person>> {
    if keys.is_empty() {
        return Ok(HashMap::new());
    }

    let team_ids: Vec<i32> = keys.iter().map(|(t, _)| *t as i32).collect();
    let distinct_ids: Vec<String> = keys.iter().map(|(_, d)| d.clone()).collect();

    let rows = sqlx::query!(
        r#"
        SELECT k.team_id as "key_team_id!", k.distinct_id as "key_distinct_id!",
               p.id as "id!", p.uuid as "uuid!", p.team_id::bigint as "team_id!",
               p.properties::text as "properties?",
               p.properties_last_updated_at::text as "properties_last_updated_at?",
               p.properties_last_operation::text as "properties_last_operation?",
               p.created_at as "created_at!", p.version, p.is_identified as "is_identified!",
               CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END as is_user_id,
               p.last_seen_at
        FROM unnest($1::int[], $2::text[]) AS k(team_id, distinct_id)
        JOIN posthog_persondistinctid pdi
          ON pdi.team_id = k.team_id AND pdi.distinct_id = k.distinct_id
         AND pdi.is_deleted = false
        JOIN posthog_person p
          ON p.team_id = pdi.team_id AND p.id = pdi.person_id
         AND p.is_deleted = false
        "#,
        &team_ids,
        &distinct_ids
    )
    .fetch_all(pool)
    .await?;

    let mut resolved = HashMap::with_capacity(rows.len());
    for row in rows {
        resolved.insert(
            (i64::from(row.key_team_id), row.key_distinct_id),
            Person {
                id: row.id,
                uuid: row.uuid,
                team_id: row.team_id,
                properties: row.properties,
                properties_last_updated_at: row.properties_last_updated_at,
                properties_last_operation: row.properties_last_operation,
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
