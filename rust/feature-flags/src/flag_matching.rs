use crate::{
    api::{FlagError, FlagValue, FlagsResponse},
    database::Client as DatabaseClient,
    feature_flag_match_reason::FeatureFlagMatchReason,
    flag_definitions::{FeatureFlag, FeatureFlagList, FlagGroupType, PropertyFilter},
    property_matching::match_property,
};
use anyhow::Result;
use serde_json::Value;
use sha1::{Digest, Sha1};
use sqlx::FromRow;
use std::collections::{HashMap, HashSet};
use std::fmt::Write;
use std::sync::Arc;
use tracing::error;

type TeamId = i32;
type DatabaseClientArc = Arc<dyn DatabaseClient + Send + Sync>;
type GroupTypeIndex = i32;

#[derive(Debug)]
struct SuperConditionEvaluation {
    should_evaluate: bool,
    is_match: bool,
    reason: FeatureFlagMatchReason,
}

#[derive(Debug, PartialEq, Eq)]
pub struct FeatureFlagMatch {
    pub matches: bool,
    pub variant: Option<String>,
    pub reason: FeatureFlagMatchReason,
    pub condition_index: Option<usize>,
    pub payload: Option<Value>,
}

#[derive(Debug, FromRow)]
pub struct GroupTypeMapping {
    pub group_type: String,
    pub group_type_index: GroupTypeIndex,
}

/// This struct is a cache for group type mappings, which are stored in a DB.  We use these mappings
/// to look up group names based on the group aggregation indices stored on flag filters, which lets us
/// perform group property matching.  We cache them per request so that we can perform multiple flag evaluations
/// without needing to fetch the mappings from the DB each time.
/// Typically, the mappings look like this:
///
/// let group_types = vec![
///     ("project", 0),
///     ("organization", 1),
///     ("instance", 2),
///     ("customer", 3),
///     ("team", 4),  ];
///
/// But for backwards compatibility, we also support whatever mappings may lie in the table.
/// These mappings are ingested via the plugin server.
#[derive(Clone)]
pub struct GroupTypeMappingCache {
    team_id: TeamId,
    failed_to_fetch_flags: bool,
    group_types_to_indexes: HashMap<String, GroupTypeIndex>,
    group_indexes_to_types: HashMap<GroupTypeIndex, String>,
    database_client: DatabaseClientArc,
}

impl GroupTypeMappingCache {
    pub fn new(team_id: TeamId, database_client: DatabaseClientArc) -> Self {
        GroupTypeMappingCache {
            team_id,
            failed_to_fetch_flags: false,
            group_types_to_indexes: HashMap::new(),
            group_indexes_to_types: HashMap::new(),
            database_client,
        }
    }

    pub async fn group_type_to_group_type_index_map(
        &mut self,
    ) -> Result<HashMap<String, GroupTypeIndex>, FlagError> {
        if self.failed_to_fetch_flags {
            return Err(FlagError::DatabaseUnavailable);
        }

        if !self.group_types_to_indexes.is_empty() {
            return Ok(self.group_types_to_indexes.clone());
        }

        let database_client = self.database_client.clone();
        let team_id = self.team_id;
        let mapping = match self
            .fetch_group_type_mapping(database_client, team_id)
            .await
        {
            Ok(mapping) if !mapping.is_empty() => mapping,
            Ok(_) => {
                self.failed_to_fetch_flags = true;
                return Err(FlagError::NoGroupTypeMappings);
            }
            Err(e) => {
                self.failed_to_fetch_flags = true;
                return Err(e);
            }
        };
        self.group_types_to_indexes.clone_from(&mapping);

        Ok(mapping)
    }

    pub async fn group_type_index_to_group_type_map(
        &mut self,
    ) -> Result<HashMap<GroupTypeIndex, String>, FlagError> {
        if !self.group_indexes_to_types.is_empty() {
            return Ok(self.group_indexes_to_types.clone());
        }

        let types_to_indexes = self.group_type_to_group_type_index_map().await?;
        let result: HashMap<GroupTypeIndex, String> =
            types_to_indexes.into_iter().map(|(k, v)| (v, k)).collect();

        if !result.is_empty() {
            self.group_indexes_to_types.clone_from(&result);
            Ok(result)
        } else {
            Err(FlagError::NoGroupTypeMappings)
        }
    }

