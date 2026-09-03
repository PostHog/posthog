//! Register `/flags` `person_properties` keys as person property definitions.
//!
//! `setPersonPropertiesForFlags` (and server-side `personProperties` overrides) evaluate flags
//! without ingesting a `$set` event, so those keys never appear in the release-condition picker.
//! A property definition is taxonomy metadata only — this writes no person profile values.

use common_database::Client as DatabaseClient;
use common_redis::Client as RedisClient;
use moka::sync::Cache;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::{Arc, OnceLock};
use std::time::Duration;
use tokio::sync::Semaphore;
use tracing::warn;
use uuid::Uuid;

use crate::metrics::consts::OVERRIDE_PROPERTY_DEF_WRITES_COUNTER;

#[cfg(test)]
use super::test_metrics::inc;
#[cfg(not(test))]
use common_metrics::inc;

/// `PropertyDefinition.Type.PERSON` in Django.
const PERSON_PROPERTY_TYPE: i16 = 2;

/// Person property definitions change rarely. One attempt per key per day is enough
/// to keep the picker current without adding steady-state write load.
pub const DEBOUNCE_TTL_SECONDS: u64 = 86_400;

/// Bounds the work a single request can trigger.
pub const MAX_KEYS_PER_REQUEST: usize = 25;

/// Caps concurrent background inserts so they cannot fill the writer pool.
const MAX_IN_FLIGHT_SPAWNS: usize = 32;

/// Matches the varchar(400) `name` column on `posthog_propertydefinition`.
const MAX_PROPERTY_NAME_LEN: usize = 400;

const LOCAL_CACHE_CAPACITY: u64 = 50_000;

pub fn debounce_key(project_id: i64, name: &str) -> String {
    format!("posthog:override_person_prop_def:{project_id}:{name}")
}

fn seen_override_keys() -> &'static Cache<(i64, String), ()> {
    static CACHE: OnceLock<Cache<(i64, String), ()>> = OnceLock::new();
    CACHE.get_or_init(|| {
        Cache::builder()
            .max_capacity(LOCAL_CACHE_CAPACITY)
            .time_to_live(Duration::from_secs(DEBOUNCE_TTL_SECONDS))
            .build()
    })
}

fn in_flight_spawns() -> &'static Semaphore {
    static SPAWNS: OnceLock<Semaphore> = OnceLock::new();
    SPAWNS.get_or_init(|| Semaphore::new(MAX_IN_FLIGHT_SPAWNS))
}

/// Spawn taxonomy writes without waiting for them on the `/flags` response.
///
/// Starts before evaluation; the task is detached so the request is not delayed.
/// `skip_writes` is the process-wide off switch (same gate as PAK last-used),
/// and also true when `OVERRIDE_PERSON_PROPERTY_DEFS=false`.
pub fn maybe_spawn_register_override_person_properties(
    skip_writes: bool,
    redis: Arc<dyn RedisClient + Send + Sync>,
    pg_writer: Arc<dyn DatabaseClient + Send + Sync>,
    team_id: i32,
    project_id: i64,
    person_properties: Option<&HashMap<String, Value>>,
) {
    if skip_writes {
        return;
    }
    let Some(person_properties) = person_properties else {
        return;
    };
    let names = eligible_override_property_names(person_properties.keys());
    if names.is_empty() {
        return;
    }
    let Ok(permit) = in_flight_spawns().try_acquire_owned() else {
        warn!("dropping override person property definition spawn; too many in flight");
        return;
    };
    tokio::spawn(async move {
        let _permit = permit;
        register_override_person_properties(redis, pg_writer, team_id, project_id, names).await;
    });
}

