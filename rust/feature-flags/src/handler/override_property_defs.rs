use common_database::Client as DatabaseClient;
use common_redis::Client as RedisClient;
use std::sync::Arc;
use tracing::warn;
use uuid::Uuid;

use crate::metrics::consts::OVERRIDE_PROPERTY_DEF_WRITES_COUNTER;

// `type` value for a person property definition (PropertyDefinition.Type.PERSON in Django).
const PERSON_PROPERTY_TYPE: i16 = 2;

// Person property definitions change rarely, so one write per key per day keeps the
// release-condition picker current without adding steady-state write load.
pub const DEBOUNCE_TTL_SECONDS: u64 = 86_400;

// Bounds the work a single request can trigger. Real override payloads carry a handful of keys.
pub const MAX_KEYS_PER_REQUEST: usize = 25;

// Matches the varchar(400) `name` column on posthog_propertydefinition.
const MAX_PROPERTY_NAME_LEN: usize = 400;

pub fn debounce_key(project_id: i64, name: &str) -> String {
    format!("posthog:override_person_prop_def:{project_id}:{name}")
}

/// Registers request-time `personProperties` override keys as person property definitions, so they
/// become selectable in the flag release-condition picker. Writes no value to any person profile:
/// a property definition is taxonomy metadata only.
///
/// Best-effort and debounced. Each (project, key) is written at most once per
/// `DEBOUNCE_TTL_SECONDS` via Redis `SET NX EX`. Meant to run off the request path; a failure only
/// skips a definition that the next request re-attempts.
pub async fn register_override_person_properties(
    redis: Arc<dyn RedisClient + Send + Sync>,
    pg_writer: Arc<dyn DatabaseClient + Send + Sync>,
    team_id: i32,
    project_id: i64,
    names: Vec<String>,
) {
    let mut to_write = Vec::new();
    for name in names.into_iter().take(MAX_KEYS_PER_REQUEST) {
        // `$`-prefixed keys are reserved (GeoIP, cookieless, and other internal properties) and
        // already get definitions from event ingestion, so only user-defined keys need registering.
        if name.is_empty() || name.len() > MAX_PROPERTY_NAME_LEN || name.starts_with('$') {
            continue;
        }
        match redis
            .set_nx_ex(
                debounce_key(project_id, &name),
                "1".to_string(),
                DEBOUNCE_TTL_SECONDS,
            )
            .await
        {
            Ok(true) => to_write.push(name),
            Ok(false) => {}
            Err(e) => {
                warn!(error = %e, "Redis debounce check failed for override person property definition")
            }
        }
    }

    if to_write.is_empty() {
        return;
    }

    insert_person_property_definitions(pg_writer, team_id, project_id, &to_write).await;
}

