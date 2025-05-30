use crate::api::errors::FlagError;
use crate::api::types::{FlagDetails, FlagsResponse, FromFeatureAndMatch};
use crate::cohorts::cohort_cache_manager::CohortCacheManager;
use crate::cohorts::cohort_models::{Cohort, CohortId};
use crate::cohorts::cohort_operations::{apply_cohort_membership_logic, evaluate_dynamic_cohorts};
use crate::flags::flag_group_type_mapping::{GroupTypeIndex, GroupTypeMappingCache};
use crate::flags::flag_match_reason::FeatureFlagMatchReason;
use crate::flags::flag_models::{FeatureFlag, FeatureFlagList, FlagPropertyGroup};
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
use tracing::error;
use uuid::Uuid;

#[cfg(test)] // Only used in the tests
use crate::api::types::{FlagValue, LegacyFlagsResponse};

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
    person_properties: Option<HashMap<String, Value>>,
    /// Properties for each group type involved in flag evaluation
    group_properties: HashMap<GroupTypeIndex, HashMap<String, Value>>,
    /// Cohorts for the current request
    cohorts: Option<Vec<Cohort>>,
    /// Cache of static cohort membership results to avoid repeated DB lookups
    static_cohort_matches: Option<HashMap<CohortId, bool>>,
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
    flag_evaluation_state: FlagEvaluationState,
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
        let hash_key_timer = common_metrics::timing_guard(FLAG_HASH_KEY_PROCESSING_TIME, &[]);
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

        // If there was an initial error in processing hash key overrides, increment the error counter
        if flag_hash_key_override_error {
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

        FlagsResponse::new(
            flag_hash_key_override_error || flags_response.errors_while_computing_flags,
            flags_response.flags,
            None,
            request_id,
        )
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
                self.writer.clone(),
                self.team_id,
                target_distinct_ids.clone(),
                self.project_id,
                hash_key.clone(),
            )
            .await
            {
                error!("Failed to set feature flag hash key overrides: {:?}", e);
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
        let mut errors_while_computing_flags = false;
        let mut flag_details_map = HashMap::new();
        let mut flags_needing_db_properties = Vec::new();

        // Check if we need to fetch group type mappings – we have flags that use group properties (have group type indices)
        let has_type_indexes = feature_flags
            .flags
            .iter()
            .any(|flag| flag.active && !flag.deleted && flag.get_group_type_index().is_some());

        if has_type_indexes {
            let group_type_mapping_timer =
                common_metrics::timing_guard(FLAG_GROUP_DB_FETCH_TIME, &[]);

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
        }

        // Step 1: Evaluate flags with locally computable property overrides first
        for flag in &feature_flags.flags {
            // we shouldn't have any disabled or deleted flags (the query should filter them out),
            // but just in case, we skip them here
            if !flag.active || flag.deleted {
                continue;
            }

            let property_override_match_timer =
                common_metrics::timing_guard(FLAG_LOCAL_PROPERTY_OVERRIDE_MATCH_TIME, &[]);

            match self.match_flag_with_property_overrides(
                flag,
                &person_property_overrides,
                &group_property_overrides,
                hash_key_overrides.clone(),
            ) {
                Ok(Some(flag_match)) => {
                    flag_details_map
                        .insert(flag.key.clone(), FlagDetails::create(flag, &flag_match));
                }
                Ok(None) => {
                    flags_needing_db_properties.push(flag.clone());
                }
                Err(e) => {
                    errors_while_computing_flags = true;
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
                errors_while_computing_flags = true;
                let reason = parse_exception_for_prometheus_label(&e);
                for flag in flags_needing_db_properties {
                    flag_details_map
                        .insert(flag.key.clone(), FlagDetails::create_error(&flag, reason));
                }
                error!("Error preparing flag evaluation state: {:?}", e);
                inc(
                    FLAG_EVALUATION_ERROR_COUNTER,
                    &[("reason".to_string(), reason.to_string())],
                    1,
                );
                return FlagsResponse::new(
                    errors_while_computing_flags,
                    flag_details_map,
                    None,
                    request_id,
                );
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
                        (
                            flag.key.clone(),
                            self.get_match(flag, None, hash_key_overrides.clone()),
                        )
                    })
                    .collect();

            for (flag_key, result) in results {
                let flag = flags_map.get(&flag_key).unwrap();

                match result {
                    Ok(flag_match) => {
                        flag_details_map.insert(flag_key, FlagDetails::create(flag, &flag_match));
                    }
                    Err(e) => {
                        errors_while_computing_flags = true;
                        // TODO add posthog error tracking
                        error!(
                            "Error evaluating feature flag '{}' for distinct_id '{}': {:?}",
                            flag_key, self.distinct_id, e
                        );
                        let reason = parse_exception_for_prometheus_label(&e);
                        inc(
                            FLAG_EVALUATION_ERROR_COUNTER,
                            &[("reason".to_string(), reason.to_string())],
                            1,
                        );
                        flag_details_map.insert(flag_key, FlagDetails::create_error(flag, reason));
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
        }

        FlagsResponse::new(
            errors_while_computing_flags,
            flag_details_map,
            None,
            request_id,
        )
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

        match overrides {
            Some(props) => self
                .get_match(flag, Some(props), hash_key_overrides)
                .map(Some),
            None => Ok(None),
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
        person_property_overrides.as_ref().and_then(|overrides| {
            locally_computable_property_overrides(&Some(overrides.clone()), flag_property_filters)
        })
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
    fn is_condition_match(
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

            // Separate cohort and non-cohort filters
            let (cohort_filters, non_cohort_filters): (Vec<PropertyFilter>, Vec<PropertyFilter>) =
                flag_property_filters
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
            let person_properties = self.get_person_properties(
                property_overrides.clone(),
                super_condition.properties.as_deref().unwrap_or(&[]),
            )?;

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
            let group_key = self
                .group_type_mapping_cache
                .get_group_type_index_to_type_map()?
                .get(&group_type_index)
                .and_then(|group_type_name| self.groups.get(group_type_name))
                .and_then(|group_key_value| group_key_value.as_str())
                // NB: we currently use empty string ("") as the hashed identifier for group flags without a group key,
                // and I don't want to break parity with the old service since I don't want the hash values to change
                .unwrap_or("")
                .to_string();

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
    fn get_matching_variant(
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
                error!("Error fetching properties: {:?}", e);
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
                let group_key = group_key_value.as_str()?.to_string();
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
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::collections::HashMap;

    use crate::{
        flags::{
            flag_group_type_mapping::GroupTypeMappingCache,
            flag_models::{FlagFilters, MultivariateFlagOptions, MultivariateFlagVariant},
        },
        properties::property_models::OperatorType,
        utils::test_utils::{
            add_person_to_cohort, create_test_flag, get_person_id_by_distinct_id,
            insert_cohort_for_team_in_pg, insert_new_team_in_pg, insert_person_for_team_in_pg,
            setup_pg_reader_client, setup_pg_writer_client,
        },
    };

    #[tokio::test]
    async fn test_fetch_properties_from_pg_to_match() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));

        let team = insert_new_team_in_pg(reader.clone(), None)
            .await
            .expect("Failed to insert team in pg");

        let distinct_id = "user_distinct_id".to_string();
        insert_person_for_team_in_pg(reader.clone(), team.id, distinct_id.clone(), None)
            .await
            .expect("Failed to insert person");

        let not_matching_distinct_id = "not_matching_distinct_id".to_string();
        insert_person_for_team_in_pg(
            reader.clone(),
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
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None).unwrap();
        assert!(match_result.matches);
        assert_eq!(match_result.variant, None);

        // Matcher for a non-matching distinct_id
        let mut matcher = FeatureFlagMatcher::new(
            not_matching_distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None).unwrap();
        assert!(!match_result.matches);
        assert_eq!(match_result.variant, None);

        // Matcher for a distinct_id that does not exist
        let mut matcher = FeatureFlagMatcher::new(
            "other_distinct_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None).unwrap();

        // Expecting false for non-existent distinct_id
        assert!(!match_result.matches);
    }

    #[tokio::test]
    async fn test_person_property_overrides() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("override@example.com")),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let overrides = HashMap::from([("email".to_string(), json!("override@example.com"))]);

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader,
            writer,
            cohort_cache,
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };
        let result = matcher
            .evaluate_all_feature_flags(flags, Some(overrides), None, None, Uuid::new_v4())
            .await;
        assert!(!result.errors_while_computing_flags);
        assert_eq!(
            result.flags.get("test_flag").unwrap().to_value(),
            FlagValue::Boolean(true)
        );
    }

    #[tokio::test]
    async fn test_group_property_overrides() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "industry".to_string(),
                        value: Some(json!("tech")),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id);
        group_type_mapping_cache.init(reader.clone()).await.unwrap();

        let group_types_to_indexes = [("organization".to_string(), 1)].into_iter().collect();
        let indexes_to_types = [(1, "organization".to_string())].into_iter().collect();
        group_type_mapping_cache.set_test_mappings(group_types_to_indexes, indexes_to_types);

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
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            Some(groups),
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };
        let result = matcher
            .evaluate_all_feature_flags(flags, None, Some(group_overrides), None, Uuid::new_v4())
            .await;

        let legacy_response = LegacyFlagsResponse::from_response(result);
        assert!(!legacy_response.errors_while_computing_flags);
        assert_eq!(
            legacy_response.feature_flags.get("test_flag"),
            Some(&FlagValue::Boolean(true))
        );
    }

    #[tokio::test]
    async fn test_get_matching_variant_with_cache() {
        let flag = create_test_flag_with_variants(1);
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let mut group_type_mapping_cache = GroupTypeMappingCache::new(1);
        let group_types_to_indexes = [("group_type_1".to_string(), 1)].into_iter().collect();
        let indexes_to_types = [(1, "group_type_1".to_string())].into_iter().collect();
        group_type_mapping_cache.set_test_mappings(group_types_to_indexes, indexes_to_types);

        let groups = HashMap::from([("group_type_1".to_string(), json!("group_key_1"))]);

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            1,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            Some(groups),
        );
        let variant = matcher.get_matching_variant(&flag, None).unwrap();
        assert!(variant.is_some(), "No variant was selected");
        assert!(
            ["control", "test", "test2"].contains(&variant.unwrap().as_str()),
            "Selected variant is not one of the expected options"
        );
    }

    #[tokio::test]
    async fn test_get_matching_variant_with_db() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        let flag = create_test_flag_with_variants(team.id);

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id);
        group_type_mapping_cache.init(reader.clone()).await.unwrap();

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            None,
        );

        let variant = matcher.get_matching_variant(&flag, None).unwrap();
        assert!(variant.is_some());
        assert!(["control", "test", "test2"].contains(&variant.unwrap().as_str()));
    }

    #[tokio::test]
    async fn test_is_condition_match_empty_properties() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let flag = create_test_flag(
            Some(1),
            None,
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let condition = FlagPropertyGroup {
            variant: None,
            properties: Some(vec![]),
            rollout_percentage: Some(100.0),
        };

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            1,
            reader,
            writer,
            cohort_cache,
            None,
            None,
        );
        let (is_match, reason) = matcher
            .is_condition_match(&flag, &condition, None, None)
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
                groups: vec![FlagPropertyGroup {
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
                holdout_groups: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: false,
            version: Some(1),
            creation_context: None,
        }
    }

    #[tokio::test]
    async fn test_overrides_avoid_db_lookups() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("test@example.com")),
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
                holdout_groups: None,
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
            team.project_id,
            reader.clone(),
            writer.clone(),
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
                Uuid::new_v4(),
            )
            .await;

        let legacy_response = LegacyFlagsResponse::from_response(result);
        assert!(!legacy_response.errors_while_computing_flags);
        assert_eq!(
            legacy_response.feature_flags.get("test_flag"),
            Some(&FlagValue::Boolean(true))
        );

        let cache = &matcher.flag_evaluation_state;
        assert!(cache.person_properties.is_none());
    }

    #[tokio::test]
    async fn test_concurrent_flag_evaluation() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
        let flag = Arc::new(create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        ));

        let mut handles = vec![];
        for i in 0..100 {
            let flag_clone = flag.clone();
            let reader_clone = reader.clone();
            let writer_clone = writer.clone();
            let cohort_cache_clone = cohort_cache.clone();
            handles.push(tokio::spawn(async move {
                let matcher = FeatureFlagMatcher::new(
                    format!("test_user_{}", i),
                    team.id,
                    team.project_id,
                    reader_clone,
                    writer_clone,
                    cohort_cache_clone,
                    None,
                    None,
                );
                matcher.get_match(&flag_clone, None, None).unwrap()
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![
                        PropertyFilter {
                            key: "age".to_string(),
                            value: Some(json!(25)),
                            operator: Some(OperatorType::Gte),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
                        },
                        PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("example@domain.com")),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "user@example@domain.com", "age": 30})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_empty_hashed_identifier() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let flag = create_test_flag(
            Some(1),
            None,
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "".to_string(),
            1,
            1,
            reader,
            writer,
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_rollout_percentage() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let mut flag = create_test_flag(
            Some(1),
            None,
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(0.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            1,
            reader,
            writer,
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(!result.matches);

        // Now set the rollout percentage to 100%
        flag.filters.groups[0].rollout_percentage = Some(100.0);

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_uneven_variant_distribution() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
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
            1,
            reader,
            writer,
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
            let variant = matcher.get_matching_variant(&flag, None).unwrap();
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a person without properties
        insert_person_for_team_in_pg(reader.clone(), team.id, "test_user".to_string(), None)
            .await
            .unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("test@example.com")),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_malformed_property_data() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a person with malformed properties
        insert_person_for_team_in_pg(
            reader.clone(),
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
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "age".to_string(),
                        value: Some(json!(25)),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

        // The match should fail due to invalid data type
        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_evaluation_reasons() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let flag = create_test_flag(
            Some(1),
            None,
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            1,
            reader.clone(),
            writer.clone(),
            cohort_cache,
            None,
            None,
        );

        let (is_match, reason) = matcher
            .is_condition_match(&flag, &flag.filters.groups[0], None, None)
            .unwrap();

        assert!(is_match);
        assert_eq!(reason, FeatureFlagMatchReason::ConditionMatch);
    }

    #[tokio::test]
    async fn test_complex_conditions() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Complex Flag".to_string()),
            Some("complex_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("user1@example.com")),
                            operator: None,
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "age".to_string(),
                            value: Some(json!(30)),
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
                holdout_groups: None,
            }),
            Some(false),
            Some(true),
            Some(false),
        );

        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "user2@example.com", "age": 35})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache,
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_complex_cohort_conditions() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a cohort with complex conditions
        let cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
            team.id,
            None,
            json!({
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{
                                "key": "email",
                                "type": "person",
                                "value": "@posthog\\.com$",
                                "negation": false,
                                "operator": "regex"
                            }]
                        },
                        {
                            "type": "AND",
                            "values": [{
                                "key": "email",
                                "type": "person",
                                "value": ["fuziontech@gmail.com"],
                                "operator": "exact"
                            }]
                        },
                        {
                            "type": "AND",
                            "values": [{
                                "key": "distinct_id",
                                "type": "person",
                                "value": ["D_9eluZIT3gqjO9dJqo1aDeqTbAG4yLwXFhN0bz_Vfc"],
                                "operator": "exact"
                            }]
                        },
                        {
                            "type": "OR",
                            "values": [{
                                "key": "email",
                                "type": "person",
                                "value": ["neil@posthog.com"],
                                "negation": false,
                                "operator": "exact"
                            }]
                        },
                        {
                            "type": "OR",
                            "values": [{
                                "key": "email",
                                "type": "person",
                                "value": ["corywatilo@gmail.com"],
                                "negation": false,
                                "operator": "exact"
                            }]
                        },
                        {
                            "type": "OR",
                            "values": [{
                                "key": "email",
                                "type": "person",
                                "value": "@leads\\.io$",
                                "negation": false,
                                "operator": "regex"
                            }]
                        },
                        {
                            "type": "OR",
                            "values": [{
                                "key": "email",
                                "type": "person",
                                "value": "@desertcart\\.io$",
                                "negation": false,
                                "operator": "regex"
                            }]
                        }
                    ]
                }
            }),
            false,
        )
        .await
        .unwrap();

        // Test case 1: Should match - posthog.com email (AND condition)
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_user_1".to_string(),
            Some(json!({
                "email": "test@posthog.com",
                "distinct_id": "test_user_1"
            })),
        )
        .await
        .unwrap();

        // Test case 2: Should match - fuziontech@gmail.com (AND condition)
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_user_2".to_string(),
            Some(json!({
                "email": "fuziontech@gmail.com",
                "distinct_id": "test_user_2"
            })),
        )
        .await
        .unwrap();

        // Test case 3: Should match - specific distinct_id (AND condition)
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "D_9eluZIT3gqjO9dJqo1aDeqTbAG4yLwXFhN0bz_Vfc".to_string(),
            Some(json!({
                "email": "other@example.com",
                "distinct_id": "D_9eluZIT3gqjO9dJqo1aDeqTbAG4yLwXFhN0bz_Vfc"
            })),
        )
        .await
        .unwrap();

        // Test case 4: Should match - neil@posthog.com (OR condition)
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_user_4".to_string(),
            Some(json!({
                "email": "neil@posthog.com",
                "distinct_id": "test_user_4"
            })),
        )
        .await
        .unwrap();

        // Test case 5: Should match - @leads.io email (OR condition with regex)
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_user_5".to_string(),
            Some(json!({
                "email": "test@leads.io",
                "distinct_id": "test_user_5"
            })),
        )
        .await
        .unwrap();

        // Test case 6: Should NOT match - random email
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_user_6".to_string(),
            Some(json!({
                "email": "random@example.com",
                "distinct_id": "test_user_6"
            })),
        )
        .await
        .unwrap();

        // Create a feature flag using this cohort and verify matches
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort_row.id)),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        // Test each case
        for (user_id, should_match) in [
            ("test_user_1", true),                                 // @posthog.com
            ("test_user_2", true),                                 // fuziontech@gmail.com
            ("D_9eluZIT3gqjO9dJqo1aDeqTbAG4yLwXFhN0bz_Vfc", true), // specific distinct_id
            ("test_user_4", true),                                 // neil@posthog.com
            ("test_user_5", true),                                 // @leads.io
            ("test_user_6", false),                                // random@example.com
        ] {
            let mut matcher = FeatureFlagMatcher::new(
                user_id.to_string(),
                team.id,
                team.project_id,
                reader.clone(),
                writer.clone(),
                cohort_cache.clone(),
                None,
                None,
            );

            matcher
                .prepare_flag_evaluation_state(&[flag.clone()])
                .await
                .unwrap();

            let result = matcher.get_match(&flag, None, None).unwrap();
            assert_eq!(
                result.matches,
                should_match,
                "User {} should{} match",
                user_id,
                if should_match { "" } else { " not" }
            );
        }
    }

    #[tokio::test]
    async fn test_super_condition_matches_boolean() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Super Condition Flag".to_string()),
            Some("super_condition_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("fake@posthog.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(0.0),
                        variant: None,
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("test@posthog.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    },
                    FlagPropertyGroup {
                        properties: None,
                        rollout_percentage: Some(50.0),
                        variant: None,
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "is_enabled".to_string(),
                        value: Some(json!(["true"])),
                        operator: Some(OperatorType::Exact),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }]),
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_id".to_string(),
            Some(json!({"email": "test@posthog.com", "is_enabled": true})),
        )
        .await
        .unwrap();

        insert_person_for_team_in_pg(reader.clone(), team.id, "lil_id".to_string(), None)
            .await
            .unwrap();

        insert_person_for_team_in_pg(reader.clone(), team.id, "another_id".to_string(), None)
            .await
            .unwrap();

        let mut matcher_test_id = FeatureFlagMatcher::new(
            "test_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_example_id = FeatureFlagMatcher::new(
            "lil_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_another_id = FeatureFlagMatcher::new(
            "another_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher_test_id
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        matcher_example_id
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        matcher_another_id
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result_test_id = matcher_test_id.get_match(&flag, None, None).unwrap();
        let result_example_id = matcher_example_id.get_match(&flag, None, None).unwrap();
        let result_another_id = matcher_another_id.get_match(&flag, None, None).unwrap();

        assert!(result_test_id.matches);
        assert!(result_test_id.reason == FeatureFlagMatchReason::SuperConditionValue);
        assert!(result_example_id.matches);
        assert!(result_example_id.reason == FeatureFlagMatchReason::ConditionMatch);
        assert!(!result_another_id.matches);
        assert!(result_another_id.reason == FeatureFlagMatchReason::OutOfRolloutBound);
    }

    #[tokio::test]
    async fn test_super_condition_matches_string() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        insert_person_for_team_in_pg(
            reader.clone(),
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
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("fake@posthog.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(0.0),
                        variant: None,
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("test@posthog.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    },
                    FlagPropertyGroup {
                        properties: None,
                        rollout_percentage: Some(50.0),
                        variant: None,
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "is_enabled".to_string(),
                        value: Some(json!("true")),
                        operator: Some(OperatorType::Exact),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }]),
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut matcher = FeatureFlagMatcher::new(
            "test_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
        assert_eq!(result.reason, FeatureFlagMatchReason::SuperConditionValue);
        assert_eq!(result.condition_index, Some(0));
    }

    #[tokio::test]
    async fn test_super_condition_matches_and_false() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_id".to_string(),
            Some(json!({"email": "test@posthog.com", "is_enabled": true})),
        )
        .await
        .unwrap();

        insert_person_for_team_in_pg(reader.clone(), team.id, "another_id".to_string(), None)
            .await
            .unwrap();

        insert_person_for_team_in_pg(reader.clone(), team.id, "lil_id".to_string(), None)
            .await
            .unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Super Condition Flag".to_string()),
            Some("super_condition_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("fake@posthog.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(0.0),
                        variant: None,
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("test@posthog.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    },
                    FlagPropertyGroup {
                        properties: None,
                        rollout_percentage: Some(50.0),
                        variant: None,
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "is_enabled".to_string(),
                        value: Some(json!(false)),
                        operator: Some(OperatorType::Exact),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }]),
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut matcher_test_id = FeatureFlagMatcher::new(
            "test_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_example_id = FeatureFlagMatcher::new(
            "lil_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_another_id = FeatureFlagMatcher::new(
            "another_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher_test_id
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        matcher_example_id
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        matcher_another_id
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result_test_id = matcher_test_id.get_match(&flag, None, None).unwrap();
        let result_example_id = matcher_example_id.get_match(&flag, None, None).unwrap();
        let result_another_id = matcher_another_id.get_match(&flag, None, None).unwrap();

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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a cohort with the condition that matches the test user's properties
        let cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
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
            reader.clone(),
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
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort_row.id)),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_not_in_cohort_matching() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a cohort with a condition that does not match the test user's properties
        let cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
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
            reader.clone(),
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
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort_row.id)),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_not_in_cohort_matching_user_in_cohort() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a cohort with a condition that matches the test user's properties
        let cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
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
            reader.clone(),
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
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort_row.id)),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

        // The user matches the cohort, but the flag is set to NotIn, so it should evaluate to false
        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_cohort_dependent_on_another_cohort() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a base cohort
        let base_cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
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
            reader.clone(),
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
            reader.clone(),
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
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(dependent_cohort_row.id)),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_in_cohort_matching_user_not_in_cohort() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a cohort with a condition that does not match the test user's properties
        let cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
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
            reader.clone(),
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
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort_row.id)),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

        // The user does not match the cohort, and the flag is set to In, so it should evaluate to false
        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_static_cohort_matching_user_in_cohort() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            reader.clone(),
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
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "static@user.com"})),
        )
        .await
        .unwrap();

        // Retrieve the person's ID
        let person_id = get_person_id_by_distinct_id(reader.clone(), team.id, &distinct_id)
            .await
            .unwrap();

        // Associate the person with the static cohort
        add_person_to_cohort(reader.clone(), person_id, cohort.id)
            .await
            .unwrap();

        // Define a flag with an 'In' cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort.id)),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(
            result.matches,
            "User should match the static cohort and flag"
        );
    }

    #[tokio::test]
    async fn test_static_cohort_matching_user_not_in_cohort() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            reader.clone(),
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
            reader.clone(),
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
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort.id)),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(
            !result.matches,
            "User should not match the static cohort and flag"
        );
    }

    #[tokio::test]
    async fn test_static_cohort_not_in_matching_user_not_in_cohort() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            reader.clone(),
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
            reader.clone(),
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
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort.id)),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(
            result.matches,
            "User not in the static cohort should match the 'NotIn' flag"
        );
    }

    #[tokio::test]
    async fn test_static_cohort_not_in_matching_user_in_cohort() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            reader.clone(),
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
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "innotinstatic@user.com"})),
        )
        .await
        .unwrap();

        // Retrieve the person's ID
        let person_id = get_person_id_by_distinct_id(reader.clone(), team.id, &distinct_id)
            .await
            .unwrap();

        // Associate the person with the static cohort
        add_person_to_cohort(reader.clone(), person_id, cohort.id)
            .await
            .unwrap();

        // Define a flag with a 'NotIn' cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort.id)),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(
            !result.matches,
            "User in the static cohort should not match the 'NotIn' flag"
        );
    }

    #[tokio::test]
    async fn test_evaluate_feature_flags_with_experience_continuity() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
        let distinct_id = "user3".to_string();

        // Insert person
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "user3@example.com"})),
        )
        .await
        .unwrap();

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id);
        group_type_mapping_cache.init(reader.clone()).await.unwrap();

        // Create flag with experience continuity
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("flag_continuity".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("user3@example.com")),
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
                holdout_groups: None,
            }),
            None,
            None,
            Some(true),
        );

        // Set hash key override
        set_feature_flag_hash_key_overrides(
            writer.clone(),
            team.id,
            vec![distinct_id.clone()],
            team.project_id,
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
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            None,
            None,
            Some("hash_key_continuity".to_string()),
            Uuid::new_v4(),
        )
        .await;

        let legacy_response = LegacyFlagsResponse::from_response(result);
        assert!(
            !legacy_response.errors_while_computing_flags,
            "No error should occur"
        );
        assert_eq!(
            legacy_response.feature_flags.get("flag_continuity"),
            Some(&FlagValue::Boolean(true)),
            "Flag should be evaluated as true with continuity"
        );
    }

    #[tokio::test]
    async fn test_evaluate_feature_flags_with_continuity_missing_override() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
        let distinct_id = "user4".to_string();

        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "user4@example.com"})),
        )
        .await
        .unwrap();

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id);
        group_type_mapping_cache.init(reader.clone()).await.unwrap();

        // Create flag with experience continuity
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("flag_continuity_missing".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("user4@example.com")),
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
                holdout_groups: None,
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
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            None,
        )
        .evaluate_all_feature_flags(flags, None, None, None, Uuid::new_v4())
        .await;

        assert!(result.flags.get("flag_continuity_missing").unwrap().enabled);

        let legacy_response = LegacyFlagsResponse::from_response(result);
        assert!(
            !legacy_response.errors_while_computing_flags,
            "No error should occur"
        );
        assert_eq!(
            legacy_response.feature_flags.get("flag_continuity_missing"),
            Some(&FlagValue::Boolean(true)),
            "Flag should be evaluated as true even without continuity override"
        );
    }

    #[tokio::test]
    async fn test_evaluate_all_feature_flags_mixed_continuity() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
        let distinct_id = "user5".to_string();

        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "user5@example.com"})),
        )
        .await
        .unwrap();

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id);
        group_type_mapping_cache.init(reader.clone()).await.unwrap();

        // Create flag with continuity
        let flag_continuity = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("flag_continuity_mix".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("user5@example.com")),
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
                holdout_groups: None,
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
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "age".to_string(),
                        value: Some(json!(30)),
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
                holdout_groups: None,
            }),
            None,
            None,
            Some(false),
        );

        // Set hash key override for the continuity flag
        set_feature_flag_hash_key_overrides(
            writer.clone(),
            team.id,
            vec![distinct_id.clone()],
            team.project_id,
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
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            Some(HashMap::from([("age".to_string(), json!(35))])),
            None,
            Some("hash_key_mixed".to_string()),
            Uuid::new_v4(),
        )
        .await;

        let legacy_response = LegacyFlagsResponse::from_response(result);
        assert!(
            !legacy_response.errors_while_computing_flags,
            "No error should occur"
        );
        assert_eq!(
            legacy_response.feature_flags.get("flag_continuity_mix"),
            Some(&FlagValue::Boolean(true)),
            "Continuity flag should be evaluated as true"
        );
        assert_eq!(
            legacy_response.feature_flags.get("flag_no_continuity_mix"),
            Some(&FlagValue::Boolean(true)),
            "Non-continuity flag should be evaluated based on properties"
        );
    }

    #[tokio::test]
    async fn test_variant_override_in_condition() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
        let distinct_id = "test_user".to_string();

        // Insert a person with properties that will match our condition
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "test@example.com"})),
        )
        .await
        .unwrap();

        // Create a flag with multiple variants and a condition with a variant override
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("test_flag".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("test@example.com")),
                        operator: None,
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: Some("control".to_string()), // Override to always show "control" variant
                }],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            name: Some("Control".to_string()),
                            key: "control".to_string(),
                            rollout_percentage: 25.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Test".to_string()),
                            key: "test".to_string(),
                            rollout_percentage: 25.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Test2".to_string()),
                            key: "test2".to_string(),
                            rollout_percentage: 50.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        // The condition matches and has a variant override, so it should return "control"
        // regardless of what the hash-based variant computation would return
        assert!(result.matches);
        assert_eq!(result.variant, Some("control".to_string()));

        // Now test with an invalid variant override
        let flag_invalid_override = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("test_flag_invalid".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("test@example.com")),
                        operator: None,
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: Some("nonexistent_variant".to_string()), // Override with invalid variant
                }],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            name: Some("Control".to_string()),
                            key: "control".to_string(),
                            rollout_percentage: 25.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Test".to_string()),
                            key: "test".to_string(),
                            rollout_percentage: 75.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag_invalid_override.clone()])
            .await
            .unwrap();

        let result_invalid = matcher
            .get_match(&flag_invalid_override, None, None)
            .unwrap();

        // The condition matches but has an invalid variant override,
        // so it should fall back to hash-based variant computation
        assert!(result_invalid.matches);
        assert!(result_invalid.variant.is_some()); // Will be either "control" or "test" based on hash
    }

    #[tokio::test]
    async fn test_feature_flag_with_holdout_filter() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // example_id is outside 70% holdout
        let _person1 = insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "example_id".to_string(),
            Some(json!({"$some_prop": 5})),
        )
        .await
        .unwrap();

        // example_id2 is within 70% holdout
        let _person2 = insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "example_id2".to_string(),
            Some(json!({"$some_prop": 5})),
        )
        .await
        .unwrap();

        let multivariate_json = MultivariateFlagOptions {
            variants: vec![
                MultivariateFlagVariant {
                    key: "first-variant".to_string(),
                    name: Some("First Variant".to_string()),
                    rollout_percentage: 50.0,
                },
                MultivariateFlagVariant {
                    key: "second-variant".to_string(),
                    name: Some("Second Variant".to_string()),
                    rollout_percentage: 25.0,
                },
                MultivariateFlagVariant {
                    key: "third-variant".to_string(),
                    name: Some("Third Variant".to_string()),
                    rollout_percentage: 25.0,
                },
            ],
        };

        let flag_with_holdout = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Flag with holdout".to_string()),
            Some("flag-with-gt-filter".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$some_prop".to_string(),
                        value: Some(json!(4)),
                        operator: Some(OperatorType::Gt),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                holdout_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(70.0),
                    variant: Some("holdout".to_string()),
                }]),
                multivariate: Some(multivariate_json.clone()),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            Some(true),
            None,
        );

        let other_flag_with_holdout = create_test_flag(
            Some(2),
            Some(team.id),
            Some("Other flag with holdout".to_string()),
            Some("other-flag-with-gt-filter".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$some_prop".to_string(),
                        value: Some(json!(4)),
                        operator: Some(OperatorType::Gt),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                holdout_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(70.0),
                    variant: Some("holdout".to_string()),
                }]),
                multivariate: Some(multivariate_json.clone()),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            Some(true),
            None,
        );

        let flag_without_holdout = create_test_flag(
            Some(3),
            Some(team.id),
            Some("Flag".to_string()),
            Some("other-flag-without-holdout-with-gt-filter".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$some_prop".to_string(),
                        value: Some(json!(4)),
                        operator: Some(OperatorType::Gt),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                holdout_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(0.0),
                    variant: Some("holdout".to_string()),
                }]),
                multivariate: Some(multivariate_json),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            Some(true),
            None,
        );

        // regular flag evaluation when outside holdout
        let mut matcher = FeatureFlagMatcher::new(
            "example_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag_with_holdout.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag_with_holdout, None, None).unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("second-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);

        // Test inside holdout behavior - should get holdout variant override
        let mut matcher2 = FeatureFlagMatcher::new(
            "example_id2".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher2
            .prepare_flag_evaluation_state(&[
                flag_with_holdout.clone(),
                flag_without_holdout.clone(),
                other_flag_with_holdout.clone(),
            ])
            .await
            .unwrap();

        let result = matcher2.get_match(&flag_with_holdout, None, None).unwrap();

        assert!(result.matches);
        assert_eq!(result.variant, Some("holdout".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::HoldoutConditionValue);

        // same should hold true for a different feature flag when within holdout
        let result = matcher2
            .get_match(&other_flag_with_holdout, None, None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("holdout".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::HoldoutConditionValue);

        // Test with matcher1 (outside holdout) to verify different variants
        let result = matcher
            .get_match(&other_flag_with_holdout, None, None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("third-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);

        // when holdout exists but is zero, should default to regular flag evaluation
        let result = matcher
            .get_match(&flag_without_holdout, None, None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("second-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);

        let result = matcher2
            .get_match(&flag_without_holdout, None, None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("second-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);
    }

    #[tokio::test]
    async fn test_variants() {
        // Ported from posthog/test/test_feature_flag.py test_variants
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        let flag = FeatureFlag {
            id: 1,
            team_id: team.id,
            name: Some("Beta feature".to_string()),
            key: "beta-feature".to_string(),
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: None,
                    variant: None,
                }],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            name: Some("First Variant".to_string()),
                            key: "first-variant".to_string(),
                            rollout_percentage: 50.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Second Variant".to_string()),
                            key: "second-variant".to_string(),
                            rollout_percentage: 25.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Third Variant".to_string()),
                            key: "third-variant".to_string(),
                            rollout_percentage: 25.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: false,
            version: Some(1),
            creation_context: None,
        };

        // Test user "11" - should get first-variant
        let matcher = FeatureFlagMatcher::new(
            "11".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );
        let result = matcher.get_match(&flag, None, None).unwrap();
        assert_eq!(
            result,
            FeatureFlagMatch {
                matches: true,
                variant: Some("first-variant".to_string()),
                reason: FeatureFlagMatchReason::ConditionMatch,
                condition_index: Some(0),
                payload: None,
            }
        );

        // Test user "example_id" - should get second-variant
        let matcher = FeatureFlagMatcher::new(
            "example_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );
        let result = matcher.get_match(&flag, None, None).unwrap();
        assert_eq!(
            result,
            FeatureFlagMatch {
                matches: true,
                variant: Some("second-variant".to_string()),
                reason: FeatureFlagMatchReason::ConditionMatch,
                condition_index: Some(0),
                payload: None,
            }
        );

        // Test user "3" - should get third-variant
        let matcher = FeatureFlagMatcher::new(
            "3".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );
        let result = matcher.get_match(&flag, None, None).unwrap();
        assert_eq!(
            result,
            FeatureFlagMatch {
                matches: true,
                variant: Some("third-variant".to_string()),
                reason: FeatureFlagMatchReason::ConditionMatch,
                condition_index: Some(0),
                payload: None,
            }
        );
    }

    #[tokio::test]
    async fn test_static_cohort_evaluation_skips_dependency_graph() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            reader.clone(),
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
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "static@user.com"})),
        )
        .await
        .unwrap();

        // Get person ID and add to cohort
        let person_id = get_person_id_by_distinct_id(reader.clone(), team.id, &distinct_id)
            .await
            .unwrap();
        add_person_to_cohort(reader.clone(), person_id, cohort.id)
            .await
            .unwrap();

        // Define a flag that references the static cohort
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort.id)),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        // This should not throw CohortNotFound because we skip dependency graph evaluation for static cohorts
        let result = matcher.get_match(&flag, None, None);
        assert!(result.is_ok(), "Should not throw CohortNotFound error");

        let match_result = result.unwrap();
        assert!(match_result.matches, "User should match the static cohort");
    }

    #[tokio::test]
    async fn test_no_person_id_with_overrides() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("test@example.com")),
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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let person_property_overrides =
            HashMap::from([("email".to_string(), json!("test@example.com"))]);

        let mut matcher = FeatureFlagMatcher::new(
            "nonexistent_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
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
                Uuid::new_v4(),
            )
            .await;

        // Should succeed because we have overrides
        assert!(!result.errors_while_computing_flags);
        let flag_details = result.flags.get("test_flag").unwrap();
        assert!(flag_details.enabled);
    }

    #[tokio::test]
    async fn test_complex_super_condition_matching() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("complex_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("@storytell.ai")),
                            operator: Some(OperatorType::Icontains),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!([
                                "simone.demarchi@outlook.com",
                                "djokovic.dav@gmail.com",
                                "dario.passarello@gmail.com",
                                "matt.amick@purplewave.com"
                            ])),
                            operator: Some(OperatorType::Exact),
                            prop_type: "person".to_string(),
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("@posthog.com")),
                            operator: Some(OperatorType::Icontains),
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
                super_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$feature_enrollment/artificial-hog".to_string(),
                        value: Some(json!(["true"])),
                        operator: Some(OperatorType::Exact),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }]),
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        // Test case 1: User with super condition property set to true
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "super_user".to_string(),
            Some(json!({
                "email": "random@example.com",
                "$feature_enrollment/artificial-hog": true
            })),
        )
        .await
        .unwrap();

        // Test case 2: User with matching email but no super condition
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "posthog_user".to_string(),
            Some(json!({
                "email": "test@posthog.com",
                "$feature_enrollment/artificial-hog": false
            })),
        )
        .await
        .unwrap();

        // Test case 3: User with neither super condition nor matching email
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "regular_user".to_string(),
            Some(json!({
                "email": "regular@example.com"
            })),
        )
        .await
        .unwrap();

        // Test super condition user
        let mut matcher = FeatureFlagMatcher::new(
            "super_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();
        assert!(result.matches, "Super condition user should match");
        assert_eq!(
            result.reason,
            FeatureFlagMatchReason::SuperConditionValue,
            "Match reason should be SuperConditionValue"
        );

        // Test PostHog user
        let mut matcher = FeatureFlagMatcher::new(
            "posthog_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();
        assert!(!result.matches, "PostHog user should not match");
        assert_eq!(
            result.reason,
            FeatureFlagMatchReason::SuperConditionValue,
            "Match reason should be SuperConditionValue"
        );

        // Test regular user
        let mut matcher = FeatureFlagMatcher::new(
            "regular_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();
        assert!(!result.matches, "Regular user should not match");
        assert_eq!(
            result.reason,
            FeatureFlagMatchReason::NoConditionMatch,
            "Match reason should be NoConditionMatch"
        );
    }
}