    async fn fetch_group_type_mapping(
        &mut self,
        database_client: DatabaseClientArc,
        team_id: TeamId,
    ) -> Result<HashMap<String, GroupTypeIndex>, FlagError> {
        let mut conn = database_client.as_ref().get_connection().await?;

        let query = r#"
            SELECT group_type, group_type_index 
            FROM posthog_grouptypemapping 
            WHERE team_id = $1
        "#;

        let rows = sqlx::query_as::<_, GroupTypeMapping>(query)
            .bind(team_id)
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

/// This struct is a cache for group and person properties fetched from the database.  
/// We cache them per request so that we can perform multiple flag evaluations without needing
/// to fetch the properties from the DB each time.
#[derive(Clone, Default, Debug)]
pub struct PropertiesCache {
    person_properties: Option<HashMap<String, Value>>,
    group_properties: HashMap<GroupTypeIndex, HashMap<String, Value>>,
}

#[derive(Clone)]
pub struct FeatureFlagMatcher {
    pub distinct_id: String,
    pub team_id: TeamId,
    pub database_client: DatabaseClientArc,
    group_type_mapping_cache: GroupTypeMappingCache,
    properties_cache: PropertiesCache,
    groups: HashMap<String, Value>,
}

const LONG_SCALE: u64 = 0xfffffffffffffff;

impl FeatureFlagMatcher {
    pub fn new(
        distinct_id: String,
        team_id: TeamId,
        database_client: DatabaseClientArc,
        group_type_mapping_cache: Option<GroupTypeMappingCache>,
        properties_cache: Option<PropertiesCache>,
        groups: Option<HashMap<String, Value>>,
    ) -> Self {
        FeatureFlagMatcher {
            distinct_id,
            team_id,
            database_client: database_client.clone(),
            group_type_mapping_cache: group_type_mapping_cache
                .unwrap_or_else(|| GroupTypeMappingCache::new(team_id, database_client.clone())),
            properties_cache: properties_cache.unwrap_or_default(),
            groups: groups.unwrap_or_default(),
        }
    }

    /// Evaluate feature flags for a given distinct_id
    /// - Returns a map of feature flag keys to their values
    /// - If an error occurs while evaluating a flag, it will be logged and the flag will be omitted from the result
    pub async fn evaluate_feature_flags(
        &mut self,
        feature_flags: FeatureFlagList,
        person_property_overrides: Option<HashMap<String, Value>>,
        group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    ) -> FlagsResponse {
        let mut result = HashMap::new();
        let mut error_while_computing_flags = false;
        let mut flags_needing_db_properties = Vec::new();

        // Step 1: Evaluate flags that can be resolved with overrides
        for flag in &feature_flags.flags {
            // Skip inactive or deleted flags
            if !flag.active || flag.deleted {
                continue;
            }

            // Get any flag matches with overrides, assuming that these overrides can be computed locally
            match self
                .match_flag_with_overrides(
                    flag,
                    &person_property_overrides,
                    &group_property_overrides,
                )
                .await
            {
                Ok(Some(flag_match)) => {
                    let flag_value = self.flag_match_to_value(&flag_match);
                    result.insert(flag.key.clone(), flag_value);
                }
                Ok(None) => {
                    flags_needing_db_properties.push(flag.clone());
                }
                // We had overrides, but couldn't evaluate the flag
                Err(e) => {
                    error_while_computing_flags = true;
                    error!(
                        "Error evaluating feature flag '{}' with overrides for distinct_id '{}': {:?}",
                        flag.key, self.distinct_id, e
                    );
                }
            }
        }

        // At this point, we have a list of flags that we couldn't locally evaluate (with overrides, or without), so
        // we need to hit the DB to fetch the properties for these flags to continue our evaluation.

        // Step 2: Fetch and cache properties for remaining flags
        if !flags_needing_db_properties.is_empty() {
            let group_type_indexes: HashSet<GroupTypeIndex> = flags_needing_db_properties
                .iter()
                .filter_map(|flag| flag.get_group_type_index())
                .collect();

            let database_client = self.database_client.clone();
            let distinct_id = self.distinct_id.clone();
            let team_id = self.team_id;

            match fetch_and_locally_cache_all_properties(
                &mut self.properties_cache,
                database_client,
                distinct_id,
                team_id,
                &group_type_indexes,
            )
            .await
            {
                Ok(_) => {} // `fetch_and_locally_cache_all_properties` returns void on success,
                // so at this point we know we've cached the properties, and can continue.
                Err(e) => {
                    error_while_computing_flags = true;
                    error!("Error fetching properties: {:?}", e);
                }
            }

            // Step 3: Evaluate remaining flags
            for flag in flags_needing_db_properties {
                match self.get_match(&flag, None).await {
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

        FlagsResponse {
            error_while_computing_flags,
            feature_flags: result,
        }
    }

    /// Matches a feature flag with property overrides.
    ///
    /// This function attempts to match a feature flag using either group or person property overrides,
    /// depending on whether the flag is group-based or person-based. It first collects all property
    /// filters from the flag's conditions, then retrieves the appropriate overrides, and finally
    /// attempts to match the flag using these overrides.
    async fn match_flag_with_overrides(
        &mut self,
        flag: &FeatureFlag,
        person_property_overrides: &Option<HashMap<String, Value>>,
        group_property_overrides: &Option<HashMap<String, HashMap<String, Value>>>,
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
            Some(props) => self.get_match(flag, Some(props)).await.map(Some),
            None => Ok(None),
        }
    }

    /// Retrieves group overrides for a specific group type index.
    ///
    /// This function attempts to find and return property overrides for a given group type.
    /// It first maps the group type index to a group type, then checks if there are any
    /// overrides for that group type in the provided group property overrides.
    async fn get_group_overrides(
        &mut self,
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

    /// Retrieves person overrides for feature flag evaluation.
    ///
    /// This function attempts to find and return property overrides for a person.
    /// It uses the provided person property overrides and filters them based on
    /// the property filters defined in the feature flag.
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

    /// Determines if a feature flag matches for the current context.
    ///
    /// This method evaluates the conditions of a feature flag to determine if it should be enabled,
    /// and if so, which variant (if any) should be applied. It follows these steps:
    ///
    /// 1. Check if there's a valid hashed identifier for the flag.
    /// 2. Evaluate any super conditions that might override normal conditions.
    /// 3. Sort and evaluate each condition, prioritizing those with variant overrides.
    /// 4. For each matching condition, determine the appropriate variant and payload.
    /// 5. Return the result of the evaluation, including match status, variant, reason, and payload.
    ///
    /// The method also keeps track of the highest priority match reason and index,
    /// which are used even if no conditions ultimately match.
    pub async fn get_match(
        &mut self,
        flag: &FeatureFlag,
        property_overrides: Option<HashMap<String, Value>>,
    ) -> Result<FeatureFlagMatch, FlagError> {
        if self.hashed_identifier(flag).await?.is_empty() {
            return Ok(FeatureFlagMatch {
                matches: false,
                variant: None,
                reason: FeatureFlagMatchReason::NoGroupType,
                condition_index: None,
                payload: None,
            });
        }

        let mut highest_match = FeatureFlagMatchReason::NoConditionMatch;
        let mut highest_index = None;

        // Evaluate any super conditions first
        if let Some(super_groups) = &flag.filters.super_groups {
            if !super_groups.is_empty() {
                let super_condition_evaluation = self
                    .is_super_condition_match(flag, property_overrides.clone())
                    .await?;

                if super_condition_evaluation.should_evaluate {
                    let payload = self.get_matching_payload(None, flag);
                    return Ok(FeatureFlagMatch {
                        matches: super_condition_evaluation.is_match,
                        variant: None,
                        reason: super_condition_evaluation.reason,
                        condition_index: Some(0),
                        payload,
                    });
                } // if no match, continue to normal conditions
            }
        }

        // Sort conditions with variant overrides to the top so that we can evaluate them first
        let mut sorted_conditions: Vec<(usize, &FlagGroupType)> =
            flag.get_conditions().iter().enumerate().collect();

        sorted_conditions
            .sort_by_key(|(_, condition)| if condition.variant.is_some() { 0 } else { 1 });

        for (index, condition) in sorted_conditions {
            let (is_match, reason) = self
                .is_condition_match(flag, condition, property_overrides.clone())
                .await?;

            // Update highest_match and highest_index
            let (new_highest_match, new_highest_index) = self
                .get_highest_priority_match_evaluation(
                    highest_match.clone(),
                    highest_index,
                    reason.clone(),
                    Some(index),
                );
            highest_match = new_highest_match;
            highest_index = new_highest_index;

            if is_match {
                if highest_match == FeatureFlagMatchReason::SuperConditionValue {
                    break; // Exit early if we've found a super condition match
                }

                let variant = self.get_matching_variant(flag).await?;
                let payload = self.get_matching_payload(variant.as_deref(), flag);

                return Ok(FeatureFlagMatch {
                    matches: true,
                    variant,
                    reason: highest_match,
                    condition_index: highest_index,
                    payload,
                });
            }
        }

        // Return with the highest_match reason and index even if no conditions matched
        Ok(FeatureFlagMatch {
            matches: false,
            variant: None,
            reason: highest_match,
            condition_index: highest_index,
            payload: None,
        })
    }

    /// This function determines the highest priority match evaluation for feature flag conditions.
    /// It compares the current match reason with a new match reason and returns the higher priority one.
    /// The priority is determined by the ordering of FeatureFlagMatchReason variants.
    /// It's used to keep track of the most significant reason why a flag matched or didn't match,
    /// which is especially useful when multiple conditions are evaluated.
    fn get_highest_priority_match_evaluation(
        &self,
        current_match: FeatureFlagMatchReason,
        current_index: Option<usize>,
        new_match: FeatureFlagMatchReason,
        new_index: Option<usize>,
    ) -> (FeatureFlagMatchReason, Option<usize>) {
        if current_match <= new_match {
            (new_match, new_index)
        } else {
            (current_match, current_index)
        }
    }

    /// Check if a condition matches for a feature flag.
    ///
    /// This function evaluates a specific condition of a feature flag to determine if it should be enabled.
    /// It first checks if the condition has any property filters. If not, it performs a rollout check.
    /// Otherwise, it fetches the relevant properties and checks if they match the condition's filters.
    /// The function returns a tuple indicating whether the condition matched and the reason for the match.
    async fn is_condition_match(
        &mut self,
        feature_flag: &FeatureFlag,
        condition: &FlagGroupType,
        property_overrides: Option<HashMap<String, Value>>,
    ) -> Result<(bool, FeatureFlagMatchReason), FlagError> {
        let rollout_percentage = condition.rollout_percentage.unwrap_or(100.0);

        if let Some(flag_property_filters) = &condition.properties {
            if flag_property_filters.is_empty() {
                return self.check_rollout(feature_flag, rollout_percentage).await;
            }

            // NB: we can only evaluate group or person properties, not both
            let properties_to_check = self
                .get_properties_to_check(feature_flag, property_overrides, flag_property_filters)
                .await?;

            if !all_properties_match(flag_property_filters, &properties_to_check) {
                return Ok((false, FeatureFlagMatchReason::NoConditionMatch));
            }
        }

        self.check_rollout(feature_flag, rollout_percentage).await
    }

    /// Get properties to check for a feature flag.
    ///
    /// This function determines which properties to check based on the feature flag's group type index.
    /// If the flag is group-based, it fetches group properties; otherwise, it fetches person properties.
    async fn get_properties_to_check(
        &mut self,
        feature_flag: &FeatureFlag,
        property_overrides: Option<HashMap<String, Value>>,
        flag_property_filters: &[PropertyFilter],
    ) -> Result<HashMap<String, Value>, FlagError> {
        if let Some(group_type_index) = feature_flag.get_group_type_index() {
            self.get_group_properties(group_type_index, property_overrides, flag_property_filters)
                .await
        } else {
            self.get_person_properties(property_overrides, flag_property_filters)
                .await
        }
    }

    /// Get group properties from cache or database.
    ///
    /// This function attempts to retrieve group properties either from a cache or directly from the database.
    /// It first checks if there are any locally computable property overrides. If so, it returns those.
    /// Otherwise, it fetches the properties from the cache or database and returns them.
    async fn get_group_properties(
        &mut self,
        group_type_index: GroupTypeIndex,
        property_overrides: Option<HashMap<String, Value>>,
        flag_property_filters: &[PropertyFilter],
    ) -> Result<HashMap<String, Value>, FlagError> {
        if let Some(overrides) =
            locally_computable_property_overrides(&property_overrides, flag_property_filters)
        {
            Ok(overrides)
        } else {
            self.get_group_properties_from_cache_or_db(group_type_index)
                .await
        }
    }

    /// Get person properties from cache or database.
    ///
    /// This function attempts to retrieve person properties either from a cache or directly from the database.
    /// It first checks if there are any locally computable property overrides. If so, it returns those.
    /// Otherwise, it fetches the properties from the cache or database and returns them.
    async fn get_person_properties(
        &mut self,
        property_overrides: Option<HashMap<String, Value>>,
        flag_property_filters: &[PropertyFilter],
    ) -> Result<HashMap<String, Value>, FlagError> {
        if let Some(overrides) =
            locally_computable_property_overrides(&property_overrides, flag_property_filters)
        {
            Ok(overrides)
        } else {
            self.get_person_properties_from_cache_or_db().await
        }
    }

    /// Check if a super condition matches for a feature flag.
    ///
    /// This function evaluates the super conditions of a feature flag to determine if any of them should be enabled.
    /// It first checks if there are any super conditions. If so, it evaluates the first condition.
    /// The function returns a struct indicating whether a super condition should be evaluated,
    /// whether it matches if evaluated, and the reason for the match.
    async fn is_super_condition_match(
        &mut self,
        feature_flag: &FeatureFlag,
        property_overrides: Option<HashMap<String, Value>>,
    ) -> Result<SuperConditionEvaluation, FlagError> {
        if let Some(first_condition) = feature_flag
            .filters
            .super_groups
            .as_ref()
            .and_then(|sc| sc.first())
        {
            // Need to fetch person properties to check super conditions.  If these properties are already locally computable,
            // we don't need to fetch from the database, but if they aren't we need to fetch from the database and then we'll cache them.
            let person_properties = self
                .get_person_properties(
                    property_overrides,
                    first_condition.properties.as_deref().unwrap_or(&[]),
                )
                .await?;

            let has_relevant_super_condition_properties =
                first_condition.properties.as_ref().map_or(false, |props| {
                    props
                        .iter()
                        .any(|prop| person_properties.contains_key(&prop.key))
                });

            let (is_match, _) = self
                .is_condition_match(feature_flag, first_condition, Some(person_properties))
                .await?;

            if has_relevant_super_condition_properties {
                return Ok(SuperConditionEvaluation {
                    should_evaluate: true,
                    is_match,
                    reason: FeatureFlagMatchReason::SuperConditionValue,
                });
                // If there is a super condition evaluation, return early with those results.
                // The reason is super condition value because we're not evaluating the rest of the conditions.
            }
        }

        Ok(SuperConditionEvaluation {
            should_evaluate: false,
            is_match: false,
            reason: FeatureFlagMatchReason::NoConditionMatch,
        })
    }

    /// Get group properties from cache or database.
    ///
    /// This function attempts to retrieve group properties either from a cache or directly from the database.
    /// It first checks if the properties are already cached. If so, it returns those.
    /// Otherwise, it fetches the properties from the database and caches them.
    async fn get_group_properties_from_cache_or_db(
        &mut self,
        group_type_index: GroupTypeIndex,
    ) -> Result<HashMap<String, Value>, FlagError> {
        // check if the properties are already cached, if so return them
        if let Some(properties) = self
            .properties_cache
            .group_properties
            .get(&group_type_index)
        {
            let mut result = HashMap::new();
            result.clone_from(properties);
            return Ok(result);
        }

        let database_client = self.database_client.clone();
        let team_id = self.team_id;
        let db_properties =
            fetch_group_properties_from_db(database_client, team_id, group_type_index).await?;

        // once the properties are fetched, cache them so we don't need to fetch again in a given request
        self.properties_cache
            .group_properties
            .insert(group_type_index, db_properties.clone());

        Ok(db_properties)
    }

    /// Get person properties from cache or database.
    ///
    /// This function attempts to retrieve person properties either from a cache or directly from the database.
    /// It first checks if the properties are already cached. If so, it returns those.
    /// Otherwise, it fetches the properties from the database and caches them.
    async fn get_person_properties_from_cache_or_db(
        &mut self,
    ) -> Result<HashMap<String, Value>, FlagError> {
        // check if the properties are already cached, if so return them
        if let Some(properties) = &self.properties_cache.person_properties {
            let mut result = HashMap::new();
            result.clone_from(properties);
            return Ok(result);
        }

        let database_client = self.database_client.clone();
        let distinct_id = self.distinct_id.clone();
        let team_id = self.team_id;
        let db_properties =
            fetch_person_properties_from_db(database_client, distinct_id, team_id).await?;

        // once the properties are fetched, cache them so we don't need to fetch again in a given request
        self.properties_cache.person_properties = Some(db_properties.clone());

        Ok(db_properties)
    }

    /// Get hashed identifier for a feature flag.
    ///
    /// This function generates a hashed identifier for a feature flag based on the feature flag's group type index.
    /// If the feature flag is group-based, it fetches the group key; otherwise, it uses the distinct ID.
    async fn hashed_identifier(&mut self, feature_flag: &FeatureFlag) -> Result<String, FlagError> {
        // TODO: Use hash key overrides for experience continuity

        if let Some(group_type_index) = feature_flag.get_group_type_index() {
            // Group-based flag
            let group_key = self
                .group_type_mapping_cache
                .group_type_index_to_group_type_map()
                .await?
                .get(&group_type_index)
                .and_then(|group_type_name| self.groups.get(group_type_name))
                .cloned()
                .unwrap_or_default();

            Ok(group_key.to_string())
        } else {
            // Person-based flag
            Ok(self.distinct_id.clone())
        }
    }

    /// This function takes a identifier and a feature flag key and returns a float between 0 and 1.
    /// Given the same identifier and key, it'll always return the same float. These floats are
    /// uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    /// we can do _hash(key, identifier) < 0.2
    async fn get_hash(&mut self, feature_flag: &FeatureFlag, salt: &str) -> Result<f64, FlagError> {
        let hashed_identifier = self.hashed_identifier(feature_flag).await?;
        if hashed_identifier.is_empty() {
            // Return a hash value that will make the flag evaluate to false
            // TODO make this cleaner – we should have a way to return a default value
            return Ok(0.0);
        }
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

    /// Check if a feature flag should be shown based on its rollout percentage.
    ///
    /// This function determines if a feature flag should be shown to a user based on the flag's rollout percentage.
    /// It first calculates a hash of the feature flag's identifier and compares it to the rollout percentage.
    /// If the hash value is less than or equal to the rollout percentage, the flag is shown; otherwise, it is not.
    /// The function returns a tuple indicating whether the flag matched and the reason for the match.
    async fn check_rollout(
        &mut self,
        feature_flag: &FeatureFlag,
        rollout_percentage: f64,
    ) -> Result<(bool, FeatureFlagMatchReason), FlagError> {
        let hash = self.get_hash(feature_flag, "").await?;
        if rollout_percentage == 100.0 || hash <= (rollout_percentage / 100.0) {
            Ok((true, FeatureFlagMatchReason::ConditionMatch))
        } else {
            Ok((false, FeatureFlagMatchReason::OutOfRolloutBound))
        }
    }

    /// This function takes a feature flag and returns the key of the variant that should be shown to the user.
    async fn get_matching_variant(
        &mut self,
        feature_flag: &FeatureFlag,
    ) -> Result<Option<String>, FlagError> {
        let hash = self.get_hash(feature_flag, "variant").await?;
        let mut cumulative_percentage = 0.0;

        for variant in feature_flag.get_variants() {
            cumulative_percentage += variant.rollout_percentage / 100.0;
            if hash < cumulative_percentage {
                return Ok(Some(variant.key.clone()));
            }
        }
        Ok(None)
    }

    /// Get matching payload for a feature flag.
    ///
    /// This function retrieves the payload associated with a matching variant of a feature flag.
    /// It takes the matched variant key and the feature flag itself as inputs and returns the payload.
    fn get_matching_payload(
        &self,
        match_variant: Option<&str>,
        feature_flag: &FeatureFlag,
    ) -> Option<serde_json::Value> {
        let variant = match_variant.unwrap_or("true");
        feature_flag.get_payload(variant)
    }
}

/// Fetch and locally cache all properties for a given distinct ID and team ID.
///
/// This function fetches both person and group properties for a specified distinct ID and team ID.
/// It updates the properties cache with the fetched properties and returns the result.
async fn fetch_and_locally_cache_all_properties(
    properties_cache: &mut PropertiesCache,
    database_client: DatabaseClientArc,
    distinct_id: String,
    team_id: TeamId,
    group_type_indexes: &HashSet<GroupTypeIndex>,
) -> Result<(), FlagError> {
    let mut conn = database_client.as_ref().get_connection().await?;

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

    let group_type_indexes_vec: Vec<GroupTypeIndex> = group_type_indexes.iter().cloned().collect();

    let row: (Option<Value>, Option<Value>) = sqlx::query_as(query)
        .bind(&distinct_id)
        .bind(team_id)
        .bind(&group_type_indexes_vec)
        .fetch_optional(&mut *conn)
        .await?
        .unwrap_or((None, None));

    if let Some(person_props) = row.0 {
        properties_cache.person_properties = Some(
            person_props
                .as_object()
                .unwrap_or(&serde_json::Map::new())
                .iter()
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
        );
    }

    if let Some(group_props) = row.1 {
        let group_props_map: HashMap<GroupTypeIndex, HashMap<String, Value>> = group_props
            .as_object()
            .unwrap_or(&serde_json::Map::new())
            .iter()
            .map(|(k, v)| {
                let group_type_index = k.parse().unwrap_or_default();
                let properties: HashMap<String, Value> = v
                    .as_object()
                    .unwrap_or(&serde_json::Map::new())
                    .iter()
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect();
                (group_type_index, properties)
            })
            .collect();

        properties_cache.group_properties.extend(group_props_map);
    }

    Ok(())
}

/// Fetch person properties from the database for a given distinct ID and team ID.
///
/// This function constructs and executes a SQL query to fetch the person properties for a specified distinct ID and team ID.
/// It returns the fetched properties as a HashMap.
async fn fetch_person_properties_from_db(
    database_client: DatabaseClientArc,
    distinct_id: String,
    team_id: TeamId,
) -> Result<HashMap<String, Value>, FlagError> {
    let mut conn = database_client.as_ref().get_connection().await?;

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
        .bind(&distinct_id)
        .bind(team_id)
        .fetch_optional(&mut *conn)
        .await?;

    Ok(row
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_default()
        .into_iter()
        .map(|(k, v)| (k, v.clone()))
        .collect())
}

/// Fetch group properties from the database for a given team ID and group type index.
///
/// This function constructs and executes a SQL query to fetch the group properties for a specified team ID and group type index.
/// It returns the fetched properties as a HashMap.
async fn fetch_group_properties_from_db(
    database_client: DatabaseClientArc,
    team_id: TeamId,
    group_type_index: GroupTypeIndex,
) -> Result<HashMap<String, Value>, FlagError> {
    let mut conn = database_client.as_ref().get_connection().await?;

    let query = r#"
        SELECT "posthog_group"."group_properties"
        FROM "posthog_group"
        WHERE ("posthog_group"."team_id" = $1
                AND "posthog_group"."group_type_index" = $2)
        LIMIT 1
    "#;

    let row: Option<Value> = sqlx::query_scalar(query)
        .bind(team_id)
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

/// Check if all properties match the given filters
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
    use std::collections::HashMap;

    use super::*;
    use crate::{
        flag_definitions::{
            FlagFilters, MultivariateFlagOptions, MultivariateFlagVariant, OperatorType,
        },
        test_utils::{insert_new_team_in_pg, insert_person_for_team_in_pg, setup_pg_client},
    };

    fn create_test_flag(
        id: Option<i32>,
        team_id: Option<TeamId>,
        name: Option<String>,
        key: Option<String>,
        filters: Option<FlagFilters>,
        deleted: Option<bool>,
        active: Option<bool>,
        ensure_experience_continuity: Option<bool>,
    ) -> FeatureFlag {
        FeatureFlag {
            id: id.unwrap_or(1),
            team_id: team_id.unwrap_or(1),
            name: name.or(Some("Test Flag".to_string())),
            key: key.unwrap_or_else(|| "test_flag".to_string()),
            filters: filters.unwrap_or_else(|| FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            deleted: deleted.unwrap_or(false),
            active: active.unwrap_or(true),
            ensure_experience_continuity: ensure_experience_continuity.unwrap_or(false),
        }
    }

    #[tokio::test]
    async fn test_fetch_properties_from_pg_to_match() {
        let database_client = setup_pg_client(None).await;

        let team = insert_new_team_in_pg(database_client.clone())
            .await
            .expect("Failed to insert team in pg");

        let distinct_id = "user_distinct_id".to_string();
        insert_person_for_team_in_pg(database_client.clone(), team.id, distinct_id.clone(), None)
            .await
            .expect("Failed to insert person");

        let not_matching_distinct_id = "not_matching_distinct_id".to_string();
        insert_person_for_team_in_pg(
            database_client.clone(),
            team.id,
            not_matching_distinct_id.clone(),
            Some(json!({ "email": "a@x.com"})),
        )
        .await
        .expect("Failed to insert person");

        let flag: FeatureFlag = serde_json::from_value(json!(
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
            distinct_id.clone(),
            team.id,
            database_client.clone(),
            None,
            None,
            None,
        );
        let match_result = matcher.get_match(&flag, None).await.unwrap();
        assert!(match_result.matches);
        assert_eq!(match_result.variant, None);

        let mut matcher = FeatureFlagMatcher::new(
            not_matching_distinct_id.clone(),
            team.id,
            database_client.clone(),
            None,
            None,
            None,
        );
        let match_result = matcher.get_match(&flag, None).await.unwrap();
        assert!(!match_result.matches);
        assert_eq!(match_result.variant, None);

        let mut matcher = FeatureFlagMatcher::new(
            "other_distinct_id".to_string(),
            team.id,
            database_client.clone(),
            None,
            None,
            None,
        );
        let match_result = matcher.get_match(&flag, None).await.unwrap();
        assert!(!match_result.matches);
        assert_eq!(match_result.variant, None);
    }

    #[tokio::test]
    async fn test_person_property_overrides() {
        let database_client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(database_client.clone())
            .await
            .unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: json!("override@example.com"),
                        operator: None,
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
            }),
            None,
            None,
            None,
        );

        let overrides = HashMap::from([("email".to_string(), json!("override@example.com"))]);

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            database_client,
            None,
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };
        let result = matcher
            .evaluate_feature_flags(flags, Some(overrides), None)
            .await;
        assert!(!result.error_while_computing_flags);
        assert_eq!(
            result.feature_flags.get("test_flag"),
            Some(&FlagValue::Boolean(true))
        );
    }

    #[tokio::test]
    async fn test_group_property_overrides() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "industry".to_string(),
                        value: json!("tech"),
                        operator: None,
                        prop_type: "group".to_string(),
                        group_type_index: Some(1),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: Some(1),
                payloads: None,
                super_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut cache = GroupTypeMappingCache::new(team.id, client.clone());
        let group_types_to_indexes = [("organization".to_string(), 1)].into_iter().collect();
        cache.group_types_to_indexes = group_types_to_indexes;
        cache.group_indexes_to_types = [(1, "organization".to_string())].into_iter().collect();

        let groups = HashMap::from([("organization".to_string(), json!("org_123"))]);

        let group_overrides = HashMap::from([(
            "organization".to_string(),
            HashMap::from([
                ("industry".to_string(), json!("tech")),
                ("$group_key".to_string(), json!("org_123")),
            ]),
        )]);

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            client.clone(),
            Some(cache),
            None,
            Some(groups),
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };
        let result = matcher
            .evaluate_feature_flags(flags, None, Some(group_overrides))
            .await;

        assert!(!result.error_while_computing_flags);
        assert_eq!(
            result.feature_flags.get("test_flag"),
            Some(&FlagValue::Boolean(true))
        );
    }

    #[tokio::test]
    async fn test_get_matching_variant_with_cache() {
        let flag = create_test_flag_with_variants(1);
        let database_client = setup_pg_client(None).await;

        let mut cache = GroupTypeMappingCache::new(1, database_client.clone());

        let group_types_to_indexes = [("group_type_1".to_string(), 1)].into_iter().collect();
        let group_type_index_to_name = [(1, "group_type_1".to_string())].into_iter().collect();

        cache.group_types_to_indexes = group_types_to_indexes;
        cache.group_indexes_to_types = group_type_index_to_name;

        let groups = HashMap::from([("group_type_1".to_string(), json!("group_key_1"))]);

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            database_client.clone(),
            Some(cache),
            None,
            Some(groups),
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

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            database_client.clone(),
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
        let database_client = setup_pg_client(None).await;
        let flag = create_test_flag(
            Some(1),
            None,
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            None,
            None,
        );

        let condition = FlagGroupType {
            variant: None,
            properties: Some(vec![]),
            rollout_percentage: Some(100.0),
        };

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            database_client,
            None,
            None,
            None,
        );
        let (is_match, reason) = matcher
            .is_condition_match(&flag, &condition, None)
            .await
            .unwrap();
        assert!(is_match);
        assert_eq!(reason, FeatureFlagMatchReason::ConditionMatch);
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
    async fn test_overrides_avoid_db_lookups() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: json!("test@example.com"),
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
            }),
            None,
            None,
            None,
        );

        let person_property_overrides =
            HashMap::from([("email".to_string(), json!("test@example.com"))]);

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let result = matcher
            .evaluate_feature_flags(
                FeatureFlagList {
                    flags: vec![flag.clone()],
                },
                Some(person_property_overrides),
                None,
            )
            .await;

        assert!(!result.error_while_computing_flags);
        assert_eq!(
            result.feature_flags.get("test_flag"),
            Some(&FlagValue::Boolean(true))
        );

        let cache = &matcher.properties_cache;
        assert!(cache.person_properties.is_none());
    }

    #[tokio::test]
    async fn test_fallback_to_db_when_overrides_insufficient() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
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
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            None,
            None,
        );

        let person_property_overrides = Some(HashMap::from([(
            "email".to_string(),
            json!("test@example.com"),
        )]));

        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "test@example.com", "age": 30})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let result = matcher
            .get_match(&flag, person_property_overrides.clone())
            .await
            .unwrap();

        assert!(result.matches);

        let cache = &matcher.properties_cache;
        assert!(cache.person_properties.is_some());
        assert_eq!(
            cache.person_properties.as_ref().unwrap().get("age"),
            Some(&json!(30))
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

        let mut matcher =
            FeatureFlagMatcher::new(distinct_id, team.id, client.clone(), None, None, None);

        let properties = matcher
            .get_person_properties_from_cache_or_db()
            .await
            .unwrap();

        assert_eq!(properties.get("email").unwrap(), &json!("test@example.com"));
        assert_eq!(properties.get("age").unwrap(), &json!(30));

        let cached_properties = matcher.properties_cache.person_properties.clone();
        assert!(cached_properties.is_some());
        assert_eq!(
            cached_properties.unwrap().get("email").unwrap(),
            &json!("test@example.com")
        );
    }

    #[tokio::test]
    async fn test_property_caching() {
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

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        // First access should fetch from the database
        let start = std::time::Instant::now();
        let properties = matcher
            .get_person_properties_from_cache_or_db()
            .await
            .unwrap();
        let first_duration = start.elapsed();

        // Second access should use the cache and be faster
        let start = std::time::Instant::now();
        let cached_properties = matcher
            .get_person_properties_from_cache_or_db()
            .await
            .unwrap();
        let second_duration = start.elapsed();

        assert_eq!(properties, cached_properties);
        assert!(
            second_duration < first_duration,
            "Second access should be faster due to caching"
        );

        // Create a new matcher to simulate a fresh state
        let mut new_matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        // First access with new matcher should fetch from the database again
        let start = std::time::Instant::now();
        let new_properties = new_matcher
            .get_person_properties_from_cache_or_db()
            .await
            .unwrap();
        let new_first_duration = start.elapsed();

        assert_eq!(properties, new_properties);
        assert!(
            new_first_duration > second_duration,
            "First access with new matcher should be slower than cached access"
        );

        // Second access with new matcher should use the cache and be faster
        let start = std::time::Instant::now();
        let new_cached_properties = new_matcher
            .get_person_properties_from_cache_or_db()
            .await
            .unwrap();
        let new_second_duration = start.elapsed();

        assert_eq!(properties, new_cached_properties);
        assert!(
            new_second_duration < new_first_duration,
            "Second access with new matcher should be faster due to caching"
        );
    }

    #[tokio::test]
    async fn test_overrides_locally_computable() {
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
    async fn test_concurrent_flag_evaluation() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();
        let flag = Arc::new(create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            None,
            None,
        ));

        let mut handles = vec![];
        for i in 0..100 {
            let flag_clone = flag.clone();
            let client_clone = client.clone();
            handles.push(tokio::spawn(async move {
                let mut matcher = FeatureFlagMatcher::new(
                    format!("test_user_{}", i),
                    team.id,
                    client_clone,
                    None,
                    None,
                    None,
                );
                matcher.get_match(&flag_clone, None).await.unwrap()
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

    #[tokio::test]
    async fn test_property_operators() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![
                        PropertyFilter {
                            key: "age".to_string(),
                            value: json!(25),
                            operator: Some(OperatorType::Gte),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                        },
                        PropertyFilter {
                            key: "email".to_string(),
                            value: json!("example@domain.com"),
                            operator: Some(OperatorType::Icontains),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                        },
                    ]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            None,
            None,
        );

        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "user@example@domain.com", "age": 30})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None).await.unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_empty_hashed_identifier() {
        let client = setup_pg_client(None).await;

        let flag = create_test_flag(
            Some(1),
            None,
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut matcher = FeatureFlagMatcher::new("".to_string(), 1, client, None, None, None);

        let result = matcher.get_match(&flag, None).await.unwrap();

        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_rollout_percentage() {
        let client = setup_pg_client(None).await;

        let mut flag = create_test_flag(
            Some(1),
            None,
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![]),
                    rollout_percentage: Some(0.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut matcher =
            FeatureFlagMatcher::new("test_user".to_string(), 1, client, None, None, None);

        let result = matcher.get_match(&flag, None).await.unwrap();

        assert!(!result.matches);

        // Now set the rollout percentage to 100%
        flag.filters.groups[0].rollout_percentage = Some(100.0);

        let result = matcher.get_match(&flag, None).await.unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_uneven_variant_distribution() {
        let client = setup_pg_client(None).await;

        let mut flag = create_test_flag_with_variants(1);

        // Adjust variant rollout percentages to be uneven
        flag.filters.multivariate.as_mut().unwrap().variants = vec![
            MultivariateFlagVariant {
                name: Some("Control".to_string()),
                key: "control".to_string(),
                rollout_percentage: 10.0,
            },
            MultivariateFlagVariant {
                name: Some("Test".to_string()),
                key: "test".to_string(),
                rollout_percentage: 30.0,
            },
            MultivariateFlagVariant {
                name: Some("Test2".to_string()),
                key: "test2".to_string(),
                rollout_percentage: 60.0,
            },
        ];

        // Ensure the flag is person-based by setting aggregation_group_type_index to None
        flag.filters.aggregation_group_type_index = None;

        let mut matcher =
            FeatureFlagMatcher::new("test_user".to_string(), 1, client, None, None, None);

        let mut control_count = 0;
        let mut test_count = 0;
        let mut test2_count = 0;

        // Run the test multiple times to simulate distribution
        for i in 0..1000 {
            matcher.distinct_id = format!("user_{}", i);
            let variant = matcher.get_matching_variant(&flag).await.unwrap();
            match variant.as_deref() {
                Some("control") => control_count += 1,
                Some("test") => test_count += 1,
                Some("test2") => test2_count += 1,
                _ => (),
            }
        }

        // Check that the distribution roughly matches the rollout percentages
        let total = control_count + test_count + test2_count;
        assert!((control_count as f64 / total as f64 - 0.10).abs() < 0.05);
        assert!((test_count as f64 / total as f64 - 0.30).abs() < 0.05);
        assert!((test2_count as f64 / total as f64 - 0.60).abs() < 0.05);
    }

    #[tokio::test]
    async fn test_missing_properties_in_db() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        // Insert a person without properties
        insert_person_for_team_in_pg(client.clone(), team.id, "test_user".to_string(), None)
            .await
            .unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: json!("test@example.com"),
                        operator: None,
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
            }),
            None,
            None,
            None,
        );

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None).await.unwrap();

        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_malformed_property_data() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        // Insert a person with malformed properties
        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"age": "not_a_number"})),
        )
        .await
        .unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "age".to_string(),
                        value: json!(25),
                        operator: Some(OperatorType::Gte),
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
            }),
            None,
            None,
            None,
        );

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None).await.unwrap();

        // The match should fail due to invalid data type
        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_get_match_with_insufficient_overrides() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![
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
                    ]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            None,
            None,
        );

        let person_overrides = Some(HashMap::from([(
            "email".to_string(),
            json!("test@example.com"),
        )]));

        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "test@example.com", "age": 30})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let result = matcher.get_match(&flag, person_overrides).await.unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_evaluation_reasons() {
        let client = setup_pg_client(None).await;
        let flag = create_test_flag(
            Some(1),
            None,
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut matcher =
            FeatureFlagMatcher::new("test_user".to_string(), 1, client, None, None, None);

        let (is_match, reason) = matcher
            .is_condition_match(&flag, &flag.filters.groups[0], None)
            .await
            .unwrap();

        assert!(is_match);
        assert_eq!(reason, FeatureFlagMatchReason::ConditionMatch);
    }

    #[tokio::test]
    async fn test_complex_conditions() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Complex Flag".to_string()),
            Some("complex_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagGroupType {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: json!("user1@example.com"),
                            operator: None,
                            prop_type: "person".to_string(),
                            group_type_index: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    },
                    FlagGroupType {
                        properties: Some(vec![PropertyFilter {
                            key: "age".to_string(),
                            value: json!(30),
                            operator: Some(OperatorType::Gte),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            Some(false),
            Some(true),
            Some(false),
        );

        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "user2@example.com", "age": 35})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None).await.unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_super_condition_matches_boolean() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Super Condition Flag".to_string()),
            Some("super_condition_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagGroupType {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: json!("fake@posthog.com"),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                        }]),
                        rollout_percentage: Some(0.0),
                        variant: None,
                    },
                    FlagGroupType {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: json!("test@posthog.com"),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    },
                    FlagGroupType {
                        properties: None,
                        rollout_percentage: Some(50.0),
                        variant: None,
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "is_enabled".to_string(),
                        value: json!(["true"]),
                        operator: Some(OperatorType::Exact),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }]),
            }),
            None,
            None,
            None,
        );

        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            "test_id".to_string(),
            Some(json!({"email": "test@posthog.com", "is_enabled": true})),
        )
        .await
        .unwrap();

        let mut matcher_test_id = FeatureFlagMatcher::new(
            "test_id".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let mut matcher_example_id = FeatureFlagMatcher::new(
            "lil_id".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let mut matcher_another_id = FeatureFlagMatcher::new(
            "another_id".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let result_test_id = matcher_test_id.get_match(&flag, None).await.unwrap();
        let result_example_id = matcher_example_id.get_match(&flag, None).await.unwrap();
        let result_another_id = matcher_another_id.get_match(&flag, None).await.unwrap();

        assert!(result_test_id.matches);
        assert!(result_test_id.reason == FeatureFlagMatchReason::SuperConditionValue);
        assert!(result_example_id.matches);
        assert!(result_example_id.reason == FeatureFlagMatchReason::ConditionMatch);
        assert!(!result_another_id.matches);
        assert!(result_another_id.reason == FeatureFlagMatchReason::OutOfRolloutBound);
    }

    #[tokio::test]
    async fn test_super_condition_matches_string() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            "test_id".to_string(),
            Some(json!({"email": "test@posthog.com", "is_enabled": "true"})),
        )
        .await
        .unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Super Condition Flag".to_string()),
            Some("super_condition_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagGroupType {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: json!("fake@posthog.com"),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                        }]),
                        rollout_percentage: Some(0.0),
                        variant: None,
                    },
                    FlagGroupType {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: json!("test@posthog.com"),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    },
                    FlagGroupType {
                        properties: None,
                        rollout_percentage: Some(50.0),
                        variant: None,
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "is_enabled".to_string(),
                        value: json!("true"),
                        operator: Some(OperatorType::Exact),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }]),
            }),
            None,
            None,
            None,
        );

        let mut matcher = FeatureFlagMatcher::new(
            "test_id".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None).await.unwrap();

        assert!(result.matches);
        assert_eq!(result.reason, FeatureFlagMatchReason::SuperConditionValue);
        assert_eq!(result.condition_index, Some(0));
    }

    #[tokio::test]
    async fn test_super_condition_matches_and_false() {
        let client = setup_pg_client(None).await;
        let team = insert_new_team_in_pg(client.clone()).await.unwrap();

        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            "test_id".to_string(),
            Some(json!({"email": "test@posthog.com", "is_enabled": true})),
        )
        .await
        .unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Super Condition Flag".to_string()),
            Some("super_condition_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagGroupType {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: json!("fake@posthog.com"),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                        }]),
                        rollout_percentage: Some(0.0),
                        variant: None,
                    },
                    FlagGroupType {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: json!("test@posthog.com"),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    },
                    FlagGroupType {
                        properties: None,
                        rollout_percentage: Some(50.0),
                        variant: None,
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "is_enabled".to_string(),
                        value: json!(false),
                        operator: Some(OperatorType::Exact),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }]),
            }),
            None,
            None,
            None,
        );

        let mut matcher_test_id = FeatureFlagMatcher::new(
            "test_id".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let mut matcher_example_id = FeatureFlagMatcher::new(
            "lil_id".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let mut matcher_another_id = FeatureFlagMatcher::new(
            "another_id".to_string(),
            team.id,
            client.clone(),
            None,
            None,
            None,
        );

        let result_test_id = matcher_test_id.get_match(&flag, None).await.unwrap();
        let result_example_id = matcher_example_id.get_match(&flag, None).await.unwrap();
        let result_another_id = matcher_another_id.get_match(&flag, None).await.unwrap();

        assert!(!result_test_id.matches);
        assert_eq!(
            result_test_id.reason,
            FeatureFlagMatchReason::SuperConditionValue
        );
        assert_eq!(result_test_id.condition_index, Some(0));

        assert!(result_example_id.matches);
        assert_eq!(
            result_example_id.reason,
            FeatureFlagMatchReason::ConditionMatch
        );
        assert_eq!(result_example_id.condition_index, Some(2));

        assert!(!result_another_id.matches);
        assert_eq!(
            result_another_id.reason,
            FeatureFlagMatchReason::OutOfRolloutBound
        );
        assert_eq!(result_another_id.condition_index, Some(2));
    }
}
