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
/// However, this type really _should_ be an enum, since in Postgres we constrain the values of this field
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
            Ok(mapping) if !mapping.is_empty() => {
                *cache = Some(mapping.clone());
                Ok(mapping)
            }
            Ok(_) => {
                self.failed_to_fetch_flags.store(true, Ordering::Relaxed);
                Err(FlagError::NoGroupTypeMappings)
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

        let types_to_indexes = self.group_type_to_group_type_index_map().await?;
        let result: HashMap<GroupTypeIndex, String> =
            types_to_indexes.into_iter().map(|(k, v)| (v, k)).collect();

        if !result.is_empty() {
            *cache = Some(result.clone());
            Ok(result)
        } else {
            Err(FlagError::NoGroupTypeMappings)
        }
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

        let mapping: HashMap<String, GroupTypeIndex> = rows
            .into_iter()
            .map(|row| (row.group_type, row.group_type_index))
            .collect();

        if mapping.is_empty() {
            Err(FlagError::NoGroupTypeMappings)
        } else {
            Ok(mapping)
        }
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
    group_type_mapping_cache: Arc<GroupTypeMappingCache>,
    properties_cache: Arc<RwLock<PropertiesCache>>,
}

const LONG_SCALE: u64 = 0xfffffffffffffff;

impl FeatureFlagMatcher {
    pub fn new(
        distinct_id: String,
        team_id: TeamId,
        database_client: Option<DatabaseClientArc>,
        group_type_mapping_cache: Option<Arc<GroupTypeMappingCache>>,
        properties_cache: Option<Arc<RwLock<PropertiesCache>>>,
    ) -> Self {
        FeatureFlagMatcher {
            distinct_id,
            team_id,
            database_client: database_client.clone(),
            group_type_mapping_cache: group_type_mapping_cache
                .unwrap_or_else(|| Arc::new(GroupTypeMappingCache::new(team_id, database_client))),
            properties_cache: properties_cache
                .unwrap_or_else(|| Arc::new(RwLock::new(PropertiesCache::default()))),
        }
    }

