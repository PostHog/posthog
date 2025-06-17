use crate::api::errors::FlagError;
use crate::api::types::{
    ConfigResponse, FlagDetails, FlagValue, FlagsResponse, FromFeatureAndMatch,
};
use crate::cohorts::cohort_cache_manager::CohortCacheManager;
use crate::cohorts::cohort_models::{Cohort, CohortId};
use crate::cohorts::cohort_operations::{apply_cohort_membership_logic, evaluate_dynamic_cohorts};
use crate::flags::flag_group_type_mapping::{GroupTypeIndex, GroupTypeMappingCache};
use crate::flags::flag_match_reason::FeatureFlagMatchReason;
use crate::flags::flag_matching_utils::all_flag_condition_properties_match;
use crate::flags::flag_models::{FeatureFlag, FeatureFlagId, FeatureFlagList, FlagPropertyGroup};
use crate::metrics::consts::{
    DB_PERSON_AND_GROUP_PROPERTIES_READS_COUNTER, FLAG_DB_PROPERTIES_FETCH_TIME,
    FLAG_EVALUATE_ALL_CONDITIONS_TIME, FLAG_EVALUATION_ERROR_COUNTER, FLAG_EVALUATION_TIME,
    FLAG_GET_MATCH_TIME, FLAG_GROUP_CACHE_FETCH_TIME, FLAG_GROUP_DB_FETCH_TIME,
    FLAG_HASH_KEY_PROCESSING_TIME, FLAG_HASH_KEY_WRITES_COUNTER,
    FLAG_LOCAL_PROPERTY_OVERRIDE_MATCH_TIME, PROPERTY_CACHE_HITS_COUNTER,
    PROPERTY_CACHE_MISSES_COUNTER,
};
use crate::metrics::utils::parse_exception_for_prometheus_label;
use crate::properties::property_models::PropertyFilter;
use anyhow::Result;
use common_database::Client as DatabaseClient;
use common_metrics::inc;
use common_types::{PersonId, ProjectId, TeamId};
use rayon::prelude::*;
use serde_json::Value;
use std::collections::hash_map::Entry;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tracing::{error, warn};
use uuid::Uuid;

use super::flag_matching_utils::{
    all_properties_match, calculate_hash, fetch_and_locally_cache_all_relevant_properties,
    get_feature_flag_hash_key_overrides, locally_computable_property_overrides,
    set_feature_flag_hash_key_overrides, should_write_hash_key_override,
};

pub type PostgresReader = Arc<dyn DatabaseClient + Send + Sync>;
pub type PostgresWriter = Arc<dyn DatabaseClient + Send + Sync>;

#[derive(Debug)]
struct SuperConditionEvaluation {
    should_evaluate: bool,
    is_match: bool,
    reason: FeatureFlagMatchReason,
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct FeatureFlagMatch {
    pub matches: bool,
    pub variant: Option<String>,
    pub reason: FeatureFlagMatchReason,
    pub condition_index: Option<usize>,
    pub payload: Option<Value>,
}

impl FeatureFlagMatch {
    pub fn get_flag_value(&self) -> FlagValue {
        match (self.matches, &self.variant) {
            (true, Some(variant)) => FlagValue::String(variant.clone()),
            (true, None) => FlagValue::Boolean(true),
            (false, _) => FlagValue::Boolean(false),
        }
    }
}

/// This struct maintains evaluation state by caching database-sourced data during feature flag evaluation.
/// It stores person IDs, properties, group properties, and cohort matches that are fetched from the database,
/// allowing them to be reused across multiple flag evaluations within the same request without additional DB lookups.
///
/// The cache is scoped to a single evaluation session and is cleared between different requests.
#[derive(Clone, Default, Debug)]
pub struct FlagEvaluationState {
    /// The person ID associated with the distinct_id being evaluated
    person_id: Option<PersonId>,
    /// Properties associated with the person, fetched from the database
    pub(crate) person_properties: Option<HashMap<String, Value>>,
    /// Properties for each group type involved in flag evaluation
    group_properties: HashMap<GroupTypeIndex, HashMap<String, Value>>,
    /// Cohorts for the current request
    cohorts: Option<Vec<Cohort>>,
    /// Cache of static cohort membership results to avoid repeated DB lookups
    static_cohort_matches: Option<HashMap<CohortId, bool>>,
    /// Cache of flag evaluation results to avoid repeated DB lookups
    flag_evaluation_results: HashMap<FeatureFlagId, FlagValue>,
}

impl FlagEvaluationState {
    pub fn get_person_id(&self) -> Option<PersonId> {
        self.person_id
    }

    pub fn get_person_properties(&self) -> Option<&HashMap<String, Value>> {
        self.person_properties.as_ref()
    }

    pub fn get_group_properties(&self) -> &HashMap<GroupTypeIndex, HashMap<String, Value>> {
        &self.group_properties
    }

    pub fn get_static_cohort_matches(&self) -> Option<&HashMap<CohortId, bool>> {
        self.static_cohort_matches.as_ref()
    }

    pub fn set_person_id(&mut self, id: PersonId) {
        self.person_id = Some(id);
    }

    pub fn set_person_properties(&mut self, properties: HashMap<String, Value>) {
        self.person_properties = Some(properties);
    }

    pub fn set_cohorts(&mut self, cohorts: Vec<Cohort>) {
        self.cohorts = Some(cohorts);
    }

    pub fn set_group_properties(
        &mut self,
        group_type_index: GroupTypeIndex,
        properties: HashMap<String, Value>,
    ) {
        self.group_properties.insert(group_type_index, properties);
    }

    pub fn set_static_cohort_matches(&mut self, matches: HashMap<CohortId, bool>) {
        self.static_cohort_matches = Some(matches);
    }

