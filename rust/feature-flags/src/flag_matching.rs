use crate::{
    api::{FlagError, FlagValue, FlagsResponse},
    database::Client as DatabaseClient,
    flag_definitions::{FeatureFlag, FeatureFlagList, FlagGroupType, PropertyFilter},
    property_matching::match_property,
};
use anyhow::Result;
use serde_json::Value;
use sha1::{Digest, Sha1};
use sqlx::FromRow;
use std::{
    collections::{HashMap, HashSet},
    fmt::Write,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};
use tokio::sync::RwLock;
use tracing::error;

type TeamId = i32;
type DatabaseClientArc = Arc<dyn DatabaseClient + Send + Sync>;
/// This is an i32 because the group_type_index stored in Postgres is an INT and I wanted to map the Rust
/// type as closely as possible to the database schema so that serialization and deserialization is easy.
/// However, this type really _should_ be an enum, since in Postgres we constaint the values of this field
/// to be INTs between 0 and 4.  Eventually, we should migrate the field in Postgres, and when we do that,
/// I'll change this type to an enum.
type GroupTypeIndex = i32;

#[derive(Debug, PartialEq, Eq)]
pub struct FeatureFlagMatch {
    pub matches: bool,
    pub variant: Option<String>,
    //reason
    //condition_index
    //payload
}

#[derive(Debug, FromRow)]
pub struct Person {
    pub properties: sqlx::types::Json<HashMap<String, Value>>,
}

#[derive(Debug, FromRow)]
pub struct Group {
    pub group_properties: sqlx::types::Json<HashMap<String, Value>>,
}

#[derive(Debug, FromRow)]
pub struct GroupTypeMapping {
    pub group_type: String,
    pub group_type_index: GroupTypeIndex,
}

/// This struct is a cache for group type mappings, which are used to determine which group properties to fetch
pub struct GroupTypeMappingCache {
    team_id: TeamId,
    failed_to_fetch_flags: AtomicBool,
    group_types_to_indexes: Arc<RwLock<Option<HashMap<String, GroupTypeIndex>>>>,
    group_indexes_to_types: Arc<RwLock<Option<HashMap<GroupTypeIndex, String>>>>,
    database_client: Option<DatabaseClientArc>,
}

impl GroupTypeMappingCache {
    pub fn new(team_id: TeamId, database_client: Option<DatabaseClientArc>) -> Self {
        GroupTypeMappingCache {
            team_id,
            failed_to_fetch_flags: AtomicBool::new(false),
            group_types_to_indexes: Arc::new(RwLock::new(None)),
            group_indexes_to_types: Arc::new(RwLock::new(None)),
            database_client,
        }
    }

    async fn group_type_to_group_type_index_map(
        &self,
    ) -> Result<HashMap<String, GroupTypeIndex>, FlagError> {
        if self.database_client.is_none() || self.failed_to_fetch_flags.load(Ordering::Relaxed) {
            return Err(FlagError::DatabaseUnavailable);
        }

        if let Some(cached) = self.group_types_to_indexes.read().await.as_ref() {
            return Ok(cached.clone());
        }

        // double-checked locking pattern
        let mut cache = self.group_types_to_indexes.write().await;
        if let Some(cached) = cache.as_ref() {
            return Ok(cached.clone());
        }

        match self.fetch_group_type_mapping().await {
            Ok(mapping) => {
                *cache = Some(mapping.clone());
                Ok(mapping)
            }
            Err(e) => {
                self.failed_to_fetch_flags.store(true, Ordering::Relaxed);
                Err(e)
            }
        }
    }

    async fn group_type_index_to_group_type_map(
        &self,
    ) -> Result<HashMap<GroupTypeIndex, String>, FlagError> {
        if let Some(cached) = self.group_indexes_to_types.read().await.as_ref() {
            return Ok(cached.clone());
        }

        // If not cached, acquire write lock and check again
        let mut cache = self.group_indexes_to_types.write().await;
        if let Some(cached) = cache.as_ref() {
            return Ok(cached.clone());
        }

        // Derive from group_types_to_indexes
        let types_to_indexes = self.group_type_to_group_type_index_map().await?;
        let result: HashMap<GroupTypeIndex, String> =
            types_to_indexes.into_iter().map(|(k, v)| (v, k)).collect();

        *cache = Some(result.clone());
        Ok(result)
    }

    async fn fetch_group_type_mapping(&self) -> Result<HashMap<String, GroupTypeIndex>, FlagError> {
        let mut conn = self
            .database_client
            .as_ref()
            .ok_or(FlagError::DatabaseUnavailable)?
            .get_connection()
            .await?;

        let query = r#"
            SELECT group_type, group_type_index 
            FROM posthog_grouptypemapping 
            WHERE team_id = $1
        "#;

        let rows = sqlx::query_as::<_, GroupTypeMapping>(query)
            .bind(self.team_id)
            .fetch_all(&mut *conn)
            .await?;

        Ok(rows
            .into_iter()
            .map(|row| (row.group_type, row.group_type_index))
            .collect())
    }
}

#[derive(Default, Debug)]
pub struct PropertiesCache {
    person_properties: Option<HashMap<String, Value>>,
    group_properties: HashMap<GroupTypeIndex, HashMap<String, Value>>,
}

