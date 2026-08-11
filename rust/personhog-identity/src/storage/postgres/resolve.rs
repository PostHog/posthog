use std::collections::HashMap;

use sqlx::postgres::PgPool;
use sqlx::Row;

use crate::config::IdentityTables;
use crate::storage::error::StorageResult;
use crate::storage::postgres::{person_columns, person_from_row};
use crate::storage::types::Person;

/// Batch-resolve (team_id, distinct_id) keys to their live persons on the
/// primary. Tombstoned mappings and persons are invisible; unresolved keys
/// are absent from the result.
pub(super) async fn resolve_distinct_ids(
    pool: &PgPool,
    tables: &IdentityTables,
    keys: &[(i64, String)],
) -> StorageResult<HashMap<(i64, String), Person>> {
    if keys.is_empty() {
        return Ok(HashMap::new());
    }

    let team_ids: Vec<i32> = keys.iter().map(|(t, _)| *t as i32).collect();
    let distinct_ids: Vec<String> = keys.iter().map(|(_, d)| d.clone()).collect();

    let sql = format!(
        r#"
        SELECT k.team_id AS key_team_id, k.distinct_id AS key_distinct_id,
               {person_cols}
        FROM unnest($1::int[], $2::text[]) AS k(team_id, distinct_id)
        JOIN {pdi_table} pdi
          ON pdi.team_id = k.team_id AND pdi.distinct_id = k.distinct_id
         AND pdi.is_deleted = false
        JOIN {person_table} p
          ON p.team_id = pdi.team_id AND p.id = pdi.person_id
         AND p.is_deleted = false
        "#,
        person_cols = person_columns("p"),
        pdi_table = tables.person_distinct_id,
        person_table = tables.person,
    );
    let rows = sqlx::query(&sql)
        .bind(&team_ids)
        .bind(&distinct_ids)
        .fetch_all(pool)
        .await?;

    let mut resolved = HashMap::with_capacity(rows.len());
    for row in rows {
        let key_team_id: i32 = row.try_get("key_team_id")?;
        let key_distinct_id: String = row.try_get("key_distinct_id")?;
        resolved.insert(
            (i64::from(key_team_id), key_distinct_id),
            person_from_row(&row)?,
        );
    }
    Ok(resolved)
}