/// Keys that should become person property definitions.
///
/// `$`-prefixed names are reserved (GeoIP, `$lib`, cookieless, …) and already get
/// definitions from event ingestion, so they are skipped.
pub fn eligible_override_property_names<'a, I>(names: I) -> Vec<String>
where
    I: IntoIterator<Item = &'a String>,
{
    let mut out: Vec<String> = names
        .into_iter()
        .filter(|name| {
            !name.is_empty()
                && name.len() <= MAX_PROPERTY_NAME_LEN
                && !name.starts_with('$')
                && !name.contains('\0')
        })
        .cloned()
        .collect();
    out.sort();
    out.dedup();
    out.truncate(MAX_KEYS_PER_REQUEST);
    out
}

/// Registers request-time `person_properties` keys as person property definitions.
///
/// Best-effort and debounced. Each `(project, key)` is written at most once per
/// `DEBOUNCE_TTL_SECONDS` via an in-process cache and Redis `SET NX EX`. Meant to
/// run off the request path; a failure only skips a definition the next request
/// can retry.
pub async fn register_override_person_properties(
    redis: Arc<dyn RedisClient + Send + Sync>,
    pg_writer: Arc<dyn DatabaseClient + Send + Sync>,
    team_id: i32,
    project_id: i64,
    names: Vec<String>,
) {
    let mut candidates = Vec::new();
    let seen = seen_override_keys();
    for name in names {
        if name.is_empty()
            || name.len() > MAX_PROPERTY_NAME_LEN
            || name.starts_with('$')
            || name.contains('\0')
        {
            continue;
        }
        let cache_key = (project_id, name.clone());
        if seen.contains_key(&cache_key) {
            continue;
        }
        candidates.push(name);
    }

    if candidates.is_empty() {
        return;
    }

    let items: Vec<(String, String, usize)> = candidates
        .iter()
        .map(|name| {
            (
                debounce_key(project_id, name),
                "1".to_string(),
                DEBOUNCE_TTL_SECONDS as usize,
            )
        })
        .collect();

    let acquired = match redis.batch_set_nx_ex(items).await {
        Ok(flags) => flags,
        Err(e) => {
            warn!(
                error = %e,
                "Redis debounce check failed for override person property definition"
            );
            return;
        }
    };

    let mut to_write = Vec::new();
    for (name, won) in candidates.into_iter().zip(acquired) {
        let cache_key = (project_id, name.clone());
        seen.insert(cache_key, ());
        if won {
            to_write.push(name);
        }
    }

    if to_write.is_empty() {
        return;
    }

    if !insert_person_property_definitions(pg_writer, team_id, project_id, &to_write).await {
        let keys: Vec<String> = to_write
            .iter()
            .map(|name| debounce_key(project_id, name))
            .collect();
        if let Err(e) = redis.batch_del(keys).await {
            warn!(
                error = %e,
                "Failed to roll back Redis debounce after override person property definition insert error"
            );
        }
        for name in &to_write {
            seen.invalidate(&(project_id, name.clone()));
        }
    }
}

