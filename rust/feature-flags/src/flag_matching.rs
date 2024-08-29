use crate::{
    api::FlagError,
    database::Client as DatabaseClient,
    flag_definitions::{FeatureFlag, FlagGroupType, PropertyFilter},
    property_matching::match_property,
};
use anyhow::Result;
use serde_json::Value;
use sha1::{Digest, Sha1};
use sqlx::FromRow;
use std::{
    collections::HashMap,
    fmt::Write,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};
use tokio::sync::RwLock;

type TeamId = i32;
type DatabaseClientArc = Arc<dyn DatabaseClient + Send + Sync>;
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

impl GroupTypeMapping {
    pub fn new(group_type: String, group_type_index: GroupTypeIndex) -> Result<Self, &'static str> {
        // Check group_type_index constraint
        if group_type_index > 5 {
            return Err("group_type_index must be less than or equal to 5");
        }

        // Check group_type length
        if group_type.len() > 400 {
            return Err("group_type must not exceed 400 characters");
        }

        Ok(Self {
            group_type,
            group_type_index,
        })
    }
}

pub struct FlagsMatcherCache {
    team_id: TeamId,
    failed_to_fetch_flags: AtomicBool,
    group_types_to_indexes: Arc<RwLock<Option<HashMap<String, GroupTypeIndex>>>>,
    group_indexes_to_types: Arc<RwLock<Option<HashMap<GroupTypeIndex, String>>>>,
    database_client: Option<DatabaseClientArc>,
}

impl FlagsMatcherCache {
    pub fn new(team_id: TeamId, database_client: Option<DatabaseClientArc>) -> Self {
        FlagsMatcherCache {
            team_id,
            failed_to_fetch_flags: AtomicBool::new(false),
            group_types_to_indexes: Arc::new(RwLock::new(None)),
            group_indexes_to_types: Arc::new(RwLock::new(None)),
            database_client,
        }
    }

