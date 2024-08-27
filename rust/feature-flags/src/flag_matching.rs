use crate::{
    api::FlagError,
    database::Client as DatabaseClient,
    flag_definitions::{FeatureFlag, FlagGroupType, PropertyFilter},
    property_matching::match_property,
};
use anyhow::Result;
use serde_json::Value;
use sha1::{Digest, Sha1};
use std::{
    collections::HashMap,
    fmt::Write,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};
use tokio::sync::RwLock;

#[derive(Debug, PartialEq, Eq)]
pub struct FeatureFlagMatch {
    pub matches: bool,
    pub variant: Option<String>,
    //reason
    //condition_index
    //payload
}

#[derive(Debug, sqlx::FromRow)]
pub struct Person {
    pub properties: sqlx::types::Json<HashMap<String, Value>>,
}

type GroupTypeName = String;
type GroupTypeIndex = i8;
type TeamId = i32;

#[derive(Debug, sqlx::FromRow)]
struct GroupTypeMapping {
    group_type: GroupTypeName,
    group_type_index: GroupTypeIndex,
}

pub struct FlagsMatcherCache {
    team_id: TeamId,
    failed_to_fetch_flags: AtomicBool,
    group_types_to_indexes: Arc<RwLock<Option<HashMap<GroupTypeName, GroupTypeIndex>>>>,
    group_type_index_to_name: Arc<RwLock<Option<HashMap<GroupTypeIndex, GroupTypeName>>>>,
    database_client: Option<Arc<dyn DatabaseClient + Send + Sync>>,
}

impl FlagsMatcherCache {
    pub fn new(
        team_id: TeamId,
        database_client: Option<Arc<dyn DatabaseClient + Send + Sync>>,
    ) -> Self {
        FlagsMatcherCache {
            team_id,
            failed_to_fetch_flags: AtomicBool::new(false),
            group_types_to_indexes: Arc::new(RwLock::new(None)),
            group_type_index_to_name: Arc::new(RwLock::new(None)),
            database_client,
        }
    }

    pub async fn group_types_to_indexes(
        &self,
    ) -> Result<HashMap<GroupTypeName, GroupTypeIndex>, FlagError> {
        if self.database_client.is_none() || self.failed_to_fetch_flags.load(Ordering::Relaxed) {
            return Err(FlagError::DatabaseUnavailable);
        }

        let cache = self.group_types_to_indexes.read().await;
        if let Some(ref cached) = *cache {
            return Ok(cached.clone());
        }
        drop(cache);

        let mut cache = self.group_types_to_indexes.write().await;
        if cache.is_none() {
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
        } else {
            Ok(cache.as_ref().unwrap().clone())
        }
    }

    pub async fn group_type_index_to_name(
        &self,
    ) -> Result<HashMap<GroupTypeIndex, GroupTypeName>, FlagError> {
        {
            let cache = self.group_type_index_to_name.read().await;
            if let Some(ref cached) = *cache {
                return Ok(cached.clone());
            }
        }

        let types_to_indexes = self.group_types_to_indexes().await?;
        let result: HashMap<GroupTypeIndex, GroupTypeName> =
            types_to_indexes.into_iter().map(|(k, v)| (v, k)).collect();

        let mut cache = self.group_type_index_to_name.write().await;
        *cache = Some(result);

        Ok(cache.as_ref().unwrap().clone())
    }

    async fn fetch_group_type_mapping(
        &self,
    ) -> Result<HashMap<GroupTypeName, GroupTypeIndex>, FlagError> {
        let mut conn = self
            .database_client
            .as_ref()
            .ok_or(FlagError::DatabaseUnavailable)?
            .get_connection()
            .await?;

        let query = r#"
            SELECT group_type, group_type_index 
            FROM group_type_mapping 
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
    // pub flags: Vec<FeatureFlag>,
    pub distinct_id: String,
    pub database_client: Option<Arc<dyn DatabaseClient + Send + Sync>>,
    // TODO do I need cached_properties, or do I get them from the request?
    // like, in python I get them from the request.  Hmm.  Let me try that.
    // OH, or is this the FlagMatcherCache.  Yeah, so this is the flag matcher cache
    cached_properties: Option<HashMap<String, Value>>,
    person_property_overrides: Option<HashMap<String, Value>>,
    // TODO handle group properties
    group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    cache: Arc<FlagsMatcherCache>,
}

const LONG_SCALE: u64 = 0xfffffffffffffff;

impl FeatureFlagMatcher {
    pub fn new(
        distinct_id: String,
        database_client: Option<Arc<dyn DatabaseClient + Send + Sync>>,
        person_property_overrides: Option<HashMap<String, Value>>,
        group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    ) -> Self {
        FeatureFlagMatcher {
            // flags,
            distinct_id,
            database_client,
            cached_properties: None,
            person_property_overrides,
            group_property_overrides,
            cache: Arc::new(FlagsMatcherCache::new(1, None)), // TODO needs a team_id and a non-copied DB client?
        }
    }