/// Inserts person property definitions for `names`, skipping any that already exist.
///
/// `ON CONFLICT DO NOTHING` means a real definition (with a resolved `property_type`)
/// or an earlier registration always wins; this never overwrites one. `property_type`
/// stays NULL until event ingestion resolves it.
pub async fn insert_person_property_definitions(
    pg_writer: Arc<dyn DatabaseClient + Send + Sync>,
    team_id: i32,
    project_id: i64,
    names: &[String],
) -> bool {
    let mut conn = match pg_writer.get_connection().await {
        Ok(conn) => conn,
        Err(e) => {
            inc(
                OVERRIDE_PROPERTY_DEF_WRITES_COUNTER,
                &[("result".to_string(), "error".to_string())],
                1,
            );
            warn!(
                team_id,
                error = %e,
                "Failed to acquire connection for override person property definitions"
            );
            return false;
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
            inc(
                OVERRIDE_PROPERTY_DEF_WRITES_COUNTER,
                &[("result".to_string(), "success".to_string())],
                1,
            );
            true
        }
        Err(e) => {
            inc(
                OVERRIDE_PROPERTY_DEF_WRITES_COUNTER,
                &[("result".to_string(), "error".to_string())],
                1,
            );
            warn!(
                team_id,
                error = %e,
                "Failed to write override person property definitions"
            );
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test_utils::TestContext;
    use common_redis::MockRedisClient;

    const PERSON_TYPE: i16 = 2;

    async fn count_person_definition(ctx: &TestContext, project_id: i64, name: &str) -> i64 {
        let mut conn = ctx.get_non_persons_connection().await.unwrap();
        let row: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM posthog_propertydefinition WHERE coalesce(project_id, team_id) = $1 AND name = $2 AND type = $3",
        )
        .bind(project_id)
        .bind(name)
        .bind(PERSON_TYPE)
        .fetch_one(&mut *conn)
        .await
        .unwrap();
        row.0
    }

    #[test]
    fn test_eligible_names_skip_reserved_empty_and_cap() {
        let too_long = "x".repeat(MAX_PROPERTY_NAME_LEN + 1);
        let names = vec![
            "$geoip_city_name".to_string(),
            "$lib".to_string(),
            "plan\0evil".to_string(),
            String::new(),
            too_long,
            "plan_tier".to_string(),
            "region".to_string(),
        ];
        assert_eq!(
            eligible_override_property_names(names.iter()),
            vec!["plan_tier".to_string(), "region".to_string()]
        );
    }

    #[test]
    fn test_eligible_names_cap_at_max_keys() {
        let names: Vec<String> = (0..(MAX_KEYS_PER_REQUEST + 5))
            .map(|i| format!("prop_{i:02}"))
            .collect();
        let got = eligible_override_property_names(names.iter());
        let mut expected = names;
        expected.sort();
        expected.truncate(MAX_KEYS_PER_REQUEST);
        assert_eq!(got, expected);
    }

    #[tokio::test]
    async fn test_insert_creates_person_definition() {
        let ctx = TestContext::new(None).await;
        let team = ctx.insert_new_team(None).await.unwrap();
        let project_id = i64::from(team.id);
        let name = format!("plan_tier_{}", team.id);

        insert_person_property_definitions(
            ctx.non_persons_writer.clone(),
            team.id,
            project_id,
            std::slice::from_ref(&name),
        )
        .await;

        assert_eq!(count_person_definition(&ctx, project_id, &name).await, 1);

        let mut conn = ctx.get_non_persons_connection().await.unwrap();
        let row: (Option<String>,) = sqlx::query_as(
            "SELECT property_type FROM posthog_propertydefinition WHERE team_id = $1 AND name = $2 AND type = $3",
        )
        .bind(team.id)
        .bind(&name)
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
        let project_id = i64::from(team.id);
        let name = format!("plan_tier_idempotent_{}", team.id);

        for _ in 0..2 {
            insert_person_property_definitions(
                ctx.non_persons_writer.clone(),
                team.id,
                project_id,
                std::slice::from_ref(&name),
            )
            .await;
        }

        assert_eq!(count_person_definition(&ctx, project_id, &name).await, 1);
    }

    #[tokio::test]
    async fn test_register_writes_new_keys_and_skips_reserved() {
        let ctx = TestContext::new(None).await;
        let team = ctx.insert_new_team(None).await.unwrap();
        let project_id = i64::from(team.id);
        let plan = format!("plan_tier_reg_{}", team.id);
        let region = format!("region_reg_{}", team.id);

        let redis: Arc<dyn RedisClient + Send + Sync> = Arc::new(
            MockRedisClient::new()
                .set_nx_ex_ret(&debounce_key(project_id, &plan), Ok(true))
                .set_nx_ex_ret(&debounce_key(project_id, &region), Ok(true)),
        );

        register_override_person_properties(
            redis,
            ctx.non_persons_writer.clone(),
            team.id,
            project_id,
            vec![
                plan.clone(),
                region.clone(),
                "$geoip_city_name".to_string(),
                "plan\0evil".to_string(),
            ],
        )
        .await;

        assert_eq!(count_person_definition(&ctx, project_id, &plan).await, 1);
        assert_eq!(count_person_definition(&ctx, project_id, &region).await, 1);
        assert_eq!(
            count_person_definition(&ctx, project_id, "$geoip_city_name").await,
            0
        );
    }

    #[tokio::test]
    async fn test_register_skips_debounced_keys() {
        let ctx = TestContext::new(None).await;
        let team = ctx.insert_new_team(None).await.unwrap();
        let project_id = i64::from(team.id);
        let name = format!("plan_tier_debounced_{}", team.id);

        let redis: Arc<dyn RedisClient + Send + Sync> = Arc::new(
            MockRedisClient::new().set_nx_ex_ret(&debounce_key(project_id, &name), Ok(false)),
        );

        register_override_person_properties(
            redis,
            ctx.non_persons_writer.clone(),
            team.id,
            project_id,
            vec![name.clone()],
        )
        .await;

        assert_eq!(count_person_definition(&ctx, project_id, &name).await, 0);
    }

    #[tokio::test]
    async fn test_register_uses_local_cache_to_skip_redis_on_repeat() {
        let ctx = TestContext::new(None).await;
        let team = ctx.insert_new_team(None).await.unwrap();
        let project_id = i64::from(team.id);
        let name = format!("plan_tier_local_{}", team.id);
        let key = debounce_key(project_id, &name);

        let mock = MockRedisClient::new().set_nx_ex_ret(&key, Ok(true));
        let redis: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock.clone());

        register_override_person_properties(
            redis.clone(),
            ctx.non_persons_writer.clone(),
            team.id,
            project_id,
            vec![name.clone()],
        )
        .await;
        register_override_person_properties(
            redis,
            ctx.non_persons_writer.clone(),
            team.id,
            project_id,
            vec![name.clone()],
        )
        .await;

        let redis_calls = mock
            .get_calls()
            .into_iter()
            .filter(|call| call.op == "batch_set_nx_ex")
            .count();
        assert_eq!(redis_calls, 1);
        assert_eq!(count_person_definition(&ctx, project_id, &name).await, 1);
    }

    #[tokio::test]
    async fn test_insert_scopes_on_project_id() {
        let ctx = TestContext::new(None).await;
        let team = ctx.insert_new_team(None).await.unwrap();
        let other = ctx.insert_new_team(None).await.unwrap();
        let project_id = i64::from(other.id);
        let name = format!("plan_tier_project_{}", team.id);

        insert_person_property_definitions(
            ctx.non_persons_writer.clone(),
            team.id,
            project_id,
            std::slice::from_ref(&name),
        )
        .await;

        assert_eq!(count_person_definition(&ctx, project_id, &name).await, 1);
        assert_eq!(
            count_person_definition(&ctx, i64::from(team.id), &name).await,
            0
        );
    }

    #[tokio::test]
    async fn test_register_retries_after_redis_error() {
        let ctx = TestContext::new(None).await;
        let team = ctx.insert_new_team(None).await.unwrap();
        let project_id = i64::from(team.id);
        let name = format!("plan_tier_redis_err_{}", team.id);
        let key = debounce_key(project_id, &name);

        let mock = MockRedisClient::new()
            .set_nx_ex_ret(&key, Err(common_redis::CustomRedisError::Timeout));
        let redis: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock.clone());

        register_override_person_properties(
            redis.clone(),
            ctx.non_persons_writer.clone(),
            team.id,
            project_id,
            vec![name.clone()],
        )
        .await;
        assert_eq!(count_person_definition(&ctx, project_id, &name).await, 0);

        let mock = MockRedisClient::new().set_nx_ex_ret(&key, Ok(true));
        let redis: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock.clone());
        register_override_person_properties(
            redis,
            ctx.non_persons_writer.clone(),
            team.id,
            project_id,
            vec![name.clone()],
        )
        .await;
        assert_eq!(count_person_definition(&ctx, project_id, &name).await, 1);
        assert_eq!(
            mock.get_calls()
                .into_iter()
                .filter(|call| call.op == "batch_set_nx_ex")
                .count(),
            1
        );
    }
}