// TODO: Rework FeatureFlagMatcher - python has a pretty awkward interface, where we pass in all flags, and then again
// the flag to match. I don't think there's any reason anymore to store the flags in the matcher, since we can just
// pass the flag to match directly to the get_match method. This will also make the matcher more stateless.
// Potentially, we could also make the matcher a long-lived object, with caching for group keys and such.
// It just takes in the flag and distinct_id and returns the match...
// Or, make this fully stateless
// and have a separate cache struct for caching group keys, cohort definitions, etc. - and check size, if we can keep it in memory
// for all teams. If not, we can have a LRU cache, or a cache that stores only the most recent N keys.
// But, this can be a future refactor, for now just focusing on getting the basic matcher working, write lots and lots of tests
// and then we can easily refactor stuff around.
#[derive(Clone)]
pub struct FeatureFlagMatcher {
    pub distinct_id: String,
    pub team_id: TeamId,
    pub database_client: Option<DatabaseClientArc>,
    person_property_overrides: Option<HashMap<String, Value>>,
    group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    group_type_mapping_cache: Arc<GroupTypeMappingCache>,
    properties_cache: Arc<RwLock<PropertiesCache>>,
    #[cfg(test)]
    test_hash: Option<f64>,
}

const LONG_SCALE: u64 = 0xfffffffffffffff;

impl FeatureFlagMatcher {
    pub fn new(
        distinct_id: String,
        team_id: TeamId,
        database_client: Option<DatabaseClientArc>,
        person_property_overrides: Option<HashMap<String, Value>>,
        group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
        group_type_mapping_cache: Option<Arc<GroupTypeMappingCache>>,
        properties_cache: Option<Arc<RwLock<PropertiesCache>>>,
    ) -> Self {
        FeatureFlagMatcher {
            distinct_id,
            team_id,
            database_client: database_client.clone(),
            person_property_overrides,
            group_property_overrides,
            group_type_mapping_cache: group_type_mapping_cache
                .unwrap_or_else(|| Arc::new(GroupTypeMappingCache::new(team_id, database_client))),
            properties_cache: properties_cache
                .unwrap_or_else(|| Arc::new(RwLock::new(PropertiesCache::default()))),
            #[cfg(test)]
            test_hash: None,
        }
    }

    /// Evaluate feature flags for a given distinct_id
    /// - Returns a map of feature flag keys to their values
    /// - If an error occurs while evaluating a flag, it will be logged and the flag will be omitted from the result
    pub async fn evaluate_feature_flags(
        &mut self,
        feature_flags: FeatureFlagList,
    ) -> FlagsResponse {
        let mut result = HashMap::new();
        let mut error_while_computing_flags = false;

        // Step 2: Fetch and cache all relevant person and group properties
        // If we fail to fetch properties, we'll return an error response immediately
        if let Err(e) = self
            .fetch_and_cache_properties(
                &feature_flags
                    .flags
                    .iter()
                    .filter_map(|flag| flag.get_group_type_index())
                    .collect(),
            )
            .await
        {
            error_while_computing_flags = true;
            error!("Error fetching properties: {:?}", e);
            return FlagsResponse {
                error_while_computing_flags,
                feature_flags: result,
            };
        }

        // Step 3: Evaluate each flag
        for flag in feature_flags.flags {
            if !flag.active || flag.deleted {
                continue;
            }

            match self.get_match(&flag).await {
                Ok(flag_match) => {
                    let flag_value = if flag_match.matches {
                        match flag_match.variant {
                            Some(variant) => FlagValue::String(variant),
                            None => FlagValue::Boolean(true),
                        }
                    } else {
                        FlagValue::Boolean(false)
                    };
                    result.insert(flag.key.clone(), flag_value);
                }
                Err(e) => {
                    error_while_computing_flags = true;
                    error!(
                        "Error evaluating feature flag '{}' for distinct_id '{}': {:?}",
                        flag.key, self.distinct_id, e
                    );
                }
            }
        }

        FlagsResponse {
            error_while_computing_flags,
            feature_flags: result,
        }
    }

    async fn fetch_and_cache_properties(
        &self,
        group_type_indexes: &HashSet<GroupTypeIndex>,
    ) -> Result<(), FlagError> {
        if self.database_client.is_none() {
            error!("Database client is None");
            return Err(FlagError::DatabaseUnavailable);
        }

        let mut conn = self
            .database_client
            .as_ref()
            .expect("client should exist here")
            .get_connection()
            .await?;

        let query = r#"
            WITH person_props AS (
                SELECT "posthog_person"."properties" as person_properties
                FROM "posthog_person"
                INNER JOIN "posthog_persondistinctid" ON ("posthog_person"."id" = "posthog_persondistinctid"."person_id")
                WHERE ("posthog_persondistinctid"."distinct_id" = $1
                        AND "posthog_persondistinctid"."team_id" = $2
                        AND "posthog_person"."team_id" = $2)
                LIMIT 1
            ),
            group_props AS (
                SELECT "posthog_group"."group_type_index", "posthog_group"."group_properties"
                FROM "posthog_group"
                WHERE ("posthog_group"."team_id" = $2
                        AND "posthog_group"."group_type_index" = ANY($3))
            )
            SELECT 
                (SELECT person_properties FROM person_props) as person_properties,
                (SELECT json_object_agg(group_type_index, group_properties) FROM group_props) as group_properties
        "#;

        let group_type_indexes_vec: Vec<GroupTypeIndex> =
            group_type_indexes.iter().cloned().collect();

        let row: (Option<Value>, Option<Value>) = sqlx::query_as(query)
            .bind(&self.distinct_id)
            .bind(self.team_id)
            .bind(&group_type_indexes_vec)
            .fetch_optional(&mut *conn)
            .await?
            .unwrap_or((None, None));

        let mut cache = self.properties_cache.write().await;

        if let Some(person_props) = row.0 {
            cache.person_properties = Some(
                person_props
                    .as_object()
                    .unwrap()
                    .iter()
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect(),
            );
        }

        if let Some(group_props) = row.1 {
            let group_props_map: HashMap<GroupTypeIndex, HashMap<String, Value>> = group_props
                .as_object()
                .unwrap()
                .iter()
                .map(|(k, v)| {
                    let group_type_index = k.parse().unwrap();
                    let properties: HashMap<String, Value> = v
                        .as_object()
                        .unwrap()
                        .iter()
                        .map(|(k, v)| (k.clone(), v.clone()))
                        .collect();
                    (group_type_index, properties)
                })
                .collect();

            cache.group_properties.extend(group_props_map);
        }

        Ok(())
    }