    pub async fn get_match(
        &mut self,
        feature_flag: &FeatureFlag,
    ) -> Result<FeatureFlagMatch, FlagError> {
        if self.hashed_identifier(feature_flag).is_none() {
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
                // TODO: this is a bit awkward, we should only handle variants when overrides exist
                let variant = match condition.variant.clone() {
                    Some(variant_override) => {
                        if feature_flag
                            .get_variants()
                            .iter()
                            .any(|v| v.key == variant_override)
                        {
                            Some(variant_override)
                        } else {
                            self.get_matching_variant(feature_flag)
                        }
                    }
                    None => self.get_matching_variant(feature_flag),
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

    fn check_rollout(&self, feature_flag: &FeatureFlag, rollout_percentage: f64) -> (bool, String) {
        if rollout_percentage == 100.0
            || self.get_hash(feature_flag, "") <= (rollout_percentage / 100.0)
        {
            (true, "CONDITION_MATCH".to_string())
        } else {
            (false, "OUT_OF_ROLLOUT_BOUND".to_string())
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
        if let Some(properties) = &condition.properties {
            if properties.is_empty() {
                return Ok(self.check_rollout(feature_flag, rollout_percentage));
            }

            let target_properties = if let Some(group_index) = feature_flag.get_group_type_index() {
                self.get_person_properties_from_group(feature_flag, group_index)
                    .await?
            } else {
                self.get_person_properties(feature_flag.team_id, properties)
                    .await?
            };

            if !self.all_properties_match(properties, &target_properties) {
                return Ok((false, "NO_CONDITION_MATCH".to_string()));
            }
        }

        Ok(self.check_rollout(feature_flag, rollout_percentage))
    }

    async fn get_person_properties_from_group(
        &mut self,
        feature_flag: &FeatureFlag,
        group_index: i8,
    ) -> Result<HashMap<String, Value>, FlagError> {
        let index_to_name = self.cache.group_type_index_to_name().await?;

        let group_name = match index_to_name.get(&group_index) {
            Some(name) => name,
            None => {
                // If no group name can be found in the in-memory cache, fall back to redis cache/DB
                return self
                    .get_person_properties_from_cache_or_db(
                        feature_flag.team_id,
                        self.distinct_id.clone(),
                    )
                    .await;
            }
        };

        // If there are matching property overrides, use them instead of cache/DB
        if let Some(overrides) = self.group_property_overrides.as_ref() {
            if let Some(override_properties) = overrides.get(group_name) {
                return Ok(override_properties.clone());
            }
        };

        // If we didn't return overrides, fall back to cache/DB
        self.get_person_properties_from_cache_or_db(feature_flag.team_id, self.distinct_id.clone())
            .await
    }

    async fn get_person_properties(
        &mut self,
        team_id: i32,
        properties: &[PropertyFilter],
    ) -> Result<HashMap<String, Value>, FlagError> {
        if let Some(person_overrides) = &self.person_property_overrides {
            // Check if all required properties are present in the overrides
            // and none of them are of type "cohort"
            let should_prefer_overrides = properties
                .iter()
                .all(|prop| person_overrides.contains_key(&prop.key) && prop.prop_type != "cohort");

            if should_prefer_overrides {
                return Ok(person_overrides.clone());
            }
        }

        // If we don't prefer the overrides (they're either not present, don't contain enough properties to evaluate the condition,
        // or contain a cohort property), fall back to getting properties from cache or DB
        self.get_person_properties_from_cache_or_db(team_id, self.distinct_id.clone())
            .await
    }

    fn all_properties_match(
        &self,
        condition_properties: &[PropertyFilter],
        target_properties: &HashMap<String, Value>,
    ) -> bool {
        condition_properties
            .iter()
            .all(|property| match_property(property, target_properties, false).unwrap_or(false))
    }

    pub fn hashed_identifier(&self, feature_flag: &FeatureFlag) -> Option<String> {
        if feature_flag.get_group_type_index().is_none() {
            // TODO: Use hash key overrides for experience continuity
            Some(self.distinct_id.clone())
        } else {
            // TODO: Handle getting group key
            Some("".to_string())
        }
    }

    /// This function takes a identifier and a feature flag key and returns a float between 0 and 1.
    /// Given the same identifier and key, it'll always return the same float. These floats are
    /// uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    /// we can do _hash(key, identifier) < 0.2
    pub fn get_hash(&self, feature_flag: &FeatureFlag, salt: &str) -> f64 {
        // check if hashed_identifier is None
        let hashed_identifier = self
            .hashed_identifier(feature_flag)
            .expect("hashed_identifier is None when computing hash");
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

        hash_val as f64 / LONG_SCALE as f64
    }

    /// This function takes a feature flag and returns the key of the variant that should be shown to the user.
    pub fn get_matching_variant(&self, feature_flag: &FeatureFlag) -> Option<String> {
        let hash = self.get_hash(feature_flag, "variant");
        let mut total_percentage = 0.0;

        for variant in feature_flag.get_variants() {
            total_percentage += variant.rollout_percentage / 100.0;
            if hash < total_percentage {
                return Some(variant.key.clone());
            }
        }
        None
    }

    /// This function takes a feature flag and returns the key of the variant that should be shown to the user.
    pub async fn get_person_properties_from_cache_or_db(
        &mut self,
        team_id: i32,
        distinct_id: String,
    ) -> Result<HashMap<String, Value>, FlagError> {
        // TODO: Do we even need to cache here anymore?
        // Depends on how often we're calling this function
        // to match all flags for a single person

        // TODO which of these properties do we need to cache?
        if let Some(cached_props) = self.cached_properties.clone() {
            // TODO: Maybe we don't want to copy around all user properties, this will by far be the largest chunk
            // of data we're copying around. Can we work with references here?
            // Worst case, just use a Rc.
            return Ok(cached_props);
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
            None => HashMap::new(),
        };

        self.cached_properties = Some(props.clone());

        Ok(props)
    }

    // async fn get_group_properties_from_cache_or_db(
    //     &self,
    //     team_id: i32,
    //     group_index: usize,
    //     properties: &Vec<PropertyFilter>,
    // ) -> HashMap<String, Value> {
    //     todo!()
    // }
}

#[cfg(test)]
mod tests {

    use serde_json::json;

    use super::*;
    use crate::{
        flag_definitions::{FlagFilters, MultivariateFlagOptions, MultivariateFlagVariant},
        test_utils::{insert_new_team_in_pg, insert_person_for_team_in_pg, setup_pg_client},
    };

    fn create_test_flag(team_id: i32, properties: Vec<PropertyFilter>) -> FeatureFlag {
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

        let mut matcher = FeatureFlagMatcher::new(distinct_id, Some(client.clone()), None, None);
        let match_result = matcher.get_match(&flag).await.unwrap();
        assert_eq!(match_result.matches, true);
        assert_eq!(match_result.variant, None);

        // property value is different
        let mut matcher =
            FeatureFlagMatcher::new(not_matching_distinct_id, Some(client.clone()), None, None);
        let match_result = matcher.get_match(&flag).await.unwrap();
        assert_eq!(match_result.matches, false);
        assert_eq!(match_result.variant, None);

        // person does not exist
        let mut matcher = FeatureFlagMatcher::new(
            "other_distinct_id".to_string(),
            Some(client.clone()),
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
            Some(client.clone()),
            Some(overrides),
            None,
        );

        let match_result = matcher.get_match(&flag).await.unwrap();
        assert_eq!(match_result.matches, true);
    }

    #[test]
    fn test_hashed_identifier() {
        let flag = create_test_flag(1, vec![]);

        let matcher = FeatureFlagMatcher::new("test_user".to_string(), None, None, None);
        assert_eq!(
            matcher.hashed_identifier(&flag),
            Some("test_user".to_string())
        );

        // Test with a group type index (this part of the functionality is not implemented yet)
        // let mut group_flag = flag.clone();
        // group_flag.filters.aggregation_group_type_index = Some(1);
        // assert_eq!(matcher.hashed_identifier(&group_flag), Some("".to_string()));
    }

    #[test]
    fn test_get_matching_variant() {
        let flag = FeatureFlag {
            id: 1,
            team_id: 1,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: FlagFilters {
                groups: vec![],
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
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: false,
        };

        let matcher = FeatureFlagMatcher::new("test_user".to_string(), None, None, None);
        let variant = matcher.get_matching_variant(&flag);
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

        let mut matcher = FeatureFlagMatcher::new("test_user".to_string(), None, None, None);
        let (is_match, reason) = matcher
            .is_condition_match(&flag, &condition, 0)
            .await
            .unwrap();
        assert_eq!(is_match, true);
        assert_eq!(reason, "CONDITION_MATCH");
    }
}
