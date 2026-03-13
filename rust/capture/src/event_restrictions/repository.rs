use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common_redis::{Client as RedisClient, CustomRedisError};
use metrics::counter;
use serde::Deserialize;
use tracing::warn;

use super::types::{Restriction, RestrictionFilters, RestrictionScope, RestrictionType};

const REDIS_KEY_PREFIX: &str = "event_ingestion_restriction_dynamic_config";

/// Entry format for restriction data (matches Python's JSON format)
#[derive(Debug, Clone, Deserialize)]
pub struct RestrictionEntry {
    pub version: Option<i32>,
    pub token: String,
    #[serde(default)]
    pub pipelines: Vec<String>,
    #[serde(default)]
    pub distinct_ids: Vec<String>,
    #[serde(default)]
    pub session_ids: Vec<String>,
    #[serde(default)]
    pub event_names: Vec<String>,
    #[serde(default)]
    pub event_uuids: Vec<String>,
}

impl RestrictionEntry {
    pub fn into_restriction(self, restriction_type: RestrictionType) -> Restriction {
        let has_filters = !self.distinct_ids.is_empty()
            || !self.session_ids.is_empty()
            || !self.event_names.is_empty()
            || !self.event_uuids.is_empty();

        let scope = if has_filters {
            RestrictionScope::Filtered(RestrictionFilters {
                distinct_ids: self.distinct_ids.into_iter().collect(),
                session_ids: self.session_ids.into_iter().collect(),
                event_names: self.event_names.into_iter().collect(),
                event_uuids: self.event_uuids.into_iter().collect(),
            })
        } else {
            RestrictionScope::AllEvents
        };

        Restriction {
            restriction_type,
            scope,
        }
    }
}

/// Repository trait for fetching restriction entries from storage.
/// This abstraction allows easy mocking in tests.
#[async_trait]
pub trait EventRestrictionsRepository: Send + Sync {
    /// Fetch restriction entries for a given restriction type.
    /// Returns None if no data exists, or an error if fetching failed.
    async fn get_entries(
        &self,
        restriction_type: RestrictionType,
    ) -> Result<Option<Vec<RestrictionEntry>>, CustomRedisError>;
}

/// Redis implementation of the restrictions repository.
/// Reads plain JSON data written by Python.
///
/// This repository creates its own Redis client configured for UTF-8/JSON format,
/// ensuring the correct serialization format is always used.
pub struct RedisRestrictionsRepository {
    redis: Arc<dyn RedisClient + Send + Sync>,
    key_prefix: Option<String>,
}

impl RedisRestrictionsRepository {
    /// Create a new repository connected to the given Redis URL.
    ///
    /// The Redis client is configured with UTF-8 format (no compression) to read
    /// plain JSON data written by Python.
    pub async fn new(
        redis_url: String,
        response_timeout: Option<Duration>,
        connection_timeout: Option<Duration>,
    ) -> Result<Self, CustomRedisError> {
        let redis = Arc::new(
            common_redis::RedisClient::with_config(
                redis_url,
                common_redis::CompressionConfig::disabled(),
                common_redis::RedisValueFormat::Utf8,
                response_timeout,
                connection_timeout,
            )
            .await?,
        );

        Ok(Self {
            redis,
            key_prefix: None,
        })
    }

    /// Create with a key prefix (for testing only).
    ///
    /// Like `new()`, this creates a correctly-configured Redis client internally.
    #[cfg(test)]
    pub async fn with_prefix_for_test(
        redis_url: String,
        prefix: String,
    ) -> Result<Self, CustomRedisError> {
        let redis = Arc::new(
            common_redis::RedisClient::with_config(
                redis_url,
                common_redis::CompressionConfig::disabled(),
                common_redis::RedisValueFormat::Utf8,
                None,
                None,
            )
            .await?,
        );

        Ok(Self {
            redis,
            key_prefix: Some(prefix),
        })
    }

    fn build_key(&self, restriction_type: RestrictionType) -> String {
        match &self.key_prefix {
            Some(prefix) => {
                format!(
                    "{}{}:{}",
                    prefix,
                    REDIS_KEY_PREFIX,
                    restriction_type.redis_key()
                )
            }
            None => format!("{}:{}", REDIS_KEY_PREFIX, restriction_type.redis_key()),
        }
    }
}