    async fn fetch_person_properties_from_db(&self) -> Result<HashMap<String, Value>, FlagError> {
        if self.database_client.is_none() {
            error!("Database client is None");
            return Err(FlagError::DatabaseUnavailable);
        }

        let mut conn = self
            .database_client
            .as_ref()
            .expect("client should exist here")
            .get_connection()
            .await?;

        let query = r#"
            SELECT "posthog_person"."properties" as person_properties
            FROM "posthog_person"
            INNER JOIN "posthog_persondistinctid" ON ("posthog_person"."id" = "posthog_persondistinctid"."person_id")
            WHERE ("posthog_persondistinctid"."distinct_id" = $1
                    AND "posthog_persondistinctid"."team_id" = $2
                    AND "posthog_person"."team_id" = $2)
            LIMIT 1
        "#;

        let row: Option<Value> = sqlx::query_scalar(query)
            .bind(&self.distinct_id)
            .bind(self.team_id)
            .fetch_optional(&mut *conn)
            .await?;

        Ok(row
            .and_then(|v| v.as_object().cloned())
            .unwrap_or_default()
            .into_iter()
            .map(|(k, v)| (k, v.clone()))
            .collect())
    }

    async fn fetch_group_properties_from_db(
        &self,
        group_type_index: GroupTypeIndex,
    ) -> Result<HashMap<String, Value>, FlagError> {
        if self.database_client.is_none() {
            error!("Database client is None");
            return Err(FlagError::DatabaseUnavailable);
        }

        let mut conn = self
            .database_client
            .as_ref()
            .expect("client should exist here")
            .get_connection()
            .await?;

        let query = r#"
            SELECT "posthog_group"."group_properties"
            FROM "posthog_group"
            WHERE ("posthog_group"."team_id" = $1
                    AND "posthog_group"."group_type_index" = $2)
            LIMIT 1
        "#;

        let row: Option<Value> = sqlx::query_scalar(query)
            .bind(self.team_id)
            .bind(group_type_index)
            .fetch_optional(&mut *conn)
            .await?;

        Ok(row
            .and_then(|v| v.as_object().cloned())
            .unwrap_or_default()
            .into_iter()
            .map(|(k, v)| (k, v.clone()))
            .collect())
    }

    pub async fn get_match(&mut self, flag: &FeatureFlag) -> Result<FeatureFlagMatch, FlagError> {
        if self.hashed_identifier(flag).await?.is_empty() {
            return Ok(FeatureFlagMatch {
                matches: false,
                variant: None,
            });
        }

        for (index, condition) in flag.get_conditions().iter().enumerate() {
            let (is_match, _evaluation_reason) =
                self.is_condition_match(flag, condition, index).await?;

            if is_match {
                let variant = match condition.variant.clone() {
                    Some(variant_override)
                        if flag
                            .get_variants()
                            .iter()
                            .any(|v| v.key == variant_override) =>
                    {
                        Some(variant_override)
                    }
                    _ => self.get_matching_variant(flag).await?,
                };

                return Ok(FeatureFlagMatch {
                    matches: true,
                    variant,
                });
            }
        }

        Ok(FeatureFlagMatch {
            matches: false,
            variant: None,
        })
    }

    async fn check_rollout(
        &self,
        feature_flag: &FeatureFlag,
        rollout_percentage: f64,
    ) -> Result<(bool, String), FlagError> {
        if rollout_percentage == 100.0
            || self.get_hash(feature_flag, "").await? <= (rollout_percentage / 100.0)
        {
            Ok((true, "CONDITION_MATCH".to_string())) // TODO enum, I'll implement this when I implement evaluation reasons
        } else {
            Ok((false, "OUT_OF_ROLLOUT_BOUND".to_string())) // TODO enum, I'll implement this when I implement evaluation reasons
        }
    }

    async fn is_condition_match(
        &self,
        feature_flag: &FeatureFlag,
        condition: &FlagGroupType,
        _index: usize,
    ) -> Result<(bool, String), FlagError> {
        let rollout_percentage = condition.rollout_percentage.unwrap_or(100.0);

        if let Some(flag_property_filters) = &condition.properties {
            if flag_property_filters.is_empty() {
                return self.check_rollout(feature_flag, rollout_percentage).await;
            }

            let target_properties =
                if let Some(group_type_index) = feature_flag.get_group_type_index() {
                    self.get_group_properties(group_type_index, flag_property_filters)
                        .await?
                } else {
                    self.get_person_properties(flag_property_filters).await?
                };

            if !all_properties_match(flag_property_filters, &target_properties) {
                return Ok((false, "NO_CONDITION_MATCH".to_string()));
            }
        }

        self.check_rollout(feature_flag, rollout_percentage).await
    }

