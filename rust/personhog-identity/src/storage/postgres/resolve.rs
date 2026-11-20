use std::collections::HashMap;

use chrono::{DateTime, Utc};
use common_sqlx_macros::mirrored_query_as;
use personhog_common::query_tag;
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
    // Postgres plans these statements again on every call, because a cached
    // generic plan cannot prune the person partitions and so always costs
    // more than a custom plan. A scalar team plans in a fraction of the time
    // of the `unnest` join, so only keys from several teams take the join.
    let rows = match keys {
        [] => return Ok(HashMap::new()),
        [(team_id, distinct_id)] => resolve_one(pools, tables, *team_id, distinct_id).await?,
        [(team_id, _), rest @ ..] if rest.iter().all(|(t, _)| t == team_id) => {
            resolve_in_team(pools, tables, *team_id, keys).await?
        }
        _ => resolve_across_teams(pools, tables, keys).await?,
    };

    let mut resolved = HashMap::with_capacity(rows.len());
    for row in rows {
        resolved.insert(
            (i64::from(row.key_team_id), row.key_distinct_id),
            Person {
                id: row.id,
                uuid: row.uuid,
                team_id: row.team_id,
                properties: None,
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

/// The subquery returns at most one row because `(team_id, distinct_id)` is
/// unique in both distinct id tables.
async fn resolve_one(
    pools: &IdentityPools,
    tables: &IdentityTables,
    team_id: i64,
    distinct_id: &str,
) -> StorageResult<Vec<ResolvedRow>> {
    let mut conn = pools.acquire(Lane::Fast).await?;
    let row = mirrored_query_as!(
        ResolvedRow,
        tables.is_validation(),
        op = "resolve_person",
        r#"
        SELECT $1::int AS "key_team_id!", $2::text AS "key_distinct_id!",
               p.id, p.uuid, p.team_id::bigint AS "team_id!", p.created_at, p.version,
               p.is_identified,
               CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END AS is_user_id,
               p.last_seen_at
        FROM {posthog_person|personhog_person_tmp} p
        WHERE p.team_id = $1
          AND p.id = (
              SELECT pdi.person_id
              FROM {posthog_persondistinctid|personhog_persondistinctid_tmp} pdi
              WHERE pdi.team_id = $1 AND pdi.distinct_id = $2 AND pdi.is_deleted = false
          )
          AND p.is_deleted = false
        "#,
        team_id as i32,
        distinct_id
        => fetch_optional(&mut *conn)
    )?;
    Ok(row.into_iter().collect())
}

async fn resolve_in_team(
    pools: &IdentityPools,
    tables: &IdentityTables,
    team_id: i64,
    keys: &[(i64, String)],
) -> StorageResult<Vec<ResolvedRow>> {
    let distinct_ids: Vec<String> = keys.iter().map(|(_, d)| d.clone()).collect();

    let mut conn = pools.acquire(Lane::Fast).await?;
    let rows = mirrored_query_as!(
        ResolvedRow,
        tables.is_validation(),
        op = "resolve_team_persons",
        r#"
        SELECT pdi.team_id AS "key_team_id!", pdi.distinct_id AS "key_distinct_id!",
               p.id, p.uuid, p.team_id::bigint AS "team_id!", p.created_at, p.version,
               p.is_identified,
               CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END AS is_user_id,
               p.last_seen_at
        FROM {posthog_persondistinctid|personhog_persondistinctid_tmp} pdi
        JOIN {posthog_person|personhog_person_tmp} p
          ON p.team_id = pdi.team_id AND p.id = pdi.person_id
        WHERE pdi.team_id = $1 AND pdi.distinct_id = ANY($2::text[]) AND pdi.is_deleted = false
          AND p.team_id = $1 AND p.is_deleted = false
        "#,
        team_id as i32,
        &distinct_ids
        => fetch_all(&mut *conn)
    )?;
    Ok(rows)
}

async fn resolve_across_teams(
    pools: &IdentityPools,
    tables: &IdentityTables,
    keys: &[(i64, String)],
) -> StorageResult<Vec<ResolvedRow>> {
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
    Ok(rows)
}

pub(super) async fn resolve_person_ids(
    pools: &IdentityPools,
    tables: &IdentityTables,
    keys: &[(i64, String)],
) -> StorageResult<HashMap<(i64, String), i64>> {
    if keys.is_empty() {
        return Ok(HashMap::new());
    }

    let team_ids: Vec<i32> = keys.iter().map(|(t, _)| *t as i32).collect();
    let distinct_ids: Vec<String> = keys.iter().map(|(_, d)| d.clone()).collect();

    let sql = format!(
        r#"
        SELECT k.team_id, k.distinct_id, pdi.person_id
        FROM unnest($1::int[], $2::text[]) AS k(team_id, distinct_id)
        JOIN {pdi_table} pdi
          ON pdi.team_id = k.team_id AND pdi.distinct_id = k.distinct_id
         AND pdi.is_deleted = false
        "#,
        pdi_table = tables.person_distinct_id,
    );
    let mut conn = pools.acquire(Lane::Fast).await?;
    let rows: Vec<(i32, String, i64)> = sqlx::query_as(&query_tag!("resolve_person_ids", sql))
        .bind(&team_ids)
        .bind(&distinct_ids)
        .fetch_all(&mut *conn)
        .await?;

    Ok(rows
        .into_iter()
        .map(|(team_id, distinct_id, person_id)| ((i64::from(team_id), distinct_id), person_id))
        .collect())
}