    pub async fn group_type_to_group_type_index_map(
        &self,
    ) -> Result<HashMap<String, GroupTypeIndex>, FlagError> {
        if self.database_client.is_none() || self.failed_to_fetch_flags.load(Ordering::Relaxed) {
            return Err(FlagError::DatabaseUnavailable);
        }

        // Use a single read lock check
        if let Some(cached) = self.group_types_to_indexes.read().await.as_ref() {
            return Ok(cached.clone());
        }

        // If not cached, acquire write lock and check again (double-checked locking pattern)
        let mut cache = self.group_types_to_indexes.write().await;
        if let Some(cached) = cache.as_ref() {
            return Ok(cached.clone());
        }

        // Fetch from database
        match self.fetch_posthog_group_type_mapping().await {
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

    pub async fn group_type_index_to_group_type_map(
        &self,
    ) -> Result<HashMap<GroupTypeIndex, String>, FlagError> {
        // Use a single read lock check
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

    async fn fetch_posthog_group_type_mapping(
        &self,
    ) -> Result<HashMap<String, GroupTypeIndex>, FlagError> {
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
// #[derive(Debug)]
pub struct FeatureFlagMatcher {
    pub distinct_id: String,
    pub team_id: TeamId,
    pub database_client: Option<DatabaseClientArc>,
    // TODO should all the properties by cached in the same cache?
    // Like what's the point of having separate caches for person and group properties,
    // especially considering that they don't appear to persist across multiple instances of the matcher?
    cached_person_properties: Option<HashMap<String, Value>>,
    cached_group_properties: Option<HashMap<String, Value>>,
    person_property_overrides: Option<HashMap<String, Value>>,
    group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    flag_matcher_cache: Arc<FlagsMatcherCache>, // TODO rename to something more descriptive – this is the cache for group type mappings
}

const LONG_SCALE: u64 = 0xfffffffffffffff;

impl FeatureFlagMatcher {
    pub fn new(
        distinct_id: String,
        team_id: TeamId,
        database_client: Option<DatabaseClientArc>,
        person_property_overrides: Option<HashMap<String, Value>>,
        group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
        cache: Option<Arc<FlagsMatcherCache>>,
    ) -> Self {
        FeatureFlagMatcher {
            distinct_id,
            team_id,
            database_client: database_client.clone(),
            cached_person_properties: None,
            cached_group_properties: None,
            person_property_overrides,
            group_property_overrides,
            flag_matcher_cache: cache
                .unwrap_or_else(|| Arc::new(FlagsMatcherCache::new(team_id, database_client))),
        }
    }

    pub async fn get_match(
        &mut self,
        feature_flag: &FeatureFlag,
    ) -> Result<FeatureFlagMatch, FlagError> {
        if self.hashed_identifier(feature_flag).await?.is_empty() {
            return Ok(FeatureFlagMatch {
                matches: false,
                variant: None,
            });
        }

        // TODO: super groups for early access
        // TODO: Variant overrides condition sort

        for (index, condition) in feature_flag.get_conditions().iter().enumerate() {
            let (is_match, _evaluation_reason) = self
                .is_condition_match(feature_flag, condition, index)
                .await?;

            if is_match {
                // TODO: this is a bit awkward, we should only handle variants when variant overrides exist
                // I'll handle this when I implement variant overrides
                let variant = match condition.variant.clone() {
                    Some(variant_override) => {
                        if feature_flag
                            .get_variants()
                            .iter()
                            .any(|v| v.key == variant_override)
                        {
                            Some(variant_override)
                        } else {
                            self.get_matching_variant(feature_flag).await?
                        }
                    }
                    None => self.get_matching_variant(feature_flag).await?,
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

    // TODO: Making all this mutable just to store a cached value is annoying. Can I refactor this to be non-mutable?
    // Leaning a bit more towards a separate cache store for this.
    pub async fn is_condition_match(
        &mut self,
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
                    self.get_or_fetch_group_properties(
                        feature_flag,
                        group_type_index,
                        flag_property_filters,
                    )
                    .await?
                } else {
                    self.get_or_fetch_person_properties(feature_flag.team_id, flag_property_filters)
                        .await?
                };

            if !self.all_properties_match(flag_property_filters, &target_properties) {
                return Ok((false, "NO_CONDITION_MATCH".to_string()));
            }
        }

        self.check_rollout(feature_flag, rollout_percentage).await
    }

    async fn get_or_fetch_group_properties(
        &mut self,
        feature_flag: &FeatureFlag,
        group_type_index: GroupTypeIndex,
        property_filters: &[PropertyFilter],
    ) -> Result<HashMap<String, Value>, FlagError> {
        let index_to_type_map = self
            .flag_matcher_cache
            .group_type_index_to_group_type_map()
            .await?;

        let group_type = match index_to_type_map.get(&group_type_index) {
            Some(name) => name,
            None => {
                return self
                    .get_group_properties_from_in_memory_cache_or_db(
                        feature_flag.team_id,
                        group_type_index,
                    )
                    .await
            }
        };

        if let Some(override_properties) = self
            .group_property_overrides
            .as_ref()
            .and_then(|overrides| overrides.get(group_type))
        {
            if let Some(local_overrides) = self.can_compute_property_overrides_locally(
                &Some(override_properties.clone()),
                property_filters,
            ) {
                return Ok(local_overrides);
            }
        }

        self.get_group_properties_from_in_memory_cache_or_db(feature_flag.team_id, group_type_index)
            .await
    }

    async fn get_or_fetch_person_properties(
        &mut self,
        team_id: TeamId,
        flag_property_filters: &[PropertyFilter],
    ) -> Result<HashMap<String, Value>, FlagError> {
        if let Some(overrides) = self.can_compute_property_overrides_locally(
            &self.person_property_overrides,
            flag_property_filters,
        ) {
            return Ok(overrides);
        }

        // If we don't prefer the overrides (they're either not present, don't contain enough properties to evaluate the condition,
        // or contain a cohort property), fall back to getting properties from cache or DB
        self.get_person_properties_from_in_memory_cache_or_db(team_id, self.distinct_id.clone())
            .await
    }

    /// Check if all required properties are present in the overrides
    /// and none of them are of type "cohort" – if so, return the overrides,
    /// otherwise return None, because we can't locally compute cohort properties
    fn can_compute_property_overrides_locally(
        &self,
        property_overrides: &Option<HashMap<String, Value>>,
        property_filters: &[PropertyFilter],
    ) -> Option<HashMap<String, Value>> {
        property_overrides.as_ref().and_then(|person_overrides| {
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

    fn all_properties_match(
        &self,
        flag_condition_properties: &[PropertyFilter],
        target_properties: &HashMap<String, Value>,
    ) -> bool {
        flag_condition_properties
            .iter()
            .all(|property| match_property(property, target_properties, false).unwrap_or(false))
    }

    /// This function takes a feature flag and returns the hashed identifier for the flag.
    /// If the flag has a group type index, it returns the group type name, otherwise it returns the distinct_id.
    pub async fn hashed_identifier(&self, feature_flag: &FeatureFlag) -> Result<String, FlagError> {
        if let Some(group_type_index) = feature_flag.get_group_type_index() {
            let indexes_to_names = self
                .flag_matcher_cache
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

    /// This function takes a identifier and a feature flag key and returns a float between 0 and 1.
    /// Given the same identifier and key, it'll always return the same float. These floats are
    /// uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    /// we can do _hash(key, identifier) < 0.2
    pub async fn get_hash(&self, feature_flag: &FeatureFlag, salt: &str) -> Result<f64, FlagError> {
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
        let mut total_percentage = 0.0;

        for variant in feature_flag.get_variants() {
            total_percentage += variant.rollout_percentage / 100.0;
            if hash < total_percentage {
                return Ok(Some(variant.key.clone()));
            }
        }
        Ok(None)
    }

    /// This function takes a feature flag and returns the key of the variant that should be shown to the user.
    pub async fn get_person_properties_from_in_memory_cache_or_db(
        &mut self,
        team_id: TeamId,
        distinct_id: String,
    ) -> Result<HashMap<String, Value>, FlagError> {
        // TODO: Do we even need to cache here anymore?
        // Depends on how often we're calling this function
        // to match all flags for a single person

        // TODO which of these properties do we need to cache?
        if let Some(cached_person_props) = self.cached_person_properties.clone() {
            // TODO: Maybe we don't want to copy around all user properties, this will by far be the largest chunk
            // of data we're copying around. Can we work with references here?
            // Worst case, just use a Rc.
            return Ok(cached_person_props);
        }

        if self.database_client.is_none() {
            return Err(FlagError::DatabaseUnavailable);
        }

        let mut conn = self
            .database_client
            .as_ref()
            .expect("client should exist here")
            .get_connection()
            .await?;

        let query = r#"
            SELECT "posthog_person"."properties" 
            FROM "posthog_person"
            INNER JOIN "posthog_persondistinctid" ON ("posthog_person"."id" = "posthog_persondistinctid"."person_id")
            WHERE ("posthog_persondistinctid"."distinct_id" = $1
                    AND "posthog_persondistinctid"."team_id" = $2
                    AND "posthog_person"."team_id" = $3)
            LIMIT 1;
        "#;

        let row = sqlx::query_as::<_, Person>(query)
            .bind(&distinct_id)
            .bind(team_id)
            .bind(team_id)
            .fetch_optional(&mut *conn)
            .await?;

        let props = match row {
            Some(row) => row.properties.0,
            None => HashMap::new(), // TODO handle empty result instead of allocating a new HashMap
        };

        self.cached_person_properties = Some(props.clone());

        Ok(props)
    }

    async fn get_group_properties_from_in_memory_cache_or_db(
        &mut self,
        team_id: TeamId,
        group_type_index: GroupTypeIndex,
    ) -> Result<HashMap<String, Value>, FlagError> {
        // TODO which of these properties do we need to cache?
        if let Some(cached_group_props) = self.cached_group_properties.clone() {
            // TODO: Maybe we don't want to copy around all user properties, this will by far be the largest chunk
            // of data we're copying around. Can we work with references here?
            // Worst case, just use a Rc, like we do with the group type mappings.
            return Ok(cached_group_props);
        }

        if self.database_client.is_none() {
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
            LIMIT 1;
        "#;

        let row = sqlx::query_as::<_, Group>(query)
            .bind(team_id)
            .bind(group_type_index)
            .fetch_optional(&mut *conn)
            .await?;

        let props = match row {
            Some(row) => row.group_properties.0,
            None => HashMap::new(), // TODO handle empty result instead of allocating a new HashMap
        };

        self.cached_group_properties = Some(props.clone());

        Ok(props)
    }
}

#[cfg(test)]
mod tests {

    use serde_json::json;

    use super::*;
    use crate::{
        flag_definitions::{FlagFilters, MultivariateFlagOptions, MultivariateFlagVariant},
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

        let mut matcher =
            FeatureFlagMatcher::new(distinct_id, 1, Some(client.clone()), None, None, None);
        let match_result = matcher.get_match(&flag).await.unwrap();
        assert_eq!(match_result.matches, true);
        assert_eq!(match_result.variant, None);

        // property value is different
        let mut matcher = FeatureFlagMatcher::new(
            not_matching_distinct_id,
            1,
            Some(client.clone()),
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
        );

        let match_result = matcher.get_match(&flag).await.unwrap();
        assert_eq!(match_result.matches, true);
    }

    #[tokio::test]
    async fn test_hashed_identifier() {
        let flag = create_test_flag(1, vec![]);
        let database_client = setup_pg_client(None).await;

        // Create a FlagsMatcherCache with pre-populated group type mappings
        let cache = Arc::new(FlagsMatcherCache::new(1, Some(database_client.clone())));
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
        let cache = Arc::new(FlagsMatcherCache::new(1, Some(database_client.clone())));

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
        );

        // Debug: Print flag details
        println!("Flag: {:?}", flag);
        println!("Flag variants: {:?}", flag.get_variants());

        // Debug: Check hashed_identifier
        let hashed_identifier = matcher.hashed_identifier(&flag).await.unwrap();
        println!("Hashed identifier: {:?}", hashed_identifier);

        // Debug: Check get_hash
        let hash = matcher.get_hash(&flag, "variant").await.unwrap();
        println!("Hash value: {}", hash);

        let variant = matcher.get_matching_variant(&flag).await.unwrap();
        println!("Selected variant: {:?}", variant);

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

        let mut matcher =
            FeatureFlagMatcher::new("test_user".to_string(), 1, None, None, None, None);
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

        println!("Flag: {:?}", flag);
        println!("Group flag: {:?}", group_flag);

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(database_client.clone()),
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
}