    async fn get_group_properties(
        &self,
        group_type_index: GroupTypeIndex,
        flag_property_filters: &[PropertyFilter],
    ) -> Result<HashMap<String, Value>, FlagError> {
        let index_to_type_map = self
            .group_type_mapping_cache
            .group_type_index_to_group_type_map()
            .await?;

        let group_type = index_to_type_map.get(&group_type_index).cloned();

        if let Some(group_type) = group_type {
            if let Some(override_properties) = self
                .group_property_overrides
                .as_ref()
                .and_then(|overrides| overrides.get(&group_type))
            {
                if let Some(local_overrides) = can_compute_property_overrides_locally(
                    &Some(override_properties.clone()),
                    flag_property_filters,
                ) {
                    return Ok(local_overrides);
                }
            }
        }

        let cache = self.properties_cache.read().await;
        if let Some(properties) = cache.group_properties.get(&group_type_index).cloned() {
            return Ok(properties);
        }
        drop(cache);

        let db_properties = self
            .fetch_group_properties_from_db(group_type_index)
            .await?;
        let mut cache = self.properties_cache.write().await;
        cache
            .group_properties
            .insert(group_type_index, db_properties.clone());

        Ok(db_properties)
    }

    async fn get_person_properties(
        &self,
        flag_property_filters: &[PropertyFilter],
    ) -> Result<HashMap<String, Value>, FlagError> {
        if let Some(overrides) = can_compute_property_overrides_locally(
            &self.person_property_overrides,
            flag_property_filters,
        ) {
            return Ok(overrides);
        }

        let cache = self.properties_cache.read().await;
        if let Some(properties) = cache.person_properties.clone() {
            return Ok(properties);
        }
        drop(cache);

        let db_properties = self.fetch_person_properties_from_db().await?;
        let mut cache = self.properties_cache.write().await;
        cache.person_properties = Some(db_properties.clone());

        Ok(db_properties)
    }

    /// This function takes a feature flag and returns the hashed identifier for the flag.
    /// If the flag has a group type index, it returns the group type name, otherwise it returns the distinct_id.
    pub async fn hashed_identifier(&self, feature_flag: &FeatureFlag) -> Result<String, FlagError> {
        if let Some(group_type_index) = feature_flag.get_group_type_index() {
            // TODO: Use hash key overrides for experience continuity
            let indexes_to_names = self
                .group_type_mapping_cache
                .group_type_index_to_group_type_map()
                .await?;
            Ok(indexes_to_names
                .get(&group_type_index)
                .cloned()
                .unwrap_or_default())
        } else {
            Ok(self.distinct_id.clone())
        }
    }

    #[cfg(test)]
    pub fn with_test_hash(mut self, hash: f64) -> Self {
        self.test_hash = Some(hash);
        self
    }

    /// This function takes a identifier and a feature flag key and returns a float between 0 and 1.
    /// Given the same identifier and key, it'll always return the same float. These floats are
    /// uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    /// we can do _hash(key, identifier) < 0.2
    async fn get_hash(&self, feature_flag: &FeatureFlag, salt: &str) -> Result<f64, FlagError> {
        #[cfg(test)]
        if let Some(test_hash) = self.test_hash {
            return Ok(test_hash);
        }
        let hashed_identifier = self.hashed_identifier(feature_flag).await?;
        let hash_key = format!("{}.{}{}", feature_flag.key, hashed_identifier, salt);
        let mut hasher = Sha1::new();
        hasher.update(hash_key.as_bytes());
        let result = hasher.finalize();
        // :TRICKY: Convert the first 15 characters of the digest to a hexadecimal string
        let hex_str: String = result.iter().fold(String::new(), |mut acc, byte| {
            let _ = write!(acc, "{:02x}", byte);
            acc
        })[..15]
            .to_string();
        let hash_val = u64::from_str_radix(&hex_str, 16).unwrap();

        Ok(hash_val as f64 / LONG_SCALE as f64)
    }

    /// This function takes a feature flag and returns the key of the variant that should be shown to the user.
    pub async fn get_matching_variant(
        &self,
        feature_flag: &FeatureFlag,
    ) -> Result<Option<String>, FlagError> {
        let hash = self.get_hash(feature_flag, "variant").await?;
        let mut cumulative_percentage = 0.0;

        println!("Hash: {}", hash); // Debug print

        for variant in feature_flag.get_variants() {
            cumulative_percentage += variant.rollout_percentage / 100.0;
            println!(
                "Variant: {}, Cumulative Percentage: {}",
                variant.key, cumulative_percentage
            ); // Debug print
            if hash < cumulative_percentage {
                return Ok(Some(variant.key.clone()));
            }
        }
        Ok(None)
    }
}

/// Check if all required properties are present in the overrides
/// and none of them are of type "cohort" – if so, return the overrides,
/// otherwise return None, because we can't locally compute cohort properties
fn can_compute_property_overrides_locally(
    property_overrides: &Option<HashMap<String, Value>>,
    property_filters: &[PropertyFilter],
) -> Option<HashMap<String, Value>> {
    property_overrides.as_ref().and_then(|person_overrides| {
        // TODO handle note from Neil: https://github.com/PostHog/posthog/pull/24589#discussion_r1735828561
        // TL;DR – we'll need to handle cohort properties at the DB level, i.e. we'll need to adjust the cohort query
        // to account for if a given person is an element of the cohort X, Y, Z, etc
        let should_prefer_overrides = property_filters
            .iter()
            .all(|prop| person_overrides.contains_key(&prop.key) && prop.prop_type != "cohort");

        if should_prefer_overrides {
            Some(person_overrides.clone())
        } else {
            None
        }
    })
}

