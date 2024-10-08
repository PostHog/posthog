use std::{collections::HashMap, sync::Arc};

use bytes::Bytes;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::instrument;

use crate::{
    api::FlagError, database::Client as DatabaseClient, flag_definitions::FeatureFlagList,
    redis::Client as RedisClient, team::Team,
};

#[derive(Debug, Clone, Copy)]
pub enum FlagRequestType {
    Decide,
    LocalEvaluation,
}

#[derive(Default, Debug, Deserialize, Serialize)]
pub struct FlagRequest {
    #[serde(
        alias = "$token",
        alias = "api_key",
        skip_serializing_if = "Option::is_none"
    )]
    pub token: Option<String>,
    #[serde(alias = "$distinct_id", skip_serializing_if = "Option::is_none")]
    pub distinct_id: Option<String>,
    pub geoip_disable: Option<bool>,
    #[serde(default)]
    pub person_properties: Option<HashMap<String, Value>>,
    #[serde(default)]
    pub groups: Option<HashMap<String, Value>>,
    // TODO: better type this since we know its going to be a nested json
    #[serde(default)]
    pub group_properties: Option<HashMap<String, HashMap<String, Value>>>,
    #[serde(alias = "$anon_distinct_id", skip_serializing_if = "Option::is_none")]
    pub anon_distinct_id: Option<String>,
    pub ip_address: Option<String>,
}

impl FlagRequest {
    /// Takes a request payload and tries to read it.
    /// Only supports base64 encoded payloads or uncompressed utf-8 as json.
    #[instrument(skip_all)]
    pub fn from_bytes(bytes: Bytes) -> Result<FlagRequest, FlagError> {
        tracing::debug!(len = bytes.len(), "decoding new request");

        let payload = String::from_utf8(bytes.to_vec()).map_err(|e| {
            tracing::error!("failed to decode body: {}", e);
            FlagError::RequestDecodingError(String::from("invalid body encoding"))
        })?;

        tracing::debug!(json = payload, "decoded event data");

        // Attempt to parse as JSON, rejecting invalid JSON
        match serde_json::from_str::<FlagRequest>(&payload) {
            Ok(request) => Ok(request),
            Err(e) => {
                tracing::error!("failed to parse JSON: {}", e);
                Err(FlagError::RequestDecodingError(String::from(
                    "invalid JSON",
                )))
            }
        }
    }

    /// Extracts the token from the request and verifies it against the cache.
    /// If the token is not found in the cache, it will be verified against the database.
    pub async fn extract_and_verify_token(
        &self,
        redis_client: Arc<dyn RedisClient + Send + Sync>,
        pg_client: Arc<dyn DatabaseClient + Send + Sync>,
    ) -> Result<String, FlagError> {
        let token = match self {
            FlagRequest {
                token: Some(token), ..
            } => token.to_string(),
            _ => return Err(FlagError::NoTokenError),
        };

        match Team::from_redis(redis_client.clone(), token.clone()).await {
            Ok(_) => Ok(token),
            Err(_) => {
                // Fallback: Check PostgreSQL if not found in Redis
                match Team::from_pg(pg_client, token.clone()).await {
                    Ok(team) => {
                        // Token found in PostgreSQL, update Redis cache so that we can verify it from Redis next time
                        if let Err(e) = Team::update_redis_cache(redis_client, &team).await {
                            tracing::warn!("Failed to update Redis cache: {}", e);
                        }
                        Ok(token)
                    }
                    // TODO do we need a custom error here to track the fallback
                    Err(_) => Err(FlagError::TokenValidationError),
                }
            }
        }
    }

