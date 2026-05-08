use crate::api::errors::FlagError;
use crate::api::types::{FlagDetails, FlagValue, FlagsResponse, FromFeatureAndMatch};
use crate::cohorts::cohort_cache_manager::CohortCacheManager;
use crate::cohorts::cohort_models::{Cohort, CohortId};
use crate::cohorts::cohort_operations::{apply_cohort_membership_logic, evaluate_dynamic_cohorts};
use crate::cohorts::membership::{CohortMembershipProvider, NoOpCohortMembershipProvider};
use crate::database::PostgresRouter;
use crate::flags::flag_group_type_mapping::{
    GroupTypeCacheManager, GroupTypeIndex, GroupTypeMapping,
};
use crate::flags::flag_match_reason::FeatureFlagMatchReason;
use crate::flags::flag_matching_utils::{
    calculate_hash, fetch_and_locally_cache_all_relevant_properties,
    get_feature_flag_hash_key_overrides, match_flag_value_to_flag_filter,
    populate_missing_initial_properties, set_feature_flag_hash_key_overrides,
    should_write_hash_key_override,
};
use crate::flags::flag_models::{
    FeatureFlag, FeatureFlagId, FeatureFlagList, FlagFilters, FlagPropertyGroup,
};
use crate::flags::flag_operations::flags_require_db_preparation;
use crate::handler::canonical_log::{install_rayon_canonical_log, take_rayon_canonical_log};
use crate::handler::with_canonical_log;
use crate::metrics::consts::{
    DB_PERSON_AND_GROUP_PROPERTIES_READS_COUNTER, FLAG_BATCH_EVALUATION_COUNTER,
    FLAG_BATCH_EVALUATION_TIME, FLAG_BATCH_SIZE, FLAG_COHORT_SOURCE_COUNTER,
    FLAG_DB_PROPERTIES_FETCH_TIME, FLAG_EVALUATE_ALL_CONDITIONS_TIME,
    FLAG_EVALUATION_ERROR_COUNTER, FLAG_EVALUATION_TIME, FLAG_EXPERIENCE_CONTINUITY_OPTIMIZED,
    FLAG_EXPERIENCE_CONTINUITY_REQUESTS_COUNTER, FLAG_GET_MATCH_TIME, FLAG_GROUP_CACHE_FETCH_TIME,
    FLAG_GROUP_DB_FETCH_TIME, FLAG_HASH_KEY_PROCESSING_TIME, FLAG_HASH_KEY_WRITES_COUNTER,
    FLAG_REALTIME_COHORT_QUERY_ERROR_COUNTER, FLAG_REALTIME_COHORT_QUERY_TIME,
    PROPERTY_CACHE_HITS_COUNTER, PROPERTY_CACHE_MISSES_COUNTER,
};
use crate::properties::property_matching::match_property;
use crate::properties::property_models::{PropertyFilter, PropertyType};
use crate::rayon_dispatcher::RayonDispatcher;
use crate::utils::graph_utils::PrecomputedDependencyGraph;
use anyhow::Result;
use common_metrics::{histogram, inc, timing_guard};
use common_types::collections::HashMapExt;
use common_types::{PersonId, TeamId};
use rayon::prelude::*;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tracing::{error, instrument, warn};
use uuid::Uuid;

const DEFAULT_PARALLEL_EVAL_THRESHOLD: usize = 100;

/// Parameters for feature flag evaluation with various override options
#[derive(Debug, Default)]
pub struct FlagEvaluationOverrides {
    pub person_property_overrides: Option<HashMap<String, Value>>,
    pub group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    pub hash_key_overrides: Option<HashMap<String, String>>,
    pub hash_key_override_error: bool,
    /// The request's anon_distinct_id, used as a fallback for EEC flags when no DB override exists
    pub request_hash_key_override: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EvaluationType {
    Sequential,
    Parallel,
}

impl EvaluationType {
    pub const fn as_str(self) -> &'static str {
        match self {
            EvaluationType::Sequential => "sequential",
            EvaluationType::Parallel => "parallel",
        }
    }

    /// Promote evaluation type across dependency levels:
    /// None → Sequential, None → Parallel, Sequential → Parallel.
    /// Parallel is sticky — once set, it never demotes back to Sequential.
    pub fn promote(current: Option<Self>, level_type: Self) -> Option<Self> {
        match (current, level_type) {
            (_, Self::Parallel) => Some(Self::Parallel),
            (None, Self::Sequential) => Some(Self::Sequential),
            (current, Self::Sequential) => current,
        }
    }
}

impl std::fmt::Display for EvaluationType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

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

    /// Creates a match result for flags with missing dependencies.
    /// These flags evaluate to `false` (fail closed) with the `MissingDependency` reason.
    pub fn missing_dependency() -> Self {
        Self {
            matches: false,
            variant: None,
            reason: FeatureFlagMatchReason::MissingDependency,
            condition_index: None,
            payload: None,
        }
    }
}

/// Tracks person property state through the evaluation lifecycle.
///
/// Combines fetch status with property data so that impossible states (e.g. "fetched"
/// but no properties) are unrepresentable. When request overrides cover all needed keys,
/// DB prep is skipped and this stays `Skipped`. When DB prep runs, properties are stored
/// directly in the `Fetched` variant.
#[derive(Clone, Debug, Default)]
pub(crate) enum PersonPropertyState {
    /// DB prep has not yet run (initial state)
    #[default]
    Pending,
    /// DB prep was skipped because request overrides covered all needed property keys
    Skipped,
    /// DB prep ran and populated person properties
    Fetched(HashMap<String, Value>),
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
    /// The person UUID, needed for realtime cohort membership lookups
    person_uuid: Option<Uuid>,
    /// Person property fetch state: pending, skipped, or fetched (with property data)
    person_property_state: PersonPropertyState,
    /// Properties for each group type involved in flag evaluation
    group_properties: HashMap<GroupTypeIndex, HashMap<String, Value>>,
    /// Cohorts for the current request, shared via `Arc` either from the
    /// preloaded hypercache slice or wrapped from a `CohortCacheManager`
    /// fetch.
    cohorts: Option<Arc<[Cohort]>>,
    /// Cache of cohort membership results (both static and realtime) to avoid repeated lookups.
    /// Static results come from `posthog_cohortpeople`, realtime results from `cohort_membership`.
    /// The two sources produce disjoint key sets partitioned by `CohortType`.
    cohort_matches: Option<HashMap<CohortId, bool>>,
    /// Cache of flag evaluation results to avoid repeated DB lookups
    flag_evaluation_results: HashMap<FeatureFlagId, FlagValue>,
}

impl FlagEvaluationState {
    pub fn get_person_id(&self) -> Option<PersonId> {
        self.person_id
    }

    pub fn get_person_properties(&self) -> Option<&HashMap<String, Value>> {
        match &self.person_property_state {
            PersonPropertyState::Fetched(props) => Some(props),
            _ => None,
        }
    }

    pub fn get_group_properties(&self) -> &HashMap<GroupTypeIndex, HashMap<String, Value>> {
        &self.group_properties
    }

    pub fn get_cohort_matches(&self) -> Option<&HashMap<CohortId, bool>> {
        self.cohort_matches.as_ref()
    }

    pub fn get_person_uuid(&self) -> Option<Uuid> {
        self.person_uuid
    }

    pub fn set_person_id(&mut self, id: PersonId) {
        self.person_id = Some(id);
    }

    pub fn set_person_uuid(&mut self, uuid: Uuid) {
        self.person_uuid = Some(uuid);
    }

    pub fn set_person_properties(&mut self, properties: HashMap<String, Value>) {
        self.person_property_state = PersonPropertyState::Fetched(properties);
    }

    pub fn skip_person_properties(&mut self) {
        self.person_property_state = PersonPropertyState::Skipped;
    }

    pub fn set_cohorts(&mut self, cohorts: Arc<[Cohort]>) {
        self.cohorts = Some(cohorts);
    }

    pub fn set_group_properties(
        &mut self,
        group_type_index: GroupTypeIndex,
        properties: HashMap<String, Value>,
    ) {
        self.group_properties.insert(group_type_index, properties);
    }

    pub fn set_cohort_matches(&mut self, matches: HashMap<CohortId, bool>) {
        self.cohort_matches = Some(matches);
    }

    /// Merge additional cohort membership results into the existing map.
    /// Used to add realtime cohort results after static results are already set.
    pub fn merge_cohort_matches(&mut self, additional: HashMap<CohortId, bool>) {
        match &mut self.cohort_matches {
            Some(existing) => existing.extend(additional),
            None => self.cohort_matches = Some(additional),
        }
    }

    pub fn add_flag_evaluation_result(&mut self, flag_id: FeatureFlagId, flag_value: FlagValue) {
        self.flag_evaluation_results.insert(flag_id, flag_value);
    }
}

static EMPTY_PROPERTY_MAP: std::sync::LazyLock<HashMap<String, Value>> =
    std::sync::LazyLock::new(HashMap::new);

/// Bundles references to the property maps and aggregation mode needed during
/// condition matching. A condition may reference both person and group properties
/// (mixed targeting), so this struct carries both sources and routes each filter
/// to the correct one.
pub(crate) struct PropertyContext<'a> {
    pub person_properties: Option<&'a HashMap<String, Value>>,
    pub group_properties: &'a HashMap<GroupTypeIndex, HashMap<String, Value>>,
    pub aggregation: Option<GroupTypeIndex>,
}