/// Inserts person property definitions for `names`, skipping any that already exist.
///
/// `ON CONFLICT DO NOTHING` means a real definition (with a resolved `property_type`) or an earlier
/// registration always wins; this never overwrites one. `property_type` stays NULL until event
/// ingestion resolves it.
pub async fn insert_person_property_definitions(
    pg_writer: Arc<dyn DatabaseClient + Send + Sync>,
    team_id: i32,
    project_id: i64,
    names: &[String],
) {
    let mut conn = match pg_writer.get_connection().await {
        Ok(conn) => conn,
        Err(e) => {
            warn!(team_id, error = %e, "Failed to acquire connection for override person property definitions");
            return;
        }
    };

    let ids: Vec<Uuid> = names.iter().map(|_| Uuid::now_v7()).collect();

    let result = sqlx::query(
        r#"
        INSERT INTO posthog_propertydefinition (id, name, type, group_type_index, is_numerical, team_id, project_id)
            SELECT DISTINCT ON (name) id, name, $3::smallint, NULL::smallint, false, $4::int, $5::bigint
            FROM UNNEST($1::uuid[], $2::varchar[]) AS t(id, name)
            ORDER BY name
            ON CONFLICT DO NOTHING
        "#,
    )
    .bind(&ids)
    .bind(names)
    .bind(PERSON_PROPERTY_TYPE)
    .bind(team_id)
    .bind(project_id)
    .execute(&mut *conn)
    .await;

    match result {
        Ok(_) => {
            metrics::counter!(
                OVERRIDE_PROPERTY_DEF_WRITES_COUNTER,
                &[("result", "success")]
            )
            .increment(1);
        }
        Err(e) => {
            metrics::counter!(OVERRIDE_PROPERTY_DEF_WRITES_COUNTER, &[("result", "error")])
                .increment(1);
            warn!(team_id, error = %e, "Failed to write override person property definitions");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test_utils::TestContext;
    use common_redis::MockRedisClient;

    // PropertyDefinition.Type.PERSON
    const PERSON_TYPE: i16 = 2;

    async fn count_person_definition(ctx: &TestContext, team_id: i32, name: &str) -> i64 {
        let mut conn = ctx.get_non_persons_connection().await.unwrap();
        let row: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM posthog_propertydefinition WHERE team_id = $1 AND name = $2 AND type = $3",
        )
        .bind(team_id)
        .bind(name)
        .bind(PERSON_TYPE)
        .fetch_one(&mut *conn)
        .await
        .unwrap();
        row.0
    }

    #[tokio::test]
    async fn test_insert_creates_person_definition() {
        let ctx = TestContext::new(None).await;
        let team = ctx.insert_new_team(None).await.unwrap();
        let project_id = team.id as i64;

        insert_person_property_definitions(
            ctx.non_persons_writer.clone(),
            team.id,
            project_id,
            &["plan_tier".to_string()],
        )
        .await;

        assert_eq!(count_person_definition(&ctx, team.id, "plan_tier").await, 1);

        // property_type stays NULL until ingestion resolves it, and no person row is written.
        let mut conn = ctx.get_non_persons_connection().await.unwrap();
        let row: (Option<String>,) = sqlx::query_as(
            "SELECT property_type FROM posthog_propertydefinition WHERE team_id = $1 AND name = $2 AND type = $3",
        )
        .bind(team.id)
        .bind("plan_tier")
        .bind(PERSON_TYPE)
        .fetch_one(&mut *conn)
        .await
        .unwrap();
        assert_eq!(row.0, None);
    }

    #[tokio::test]
    async fn test_insert_is_idempotent() {
        let ctx = TestContext::new(None).await;
        let team = ctx.insert_new_team(None).await.unwrap();
        let project_id = team.id as i64;

        for _ in 0..2 {
            insert_person_property_definitions(
                ctx.non_persons_writer.clone(),
                team.id,
                project_id,
                &["plan_tier".to_string()],
            )
            .await;
        }

        assert_eq!(count_person_definition(&ctx, team.id, "plan_tier").await, 1);
    }

    #[tokio::test]
    async fn test_register_writes_new_keys_and_skips_reserved() {
        let ctx = TestContext::new(None).await;
        let team = ctx.insert_new_team(None).await.unwrap();
        let project_id = team.id as i64;

        let redis: Arc<dyn RedisClient + Send + Sync> = Arc::new(
            MockRedisClient::new()
                .set_nx_ex_ret(&debounce_key(project_id, "plan_tier"), Ok(true))
                .set_nx_ex_ret(&debounce_key(project_id, "region"), Ok(true)),
        );

        register_override_person_properties(
            redis,
            ctx.non_persons_writer.clone(),
            team.id,
            project_id,
            vec![
                "plan_tier".to_string(),
                "region".to_string(),
                // Reserved keys are filtered before the Redis debounce, so they never reach the DB.
                "$geoip_city_name".to_string(),
            ],
        )
        .await;

        assert_eq!(count_person_definition(&ctx, team.id, "plan_tier").await, 1);
        assert_eq!(count_person_definition(&ctx, team.id, "region").await, 1);
        assert_eq!(
            count_person_definition(&ctx, team.id, "$geoip_city_name").await,
            0
        );
    }

    #[tokio::test]
    async fn test_register_skips_debounced_keys() {
        let ctx = TestContext::new(None).await;
        let team = ctx.insert_new_team(None).await.unwrap();
        let project_id = team.id as i64;

        // A debounce key that already exists returns false, so the key is not written.
        let redis: Arc<dyn RedisClient + Send + Sync> = Arc::new(
            MockRedisClient::new().set_nx_ex_ret(&debounce_key(project_id, "plan_tier"), Ok(false)),
        );

        register_override_person_properties(
            redis,
            ctx.non_persons_writer.clone(),
            team.id,
            project_id,
            vec!["plan_tier".to_string()],
        )
        .await;

        assert_eq!(count_person_definition(&ctx, team.id, "plan_tier").await, 0);
    }
}