    /// Fetches the team from the cache or the database.
    /// If the team is not found in the cache, it will be fetched from the database and stored in the cache.
    /// Returns the team if found, otherwise an error.
    pub async fn get_team_from_cache_or_pg(
        &self,
        token: &str,
        redis_client: Arc<dyn RedisClient + Send + Sync>,
        pg_client: Arc<dyn DatabaseClient + Send + Sync>,
    ) -> Result<Team, FlagError> {
        match Team::from_redis(redis_client.clone(), token.to_owned()).await {
            Ok(team) => Ok(team),
            Err(_) => match Team::from_pg(pg_client, token.to_owned()).await {
                Ok(team) => {
                    // If we have the team in postgres, but not redis, update redis so we're faster next time
                    // TODO: we have some counters in django for tracking these cache misses
                    // we should probably do the same here
                    if let Err(e) = Team::update_redis_cache(redis_client, &team).await {
                        tracing::warn!("Failed to update Redis cache: {}", e);
                    }
                    Ok(team)
                }
                // TODO what kind of error should we return here?
                Err(e) => Err(e),
            },
        }
    }

    /// Extracts the distinct_id from the request.
    /// If the distinct_id is missing or empty, an error is returned.
    pub fn extract_distinct_id(&self) -> Result<String, FlagError> {
        let distinct_id = match &self.distinct_id {
            None => return Err(FlagError::MissingDistinctId),
            Some(id) => id,
        };

        match distinct_id.len() {
            0 => Err(FlagError::EmptyDistinctId),
            1..=200 => Ok(distinct_id.to_owned()),
            _ => Ok(distinct_id.chars().take(200).collect()),
        }
    }

    /// Extracts the properties from the request.
    /// If the request contains person_properties, they are returned.
    // TODO do I even need this one?
    pub fn extract_properties(&self) -> HashMap<String, Value> {
        let mut properties = HashMap::new();
        if let Some(person_properties) = &self.person_properties {
            properties.extend(person_properties.clone());
        }
        properties
    }

