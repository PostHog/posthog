use anyhow::{bail, Context, Result};
use sqlx::postgres::PgPool;

/// Seed `count` persons for `team_id` directly in `table` and return their
/// ids, assigned by the table's own id default so they spread across
/// leader partitions exactly like organic ids.
///
/// Every harness mode operates on one configured table (the writer's
/// validation target by default) for seeding, verification, and cleanup
/// alike — `posthog_person` is deliberately not reachable from here.
///
/// There is no team to seed: the persons database has no team table and no
/// foreign key on `team_id` — a team exists here only as an integer value
/// on rows, so the first insert brings the harness team into existence and
/// a team-wide delete removes every trace of it.
///
/// This writes SQL instead of calling CreatePerson because the create RPC's
/// future is still being settled; this function is the seam where the RPC
/// swaps in.
pub async fn seed_persons(
    pool: &PgPool,
    table: &str,
    team_id: i64,
    count: u32,
) -> Result<Vec<i64>> {
    validate_table_name(table)?;
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;

    let ids: Vec<i64> = sqlx::query_scalar(&format!(
        r#"
        INSERT INTO {table} (
            team_id, uuid, properties, properties_last_updated_at,
            properties_last_operation, created_at, version, is_identified
        )
        SELECT $1, gen_random_uuid(), '{{}}'::jsonb, '{{}}'::jsonb, '{{}}'::jsonb, now(), 0, false
        FROM generate_series(1, $2)
        RETURNING id
        "#
    ))
    .bind(team)
    .bind(count as i32)
    .fetch_all(pool)
    .await
    .with_context(|| format!("seeding persons into {table}"))?;

    Ok(ids)
}

/// Delete all of `team_id`'s rows from `table`. The harness owns its team
/// ids outright, so a team-wide delete is the whole cleanup. Nothing
/// writes distinct-id rows today (traffic is id-keyed), so nothing cleans
/// them — that changes together when seeding grows a mechanism that
/// writes them.
pub async fn cleanup_team(pool: &PgPool, table: &str, team_id: i64) -> Result<u64> {
    validate_table_name(table)?;
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;
    let deleted = sqlx::query(&format!("DELETE FROM {table} WHERE team_id = $1"))
        .bind(team)
        .execute(pool)
        .await
        .with_context(|| format!("cleaning up {table}"))?
        .rows_affected();
    Ok(deleted)
}

/// The table name comes from the operator's CLI/env, but sanity-check it
/// anyway since it is interpolated into SQL (identifiers cannot be bound).
pub fn validate_table_name(table: &str) -> Result<()> {
    if table.is_empty() || !table.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        bail!("invalid table name: {table}");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::validate_table_name;

    #[test]
    fn validate_table_name_gates_what_reaches_sql_interpolation() {
        for ok in ["posthog_person", "personhog_person_tmp", "t1"] {
            assert!(validate_table_name(ok).is_ok(), "{ok} should be valid");
        }
        for bad in [
            "",
            "posthog_person; DROP TABLE posthog_person",
            "table-name",
            "table name",
            "table\"quoted",
        ] {
            assert!(
                validate_table_name(bad).is_err(),
                "{bad:?} should be rejected"
            );
        }
    }
}
