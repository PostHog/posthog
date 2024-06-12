use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tracing::instrument;

use crate::{
    api::FlagError,
    redis::{Client, CustomRedisError},
};

// TRICKY: This cache data is coming from django-redis. If it ever goes out of sync, we'll bork.
// TODO: Add integration tests across repos to ensure this doesn't happen.
pub const TEAM_TOKEN_CACHE_PREFIX: &str = "posthog:1:team_token:";

#[derive(Debug, Deserialize, Serialize)]
pub struct Team {
    pub id: i64,
    pub name: String,
    pub api_token: String,
}

impl Team {
    /// Validates a token, and returns a team if it exists.

    #[instrument(skip_all)]
    pub async fn from_redis(
        client: Arc<dyn Client + Send + Sync>,
        token: String,
    ) -> Result<Team, FlagError> {
        // TODO: Instead of failing here, i.e. if not in redis, fallback to pg
        let serialized_team = client
            .get(format!("{TEAM_TOKEN_CACHE_PREFIX}{}", token))
            .await
            .map_err(|e| match e {
                CustomRedisError::NotFound => FlagError::TokenValidationError,
                CustomRedisError::PickleError(_) => {
                    tracing::error!("failed to fetch data: {}", e);
                    FlagError::DataParsingError
                }
                _ => {
                    tracing::error!("Unknown redis error: {}", e);
                    FlagError::RedisUnavailable
                }
            })?;

        // TODO: Consider an LRU cache for teams as well, with small TTL to skip redis/pg lookups
        let team: Team = serde_json::from_str(&serialized_team).map_err(|e| {
            tracing::error!("failed to parse data to team: {}", e);
            FlagError::DataParsingError
        })?;

        Ok(team)
    }
}

#[cfg(test)]
mod tests {
    use rand::Rng;
    use redis::AsyncCommands;

    use super::*;
    use crate::{
        team,
        test_utils::{insert_new_team_in_redis, random_string, setup_redis_client},
    };

    #[tokio::test]
    async fn test_fetch_team_from_redis() {
        let client = setup_redis_client(None);

        let team = insert_new_team_in_redis(client.clone()).await.unwrap();

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
}
