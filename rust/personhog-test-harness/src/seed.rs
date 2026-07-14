use anyhow::{bail, Context, Result};
use sqlx::postgres::PgPool;

/// Seed `count` persons for `team_id` directly in Postgres and return their
/// ids. Ids come from the production sequence so they are unique against
/// real data and spread across leader partitions exactly like organic ids.
///
/// There is no team to seed: the persons database has no team table and no
/// foreign key on `team_id` — a team exists here only as an integer value
/// on rows, so the first insert brings the harness team into existence and
/// a team-wide delete removes every trace of it.
///
/// This writes SQL instead of calling CreatePerson because the create RPC's
/// future is still being settled; this function is the seam where the RPC
/// swaps in.
pub async fn seed_persons(pool: &PgPool, team_id: i64, count: u32) -> Result<Vec<i64>> {
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;

    let ids: Vec<i64> =
        sqlx::query_scalar("SELECT nextval('posthog_person_id_seq') FROM generate_series(1, $1)")
            .bind(count as i32)
            .fetch_all(pool)
            .await
            .context("allocating person ids")?;

    let teams: Vec<i32> = vec![team; ids.len()];
    let uuids: Vec<String> = ids
        .iter()
        .map(|_| uuid::Uuid::new_v4().to_string())
        .collect();

    sqlx::query(
        r#"
        INSERT INTO posthog_person (
            id, team_id, uuid, properties, properties_last_updated_at,
            properties_last_operation, created_at, version, is_identified
        )
        SELECT id, team_id, uuid::uuid, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, now(), 0, false
        FROM UNNEST($1::bigint[], $2::int[], $3::text[]) AS u(id, team_id, uuid)
        "#,
    )
    .bind(&ids)
    .bind(&teams)
    .bind(&uuids)
    .execute(pool)
    .await
    .context("inserting seed persons")?;

    Ok(ids)
}

/// Delete a team's rows from a writer target table other than
/// posthog_person (e.g. the dev stack's personhog_person_tmp validation
/// table). The table name comes from the operator's CLI, but sanity-check
/// it anyway since it is interpolated into SQL.
pub async fn cleanup_target_table(pool: &PgPool, table: &str, team_id: i64) -> Result<u64> {
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

pub fn validate_table_name(table: &str) -> Result<()> {
    if table.is_empty() || !table.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        bail!("invalid table name: {table}");
    }
    Ok(())
}

/// Delete all persons for `team_id`. The harness owns its team ids
/// outright, so a team-wide delete is the whole cleanup. Nothing writes
/// distinct-id rows today (traffic is id-keyed), so nothing cleans them —
/// that changes together when seeding grows a mechanism that writes them.
pub async fn cleanup_team(pool: &PgPool, team_id: i64) -> Result<u64> {
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;

    let persons = sqlx::query("DELETE FROM posthog_person WHERE team_id = $1")
        .bind(team)
        .execute(pool)
        .await
        .context("deleting persons")?
        .rows_affected();

    Ok(persons)
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