#[async_trait]
impl EventRestrictionsRepository for RedisRestrictionsRepository {
    async fn get_entries(
        &self,
        restriction_type: RestrictionType,
    ) -> Result<Option<Vec<RestrictionEntry>>, CustomRedisError> {
        let key = self.build_key(restriction_type);
        let restriction_type_str = restriction_type.as_str();

        let json_str = match self.redis.get(key.clone()).await {
            Ok(s) => s,
            Err(CustomRedisError::NotFound) => {
                counter!(
                    "capture_event_restrictions_redis_fetch",
                    "restriction_type" => restriction_type_str,
                    "result" => "not_found"
                )
                .increment(1);
                return Ok(None);
            }
            Err(e) => {
                counter!(
                    "capture_event_restrictions_redis_fetch",
                    "restriction_type" => restriction_type_str,
                    "result" => "error"
                )
                .increment(1);
                warn!(key = %key, error = %e, "Failed to fetch restrictions from Redis");
                return Err(e);
            }
        };

        match serde_json::from_str(&json_str) {
            Ok(entries) => {
                counter!(
                    "capture_event_restrictions_redis_fetch",
                    "restriction_type" => restriction_type_str,
                    "result" => "success"
                )
                .increment(1);
                Ok(Some(entries))
            }
            Err(e) => {
                counter!(
                    "capture_event_restrictions_redis_fetch",
                    "restriction_type" => restriction_type_str,
                    "result" => "parse_error"
                )
                .increment(1);
                warn!(key = %key, error = %e, "Failed to parse restrictions from Redis");
                Err(CustomRedisError::ParseError(format!(
                    "Failed to parse JSON: {}",
                    e
                )))
            }
        }
    }
}

// ============================================================================
// Mock Repository for Testing
// ============================================================================

#[cfg(test)]
pub mod testing {
    use super::*;
    use std::collections::HashMap;
    use tokio::sync::Mutex;

    type MockEntries =
        HashMap<RestrictionType, Result<Option<Vec<RestrictionEntry>>, CustomRedisError>>;

    /// Mock repository for unit testing RestrictionManager
    pub struct MockRestrictionsRepository {
        entries: Mutex<MockEntries>,
    }

    impl MockRestrictionsRepository {
        pub fn new() -> Self {
            Self {
                entries: Mutex::new(HashMap::new()),
            }
        }

        pub async fn set_entries(
            &self,
            restriction_type: RestrictionType,
            entries: Option<Vec<RestrictionEntry>>,
        ) {
            self.entries
                .lock()
                .await
                .insert(restriction_type, Ok(entries));
        }

        pub async fn set_error(&self, restriction_type: RestrictionType, error: CustomRedisError) {
            self.entries
                .lock()
                .await
                .insert(restriction_type, Err(error));
        }
    }

    impl Default for MockRestrictionsRepository {
        fn default() -> Self {
            Self::new()
        }
    }

    #[async_trait]
    impl EventRestrictionsRepository for MockRestrictionsRepository {
        async fn get_entries(
            &self,
            restriction_type: RestrictionType,
        ) -> Result<Option<Vec<RestrictionEntry>>, CustomRedisError> {
            self.entries
                .lock()
                .await
                .get(&restriction_type)
                .cloned()
                .unwrap_or(Ok(None))
        }
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_restriction_entry_parsing() {
        let json = r#"[
            {
                "version": 2,
                "token": "token1",
                "pipelines": ["analytics"],
                "distinct_ids": ["user1", "user2"],
                "event_names": ["$pageview"]
            },
            {
                "version": 2,
                "token": "token2",
                "pipelines": ["analytics", "session_recordings"]
            }
        ]"#;

        let entries: Vec<RestrictionEntry> = serde_json::from_str(json).unwrap();
        assert_eq!(entries.len(), 2);

        let entry1 = &entries[0];
        assert_eq!(entry1.token, "token1");
        assert_eq!(entry1.distinct_ids, vec!["user1", "user2"]);
        assert_eq!(entry1.event_names, vec!["$pageview"]);
        assert!(entry1.session_ids.is_empty());