impl PropertyContext<'_> {
    /// Resolves the correct property map for a filter based on its type. Person filters
    /// use person properties, group filters use the group properties for the filter's
    /// `group_type_index`. Falls back to aggregation mode for legacy filters without
    /// an explicit type distinction.
    pub fn resolve_for_filter(&self, filter: &PropertyFilter) -> &HashMap<String, Value> {
        match filter.prop_type {
            PropertyType::Person => self.person_properties.unwrap_or(&*EMPTY_PROPERTY_MAP),
            PropertyType::Group => {
                let gti = filter.group_type_index.or(self.aggregation);
                gti.and_then(|idx| self.group_properties.get(&idx))
                    .unwrap_or(&*EMPTY_PROPERTY_MAP)
            }
            PropertyType::Cohort | PropertyType::Flag => match self.aggregation {
                Some(gti) => self
                    .group_properties
                    .get(&gti)
                    .unwrap_or(&*EMPTY_PROPERTY_MAP),
                None => self.person_properties.unwrap_or(&*EMPTY_PROPERTY_MAP),
            },
        }
    }
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
    /// Optional device identifier for device-level bucketing
    pub device_id: Option<String>,
    /// Team ID for scoping flag evaluations
    pub team_id: TeamId,
    /// Router for database connections across persons/non-persons pools
    pub router: PostgresRouter,
    /// Cache manager for cohort definitions and memberships
    pub cohort_cache: Arc<CohortCacheManager>,
    /// Shared in-process cache for group type mappings
    group_type_cache: Arc<GroupTypeCacheManager>,
    /// Lazily populated mapping for the current team (fetched via group_type_cache)
    group_type_mapping: Option<GroupTypeMapping>,
    /// State maintained during flag evaluation, including cached DB lookups
    pub(crate) flag_evaluation_state: FlagEvaluationState,
    /// Group key mappings for group-based flag evaluation
    /// Maps group type name to the group key (identifier customer supplies for the group)
    /// ex. "project" → "123"
    ///     "organization" → "456"
    ///     "instance" → "789"
    ///     "customer" → "101"
    ///     "team" → "112"
    groups: HashMap<String, Value>,
    /// Flag count threshold for switching from sequential to parallel evaluation.
    /// Configured via PARALLEL_EVAL_THRESHOLD env var in production.
    parallel_eval_threshold: usize,
    /// Dispatcher for bounded-concurrency Rayon batch evaluation.
    /// `None` in tests that don't exercise the parallel path.
    rayon_dispatcher: Option<RayonDispatcher>,
    /// When true, skip all writes to PostgreSQL and Redis.
    skip_writes: bool,
    /// Flag IDs that should be skipped during evaluation.
    /// Populated once per request from `FeatureFlagList::filtered_out_flag_ids`.
    pub(crate) filtered_out_flag_ids: HashSet<i32>,
    /// Provider for realtime/behavioral cohort membership lookups.
    /// Queries the behavioral cohorts database for cohorts with CohortType::Realtime or Behavioral.
    cohort_membership_provider: Arc<dyn CohortMembershipProvider>,
    /// Whether to enable realtime cohort evaluation.
    /// When false, realtime cohorts are treated as non-members.
    enable_realtime_cohort_evaluation: bool,
    /// Cohort definitions preloaded from the flags hypercache.
    /// When present, scoped to only the cohorts referenced by flags (including transitive deps),
    /// so the matcher skips the CohortCacheManager PG query entirely.
    /// `None` means no preloaded data (PG fallback or old cache) — use CohortCacheManager.
    preloaded_cohorts: Option<Arc<[Cohort]>>,
    /// Whether to include detailed condition analysis in flag evaluation results.
    detailed_analysis: bool,
    /// Whether to only use person properties from request payload, ignoring database properties.
    only_use_override_person_properties: bool,
}

/// Lightweight snapshot of a flag's identity fields, saved before moving
/// flags into the Rayon pool. Used to reconstruct per-flag error results
/// if the rayon task panics.
struct FlagSnapshot {
    key: String,
    id: FeatureFlagId,
    version: Option<i32>,
}

impl FlagSnapshot {
    pub fn from_flag(flag: &FeatureFlag) -> Self {
        FlagSnapshot {
            key: flag.key.clone(),
            id: flag.id,
            version: flag.version,
        }
    }
}