    pub fn add_flag_evaluation_result(&mut self, flag_id: FeatureFlagId, flag_value: FlagValue) {
        self.flag_evaluation_results.insert(flag_id, flag_value);
    }
}

/// Represents the group-related data needed for feature flag evaluation
#[derive(Debug)]
struct GroupEvaluationData {
    /// Set of group type indexes required for flag evaluation
    type_indexes: HashSet<GroupTypeIndex>,
    /// Set of group keys that need to be evaluated
    keys: HashSet<String>,
}

/// Evaluates feature flags for a specific user/group context.
///
/// This struct maintains the state and logic needed to evaluate feature flags, including:
/// - User identification (distinct_id, team_id)
/// - Database connections for fetching data
/// - Caches for properties, cohorts, and group mappings to optimize performance
/// - Evaluation state that persists across multiple flag evaluations in a request
///
/// The matcher is typically created once per request and can evaluate multiple flags
/// efficiently by reusing cached data and DB connections.
#[derive(Clone)]
pub struct FeatureFlagMatcher {
    /// Unique identifier for the user/entity being evaluated
    pub distinct_id: String,
    /// Team ID for scoping flag evaluations
    pub team_id: TeamId,
    /// Project ID for scoping flag evaluations
    pub project_id: ProjectId,
    /// Database connection for reading data
    pub reader: PostgresReader,
    /// Database connection for writing data (e.g. experience continuity overrides)
    pub writer: PostgresWriter,
    /// Cache manager for cohort definitions and memberships
    pub cohort_cache: Arc<CohortCacheManager>,
    /// Cache for mapping between group types and their indices
    group_type_mapping_cache: GroupTypeMappingCache,
    /// State maintained during flag evaluation, including cached DB lookups
    pub(crate) flag_evaluation_state: FlagEvaluationState,
    /// Group key mappings for group-based flag evaluation
    groups: HashMap<String, Value>,
}

impl FeatureFlagMatcher {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        distinct_id: String,
        team_id: TeamId,
        project_id: ProjectId,
        reader: PostgresReader,
        writer: PostgresWriter,
        cohort_cache: Arc<CohortCacheManager>,
        group_type_mapping_cache: Option<GroupTypeMappingCache>,
        groups: Option<HashMap<String, Value>>,
    ) -> Self {
        FeatureFlagMatcher {
            distinct_id,
            team_id,
            project_id,
            reader: reader.clone(),
            writer: writer.clone(),
            cohort_cache,
            group_type_mapping_cache: group_type_mapping_cache
                .unwrap_or_else(|| GroupTypeMappingCache::new(project_id)),
            groups: groups.unwrap_or_default(),
            flag_evaluation_state: FlagEvaluationState::default(),
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
        request_id: Uuid,
    ) -> FlagsResponse {
        let eval_timer = common_metrics::timing_guard(FLAG_EVALUATION_TIME, &[]);
        let flags_have_experience_continuity_enabled = feature_flags
            .flags
            .iter()
            .any(|flag| flag.ensure_experience_continuity);

        // Process any hash key overrides
        let (hash_key_overrides, flag_hash_key_override_error) = self
            .process_hash_key_override_if_needed(
                flags_have_experience_continuity_enabled,
                hash_key_override,
            )
            .await;

        let flags_response = self
            .evaluate_flags_with_overrides(
                feature_flags,
                person_property_overrides,
                group_property_overrides,
                hash_key_overrides,
                request_id,
            )
            .await;

        eval_timer
            .label(
                "outcome",
                if flags_response.errors_while_computing_flags || flag_hash_key_override_error {
                    "error"
                } else {
                    "success"
                },
            )
            .fin();

        FlagsResponse {
            errors_while_computing_flags: flag_hash_key_override_error
                || flags_response.errors_while_computing_flags,
            flags: flags_response.flags,
            quota_limited: None,
            request_id,
            config: ConfigResponse::default(),
        }
    }

    /// Processes hash key overrides for feature flags with experience continuity enabled.
    ///
    /// This method handles the logic for managing hash key overrides, which are used to ensure
    /// consistent feature flag experiences across different distinct IDs (e.g., when a user logs in).
    /// It performs the following steps:
    ///
    /// 1. Checks if a hash key override needs to be written by comparing the current distinct ID
    ///    with the provided hash key
    /// 2. If needed, writes the hash key override to the database using the writer connection
    /// 3. Increments metrics to track successful/failed hash key override writes
    /// 4. Retrieves and returns the current hash key overrides for the target distinct IDs
    ///
    /// Returns a tuple containing:
    /// - Option<HashMap<String, String>>: The hash key overrides if successfully retrieved, None if there was an error
    /// - bool: Whether there was an error during processing (true = error occurred)
    async fn process_hash_key_override(
        &self,
        hash_key: String,
        target_distinct_ids: Vec<String>,
    ) -> (Option<HashMap<String, String>>, bool) {
        let should_write = match should_write_hash_key_override(
            self.reader.clone(),
            self.team_id,
            self.distinct_id.clone(),
            self.project_id,
            hash_key.clone(),
        )
        .await
        {
            Ok(should_write) => should_write,
            Err(e) => {
                error!(
                    "Failed to check if hash key override should be written for team {} project {} distinct_id {}: {:?}",
                    self.team_id, self.project_id, self.distinct_id, e
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
                self.writer.clone(),
                self.team_id,
                target_distinct_ids.clone(),
                self.project_id,
                hash_key.clone(),
            )
            .await
            {
                error!("Failed to set feature flag hash key overrides for team {} project {} distinct_id {} hash_key {}: {:?}", self.team_id, self.project_id, self.distinct_id, hash_key, e);
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

        inc(
            FLAG_HASH_KEY_WRITES_COUNTER,
            &[(
                "successful_write".to_string(),
                writing_hash_key_override.to_string(),
            )],
            1,
        );

        match get_feature_flag_hash_key_overrides(
            self.reader.clone(),
            self.team_id,
            target_distinct_ids,
        )
        .await
        {
            Ok(overrides) => (Some(overrides), false),
            Err(e) => {
                error!("Failed to get feature flag hash key overrides for team {} project {} distinct_id {}: {:?}", self.team_id, self.project_id, self.distinct_id, e);
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

    /// Evaluates cohort filters
    /// Uses the static cohort results from the cache, and
    /// evaluates dynamic cohorts based on the provided properties
    /// (converts dynamic cohorts into property filters and then evaluates them)
    pub fn evaluate_cohort_filters(
        &self,
        cohort_property_filters: &[PropertyFilter],
        target_properties: &HashMap<String, Value>,
        cohorts: Vec<Cohort>,
    ) -> Result<bool, FlagError> {
        // Get cached static cohort results or evaluate them if not cached
        let static_cohort_matches = match self.flag_evaluation_state.get_static_cohort_matches() {
            Some(matches) => matches.clone(),
            None => HashMap::new(), // NB: this happens if a flag has static cohort filters but is targeting an anonymous user.  Shouldn't error, just return empty.
        };

        // Store all cohort match results, starting with static cohort results
        let mut cohort_matches = static_cohort_matches;

        // For any cohorts not yet evaluated (i.e., dynamic ones), evaluate them
        for filter in cohort_property_filters {
            let cohort_id = filter
                .get_cohort_id()
                .ok_or(FlagError::CohortFiltersParsingError)?;

            if let Entry::Vacant(e) = cohort_matches.entry(cohort_id) {
                let match_result =
                    evaluate_dynamic_cohorts(cohort_id, target_properties, &cohorts)?;
                e.insert(match_result);
            }
        }

        // Apply cohort membership logic (IN|NOT_IN) to the cohort match results
        apply_cohort_membership_logic(cohort_property_filters, &cohort_matches)
    }

    /// Evaluates feature flags with property and hash key overrides.
    ///
    /// This function evaluates feature flags in two steps:
    /// 1. First, it evaluates flags that can be computed using only the provided property overrides
    /// 2. Then, for remaining flags that need database properties, it fetches and caches those properties
    ///    before evaluating those flags
    pub async fn evaluate_flags_with_overrides(
        &mut self,
        feature_flags: FeatureFlagList,
        person_property_overrides: Option<HashMap<String, Value>>,
        group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
        hash_key_overrides: Option<HashMap<String, String>>,
        request_id: Uuid,
    ) -> FlagsResponse {
        // Initialize group type mappings if needed
        let mut errors_while_computing_flags = self
            .initialize_group_type_mappings_if_needed(&feature_flags)
            .await;

        // Evaluate all flags in the current level
        let (flag_details_map, level_errors) = self
            .evaluate_flags_in_level(
                &feature_flags.flags,
                &person_property_overrides,
                &group_property_overrides,
                hash_key_overrides,
            )
            .await;
        errors_while_computing_flags |= level_errors;

        FlagsResponse {
            errors_while_computing_flags,
            flags: flag_details_map,
            quota_limited: None,
            request_id,
            config: ConfigResponse::default(),
        }
    }

    /// Evaluates a set of flags using a fallback strategy:
    /// 1. First tries to evaluate with property overrides
    /// 2. For flags that need DB properties, prepares evaluation state
    /// 3. Evaluates remaining flags with cached properties
    ///
    /// This function is designed to be used as part of a level-based evaluation strategy
    /// (e.g., Kahn's algorithm) for handling flag dependencies.
    async fn evaluate_flags_in_level(
        &mut self,
        flags: &[FeatureFlag],
        person_property_overrides: &Option<HashMap<String, Value>>,
        group_property_overrides: &Option<HashMap<String, HashMap<String, Value>>>,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> (HashMap<String, FlagDetails>, bool) {
        let mut errors_while_computing_flags = false;
        let mut flag_details_map = HashMap::new();
        let mut flags_needing_db_properties = Vec::new();

        // Step 1: Evaluate flags with locally computable property overrides first
        for flag in flags {
            // Skip disabled or deleted flags
            if !flag.active || flag.deleted {
                continue;
            }

            let property_override_match_timer =
                common_metrics::timing_guard(FLAG_LOCAL_PROPERTY_OVERRIDE_MATCH_TIME, &[]);

            match self.match_flag_with_property_overrides(
                flag,
                person_property_overrides,
                group_property_overrides,
                hash_key_overrides.clone(),
            ) {
                Ok(Some(flag_match)) => {
                    self.flag_evaluation_state
                        .add_flag_evaluation_result(flag.id, flag_match.get_flag_value());
                    flag_details_map
                        .insert(flag.key.clone(), FlagDetails::create(flag, &flag_match));
                }
                Ok(None) => {
                    flags_needing_db_properties.push(flag.clone());
                }
                Err(e) => {
                    errors_while_computing_flags = true;
                    let reason = parse_exception_for_prometheus_label(&e);

                    // Handle DependencyNotFound errors differently since they indicate a deleted dependency
                    if let FlagError::DependencyNotFound(dependency_type, dependency_id) = &e {
                        warn!(
                            "Feature flag '{}' targeting deleted {} with id {} for distinct_id '{}': {:?}",
                            flag.key, dependency_type, dependency_id, self.distinct_id, e
                        );
                    } else {
                        error!(
                            "Error evaluating feature flag '{}' with overrides for distinct_id '{}': {:?}",
                            flag.key, self.distinct_id, e
                        );
                    }

                    inc(
                        FLAG_EVALUATION_ERROR_COUNTER,
                        &[("reason".to_string(), reason.to_string())],
                        1,
                    );
                }
            }
            property_override_match_timer
                .label(
                    "outcome",
                    if errors_while_computing_flags {
                        "error"
                    } else {
                        "success"
                    },
                )
                .fin();
        }

        // Step 2: Prepare evaluation data for remaining flags
        if !flags_needing_db_properties.is_empty() {
            if let Err(e) = self
                .prepare_flag_evaluation_state(&flags_needing_db_properties)
                .await
            {
                // Handle database errors
                errors_while_computing_flags = true;
                let reason = parse_exception_for_prometheus_label(&e);
                for flag in &flags_needing_db_properties {
                    flag_details_map.insert(
                        flag.key.clone(),
                        FlagDetails::create_error(flag, reason, None),
                    );
                }
                error!("Error preparing flag evaluation state for team {} project {} distinct_id {}: {:?}", self.team_id, self.project_id, self.distinct_id, e);
                inc(
                    FLAG_EVALUATION_ERROR_COUNTER,
                    &[("reason".to_string(), reason.to_string())],
                    1,
                );
                return (flag_details_map, errors_while_computing_flags);
            }
        }

        // Step 3: Evaluate remaining flags with cached properties
        let flag_get_match_timer = common_metrics::timing_guard(FLAG_GET_MATCH_TIME, &[]);

        // Create a HashMap for quick flag lookups
        let flags_map: HashMap<_, _> = flags_needing_db_properties
            .iter()
            .map(|flag| (flag.key.clone(), flag))
            .collect();

        let results: Vec<(String, Result<FeatureFlagMatch, FlagError>)> =
            flags_needing_db_properties
                .par_iter()
                .map(|flag| {
                    // For flags that need DB properties, we still pass person property overrides
                    // but only for super condition evaluation. Regular conditions will use cached DB properties.
                    let person_overrides_for_super_conditions =
                        if flag.get_group_type_index().is_some() {
                            // For group-based flags, don't pass person overrides
                            None
                        } else {
                            // For person-based flags, pass person overrides for super condition evaluation
                            person_property_overrides.clone()
                        };

                    (
                        flag.key.clone(),
                        self.get_match_for_db_path(
                            flag,
                            person_overrides_for_super_conditions,
                            hash_key_overrides.clone(),
                        ),
                    )
                })
                .collect();

        for (flag_key, result) in results {
            let flag = flags_map.get(&flag_key).unwrap();

            match result {
                Ok(flag_match) => {
                    self.flag_evaluation_state
                        .add_flag_evaluation_result(flag.id, flag_match.get_flag_value());
                    flag_details_map.insert(flag_key, FlagDetails::create(flag, &flag_match));
                }
                Err(e) => {
                    errors_while_computing_flags = true;
                    let reason = parse_exception_for_prometheus_label(&e);

                    // Handle DependencyNotFound errors differently since they indicate a deleted dependency
                    if let FlagError::DependencyNotFound(dependency_type, dependency_id) = &e {
                        warn!(
                            "Feature flag '{}' targeting deleted {} with id {} for distinct_id '{}': {:?}",
                            flag_key, dependency_type, dependency_id, self.distinct_id, e
                        );
                    } else {
                        error!(
                            "Error evaluating feature flag '{}' for distinct_id '{}': {:?}",
                            flag_key, self.distinct_id, e
                        );
                    }

                    inc(
                        FLAG_EVALUATION_ERROR_COUNTER,
                        &[("reason".to_string(), reason.to_string())],
                        1,
                    );
                    flag_details_map
                        .insert(flag_key, FlagDetails::create_error(flag, reason, None));
                }
            }
        }
        flag_get_match_timer
            .label(
                "outcome",
                if errors_while_computing_flags {
                    "error"
                } else {
                    "success"
                },
            )
            .fin();

        (flag_details_map, errors_while_computing_flags)
    }

    /// Matches a feature flag with property overrides.
    ///
    /// This function attempts to match a feature flag using either group or person property overrides,
    /// depending on whether the flag is group-based or person-based. It first collects all property
    /// filters from the flag's conditions, then retrieves the appropriate overrides, and finally
    /// attempts to match the flag using these overrides.
    fn match_flag_with_property_overrides(
        &mut self,
        flag: &FeatureFlag,
        person_property_overrides: &Option<HashMap<String, Value>>,
        group_property_overrides: &Option<HashMap<String, HashMap<String, Value>>>,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<Option<FeatureFlagMatch>, FlagError> {
        // Collect ALL property filters - both from regular conditions and super conditions
        let mut flag_property_filters: Vec<PropertyFilter> = flag
            .get_conditions()
            .iter()
            .flat_map(|c| c.properties.clone().unwrap_or_default())
            .collect();

        // Add super condition properties
        if let Some(super_groups) = &flag.filters.super_groups {
            flag_property_filters.extend(
                super_groups
                    .iter()
                    .flat_map(|c| c.properties.clone().unwrap_or_default()),
            );
        }

        let overrides = match flag.get_group_type_index() {
            Some(group_type_index) => self.get_group_overrides(
                group_type_index,
                group_property_overrides,
                &flag_property_filters,
            )?,
            None => self.get_person_overrides(person_property_overrides, &flag_property_filters),
        };

        // For flags with super conditions, we need special logic to ensure super condition properties are available
        if let Some(super_groups) = &flag.filters.super_groups {
            self.evaluate_with_super_conditions(flag, overrides, hash_key_overrides, super_groups)
        } else if flag.ensure_experience_continuity {
            self.evaluate_with_experience_continuity(
                flag,
                overrides,
                hash_key_overrides,
                &flag_property_filters,
            )
        } else {
            // Flag has no super conditions and no experience continuity - use the original override logic
            // This preserves the existing behavior where overrides can be partial
            match overrides {
                Some(props) => self
                    .get_match(flag, Some(props), hash_key_overrides)
                    .map(Some),
                None => Ok(None),
            }
        }
    }

    /// Evaluates flags with super conditions, ensuring all required properties are available in overrides
    fn evaluate_with_super_conditions(
        &mut self,
        flag: &FeatureFlag,
        overrides: Option<HashMap<String, Value>>,
        hash_key_overrides: Option<HashMap<String, String>>,
        super_groups: &[FlagPropertyGroup],
    ) -> Result<Option<FeatureFlagMatch>, FlagError> {
        let properties_available =
            self.are_super_condition_properties_available(&overrides, super_groups);

        match overrides {
            Some(props) if properties_available => {
                // Super condition properties are available in overrides
                self.get_match(flag, Some(props), hash_key_overrides)
                    .map(Some)
            }
            _ => {
                // Super condition properties are missing from overrides, go to DB path
                Ok(None)
            }
        }
    }

    /// Evaluates flags with experience continuity, ensuring all flag properties are available in overrides
    fn evaluate_with_experience_continuity(
        &mut self,
        flag: &FeatureFlag,
        overrides: Option<HashMap<String, Value>>,
        hash_key_overrides: Option<HashMap<String, String>>,
        flag_property_filters: &[PropertyFilter],
    ) -> Result<Option<FeatureFlagMatch>, FlagError> {
        let properties_available =
            self.are_all_properties_available(&overrides, flag_property_filters);

        match overrides {
            Some(props) if properties_available => {
                // All flag properties are available in overrides for continuity flag
                self.get_match(flag, Some(props), hash_key_overrides)
                    .map(Some)
            }
            _ => {
                // Required properties missing from overrides for continuity flag, go to DB path
                Ok(None)
            }
        }
    }

    /// Checks if all super condition properties are available in the provided overrides
    fn are_super_condition_properties_available(
        &self,
        overrides: &Option<HashMap<String, Value>>,
        super_groups: &[FlagPropertyGroup],
    ) -> bool {
        if let Some(ref overrides_map) = overrides {
            super_groups.iter().all(|super_group| {
                super_group.properties.as_ref().map_or(true, |props| {
                    props
                        .iter()
                        .all(|prop| overrides_map.contains_key(&prop.key))
                })
            })
        } else {
            false
        }
    }

    /// Checks if all required properties are available in the provided overrides
    fn are_all_properties_available(
        &self,
        overrides: &Option<HashMap<String, Value>>,
        property_filters: &[PropertyFilter],
    ) -> bool {
        if let Some(ref overrides_map) = overrides {
            property_filters
                .iter()
                .all(|prop| overrides_map.contains_key(&prop.key))
        } else {
            false
        }
    }

    /// Retrieves group overrides for a specific group type index.
    ///
    /// This function attempts to find and return property overrides for a given group type.
    /// It first maps the group type index to a group type, then checks if there are any
    /// overrides for that group type in the provided group property overrides.
    fn get_group_overrides(
        &mut self,
        group_type_index: GroupTypeIndex,
        group_property_overrides: &Option<HashMap<String, HashMap<String, Value>>>,
        flag_property_filters: &[PropertyFilter],
    ) -> Result<Option<HashMap<String, Value>>, FlagError> {
        // If we can't get the mapping, just return None instead of propagating the error
        let index_to_type_map = match self
            .group_type_mapping_cache
            .get_group_type_index_to_type_map()
        {
            Ok(map) => map,
            Err(FlagError::NoGroupTypeMappings) => return Ok(None),
            Err(e) => return Err(e),
        };

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
        locally_computable_property_overrides(person_property_overrides, flag_property_filters)
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
    pub fn get_match(
        &self,
        flag: &FeatureFlag,
        property_overrides: Option<HashMap<String, Value>>,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<FeatureFlagMatch, FlagError> {
        if self
            .hashed_identifier(flag, hash_key_overrides.clone())?
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
                let super_condition_evaluation = self.is_super_condition_match(
                    flag,
                    property_overrides.clone(),
                    hash_key_overrides.clone(),
                )?;

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

        // Match for holdout super condition
        // TODO: Flags shouldn't have both super_groups and holdout_groups
        // TODO: Validate only multivariant flags to have holdout groups. I could make this implicit by reusing super_groups but
        // this will shoot ourselves in the foot when we extend early access to support variants as well.
        // TODO: Validate holdout variant should have 0% default rollout %?
        // TODO: All this validation we need to do suggests the modelling is imperfect here. Carrying forward for now, we'll only enable
        // in beta, and potentially rework representation before rolling out to everyone. Probably the problem is holdout groups are an
        // experiment level concept that applies across experiments, and we are creating a feature flag level primitive to handle it.
        // Validating things like the variant name is the same across all flags, rolled out to 0%, has the same correct conditions is a bit of
        // a pain here. But I'm not sure if feature flags should indeed know all this info. It's fine for them to just work with what they're given.
        if let Some(holdout_groups) = &flag.filters.holdout_groups {
            if !holdout_groups.is_empty() {
                let (is_match, holdout_value, evaluation_reason) =
                    self.is_holdout_condition_match(flag)?;
                if is_match {
                    let payload = self.get_matching_payload(holdout_value.as_deref(), flag);
                    return Ok(FeatureFlagMatch {
                        matches: true,
                        variant: holdout_value,
                        reason: evaluation_reason,
                        condition_index: None,
                        payload,
                    });
                }
            }
        }
        // Sort conditions with variant overrides to the top so that we can evaluate them first
        let mut sorted_conditions: Vec<(usize, &FlagPropertyGroup)> =
            flag.get_conditions().iter().enumerate().collect();

        sorted_conditions
            .sort_by_key(|(_, condition)| if condition.variant.is_some() { 0 } else { 1 });

        let condition_timer = common_metrics::timing_guard(FLAG_EVALUATE_ALL_CONDITIONS_TIME, &[]);
        for (index, condition) in sorted_conditions {
            let (is_match, reason) = self.is_condition_match(
                flag,
                condition,
                property_overrides.clone(),
                hash_key_overrides.clone(),
            )?;

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

                // Check for variant override in the condition
                let variant = if let Some(variant_override) = &condition.variant {
                    // Check if the override is a valid variant
                    if flag
                        .get_variants()
                        .iter()
                        .any(|v| &v.key == variant_override)
                    {
                        Some(variant_override.clone())
                    } else {
                        // If override isn't valid, fall back to computed variant
                        self.get_matching_variant(flag, hash_key_overrides.clone())?
                    }
                } else {
                    // No override, use computed variant
                    self.get_matching_variant(flag, hash_key_overrides.clone())?
                };
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

        condition_timer.label("outcome", "success").fin();
        // Return with the highest_match reason and index even if no conditions matched
        Ok(FeatureFlagMatch {
            matches: false,
            variant: None,
            reason: highest_match,
            condition_index: highest_index,
            payload: None,
        })
    }

    /// Evaluates a feature flag in the DB path where regular conditions use cached DB properties
    /// but super conditions can still access property overrides.
    ///
    /// This method is used when a flag has property filters that require DB access (like cohorts),
    /// but we still want super conditions to be able to use property overrides.
    fn get_match_for_db_path(
        &self,
        flag: &FeatureFlag,
        super_condition_overrides: Option<HashMap<String, Value>>,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<FeatureFlagMatch, FlagError> {
        if self
            .hashed_identifier(flag, hash_key_overrides.clone())?
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

        // Evaluate any super conditions first, with access to property overrides
        if let Some(super_groups) = &flag.filters.super_groups {
            if !super_groups.is_empty() {
                let super_condition_evaluation = self.is_super_condition_match(
                    flag,
                    super_condition_overrides,
                    hash_key_overrides.clone(),
                )?;

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

        // Match for holdout super condition - same logic as regular get_match
        if let Some(holdout_groups) = &flag.filters.holdout_groups {
            if !holdout_groups.is_empty() {
                let (is_match, holdout_value, evaluation_reason) =
                    self.is_holdout_condition_match(flag)?;
                if is_match {
                    let payload = self.get_matching_payload(holdout_value.as_deref(), flag);
                    return Ok(FeatureFlagMatch {
                        matches: true,
                        variant: holdout_value,
                        reason: evaluation_reason,
                        condition_index: None,
                        payload,
                    });
                }
            }
        }

        // Evaluate regular conditions using cached DB properties (no overrides)
        let mut sorted_conditions: Vec<(usize, &FlagPropertyGroup)> =
            flag.get_conditions().iter().enumerate().collect();

        sorted_conditions
            .sort_by_key(|(_, condition)| if condition.variant.is_some() { 0 } else { 1 });

        let condition_timer = common_metrics::timing_guard(FLAG_EVALUATE_ALL_CONDITIONS_TIME, &[]);
        for (index, condition) in sorted_conditions {
            let (is_match, reason) = self.is_condition_match(
                flag,
                condition,
                None, // Use cached DB properties instead of overrides
                hash_key_overrides.clone(),
            )?;

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

                // Check for variant override in the condition
                let variant = if let Some(variant_override) = &condition.variant {
                    // Check if the override is a valid variant
                    if flag
                        .get_variants()
                        .iter()
                        .any(|v| &v.key == variant_override)
                    {
                        Some(variant_override.clone())
                    } else {
                        // If override isn't valid, fall back to computed variant
                        self.get_matching_variant(flag, hash_key_overrides.clone())?
                    }
                } else {
                    // No override, use computed variant
                    self.get_matching_variant(flag, hash_key_overrides.clone())?
                };
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

        condition_timer.label("outcome", "success").fin();
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
    /// especially useful when multiple conditions are evaluated.
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
    pub(crate) fn is_condition_match(
        &self,
        feature_flag: &FeatureFlag,
        condition: &FlagPropertyGroup,
        property_overrides: Option<HashMap<String, Value>>,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<(bool, FeatureFlagMatchReason), FlagError> {
        let rollout_percentage = condition.rollout_percentage.unwrap_or(100.0);

        if let Some(flag_property_filters) = &condition.properties {
            if flag_property_filters.is_empty() {
                return self.check_rollout(feature_flag, rollout_percentage, hash_key_overrides);
            }

            // Separate flag value filters from other filters
            let (flag_value_filters, other_filters): (Vec<PropertyFilter>, Vec<PropertyFilter>) =
                flag_property_filters
                    .iter()
                    .cloned()
                    .partition(|prop| prop.depends_on_feature_flag());

            if !flag_value_filters.is_empty()
                && !all_flag_condition_properties_match(
                    &flag_value_filters,
                    &self.flag_evaluation_state.flag_evaluation_results,
                )
            {
                return Ok((false, FeatureFlagMatchReason::NoConditionMatch));
            }

            // Separate cohort and non-cohort filters
            let (cohort_filters, non_cohort_filters): (Vec<PropertyFilter>, Vec<PropertyFilter>) =
                other_filters
                    .iter()
                    .cloned()
                    .partition(|prop| prop.is_cohort());

            // Get the properties we need to check for in this condition match from the flag + any overrides
            let person_or_group_properties = self.get_properties_to_check(
                feature_flag,
                property_overrides,
                &non_cohort_filters,
            )?;

            // Evaluate non-cohort filters first, since they're cheaper to evaluate and we can return early if they don't match
            if !all_properties_match(&non_cohort_filters, &person_or_group_properties) {
                return Ok((false, FeatureFlagMatchReason::NoConditionMatch));
            }

            // Evaluate cohort filters, if any.
            if !cohort_filters.is_empty() {
                let cohorts = match &self.flag_evaluation_state.cohorts {
                    Some(cohorts) => cohorts.clone(),
                    None => return Ok((false, FeatureFlagMatchReason::NoConditionMatch)),
                };
                if !self.evaluate_cohort_filters(
                    &cohort_filters,
                    &person_or_group_properties,
                    cohorts,
                )? {
                    return Ok((false, FeatureFlagMatchReason::NoConditionMatch));
                }
            }
        }

        self.check_rollout(feature_flag, rollout_percentage, hash_key_overrides)
    }

    /// Get properties to check for a feature flag.
    ///
    /// This function determines which properties to check based on the feature flag's group type index.
    /// If the flag is group-based, it fetches group properties; otherwise, it fetches person properties.
    fn get_properties_to_check(
        &self,
        feature_flag: &FeatureFlag,
        property_overrides: Option<HashMap<String, Value>>,
        flag_property_filters: &[PropertyFilter],
    ) -> Result<HashMap<String, Value>, FlagError> {
        if let Some(group_type_index) = feature_flag.get_group_type_index() {
            self.get_group_properties(group_type_index, property_overrides, flag_property_filters)
        } else {
            self.get_person_properties(property_overrides, flag_property_filters)
        }
    }

    /// Get group properties from overrides, cache or database.
    ///
    /// This function attempts to retrieve group properties either from a cache or directly from the database.
    /// It first checks if there are any locally computable property overrides. If so, it returns those.
    /// Otherwise, it fetches the properties from the cache or database and returns them.
    fn get_group_properties(
        &self,
        group_type_index: GroupTypeIndex,
        property_overrides: Option<HashMap<String, Value>>,
        flag_property_filters: &[PropertyFilter],
    ) -> Result<HashMap<String, Value>, FlagError> {
        if let Some(overrides) =
            locally_computable_property_overrides(&property_overrides, flag_property_filters)
        {
            Ok(overrides)
        } else {
            self.get_group_properties_from_cache(group_type_index)
        }
    }

    /// Get person properties from overrides, cache or database.
    ///
    /// This function attempts to retrieve person properties either from a cache or directly from the database.
    /// It first checks if there are any locally computable property overrides. If so, it returns those.
    /// Otherwise, it fetches the properties from the cache or database and returns them.
    fn get_person_properties(
        &self,
        property_overrides: Option<HashMap<String, Value>>,
        flag_property_filters: &[PropertyFilter],
    ) -> Result<HashMap<String, Value>, FlagError> {
        if let Some(overrides) =
            locally_computable_property_overrides(&property_overrides, flag_property_filters)
        {
            Ok(overrides)
        } else {
            match self.get_person_properties_from_cache() {
                Ok(props) => Ok(props),
                Err(_e) => Ok(HashMap::new()), // NB: if we can't find the properties in the cache, we return an empty HashMap because we just treat this person as one with no properties, essentially an anonymous user
            }
        }
    }

    fn is_holdout_condition_match(
        &self,
        flag: &FeatureFlag,
    ) -> Result<(bool, Option<String>, FeatureFlagMatchReason), FlagError> {
        // TODO: Right now holdout conditions only support basic rollout %s, and not property overrides.

        if let Some(holdout_groups) = &flag.filters.holdout_groups {
            if !holdout_groups.is_empty() {
                let condition = &holdout_groups[0];
                // TODO: Check properties and match based on them

                if condition
                    .properties
                    .as_ref()
                    .map_or(false, |p| !p.is_empty())
                {
                    return Ok((false, None, FeatureFlagMatchReason::NoConditionMatch));
                }

                let rollout_percentage = condition.rollout_percentage;

                if let Some(percentage) = rollout_percentage {
                    if self.get_holdout_hash(flag, None)? > (percentage / 100.0) {
                        // If hash is greater than percentage, we're OUT of holdout
                        return Ok((false, None, FeatureFlagMatchReason::OutOfRolloutBound));
                    }
                }

                // rollout_percentage is None (=100%), or we are inside holdout rollout bound.
                // Thus, we match. Now get the variant override for the holdout condition.
                let variant = if let Some(variant_override) = condition.variant.as_ref() {
                    variant_override.clone()
                } else {
                    self.get_matching_variant(flag, None)?
                        .unwrap_or_else(|| "holdout".to_string())
                };

                return Ok((
                    true,
                    Some(variant),
                    FeatureFlagMatchReason::HoldoutConditionValue,
                ));
            }
        }
        Ok((false, None, FeatureFlagMatchReason::NoConditionMatch))
    }

    /// Check if a super condition matches for a feature flag.
    ///
    /// This function evaluates the super conditions of a feature flag to determine if any of them should be enabled.
    /// It first checks if there are any super conditions. If so, it evaluates the first condition.
    /// The function returns a struct indicating whether a super condition should be evaluated,
    /// whether it matches if evaluated, and the reason for the match.
    fn is_super_condition_match(
        &self,
        feature_flag: &FeatureFlag,
        property_overrides: Option<HashMap<String, Value>>,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<SuperConditionEvaluation, FlagError> {
        if let Some(super_condition) = feature_flag
            .filters
            .super_groups
            .as_ref()
            .and_then(|sc| sc.first())
        {
            // For super conditions, we want to check if we can evaluate using ONLY the super condition properties
            // We don't care about other properties on the flag (like cohort filters in regular conditions)
            let super_condition_properties = super_condition.properties.as_deref().unwrap_or(&[]);

            let person_properties = if let Some(ref overrides) = property_overrides {
                // For super conditions, check if ALL required properties are present in overrides
                let all_super_condition_props_in_overrides = super_condition_properties
                    .iter()
                    .all(|prop| overrides.contains_key(&prop.key));

                if all_super_condition_props_in_overrides {
                    // We can compute all super condition properties from overrides
                    overrides.clone()
                } else {
                    // Fall back to cached properties since some super condition properties are missing
                    self.get_person_properties_from_cache().unwrap_or_default()
                }
            } else {
                // No overrides at all, fall back to cached properties
                self.get_person_properties_from_cache().unwrap_or_default()
            };

            let has_relevant_super_condition_properties =
                super_condition.properties.as_ref().map_or(false, |props| {
                    props
                        .iter()
                        .any(|prop| person_properties.contains_key(&prop.key))
                });

            let (is_match, _) = self.is_condition_match(
                feature_flag,
                super_condition,
                Some(person_properties),
                hash_key_overrides,
            )?;

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

    /// Get hashed identifier for a feature flag.
    ///
    /// This function generates a hashed identifier for a feature flag based on the feature flag's group type index.
    /// If the feature flag is group-based, it fetches the group key; otherwise, it uses the distinct ID.
    fn hashed_identifier(
        &self,
        feature_flag: &FeatureFlag,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<String, FlagError> {
        if let Some(group_type_index) = feature_flag.get_group_type_index() {
            // Group-based flag
            let group_key = match self
                .group_type_mapping_cache
                .get_group_type_index_to_type_map()?
                .get(&group_type_index)
                .and_then(|group_type_name| self.groups.get(group_type_name))
            {
                Some(Value::String(s)) => s.clone(),
                Some(Value::Number(n)) => n.to_string(),
                Some(_) => {
                    // For any other JSON type (bool, array, object, null), use empty string
                    // NB: we currently use empty string ("") as the hashed identifier for group flags without a group key,
                    // and I don't want to break parity with the old service since I don't want the hash values to change
                    "".to_string()
                }
                None => "".to_string(),
            };

            Ok(group_key)
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
    fn get_hash(
        &self,
        feature_flag: &FeatureFlag,
        salt: &str,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<f64, FlagError> {
        let hashed_identifier = self.hashed_identifier(feature_flag, hash_key_overrides)?;
        if hashed_identifier.is_empty() {
            // Return a hash value that will make the flag evaluate to false; since we
            // can't evaluate a flag without an identifier.
            return Ok(0.0); // NB: A flag with 0.0 hash will always evaluate to false
        }

        calculate_hash(&format!("{}.", feature_flag.key), &hashed_identifier, salt)
    }

    fn get_holdout_hash(
        &self,
        feature_flag: &FeatureFlag,
        salt: Option<&str>,
    ) -> Result<f64, FlagError> {
        let hashed_identifier = self.hashed_identifier(feature_flag, None)?;
        let hash = calculate_hash("holdout-", &hashed_identifier, salt.unwrap_or(""))?;
        Ok(hash)
    }

    /// Check if a feature flag should be shown based on its rollout percentage.
    ///
    /// This function determines if a feature flag should be shown to a user based on the flag's rollout percentage.
    /// It first calculates a hash of the feature flag's identifier and compares it to the rollout percentage.
    /// If the hash value is less than or equal to the rollout percentage, the flag is shown; otherwise, it is not.
    /// The function returns a tuple indicating whether the flag matched and the reason for the match.
    fn check_rollout(
        &self,
        feature_flag: &FeatureFlag,
        rollout_percentage: f64,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<(bool, FeatureFlagMatchReason), FlagError> {
        let hash = self.get_hash(feature_flag, "", hash_key_overrides)?;
        if rollout_percentage == 100.0 || hash <= (rollout_percentage / 100.0) {
            Ok((true, FeatureFlagMatchReason::ConditionMatch))
        } else {
            Ok((false, FeatureFlagMatchReason::OutOfRolloutBound))
        }
    }

    /// This function takes a feature flag and returns the key of the variant that should be shown to the user.
    pub(crate) fn get_matching_variant(
        &self,
        feature_flag: &FeatureFlag,
        hash_key_overrides: Option<HashMap<String, String>>,
    ) -> Result<Option<String>, FlagError> {
        let hash = self.get_hash(feature_flag, "variant", hash_key_overrides)?;
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

    /// Prepares all database-sourced data needed for flag evaluation.
    /// This includes:
    /// - Static cohort memberships
    /// - Group type mappings
    /// - Person and group properties
    ///
    /// The data is cached in FlagEvaluationState to avoid repeated DB lookups
    /// during subsequent flag evaluations.
    pub async fn prepare_flag_evaluation_state(
        &mut self,
        flags: &[FeatureFlag],
    ) -> Result<(), FlagError> {
        // Get cohorts first since we need the IDs
        let cohorts = self.cohort_cache.get_cohorts(self.project_id).await?;
        self.flag_evaluation_state.set_cohorts(cohorts.clone());

        // Get static cohort IDs
        let static_cohort_ids: Vec<CohortId> = cohorts
            .iter()
            .filter(|c| c.is_static)
            .map(|c| c.id)
            .collect();

        // Then prepare group mappings and properties
        // This should be _wicked_ fast since it's async and is just pulling from a cache that's already in memory
        let group_timer = common_metrics::timing_guard(FLAG_GROUP_CACHE_FETCH_TIME, &[]);
        let group_data = self.prepare_group_data(flags)?;
        group_timer.fin();

        // Single DB operation for properties and cohorts
        let db_fetch_timer = common_metrics::timing_guard(FLAG_DB_PROPERTIES_FETCH_TIME, &[]);
        match fetch_and_locally_cache_all_relevant_properties(
            &mut self.flag_evaluation_state,
            self.reader.clone(),
            self.distinct_id.clone(),
            self.team_id,
            &group_data.type_indexes,
            &group_data.keys,
            static_cohort_ids,
        )
        .await
        {
            Ok(_) => {
                inc(DB_PERSON_AND_GROUP_PROPERTIES_READS_COUNTER, &[], 1);
                db_fetch_timer.label("outcome", "success").fin();
                Ok(())
            }
            Err(e) => {
                error!(
                    "Error fetching properties for team {} project {} distinct_id {}: {:?}",
                    self.team_id, self.project_id, self.distinct_id, e
                );
                db_fetch_timer.label("outcome", "error").fin();
                Err(e)
            }
        }
    }

    /// Analyzes flags and prepares required group type data for flag evaluation.
    /// This includes:
    /// - Extracting required group type indexes from flags
    /// - Mapping group names to group_type_index and group_keys
    fn prepare_group_data(
        &mut self,
        flags: &[FeatureFlag],
    ) -> Result<GroupEvaluationData, FlagError> {
        // Extract required group type indexes from flags
        let type_indexes: HashSet<GroupTypeIndex> = flags
            .iter()
            .filter_map(|flag| flag.get_group_type_index())
            .collect();

        // Map group names to group_type_index and group_keys
        let group_type_to_key_map: HashMap<GroupTypeIndex, String> = self
            .groups
            .iter()
            .filter_map(|(group_type, group_key_value)| {
                let group_key = match group_key_value {
                    Value::String(s) => s.clone(),
                    Value::Number(n) => n.to_string(),
                    _ => return None, // Skip non-string, non-number group keys
                };
                self.group_type_mapping_cache
                    .get_group_types_to_indexes()
                    .ok()?
                    .get(group_type)
                    .cloned()
                    .map(|group_type_index| (group_type_index, group_key))
            })
            .collect();

        // Extract group_keys that are relevant to the required group_type_indexes
        let keys: HashSet<String> = group_type_to_key_map
            .iter()
            .filter_map(|(group_type_index, group_key)| {
                if type_indexes.contains(group_type_index) {
                    Some(group_key.clone())
                } else {
                    None
                }
            })
            .collect();

        Ok(GroupEvaluationData { type_indexes, keys })
    }

    /// Get person properties from cache only, returning empty HashMap if not found.
    fn get_person_properties_from_cache(&self) -> Result<HashMap<String, Value>, FlagError> {
        if let Some(properties) = self.flag_evaluation_state.get_person_properties() {
            inc(
                PROPERTY_CACHE_HITS_COUNTER,
                &[("type".to_string(), "person_properties".to_string())],
                1,
            );
            let mut result = HashMap::new();
            result.clone_from(properties);
            Ok(result)
        } else {
            inc(
                PROPERTY_CACHE_MISSES_COUNTER,
                &[("type".to_string(), "person_properties".to_string())],
                1,
            );
            // Return empty HashMap instead of error - no properties is a valid state
            // TODO probably worth error modeling empty cache vs error.
            // Maybe an error is fine?  Idk.  I feel like the idea is that there's no matching properties,
            // so it's not an error, it's just an empty result.
            // i just want to be able to differentiate between no properties because we fetched no properties,
            // and no properties because we failed to fetch
            // maybe I need a fetch indicator in the cache?
            Err(FlagError::PersonNotFound)
        }
    }

    /// Get group properties from cache only. Returns empty HashMap if not found.
    fn get_group_properties_from_cache(
        &self,
        group_type_index: GroupTypeIndex,
    ) -> Result<HashMap<String, Value>, FlagError> {
        let group_properties = self.flag_evaluation_state.get_group_properties();
        if let Some(properties) = group_properties.get(&group_type_index) {
            inc(
                PROPERTY_CACHE_HITS_COUNTER,
                &[("type".to_string(), "group_properties".to_string())],
                1,
            );
            let mut result = HashMap::new();
            result.clone_from(properties);
            Ok(result)
        } else {
            inc(
                PROPERTY_CACHE_MISSES_COUNTER,
                &[("type".to_string(), "group_properties".to_string())],
                1,
            );
            // Return empty HashMap instead of error - no properties is a valid state
            Ok(HashMap::new())
        }
    }

    // If experience continuity is enabled, we need to process the hash key override if it's provided.
    async fn process_hash_key_override_if_needed(
        &self,
        flags_have_experience_continuity_enabled: bool,
        hash_key_override: Option<String>,
    ) -> (Option<HashMap<String, String>>, bool) {
        let hash_key_timer = common_metrics::timing_guard(FLAG_HASH_KEY_PROCESSING_TIME, &[]);
        // If experience continuity is enabled, we need to process the hash key override if it's provided.
        let (hash_key_overrides, flag_hash_key_override_error) =
            if flags_have_experience_continuity_enabled {
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

        // If there was an error in processing hash key overrides, increment the error counter
        if flag_hash_key_override_error {
            let reason = "hash_key_override_error";
            common_metrics::inc(
                FLAG_EVALUATION_ERROR_COUNTER,
                &[("reason".to_string(), reason.to_string())],
                1,
            );
        }

        hash_key_timer
            .label(
                "outcome",
                if flag_hash_key_override_error {
                    "error"
                } else {
                    "success"
                },
            )
            .fin();

        (hash_key_overrides, flag_hash_key_override_error)
    }

    async fn initialize_group_type_mappings_if_needed(
        &mut self,
        feature_flags: &FeatureFlagList,
    ) -> bool {
        // Check if we need to fetch group type mappings – we have flags that use group properties (have group type indices)
        let has_type_indexes = feature_flags
            .flags
            .iter()
            .any(|flag| flag.active && !flag.deleted && flag.get_group_type_index().is_some());

        if !has_type_indexes {
            return false;
        }

        let group_type_mapping_timer = common_metrics::timing_guard(FLAG_GROUP_DB_FETCH_TIME, &[]);
        let mut errors_while_computing_flags = false;

        if self
            .group_type_mapping_cache
            .init(self.reader.clone())
            .await
            .is_err()
        {
            errors_while_computing_flags = true;
        }

        group_type_mapping_timer
            .label(
                "outcome",
                if errors_while_computing_flags {
                    "error"
                } else {
                    "success"
                },
            )
            .fin();

        errors_while_computing_flags
    }
}
