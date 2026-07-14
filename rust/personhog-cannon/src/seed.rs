use anyhow::{Context, Result};
use sqlx::postgres::PgPool;

/// Seed `count` persons for `team_id` directly in Postgres and return their
/// ids. Ids come from the production sequence so they are unique against
/// real data and spread across leader partitions exactly like organic ids.
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

/// Delete all persons (and any distinct-id rows) for `team_id`. The harness
/// owns its team ids outright, so a team-wide delete is the whole cleanup.
pub async fn cleanup_team(pool: &PgPool, team_id: i64) -> Result<(u64, u64)> {
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;

    let pdis = sqlx::query("DELETE FROM posthog_persondistinctid WHERE team_id = $1")
        .bind(team)
        .execute(pool)
        .await
        .context("deleting distinct ids")?
        .rows_affected();

    let persons = sqlx::query("DELETE FROM posthog_person WHERE team_id = $1")
        .bind(team)
        .execute(pool)
        .await
        .context("deleting persons")?
        .rows_affected();

    Ok((persons, pdis))
}
