use crate::{
    api::{FlagError, FlagValue, FlagsResponse},
    cohort_cache::CohortCacheManager,
    cohort_models::{Cohort, CohortId},
    database::Client as DatabaseClient,
    feature_flag_match_reason::FeatureFlagMatchReason,
    flag_definitions::{FeatureFlag, FeatureFlagList, FlagGroupType, OperatorType, PropertyFilter},
    metrics_consts::{FLAG_EVALUATION_ERROR_COUNTER, FLAG_HASH_KEY_WRITES_COUNTER},
    metrics_utils::parse_exception_for_prometheus_label,
    property_matching::match_property,
};
use anyhow::Result;
use common_metrics::inc;
use petgraph::algo::{is_cyclic_directed, toposort};
use petgraph::graph::DiGraph;
use serde_json::Value;
use sha1::{Digest, Sha1};
use sqlx::{postgres::PgQueryResult, Acquire, FromRow, Row};
use std::fmt::Write;
use std::sync::Arc;
use std::{
    collections::{HashMap, HashSet, VecDeque},
    time::Duration,
};
use tokio::time::{sleep, timeout};
use tracing::{error, info};

pub type TeamId = i32;
pub type PersonId = i32;
pub type GroupTypeIndex = i32;
pub type PostgresReader = Arc<dyn DatabaseClient + Send + Sync>;
pub type PostgresWriter = Arc<dyn DatabaseClient + Send + Sync>;

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
    postgres_reader: PostgresReader,
}