    /// Evaluate feature flags for a given distinct_id
    /// - Returns a map of feature flag keys to their values
    /// - If an error occurs while evaluating a flag, it will be logged and the flag will be omitted from the result
    pub async fn evaluate_feature_flags(
        &self,
        feature_flags: FeatureFlagList,
        person_property_overrides: Option<HashMap<String, Value>>,
        group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
        hard_coded_hash: Option<f64>,
    ) -> FlagsResponse {
        let mut result = HashMap::new();
        let mut error_while_computing_flags = false;
        let mut flags_needing_db_properties = Vec::new();

        // Step 1: Evaluate flags that can be resolved with overrides
        for flag in &feature_flags.flags {
            if !flag.active || flag.deleted {
                continue;
            }

            match self
                .match_flag_with_overrides(
                    flag,
                    &person_property_overrides,
                    &group_property_overrides,
                    hard_coded_hash,
                )
                .await
            {
                Ok(Some(flag_match)) => {
                    let flag_value = self.flag_match_to_value(&flag_match);
                    result.insert(flag.key.clone(), flag_value);
                }
                Ok(None) => {
                    flags_needing_db_properties.push(flag);
                }
                Err(e) => {
                    error_while_computing_flags = true;
                    error!(
                    "Error evaluating feature flag '{}' with overrides for distinct_id '{}': {:?}",
                    flag.key, self.distinct_id, e
                );
                }
            }
        }

        // Step 2: Fetch and cache properties for remaining flags
        if !flags_needing_db_properties.is_empty() {
            let group_type_indexes: HashSet<GroupTypeIndex> = flags_needing_db_properties
                .iter()
                .filter_map(|flag| flag.get_group_type_index())
                .collect();

            if let Err(e) = self
                .fetch_and_cache_all_properties(&group_type_indexes)
                .await
            {
                error_while_computing_flags = true;
                error!("Error fetching properties: {:?}", e);
            } else {
                // Step 3: Evaluate remaining flags
                for flag in flags_needing_db_properties {
                    match self.get_match(flag, None, hard_coded_hash).await {
                        Ok(flag_match) => {
                            let flag_value = self.flag_match_to_value(&flag_match);
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
            }
        }

        FlagsResponse {
            error_while_computing_flags,
            feature_flags: result,
        }
    }

    async fn match_flag_with_overrides(
        &self,
        flag: &FeatureFlag,
        person_property_overrides: &Option<HashMap<String, Value>>,
        group_property_overrides: &Option<HashMap<String, HashMap<String, Value>>>,
        hard_coded_hash: Option<f64>,
    ) -> Result<Option<FeatureFlagMatch>, FlagError> {
        let flag_property_filters: Vec<PropertyFilter> = flag
            .get_conditions()
            .iter()
            .flat_map(|c| c.properties.clone().unwrap_or_default())
            .collect();

        let overrides = match flag.get_group_type_index() {
            Some(group_type_index) => {
                self.get_group_overrides(
                    group_type_index,
                    group_property_overrides,
                    &flag_property_filters,
                )
                .await?
            }
            None => self.get_person_overrides(person_property_overrides, &flag_property_filters),
        };

        match overrides {
            Some(props) => self
                .get_match(flag, Some(props), hard_coded_hash)
                .await
                .map(Some),
            None => Ok(None),
        }
    }

    async fn get_group_overrides(
        &self,
        group_type_index: GroupTypeIndex,
        group_property_overrides: &Option<HashMap<String, HashMap<String, Value>>>,
        flag_property_filters: &[PropertyFilter],
    ) -> Result<Option<HashMap<String, Value>>, FlagError> {
        let index_to_type_map = self
            .group_type_mapping_cache
            .group_type_index_to_group_type_map()
            .await?;

        if let Some(group_type) = index_to_type_map.get(&group_type_index) {
            if let Some(group_overrides) = group_property_overrides {
                if let Some(group_overrides_by_type) = group_overrides.get(group_type) {
                    return Ok(locally_computable_property_overrides(
                        &Some(group_overrides_by_type.clone()),
                        flag_property_filters,
                    ));
                }
            }
        }

        Ok(None)
    }

    fn get_person_overrides(
        &self,
        person_property_overrides: &Option<HashMap<String, Value>>,
        flag_property_filters: &[PropertyFilter],
    ) -> Option<HashMap<String, Value>> {
        person_property_overrides.as_ref().and_then(|overrides| {
            locally_computable_property_overrides(&Some(overrides.clone()), flag_property_filters)
        })
    }

    fn flag_match_to_value(&self, flag_match: &FeatureFlagMatch) -> FlagValue {
        if flag_match.matches {
            match &flag_match.variant {
                Some(variant) => FlagValue::String(variant.clone()),
                None => FlagValue::Boolean(true),
            }
        } else {
            FlagValue::Boolean(false)
        }
    }

    async fn fetch_and_cache_all_properties(
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
            SELECT 
                (SELECT "posthog_person"."properties"
                 FROM "posthog_person"
                 INNER JOIN "posthog_persondistinctid" 
                 ON ("posthog_person"."id" = "posthog_persondistinctid"."person_id")
                 WHERE ("posthog_persondistinctid"."distinct_id" = $1
                        AND "posthog_persondistinctid"."team_id" = $2
                        AND "posthog_person"."team_id" = $2)
                 LIMIT 1) as person_properties,
                
                (SELECT json_object_agg("posthog_group"."group_type_index", "posthog_group"."group_properties")
                 FROM "posthog_group"
                 WHERE ("posthog_group"."team_id" = $2
                        AND "posthog_group"."group_type_index" = ANY($3))) as group_properties
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

    pub async fn get_match(
        &self,
        flag: &FeatureFlag,
        property_overrides: Option<HashMap<String, Value>>,
        hard_coded_hash: Option<f64>,
    ) -> Result<FeatureFlagMatch, FlagError> {
        if self.hashed_identifier(flag).await?.is_empty() {
            return Ok(FeatureFlagMatch {
                matches: false,
                variant: None,
            });
        }

        // TODO: super groups for early access
        // TODO: Variant overrides condition sort

        for condition in flag.get_conditions().iter() {
            let (is_match, _evaluation_reason) = self
                .is_condition_match(flag, condition, property_overrides.clone(), hard_coded_hash)
                .await?;

            if is_match {
                // TODO: this is a bit awkward, we should only handle variants when overrides exist
                let variant = match condition.variant.clone() {
                    Some(variant_override)
                        if flag
                            .get_variants()
                            .iter()
                            .any(|v| v.key == variant_override) =>
                    {
                        Some(variant_override)
                    }
                    _ => self.get_matching_variant(flag, hard_coded_hash).await?,
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
        hard_coded_hash: Option<f64>,
    ) -> Result<(bool, String), FlagError> {
        if rollout_percentage == 100.0
            || self.get_hash(feature_flag, "", hard_coded_hash).await?
                <= (rollout_percentage / 100.0)
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
        property_overrides: Option<HashMap<String, Value>>, // TODO need to guarantee that these props map to the correct type (person or group)
        hard_coded_hash: Option<f64>,
    ) -> Result<(bool, String), FlagError> {
        let rollout_percentage = condition.rollout_percentage.unwrap_or(100.0);

        if let Some(flag_property_filters) = &condition.properties {
            if flag_property_filters.is_empty() {
                return self
                    .check_rollout(feature_flag, rollout_percentage, hard_coded_hash)
                    .await;
            }

            let properties_to_check =
             // Group-based flag
                if let Some(group_type_index) = feature_flag.get_group_type_index() {
                            if let Some(local_overrides) = locally_computable_property_overrides(
                                &property_overrides.clone(),
                                flag_property_filters,
                            ) {
                                local_overrides
                            } else {
                                self.get_group_properties_from_cache_or_db(group_type_index)
                                    .await?
                            }
                } else {
                    // Person-based flag
                    if let Some(person_overrides) = property_overrides {
                        if let Some(local_overrides) = locally_computable_property_overrides(
                            &Some(person_overrides),
                            flag_property_filters,
                        ) {
                            local_overrides
                        } else {
                            self.get_person_properties_from_cache_or_db()
                                .await?
                        }
                    } else {
                        self.get_person_properties_from_cache_or_db()
                            .await?
                    }
                };

            let properties_match =
                all_properties_match(flag_property_filters, &properties_to_check);

            if !properties_match {
                return Ok((false, "NO_CONDITION_MATCH".to_string()));
            }
        }

        self.check_rollout(feature_flag, rollout_percentage, hard_coded_hash)
            .await
    }

    async fn get_group_properties_from_cache_or_db(
        &self,
        group_type_index: GroupTypeIndex,
    ) -> Result<HashMap<String, Value>, FlagError> {
        // let index_to_type_map = self
        //     .group_type_mapping_cache
        //     .group_type_index_to_group_type_map()
        //     .await?;

        // let group_type = index_to_type_map.get(&group_type_index).cloned();

        // if let Some(group_type) = group_type {
        //     if let Some(override_properties) = group_property_overrides
        //         .as_ref()
        //         .and_then(|overrides| overrides.get(&group_type))
        //     {
        //         if let Some(local_overrides) = locally_computable_property_overrides(
        //             &Some(override_properties.clone()),
        //             flag_property_filters,
        //         ) {
        //             return Ok(local_overrides);
        //         }
        //     }
        // }

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

    async fn get_person_properties_from_cache_or_db(
        &self,
    ) -> Result<HashMap<String, Value>, FlagError> {
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
    async fn hashed_identifier(&self, feature_flag: &FeatureFlag) -> Result<String, FlagError> {
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

    /// This function takes a identifier and a feature flag key and returns a float between 0 and 1.
    /// Given the same identifier and key, it'll always return the same float. These floats are
    /// uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    /// we can do _hash(key, identifier) < 0.2
    async fn get_hash(
        &self,
        feature_flag: &FeatureFlag,
        salt: &str,
        hard_coded_hash: Option<f64>,
    ) -> Result<f64, FlagError> {
        if let Some(hash) = hard_coded_hash {
            return Ok(hash);
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
    async fn get_matching_variant(
        &self,
        feature_flag: &FeatureFlag,
        hard_coded_hash: Option<f64>,
    ) -> Result<Option<String>, FlagError> {
        let hash = self
            .get_hash(feature_flag, "variant", hard_coded_hash)
            .await?;
        let mut cumulative_percentage = 0.0;

        for variant in feature_flag.get_variants() {
            cumulative_percentage += variant.rollout_percentage / 100.0;
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
fn locally_computable_property_overrides(
    property_overrides: &Option<HashMap<String, Value>>,
    property_filters: &[PropertyFilter],
) -> Option<HashMap<String, Value>> {
    property_overrides.as_ref().and_then(|overrides| {
        // TODO handle note from Neil: https://github.com/PostHog/posthog/pull/24589#discussion_r1735828561
        // TL;DR – we'll need to handle cohort properties at the DB level, i.e. we'll need to adjust the cohort query
        // to account for if a given person is an element of the cohort X, Y, Z, etc
        let should_prefer_overrides = property_filters
            .iter()
            .all(|prop| overrides.contains_key(&prop.key) && prop.prop_type != "cohort");

        if should_prefer_overrides {
            Some(overrides.clone())
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

        let matcher =
            FeatureFlagMatcher::new(distinct_id, team.id, Some(client.clone()), None, None);
        let match_result = matcher.get_match(&flag, None, None).await.unwrap();
        assert_eq!(match_result.matches, true);
        assert_eq!(match_result.variant, None);

        // property value is different
        let matcher = FeatureFlagMatcher::new(
            not_matching_distinct_id,
            team.id,
            Some(client.clone()),
            None,
            None,
        );
        let match_result = matcher.get_match(&flag, None, None).await.unwrap();
        assert_eq!(match_result.matches, false);
        assert_eq!(match_result.variant, None);

        // person does not exist
        let matcher = FeatureFlagMatcher::new(
            "other_distinct_id".to_string(),
            1,
            Some(client.clone()),
            None,
            None,
        );
        let match_result = matcher.get_match(&flag, None, None).await.unwrap();
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

        let matcher =
            FeatureFlagMatcher::new("test_user".to_string(), 1, Some(client.clone()), None, None);

        let flags = FeatureFlagList { flags: vec![flag] };
        let result = matcher
            .evaluate_feature_flags(flags, Some(overrides), None, None)
            .await;

        assert!(!result.error_while_computing_flags);
        assert_eq!(
            result.feature_flags.get("test_flag"),
            Some(&FlagValue::Boolean(true))
        );
    }
    // TODO test group property overrides

    #[tokio::test]
    async fn hard_coded_hashed_identifier() {
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
            Some(cache.clone()),
            None,
        );
        let variant = matcher.get_matching_variant(&flag, None).await.unwrap();
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
        );

        let variant = matcher.get_matching_variant(&flag, None).await.unwrap();
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

        let matcher = FeatureFlagMatcher::new("test_user".to_string(), 1, None, None, None);
        let (is_match, reason) = matcher
            .is_condition_match(&flag, &condition, None, None)
            .await
            .unwrap();
        assert_eq!(is_match, true);
        assert_eq!(reason, "CONDITION_MATCH");
    }

    #[tokio::test]
    async fn hard_coded_hashed_identifier_with_db() {
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

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(client.clone()),
            None,
            None,
        );

        let result = matcher
            .evaluate_feature_flags(flags, None, None, None)
            .await;

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
    async fn test_evaluate_feature_flags_with_overrides() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let mut person_flag = create_test_flag(
            team.id,
            vec![PropertyFilter {
                key: "email".to_string(),
                value: json!("test@example.com"),
                operator: Some(OperatorType::Exact),
                prop_type: "person".to_string(),
                group_type_index: None,
            }],
        );
        person_flag.key = "person_flag".to_string();

        let mut group_flag = create_test_flag(
            team.id,
            vec![PropertyFilter {
                key: "industry".to_string(),
                value: json!("tech"),
                operator: Some(OperatorType::Exact),
                prop_type: "group".to_string(),
                group_type_index: Some(0),
            }],
        );
        group_flag.key = "group_flag".to_string();
        group_flag.filters.aggregation_group_type_index = Some(0);

        let flags = FeatureFlagList {
            flags: vec![person_flag.clone(), group_flag.clone()],
        };

        let person_property_overrides =
            HashMap::from([("email".to_string(), json!("test@example.com"))]);

        let group_property_overrides = HashMap::from([(
            "project".to_string(),
            HashMap::from([("industry".to_string(), json!("tech"))]),
        )]);

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(client.clone()),
            None,
            None,
        );

        // Evaluate person flag
        let person_result = matcher
            .evaluate_feature_flags(
                FeatureFlagList {
                    flags: vec![person_flag],
                },
                Some(person_property_overrides.clone()),
                None,
                None,
            )
            .await;
        assert!(!person_result.error_while_computing_flags);
        assert_eq!(
            person_result.feature_flags.get("person_flag"),
            Some(&FlagValue::Boolean(true))
        );

        // Evaluate group flag
        let group_result = matcher
            .evaluate_feature_flags(
                FeatureFlagList {
                    flags: vec![group_flag],
                },
                None,
                Some(group_property_overrides.clone()),
                None,
            )
            .await;
        assert!(!group_result.error_while_computing_flags);
        assert_eq!(
            group_result.feature_flags.get("group_flag"),
            Some(&FlagValue::Boolean(true))
        );

        // Now evaluate all flags
        let result = matcher
            .evaluate_feature_flags(
                flags,
                Some(person_property_overrides),
                Some(group_property_overrides),
                None,
            )
            .await;

        assert!(!result.error_while_computing_flags);
        assert_eq!(result.feature_flags.len(), 2);
        assert_eq!(
            result.feature_flags.get("person_flag"),
            Some(&FlagValue::Boolean(true)),
            "Person flag should be true"
        );
        assert_eq!(
            result.feature_flags.get("group_flag"),
            Some(&FlagValue::Boolean(true)),
            "Group flag should be true"
        );
    }

    #[tokio::test]
    async fn test_overrides_avoid_db_lookups() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag(
            team.id,
            vec![PropertyFilter {
                key: "email".to_string(),
                value: json!("test@example.com"),
                operator: Some(OperatorType::Exact),
                prop_type: "person".to_string(),
                group_type_index: None,
            }],
        );

        let person_property_overrides =
            HashMap::from([("email".to_string(), json!("test@example.com"))]);

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(client.clone()),
            None,
            None,
        );

        // Evaluate the flag
        let result = matcher
            .evaluate_feature_flags(
                FeatureFlagList { flags: vec![flag] },
                Some(person_property_overrides),
                None,
                None,
            )
            .await;

        assert!(!result.error_while_computing_flags);
        assert_eq!(
            result.feature_flags.get("test_flag"),
            Some(&FlagValue::Boolean(true))
        );

        // Check that the properties cache is still empty, indicating no DB lookup
        let cache = matcher.properties_cache.read().await;
        assert!(cache.person_properties.is_none());
    }

    #[tokio::test]
    async fn test_fallback_to_db_when_overrides_insufficient() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag(
            team.id,
            vec![
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
            ],
        );

        let person_property_overrides = Some(HashMap::from([(
            "email".to_string(),
            json!("test@example.com"),
        )]));

        // Insert a person with both email and age
        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "test@example.com", "age": 30})),
        )
        .await
        .unwrap();

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(client.clone()),
            None,
            None,
        );

        // Evaluate the flag
        let result = matcher
            .get_match(&flag, person_property_overrides.clone(), None)
            .await
            .unwrap();

        assert!(result.matches);

        // Check that the properties cache is populated, indicating a DB lookup
        let cache = matcher.properties_cache.read().await;
        assert!(cache.person_properties.is_some());
        assert_eq!(
            cache.person_properties.as_ref().unwrap().get("age"),
            Some(&json!(30))
        );
    }

    #[tokio::test]
    async fn test_evaluate_flags_mixed_override_and_db() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let mut override_flag = create_test_flag(
            team.id,
            vec![PropertyFilter {
                key: "email".to_string(),
                value: json!("test@example.com"),
                operator: Some(OperatorType::Exact),
                prop_type: "person".to_string(),
                group_type_index: None,
            }],
        );
        override_flag.key = "override_flag".to_string();

        let mut db_flag = create_test_flag(
            team.id,
            vec![PropertyFilter {
                key: "age".to_string(),
                value: json!(25),
                operator: Some(OperatorType::Gte),
                prop_type: "person".to_string(),
                group_type_index: None,
            }],
        );
        db_flag.key = "db_flag".to_string();

        let flags = FeatureFlagList {
            flags: vec![override_flag, db_flag],
        };

        let person_property_overrides = Some(HashMap::from([(
            "email".to_string(),
            json!("test@example.com"),
        )]));

        // Insert a person with both email and age
        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "test@example.com", "age": 30})),
        )
        .await
        .unwrap();

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(client.clone()),
            None,
            None,
        );