/// Check if all required properties are present in the overrides
/// and none of them are of type "cohort" – if so, return the overrides,
/// otherwise return None, because we can't locally compute cohort properties
fn all_properties_match(
    flag_condition_properties: &[PropertyFilter],
    target_properties: &HashMap<String, Value>,
) -> bool {
    flag_condition_properties
        .iter()
        .all(|property| match_property(property, target_properties, false).unwrap_or(false))
}

#[cfg(test)]
mod tests {

    use serde_json::json;

    use super::*;
    use crate::{
        flag_definitions::{
            FlagFilters, MultivariateFlagOptions, MultivariateFlagVariant, OperatorType,
        },
        test_utils::{insert_new_team_in_pg, insert_person_for_team_in_pg, setup_pg_client},
    };

    fn create_test_flag(team_id: TeamId, properties: Vec<PropertyFilter>) -> FeatureFlag {
        FeatureFlag {
            id: 1,
            team_id,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(properties),
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
        }
    }

    #[tokio::test]
    async fn test_fetch_properties_from_pg_to_match() {
        let client = setup_pg_client(None).await;

        let team = insert_new_team_in_pg(client.clone())
            .await
            .expect("Failed to insert team in pg");

        let distinct_id = "user_distinct_id".to_string();
        insert_person_for_team_in_pg(client.clone(), team.id, distinct_id.clone(), None)
            .await
            .expect("Failed to insert person");

        let not_matching_distinct_id = "not_matching_distinct_id".to_string();
        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            not_matching_distinct_id.clone(),
            Some(json!({ "email": "a@x.com"})),
        )
        .await
        .expect("Failed to insert person");