        let restriction1 = entries[0]
            .clone()
            .into_restriction(RestrictionType::DropEvent);
        assert!(matches!(restriction1.scope, RestrictionScope::Filtered(_)));

        let entry2 = &entries[1];
        assert_eq!(entry2.token, "token2");
        assert!(entry2.distinct_ids.is_empty());

        let restriction2 = entries[1]
            .clone()
            .into_restriction(RestrictionType::DropEvent);
        assert!(matches!(restriction2.scope, RestrictionScope::AllEvents));
    }
}

// ============================================================================
// Integration Tests
// ============================================================================

/// Integration tests for RedisRestrictionsRepository using real Redis.
/// Each test uses a unique prefix to avoid conflicts when running in parallel.
#[cfg(test)]
mod integration_tests {
    use super::*;
    use common_redis::Client;
    use rand::distributions::Alphanumeric;
    use rand::Rng;

    const REDIS_URL: &str = "redis://localhost:6379/";

    fn random_prefix() -> String {
        let suffix: String = rand::thread_rng()
            .sample_iter(Alphanumeric)
            .take(12)
            .map(char::from)
            .collect();
        format!("test_{suffix}/")
    }

    /// Helper client for test setup/cleanup (writing test data, deleting keys).
    /// The repository creates its own client with guaranteed correct config.
    async fn create_helper_client() -> Arc<dyn Client + Send + Sync> {
        Arc::new(
            common_redis::RedisClient::with_config(
                REDIS_URL.to_string(),
                common_redis::CompressionConfig::disabled(),
                common_redis::RedisValueFormat::Utf8,
                None,
                None,
            )
            .await
            .expect("Failed to connect to Redis - is Redis running at localhost:6379?"),
        )
    }

    async fn cleanup(client: &Arc<dyn Client + Send + Sync>, prefix: &str) {
        for restriction_type in RestrictionType::all() {
            let key = format!(
                "{}{}:{}",
                prefix,
                REDIS_KEY_PREFIX,
                restriction_type.redis_key()
            );
            client.del(key).await.ok();
        }
    }