        let result = matcher
            .evaluate_feature_flags(flags, person_property_overrides, None, None)
            .await;

        assert!(!result.error_while_computing_flags);
        assert_eq!(result.feature_flags.len(), 2);
        assert_eq!(
            result.feature_flags.get("override_flag"),
            Some(&FlagValue::Boolean(true))
        );
        assert_eq!(
            result.feature_flags.get("db_flag"),
            Some(&FlagValue::Boolean(true))
        );

        // Check that the properties cache is populated only after evaluating the db_flag
        let cache = matcher.properties_cache.read().await;
        assert!(cache.person_properties.is_some());
        assert_eq!(
            cache.person_properties.as_ref().unwrap().get("age"),
            Some(&json!(30))
        );
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

        let overrides = Some(HashMap::from([
            ("email".to_string(), json!("test@example.com")),
            ("country".to_string(), json!("US")),
        ]));

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(client.clone()),
            None,
            None,
        );

        let match_result = matcher.get_match(&flag, overrides, None).await.unwrap();
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
        );

        // Test 0% rollout
        let (is_match, reason) = base_matcher
            .check_rollout(&flag, 0.0, Some(0.5))
            .await
            .unwrap();
        assert!(!is_match);
        assert_eq!(reason, "OUT_OF_ROLLOUT_BOUND");

        // Test 100% rollout
        let (is_match, reason) = base_matcher
            .check_rollout(&flag, 100.0, Some(0.99))
            .await
            .unwrap();
        assert!(is_match);
        assert_eq!(reason, "CONDITION_MATCH");

        // Test 50% rollout
        // User just within the rollout
        let (is_match, reason) = base_matcher
            .check_rollout(&flag, 50.0, Some(0.49))
            .await
            .unwrap();
        assert!(is_match);
        assert_eq!(reason, "CONDITION_MATCH");

        // User just outside the rollout
        let (is_match, reason) = base_matcher
            .check_rollout(&flag, 50.0, Some(0.51))
            .await
            .unwrap();
        assert!(!is_match);
        assert_eq!(reason, "OUT_OF_ROLLOUT_BOUND");

        // Edge cases
        // Test with 0.0 hash (should always be in rollout except for 0%)
        let (is_match, _) = base_matcher
            .check_rollout(&flag, 0.1, Some(0.0))
            .await
            .unwrap();
        assert!(is_match);

        // Test with 0.99999 hash (should only be in rollout for 100%)
        let (is_match, _) = base_matcher
            .check_rollout(&flag, 99.9, Some(0.99999))
            .await
            .unwrap();
        assert!(!is_match);
        let (is_match, _) = base_matcher
            .check_rollout(&flag, 100.0, Some(0.99999))
            .await
            .unwrap();
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

        let property_overrides = Some(HashMap::from([
            ("email".to_string(), json!("test@example.com")),
            ("age".to_string(), json!(30)),
        ]));

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            Some(client.clone()),
            None,
            None,
        );

        let (is_match, reason) = matcher
            .is_condition_match(&flag, &condition, property_overrides.clone(), Some(0.4)) // Set a test hash value that falls within the 50% rollout
            .await
            .unwrap();

        assert!(
            is_match,
            "Expected a match, but got: is_match = {}, reason = {}",
            is_match, reason
        );

        let (is_match, reason) = matcher
            .is_condition_match(&flag, &condition, property_overrides.clone(), Some(0.6)) // Set a test hash value that falls outside the 50% rollout
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

        let matcher =
            FeatureFlagMatcher::new(distinct_id, team.id, Some(client.clone()), None, None);

        let properties = matcher
            .get_person_properties_from_cache_or_db()
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

        let result = locally_computable_property_overrides(&overrides, &property_filters);
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
            locally_computable_property_overrides(&overrides, &property_filters_with_cohort);
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
        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            None, // No database client
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

        let result = matcher.get_match(&flag, None, None).await;
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
        );

        let hash = matcher.get_hash(&flag, "variant", None).await.unwrap();
        assert!(hash >= 0.0 && hash <= 1.0, "Hash should be between 0 and 1");

        let variant = matcher.get_matching_variant(&flag, None).await.unwrap();
        assert!(variant.is_some(), "A variant should be selected");

        // Test with specific hash values
        let test_cases = [
            (0.1, "control"),
            (0.3, "control"),
            (0.5, "test"),
            (0.7, "test2"),
            (0.9, "test2"),
        ];

        for (hard_coded_hash, expected_variant) in test_cases.iter() {
            let test_variant = matcher
                .get_matching_variant(&flag, Some(*hard_coded_hash))
                .await
                .unwrap();
            assert_eq!(
                test_variant.as_deref(),
                Some(*expected_variant),
                "For hash {}, expected variant {}",
                hard_coded_hash,
                expected_variant
            );
        }

        // Test distribution over 100 iterations
        let mut variant_counts: HashMap<String, i32> = HashMap::new();
        let iterations = 100;

        for i in 0..iterations {
            let hard_coded_hash = i as f64 / iterations as f64;
            let test_variant = matcher
                .get_matching_variant(&flag, Some(hard_coded_hash))
                .await
                .unwrap();
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
                let matcher = FeatureFlagMatcher::new(
                    format!("test_user_{}", i),
                    team.id,
                    Some(client_clone),
                    None,
                    None,
                );
                matcher.get_match(&flag_clone, None, None).await.unwrap()
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
