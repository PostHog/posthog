use crate::{api::FlagError, database::Client as DatabaseClient, redis::Client as RedisClient};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tracing::instrument;

// TRICKY: This cache data is coming from django-redis. If it ever goes out of sync, we'll bork.
// TODO: Add integration tests across repos to ensure this doesn't happen.
pub const TEAM_FLAGS_CACHE_PREFIX: &str = "posthog:1:team_feature_flags_";

// TODO: Hmm, revisit when dealing with groups, but seems like
// ideal to just treat it as a u8 and do our own validation on top
#[derive(Debug, Deserialize)]
pub enum GroupTypeIndex {}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OperatorType {
    Exact,
    IsNot,
    Icontains,
    NotIcontains,
    Regex,
    NotRegex,
    Gt,
    Lt,
    Gte,
    Lte,
    IsSet,
    IsNotSet,
    IsDateExact,
    IsDateAfter,
    IsDateBefore,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PropertyFilter {
    pub key: String,
    // TODO: Probably need a default for value?
    // incase operators like is_set, is_not_set are used
    // not guaranteed to have a value, if say created via api
    pub value: serde_json::Value,
    pub operator: Option<OperatorType>,
    #[serde(rename = "type")]
    pub prop_type: String,
    pub group_type_index: Option<i8>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct FlagGroupType {
    pub properties: Option<Vec<PropertyFilter>>,
    pub rollout_percentage: Option<f64>,
    pub variant: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct MultivariateFlagVariant {
    pub key: String,
    pub name: Option<String>,
    pub rollout_percentage: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct MultivariateFlagOptions {
    pub variants: Vec<MultivariateFlagVariant>,
}

// TODO: test name with https://www.fileformat.info/info/charset/UTF-16/list.htm values, like '𝖕𝖗𝖔𝖕𝖊𝖗𝖙𝖞': `𝓿𝓪𝓵𝓾𝓮`

#[derive(Debug, Clone, Deserialize)]
pub struct FlagFilters {
    pub groups: Vec<FlagGroupType>,
    pub multivariate: Option<MultivariateFlagOptions>,
    pub aggregation_group_type_index: Option<i8>,
    pub payloads: Option<serde_json::Value>,
    pub super_groups: Option<Vec<FlagGroupType>>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct FeatureFlag {
    pub id: i32,
    pub team_id: i32,
    pub name: Option<String>,
    pub key: String,
    pub filters: FlagFilters,
    #[serde(default)]
    pub deleted: bool,
    #[serde(default)]
    pub active: bool,
    #[serde(default)]
    pub ensure_experience_continuity: bool,
}

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct FeatureFlagRow {
    pub id: i32,
    pub team_id: i32,
    pub name: Option<String>,
    pub key: String,
    pub filters: serde_json::Value,
    pub deleted: bool,
    pub active: bool,
    pub ensure_experience_continuity: bool,
}

impl FeatureFlag {
    pub fn get_group_type_index(&self) -> Option<i8> {
        self.filters.aggregation_group_type_index
    }

    pub fn get_conditions(&self) -> &Vec<FlagGroupType> {
        &self.filters.groups
    }

    pub fn get_variants(&self) -> Vec<MultivariateFlagVariant> {
        self.filters
            .multivariate
            .clone()
            .map_or(vec![], |m| m.variants)
    }
}

#[derive(Debug, Deserialize)]
pub struct FeatureFlagList {
    pub flags: Vec<FeatureFlag>,
}

impl FeatureFlagList {
    /// Returns feature flags from redis given a team_id
    #[instrument(skip_all)]
    pub async fn from_redis(
        client: Arc<dyn RedisClient + Send + Sync>,
        team_id: i32,
    ) -> Result<FeatureFlagList, FlagError> {
        // TODO: Instead of failing here, i.e. if not in redis, fallback to pg
        let serialized_flags = client
            .get(format!("{TEAM_FLAGS_CACHE_PREFIX}{}", team_id))
            .await?;

        let flags_list: Vec<FeatureFlag> =
            serde_json::from_str(&serialized_flags).map_err(|e| {
                tracing::error!("failed to parse data to flags list: {}", e);
                println!("failed to parse data: {}", e);

                FlagError::DataParsingError
            })?;

        Ok(FeatureFlagList { flags: flags_list })
    }

    /// Returns feature flags from postgres given a team_id
    #[instrument(skip_all)]
    pub async fn from_pg(
        client: Arc<dyn DatabaseClient + Send + Sync>,
        team_id: i32,
    ) -> Result<FeatureFlagList, FlagError> {
        let mut conn = client.get_connection().await.map_err(|e| {
            tracing::error!("Failed to get database connection: {}", e);
            FlagError::DatabaseUnavailable
        })?;

        let query = "SELECT id, team_id, name, key, filters, deleted, active, ensure_experience_continuity FROM posthog_featureflag WHERE team_id = $1";
        let flags_row = sqlx::query_as::<_, FeatureFlagRow>(query)
            .bind(team_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!("Failed to fetch feature flags from database: {}", e);
                FlagError::Internal(format!("Database query error: {}", e))
            })?;

        let flags_list = flags_row
            .into_iter()
            .map(|row| {
                let filters = serde_json::from_value(row.filters).map_err(|e| {
                    tracing::error!("Failed to deserialize filters for flag {}: {}", row.key, e);
                    FlagError::DataParsingError
                })?;

                Ok(FeatureFlag {
                    id: row.id,
                    team_id: row.team_id,
                    name: row.name,
                    key: row.key,
                    filters,
                    deleted: row.deleted,
                    active: row.active,
                    ensure_experience_continuity: row.ensure_experience_continuity,
                })
            })
            .collect::<Result<Vec<FeatureFlag>, FlagError>>()?;

        Ok(FeatureFlagList { flags: flags_list })
    }
}

#[cfg(test)]
mod tests {
    use async_trait::async_trait;
    use mockall::mock;
    use mockall::predicate::*;
    use serde_json::json;
    use tokio::runtime::Runtime;
    use tokio::time::timeout;

    use std::time::Duration;

    use super::*;
    use crate::database::CustomDatabaseError;
    use crate::test_utils::{
        insert_flags_for_team_in_pg, insert_flags_for_team_in_redis, insert_new_team_in_pg,
        insert_new_team_in_redis, setup_pg_client, setup_redis_client,
    };

    #[tokio::test]
    async fn test_fetch_flags_from_redis() {
        let client = setup_redis_client(None);

        let team = insert_new_team_in_redis(client.clone())
            .await
            .expect("Failed to insert team");

        insert_flags_for_team_in_redis(client.clone(), team.id, None)
            .await
            .expect("Failed to insert flags");

        let flags_from_redis = FeatureFlagList::from_redis(client.clone(), team.id)
            .await
            .expect("Failed to fetch flags from redis");
        assert_eq!(flags_from_redis.flags.len(), 1);
        let flag = flags_from_redis.flags.get(0).expect("Empty flags in redis");
        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(
            flag.filters.groups[0]
                .properties
                .as_ref()
                .expect("Properties don't exist on flag")
                .len(),
            1
        );
    }

    #[tokio::test]
    async fn test_fetch_invalid_team_from_redis() {
        let client = setup_redis_client(None);

        match FeatureFlagList::from_redis(client.clone(), 1234).await {
            Err(FlagError::TokenValidationError) => (),
            _ => panic!("Expected TokenValidationError"),
        };
    }

    #[tokio::test]
    async fn test_cant_connect_to_redis_error_is_not_token_validation_error() {
        let client = setup_redis_client(Some("redis://localhost:1111/".to_string()));

        match FeatureFlagList::from_redis(client.clone(), 1234).await {
            Err(FlagError::RedisUnavailable) => (),
            _ => panic!("Expected RedisUnavailable"),
        };
    }

    #[tokio::test]
    async fn test_fetch_flags_from_pg() {
        let client = setup_pg_client(None).await;

        let team = insert_new_team_in_pg(client.clone())
            .await
            .expect("Failed to insert team in pg");

        insert_flags_for_team_in_pg(client.clone(), team.id, None)
            .await
            .expect("Failed to insert flags");

        let flags_from_pg = FeatureFlagList::from_pg(client.clone(), team.id)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.flags.len(), 1);
        let flag = flags_from_pg.flags.get(0).expect("Flags should be in pg");

        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(
            flag.filters.groups[0]
                .properties
                .as_ref()
                .expect("Properties don't exist on flag")
                .len(),
            1
        );
        let property_filter = &flag.filters.groups[0]
            .properties
            .as_ref()
            .expect("Properties don't exist on flag")[0];

        assert_eq!(property_filter.key, "email");
        assert_eq!(property_filter.value, "a@b.com");
        assert_eq!(property_filter.operator, None);
        assert_eq!(property_filter.prop_type, "person");
        assert_eq!(property_filter.group_type_index, None);
        assert_eq!(flag.filters.groups[0].rollout_percentage, Some(50.0));
    }

    #[test]
    fn test_utf16_property_names_and_values() {
        let json_str = r#"{
            "id": 1,
            "team_id": 2,
            "name": "𝖚𝖙𝖋16_𝖙𝖊𝖘𝖙_𝖋𝖑𝖆𝖌",
            "key": "𝖚𝖙𝖋16_𝖙𝖊𝖘𝖙_𝖋𝖑𝖆𝖌",
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "𝖕𝖗𝖔𝖕𝖊𝖗𝖙𝖞",
                                "value": "𝓿𝓪𝓵𝓾𝓮",
                                "type": "person"
                            }
                        ]
                    }
                ]
            }
        }"#;

        let flag: FeatureFlag = serde_json::from_str(json_str).expect("Failed to deserialize");

        assert_eq!(flag.key, "𝖚𝖙𝖋16_𝖙𝖊𝖘𝖙_𝖋𝖑𝖆𝖌");
        let property = &flag.filters.groups[0].properties.as_ref().unwrap()[0];
        assert_eq!(property.key, "𝖕𝖗𝖔𝖕𝖊𝖗𝖙𝖞");
        assert_eq!(property.value, json!("𝓿𝓪𝓵𝓾𝓮"));
    }

    #[test]
    fn test_deserialize_complex_flag() {
        let json_str = r#"{
            "id": 1,
            "team_id": 2,
            "name": "Complex Flag",
            "key": "complex_flag",
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "test@example.com",
                                "operator": "exact",
                                "type": "person"
                            }
                        ],
                        "rollout_percentage": 50
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33.33
                        },
                        {
                            "key": "test",
                            "name": "Test Group",
                            "rollout_percentage": 66.67
                        }
                    ]
                },
                "aggregation_group_type_index": 0,
                "payloads": {"test": {"type": "json", "value": {"key": "value"}}}
            },
            "deleted": false,
            "active": true,
            "ensure_experience_continuity": false
        }"#;

        let flag: FeatureFlag = serde_json::from_str(json_str).expect("Failed to deserialize");

        assert_eq!(flag.id, 1);
        assert_eq!(flag.team_id, 2);
        assert_eq!(flag.name, Some("Complex Flag".to_string()));
        assert_eq!(flag.key, "complex_flag");
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(flag.filters.groups[0].properties.as_ref().unwrap().len(), 1);
        assert_eq!(flag.filters.groups[0].rollout_percentage, Some(50.0));
        assert_eq!(
            flag.filters.multivariate.as_ref().unwrap().variants.len(),
            2
        );
        assert_eq!(flag.filters.aggregation_group_type_index, Some(0));
        assert!(flag.filters.payloads.is_some());
        assert!(!flag.deleted);
        assert!(flag.active);
        assert!(!flag.ensure_experience_continuity);
    }

    // TODO: Add more tests to validate deserialization of flags.
    // TODO: Also make sure old flag data is handled, or everything is migrated to new style in production

    #[tokio::test]
    async fn test_fetch_empty_team_from_pg() {
        let client = setup_pg_client(None).await;

        match FeatureFlagList::from_pg(client.clone(), 1234)
            .await
            .expect("Failed to fetch flags from pg")
        {
            FeatureFlagList { flags } => {
                assert_eq!(flags.len(), 0);
            }
        }
    }

    mock! {
        DatabaseClient {}
        #[async_trait]
        impl DatabaseClient for DatabaseClient {
            async fn get_connection(&self) -> Result<sqlx::pool::PoolConnection<sqlx::Postgres> , crate::database::CustomDatabaseError>;
            async fn run_query(
                &self,
                query: String,
                parameters: Vec<String>,
                timeout_ms: Option<u64>,
            ) -> Result<Vec<FeatureFlagRow>, crate::database::CustomDatabaseError>;
        }
    }

    #[tokio::test]
    async fn test_from_pg_success_mocked() {
        let mut db_mock = MockDatabaseClient::new();

        db_mock.expect_run_query()
            .withf(|query, params, _| {
                query.contains("SELECT id, team_id, name, key, filters, deleted, active, ensure_experience_continuity FROM posthog_featureflag") &&
                params == &vec![1.to_string()]
            })
            .returning(|_, _, _| {
                Ok(vec![FeatureFlagRow {
                    id: 1,
                    team_id: 1,
                    name: Some("Test Flag".to_string()),
                    key: "test_flag".to_string(),
                    filters: json!({
                        "groups": [
                            {
                                "properties": [
                                    {
                                        "key": "email",
                                        "value": "test@example.com",
                                        "type": "person"
                                    }
                                ],
                                "rollout_percentage": 50
                            }
                        ]
                    }),
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: false,
                }])
            });

        let result = FeatureFlagList::from_pg(Arc::new(db_mock), 1).await;

        assert!(result.is_ok());
        let flag_list = result.unwrap();
        assert_eq!(flag_list.flags.len(), 1);
        let flag = &flag_list.flags[0];
        assert_eq!(flag.id, 1);
        assert_eq!(flag.team_id, 1);
        assert_eq!(flag.name, Some("Test Flag".to_string()));
        assert_eq!(flag.key, "test_flag");
        assert!(!flag.deleted);
        assert!(flag.active);
        assert!(!flag.ensure_experience_continuity);

        assert_eq!(flag.filters.groups.len(), 1);
        let group = &flag.filters.groups[0];
        assert_eq!(group.properties.as_ref().unwrap().len(), 1);
        let property = &group.properties.as_ref().unwrap()[0];
        assert_eq!(property.key, "email");
        assert_eq!(property.value, json!("test@example.com"));
        assert_eq!(property.prop_type, "person");
        assert_eq!(group.rollout_percentage, Some(50.0));
    }

    #[tokio::test]
    async fn test_from_pg_database_unavailable_mocked() {
        let mut db_mock = MockDatabaseClient::new();

        db_mock.expect_run_query().returning(|_, _, _| {
            let rt = Runtime::new().unwrap();
            let elapsed_error = rt.block_on(async {
                let dummy_future = async {};
                timeout(Duration::from_secs(0), dummy_future)
                    .await
                    .unwrap_err()
            });
            Err(CustomDatabaseError::Timeout(elapsed_error))
        });

        let result = FeatureFlagList::from_pg(Arc::new(db_mock), 1).await;

        assert!(matches!(result, Err(FlagError::DatabaseUnavailable)));
    }

    #[tokio::test]
    async fn test_from_pg_data_parsing_error_mocked() {
        let mut db_mock = MockDatabaseClient::new();

        db_mock.expect_run_query().returning(|_, _, _| {
            Ok(vec![FeatureFlagRow {
                id: 1,
                team_id: 1,
                name: Some("Test Flag".to_string()),
                key: "test_flag".to_string(),
                filters: json!({"invalid": "filter"}), // Invalid filter structure
                deleted: false,
                active: true,
                ensure_experience_continuity: false,
            }])
        });

        let result = FeatureFlagList::from_pg(Arc::new(db_mock), 1).await;

        assert!(matches!(result, Err(FlagError::DataParsingError)));
    }
}
