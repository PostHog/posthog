use metrics::{counter, histogram};
use sqlx::postgres::PgPool;
use sqlx::Row;

use crate::cache::{CachedPerson, PersonCacheKey};

/// Reads a person from the main Postgres `posthog_person` table.
/// Used as a fallback when the leader's cache doesn't have the person.
pub async fn load_person_from_pg(
    pool: &PgPool,
    key: &PersonCacheKey,
) -> Result<Option<CachedPerson>, sqlx::Error> {
    let start = std::time::Instant::now();

    let team_id_i32 = i32::try_from(key.team_id)
        .map_err(|_| sqlx::Error::Protocol(format!("team_id {} exceeds i32 range", key.team_id)))?;

    let row = sqlx::query(
        "SELECT id, team_id, uuid::text, properties, created_at, version, is_identified
         FROM posthog_person
         WHERE team_id = $1 AND id = $2",
    )
    .bind(team_id_i32)
    .bind(key.person_id)
    .fetch_optional(pool)
    .await?;

    histogram!("personhog_leader_pg_fallback_duration_seconds")
        .record(start.elapsed().as_secs_f64());

    let Some(row) = row else {
        counter!("personhog_leader_pg_fallback_total", "outcome" => "not_found").increment(1);
        return Ok(None);
    };

    let id: i64 = row.get("id");
    let team_id: i32 = row.get("team_id");
    let uuid: String = row.get("uuid");
    let properties: serde_json::Value = row.get("properties");
    let created_at: chrono::DateTime<chrono::Utc> = row.get("created_at");
    let version: Option<i64> = row.get("version");
    let is_identified: bool = row.get("is_identified");

    counter!("personhog_leader_pg_fallback_total", "outcome" => "found").increment(1);

    Ok(Some(CachedPerson {
        id,
        uuid,
        team_id: team_id as i64,
        properties,
        created_at: created_at.timestamp(),
        version: version.unwrap_or(0),
        is_identified,
    }))
}
