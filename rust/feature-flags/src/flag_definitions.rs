use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tracing::instrument;

use crate::{api::FlagError, database::Client as DatabaseClient, redis::Client as RedisClient};

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
        let mut conn = client.get_connection().await?;
        // TODO: Clean up error handling here

        let query = "SELECT id, team_id, name, key, filters, deleted, active, ensure_experience_continuity FROM posthog_featureflag WHERE team_id = $1";
        let flags_row = sqlx::query_as::<_, FeatureFlagRow>(query)
            .bind(team_id)
            .fetch_all(&mut *conn)
            .await?;

        let serialized_flags = serde_json::to_string(&flags_row).map_err(|e| {
            tracing::error!("failed to serialize flags: {}", e);
            println!("failed to serialize flags: {}", e);
            FlagError::DataParsingError
        })?;

        let flags_list: Vec<FeatureFlag> =
            serde_json::from_str(&serialized_flags).map_err(|e| {
                tracing::error!("failed to parse data to flags list: {}", e);
                println!("failed to parse data: {}", e);

                FlagError::DataParsingError
            })?;
        Ok(FeatureFlagList { flags: flags_list })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
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
}