impl FeatureFlagMatcher {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        distinct_id: String,
        device_id: Option<String>,
        team_id: TeamId,
        router: PostgresRouter,
        cohort_cache: Arc<CohortCacheManager>,
        group_type_cache: Arc<GroupTypeCacheManager>,
        groups: Option<HashMap<String, Value>>,
    ) -> Self {
        FeatureFlagMatcher {
            distinct_id,
            device_id,
            team_id,
            router,
            cohort_cache,
            group_type_cache,
            group_type_mapping: None,
            groups: groups.unwrap_or_default(),
            flag_evaluation_state: FlagEvaluationState::default(),
            cohort_membership_provider: Arc::new(NoOpCohortMembershipProvider),
            parallel_eval_threshold: DEFAULT_PARALLEL_EVAL_THRESHOLD,
            rayon_dispatcher: None,
            skip_writes: false,
            filtered_out_flag_ids: HashSet::new(),
            enable_realtime_cohort_evaluation: false,
            preloaded_cohorts: None,
            detailed_analysis: false,
            only_use_override_person_properties: false,
        }
    }

    pub fn with_parallel_eval_threshold(mut self, threshold: usize) -> Self {
        self.parallel_eval_threshold = threshold;
        self
    }

    pub fn with_rayon_dispatcher(mut self, dispatcher: RayonDispatcher) -> Self {
        self.rayon_dispatcher = Some(dispatcher);
        self
    }

    pub fn with_skip_writes(mut self, skip_writes: bool) -> Self {
        self.skip_writes = skip_writes;
        self
    }

    pub fn with_cohort_membership_provider(
        mut self,
        provider: Arc<dyn CohortMembershipProvider>,
    ) -> Self {
        self.cohort_membership_provider = provider;
        self
    }

    pub fn with_realtime_cohort_evaluation(mut self, enable: bool) -> Self {
        self.enable_realtime_cohort_evaluation = enable;
        self
    }

    pub fn with_detailed_analysis(mut self, detailed_analysis: bool) -> Self {
        self.detailed_analysis = detailed_analysis;
        self
    }

    pub fn with_only_use_override_person_properties(mut self, only_use_override: bool) -> Self {
        self.only_use_override_person_properties = only_use_override;
        self
    }

    /// Evaluates all feature flags for the current matcher context.
    ///
    /// ## Arguments
    ///
    /// * `feature_flags` - The list of feature flags to evaluate.
    /// * `person_property_overrides` - Any overrides for person properties.
    /// * `group_property_overrides` - Any overrides for group properties.
    /// * `hash_key_override` - Optional hash key overrides for experience continuity.
    /// * `optimize_experience_continuity_lookups` - When true, skip lookups for flags that don't need them.
    ///
    /// ## Returns
    ///
    /// * `FlagsResponse` - The result containing flag evaluations and any errors.
    #[instrument(skip_all, fields(team_id = %self.team_id, distinct_id = %self.distinct_id, flags_len = feature_flags.flags.len()))]
    #[allow(clippy::too_many_arguments)]
    pub async fn evaluate_all_feature_flags(
        &mut self,
        feature_flags: FeatureFlagList,
        person_property_overrides: Option<HashMap<String, Value>>,
        group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
        hash_key_override: Option<String>, // Aka $anon_distinct_id
        request_id: Uuid,
        flag_keys: Option<Vec<String>>,
        optimize_experience_continuity_lookups: bool,
    ) -> Result<FlagsResponse, FlagError> {
        let eval_timer = common_metrics::timing_guard(FLAG_EVALUATION_TIME, &[]);

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, flag_keys.as_deref());

        self.filtered_out_flag_ids = feature_flags.filtered_out_flag_ids;
        self.preloaded_cohorts = feature_flags.cohorts;

        let PrecomputedDependencyGraph {
            error_count,
            has_cycle_errors,
            evaluation_stages,
            flags_with_missing_deps,
        } = precomputed;

        if error_count > 0 {
            with_canonical_log(|log| log.dependency_graph_errors = error_count);
        }

        // Compute experience continuity stats from the filtered graph.
        // This considers all flags that will actually be evaluated (including dependencies).
        let (experience_continuity_count, any_flag_needs_override) = {
            let mut continuity_count = 0;
            let mut needs_override = false;

            for flag in evaluation_stages.iter().flatten() {
                if !self.filtered_out_flag_ids.contains(&flag.id)
                    && flag.has_experience_continuity()
                {
                    continuity_count += 1;
                    if !needs_override && flag.needs_hash_key_override() {
                        needs_override = true;
                    }
                }
            }

            (continuity_count, needs_override)
        };

        // Log the experience continuity count from the filtered graph
        with_canonical_log(|log| log.flags_experience_continuity = experience_continuity_count);

        let has_experience_continuity = experience_continuity_count > 0;

        // Determine if we need to do the hash key override lookup.
        // In legacy mode (optimization disabled), we always do the lookup if any flag has continuity.
        // In optimized mode, we only do it if any flag actually needs it.
        let do_hash_key_lookup = if optimize_experience_continuity_lookups {
            any_flag_needs_override
        } else {
            has_experience_continuity
        };

        // A request is optimizable when it has experience continuity flags but none require the lookup
        let request_is_optimizable = has_experience_continuity && !any_flag_needs_override;

        // Track optimization metric: status="skipped" when we skip, "eligible" when we could have
        if request_is_optimizable {
            let status = if optimize_experience_continuity_lookups {
                "skipped"
            } else {
                "eligible"
            };

            inc(
                FLAG_EXPERIENCE_CONTINUITY_OPTIMIZED,
                &[
                    ("status".to_string(), status.to_string()),
                    ("team_id".to_string(), self.team_id.to_string()),
                ],
                1,
            );
        }

        // Record when the optimization actually skips the lookup
        if request_is_optimizable && optimize_experience_continuity_lookups {
            with_canonical_log(|log| log.hash_key_override_status = Some("skipped"));
        }

        // Clone the request's hash_key_override before passing it to process_hash_key_override_if_needed
        // since we also need it for the FlagEvaluationOverrides struct
        let request_hash_key_override = hash_key_override.clone();

        // Process any hash key overrides
        let (hash_key_overrides, flag_hash_key_override_error) = self
            .process_hash_key_override_if_needed(do_hash_key_lookup, hash_key_override)
            .await;

        let overrides = FlagEvaluationOverrides {
            person_property_overrides,
            group_property_overrides,
            hash_key_overrides,
            hash_key_override_error: flag_hash_key_override_error,
            request_hash_key_override,
        };

        let flags_response = self
            .evaluate_flags_with_overrides(
                overrides,
                request_id,
                evaluation_stages,
                flags_with_missing_deps,
            )
            .await?;

        let has_errors = flag_hash_key_override_error
            || flags_response.errors_while_computing_flags
            || has_cycle_errors;

        eval_timer
            .label("outcome", if has_errors { "error" } else { "success" })
            .fin();

        Ok(FlagsResponse::new(
            has_errors,
            flags_response.flags,
            None,
            request_id,
        ))
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
    #[instrument(skip_all, fields(team_id = %self.team_id, distinct_id = %self.distinct_id))]
    async fn process_hash_key_override(
        &self,
        hash_key: String,
        target_distinct_ids: Vec<String>,
    ) -> (Option<HashMap<String, String>>, bool) {
        let should_write = match should_write_hash_key_override(
            &self.router,
            self.team_id,
            self.distinct_id.clone(),
            hash_key.clone(),
        )
        .await
        {
            Ok(should_write) => should_write,
            Err(e) => {
                error!(
                    "Failed to check if hash key override should be written for team {} distinct_id {}: {:?}",
                    self.team_id, self.distinct_id, e
                );
                inc(
                    FLAG_EVALUATION_ERROR_COUNTER,
                    &[("reason".to_string(), e.evaluation_error_code())],
                    1,
                );
                return (None, true);
            }
        };

        let mut writing_hash_key_override = false;

        if should_write {
            if self.skip_writes {
                tracing::debug!(
                    team_id = self.team_id,
                    distinct_id = %self.distinct_id,
                    "SKIP_WRITES: skipping hash key override write to PostgreSQL"
                );
            } else {
                if let Err(e) = set_feature_flag_hash_key_overrides(
                    // NB: this is the only method that writes to the database
                    &self.router,
                    self.team_id,
                    target_distinct_ids.clone(),
                    hash_key.clone(),
                )
                .await
                {
                    error!("Failed to set feature flag hash key overrides for team {} distinct_id {} hash_key {}: {:?}", self.team_id, self.distinct_id, hash_key, e);
                    inc(
                        FLAG_EVALUATION_ERROR_COUNTER,
                        &[("reason".to_string(), e.evaluation_error_code())],
                        1,
                    );
                    return (None, true);
                }
                writing_hash_key_override = true;
            }
        }

        inc(
            FLAG_HASH_KEY_WRITES_COUNTER,
            &[(
                "successful_write".to_string(),
                writing_hash_key_override.to_string(),
            )],
            1,
        );

        // When we're writing a hash_key_override, we query the main database (writer), not the replica (reader)
        // This is because we need to make sure the write is successful before we read it back
        // to avoid read-after-write consistency issues with database replication lag
        let database_for_reading = if writing_hash_key_override {
            self.router.get_persons_writer().clone()
        } else {
            self.router.get_persons_reader().clone()
        };

        match get_feature_flag_hash_key_overrides(
            database_for_reading,
            self.team_id,
            target_distinct_ids,
        )
        .await
        {
            Ok(overrides) => (Some(overrides), false),
            Err(e) => {
                error!("Failed to get feature flag hash key overrides for team {} distinct_id {}: {:?}", self.team_id, self.distinct_id, e);
                inc(
                    FLAG_EVALUATION_ERROR_COUNTER,
                    &[("reason".to_string(), e.evaluation_error_code())],
                    1,
                );
                (None, true)
            }
        }
    }

    /// Evaluates cohort filters using cached membership results (both static and realtime)
    /// and evaluates dynamic cohorts based on the provided properties.
    pub fn evaluate_cohort_filters(
        &self,
        cohort_property_filters: &[&PropertyFilter],
        target_properties: &HashMap<String, Value>,
        cohorts: Arc<[Cohort]>,
    ) -> Result<bool, FlagError> {
        // Track cohort evaluations in canonical log
        with_canonical_log(|log| log.eval.cohorts_evaluated += cohort_property_filters.len());

        // Get cached cohort results (static + realtime, merged during prepare_flag_evaluation_state)
        let cached_matches = match self.flag_evaluation_state.get_cohort_matches() {
            Some(matches) => matches.clone(),
            None => HashMap::new(), // Happens when targeting an anonymous user with no person record
        };

        let mut cohort_matches = cached_matches;

        // For any cohorts not yet evaluated (i.e., dynamic ones), evaluate them
        for filter in cohort_property_filters {
            let cohort_id = filter
                .get_cohort_id()
                .ok_or(FlagError::CohortFiltersParsingError)?;

            if !cohort_matches.contains_key(&cohort_id) {
                let current_matches = cohort_matches.clone();
                let match_result = evaluate_dynamic_cohorts(
                    cohort_id,
                    target_properties,
                    &cohorts,
                    &current_matches,
                )?;
                cohort_matches.insert(cohort_id, match_result);
            }
        }

        // Apply cohort membership logic (IN|NOT_IN) to the cohort match results
        apply_cohort_membership_logic(cohort_property_filters, &cohort_matches)
    }

    /// Evaluates feature flags with property and hash key overrides.
    ///
    /// Takes pre-computed evaluation stages which should already be filtered by flag_keys if needed.
    /// The stages determine which flags are evaluated and in what order.
    pub async fn evaluate_flags_with_overrides(
        &mut self,
        overrides: FlagEvaluationOverrides,
        request_id: Uuid,
        evaluation_stages: Vec<Vec<FeatureFlag>>,
        flags_with_missing_deps: HashSet<i32>,
    ) -> Result<FlagsResponse, FlagError> {
        let mut errors_while_computing_flags = overrides.hash_key_override_error;
        let mut evaluated_flags_map = HashMap::new();

        // Collect flags from evaluation stages for preparation steps
        let flags: Vec<&FeatureFlag> = evaluation_stages.iter().flatten().collect();

        // Handle hash key override errors by creating error responses for flags that need experience continuity
        if overrides.hash_key_override_error && overrides.hash_key_overrides.is_none() {
            let hash_key_error = FlagError::HashKeyOverrideError;
            for flag in flags.iter().filter(|flag| {
                !self.filtered_out_flag_ids.contains(&flag.id)
                    && flag.ensure_experience_continuity.unwrap_or(false)
            }) {
                evaluated_flags_map.insert(
                    flag.key.clone(),
                    FlagDetails::create_error(flag, &hash_key_error, None),
                );
            }
        }

        // Step 1: Initialize group type mappings if needed
        errors_while_computing_flags |= self.initialize_group_type_mappings_if_needed(&flags).await;

        // Step 2: Prepare evaluation state for flags requiring DB properties
        let db_prep_errors = self
            .prepare_evaluation_state_if_needed(
                &flags,
                &overrides.person_property_overrides,
                &mut evaluated_flags_map,
            )
            .await;
        errors_while_computing_flags |= db_prep_errors;

        // Pre-seed filtered-out flags as false so dependency conditions like
        // `flag_evaluates_to=false` can match against them.
        for &flag_id in &self.filtered_out_flag_ids {
            self.flag_evaluation_state
                .add_flag_evaluation_result(flag_id, FlagValue::Boolean(false));
        }

        // Step 3: Evaluate flags stage by stage in dependency order
        for stage in evaluation_stages {
            let (level_evaluated_flags_map, level_errors) = self
                .evaluate_flags_in_level(
                    stage,
                    &mut evaluated_flags_map,
                    &overrides.person_property_overrides,
                    &overrides.group_property_overrides,
                    &overrides.hash_key_overrides,
                    &overrides.request_hash_key_override,
                    &flags_with_missing_deps,
                )
                .await?;
            errors_while_computing_flags |= level_errors;
            evaluated_flags_map.extend(level_evaluated_flags_map);
        }

        Ok(FlagsResponse::new(
            errors_while_computing_flags,
            evaluated_flags_map,
            None,
            request_id,
        ))
    }

    /// Prepares evaluation state for flags that require database properties.
    /// Returns true if there were errors during preparation.
    #[instrument(skip_all, fields(team_id = %self.team_id, distinct_id = %self.distinct_id))]
    async fn prepare_evaluation_state_if_needed(
        &mut self,
        flags: &[&FeatureFlag],
        person_property_overrides: &Option<HashMap<String, Value>>,
        evaluated_flags_map: &mut HashMap<String, FlagDetails>,
    ) -> bool {
        let flags_requiring_db_preparation = flags_require_db_preparation(
            flags,
            person_property_overrides
                .as_ref()
                .unwrap_or(&HashMap::new()),
            &self.filtered_out_flag_ids,
        );

        if flags_requiring_db_preparation.is_empty() || self.only_use_override_person_properties {
            self.flag_evaluation_state.skip_person_properties();
            return false;
        }

        match self
            .prepare_flag_evaluation_state(flags_requiring_db_preparation.as_slice())
            .await
        {
            Ok(_) => false,
            Err(e) => {
                self.handle_db_preparation_error(
                    &flags_requiring_db_preparation,
                    &e,
                    evaluated_flags_map,
                );
                true
            }
        }
    }

    /// Handles errors during database preparation by creating error responses for affected flags.
    fn handle_db_preparation_error(
        &self,
        flags_requiring_db_preparation: &[&FeatureFlag],
        error: &FlagError,
        evaluated_flags_map: &mut HashMap<String, FlagDetails>,
    ) {
        evaluated_flags_map.extend(flags_requiring_db_preparation.iter().map(|flag| {
            (
                flag.key.clone(),
                FlagDetails::create_error(flag, error, None),
            )
        }));

        error!(
            "Error preparing flag evaluation state for team {} distinct_id {}: {:?}",
            self.team_id, self.distinct_id, error
        );

        let reason = error.evaluation_error_code();
        inc(
            FLAG_EVALUATION_ERROR_COUNTER,
            &[("reason".to_string(), reason)],
            1,
        );
    }

    /// Evaluates a set of flags with a combination of property overrides and DB properties
    ///
    /// This function is designed to be used as part of a level-based evaluation strategy
    /// (e.g., Kahn's algorithm) for handling flag dependencies.
    ///
    /// Dispatches between sequential and parallel evaluation based on flag count.
    /// Sequential: borrows flags by reference (zero-copy).
    /// Parallel: moves owned flags into a rayon task via oneshot channel.
    #[allow(clippy::too_many_arguments)]
    #[instrument(skip_all, fields(team_id = %self.team_id, distinct_id = %self.distinct_id))]
    async fn evaluate_flags_in_level(
        &mut self,
        flags: Vec<FeatureFlag>,
        evaluated_flags_map: &mut HashMap<String, FlagDetails>,
        person_property_overrides: &Option<HashMap<String, Value>>,
        group_property_overrides: &Option<HashMap<String, HashMap<String, Value>>>,
        hash_key_overrides: &Option<HashMap<String, String>>,
        request_hash_key_override: &Option<String>,
        flags_with_missing_deps: &HashSet<i32>,
    ) -> Result<(HashMap<String, FlagDetails>, bool), FlagError> {
        let mut errors_while_computing_flags = false;
        let mut level_evaluated_flags_map = HashMap::new();

        let flags_to_evaluate: Vec<FeatureFlag> = flags
            .into_iter()
            .filter(|flag| {
                !flag.deleted
                    && flag.active
                    && !self.filtered_out_flag_ids.contains(&flag.id)
                    && !evaluated_flags_map.contains_key(&flag.key)
            })
            .collect();

        let eval_type = if flags_to_evaluate.len() >= self.parallel_eval_threshold {
            EvaluationType::Parallel
        } else {
            EvaluationType::Sequential
        };

        // Record evaluation type in canonical log for E2E latency metrics.
        // Skip if no flags to evaluate (all deleted, filtered out, or already evaluated) — lets the
        // metric label stay None → "none" rather than incorrectly reporting Sequential.
        if !flags_to_evaluate.is_empty() {
            with_canonical_log(|log| {
                log.evaluation_type = EvaluationType::promote(log.evaluation_type, eval_type);
            });
        }

        let labels = [("evaluation_type".to_string(), eval_type.to_string())];
        histogram(FLAG_BATCH_SIZE, &labels, flags_to_evaluate.len() as f64);
        inc(FLAG_BATCH_EVALUATION_COUNTER, &labels, 1);
        let _batch_timer = timing_guard(FLAG_BATCH_EVALUATION_TIME, &labels);

        let flag_get_match_timer = timing_guard(FLAG_GET_MATCH_TIME, &[]);

        match eval_type {
            EvaluationType::Sequential => {
                flags_to_evaluate.iter().for_each(|flag| {
                    let result = self.evaluate_single_flag(
                        flag,
                        person_property_overrides,
                        group_property_overrides,
                        flags_with_missing_deps,
                        hash_key_overrides,
                        request_hash_key_override,
                    );
                    self.process_flag_result(
                        flag,
                        &result,
                        &mut level_evaluated_flags_map,
                        &mut errors_while_computing_flags,
                        person_property_overrides,
                    );
                });
            }
            EvaluationType::Parallel => {
                let results = self
                    .evaluate_batch_parallel(
                        flags_to_evaluate,
                        person_property_overrides,
                        group_property_overrides,
                        flags_with_missing_deps,
                        hash_key_overrides,
                        request_hash_key_override,
                    )
                    .await?;

                for (flag, result) in &results {
                    self.process_flag_result(
                        flag,
                        result,
                        &mut level_evaluated_flags_map,
                        &mut errors_while_computing_flags,
                        person_property_overrides,
                    );
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

        Ok((level_evaluated_flags_map, errors_while_computing_flags))
    }

    /// Process a single flag evaluation result: update evaluation state, record metrics, and
    /// insert into the level map.
    fn process_flag_result(
        &mut self,
        flag: &FeatureFlag,
        result: &Result<FeatureFlagMatch, FlagError>,
        level_evaluated_flags_map: &mut HashMap<String, FlagDetails>,
        errors_while_computing_flags: &mut bool,
        person_property_overrides: &Option<HashMap<String, Value>>,
    ) {
        match result {
            Ok(flag_match) => {
                self.flag_evaluation_state
                    .add_flag_evaluation_result(flag.id, flag_match.get_flag_value());
                let flag_details = if self.detailed_analysis {
                    // Use merged person properties (DB + overrides) for condition analysis
                    let merged_person_props = self
                        .get_person_properties(person_property_overrides.as_ref())
                        .ok();
                    FlagDetails::create_with_analysis(
                        flag,
                        flag_match,
                        true,
                        merged_person_props.as_ref(),
                    )
                } else {
                    FlagDetails::create(flag, flag_match)
                };
                level_evaluated_flags_map.insert(flag.key.clone(), flag_details);
            }
            Err(e) => {
                *errors_while_computing_flags = true;
                with_canonical_log(|log| log.flags_errored += 1);

                if let FlagError::DependencyNotFound(dependency_type, dependency_id) = e {
                    warn!(
                        "Feature flag '{}' targeting deleted {} with id {} for distinct_id '{}': {:?}",
                        flag.key, dependency_type, dependency_id, self.distinct_id, e
                    );
                } else {
                    error!(
                        "Error evaluating feature flag '{}' for distinct_id '{}': {:?}",
                        flag.key, self.distinct_id, e
                    );
                }

                let reason = e.evaluation_error_code();
                inc(
                    FLAG_EVALUATION_ERROR_COUNTER,
                    &[("reason".to_string(), reason)],
                    1,
                );
                level_evaluated_flags_map
                    .insert(flag.key.clone(), FlagDetails::create_error(flag, e, None));
            }
        }
    }

    /// Resolves group property overrides for a specific group type index by mapping
    /// the index to the group type name and looking up the corresponding overrides.
    fn resolve_group_overrides<'a>(
        &self,
        group_type_index: GroupTypeIndex,
        group_property_overrides: Option<&'a HashMap<String, HashMap<String, Value>>>,
    ) -> Option<&'a HashMap<String, Value>> {
        let mapping = self.group_type_mapping.as_ref()?;
        let index_to_type_map = mapping.group_indexes_to_types();
        let group_type = index_to_type_map.get(&group_type_index)?;
        let group_overrides = group_property_overrides?;
        group_overrides.get(group_type)
    }

    /// Pushes CPU-bound flag evaluation onto the Rayon pool via [`RayonDispatcher`],
    /// so the calling Tokio worker thread is free to serve other requests while
    /// evaluation runs. The dispatcher bounds how many batches can be in-flight
    /// simultaneously, preventing unbounded queue growth and preserving per-batch
    /// work-stealing parallelism.
    async fn evaluate_batch_parallel(
        &self,
        flags_to_evaluate: Vec<FeatureFlag>,
        person_property_overrides: &Option<HashMap<String, Value>>,
        group_property_overrides: &Option<HashMap<String, HashMap<String, Value>>>,
        flags_with_missing_deps: &HashSet<i32>,
        hash_key_overrides: &Option<HashMap<String, String>>,
        request_hash_key_override: &Option<String>,
    ) -> Result<Vec<(FeatureFlag, Result<FeatureFlagMatch, FlagError>)>, FlagError> {
        let matcher = self.clone();
        let missing_deps = flags_with_missing_deps.clone();
        let person_overrides = person_property_overrides.clone();
        let group_overrides = group_property_overrides.clone();
        let hash_overrides = hash_key_overrides.clone();
        let req_hash_override = request_hash_key_override.clone();

        // Save lightweight snapshots before moving flags into rayon.
        // If the rayon task panics, we use these to construct per-flag error results
        // instead of silently dropping flags from the response.
        let team_id = self.team_id;
        let flag_snapshots: Vec<_> = flags_to_evaluate
            .iter()
            .map(FlagSnapshot::from_flag)
            .collect();

        // Each rayon thread accumulates evaluation counters in a thread-local
        // FlagsCanonicalLogLine. After evaluation, the per-flag deltas are
        // returned alongside each flag result and merged into the request's
        // tokio task-local canonical log.
        let work = move || {
            flags_to_evaluate
                .into_par_iter()
                .map(|flag| {
                    let _guard = install_rayon_canonical_log();
                    let result = matcher.evaluate_single_flag(
                        &flag,
                        &person_overrides,
                        &group_overrides,
                        &missing_deps,
                        &hash_overrides,
                        &req_hash_override,
                    );
                    let delta = take_rayon_canonical_log();
                    (flag, result, delta)
                })
                .collect::<Vec<_>>()
        };

        let result = match &self.rayon_dispatcher {
            Some(dispatcher) => dispatcher
                .try_spawn(work)
                .await
                .map_err(|t| FlagError::RayonSemaphoreTimeout(t.waited.as_millis() as u64))?,
            None => {
                // Fallback for tests: unbounded dispatch (no semaphore).
                let (tx, rx) = tokio::sync::oneshot::channel();
                rayon::spawn(move || {
                    if let Ok(value) = std::panic::catch_unwind(std::panic::AssertUnwindSafe(work))
                    {
                        drop(tx.send(value));
                    }
                });
                rx.await.ok()
            }
        };

        let results_with_deltas = result.unwrap_or_else(|| {
            error!("Rayon parallel evaluation task was dropped (likely panicked)");
            Self::build_panic_fallback(flag_snapshots, team_id)
                .into_iter()
                .map(|(flag, result)| (flag, result, None))
                .collect()
        });

        Ok(results_with_deltas
            .into_iter()
            .map(|(flag, result, delta)| {
                if let Some(delta) = delta {
                    with_canonical_log(|log| log.merge_rayon_delta(&delta));
                }
                (flag, result)
            })
            .collect())
    }

    /// Constructs per-flag error results from lightweight snapshots when the
    /// rayon task panics and drops the oneshot sender.
    fn build_panic_fallback(
        snapshots: Vec<FlagSnapshot>,
        team_id: TeamId,
    ) -> Vec<(FeatureFlag, Result<FeatureFlagMatch, FlagError>)> {
        snapshots
            .into_iter()
            .map(|snapshot| {
                let stub = FeatureFlag {
                    id: snapshot.id,
                    key: snapshot.key,
                    active: true,
                    version: snapshot.version,
                    filters: FlagFilters::default(),
                    team_id,
                    name: None,
                    deleted: false,
                    ensure_experience_continuity: None,
                    evaluation_runtime: None,
                    evaluation_tags: None,
                    bucketing_identifier: None,
                };
                (stub, Err(FlagError::BatchEvaluationPanicked))
            })
            .collect()
    }

    fn evaluate_single_flag(
        &self,
        flag: &FeatureFlag,
        person_property_overrides: &Option<HashMap<String, Value>>,
        group_property_overrides: &Option<HashMap<String, HashMap<String, Value>>>,
        flags_with_missing_deps: &HashSet<i32>,
        hash_key_overrides: &Option<HashMap<String, String>>,
        request_hash_key_override: &Option<String>,
    ) -> Result<FeatureFlagMatch, FlagError> {
        if flags_with_missing_deps.contains(&flag.id) {
            return Ok(FeatureFlagMatch::missing_dependency());
        }

        self.get_match(
            flag,
            person_property_overrides.as_ref(),
            group_property_overrides.as_ref(),
            hash_key_overrides.as_ref(),
            request_hash_key_override,
        )
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
        person_property_overrides: Option<&HashMap<String, Value>>,
        group_property_overrides: Option<&HashMap<String, HashMap<String, Value>>>,
        hash_key_overrides: Option<&HashMap<String, String>>,
        request_hash_key_override: &Option<String>,
    ) -> Result<FeatureFlagMatch, FlagError> {
        // Seed with the lowest-priority "could not evaluate" reason so any real evaluation
        // result outranks it via `get_highest_priority_match_evaluation`. NoGroupType is
        // the floor: a pure-group flag whose only condition is skipped for missing context
        // still surfaces NoGroupType, while a person condition that runs and reports
        // NoConditionMatch or OutOfRolloutBound takes precedence in mixed-targeting flags.
        let mut highest_match = FeatureFlagMatchReason::NoGroupType;
        let mut highest_index = None;
        let mut had_skipped_group_conditions = false;

        // Lazily compute properties per aggregation type. Person and group properties are
        // cached separately so conditions with different aggregation modes can share them.
        let mut cached_person_properties: Option<HashMap<String, Value>> = None;
        let mut cached_group_properties: HashMap<i32, HashMap<String, Value>> = HashMap::new();

        // Evaluate feature enrollment (early access features) first.
        // Enrollment is a person-level concept — always uses person properties, even for
        // group-based flags. The API validates that group-based flags cannot have early access
        // features attached.
        //
        // New format: `feature_enrollment: true` — the enrollment property key is derived
        // from the flag key as `$feature_enrollment/{flag_key}`.
        // Legacy format: `super_groups` array with explicit property filters.
        // New format takes precedence when both are present.
        if flag.filters.feature_enrollment == Some(true) {
            let enrollment_key = FlagFilters::enrollment_key(&flag.key);
            let person_properties = self.get_person_properties(person_property_overrides)?;

            if let Some(v) = person_properties.get(&enrollment_key) {
                let is_match = v == "true" || v == &Value::Bool(true);
                let payload = self.get_matching_payload(None, flag);
                return Ok(FeatureFlagMatch {
                    matches: is_match,
                    variant: None,
                    reason: FeatureFlagMatchReason::SuperConditionValue,
                    condition_index: Some(0),
                    payload,
                });
            }
            // Person doesn't have enrollment property set — fall through to normal conditions
        } else if let Some(super_groups) = &flag.filters.super_groups {
            if let Some(super_condition) = super_groups.first() {
                // Legacy path: evaluate super_groups property filters directly.
                if super_condition
                    .properties
                    .as_ref()
                    .is_some_and(|p| !p.is_empty())
                {
                    if cached_person_properties.is_none() {
                        cached_person_properties =
                            Some(self.get_person_properties(person_property_overrides)?);
                    }
                    let super_condition_evaluation = self.is_super_condition_match(
                        flag,
                        cached_person_properties.as_ref().unwrap(),
                        hash_key_overrides,
                        request_hash_key_override,
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
                    }
                    // if no match, continue to normal conditions
                }
            }
        }

        // Match for holdout super condition
        // TODO: Flags shouldn't have both super_groups and holdout
        // TODO: Validate only multivariant flags to have holdout groups. I could make this implicit by reusing super_groups but
        // this will shoot ourselves in the foot when we extend early access to support variants as well.
        // TODO: Validate holdout variant should have 0% default rollout %?
        // TODO: All this validation we need to do suggests the modelling is imperfect here. Carrying forward for now, we'll only enable
        // in beta, and potentially rework representation before rolling out to everyone. Probably the problem is holdout groups are an
        // experiment level concept that applies across experiments, and we are creating a feature flag level primitive to handle it.
        // Validating things like the variant name is the same across all flags, rolled out to 0%, has the same correct conditions is a bit of
        // a pain here. But I'm not sure if feature flags should indeed know all this info. It's fine for them to just work with what they're given.
        if flag.filters.holdout.is_some() {
            let (is_match, holdout_value, evaluation_reason) =
                self.is_holdout_condition_match(flag, request_hash_key_override)?;
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
        let conditions: Vec<(usize, &FlagPropertyGroup)> =
            flag.get_conditions().iter().enumerate().collect();

        let condition_timer = common_metrics::timing_guard(FLAG_EVALUATE_ALL_CONDITIONS_TIME, &[]);
        for (index, condition) in conditions {
            // Each condition resolves its own aggregation, falling back to the flag-level
            // value for backwards compatibility with flags that predate per-condition aggregation.
            let aggregation = condition.effective_aggregation(flag.get_group_type_index());

            // Device_id bucketing only applies to person-aggregated conditions. For mixed
            // flags, group-aggregated conditions can still match even without a device_id.
            if aggregation.is_none() {
                use crate::flags::flag_models::BucketingIdentifier;

                if flag.get_bucketing_identifier() == BucketingIdentifier::DeviceId
                    && self
                        .device_id
                        .as_ref()
                        .is_none_or(|device_id| device_id.is_empty())
                {
                    with_canonical_log(|log| {
                        tracing::warn!(
                            flag_key = %flag.key,
                            team_id = %flag.team_id,
                            condition_index = %index,
                            lib = log.lib,
                            lib_version = log.lib_version.as_deref(),
                            "Person condition uses device_id bucketing but no device_id provided, skipping"
                        );
                    });
                    let (new_highest_match, new_highest_index) = self
                        .get_highest_priority_match_evaluation(
                            highest_match.clone(),
                            highest_index,
                            FeatureFlagMatchReason::OutOfRolloutBound,
                            Some(index),
                        );
                    highest_match = new_highest_match;
                    highest_index = new_highest_index;
                    continue;
                }
                if flag.get_bucketing_identifier() == BucketingIdentifier::DeviceId {
                    with_canonical_log(|log| log.eval.flags_device_id_bucketing += 1);
                }
            }

            // For group-aggregated conditions, verify we have the group key. If not, this
            // condition can't match — log a warning and continue to the next condition.
            // This checks the group key directly rather than calling hashed_identifier,
            // which will be called again later in check_rollout/get_matching_variant.
            if let Some(group_type_index) = aggregation {
                let has_group_key = self
                    .group_type_mapping
                    .as_ref()
                    .and_then(|m| m.group_indexes_to_types().get(&group_type_index))
                    .and_then(|name| self.groups.get(name))
                    .is_some_and(|v| match v {
                        Value::String(s) => !s.is_empty(),
                        Value::Number(_) => true,
                        _ => false,
                    });
                if !has_group_key {
                    warn!(
                        flag_key = %flag.key,
                        team_id = %flag.team_id,
                        condition_index = %index,
                        "Condition uses group aggregation but group type not provided in evaluation context, skipping"
                    );
                    // Record this as a NoGroupType reason but continue to next condition.
                    // Track that we skipped a group condition so the final result can
                    // surface a richer description when person conditions also didn't match.
                    had_skipped_group_conditions = true;
                    let (new_highest_match, new_highest_index) = self
                        .get_highest_priority_match_evaluation(
                            highest_match.clone(),
                            highest_index,
                            FeatureFlagMatchReason::NoGroupType,
                            Some(index),
                        );
                    highest_match = new_highest_match;
                    highest_index = new_highest_index;
                    continue;
                }
            }

            // Lazily compute properties based on what the condition's filters reference.
            // A condition may have person filters, group filters, or both (mixed targeting).
            // Properties are cached per type so conditions sharing a property source reuse them.
            if Self::condition_needs_properties(condition) {
                let (needs_person, needed_group_types) =
                    Self::condition_property_type_needs(condition, aggregation);

                if needs_person && cached_person_properties.is_none() {
                    cached_person_properties =
                        Some(self.get_person_properties(person_property_overrides)?);
                }

                for &gti in &needed_group_types {
                    if let std::collections::hash_map::Entry::Vacant(e) =
                        cached_group_properties.entry(gti)
                    {
                        let group_overrides =
                            self.resolve_group_overrides(gti, group_property_overrides);
                        let group_props = self.get_group_properties(gti, group_overrides)?;
                        e.insert(group_props);
                    }
                }
            }

            let property_context = PropertyContext {
                person_properties: cached_person_properties.as_ref(),
                group_properties: &cached_group_properties,
                aggregation,
            };

            let (is_match, reason) = self.is_condition_match(
                flag,
                condition,
                &property_context,
                hash_key_overrides,
                request_hash_key_override,
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
                        self.get_matching_variant(
                            flag,
                            aggregation,
                            hash_key_overrides,
                            request_hash_key_override,
                        )?
                    }
                } else {
                    // No override, use computed variant
                    self.get_matching_variant(
                        flag,
                        aggregation,
                        hash_key_overrides,
                        request_hash_key_override,
                    )?
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

        // When person conditions were evaluated (and didn't match) but group conditions
        // were skipped because the caller didn't provide the required group type, upgrade
        // the reason to carry a richer description. The API code still serializes as
        // "no_condition_match" for backward compatibility, but the description tells the
        // caller about the skipped group conditions.
        if highest_match == FeatureFlagMatchReason::NoConditionMatch && had_skipped_group_conditions
        {
            highest_match = FeatureFlagMatchReason::NoConditionMatchGroupsNotEvaluated;
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
    /// Evaluates a specific condition to determine if it should be enabled.
    /// If the condition has no property filters, performs a rollout check only.
    /// Otherwise, checks if the provided properties satisfy the condition's filters.
    ///
    /// Each filter is matched against the correct property source based on its type:
    /// person filters use person properties, group filters use the group properties
    /// for that filter's `group_type_index`. This enables mixed targeting where a
    /// single condition combines person and group filters with independent rollout.
    pub(crate) fn is_condition_match(
        &self,
        feature_flag: &FeatureFlag,
        condition: &FlagPropertyGroup,
        property_context: &PropertyContext,
        hash_key_overrides: Option<&HashMap<String, String>>,
        request_hash_key_override: &Option<String>,
    ) -> Result<(bool, FeatureFlagMatchReason), FlagError> {
        let rollout_percentage = condition.rollout_percentage.unwrap_or(100.0);

        if let Some(flag_property_filters) = &condition.properties {
            if flag_property_filters.is_empty() {
                return self.check_rollout(
                    feature_flag,
                    rollout_percentage,
                    property_context.aggregation,
                    hash_key_overrides,
                    request_hash_key_override,
                );
            }

            // Single-pass evaluation: flag-value and property filters are evaluated in Vec order
            // and short-circuit immediately on mismatch. Cohort filters (the most expensive)
            // are deferred and batch-evaluated after the loop to avoid unnecessary work.
            let mut cohort_filters: Vec<&PropertyFilter> = Vec::new();
            for filter in flag_property_filters {
                if filter.depends_on_feature_flag() {
                    if !match_flag_value_to_flag_filter(
                        filter,
                        &self.flag_evaluation_state.flag_evaluation_results,
                    ) {
                        return Ok((false, FeatureFlagMatchReason::NoConditionMatch));
                    }
                } else if filter.is_cohort() {
                    cohort_filters.push(filter);
                } else {
                    let props = property_context.resolve_for_filter(filter);
                    if !match_property(filter, props, false).unwrap_or(false) {
                        return Ok((false, FeatureFlagMatchReason::NoConditionMatch));
                    }
                }
            }

            // Evaluate cohort filters using person properties (cohorts are person-level).
            if !cohort_filters.is_empty() {
                let cohorts = match &self.flag_evaluation_state.cohorts {
                    Some(cohorts) => cohorts.clone(),
                    None => return Ok((false, FeatureFlagMatchReason::NoConditionMatch)),
                };
                let cohort_props = property_context
                    .person_properties
                    .unwrap_or(&*EMPTY_PROPERTY_MAP);
                if !self.evaluate_cohort_filters(&cohort_filters, cohort_props, cohorts)? {
                    return Ok((false, FeatureFlagMatchReason::NoConditionMatch));
                }
            }
        }
        self.check_rollout(
            feature_flag,
            rollout_percentage,
            property_context.aggregation,
            hash_key_overrides,
            request_hash_key_override,
        )
    }

    /// Checks if a condition requires person/group properties to evaluate.
    /// Returns false for rollout-only conditions or conditions with only flag-value filters.
    fn condition_needs_properties(condition: &FlagPropertyGroup) -> bool {
        condition.properties.as_ref().is_some_and(|props| {
            // Check if there are any non-flag-value property filters
            props.iter().any(|prop| !prop.depends_on_feature_flag())
        })
    }

    /// Determines which property sources a condition's filters reference.
    /// Returns (needs_person_properties, set_of_group_type_indexes_needed).
    fn condition_property_type_needs(
        condition: &FlagPropertyGroup,
        effective_aggregation: Option<GroupTypeIndex>,
    ) -> (bool, HashSet<i32>) {
        let mut needs_person = false;
        let mut group_types = HashSet::new();

        if let Some(props) = &condition.properties {
            for prop in props {
                if prop.depends_on_feature_flag() || prop.is_cohort() {
                    // Cohort filters are evaluated against person properties, so the
                    // caller must load them before constructing the PropertyContext.
                    // Flag filters don't need any properties.
                    if prop.is_cohort() {
                        needs_person = true;
                    }
                    continue;
                }
                match prop.prop_type {
                    PropertyType::Person => needs_person = true,
                    PropertyType::Group => {
                        if let Some(gti) = prop.group_type_index.or(effective_aggregation) {
                            group_types.insert(gti);
                        }
                    }
                    // Cohort and Flag filters are handled by the guard above, but
                    // listing them explicitly ensures a compile error if a new
                    // PropertyType variant is added.
                    PropertyType::Cohort | PropertyType::Flag => {}
                }
            }
        }

        // For legacy flags where all filters lack explicit types but the condition
        // is group-aggregated, ensure the aggregation index is included. Similarly,
        // person-aggregated legacy conditions need person properties loaded.
        if group_types.is_empty() && !needs_person {
            match effective_aggregation {
                Some(gti) => {
                    group_types.insert(gti);
                }
                None => needs_person = true,
            }
        }

        (needs_person, group_types)
    }

    /// Gets group properties by merging DB properties with overrides (overrides take precedence).
    fn get_group_properties(
        &self,
        group_type_index: GroupTypeIndex,
        property_overrides: Option<&HashMap<String, Value>>,
    ) -> Result<HashMap<String, Value>, FlagError> {
        // Start with DB properties
        let mut merged_properties =
            self.get_group_properties_from_evaluation_state(group_type_index)?;

        // Merge in overrides (overrides take precedence)
        if let Some(overrides) = property_overrides {
            merged_properties.extend(overrides.iter_owned());
        }

        // Return all merged properties
        Ok(merged_properties)
    }

    /// Gets person properties by merging DB properties with overrides (overrides take precedence).
    fn get_person_properties(
        &self,
        property_overrides: Option<&HashMap<String, Value>>,
    ) -> Result<HashMap<String, Value>, FlagError> {
        let mut merged_properties = if self.only_use_override_person_properties {
            // When only_use_override_person_properties is true, ignore DB properties entirely
            HashMap::new()
        } else {
            // Start with DB properties (clone only when we need a mutable copy)
            self.get_person_properties_from_evaluation_state()
                .cloned()
                .unwrap_or_default()
        };

        // Merge in overrides (overrides take precedence)
        if let Some(overrides) = property_overrides {
            merged_properties.extend(overrides.iter_owned());
        }

        // Populate missing $initial_ properties from their non-initial counterparts.
        // DB $initial_ values are preserved; this only fills in missing ones from
        // the merged properties (which may come from DB or request overrides).
        populate_missing_initial_properties(&mut merged_properties);

        Ok(merged_properties)
    }

    fn is_holdout_condition_match(
        &self,
        flag: &FeatureFlag,
        request_hash_key_override: &Option<String>,
    ) -> Result<(bool, Option<String>, FeatureFlagMatchReason), FlagError> {
        if let Some(holdout) = &flag.filters.holdout {
            let percentage = holdout.exclusion_percentage.clamp(0.0, 100.0);

            if percentage < 100.0
                && self.get_holdout_hash(flag, None, request_hash_key_override)?
                    > (percentage / 100.0)
            {
                // User's hash is above the exclusion threshold — not in holdout
                return Ok((false, None, FeatureFlagMatchReason::OutOfRolloutBound));
            }

            // User is in holdout — variant name is derived from the holdout id
            return Ok((
                true,
                Some(format!("holdout-{}", holdout.id)),
                FeatureFlagMatchReason::HoldoutConditionValue,
            ));
        }
        Ok((false, None, FeatureFlagMatchReason::NoConditionMatch))
    }

    /// Check if a super condition matches for a feature flag.
    ///
    /// This function evaluates the super conditions of a feature flag to determine if any of them should be enabled.
    /// It uses pre-computed person properties (DB properties with overrides applied).
    /// The function returns a struct indicating whether a super condition should be evaluated,
    /// whether it matches if evaluated, and the reason for the match.
    ///
    /// Note: Super conditions (early access features) always use person properties, even for
    /// group-based flags, because early access enrollment is a person-level concept.
    fn is_super_condition_match(
        &self,
        feature_flag: &FeatureFlag,
        person_properties: &HashMap<String, Value>,
        hash_key_overrides: Option<&HashMap<String, String>>,
        request_hash_key_override: &Option<String>,
    ) -> Result<SuperConditionEvaluation, FlagError> {
        if let Some(super_condition) = feature_flag
            .filters
            .super_groups
            .as_ref()
            .and_then(|sc| sc.first())
        {
            let has_relevant_super_condition_properties =
                super_condition.properties.as_ref().is_some_and(|props| {
                    props
                        .iter()
                        .any(|prop| person_properties.contains_key(&prop.key))
                });

            if has_relevant_super_condition_properties {
                // Super conditions always use person-level aggregation (None)
                let empty_group_props = HashMap::new();
                let property_context = PropertyContext {
                    person_properties: Some(person_properties),
                    group_properties: &empty_group_props,
                    aggregation: None,
                };
                let (is_match, _) = self.is_condition_match(
                    feature_flag,
                    super_condition,
                    &property_context,
                    hash_key_overrides,
                    request_hash_key_override,
                )?;

                return Ok(SuperConditionEvaluation {
                    should_evaluate: true,
                    is_match,
                    reason: FeatureFlagMatchReason::SuperConditionValue,
                });
            }
        }

        Ok(SuperConditionEvaluation {
            should_evaluate: false,
            is_match: false,
            reason: FeatureFlagMatchReason::NoConditionMatch,
        })
    }

    /// Get hashed identifier for flag evaluation.
    ///
    /// Resolves the identifier used for hashing (rollout and variant assignment) based on
    /// the provided aggregation group type index. For group-based aggregation, uses the
    /// group key; for person-based aggregation, uses the distinct_id (with experience
    /// continuity and device_id bucketing fallbacks).
    ///
    /// For person-based flags with ensure_experience_continuity enabled, the identifier priority is:
    /// 1. DB-stored hash_key_override (for consistency across sessions)
    /// 2. Request's hash_key_override (anon_distinct_id) for first-time evaluations
    /// 3. distinct_id (final fallback)
    fn hashed_identifier(
        &self,
        feature_flag: &FeatureFlag,
        aggregation_group_type_index: Option<i32>,
        hash_key_overrides: Option<&HashMap<String, String>>,
        request_hash_key_override: &Option<String>,
    ) -> Result<String, FlagError> {
        if let Some(group_type_index) = aggregation_group_type_index {
            // Group-based flag
            let group_key = match self.group_type_mapping.as_ref().and_then(|m| {
                m.group_indexes_to_types()
                    .get(&group_type_index)
                    .and_then(|group_type_name| self.groups.get(group_type_name))
            }) {
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
            use crate::flags::flag_models::BucketingIdentifier;

            // Check if flag is configured for device_id bucketing
            if feature_flag.get_bucketing_identifier() == BucketingIdentifier::DeviceId {
                if let Some(device_id) = &self.device_id {
                    if !device_id.is_empty() {
                        return Ok(device_id.clone());
                    }
                }
            }

            // Use hash key overrides for experience continuity
            // Priority: DB override > request's anon_distinct_id > distinct_id
            if let Some(hash_key_override) = hash_key_overrides
                .as_ref()
                .and_then(|h| h.get(&feature_flag.key))
            {
                Ok(hash_key_override.clone())
            } else if feature_flag.has_experience_continuity() {
                // For EEC flags, use the request's anon_distinct_id as fallback when no DB override exists
                if let Some(request_override) = request_hash_key_override {
                    Ok(request_override.clone())
                } else {
                    Ok(self.distinct_id.clone())
                }
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
        aggregation_group_type_index: Option<i32>,
        hash_key_overrides: Option<&HashMap<String, String>>,
        request_hash_key_override: &Option<String>,
    ) -> Result<f64, FlagError> {
        let hashed_identifier = self.hashed_identifier(
            feature_flag,
            aggregation_group_type_index,
            hash_key_overrides,
            request_hash_key_override,
        )?;
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
        request_hash_key_override: &Option<String>,
    ) -> Result<f64, FlagError> {
        // Holdouts use the flag-level aggregation for hashing
        let hashed_identifier = self.hashed_identifier(
            feature_flag,
            feature_flag.get_group_type_index(),
            None,
            request_hash_key_override,
        )?;
        let hash = calculate_hash("holdout-", &hashed_identifier, salt.unwrap_or(""))?;
        Ok(hash)
    }

    /// Check if a feature flag should be shown based on its rollout percentage.
    ///
    /// Calculates a hash of the identifier (determined by `aggregation_group_type_index`)
    /// and compares it to the rollout percentage. Returns whether the flag matched and why.
    fn check_rollout(
        &self,
        feature_flag: &FeatureFlag,
        rollout_percentage: f64,
        aggregation_group_type_index: Option<i32>,
        hash_key_overrides: Option<&HashMap<String, String>>,
        request_hash_key_override: &Option<String>,
    ) -> Result<(bool, FeatureFlagMatchReason), FlagError> {
        if rollout_percentage == 100.0 {
            return Ok((true, FeatureFlagMatchReason::ConditionMatch));
        }
        let hash = self.get_hash(
            feature_flag,
            "",
            aggregation_group_type_index,
            hash_key_overrides,
            request_hash_key_override,
        )?;
        if hash <= (rollout_percentage / 100.0) {
            Ok((true, FeatureFlagMatchReason::ConditionMatch))
        } else {
            Ok((false, FeatureFlagMatchReason::OutOfRolloutBound))
        }
    }

    /// Returns the variant key for this flag based on the hashed identifier.
    /// The aggregation determines which identifier is hashed (group key vs distinct_id).
    pub(crate) fn get_matching_variant(
        &self,
        feature_flag: &FeatureFlag,
        aggregation_group_type_index: Option<i32>,
        hash_key_overrides: Option<&HashMap<String, String>>,
        request_hash_key_override: &Option<String>,
    ) -> Result<Option<String>, FlagError> {
        let hash = self.get_hash(
            feature_flag,
            "variant",
            aggregation_group_type_index,
            hash_key_overrides,
            request_hash_key_override,
        )?;
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
    /// - Realtime cohort memberships (via behavioral cohorts database)
    /// - Group type mappings
    /// - Person and group properties
    ///
    /// The data is cached in FlagEvaluationState to avoid repeated DB lookups
    /// during subsequent flag evaluations.
    pub async fn prepare_flag_evaluation_state(
        &mut self,
        flags: &[&FeatureFlag],
    ) -> Result<(), FlagError> {
        // Use preloaded cohorts from the flags cache when available (already scoped
        // to only referenced cohorts). Fall back to CohortCacheManager which fetches
        // ALL cohorts for the team.
        let cohorts: Arc<[Cohort]> = match self.preloaded_cohorts.take() {
            Some(preloaded) => {
                inc(
                    FLAG_COHORT_SOURCE_COUNTER,
                    &[("source".to_string(), "preloaded".to_string())],
                    1,
                );
                preloaded
            }
            None => {
                inc(
                    FLAG_COHORT_SOURCE_COUNTER,
                    &[("source".to_string(), "cache_manager".to_string())],
                    1,
                );
                Arc::from(self.cohort_cache.get_cohorts(self.team_id).await?)
            }
        };
        self.flag_evaluation_state.set_cohorts(Arc::clone(&cohorts));

        // Get static cohort IDs
        // NOTE: relies on `is_static` and `uses_realtime_membership()` being mutually exclusive
        // (a cohort with is_static=true should never have CohortType::Realtime/Behavioral).
        debug_assert!(
            !cohorts
                .iter()
                .any(|c| c.is_static && c.uses_realtime_membership()),
            "Cohort cannot be both static and realtime"
        );
        let static_cohort_ids: Vec<CohortId> = cohorts
            .iter()
            .filter(|c| c.is_static)
            .map(|c| c.id)
            .collect();

        // Load group type mappings if needed. Errors are intentionally not propagated here:
        // in the batch path (evaluate_flags_with_overrides), a group type mapping failure
        // should not poison person-based flags in the same batch. prepare_group_data
        // gracefully returns an empty map when self.group_type_mapping is None, so
        // group-based flags will fail individually rather than taking down the whole batch.
        if self.initialize_group_type_mappings_if_needed(flags).await {
            tracing::warn!("Failed to init group type mappings");
        }

        // Then prepare group mappings and properties
        // This should be _wicked_ fast since it's async and is just pulling from a cache that's already in memory
        let group_timer = common_metrics::timing_guard(FLAG_GROUP_CACHE_FETCH_TIME, &[]);
        let group_data = self.prepare_group_data(flags)?;
        group_timer.fin();

        // Single DB operation for properties and cohorts
        let db_fetch_timer = common_metrics::timing_guard(FLAG_DB_PROPERTIES_FETCH_TIME, &[]);
        match fetch_and_locally_cache_all_relevant_properties(
            &mut self.flag_evaluation_state,
            self.router.get_persons_reader().clone(),
            self.distinct_id.clone(),
            self.team_id,
            &group_data,
            static_cohort_ids,
        )
        .await
        {
            Ok(_) => {
                inc(DB_PERSON_AND_GROUP_PROPERTIES_READS_COUNTER, &[], 1);
                db_fetch_timer.label("outcome", "success").fin();
            }
            Err(e) => {
                error!(
                    "Error fetching properties for team {} distinct_id {}: {:?}",
                    self.team_id, self.distinct_id, e
                );
                db_fetch_timer.label("outcome", "error").fin();
                return Err(e);
            }
        }

        // Fetch realtime cohort memberships for Realtime/Behavioral cohorts.
        // This is a separate DB call to the behavioral cohorts database, isolated from
        // the static cohort path above which uses the persons_reader pool.
        let realtime_cohort_ids: Vec<CohortId> = if self.enable_realtime_cohort_evaluation {
            cohorts
                .iter()
                .filter(|c| c.uses_realtime_membership())
                .map(|c| c.id)
                .collect()
        } else {
            Vec::new()
        };

        if !realtime_cohort_ids.is_empty() {
            with_canonical_log(|log| {
                log.realtime_cohorts_evaluated += realtime_cohort_ids.len();
            });

            let all_non_member = || -> HashMap<CohortId, bool> {
                realtime_cohort_ids.iter().map(|id| (*id, false)).collect()
            };

            let realtime_memberships = if let Some(person_uuid) =
                self.flag_evaluation_state.get_person_uuid()
            {
                let query_labels = [("team_id".to_string(), self.team_id.to_string())];
                let realtime_timer = timing_guard(FLAG_REALTIME_COHORT_QUERY_TIME, &query_labels);
                let realtime_start = std::time::Instant::now();

                let result = self
                    .cohort_membership_provider
                    .check_memberships(self.team_id, person_uuid, &realtime_cohort_ids)
                    .await;

                let duration = realtime_start.elapsed();
                realtime_timer.fin();
                with_canonical_log(|log| {
                    log.realtime_cohort_queries += 1;
                    log.realtime_cohort_query_time_ms += duration.as_millis() as u64;
                });

                match result {
                    Ok(memberships) => memberships,
                    Err(e) => {
                        inc(FLAG_REALTIME_COHORT_QUERY_ERROR_COUNTER, &query_labels, 1);
                        warn!(
                            team_id = self.team_id,
                            person_uuid = %person_uuid,
                            realtime_cohort_count = realtime_cohort_ids.len(),
                            error = %e,
                            "Realtime cohort membership lookup failed, treating all as non-members"
                        );
                        // Graceful degradation: treat all realtime cohorts as non-members
                        all_non_member()
                    }
                }
            } else {
                // No person UUID available (anonymous user). Realtime cohorts return false.
                all_non_member()
            };

            self.flag_evaluation_state
                .merge_cohort_matches(realtime_memberships);
        }

        Ok(())
    }

    /// Builds a paired mapping from group type index to group key for flag
    /// evaluation, filtered to only the group types required by the given flags.
    fn prepare_group_data(
        &mut self,
        flags: &[&FeatureFlag],
    ) -> Result<HashMap<GroupTypeIndex, String>, FlagError> {
        // Collect group type indexes from both flag-level and per-condition aggregation,
        // so we fetch data for all group types referenced by any condition.
        let required_type_indexes: HashSet<GroupTypeIndex> = flags
            .iter()
            .flat_map(|flag| {
                let flag_level = flag.get_group_type_index();
                let condition_level = flag
                    .get_conditions()
                    .iter()
                    .filter_map(|c| c.aggregation_group_type_index.flatten());
                flag_level.into_iter().chain(condition_level)
            })
            .collect();

        if required_type_indexes.is_empty() {
            return Ok(HashMap::new());
        }

        let mapping = match &self.group_type_mapping {
            Some(m) => m,
            None => return Ok(HashMap::new()),
        };
        let types_to_indexes = mapping.group_types_to_indexes();

        let group_type_to_key: HashMap<GroupTypeIndex, String> = self
            .groups
            .iter()
            .filter_map(|(group_type, group_key_value)| {
                let group_key = match group_key_value {
                    Value::String(s) => s.clone(),
                    Value::Number(n) => n.to_string(),
                    _ => return None,
                };
                types_to_indexes
                    .get(group_type)
                    .cloned()
                    .filter(|idx| required_type_indexes.contains(idx))
                    .map(|group_type_index| (group_type_index, group_key))
            })
            .collect();

        Ok(group_type_to_key)
    }

    /// Get person properties from the `FlagEvaluationState` only, returning a reference.
    fn get_person_properties_from_evaluation_state(
        &self,
    ) -> Result<&HashMap<String, Value>, FlagError> {
        match &self.flag_evaluation_state.person_property_state {
            PersonPropertyState::Fetched(properties) => {
                inc(
                    PROPERTY_CACHE_HITS_COUNTER,
                    &[("type".to_string(), "person_properties".to_string())],
                    1,
                );
                with_canonical_log(|log| log.eval.property_cache_hits += 1);
                Ok(properties)
            }
            PersonPropertyState::Skipped => {
                tracing::debug!(
                    "Person properties not in cache — DB prep was skipped (overrides cover all needed keys)"
                );
                Err(FlagError::PersonNotFound)
            }
            PersonPropertyState::Pending => {
                inc(
                    PROPERTY_CACHE_MISSES_COUNTER,
                    &[
                        ("type".to_string(), "person_properties".to_string()),
                        ("reason".to_string(), "db_prep_never_ran".to_string()),
                    ],
                    1,
                );
                with_canonical_log(|log| {
                    log.eval.property_cache_misses += 1;
                    log.eval.person_properties_not_cached = true;
                });
                tracing::error!("Person properties not found — DB prep never ran");
                Err(FlagError::PersonNotFound)
            }
        }
    }

    /// Get group properties for the given group type index from the `FlagEvaluationState` only. Returns empty HashMap if not found.
    fn get_group_properties_from_evaluation_state(
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
            with_canonical_log(|log| log.eval.property_cache_hits += 1);
            let mut result = HashMap::new();
            result.clone_from(properties);
            Ok(result)
        } else {
            inc(
                PROPERTY_CACHE_MISSES_COUNTER,
                &[("type".to_string(), "group_properties".to_string())],
                1,
            );
            with_canonical_log(|log| {
                log.eval.property_cache_misses += 1;
                log.eval.group_properties_not_cached = true;
            });
            // Return empty HashMap instead of error - no properties is a valid state
            Ok(HashMap::new())
        }
    }

    /// If experience continuity is enabled, we need to process the hash key override.
    /// See [`FeatureFlagMatcher::process_hash_key_override`] for more details.
    async fn process_hash_key_override_if_needed(
        &self,
        flags_have_experience_continuity_enabled: bool,
        hash_key_override: Option<String>,
    ) -> (Option<HashMap<String, String>>, bool) {
        let hash_key_timer = common_metrics::timing_guard(FLAG_HASH_KEY_PROCESSING_TIME, &[]);
        let (hash_key_overrides, flag_hash_key_override_error) =
            if flags_have_experience_continuity_enabled {
                common_metrics::inc(FLAG_EXPERIENCE_CONTINUITY_REQUESTS_COUNTER, &[], 1);
                match hash_key_override {
                    Some(hash_key) => {
                        let target_distinct_ids = vec![self.distinct_id.clone(), hash_key.clone()];
                        self.process_hash_key_override(hash_key, target_distinct_ids)
                            .await
                    }
                    // If no hash key override is provided, we need to look up existing overrides.
                    // Most of the time this is fine because our client side sdks usually include $anon_distinct_id in their requests,
                    // but if a customer is using hash key overrides across a client sdk and a server sdk then the experience
                    // will be inconsistent because server sdks won't include $anon_distinct_id in their requests.
                    // In addition, this behavior is consistent with /decide.
                    None => {
                        match get_feature_flag_hash_key_overrides(
                            self.router.get_persons_reader().clone(),
                            self.team_id,
                            vec![self.distinct_id.clone()],
                        )
                        .await
                        {
                            Ok(overrides) => (Some(overrides), false),
                            Err(e) => {
                                error!(
                                    "Failed to get feature flag hash key overrides for team {} distinct_id {}: {:?}",
                                    self.team_id, self.distinct_id, e
                                );
                                (None, true)
                            }
                        }
                    }
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

        // Track hash key override status in canonical log
        if flag_hash_key_override_error {
            with_canonical_log(|log| log.hash_key_override_status = Some("error"));
        } else if let Some(ref overrides) = hash_key_overrides {
            let status = if overrides.is_empty() {
                "empty"
            } else {
                "found"
            };
            with_canonical_log(|log| log.hash_key_override_status = Some(status));
        }

        (hash_key_overrides, flag_hash_key_override_error)
    }

    /// Initializes the group type mapping cache if needed.
    ///
    /// This function checks if any of the feature flags have group type indices and initializes the group type mapping cache if needed.
    /// It returns a boolean indicating if there were any errors while initializing the group type mapping cache.
    async fn initialize_group_type_mappings_if_needed(&mut self, flags: &[&FeatureFlag]) -> bool {
        // Check if we need to fetch group type mappings — any flag or condition uses group aggregation
        let has_type_indexes = flags.iter().any(|flag| {
            !self.filtered_out_flag_ids.contains(&flag.id)
                && (flag.get_group_type_index().is_some()
                    || flag
                        .get_conditions()
                        .iter()
                        .any(|c| matches!(c.aggregation_group_type_index, Some(Some(_)))))
        });

        if !has_type_indexes {
            return false;
        }

        let group_type_mapping_timer = common_metrics::timing_guard(FLAG_GROUP_DB_FETCH_TIME, &[]);
        let mut errors_while_computing_flags = false;

        match self.group_type_cache.get_mappings(self.team_id).await {
            Ok(mapping) if mapping.is_empty() => {
                tracing::warn!("No group type mappings found for team {}", self.team_id);
                // Empty mappings are not an error — the team simply has no group types configured.
                // Group-based flags won't match, but person flags in the same batch should succeed
                // without surfacing errorsWhileComputingFlags to the client.
            }
            Ok(mapping) => {
                self.group_type_mapping = Some(mapping);
            }
            Err(_) => {
                errors_while_computing_flags = true;
            }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_promote_evaluation_type_none_to_sequential() {
        assert_eq!(
            EvaluationType::promote(None, EvaluationType::Sequential),
            Some(EvaluationType::Sequential)
        );
    }

    #[test]
    fn test_promote_evaluation_type_none_to_parallel() {
        assert_eq!(
            EvaluationType::promote(None, EvaluationType::Parallel),
            Some(EvaluationType::Parallel)
        );
    }

    #[test]
    fn test_promote_evaluation_type_sequential_to_parallel() {
        assert_eq!(
            EvaluationType::promote(Some(EvaluationType::Sequential), EvaluationType::Parallel),
            Some(EvaluationType::Parallel)
        );
    }

    #[test]
    fn test_promote_evaluation_type_parallel_stays_sticky() {
        assert_eq!(
            EvaluationType::promote(Some(EvaluationType::Parallel), EvaluationType::Sequential),
            Some(EvaluationType::Parallel)
        );
    }

    #[test]
    fn test_promote_evaluation_type_sequential_stays_sequential() {
        assert_eq!(
            EvaluationType::promote(Some(EvaluationType::Sequential), EvaluationType::Sequential),
            Some(EvaluationType::Sequential)
        );
    }

    #[test]
    fn test_panic_fallback_preserves_flag_identity() {
        let team_id = 42;
        let snapshots = vec![
            FlagSnapshot {
                key: "flag_a".to_string(),
                id: 10,
                version: Some(3),
            },
            FlagSnapshot {
                key: "flag_b".to_string(),
                id: 20,
                version: None,
            },
            FlagSnapshot {
                key: "flag_c".to_string(),
                id: 30,
                version: Some(1),
            },
        ];

        let results = FeatureFlagMatcher::build_panic_fallback(snapshots, team_id);

        assert_eq!(results.len(), 3);

        let (stub_a, err_a) = &results[0];
        assert_eq!(stub_a.key, "flag_a");
        assert_eq!(stub_a.id, 10);
        assert_eq!(stub_a.version, Some(3));
        assert!(matches!(err_a, Err(FlagError::BatchEvaluationPanicked)));

        let (stub_b, err_b) = &results[1];
        assert_eq!(stub_b.key, "flag_b");
        assert_eq!(stub_b.id, 20);
        assert_eq!(stub_b.version, None);
        assert!(matches!(err_b, Err(FlagError::BatchEvaluationPanicked)));

        let (stub_c, err_c) = &results[2];
        assert_eq!(stub_c.key, "flag_c");
        assert_eq!(stub_c.id, 30);
        assert_eq!(stub_c.version, Some(1));
        assert!(matches!(err_c, Err(FlagError::BatchEvaluationPanicked)));

        for (stub, _) in &results {
            assert_eq!(stub.team_id, team_id);
            assert!(stub.active);
            assert_eq!(stub.name, None);
            assert!(!stub.deleted);
            assert!(stub.filters.groups.is_empty());
        }
    }
}
