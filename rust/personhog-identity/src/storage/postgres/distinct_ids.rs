use sqlx::postgres::PgPool;
use sqlx::Row;

use crate::config::IdentityTables;
use crate::storage::error::StorageResult;
use crate::storage::types::{DistinctIdMapping, DistinctIdPersonMapping};

/// Expand person ids to live distinct id rows on the primary. With a
/// per-person limit, identified ids survive the cut (the regex mirrors
/// ANONYMOUS_REGEX in posthog/utils.py) and the scan is capped for
/// pathological persons — the same ordering contract as the replica's
/// expansion, so callers can switch sources without behavior change.
pub(super) async fn get_distinct_ids_for_persons(
    pool: &PgPool,
    pdi_table: &str,
    team_id: i64,
    person_ids: &[i64],
    limit_per_person: Option<i64>,
) -> StorageResult<Vec<DistinctIdMapping>> {
    if person_ids.is_empty() {
        return Ok(Vec::new());
    }

    let rows = match limit_per_person {
        Some(limit) if limit > 0 => {
            let sql = format!(
                r#"
                SELECT l.person_id, l.distinct_id, l.version
                FROM UNNEST($2::bigint[]) AS pid(id)
                CROSS JOIN LATERAL (
                    SELECT capped.person_id, capped.distinct_id, capped.version
                    FROM (
                        SELECT person_id, distinct_id, version, id
                        FROM {pdi_table}
                        WHERE team_id = $1 AND person_id = pid.id AND is_deleted = false
                        LIMIT 2500
                    ) capped
                    ORDER BY (capped.distinct_id ~ '^([a-z0-9]+-){{4}}[a-z0-9]+$'), capped.id
                    LIMIT $3
                ) l
                "#
            );
            sqlx::query(&sql)
                .bind(team_id as i32)
                .bind(person_ids)
                .bind(limit)
                .fetch_all(pool)
                .await?
        }
        _ => {
            let sql = format!(
                r#"
                SELECT person_id, distinct_id, version
                FROM {pdi_table}
                WHERE team_id = $1 AND person_id = ANY($2) AND is_deleted = false
                "#
            );
            sqlx::query(&sql)
                .bind(team_id as i32)
                .bind(person_ids)
                .fetch_all(pool)
                .await?
        }
    };
    rows.into_iter()
        .map(|row| {
            Ok(DistinctIdMapping {
                person_id: row.try_get("person_id")?,
                distinct_id: row.try_get("distinct_id")?,
                version: row.try_get("version")?,
            })
        })
        .collect()
}

/// Live mapping rows for the given distinct ids on the primary, joined to
/// the person's uuid. Mappings to tombstoned persons are invisible, like
/// `resolve_distinct_ids`.
pub(super) async fn get_distinct_id_mappings(
    pool: &PgPool,
    tables: &IdentityTables,
    team_id: i64,
    distinct_ids: &[String],
) -> StorageResult<Vec<DistinctIdPersonMapping>> {
    if distinct_ids.is_empty() {
        return Ok(Vec::new());
    }

    let sql = format!(
        r#"
        SELECT pdi.distinct_id, pdi.version, p.uuid AS person_uuid
        FROM {pdi_table} pdi
        JOIN {person_table} p
          ON p.team_id = pdi.team_id AND p.id = pdi.person_id
         AND p.is_deleted = false
        WHERE pdi.team_id = $1 AND pdi.distinct_id = ANY($2) AND pdi.is_deleted = false
        "#,
        pdi_table = tables.person_distinct_id,
        person_table = tables.person,
    );
    let rows = sqlx::query(&sql)
        .bind(team_id as i32)
        .bind(distinct_ids)
        .fetch_all(pool)
        .await?;

    rows.into_iter()
        .map(|row| {
            Ok(DistinctIdPersonMapping {
                distinct_id: row.try_get("distinct_id")?,
                person_uuid: row.try_get("person_uuid")?,
                version: row.try_get("version")?,
            })
        })
        .collect()
}