    /// Fetches the flags from the cache or the database.
    /// If the flags are not found in the cache, they will be fetched from the database and stored in the cache.
    /// Returns the flags if found, otherwise an error.
    pub async fn get_flags_from_cache_or_pg(
        &self,
        team_id: i32,
        redis_client: Arc<dyn RedisClient + Send + Sync>,
        pg_client: Arc<dyn DatabaseClient + Send + Sync>,
    ) -> Result<FeatureFlagList, FlagError> {
        // TODO add a cache hit/miss counter
        match FeatureFlagList::from_redis(redis_client.clone(), team_id).await {
            Ok(flags) => Ok(flags),
            Err(_) => match FeatureFlagList::from_pg(pg_client, team_id).await {
                Ok(flags) => {
                    // If we have the flags in postgres, but not redis, update redis so we're faster next time
                    // TODO: we have some counters in django for tracking these cache misses
                    // we should probably do the same here
                    if let Err(e) =
                        FeatureFlagList::update_flags_in_redis(redis_client, team_id, &flags).await
                    {
                        tracing::warn!("Failed to update Redis cache: {}", e);
                    }
                    Ok(flags)
                }
                // TODO what kind of error should we return here?
                Err(e) => Err(e),
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use crate::api::FlagError;
    use crate::flag_definitions::{
        FeatureFlag, FeatureFlagList, FlagFilters, FlagGroupType, OperatorType, PropertyFilter,
        TEAM_FLAGS_CACHE_PREFIX,
    };
    use crate::flag_request::FlagRequest;
    use crate::redis::Client as RedisClient;
    use crate::team::Team;
    use crate::test_utils::{insert_new_team_in_redis, setup_pg_reader_client, setup_redis_client};
    use bytes::Bytes;
    use serde_json::json;

    #[test]
    fn empty_distinct_id_not_accepted() {
        let json = json!({
            "distinct_id": "",
            "token": "my_token1",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        match flag_payload.extract_distinct_id() {
            Err(FlagError::EmptyDistinctId) => (),
            _ => panic!("expected empty distinct id error"),
        };
    }

    #[test]
    fn too_large_distinct_id_is_truncated() {
        let json = json!({
            "distinct_id": "a".repeat(210),
            "token": "my_token1",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        assert_eq!(flag_payload.extract_distinct_id().unwrap().len(), 200);
    }

    #[test]
    fn distinct_id_is_returned_correctly() {
        let json = json!({
            "$distinct_id": "alakazam",
            "token": "my_token1",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        match flag_payload.extract_distinct_id() {
            Ok(id) => assert_eq!(id, "alakazam"),
            _ => panic!("expected distinct id"),
        };
    }

    #[tokio::test]
    async fn token_is_returned_correctly() {
        let redis_client = setup_redis_client(None);
        let pg_client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        let json = json!({
            "$distinct_id": "alakazam",
            "token": team.api_token,
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        match flag_payload
            .extract_and_verify_token(redis_client, pg_client)
            .await
        {
            Ok(extracted_token) => assert_eq!(extracted_token, team.api_token),
            Err(e) => panic!("Failed to extract and verify token: {:?}", e),
        };
    }

    #[tokio::test]
    async fn test_get_team_from_cache_or_pg() {
        let redis_client = setup_redis_client(None);
        let pg_client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        let flag_request = FlagRequest {
            token: Some(team.api_token.clone()),
            ..Default::default()
        };

        // Test fetching from Redis
        let result = flag_request
            .get_team_from_cache_or_pg(&team.api_token, redis_client.clone(), pg_client.clone())
            .await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().id, team.id);

        // Test fetching from PostgreSQL (simulate Redis miss)
        // First, remove the team from Redis
        redis_client
            .del(format!("team:{}", team.api_token))
            .await
            .expect("Failed to remove team from Redis");

        let result = flag_request
            .get_team_from_cache_or_pg(&team.api_token, redis_client.clone(), pg_client.clone())
            .await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().id, team.id);

        // Verify that the team was re-added to Redis
        let redis_team = Team::from_redis(redis_client.clone(), team.api_token.clone()).await;
        assert!(redis_team.is_ok());
    }

    #[test]
    fn test_extract_properties() {
        let flag_request = FlagRequest {
            person_properties: Some(HashMap::from([
                ("key1".to_string(), json!("value1")),
                ("key2".to_string(), json!(42)),
            ])),
            ..Default::default()
        };

        let properties = flag_request.extract_properties();
        assert_eq!(properties.len(), 2);
        assert_eq!(properties.get("key1").unwrap(), &json!("value1"));
        assert_eq!(properties.get("key2").unwrap(), &json!(42));
    }

    #[tokio::test]
    async fn test_get_flags_from_cache_or_pg() {
        let redis_client = setup_redis_client(None);
        let pg_client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        // Insert some mock flags into Redis
        let mock_flags = FeatureFlagList {
            flags: vec![
                FeatureFlag {
                    id: 1,
                    team_id: team.id,
                    name: Some("Beta Feature".to_string()),
                    key: "beta_feature".to_string(),
                    filters: FlagFilters {
                        groups: vec![FlagGroupType {
                            properties: Some(vec![PropertyFilter {
                                key: "country".to_string(),
                                value: json!("US"),
                                operator: Some(OperatorType::Exact),
                                prop_type: "person".to_string(),
                                group_type_index: None,
                            }]),
                            rollout_percentage: Some(50.0),
                            variant: None,
                        }],
                        multivariate: None,
                        aggregation_group_type_index: None,
                        payloads: None,
                        super_groups: None,
                    },
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: false,
                },
                FeatureFlag {
                    id: 2,
                    team_id: team.id,
                    name: Some("New User Interface".to_string()),
                    key: "new_ui".to_string(),
                    filters: FlagFilters {
                        groups: vec![],
                        multivariate: None,
                        aggregation_group_type_index: None,
                        payloads: None,
                        super_groups: None,
                    },
                    deleted: false,
                    active: false,
                    ensure_experience_continuity: false,
                },
                FeatureFlag {
                    id: 3,
                    team_id: team.id,
                    name: Some("Premium Feature".to_string()),
                    key: "premium_feature".to_string(),
                    filters: FlagFilters {
                        groups: vec![FlagGroupType {
                            properties: Some(vec![PropertyFilter {
                                key: "is_premium".to_string(),
                                value: json!(true),
                                operator: Some(OperatorType::Exact),
                                prop_type: "person".to_string(),
                                group_type_index: None,
                            }]),
                            rollout_percentage: Some(100.0),
                            variant: None,
                        }],
                        multivariate: None,
                        aggregation_group_type_index: None,
                        payloads: None,
                        super_groups: None,
                    },
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: false,
                },
            ],
        };

        FeatureFlagList::update_flags_in_redis(redis_client.clone(), team.id, &mock_flags)
            .await
            .expect("Failed to insert mock flags in Redis");

        let flag_request = FlagRequest::default();

        // Test fetching from Redis
        let result = flag_request
            .get_flags_from_cache_or_pg(team.id, redis_client.clone(), pg_client.clone())
            .await;
        assert!(result.is_ok());
        let fetched_flags = result.unwrap();
        assert_eq!(fetched_flags.flags.len(), mock_flags.flags.len());

        // Verify the contents of the fetched flags
        let beta_feature = fetched_flags
            .flags
            .iter()
            .find(|f| f.key == "beta_feature")
            .unwrap();
        assert!(beta_feature.active);
        assert_eq!(
            beta_feature.filters.groups[0].rollout_percentage,
            Some(50.0)
        );
        assert_eq!(
            beta_feature.filters.groups[0].properties.as_ref().unwrap()[0].key,
            "country"
        );

        let new_ui = fetched_flags
            .flags
            .iter()
            .find(|f| f.key == "new_ui")
            .unwrap();
        assert!(!new_ui.active);
        assert!(new_ui.filters.groups.is_empty());

        let premium_feature = fetched_flags
            .flags
            .iter()
            .find(|f| f.key == "premium_feature")
            .unwrap();
        assert!(premium_feature.active);
        assert_eq!(
            premium_feature.filters.groups[0].rollout_percentage,
            Some(100.0)
        );
        assert_eq!(
            premium_feature.filters.groups[0]
                .properties
                .as_ref()
                .unwrap()[0]
                .key,
            "is_premium"
        );

        // Test fetching from PostgreSQL (simulate Redis miss)
        // First, remove the flags from Redis
        redis_client
            .del(format!("{}:{}", TEAM_FLAGS_CACHE_PREFIX, team.id))
            .await
            .expect("Failed to remove flags from Redis");

        let result = flag_request
            .get_flags_from_cache_or_pg(team.id, redis_client.clone(), pg_client.clone())
            .await;
        assert!(result.is_ok());
        // Verify that the flags were re-added to Redis
        let redis_flags = FeatureFlagList::from_redis(redis_client.clone(), team.id).await;
        assert!(redis_flags.is_ok());
        assert_eq!(redis_flags.unwrap().flags.len(), mock_flags.flags.len());
    }

    #[tokio::test]
    async fn test_error_cases() {
        let redis_client = setup_redis_client(None);
        let pg_client = setup_pg_reader_client(None).await;

        // Test invalid token
        let flag_request = FlagRequest {
            token: Some("invalid_token".to_string()),
            ..Default::default()
        };
        let result = flag_request
            .extract_and_verify_token(redis_client.clone(), pg_client.clone())
            .await;
        assert!(matches!(result, Err(FlagError::TokenValidationError)));

        // Test missing distinct_id
        let flag_request = FlagRequest {
            token: Some("valid_token".to_string()),
            distinct_id: None,
            ..Default::default()
        };
        let result = flag_request.extract_distinct_id();
        assert!(matches!(result, Err(FlagError::MissingDistinctId)));
    }
}