        let flag = serde_json::from_value(json!(
            {
                "id": 1,
                "team_id": team.id,
                "name": "flag1",
                "key": "flag1",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "a@b.com",
                                    "type": "person"
                                }
                            ],
                            "rollout_percentage": 100
                        }
                    ]
                }
            }
        ))
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id,
            team.id,
            Some(client.clone()),
            None,
            None,
            None,
            None,
        );
        let match_result = matcher.get_match(&flag).await.unwrap();
        assert_eq!(match_result.matches, true);
        assert_eq!(match_result.variant, None);

        // property value is different
        let mut matcher = FeatureFlagMatcher::new(
            not_matching_distinct_id,
            team.id,
            Some(client.clone()),
            None,
            None,
            None,
            None,
        );
        let match_result = matcher.get_match(&flag).await.unwrap();
        assert_eq!(match_result.matches, false);
        assert_eq!(match_result.variant, None);

        // person does not exist
        let mut matcher = FeatureFlagMatcher::new(
            "other_distinct_id".to_string(),
            1,
            Some(client.clone()),
            None,
            None,
            None,
            None,
        );
        let match_result = matcher.get_match(&flag).await.unwrap();
        assert_eq!(match_result.matches, false);
        assert_eq!(match_result.variant, None);
    }

    #[tokio::test]
    async fn test_person_property_overrides() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag(
            team.id,
            vec![PropertyFilter {
                key: "email".to_string(),
                value: json!("override@example.com"),
                operator: None,
                prop_type: "email".to_string(),
                group_type_index: None,
            }],
        );

        let overrides = HashMap::from([("email".to_string(), json!("override@example.com"))]);

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            Some(client.clone()),
            Some(overrides),
            None,
            None,
            None,
        );

        let match_result = matcher.get_match(&flag).await.unwrap();
        assert_eq!(match_result.matches, true);
    }

    #[tokio::test]
    async fn test_hashed_identifier() {
        let flag = create_test_flag(1, vec![]);
        let database_client = setup_pg_client(None).await;

        // Create a FlagsMatcherCache with pre-populated group type mappings
        let cache = Arc::new(GroupTypeMappingCache::new(1, Some(database_client.clone())));
        let mut group_types_to_indexes = HashMap::new();
        group_types_to_indexes.insert("group_type_1".to_string(), 1);
        *cache.group_types_to_indexes.write().await = Some(group_types_to_indexes);

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            Some(database_client.clone()),
            None,
            None,
            Some(cache.clone()),
            None,
        );
        assert_eq!(
            matcher.hashed_identifier(&flag).await.unwrap(),
            "test_user".to_string()
        );

        // Test with a group type index
        let mut group_flag = flag.clone();
        group_flag.filters.aggregation_group_type_index = Some(1);
        assert_eq!(
            matcher.hashed_identifier(&group_flag).await.unwrap(),
            "group_type_1".to_string()
        );
    }

    #[tokio::test]
    async fn test_get_matching_variant_with_cache() {
        let flag = create_test_flag_with_variants(1);
        let database_client = setup_pg_client(None).await;

        // Create a FlagsMatcherCache with pre-populated group type mappings
        let cache = Arc::new(GroupTypeMappingCache::new(1, Some(database_client.clone())));

        let group_types_to_indexes = [("group_type_1".to_string(), 1)].into_iter().collect();
        let group_type_index_to_name = [(1, "group_type_1".to_string())].into_iter().collect();

        *cache.group_types_to_indexes.write().await = Some(group_types_to_indexes);
        *cache.group_indexes_to_types.write().await = Some(group_type_index_to_name);

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            Some(database_client.clone()),
            None,
            None,
            Some(cache.clone()),
            None,
        );
        let variant = matcher.get_matching_variant(&flag).await.unwrap();
        assert!(variant.is_some(), "No variant was selected");
        assert!(
            ["control", "test", "test2"].contains(&variant.unwrap().as_str()),
            "Selected variant is not one of the expected options"
        );
    }

    #[tokio::test]
    async fn test_get_matching_variant_with_db() {
        let database_client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(database_client.clone())
            .await
            .unwrap();

        let flag = create_test_flag_with_variants(team.id);

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(database_client.clone()),
            None,
            None,
            None,
            None,
        );

        let variant = matcher.get_matching_variant(&flag).await.unwrap();
        assert!(variant.is_some());
        assert!(["control", "test", "test2"].contains(&variant.unwrap().as_str()));
    }

    #[tokio::test]
    async fn test_is_condition_match_empty_properties() {
        let flag = create_test_flag(1, vec![]);

        let condition = FlagGroupType {
            variant: None,
            properties: Some(vec![]),
            rollout_percentage: Some(100.0),
        };

        let matcher =
            FeatureFlagMatcher::new("test_user".to_string(), 1, None, None, None, None, None);
        let (is_match, reason) = matcher
            .is_condition_match(&flag, &condition, 0)
            .await
            .unwrap();
        assert_eq!(is_match, true);
        assert_eq!(reason, "CONDITION_MATCH");
    }

    #[tokio::test]
    async fn test_hashed_identifier_with_db() {
        let database_client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(database_client.clone())
            .await
            .unwrap();

        let flag = create_test_flag(team.id, vec![]);
        let mut group_flag = flag.clone();
        group_flag.filters.aggregation_group_type_index = Some(1);

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(database_client.clone()),
            None,
            None,
            None,
            None,
        );

        assert_eq!(
            matcher.hashed_identifier(&flag).await.unwrap(),
            "test_user".to_string()
        );
        assert_eq!(
            matcher.hashed_identifier(&group_flag).await.unwrap(),
            "organization".to_string()
        );
    }

    fn create_test_flag_with_variants(team_id: TeamId) -> FeatureFlag {
        FeatureFlag {
            id: 1,
            team_id,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: FlagFilters {
                groups: vec![FlagGroupType {
                    properties: None,
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            name: Some("Control".to_string()),
                            key: "control".to_string(),
                            rollout_percentage: 33.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Test".to_string()),
                            key: "test".to_string(),
                            rollout_percentage: 33.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Test2".to_string()),
                            key: "test2".to_string(),
                            rollout_percentage: 34.0,
                        },
                    ],
                }),
                aggregation_group_type_index: Some(1),
                payloads: None,
                super_groups: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: false,
        }
    }

    #[tokio::test]
    async fn test_evaluate_feature_flags() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let active_flag = create_test_flag(team.id, vec![]);
        let mut inactive_flag = create_test_flag(team.id, vec![]);
        inactive_flag.active = false;

        let mut group_flag = create_test_flag(team.id, vec![]);
        group_flag.filters.aggregation_group_type_index = Some(1);
        group_flag.key = "group_flag".to_string();

        let flags = FeatureFlagList {
            flags: vec![active_flag, inactive_flag, group_flag],
        };

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(client.clone()),
            None,
            None,
            None,
            None,
        );

        let result = matcher.evaluate_feature_flags(flags).await;

        println!("Resulting flags: {:?}", result.feature_flags);
        println!(
            "Error while computing: {}",
            result.error_while_computing_flags
        );

        assert_eq!(
            result.feature_flags.len(),
            2,
            "Expected 2 flags, got {}",
            result.feature_flags.len()
        );
        assert!(
            result.feature_flags.contains_key("test_flag"),
            "Missing test_flag"
        );
        assert!(
            result.feature_flags.contains_key("group_flag"),
            "Missing group_flag"
        );
        assert!(!result.error_while_computing_flags);
    }

    #[tokio::test]
    async fn test_get_match_multiple_conditions() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let mut flag = create_test_flag(team.id, vec![]);
        flag.filters.groups = vec![
            FlagGroupType {
                properties: Some(vec![PropertyFilter {
                    key: "email".to_string(),
                    value: json!("test@example.com"),
                    operator: None,
                    prop_type: "person".to_string(),
                    group_type_index: None,
                }]),
                rollout_percentage: Some(50.0),
                variant: None,
            },
            FlagGroupType {
                properties: Some(vec![PropertyFilter {
                    key: "country".to_string(),
                    value: json!("US"),
                    operator: None,
                    prop_type: "person".to_string(),
                    group_type_index: None,
                }]),
                rollout_percentage: Some(100.0),
                variant: None,
            },
        ];

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(client.clone()),
            Some(HashMap::from([
                ("email".to_string(), json!("test@example.com")),
                ("country".to_string(), json!("US")),
            ])),
            None,
            None,
            None,
        );

        let match_result = matcher.get_match(&flag).await.unwrap();
        assert!(match_result.matches);
    }

    #[tokio::test]
    async fn test_check_rollout() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag(team.id, vec![]);
        let base_matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(client.clone()),
            None,
            None,
            None,
            None,
        );

        // Test 0% rollout
        let matcher = base_matcher.clone().with_test_hash(0.5);
        let (is_match, reason) = matcher.check_rollout(&flag, 0.0).await.unwrap();
        assert!(!is_match);
        assert_eq!(reason, "OUT_OF_ROLLOUT_BOUND");

        // Test 100% rollout
        let matcher = base_matcher.clone().with_test_hash(0.99);
        let (is_match, reason) = matcher.check_rollout(&flag, 100.0).await.unwrap();
        assert!(is_match);
        assert_eq!(reason, "CONDITION_MATCH");

        // Test 50% rollout
        // User just within the rollout
        let matcher = base_matcher.clone().with_test_hash(0.49);
        let (is_match, reason) = matcher.check_rollout(&flag, 50.0).await.unwrap();
        assert!(is_match);
        assert_eq!(reason, "CONDITION_MATCH");

        // User just outside the rollout
        let matcher = base_matcher.clone().with_test_hash(0.51);
        let (is_match, reason) = matcher.check_rollout(&flag, 50.0).await.unwrap();
        assert!(!is_match);
        assert_eq!(reason, "OUT_OF_ROLLOUT_BOUND");

        // Edge cases
        // Test with 0.0 hash (should always be in rollout except for 0%)
        let matcher = base_matcher.clone().with_test_hash(0.0);
        let (is_match, _) = matcher.check_rollout(&flag, 0.1).await.unwrap();
        assert!(is_match);

        // Test with 0.99999 hash (should only be in rollout for 100%)
        let matcher = base_matcher.clone().with_test_hash(0.99999);
        let (is_match, _) = matcher.check_rollout(&flag, 99.9).await.unwrap();
        assert!(!is_match);
        let (is_match, _) = matcher.check_rollout(&flag, 100.0).await.unwrap();
        assert!(is_match);
    }

    #[tokio::test]
    async fn test_is_condition_match_complex() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag(team.id, vec![]);
        let condition = FlagGroupType {
            properties: Some(vec![
                PropertyFilter {
                    key: "email".to_string(),
                    value: json!("test@example.com"),
                    operator: Some(OperatorType::Exact),
                    prop_type: "person".to_string(),
                    group_type_index: None,
                },
                PropertyFilter {
                    key: "age".to_string(),
                    value: json!(25),
                    operator: Some(OperatorType::Gte),
                    prop_type: "person".to_string(),
                    group_type_index: None,
                },
            ]),
            rollout_percentage: Some(50.0),
            variant: None,
        };

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(client.clone()),
            Some(HashMap::from([
                ("email".to_string(), json!("test@example.com")),
                ("age".to_string(), json!(30)),
            ])),
            None,
            None,
            None,
        )
        .with_test_hash(0.4); // Set a hash value that falls within the 50% rollout

        let (is_match, reason) = matcher
            .is_condition_match(&flag, &condition, 0)
            .await
            .unwrap();

        assert!(
            is_match,
            "Expected a match, but got: is_match = {}, reason = {}",
            is_match, reason
        );

        // Test with a hash value outside the rollout percentage
        let matcher_outside_rollout = matcher.with_test_hash(0.6);
        let (is_match, reason) = matcher_outside_rollout
            .is_condition_match(&flag, &condition, 0)
            .await
            .unwrap();

        assert!(
            !is_match,
            "Expected no match due to rollout, but got: is_match = {}, reason = {}",
            is_match, reason
        );
    }
    #[tokio::test]
    async fn test_property_fetching_and_caching() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let distinct_id = "test_user".to_string();
        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "test@example.com", "age": 30})),
        )
        .await
        .unwrap();

        let matcher = FeatureFlagMatcher::new(
            distinct_id,
            team.id,
            Some(client.clone()),
            None,
            None,
            None,
            None,
        );

        let properties = matcher
            .get_person_properties(&[PropertyFilter {
                key: "email".to_string(),
                value: json!("test@example.com"),
                operator: None,
                prop_type: "person".to_string(),
                group_type_index: None,
            }])
            .await
            .unwrap();

        assert_eq!(properties.get("email").unwrap(), &json!("test@example.com"));
        assert_eq!(properties.get("age").unwrap(), &json!(30));

        // Check if properties are cached
        let cached_properties = matcher
            .properties_cache
            .read()
            .await
            .person_properties
            .clone();
        assert!(cached_properties.is_some());
        assert_eq!(
            cached_properties.unwrap().get("email").unwrap(),
            &json!("test@example.com")
        );
    }

    #[tokio::test]
    async fn test_can_compute_property_overrides_locally() {
        let overrides = Some(HashMap::from([
            ("email".to_string(), json!("test@example.com")),
            ("age".to_string(), json!(30)),
        ]));

        let property_filters = vec![
            PropertyFilter {
                key: "email".to_string(),
                value: json!("test@example.com"),
                operator: None,
                prop_type: "person".to_string(),
                group_type_index: None,
            },
            PropertyFilter {
                key: "age".to_string(),
                value: json!(25),
                operator: Some(OperatorType::Gte),
                prop_type: "person".to_string(),
                group_type_index: None,
            },
        ];

        let result = can_compute_property_overrides_locally(&overrides, &property_filters);
        assert!(result.is_some());

        let property_filters_with_cohort = vec![
            PropertyFilter {
                key: "email".to_string(),
                value: json!("test@example.com"),
                operator: None,
                prop_type: "person".to_string(),
                group_type_index: None,
            },
            PropertyFilter {
                key: "cohort".to_string(),
                value: json!(1),
                operator: None,
                prop_type: "cohort".to_string(),
                group_type_index: None,
            },
        ];

        let result =
            can_compute_property_overrides_locally(&overrides, &property_filters_with_cohort);
        assert!(result.is_none());
    }

    #[tokio::test]
    async fn test_all_properties_match() {
        let properties = HashMap::from([
            ("email".to_string(), json!("test@example.com")),
            ("age".to_string(), json!(30)),
            ("country".to_string(), json!("US")),
        ]);

        let matching_filters = vec![
            PropertyFilter {
                key: "email".to_string(),
                value: json!("test@example.com"),
                operator: Some(OperatorType::Exact),
                prop_type: "person".to_string(),
                group_type_index: None,
            },
            PropertyFilter {
                key: "age".to_string(),
                value: json!(25),
                operator: Some(OperatorType::Gte),
                prop_type: "person".to_string(),
                group_type_index: None,
            },
        ];

        assert!(all_properties_match(&matching_filters, &properties));

        let non_matching_filters = vec![
            PropertyFilter {
                key: "email".to_string(),
                value: json!("test@example.com"),
                operator: Some(OperatorType::Exact),
                prop_type: "person".to_string(),
                group_type_index: None,
            },
            PropertyFilter {
                key: "country".to_string(),
                value: json!("UK"),
                operator: Some(OperatorType::Exact),
                prop_type: "person".to_string(),
                group_type_index: None,
            },
        ];

        assert!(!all_properties_match(&non_matching_filters, &properties));
    }

    #[tokio::test]
    async fn test_error_handling() {
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            None, // No database client
            None,
            None,
            None,
            None,
        );

        let flag = create_test_flag(
            1,
            vec![PropertyFilter {
                key: "email".to_string(),
                value: json!("test@example.com"),
                operator: None,
                prop_type: "person".to_string(),
                group_type_index: None,
            }],
        );

        let result = matcher.get_match(&flag).await;
        assert!(matches!(result, Err(FlagError::DatabaseUnavailable)));
    }

    #[tokio::test]
    async fn test_multivariate_flag_distribution() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag_with_variants(team.id);

        // Verify flag setup
        assert_eq!(flag.get_variants().len(), 3, "Flag should have 3 variants");
        assert_eq!(flag.get_variants()[0].rollout_percentage, 33.0);
        assert_eq!(flag.get_variants()[1].rollout_percentage, 33.0);
        assert_eq!(flag.get_variants()[2].rollout_percentage, 34.0);

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(client.clone()),
            None,
            None,
            None,
            None,
        );

        let hash = matcher.get_hash(&flag, "variant").await.unwrap();
        assert!(hash >= 0.0 && hash <= 1.0, "Hash should be between 0 and 1");

        let variant = matcher.get_matching_variant(&flag).await.unwrap();
        assert!(variant.is_some(), "A variant should be selected");

        // Test with specific hash values
        let test_cases = [
            (0.1, "control"),
            (0.3, "control"),
            (0.5, "test"),
            (0.7, "test2"),
            (0.9, "test2"),
        ];

        for (test_hash, expected_variant) in test_cases.iter() {
            let test_matcher = matcher.clone().with_test_hash(*test_hash);
            let test_variant = test_matcher.get_matching_variant(&flag).await.unwrap();
            assert_eq!(
                test_variant.as_deref(),
                Some(*expected_variant),
                "For hash {}, expected variant {}",
                test_hash,
                expected_variant
            );
        }

        // Test distribution over 100 iterations
        let mut variant_counts: HashMap<String, i32> = HashMap::new();
        let iterations = 100;

        for i in 0..iterations {
            let test_hash = i as f64 / iterations as f64;
            let test_matcher = matcher.clone().with_test_hash(test_hash);
            let test_variant = test_matcher.get_matching_variant(&flag).await.unwrap();
            if let Some(variant) = test_variant.as_ref() {
                *variant_counts.entry(variant.clone()).or_insert(0) += 1;
            }
        }

        assert_eq!(
            variant_counts.len(),
            3,
            "All 3 variants should be represented"
        );

        let control_count = *variant_counts.get("control").unwrap_or(&0);
        let test_count = *variant_counts.get("test").unwrap_or(&0);
        let test2_count = *variant_counts.get("test2").unwrap_or(&0);

        // With only 100 iterations, we'll use a larger tolerance
        let tolerance: i32 = 10; // Allow for more variance with fewer iterations

        assert!(
            (control_count - 33_i32).abs() <= tolerance,
            "Control count {} should be close to 33",
            control_count
        );
        assert!(
            (test_count - 33_i32).abs() <= tolerance,
            "Test count {} should be close to 33",
            test_count
        );
        assert!(
            (test2_count - 34_i32).abs() <= tolerance,
            "Test2 count {} should be close to 34",
            test2_count
        );
    }
    #[tokio::test]
    async fn test_concurrent_flag_evaluation() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();
        let flag = Arc::new(create_test_flag(team.id, vec![]));

        let mut handles = vec![];
        for i in 0..100 {
            let flag_clone = flag.clone();
            let client_clone = client.clone();
            handles.push(tokio::spawn(async move {
                let mut matcher = FeatureFlagMatcher::new(
                    format!("test_user_{}", i),
                    team.id,
                    Some(client_clone),
                    None,
                    None,
                    None,
                    None,
                );
                matcher.get_match(&flag_clone).await.unwrap()
            }));
        }

        let results: Vec<FeatureFlagMatch> = futures::future::join_all(handles)
            .await
            .into_iter()
            .map(|r| r.unwrap())
            .collect();

        // Check that all evaluations completed without errors
        assert_eq!(results.len(), 100);
    }
}
