use sqlx::postgres::PgPool;
use sqlx::Row;

use crate::storage::error::StorageResult;
use crate::storage::types::DistinctIdMapping;

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