    #[tokio::test]
    async fn test_repository_reads_plain_json() {
        let helper = create_helper_client().await;
        let prefix = random_prefix();

        // Write plain JSON like Python does
        let json = r#"[{"version": 2, "token": "test_token", "pipelines": ["analytics"]}]"#;
        let key = format!(
            "{}{}:force_overflow_from_ingestion",
            prefix, REDIS_KEY_PREFIX
        );
        helper.set(key, json.to_string()).await.unwrap();

        let repo = RedisRestrictionsRepository::with_prefix_for_test(
            REDIS_URL.to_string(),
            prefix.clone(),
        )
        .await
        .unwrap();
        let entries = repo
            .get_entries(RestrictionType::ForceOverflow)
            .await
            .unwrap();

        assert!(entries.is_some());
        let entries = entries.unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].token, "test_token");
        assert_eq!(entries[0].version, Some(2));

        cleanup(&helper, &prefix).await;
    }

    #[tokio::test]
    async fn test_repository_returns_none_for_missing_key() {
        let helper = create_helper_client().await;
        let prefix = random_prefix();

        let repo = RedisRestrictionsRepository::with_prefix_for_test(
            REDIS_URL.to_string(),
            prefix.clone(),
        )
        .await
        .unwrap();
        let entries = repo.get_entries(RestrictionType::DropEvent).await.unwrap();

        assert!(entries.is_none());

        cleanup(&helper, &prefix).await;
    }

    #[tokio::test]
    async fn test_repository_parses_entries_with_filters() {
        let helper = create_helper_client().await;
        let prefix = random_prefix();

        let json = r#"[{
            "version": 2,
            "token": "filtered_token",
            "pipelines": ["analytics"],
            "distinct_ids": ["user1", "user2"],
            "event_names": ["$pageview", "$autocapture"]
        }]"#;
        let key = format!("{}{}:drop_event_from_ingestion", prefix, REDIS_KEY_PREFIX);
        helper.set(key, json.to_string()).await.unwrap();

        let repo = RedisRestrictionsRepository::with_prefix_for_test(
            REDIS_URL.to_string(),
            prefix.clone(),
        )
        .await
        .unwrap();
        let entries = repo
            .get_entries(RestrictionType::DropEvent)
            .await
            .unwrap()
            .unwrap();

        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].distinct_ids, vec!["user1", "user2"]);
        assert_eq!(entries[0].event_names, vec!["$pageview", "$autocapture"]);

        cleanup(&helper, &prefix).await;
    }

    #[tokio::test]
    async fn test_repository_parses_multiple_entries() {
        let helper = create_helper_client().await;
        let prefix = random_prefix();

        let json = r#"[
            {"version": 2, "token": "token_a", "pipelines": ["analytics"]},
            {"version": 2, "token": "token_b", "pipelines": ["session_recordings"]},
            {"version": 2, "token": "token_c", "pipelines": ["analytics", "ai"], "distinct_ids": ["user1"]}
        ]"#;
        let key = format!("{}{}:drop_event_from_ingestion", prefix, REDIS_KEY_PREFIX);
        helper.set(key, json.to_string()).await.unwrap();

        let repo = RedisRestrictionsRepository::with_prefix_for_test(
            REDIS_URL.to_string(),
            prefix.clone(),
        )
        .await
        .unwrap();
        let entries = repo
            .get_entries(RestrictionType::DropEvent)
            .await
            .unwrap()
            .unwrap();

        assert_eq!(entries.len(), 3);
        assert_eq!(entries[0].token, "token_a");
        assert_eq!(entries[0].pipelines, vec!["analytics"]);
        assert_eq!(entries[1].token, "token_b");
        assert_eq!(entries[1].pipelines, vec!["session_recordings"]);
        assert_eq!(entries[2].token, "token_c");
        assert_eq!(entries[2].pipelines, vec!["analytics", "ai"]);
        assert_eq!(entries[2].distinct_ids, vec!["user1"]);

        cleanup(&helper, &prefix).await;
    }

    #[tokio::test]
    async fn test_repository_restriction_types_are_isolated() {
        let helper = create_helper_client().await;
        let prefix = random_prefix();

        // Write different data to each restriction type
        let drop_json = r#"[{"version": 2, "token": "drop_token", "pipelines": ["analytics"]}]"#;
        let overflow_json =
            r#"[{"version": 2, "token": "overflow_token", "pipelines": ["analytics"]}]"#;
        let dlq_json = r#"[{"version": 2, "token": "dlq_token", "pipelines": ["analytics"]}]"#;
        let skip_json = r#"[{"version": 2, "token": "skip_token", "pipelines": ["analytics"]}]"#;

        helper
            .set(
                format!("{}{}:drop_event_from_ingestion", prefix, REDIS_KEY_PREFIX),
                drop_json.to_string(),
            )
            .await
            .unwrap();
        helper
            .set(
                format!(
                    "{}{}:force_overflow_from_ingestion",
                    prefix, REDIS_KEY_PREFIX
                ),
                overflow_json.to_string(),
            )
            .await
            .unwrap();
        helper
            .set(
                format!("{}{}:redirect_to_dlq", prefix, REDIS_KEY_PREFIX),
                dlq_json.to_string(),
            )
            .await
            .unwrap();
        helper
            .set(
                format!("{}{}:skip_person_processing", prefix, REDIS_KEY_PREFIX),
                skip_json.to_string(),
            )
            .await
            .unwrap();

        let repo = RedisRestrictionsRepository::with_prefix_for_test(
            REDIS_URL.to_string(),
            prefix.clone(),
        )
        .await
        .unwrap();

        // Verify each restriction type returns only its own data
        let drop_entries = repo
            .get_entries(RestrictionType::DropEvent)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(drop_entries.len(), 1);
        assert_eq!(drop_entries[0].token, "drop_token");

        let overflow_entries = repo
            .get_entries(RestrictionType::ForceOverflow)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(overflow_entries.len(), 1);
        assert_eq!(overflow_entries[0].token, "overflow_token");

        let dlq_entries = repo
            .get_entries(RestrictionType::RedirectToDlq)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(dlq_entries.len(), 1);
        assert_eq!(dlq_entries[0].token, "dlq_token");

        let skip_entries = repo
            .get_entries(RestrictionType::SkipPersonProcessing)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(skip_entries.len(), 1);
        assert_eq!(skip_entries[0].token, "skip_token");

        cleanup(&helper, &prefix).await;
    }
}
