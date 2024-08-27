use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tracing::instrument;

use crate::{api::FlagError, database::Client as DatabaseClient, redis::Client as RedisClient};

// TRICKY: This cache data is coming from django-redis. If it ever goes out of sync, we'll bork.
// TODO: Add integration tests across repos to ensure this doesn't happen.
pub const TEAM_TOKEN_CACHE_PREFIX: &str = "posthog:1:team_token:";

#[derive(Clone, Debug, Deserialize, Serialize, sqlx::FromRow)]
pub struct Team {
    pub id: i32,
    pub name: String,
    pub api_token: String,
    // TODO: the following fields are used for the `/decide` response,
    // but they're not used for flags and they don't live in redis.
    // At some point I'll need to differentiate between teams in Redis and teams
    // with additional fields in Postgres, since the Postgres team is a superset of the fields
    // we use for flags, anyway.
    // pub surveys_opt_in: bool,
    // pub heatmaps_opt_in: bool,
    // pub capture_performance_opt_in: bool,
    // pub autocapture_web_vitals_opt_in: bool,
    // pub autocapture_opt_out: bool,
    // pub autocapture_exceptions_opt_in: bool,
}

impl Team {
    /// Validates a token, and returns a team if it exists.

    #[instrument(skip_all)]
    pub async fn from_redis(
        client: Arc<dyn RedisClient + Send + Sync>,
        token: String,
    ) -> Result<Team, FlagError> {
        // NB: if this lookup fails, we fall back to the database before returning an error
        let serialized_team = client
            .get(format!("{TEAM_TOKEN_CACHE_PREFIX}{}", token))
            .await?;

        // TODO: Consider an LRU cache for teams as well, with small TTL to skip redis/pg lookups
        let team: Team = serde_json::from_str(&serialized_team).map_err(|e| {
            tracing::error!("failed to parse data to team: {}", e);
            FlagError::DataParsingError
        })?;

        Ok(team)
    }

    #[instrument(skip_all)]
    pub async fn update_redis_cache(
        client: Arc<dyn RedisClient + Send + Sync>,
        team: &Team,
    ) -> Result<(), FlagError> {
        let serialized_team = serde_json::to_string(&team).map_err(|e| {
            tracing::error!("Failed to serialize team: {}", e);
            FlagError::DataParsingError
        })?;

        client
            .set(
                format!("{TEAM_TOKEN_CACHE_PREFIX}{}", team.api_token),
                serialized_team,
            )
            .await
            .map_err(|e| {
                tracing::error!("Failed to update Redis cache: {}", e);
                FlagError::CacheUpdateError
            })?;

        Ok(())
    }

    pub async fn from_pg(
        client: Arc<dyn DatabaseClient + Send + Sync>,
        token: String,
    ) -> Result<Team, FlagError> {
        let mut conn = client.get_connection().await?;

        let query = "SELECT id, name, api_token FROM posthog_team WHERE api_token = $1";
        let row = sqlx::query_as::<_, Team>(query)
            .bind(&token)
            .fetch_one(&mut *conn)
            .await?;

        Ok(row)
    }
}

#[cfg(test)]
mod tests {
    use rand::Rng;
    use redis::AsyncCommands;

    use super::*;
    use crate::{
        team,
        test_utils::{
            insert_new_team_in_pg, insert_new_team_in_redis, random_string, setup_pg_client,
            setup_redis_client,
        },
    };

    #[tokio::test]
    async fn test_fetch_team_from_redis() {
        let client = setup_redis_client(None);

        let team = insert_new_team_in_redis(client.clone())
            .await
            .expect("Failed to insert team in redis");

        let target_token = team.api_token;

        let team_from_redis = Team::from_redis(client.clone(), target_token.clone())
            .await
            .unwrap();
        assert_eq!(team_from_redis.api_token, target_token);
        assert_eq!(team_from_redis.id, team.id);
    }

    #[tokio::test]
    async fn test_fetch_invalid_team_from_redis() {
        let client = setup_redis_client(None);

        match Team::from_redis(client.clone(), "banana".to_string()).await {
            Err(FlagError::TokenValidationError) => (),
            _ => panic!("Expected TokenValidationError"),
        };
    }

    #[tokio::test]
    async fn test_cant_connect_to_redis_error_is_not_token_validation_error() {
        let client = setup_redis_client(Some("redis://localhost:1111/".to_string()));

        match Team::from_redis(client.clone(), "banana".to_string()).await {
            Err(FlagError::RedisUnavailable) => (),
            _ => panic!("Expected RedisUnavailable"),
        };
    }

    #[tokio::test]
    async fn test_corrupted_data_in_redis_is_handled() {
        // TODO: Extend this test with fallback to pg
        let id = rand::thread_rng().gen_range(0..10_000_000);
        let token = random_string("phc_", 12);
        let team = Team {
            id,
            name: "team".to_string(),
            api_token: token,
        };
        let serialized_team = serde_json::to_string(&team).expect("Failed to serialise team");

        // manually insert non-pickled data in redis
        let client =
            redis::Client::open("redis://localhost:6379/").expect("Failed to create redis client");
        let mut conn = client
            .get_async_connection()
            .await
            .expect("Failed to get redis connection");
        conn.set::<String, String, ()>(
            format!(
                "{}{}",
                team::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await
        .expect("Failed to write data to redis");

        // now get client connection for data
        let client = setup_redis_client(None);

        match Team::from_redis(client.clone(), team.api_token.clone()).await {
            Err(FlagError::DataParsingError) => (),
            Err(other) => panic!("Expected DataParsingError, got {:?}", other),
            Ok(_) => panic!("Expected DataParsingError"),
        };
    }

    #[tokio::test]
    async fn test_fetch_team_from_pg() {
        let client = setup_pg_client(None).await;

        let team = insert_new_team_in_pg(client.clone())
            .await
            .expect("Failed to insert team in pg");

        let target_token = team.api_token;

        let team_from_pg = Team::from_pg(client.clone(), target_token.clone())
            .await
            .expect("Failed to fetch team from pg");

        assert_eq!(team_from_pg.api_token, target_token);
        assert_eq!(team_from_pg.id, team.id);
        assert_eq!(team_from_pg.name, team.name);
    }

    #[tokio::test]
    async fn test_fetch_team_from_pg_with_invalid_token() {
        // TODO: Figure out a way such that `run_database_migrations` is called only once, and already called
        // before running these tests.

        let client = setup_pg_client(None).await;
        let target_token = "xxxx".to_string();

        match Team::from_pg(client.clone(), target_token.clone()).await {
            Err(FlagError::TokenValidationError) => (),
            _ => panic!("Expected TokenValidationError"),
        };
    }

    // TODO: Handle cases where db connection fails.
}