impl GroupTypeMappingCache {
    pub fn new(team_id: TeamId, postgres_reader: PostgresReader) -> Self {
        GroupTypeMappingCache {
            team_id,
            failed_to_fetch_flags: false,
            group_types_to_indexes: HashMap::new(),
            group_indexes_to_types: HashMap::new(),
            postgres_reader,
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

        let team_id = self.team_id;
        let mapping = match self
            .fetch_group_type_mapping(self.postgres_reader.clone(), team_id)
            .await
        {
            Ok(mapping) if !mapping.is_empty() => mapping,
            Ok(_) => {
                self.failed_to_fetch_flags = true;
                // TODO add the `"Failed to fetch group"` type of lable.  See posthog/models/feature_flag/flag_matching.py:parse_exception_for_error_message
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
            // TODO add the `"Failed to fetch group"` type of lable.  See posthog/models/feature_flag/flag_matching.py:parse_exception_for_error_message
            Err(FlagError::NoGroupTypeMappings)
        }
    }

    async fn fetch_group_type_mapping(
        &mut self,
        postgres_reader: PostgresReader,
        team_id: TeamId,
    ) -> Result<HashMap<String, GroupTypeIndex>, FlagError> {
        let mut conn = postgres_reader.as_ref().get_connection().await?;

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
            // TODO add the `"Failed to fetch group"` type of lable.  See posthog/models/feature_flag/flag_matching.py:parse_exception_for_error_message
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
    person_id: Option<PersonId>,
    person_properties: Option<HashMap<String, Value>>,
    group_properties: HashMap<GroupTypeIndex, HashMap<String, Value>>,
}

#[derive(Clone)]
pub struct FeatureFlagMatcher {
    pub distinct_id: String,
    pub team_id: TeamId,
    pub postgres_reader: PostgresReader,
    pub postgres_writer: PostgresWriter,
    pub cohort_cache: Arc<CohortCacheManager>,
    group_type_mapping_cache: GroupTypeMappingCache,
    properties_cache: PropertiesCache,
    groups: HashMap<String, Value>,
}

const LONG_SCALE: u64 = 0xfffffffffffffff;

impl FeatureFlagMatcher {
    pub fn new(
        distinct_id: String,
        team_id: TeamId,
        postgres_reader: PostgresReader,
        postgres_writer: PostgresWriter,
        cohort_cache: Arc<CohortCacheManager>,
        group_type_mapping_cache: Option<GroupTypeMappingCache>,
        groups: Option<HashMap<String, Value>>,
    ) -> Self {
        FeatureFlagMatcher {
            distinct_id,
            team_id,
            postgres_reader: postgres_reader.clone(),
            postgres_writer: postgres_writer.clone(),
            cohort_cache,
            group_type_mapping_cache: group_type_mapping_cache
                .unwrap_or_else(|| GroupTypeMappingCache::new(team_id, postgres_reader.clone())),
            groups: groups.unwrap_or_default(),
            properties_cache: PropertiesCache::default(),
        }
    }

    /// Evaluates all feature flags for the current matcher context.
    ///
    /// ## Arguments
    ///
    /// * `feature_flags` - The list of feature flags to evaluate.
    /// * `person_property_overrides` - Any overrides for person properties.
    /// * `group_property_overrides` - Any overrides for group properties.
    /// * `hash_key_override` - Optional hash key overrides for experience continuity.
    ///
    /// ## Returns
    ///
    /// * `FlagsResponse` - The result containing flag evaluations and any errors.
    pub async fn evaluate_all_feature_flags(
        &mut self,
        feature_flags: FeatureFlagList,
        person_property_overrides: Option<HashMap<String, Value>>,
        group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
        hash_key_override: Option<String>,
    ) -> FlagsResponse {
        let flags_have_experience_continuity_enabled = feature_flags
            .flags
            .iter()
            .any(|flag| flag.ensure_experience_continuity);

        // Process any hash key overrides
        let (hash_key_overrides, initial_error) = if flags_have_experience_continuity_enabled {
            match hash_key_override {
                Some(hash_key) => {
                    let target_distinct_ids = vec![self.distinct_id.clone(), hash_key.clone()];
                    self.process_hash_key_override(hash_key, target_distinct_ids)
                        .await
                }
                // if a flag has experience continuity enabled but no hash key override is provided,
                // we don't need to write an override, we can just use the distinct_id
                None => (None, false),
            }
        } else {
            // if experience continuity is not enabled, we don't need to worry about hash key overrides
            (None, false)
        };

        // If there was an initial error in processing hash key overrides, increment the error counter
        if initial_error {
            let reason = "hash_key_override_error";
            common_metrics::inc(
                FLAG_EVALUATION_ERROR_COUNTER,
                &[("reason".to_string(), reason.to_string())],
                1,
            );
        }

        let flags_response = self
            .evaluate_flags_with_overrides(
                feature_flags,
                person_property_overrides,
                group_property_overrides,
                hash_key_overrides,
            )
            .await;

        FlagsResponse {
            error_while_computing_flags: initial_error
                || flags_response.error_while_computing_flags,
            feature_flags: flags_response.feature_flags,
        }
    }

    async fn process_hash_key_override(
        &self,
        hash_key: String,
        target_distinct_ids: Vec<String>,
    ) -> (Option<HashMap<String, String>>, bool) {
        let should_write = match should_write_hash_key_override(
            self.postgres_reader.clone(),
            self.team_id,
            self.distinct_id.clone(),
            hash_key.clone(),
        )
        .await
        {
            Ok(should_write) => should_write,
            Err(e) => {
                error!(
                    "Failed to check if hash key override should be written: {:?}",
                    e
                );
                let reason = parse_exception_for_prometheus_label(&e);
                inc(
                    FLAG_EVALUATION_ERROR_COUNTER,
                    &[("reason".to_string(), reason.to_string())],
                    1,
                );
                return (None, true);
            }
        };

        let mut writing_hash_key_override = false;

        if should_write {
            if let Err(e) = set_feature_flag_hash_key_overrides(
                // NB: this is the only method that writes to the database, so it's the only one that should use the writer
                self.postgres_writer.clone(),
                self.team_id,
                target_distinct_ids.clone(),
                hash_key.clone(),
            )
            .await
            {
                error!("Failed to set feature flag hash key overrides: {:?}", e);
                // Increment the counter for failed write
                let reason = parse_exception_for_prometheus_label(&e);
                inc(
                    FLAG_EVALUATION_ERROR_COUNTER,
                    &[("reason".to_string(), reason.to_string())],
                    1,
                );
                return (None, true);
            }
            writing_hash_key_override = true;
        }

        // TODO I'm not sure if this is the right place to increment this counter
        inc(
            FLAG_HASH_KEY_WRITES_COUNTER,
            &[
                ("team_id".to_string(), self.team_id.to_string()),
                (
                    "successful_write".to_string(),
                    writing_hash_key_override.to_string(),
                ),
            ],
            1,
        );

        match get_feature_flag_hash_key_overrides(
            self.postgres_reader.clone(),
            self.team_id,
            target_distinct_ids,
        )
        .await
        {
            Ok(overrides) => (Some(overrides), false),
            Err(e) => {
                error!("Failed to get feature flag hash key overrides: {:?}", e);
                let reason = parse_exception_for_prometheus_label(&e);
                common_metrics::inc(
                    FLAG_EVALUATION_ERROR_COUNTER,
                    &[("reason".to_string(), reason.to_string())],
                    1,
                );
                (None, true)
            }
        }
    }

    async fn evaluate_flags_with_overrides(
        &mut self,
        feature_flags: FeatureFlagList,
        person_property_overrides: Option<HashMap<String, Value>>,
        group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> FlagsResponse {
        let mut result = HashMap::new();
        let mut error_while_computing_flags = false;
        let mut flags_needing_db_properties = Vec::new();

        // Step 1: Evaluate flags with locally computable property overrides first
        for flag in &feature_flags.flags {
            if !flag.active || flag.deleted {
                continue;
            }

            match self
                .match_flag_with_property_overrides(
                    flag,
                    &person_property_overrides,
                    &group_property_overrides,
                    hash_key_overrides.clone(),
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
                Err(e) => {
                    error_while_computing_flags = true;
                    error!(
                        "Error evaluating feature flag '{}' with overrides for distinct_id '{}': {:?}",
                        flag.key, self.distinct_id, e
                    );
                    let reason = parse_exception_for_prometheus_label(&e);
                    inc(
                        FLAG_EVALUATION_ERROR_COUNTER,
                        &[("reason".to_string(), reason.to_string())],
                        1,
                    );
                }
            }
        }

        // Step 2: Fetch and cache properties for remaining flags (just one DB lookup for all of relevant properties)
        if !flags_needing_db_properties.is_empty() {
            let group_type_indexes: HashSet<GroupTypeIndex> = flags_needing_db_properties
                .iter()
                .filter_map(|flag| flag.get_group_type_index())
                .collect();

            let postgres_reader = self.postgres_reader.clone();
            let distinct_id = self.distinct_id.clone();
            let team_id = self.team_id;

            match fetch_and_locally_cache_all_properties(
                &mut self.properties_cache,
                postgres_reader,
                distinct_id,
                team_id,
                &group_type_indexes,
            )
            .await
            {
                Ok(_) => {}
                Err(e) => {
                    error_while_computing_flags = true;
                    // TODO add sentry exception tracking
                    error!("Error fetching properties: {:?}", e);
                    let reason = parse_exception_for_prometheus_label(&e);
                    inc(
                        FLAG_EVALUATION_ERROR_COUNTER,
                        &[("reason".to_string(), reason.to_string())],
                        1,
                    );
                }
            }

            // Step 3: Evaluate remaining flags with cached properties
            // At this point we've already done a round of flag evaluations with locally computable property overrides
            // This step is for flags that couldn't be evaluated locally due to missing property values,
            // so we do a single query to fetch all of the remaining properties, and then proceed with flag evaluations
            for flag in flags_needing_db_properties {
                match self
                    .get_match(&flag, None, hash_key_overrides.clone())
                    .await
                {
                    Ok(flag_match) => {
                        let flag_value = self.flag_match_to_value(&flag_match);
                        result.insert(flag.key.clone(), flag_value);
                    }
                    Err(e) => {
                        error_while_computing_flags = true;
                        // TODO add sentry exception tracking
                        error!(
                            "Error evaluating feature flag '{}' for distinct_id '{}': {:?}",
                            flag.key, self.distinct_id, e
                        );
                        let reason = parse_exception_for_prometheus_label(&e);
                        inc(
                            FLAG_EVALUATION_ERROR_COUNTER,
                            &[("reason".to_string(), reason.to_string())],
                            1,
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
    async fn match_flag_with_property_overrides(
        &mut self,
        flag: &FeatureFlag,
        person_property_overrides: &Option<HashMap<String, Value>>,
        group_property_overrides: &Option<HashMap<String, HashMap<String, Value>>>,
        hash_key_overrides: Option<HashMap<String, String>>,
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
                .get_match(flag, Some(props), hash_key_overrides)
                .await
                .map(Some),
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
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<FeatureFlagMatch, FlagError> {
        if self
            .hashed_identifier(flag, hash_key_overrides.clone())
            .await?
            .is_empty()
        {
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
                    .is_super_condition_match(
                        flag,
                        property_overrides.clone(),
                        hash_key_overrides.clone(),
                    )
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
                .is_condition_match(
                    flag,
                    condition,
                    property_overrides.clone(),
                    hash_key_overrides.clone(),
                )
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

                let variant = self
                    .get_matching_variant(flag, hash_key_overrides.clone())
                    .await?;
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
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<(bool, FeatureFlagMatchReason), FlagError> {
        let rollout_percentage = condition.rollout_percentage.unwrap_or(100.0);

        if let Some(flag_property_filters) = &condition.properties {
            if flag_property_filters.is_empty() {
                return self
                    .check_rollout(feature_flag, rollout_percentage, hash_key_overrides)
                    .await;
            }

            // Separate cohort and non-cohort filters
            let (cohort_filters, non_cohort_filters): (Vec<PropertyFilter>, Vec<PropertyFilter>) =
                flag_property_filters
                    .iter()
                    .cloned()
                    .partition(|prop| prop.is_cohort());

            // Get the properties we need to check for in this condition match from the flag + any overrides
            let person_or_group_properties = self
                .get_properties_to_check(feature_flag, property_overrides, &non_cohort_filters)
                .await?;

            // Evaluate non-cohort filters first, since they're cheaper to evaluate and we can return early if they don't match
            if !all_properties_match(&non_cohort_filters, &person_or_group_properties) {
                return Ok((false, FeatureFlagMatchReason::NoConditionMatch));
            }

            // Evaluate cohort filters, if any.
            if !cohort_filters.is_empty() {
                // Get the person ID for the current distinct ID – this value should be cached at this point, but as a fallback we fetch from the database
                let person_id = self.get_person_id().await?;
                if !self
                    .evaluate_cohort_filters(
                        &cohort_filters,
                        &person_or_group_properties,
                        person_id,
                    )
                    .await?
                {
                    return Ok((false, FeatureFlagMatchReason::NoConditionMatch));
                }
            }
        }

        self.check_rollout(feature_flag, rollout_percentage, hash_key_overrides)
            .await
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

    /// Retrieves the `PersonId` from the properties cache.
    /// If the cache does not contain a `PersonId`, it fetches it from the database
    /// and updates the cache accordingly.
    async fn get_person_id(&mut self) -> Result<PersonId, FlagError> {
        match self.properties_cache.person_id {
            Some(id) => Ok(id),
            None => {
                let id = self.get_person_id_from_db().await?;
                self.properties_cache.person_id = Some(id);
                Ok(id)
            }
        }
    }

    /// Fetches the `PersonId` from the database based on the current `distinct_id` and `team_id`.
    /// This method is called when the `PersonId` is not present in the properties cache.
    async fn get_person_id_from_db(&mut self) -> Result<PersonId, FlagError> {
        let postgres_reader = self.postgres_reader.clone();
        let distinct_id = self.distinct_id.clone();
        let team_id = self.team_id;
        fetch_person_properties_from_db(postgres_reader, distinct_id, team_id)
            .await
            .map(|(_, person_id)| person_id)
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

    /// Evaluates dynamic cohort property filters
    ///
    /// NB: This method first caches all of the cohorts associated with the team, which allows us to avoid
    /// hitting the database for each cohort filter.
    pub async fn evaluate_cohort_filters(
        &self,
        cohort_property_filters: &[PropertyFilter],
        target_properties: &HashMap<String, Value>,
        person_id: PersonId,
    ) -> Result<bool, FlagError> {
        // At the start of the request, fetch all of the cohorts for the team from the cache
        // This method also caches any cohorts for a given team in memory for the duration of the application, so we don't need to fetch from
        // the database again until we restart the application.  See the CohortCacheManager for more details.
        let cohorts = self.cohort_cache.get_cohorts_for_team(self.team_id).await?;

        // Split the cohorts into static and dynamic, since the dynamic ones have property filters
        // and we need to evaluate them based on the target properties, whereas the static ones are
        // purely based on person properties and are membership-based.
        let (static_cohorts, dynamic_cohorts): (Vec<_>, Vec<_>) =
            cohorts.iter().partition(|c| c.is_static);

        // Store all cohort match results in a HashMap to avoid re-evaluating the same cohort multiple times,
        // since the same cohort could appear in multiple property filters.
        let mut cohort_matches = HashMap::new();

        if !static_cohorts.is_empty() {
            let results = evaluate_static_cohorts(
                self.postgres_reader.clone(),
                person_id,
                static_cohorts.iter().map(|c| c.id).collect(),
            )
            .await?;
            cohort_matches.extend(results);
        }

        if !dynamic_cohorts.is_empty() {
            for filter in cohort_property_filters {
                let cohort_id = filter
                    .get_cohort_id()
                    .ok_or(FlagError::CohortFiltersParsingError)?;
                let match_result =
                    evaluate_dynamic_cohorts(cohort_id, target_properties, cohorts.clone())?;
                cohort_matches.insert(cohort_id, match_result);
            }
        }

        // Apply cohort membership logic (IN|NOT_IN) to the cohort match results
        apply_cohort_membership_logic(cohort_property_filters, &cohort_matches)
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
        hash_key_overrides: Option<HashMap<String, String>>,
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
                .is_condition_match(
                    feature_flag,
                    first_condition,
                    Some(person_properties),
                    hash_key_overrides,
                )
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

        let postgres_reader = self.postgres_reader.clone();
        let team_id = self.team_id;
        let db_properties =
            fetch_group_properties_from_db(postgres_reader, team_id, group_type_index).await?;

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

        let postgres_reader = self.postgres_reader.clone();
        let distinct_id = self.distinct_id.clone();
        let team_id = self.team_id;
        let (db_properties, person_id) =
            fetch_person_properties_from_db(postgres_reader, distinct_id, team_id).await?;

        // once the properties and person ID are fetched, cache them so we don't need to fetch again in a given request
        self.properties_cache.person_properties = Some(db_properties.clone());
        self.properties_cache.person_id = Some(person_id);

        Ok(db_properties)
    }

    /// Get hashed identifier for a feature flag.
    ///
    /// This function generates a hashed identifier for a feature flag based on the feature flag's group type index.
    /// If the feature flag is group-based, it fetches the group key; otherwise, it uses the distinct ID.
    async fn hashed_identifier(
        &mut self,
        feature_flag: &FeatureFlag,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<String, FlagError> {
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
            // Use hash key overrides for experience continuity
            if let Some(hash_key_override) = hash_key_overrides
                .as_ref()
                .and_then(|h| h.get(&feature_flag.key))
            {
                Ok(hash_key_override.clone())
            } else {
                Ok(self.distinct_id.clone())
            }
        }
    }

    /// This function takes a identifier and a feature flag key and returns a float between 0 and 1.
    /// Given the same identifier and key, it'll always return the same float. These floats are
    /// uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    /// we can do _hash(key, identifier) < 0.2
    async fn get_hash(
        &mut self,
        feature_flag: &FeatureFlag,
        salt: &str,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<f64, FlagError> {
        let hashed_identifier = self
            .hashed_identifier(feature_flag, hash_key_overrides)
            .await?;
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
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<(bool, FeatureFlagMatchReason), FlagError> {
        let hash = self.get_hash(feature_flag, "", hash_key_overrides).await?;
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
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<Option<String>, FlagError> {
        let hash = self
            .get_hash(feature_flag, "variant", hash_key_overrides)
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

/// Evaluate static cohort filters by checking if the person is in each cohort.
async fn evaluate_static_cohorts(
    postgres_reader: PostgresReader,
    person_id: i32, // Change this parameter from distinct_id to person_id
    cohort_ids: Vec<CohortId>,
) -> Result<Vec<(CohortId, bool)>, FlagError> {
    let mut conn = postgres_reader.get_connection().await?;

    let query = r#"
           WITH cohort_membership AS (
               SELECT c.cohort_id, 
                      CASE WHEN pc.cohort_id IS NOT NULL THEN true ELSE false END AS is_member
               FROM unnest($1::integer[]) AS c(cohort_id)
               LEFT JOIN posthog_cohortpeople AS pc
                 ON pc.person_id = $2
                 AND pc.cohort_id = c.cohort_id
           )
           SELECT cohort_id, is_member
           FROM cohort_membership
       "#;

    let rows = sqlx::query(query)
        .bind(&cohort_ids)
        .bind(person_id) // Bind person_id directly
        .fetch_all(&mut *conn)
        .await?;

    let result = rows
        .into_iter()
        .map(|row| {
            let cohort_id: CohortId = row.get("cohort_id");
            let is_member: bool = row.get("is_member");
            (cohort_id, is_member)
        })
        .collect();

    Ok(result)
}

/// Evaluates a dynamic cohort and its dependencies.
/// This uses a topological sort to evaluate dependencies first, which is necessary
/// because a cohort can depend on another cohort, and we need to respect the dependency order.
fn evaluate_dynamic_cohorts(
    initial_cohort_id: CohortId,
    target_properties: &HashMap<String, Value>,
    cohorts: Vec<Cohort>,
) -> Result<bool, FlagError> {
    let cohort_dependency_graph =
        build_cohort_dependency_graph(initial_cohort_id, cohorts.clone())?;

    // We need to sort cohorts topologically to ensure we evaluate dependencies before the cohorts that depend on them.
    // For example, if cohort A depends on cohort B, we need to evaluate B first to know if A matches.
    // This also helps detect cycles - if cohort A depends on B which depends on A, toposort will fail.
    let sorted_cohort_ids_as_graph_nodes =
        toposort(&cohort_dependency_graph, None).map_err(|e| {
            FlagError::CohortDependencyCycle(format!("Cyclic dependency detected: {:?}", e))
        })?;

    // Store evaluation results for each cohort in a map, so we can look up whether a cohort matched
    // when evaluating cohorts that depend on it, and also return the final result for the initial cohort
    let mut evaluation_results = HashMap::new();

    // Iterate through the sorted nodes in reverse order (so that we can evaluate dependencies first)
    for node in sorted_cohort_ids_as_graph_nodes.into_iter().rev() {
        let cohort_id = cohort_dependency_graph[node];
        let cohort = cohorts
            .iter()
            .find(|c| c.id == cohort_id)
            .ok_or(FlagError::CohortNotFound(cohort_id.to_string()))?;
        let property_filters = cohort.parse_filters()?;
        let dependencies = cohort.extract_dependencies()?;

        // Check if all dependencies have been met (i.e., previous cohorts matched)
        let dependencies_met = dependencies
            .iter()
            .all(|dep_id| evaluation_results.get(dep_id).copied().unwrap_or(false));

        // If dependencies are not met, mark the current cohort as not matched and continue
        // NB: We don't want to _exit_ here, since the non-matching cohort could be wrapped in a `not_in` operator
        // and we want to evaluate all cohorts to determine if the initial cohort matches.
        if !dependencies_met {
            evaluation_results.insert(cohort_id, false);
            continue;
        }

        // Evaluate all property filters for the current cohort
        let all_filters_match = property_filters
            .iter()
            .all(|filter| match_property(filter, target_properties, false).unwrap_or(false));

        // Store the evaluation result for the current cohort
        evaluation_results.insert(cohort_id, all_filters_match);
    }

    // Retrieve and return the evaluation result for the initial cohort
    evaluation_results
        .get(&initial_cohort_id)
        .copied()
        .ok_or_else(|| FlagError::CohortNotFound(initial_cohort_id.to_string()))
}

/// Apply cohort membership logic (i.e., IN|NOT_IN)
fn apply_cohort_membership_logic(
    cohort_filters: &[PropertyFilter],
    cohort_matches: &HashMap<CohortId, bool>,
) -> Result<bool, FlagError> {
    for filter in cohort_filters {
        let cohort_id = filter
            .get_cohort_id()
            .ok_or(FlagError::CohortFiltersParsingError)?;
        let matches = cohort_matches.get(&cohort_id).copied().unwrap_or(false);
        let operator = filter.operator.unwrap_or(OperatorType::In);

        // Combine the operator logic directly within this method
        let membership_match = match operator {
            OperatorType::In => matches,
            OperatorType::NotIn => !matches,
            // Currently supported operators are IN and NOT IN
            // Any other operator defaults to false
            _ => false,
        };

        // If any filter does not match, return false early
        if !membership_match {
            return Ok(false);
        }
    }
    // All filters matched
    Ok(true)
}

/// Constructs a dependency graph for cohorts.
///
/// Example dependency graph:
/// ```text
///   A    B
///   |   /|
///   |  / |
///   | /  |
///   C    D
///   \   /
///    \ /
///     E
/// ```
/// In this example:
/// - Cohorts A and B are root nodes (no dependencies)
/// - C depends on A and B
/// - D depends on B
/// - E depends on C and D
///
/// The graph is acyclic, which is required for valid cohort dependencies.
fn build_cohort_dependency_graph(
    initial_cohort_id: CohortId,
    cohorts: Vec<Cohort>,
) -> Result<DiGraph<CohortId, ()>, FlagError> {
    let mut graph = DiGraph::new();
    let mut node_map = HashMap::new();
    let mut queue = VecDeque::new();

    let initial_cohort = cohorts
        .iter()
        .find(|c| c.id == initial_cohort_id)
        .ok_or(FlagError::CohortNotFound(initial_cohort_id.to_string()))?;

    if initial_cohort.is_static {
        return Ok(graph);
    }

    // This implements a breadth-first search (BFS) traversal to build a directed graph of cohort dependencies.
    // Starting from the initial cohort, we:
    // 1. Add each cohort as a node in the graph
    // 2. Track visited nodes in a map to avoid duplicates
    // 3. For each cohort, get its dependencies and add directed edges from the cohort to its dependencies
    // 4. Queue up any unvisited dependencies to process their dependencies later
    // This builds up the full dependency graph level by level, which we can later check for cycles
    queue.push_back(initial_cohort_id);
    node_map.insert(initial_cohort_id, graph.add_node(initial_cohort_id));

    while let Some(cohort_id) = queue.pop_front() {
        let cohort = cohorts
            .iter()
            .find(|c| c.id == cohort_id)
            .ok_or(FlagError::CohortNotFound(cohort_id.to_string()))?;
        let dependencies = cohort.extract_dependencies()?;
        for dep_id in dependencies {
            // Retrieve the current node **before** mutable borrowing
            // This is safe because we're not mutating the node map,
            // and it keeps the borrow checker happy
            let current_node = node_map[&cohort_id];
            // Add dependency node if we haven't seen this cohort ID before in our traversal.
            // This happens when we discover a new dependency that wasn't previously
            // encountered while processing other cohorts in the graph.
            let dep_node = node_map
                .entry(dep_id)
                .or_insert_with(|| graph.add_node(dep_id));

            graph.add_edge(current_node, *dep_node, ());

            if !node_map.contains_key(&dep_id) {
                queue.push_back(dep_id);
            }
        }
    }

    // Check for cycles, this is an directed acyclic graph so we use is_cyclic_directed
    if is_cyclic_directed(&graph) {
        return Err(FlagError::CohortDependencyCycle(format!(
            "Cyclic dependency detected starting at cohort {}",
            initial_cohort_id
        )));
    }

    Ok(graph)
}

/// Fetch and locally cache all properties for a given distinct ID and team ID.
///
/// This function fetches both person and group properties for a specified distinct ID and team ID.
/// It updates the properties cache with the fetched properties and returns the result.
async fn fetch_and_locally_cache_all_properties(
    properties_cache: &mut PropertiesCache,
    postgres_reader: PostgresReader,
    distinct_id: String,
    team_id: TeamId,
    group_type_indexes: &HashSet<GroupTypeIndex>,
) -> Result<(), FlagError> {
    let mut conn = postgres_reader.as_ref().get_connection().await?;

    let query = r#"
        SELECT 
            person.person_id,
            person.person_properties,
            group_properties.group_properties
        FROM (
            SELECT 
                "posthog_person"."id" AS person_id,
                "posthog_person"."properties" AS person_properties
            FROM "posthog_person"
            INNER JOIN "posthog_persondistinctid" 
                ON "posthog_person"."id" = "posthog_persondistinctid"."person_id"
            WHERE 
                "posthog_persondistinctid"."distinct_id" = $1
                AND "posthog_persondistinctid"."team_id" = $2
                AND "posthog_person"."team_id" = $2
            LIMIT 1
        ) AS person,
        (
            SELECT 
                json_object_agg(
                    "posthog_group"."group_type_index", 
                    "posthog_group"."group_properties"
                ) AS group_properties
            FROM "posthog_group"
            WHERE 
                "posthog_group"."team_id" = $2
                AND "posthog_group"."group_type_index" = ANY($3)
        ) AS group_properties
    "#;

    let group_type_indexes_vec: Vec<GroupTypeIndex> = group_type_indexes.iter().cloned().collect();

    let row: (Option<i32>, Option<Value>, Option<Value>) = sqlx::query_as(query)
        .bind(&distinct_id)
        .bind(team_id)
        .bind(&group_type_indexes_vec)
        .fetch_optional(&mut *conn)
        .await?
        .unwrap_or((None, None, None));

    let (person_id, person_props, group_props) = row;

    if let Some(person_id) = person_id {
        properties_cache.person_id = Some(person_id);
    }

    if let Some(person_props) = person_props {
        properties_cache.person_properties = Some(
            person_props
                .as_object()
                .unwrap_or(&serde_json::Map::new())
                .iter()
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
        );
    }

    if let Some(group_props) = group_props {
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

/// Fetch person properties and person ID from the database for a given distinct ID and team ID.
///
/// This function constructs and executes a SQL query to fetch the person properties for a specified distinct ID and team ID.
/// It returns the fetched properties as a HashMap.
async fn fetch_person_properties_from_db(
    postgres_reader: PostgresReader,
    distinct_id: String,
    team_id: TeamId,
) -> Result<(HashMap<String, Value>, i32), FlagError> {
    let mut conn = postgres_reader.as_ref().get_connection().await?;

    let query = r#"
           SELECT "posthog_person"."id" as person_id, "posthog_person"."properties" as person_properties
           FROM "posthog_person"
           INNER JOIN "posthog_persondistinctid" ON ("posthog_person"."id" = "posthog_persondistinctid"."person_id")
           WHERE ("posthog_persondistinctid"."distinct_id" = $1
                   AND "posthog_persondistinctid"."team_id" = $2
                   AND "posthog_person"."team_id" = $2)
           LIMIT 1
       "#;

    let row: Option<(i32, Value)> = sqlx::query_as(query)
        .bind(&distinct_id)
        .bind(team_id)
        .fetch_optional(&mut *conn)
        .await?;

    match row {
        Some((person_id, person_props)) => {
            let properties_map = person_props
                .as_object()
                .unwrap_or(&serde_json::Map::new())
                .iter()
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect();
            Ok((properties_map, person_id))
        }
        None => Err(FlagError::PersonNotFound),
    }
}

/// Fetch group properties from the database for a given team ID and group type index.
///
/// This function constructs and executes a SQL query to fetch the group properties for a specified team ID and group type index.
/// It returns the fetched properties as a HashMap.
async fn fetch_group_properties_from_db(
    postgres_reader: PostgresReader,
    team_id: TeamId,
    group_type_index: GroupTypeIndex,
) -> Result<HashMap<String, Value>, FlagError> {
    let mut conn = postgres_reader.as_ref().get_connection().await?;

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
    matching_property_values: &HashMap<String, Value>,
) -> bool {
    flag_condition_properties
        .iter()
        .all(|property| match_property(property, matching_property_values, false).unwrap_or(false))
}

async fn get_feature_flag_hash_key_overrides(
    postgres_reader: PostgresReader,
    team_id: TeamId,
    distinct_id_and_hash_key_override: Vec<String>,
) -> Result<HashMap<String, String>, FlagError> {
    let mut feature_flag_hash_key_overrides = HashMap::new();
    let mut conn = postgres_reader.as_ref().get_connection().await?;

    let person_and_distinct_id_query = r#"
            SELECT person_id, distinct_id 
            FROM posthog_persondistinctid 
            WHERE team_id = $1 AND distinct_id = ANY($2)
        "#;

    let person_and_distinct_ids: Vec<(i32, String)> = sqlx::query_as(person_and_distinct_id_query)
        .bind(team_id)
        .bind(&distinct_id_and_hash_key_override)
        .fetch_all(&mut *conn)
        .await?;

    let person_id_to_distinct_id: HashMap<i32, String> =
        person_and_distinct_ids.into_iter().collect();
    let person_ids: Vec<i32> = person_id_to_distinct_id.keys().cloned().collect();

    // Get hash key overrides
    let hash_key_override_query = r#"
            SELECT feature_flag_key, hash_key, person_id 
            FROM posthog_featureflaghashkeyoverride 
            WHERE team_id = $1 AND person_id = ANY($2)
        "#;

    let overrides: Vec<(String, String, i32)> = sqlx::query_as(hash_key_override_query)
        .bind(team_id)
        .bind(&person_ids)
        .fetch_all(&mut *conn)
        .await?;

    // Sort and process overrides, with the distinct_id at the start of the array having priority
    // We want the highest priority to go last in sort order, so it's the latest update in the hashmap
    let mut sorted_overrides = overrides;
    sorted_overrides.sort_by_key(|(_, _, person_id)| {
        if person_id_to_distinct_id.get(person_id) == Some(&distinct_id_and_hash_key_override[0]) {
            std::cmp::Ordering::Greater
        } else {
            std::cmp::Ordering::Less
        }
    });

    for (feature_flag_key, hash_key, _) in sorted_overrides {
        feature_flag_hash_key_overrides.insert(feature_flag_key, hash_key);
    }

    Ok(feature_flag_hash_key_overrides)
}

async fn set_feature_flag_hash_key_overrides(
    postgres_writer: PostgresWriter,
    team_id: TeamId,
    distinct_ids: Vec<String>,
    hash_key_override: String,
) -> Result<bool, FlagError> {
    const MAX_RETRIES: u32 = 2;
    const RETRY_DELAY: Duration = Duration::from_millis(100);

    for retry in 0..MAX_RETRIES {
        let mut conn = postgres_writer.get_connection().await?;
        let mut transaction = conn.begin().await?;

        let query = r#"
            WITH target_person_ids AS (
                SELECT team_id, person_id FROM posthog_persondistinctid WHERE team_id = $1 AND
                distinct_id = ANY($2)
            ),
            existing_overrides AS (
                SELECT team_id, person_id, feature_flag_key, hash_key FROM posthog_featureflaghashkeyoverride
                WHERE team_id = $1 AND person_id IN (SELECT person_id FROM target_person_ids)
            ),
            flags_to_override AS (
                SELECT key FROM posthog_featureflag WHERE team_id = $1 AND ensure_experience_continuity = TRUE AND active = TRUE AND deleted = FALSE
                AND key NOT IN (SELECT feature_flag_key FROM existing_overrides)
            )
            INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
                SELECT team_id, person_id, key, $3
                FROM flags_to_override, target_person_ids
                WHERE EXISTS (SELECT 1 FROM posthog_person WHERE id = person_id AND team_id = $1)
            ON CONFLICT DO NOTHING
        "#;

        let result: Result<PgQueryResult, sqlx::Error> = sqlx::query(query)
            .bind(team_id)
            .bind(&distinct_ids)
            .bind(&hash_key_override)
            .execute(&mut *transaction)
            .await;

        match result {
            Ok(query_result) => {
                // Commit the transaction if successful
                transaction
                    .commit()
                    .await
                    .map_err(|e| FlagError::DatabaseError(e.to_string()))?;
                return Ok(query_result.rows_affected() > 0);
            }
            Err(e) => {
                // Rollback the transaction on error
                transaction
                    .rollback()
                    .await
                    .map_err(|e| FlagError::DatabaseError(e.to_string()))?;

                if e.to_string().contains("violates foreign key constraint")
                    && retry < MAX_RETRIES - 1
                {
                    // Retry logic for specific error
                    tracing::info!(
                        "Retrying set_feature_flag_hash_key_overrides due to person deletion: {:?}",
                        e
                    );
                    sleep(RETRY_DELAY).await;
                } else {
                    return Err(FlagError::DatabaseError(e.to_string()));
                }
            }
        }
    }

    // If we get here, something went wrong
    Ok(false)
}

async fn should_write_hash_key_override(
    postgres_reader: PostgresReader,
    team_id: TeamId,
    distinct_id: String,
    hash_key_override: String,
) -> Result<bool, FlagError> {
    const QUERY_TIMEOUT: Duration = Duration::from_millis(1000);
    const MAX_RETRIES: u32 = 2;
    const RETRY_DELAY: Duration = Duration::from_millis(100);

    let distinct_ids = vec![distinct_id, hash_key_override.clone()];

    let query = r#"
        WITH target_person_ids AS (
            SELECT team_id, person_id 
            FROM posthog_persondistinctid 
            WHERE team_id = $1 AND distinct_id = ANY($2)
        ),
        existing_overrides AS (
            SELECT team_id, person_id, feature_flag_key, hash_key 
            FROM posthog_featureflaghashkeyoverride
            WHERE team_id = $1 AND person_id IN (SELECT person_id FROM target_person_ids)
        )
        SELECT key 
        FROM posthog_featureflag 
        WHERE team_id = $1 
            AND ensure_experience_continuity = TRUE 
            AND active = TRUE 
            AND deleted = FALSE
            AND key NOT IN (SELECT feature_flag_key FROM existing_overrides)
    "#;

    for retry in 0..MAX_RETRIES {
        let result = timeout(QUERY_TIMEOUT, async {
            let mut conn = postgres_reader.get_connection().await.map_err(|e| {
                FlagError::DatabaseError(format!("Failed to acquire connection: {}", e))
            })?;

            let rows = sqlx::query(query)
                .bind(team_id)
                .bind(&distinct_ids)
                .fetch_all(&mut *conn)
                .await
                .map_err(|e| FlagError::DatabaseError(format!("Query execution failed: {}", e)))?;

            Ok::<bool, FlagError>(!rows.is_empty())
        })
        .await;

        match result {
            Ok(Ok(flags_present)) => return Ok(flags_present),
            Ok(Err(e)) => {
                if e.to_string().contains("violates foreign key constraint")
                    && retry < MAX_RETRIES - 1
                {
                    info!(
                        "Retrying set_feature_flag_hash_key_overrides due to person deletion: {:?}",
                        e
                    );
                    tokio::time::sleep(RETRY_DELAY).await;
                    continue;
                } else {
                    // For other errors or if max retries exceeded, return the error
                    return Err(e);
                }
            }
            Err(_) => {
                // Handle timeout
                return Err(FlagError::TimeoutError);
            }
        }
    }

    // If all retries failed without returning, return false
    Ok(false)
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use std::collections::HashMap;

    use super::*;
    use crate::{
        flag_definitions::{
            FeatureFlagRow, FlagFilters, MultivariateFlagOptions, MultivariateFlagVariant,
            OperatorType,
        },
        test_utils::{
            add_person_to_cohort, get_person_id_by_distinct_id, insert_cohort_for_team_in_pg,
            insert_flag_for_team_in_pg, insert_new_team_in_pg, insert_person_for_team_in_pg,
            setup_pg_reader_client, setup_pg_writer_client,
        },
    };

    #[allow(clippy::too_many_arguments)]
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
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));

        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .expect("Failed to insert team in pg");

        let distinct_id = "user_distinct_id".to_string();
        insert_person_for_team_in_pg(postgres_reader.clone(), team.id, distinct_id.clone(), None)
            .await
            .expect("Failed to insert person");

        let not_matching_distinct_id = "not_matching_distinct_id".to_string();
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
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

        // Matcher for a matching distinct_id
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );
        let match_result = matcher.get_match(&flag, None, None).await.unwrap();
        assert!(match_result.matches);
        assert_eq!(match_result.variant, None);

        // Matcher for a non-matching distinct_id
        let mut matcher = FeatureFlagMatcher::new(
            not_matching_distinct_id.clone(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );
        let match_result = matcher.get_match(&flag, None, None).await.unwrap();
        assert!(!match_result.matches);
        assert_eq!(match_result.variant, None);

        // Matcher for a distinct_id that does not exist
        let mut matcher = FeatureFlagMatcher::new(
            "other_distinct_id".to_string(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );
        let match_result = matcher.get_match(&flag, None, None).await;

        // Expecting an error for non-existent distinct_id
        assert!(match_result.is_err());
    }

    #[tokio::test]
    async fn test_person_property_overrides() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
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
                        negation: None,
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
            postgres_reader,
            postgres_writer,
            cohort_cache,
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };
        let result = matcher
            .evaluate_all_feature_flags(flags, Some(overrides), None, None)
            .await;
        assert!(!result.error_while_computing_flags);
        assert_eq!(
            result.feature_flags.get("test_flag"),
            Some(&FlagValue::Boolean(true))
        );
    }

    #[tokio::test]
    async fn test_group_property_overrides() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
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
                        key: "industry".to_string(),
                        value: json!("tech"),
                        operator: None,
                        prop_type: "group".to_string(),
                        group_type_index: Some(1),
                        negation: None,
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

        let mut group_type_mapping_cache =
            GroupTypeMappingCache::new(team.id, postgres_reader.clone());
        let group_types_to_indexes = [("organization".to_string(), 1)].into_iter().collect();
        group_type_mapping_cache.group_types_to_indexes = group_types_to_indexes;
        group_type_mapping_cache.group_indexes_to_types =
            [(1, "organization".to_string())].into_iter().collect();

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
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            Some(groups),
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };
        let result = matcher
            .evaluate_all_feature_flags(flags, None, Some(group_overrides), None)
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
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let mut group_type_mapping_cache = GroupTypeMappingCache::new(1, postgres_reader.clone());

        let group_types_to_indexes = [("group_type_1".to_string(), 1)].into_iter().collect();
        let group_type_index_to_name = [(1, "group_type_1".to_string())].into_iter().collect();

        group_type_mapping_cache.group_types_to_indexes = group_types_to_indexes;
        group_type_mapping_cache.group_indexes_to_types = group_type_index_to_name;

        let groups = HashMap::from([("group_type_1".to_string(), json!("group_key_1"))]);

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            Some(groups),
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
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        let flag = create_test_flag_with_variants(team.id);

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let variant = matcher.get_matching_variant(&flag, None).await.unwrap();
        assert!(variant.is_some());
        assert!(["control", "test", "test2"].contains(&variant.unwrap().as_str()));
    }

    #[tokio::test]
    async fn test_is_condition_match_empty_properties() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
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
            postgres_reader,
            postgres_writer,
            cohort_cache,
            None,
            None,
        );
        let (is_match, reason) = matcher
            .is_condition_match(&flag, &condition, None, None)
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
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
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
                        operator: Some(OperatorType::Exact),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
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
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher
            .evaluate_all_feature_flags(
                FeatureFlagList {
                    flags: vec![flag.clone()],
                },
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

        let cache = &matcher.properties_cache;
        assert!(cache.person_properties.is_none());
    }

    #[tokio::test]
    async fn test_fallback_to_db_when_overrides_insufficient() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

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
                            negation: None,
                        },
                        PropertyFilter {
                            key: "age".to_string(),
                            value: json!(25),
                            operator: Some(OperatorType::Gte),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
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
            postgres_reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "test@example.com", "age": 30})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher
            .get_match(&flag, person_property_overrides.clone(), None)
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
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        let distinct_id = "test_user".to_string();
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "test@example.com", "age": 30})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id,
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

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
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        let distinct_id = "test_user".to_string();
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "test@example.com", "age": 30})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
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
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
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
                negation: None,
            },
            PropertyFilter {
                key: "age".to_string(),
                value: json!(25),
                operator: Some(OperatorType::Gte),
                prop_type: "person".to_string(),
                group_type_index: None,
                negation: None,
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
                negation: None,
            },
            PropertyFilter {
                key: "cohort".to_string(),
                value: json!(1),
                operator: None,
                prop_type: "cohort".to_string(),
                group_type_index: None,
                negation: None,
            },
        ];

        let result =
            locally_computable_property_overrides(&overrides, &property_filters_with_cohort);
        assert!(result.is_none());
    }

    #[tokio::test]
    async fn test_concurrent_flag_evaluation() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();
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
            let postgres_reader_clone = postgres_reader.clone();
            let postgres_writer_clone = postgres_writer.clone();
            let cohort_cache_clone = cohort_cache.clone();
            handles.push(tokio::spawn(async move {
                let mut matcher = FeatureFlagMatcher::new(
                    format!("test_user_{}", i),
                    team.id,
                    postgres_reader_clone,
                    postgres_writer_clone,
                    cohort_cache_clone,
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

    #[tokio::test]
    async fn test_property_operators() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

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
                            negation: None,
                        },
                        PropertyFilter {
                            key: "email".to_string(),
                            value: json!("example@domain.com"),
                            operator: Some(OperatorType::Icontains),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
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
            postgres_reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "user@example@domain.com", "age": 30})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_empty_hashed_identifier() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
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

        let mut matcher = FeatureFlagMatcher::new(
            "".to_string(),
            1,
            postgres_reader,
            postgres_writer,
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_rollout_percentage() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
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

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            postgres_reader,
            postgres_writer,
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(!result.matches);

        // Now set the rollout percentage to 100%
        flag.filters.groups[0].rollout_percentage = Some(100.0);

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_uneven_variant_distribution() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
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

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            postgres_reader,
            postgres_writer,
            cohort_cache,
            None,
            None,
        );

        let mut control_count = 0;
        let mut test_count = 0;
        let mut test2_count = 0;

        // Run the test multiple times to simulate distribution
        for i in 0..1000 {
            matcher.distinct_id = format!("user_{}", i);
            let variant = matcher.get_matching_variant(&flag, None).await.unwrap();
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
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        // Insert a person without properties
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            "test_user".to_string(),
            None,
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
                        key: "email".to_string(),
                        value: json!("test@example.com"),
                        operator: None,
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
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
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_malformed_property_data() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        // Insert a person with malformed properties
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
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
                        negation: None,
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
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        // The match should fail due to invalid data type
        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_get_match_with_insufficient_overrides() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

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
                            negation: None,
                        },
                        PropertyFilter {
                            key: "age".to_string(),
                            value: json!(25),
                            operator: Some(OperatorType::Gte),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
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
            postgres_reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "test@example.com", "age": 30})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher
            .get_match(&flag, person_overrides, None)
            .await
            .unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_evaluation_reasons() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
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

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache,
            None,
            None,
        );

        let (is_match, reason) = matcher
            .is_condition_match(&flag, &flag.filters.groups[0], None, None)
            .await
            .unwrap();

        assert!(is_match);
        assert_eq!(reason, FeatureFlagMatchReason::ConditionMatch);
    }

    #[tokio::test]
    async fn test_complex_conditions() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

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
                            negation: None,
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
                            negation: None,
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
            postgres_reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "user2@example.com", "age": 35})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_super_condition_matches_boolean() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
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
                            negation: None,
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
                            negation: None,
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
                        negation: None,
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
            postgres_reader.clone(),
            team.id,
            "test_id".to_string(),
            Some(json!({"email": "test@posthog.com", "is_enabled": true})),
        )
        .await
        .unwrap();

        insert_person_for_team_in_pg(postgres_reader.clone(), team.id, "lil_id".to_string(), None)
            .await
            .unwrap();

        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            "another_id".to_string(),
            None,
        )
        .await
        .unwrap();

        let mut matcher_test_id = FeatureFlagMatcher::new(
            "test_id".to_string(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_example_id = FeatureFlagMatcher::new(
            "lil_id".to_string(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_another_id = FeatureFlagMatcher::new(
            "another_id".to_string(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result_test_id = matcher_test_id.get_match(&flag, None, None).await.unwrap();
        let result_example_id = matcher_example_id
            .get_match(&flag, None, None)
            .await
            .unwrap();
        let result_another_id = matcher_another_id
            .get_match(&flag, None, None)
            .await
            .unwrap();

        assert!(result_test_id.matches);
        assert!(result_test_id.reason == FeatureFlagMatchReason::SuperConditionValue);
        assert!(result_example_id.matches);
        assert!(result_example_id.reason == FeatureFlagMatchReason::ConditionMatch);
        assert!(!result_another_id.matches);
        assert!(result_another_id.reason == FeatureFlagMatchReason::OutOfRolloutBound);
    }

    #[tokio::test]
    async fn test_super_condition_matches_string() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        insert_person_for_team_in_pg(
            postgres_reader.clone(),
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
                            negation: None,
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
                            negation: None,
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
                        negation: None,
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
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(result.matches);
        assert_eq!(result.reason, FeatureFlagMatchReason::SuperConditionValue);
        assert_eq!(result.condition_index, Some(0));
    }

    #[tokio::test]
    async fn test_super_condition_matches_and_false() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            "test_id".to_string(),
            Some(json!({"email": "test@posthog.com", "is_enabled": true})),
        )
        .await
        .unwrap();

        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            "another_id".to_string(),
            None,
        )
        .await
        .unwrap();

        insert_person_for_team_in_pg(postgres_reader.clone(), team.id, "lil_id".to_string(), None)
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
                            negation: None,
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
                            negation: None,
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
                        negation: None,
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
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_example_id = FeatureFlagMatcher::new(
            "lil_id".to_string(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_another_id = FeatureFlagMatcher::new(
            "another_id".to_string(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result_test_id = matcher_test_id.get_match(&flag, None, None).await.unwrap();
        let result_example_id = matcher_example_id
            .get_match(&flag, None, None)
            .await
            .unwrap();
        let result_another_id = matcher_another_id
            .get_match(&flag, None, None)
            .await
            .unwrap();

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

    #[tokio::test]
    async fn test_basic_cohort_matching() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        // Insert a cohort with the condition that matches the test user's properties
        let cohort_row = insert_cohort_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            None,
            json!({
                "properties": {
                    "type": "OR",
                    "values": [{
                        "type": "OR",
                        "values": [{
                            "key": "$browser_version",
                            "type": "person",
                            "value": "125",
                            "negation": false,
                            "operator": "gt"
                        }]
                    }]
                }
            }),
            false,
        )
        .await
        .unwrap();

        // Insert a person with properties that match the cohort condition
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"$browser_version": 126})),
        )
        .await
        .unwrap();

        // Define a flag with a cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: json!(cohort_row.id),
                        operator: Some(OperatorType::In),
                        prop_type: "cohort".to_string(),
                        group_type_index: None,
                        negation: Some(false),
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
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_not_in_cohort_matching() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        // Insert a cohort with a condition that does not match the test user's properties
        let cohort_row = insert_cohort_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            None,
            json!({
                "properties": {
                    "type": "OR",
                    "values": [{
                        "type": "OR",
                        "values": [{
                            "key": "$browser_version",
                            "type": "person",
                            "value": "130",
                            "negation": false,
                            "operator": "gt"
                        }]
                    }]
                }
            }),
            false,
        )
        .await
        .unwrap();

        // Insert a person with properties that do not match the cohort condition
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"$browser_version": 126})),
        )
        .await
        .unwrap();

        // Define a flag with a NotIn cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: json!(cohort_row.id),
                        operator: Some(OperatorType::NotIn),
                        prop_type: "cohort".to_string(),
                        group_type_index: None,
                        negation: Some(false),
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
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_not_in_cohort_matching_user_in_cohort() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        // Insert a cohort with a condition that matches the test user's properties
        let cohort_row = insert_cohort_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            None,
            json!({
                "properties": {
                    "type": "OR",
                    "values": [{
                        "type": "OR",
                        "values": [{
                            "key": "$browser_version",
                            "type": "person",
                            "value": "125",
                            "negation": false,
                            "operator": "gt"
                        }]
                    }]
                }
            }),
            false,
        )
        .await
        .unwrap();

        // Insert a person with properties that match the cohort condition
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"$browser_version": 126})),
        )
        .await
        .unwrap();

        // Define a flag with a NotIn cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: json!(cohort_row.id),
                        operator: Some(OperatorType::NotIn),
                        prop_type: "cohort".to_string(),
                        group_type_index: None,
                        negation: Some(false),
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
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        // The user matches the cohort, but the flag is set to NotIn, so it should evaluate to false
        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_cohort_dependent_on_another_cohort() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        // Insert a base cohort
        let base_cohort_row = insert_cohort_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            None,
            json!({
                "properties": {
                    "type": "OR",
                    "values": [{
                        "type": "OR",
                        "values": [{
                            "key": "$browser_version",
                            "type": "person",
                            "value": "125",
                            "negation": false,
                            "operator": "gt"
                        }]
                    }]
                }
            }),
            false,
        )
        .await
        .unwrap();

        // Insert a dependent cohort that includes the base cohort
        let dependent_cohort_row = insert_cohort_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            None,
            json!({
                "properties": {
                    "type": "OR",
                    "values": [{
                        "type": "OR",
                        "values": [{
                            "key": "id",
                            "type": "cohort",
                            "value": base_cohort_row.id,
                            "negation": false,
                            "operator": "in"
                        }]
                    }]
                }
            }),
            false,
        )
        .await
        .unwrap();

        // Insert a person with properties that match the base cohort condition
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"$browser_version": 126})),
        )
        .await
        .unwrap();

        // Define a flag with a cohort filter that depends on another cohort
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: json!(dependent_cohort_row.id),
                        operator: Some(OperatorType::In),
                        prop_type: "cohort".to_string(),
                        group_type_index: None,
                        negation: Some(false),
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
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_in_cohort_matching_user_not_in_cohort() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        // Insert a cohort with a condition that does not match the test user's properties
        let cohort_row = insert_cohort_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            None,
            json!({
                "properties": {
                    "type": "OR",
                    "values": [{
                        "type": "OR",
                        "values": [{
                            "key": "$browser_version",
                            "type": "person",
                            "value": "130",
                            "negation": false,
                            "operator": "gt"
                        }]
                    }]
                }
            }),
            false,
        )
        .await
        .unwrap();

        // Insert a person with properties that do not match the cohort condition
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"$browser_version": 125})),
        )
        .await
        .unwrap();

        // Define a flag with an In cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: json!(cohort_row.id),
                        operator: Some(OperatorType::In),
                        prop_type: "cohort".to_string(),
                        group_type_index: None,
                        negation: Some(false),
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
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        // The user does not match the cohort, and the flag is set to In, so it should evaluate to false
        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_static_cohort_matching_user_in_cohort() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            Some("Static Cohort".to_string()),
            json!({}), // Static cohorts don't have property filters
            true,      // is_static = true
        )
        .await
        .unwrap();

        // Insert a person
        let distinct_id = "static_user".to_string();
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "static@user.com"})),
        )
        .await
        .unwrap();

        // Retrieve the person's ID
        let person_id =
            get_person_id_by_distinct_id(postgres_reader.clone(), team.id, &distinct_id)
                .await
                .unwrap();

        // Associate the person with the static cohort
        add_person_to_cohort(postgres_reader.clone(), person_id, cohort.id)
            .await
            .unwrap();

        // Define a flag with an 'In' cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: json!(cohort.id),
                        operator: Some(OperatorType::In),
                        prop_type: "cohort".to_string(),
                        group_type_index: None,
                        negation: Some(false),
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
            distinct_id.clone(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(
            result.matches,
            "User should match the static cohort and flag"
        );
    }

    #[tokio::test]
    async fn test_static_cohort_matching_user_not_in_cohort() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            Some("Another Static Cohort".to_string()),
            json!({}), // Static cohorts don't have property filters
            true,
        )
        .await
        .unwrap();

        // Insert a person
        let distinct_id = "non_static_user".to_string();
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "nonstatic@user.com"})),
        )
        .await
        .unwrap();

        // Note: Do NOT associate the person with the static cohort

        // Define a flag with an 'In' cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: json!(cohort.id),
                        operator: Some(OperatorType::In),
                        prop_type: "cohort".to_string(),
                        group_type_index: None,
                        negation: Some(false),
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
            distinct_id.clone(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(
            !result.matches,
            "User should not match the static cohort and flag"
        );
    }

    #[tokio::test]
    async fn test_static_cohort_not_in_matching_user_not_in_cohort() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            Some("Static Cohort NotIn".to_string()),
            json!({}), // Static cohorts don't have property filters
            true,      // is_static = true
        )
        .await
        .unwrap();

        // Insert a person
        let distinct_id = "not_in_static_user".to_string();
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "notinstatic@user.com"})),
        )
        .await
        .unwrap();

        // No association with the static cohort

        // Define a flag with a 'NotIn' cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: json!(cohort.id),
                        operator: Some(OperatorType::NotIn),
                        prop_type: "cohort".to_string(),
                        group_type_index: None,
                        negation: Some(false),
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
            distinct_id.clone(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(
            result.matches,
            "User not in the static cohort should match the 'NotIn' flag"
        );
    }

    #[tokio::test]
    async fn test_static_cohort_not_in_matching_user_in_cohort() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            Some("Static Cohort NotIn User In".to_string()),
            json!({}), // Static cohorts don't have property filters
            true,      // is_static = true
        )
        .await
        .unwrap();

        // Insert a person
        let distinct_id = "in_not_in_static_user".to_string();
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "innotinstatic@user.com"})),
        )
        .await
        .unwrap();

        // Retrieve the person's ID
        let person_id =
            get_person_id_by_distinct_id(postgres_reader.clone(), team.id, &distinct_id)
                .await
                .unwrap();

        // Associate the person with the static cohort
        add_person_to_cohort(postgres_reader.clone(), person_id, cohort.id)
            .await
            .unwrap();

        // Define a flag with a 'NotIn' cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: json!(cohort.id),
                        operator: Some(OperatorType::NotIn),
                        prop_type: "cohort".to_string(),
                        group_type_index: None,
                        negation: Some(false),
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
            distinct_id.clone(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).await.unwrap();

        assert!(
            !result.matches,
            "User in the static cohort should not match the 'NotIn' flag"
        );
    }

    #[tokio::test]
    async fn test_set_feature_flag_hash_key_overrides_success() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();
        let distinct_id = "user2".to_string();

        // Insert person
        insert_person_for_team_in_pg(postgres_reader.clone(), team.id, distinct_id.clone(), None)
            .await
            .unwrap();

        // Create a feature flag with ensure_experience_continuity = true
        let flag = create_test_flag(
            None,
            Some(team.id),
            Some("Test Flag".to_string()),
            Some("test_flag".to_string()),
            Some(FlagFilters {
                groups: vec![],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            Some(false), // not deleted
            Some(true),  // active
            Some(true),  // ensure_experience_continuity
        );

        // Convert flag to FeatureFlagRow
        let flag_row = FeatureFlagRow {
            id: flag.id,
            team_id: flag.team_id,
            name: flag.name,
            key: flag.key,
            filters: json!(flag.filters),
            deleted: flag.deleted,
            active: flag.active,
            ensure_experience_continuity: flag.ensure_experience_continuity,
        };

        // Insert the feature flag into the database
        insert_flag_for_team_in_pg(postgres_writer.clone(), team.id, Some(flag_row))
            .await
            .unwrap();

        // Set hash key override
        set_feature_flag_hash_key_overrides(
            postgres_writer.clone(),
            team.id,
            vec![distinct_id.clone()],
            "hash_key_2".to_string(),
        )
        .await
        .unwrap();

        // Retrieve hash key overrides
        let overrides = get_feature_flag_hash_key_overrides(
            postgres_reader.clone(),
            team.id,
            vec![distinct_id.clone()],
        )
        .await
        .unwrap();

        assert_eq!(
            overrides.get("test_flag"),
            Some(&"hash_key_2".to_string()),
            "Hash key override should match the set value"
        );
    }

    #[tokio::test]
    async fn test_get_feature_flag_hash_key_overrides_success() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();
        let distinct_id = "user2".to_string();

        // Insert person
        insert_person_for_team_in_pg(postgres_reader.clone(), team.id, distinct_id.clone(), None)
            .await
            .unwrap();

        // Create a feature flag with ensure_experience_continuity = true
        let flag = create_test_flag(
            None,
            Some(team.id),
            Some("Test Flag".to_string()),
            Some("test_flag".to_string()),
            Some(FlagFilters {
                groups: vec![],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            Some(false), // not deleted
            Some(true),  // active
            Some(true),  // ensure_experience_continuity
        );

        // Convert flag to FeatureFlagRow
        let flag_row = FeatureFlagRow {
            id: flag.id,
            team_id: flag.team_id,
            name: flag.name,
            key: flag.key,
            filters: json!(flag.filters),
            deleted: flag.deleted,
            active: flag.active,
            ensure_experience_continuity: flag.ensure_experience_continuity,
        };

        // Insert the feature flag into the database
        insert_flag_for_team_in_pg(postgres_writer.clone(), team.id, Some(flag_row))
            .await
            .unwrap();

        // Set hash key override
        set_feature_flag_hash_key_overrides(
            postgres_writer.clone(),
            team.id,
            vec![distinct_id.clone()],
            "hash_key_2".to_string(),
        )
        .await
        .unwrap();

        // Retrieve hash key overrides
        let overrides = get_feature_flag_hash_key_overrides(
            postgres_reader.clone(),
            team.id,
            vec![distinct_id.clone()],
        )
        .await
        .unwrap();

        assert_eq!(
            overrides.get("test_flag"),
            Some(&"hash_key_2".to_string()),
            "Hash key override should match the set value"
        );
    }

    #[tokio::test]
    async fn test_evaluate_feature_flags_with_experience_continuity() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();
        let distinct_id = "user3".to_string();

        // Insert person
        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "user3@example.com"})),
        )
        .await
        .unwrap();

        // Create flag with experience continuity
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("flag_continuity".to_string()),
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: json!("user3@example.com"),
                        operator: None,
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
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
            Some(true),
        );

        // Set hash key override
        set_feature_flag_hash_key_overrides(
            postgres_writer.clone(),
            team.id,
            vec![distinct_id.clone()],
            "hash_key_continuity".to_string(),
        )
        .await
        .unwrap();

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };

        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(flags, None, None, Some("hash_key_continuity".to_string()))
        .await;

        assert!(!result.error_while_computing_flags, "No error should occur");
        assert_eq!(
            result.feature_flags.get("flag_continuity"),
            Some(&FlagValue::Boolean(true)),
            "Flag should be evaluated as true with continuity"
        );
    }

    #[tokio::test]
    async fn test_evaluate_feature_flags_with_continuity_missing_override() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();
        let distinct_id = "user4".to_string();

        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "user4@example.com"})),
        )
        .await
        .unwrap();

        // Create flag with experience continuity
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("flag_continuity_missing".to_string()),
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: json!("user4@example.com"),
                        operator: None,
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
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
            Some(true),
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };

        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(flags, None, None, None)
        .await;

        assert!(!result.error_while_computing_flags, "No error should occur");
        assert_eq!(
            result.feature_flags.get("flag_continuity_missing"),
            Some(&FlagValue::Boolean(true)),
            "Flag should be evaluated as true even without continuity override"
        );
    }

    #[tokio::test]
    async fn test_evaluate_all_feature_flags_mixed_continuity() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(postgres_reader.clone(), None, None));
        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .unwrap();
        let distinct_id = "user5".to_string();

        insert_person_for_team_in_pg(
            postgres_reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "user5@example.com"})),
        )
        .await
        .unwrap();

        // Create flag with continuity
        let flag_continuity = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("flag_continuity_mix".to_string()),
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: json!("user5@example.com"),
                        operator: None,
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
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
            Some(true),
        );

        // Create flag without continuity
        let flag_no_continuity = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("flag_no_continuity_mix".to_string()),
            Some(FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "age".to_string(),
                        value: json!(30),
                        operator: Some(OperatorType::Gt),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
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
            Some(false),
        );

        // Set hash key override for the continuity flag
        set_feature_flag_hash_key_overrides(
            postgres_writer.clone(),
            team.id,
            vec![distinct_id.clone()],
            "hash_key_mixed".to_string(),
        )
        .await
        .unwrap();

        let flags = FeatureFlagList {
            flags: vec![flag_continuity.clone(), flag_no_continuity.clone()],
        };

        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            postgres_reader.clone(),
            postgres_writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            Some(HashMap::from([("age".to_string(), json!(35))])),
            None,
            Some("hash_key_mixed".to_string()),
        )
        .await;

        assert!(!result.error_while_computing_flags, "No error should occur");
        assert_eq!(
            result.feature_flags.get("flag_continuity_mix"),
            Some(&FlagValue::Boolean(true)),
            "Continuity flag should be evaluated as true"
        );
        assert_eq!(
            result.feature_flags.get("flag_no_continuity_mix"),
            Some(&FlagValue::Boolean(true)),
            "Non-continuity flag should be evaluated based on properties"
        );
    }
}
