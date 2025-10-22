use std::{
    collections::{HashMap, HashSet},
    time::{Duration, Instant},
};
use tokio_retry::{
    strategy::{jitter, ExponentialBackoff},
    Retry,
};

use crate::database::PostgresRouter;
use common_database::PostgresReader;
use common_types::{PersonId, ProjectId, TeamId};
use serde_json::Value;
use sha1::{Digest, Sha1};
use sqlx::{Acquire, Row};
use tokio::time::timeout;
use tracing::{error, info, instrument, warn};

// Use thread-local storage for test counter to isolate concurrent tests
#[cfg(test)]
use std::cell::RefCell;

use crate::{
    api::{errors::FlagError, types::FlagValue},
    cohorts::cohort_models::CohortId,
    config::Config,
    flags::flag_models::FeatureFlagId,
    metrics::consts::{
        FLAG_COHORT_PROCESSING_TIME, FLAG_COHORT_QUERY_TIME, FLAG_CONNECTION_HOLD_TIME,
        FLAG_DB_CONNECTION_TIME, FLAG_DEFINITION_QUERY_TIME, FLAG_GROUP_PROCESSING_TIME,
        FLAG_GROUP_QUERY_TIME, FLAG_HASH_KEY_RETRIES_COUNTER, FLAG_PERSON_PROCESSING_TIME,
        FLAG_PERSON_QUERY_TIME, FLAG_POOL_UTILIZATION_GAUGE,
        FLAG_READER_TIMEOUT_WITH_WRITER_STATE_COUNTER,
    },
    properties::{
        property_matching::match_property,
        property_models::{OperatorType, PropertyFilter},
    },
};

use super::{flag_group_type_mapping::GroupTypeIndex, flag_matching::FlagEvaluationState};

const LONG_SCALE: u64 = 0xfffffffffffffff;

// Thread-local counter ensures test isolation when running in parallel
#[cfg(test)]
thread_local! {
    static FETCH_CALLS: RefCell<usize> = const { RefCell::new(0) };
}

/// Context for flag queries - encapsulates common parameters
pub struct FlagQueryContext<'a> {
    pub reader: PostgresReader,
    pub team_id: TeamId,
    pub config: &'a Config,
}

/// RAII guard for timing queries with automatic logging
struct QueryTimer<'a> {
    name: &'static str,
    start: Instant,
    _metric_guard: common_metrics::TimingGuard<'a>,
}

impl<'a> QueryTimer<'a> {
    fn new(name: &'static str, metric_name: &'static str) -> Self {
        Self {
            name,
            start: Instant::now(),
            _metric_guard: common_metrics::timing_guard(metric_name, &[]),
        }
    }

    fn elapsed_ms(&self) -> u128 {
        self.start.elapsed().as_millis()
    }
}

impl<'a> Drop for QueryTimer<'a> {
    fn drop(&mut self) {
        // Metric is automatically finalized via the guard drop
        let duration = self.elapsed_ms();
        if duration > 500 {
            warn!("{} took {}ms", self.name, duration);
        }
    }
}

/// Log query duration based on configured thresholds
fn log_query_duration(
    query_name: &str,
    duration_ms: u128,
    config: &Config,
    context: impl FnOnce() -> String,
) {
    let threshold_ms = config.flag_query_slow_error_threshold_ms as u128;
    let warn_ms = config.flag_query_slow_warn_threshold_ms as u128;
    let info_ms = config.flag_query_slow_info_threshold_ms as u128;

    match duration_ms {
        d if d > threshold_ms => {
            error!(
                duration_ms = d,
                query = query_name,
                "CRITICAL: Very slow query - {}",
                context()
            );
        }
        d if d > warn_ms => {
            warn!(
                duration_ms = d,
                query = query_name,
                "Slow query detected - {}",
                context()
            );
        }
        d if d > info_ms => {
            info!(duration_ms = d, query = query_name, "Query completed");
        }
        _ => {}
    }
}

/// Calculates a deterministic hash value between 0 and 1 for a given identifier and salt.
///
/// This function uses SHA1 to generate a hash, then converts the first 15 characters to a number
/// between 0 and 1. The hash is deterministic for the same input values.
///
/// ## Arguments
/// * `prefix` - A prefix to add to the hash key (e.g., "holdout-")
/// * `hashed_identifier` - The main identifier to hash (e.g., user ID)
/// * `salt` - Additional string to make the hash unique (can be empty)
///
/// ## Returns
/// * `f64` - A number between 0 and 1
pub fn calculate_hash(prefix: &str, hashed_identifier: &str, salt: &str) -> Result<f64, FlagError> {
    let hash_key = format!("{prefix}{hashed_identifier}{salt}");
    let hash_value = Sha1::digest(hash_key.as_bytes());
    // We use the first 8 bytes of the hash and shift right by 4 bits
    // This is equivalent to using the first 15 hex characters (7.5 bytes) of the hash
    // as was done in the previous implementation, ensuring consistent feature flag distribution
    let hash_val: u64 = u64::from_be_bytes(hash_value[..8].try_into().unwrap()) >> 4;
    Ok(hash_val as f64 / LONG_SCALE as f64)
}

/// Fetch and locally cache all properties for a given distinct ID and team ID.
///
/// This function fetches both person and group properties for a specified distinct ID and team ID.
/// It updates the properties cache with the fetched properties and returns void if it succeeds.
#[instrument(skip_all, fields(
    team_id = %team_id,
    distinct_id = %distinct_id,
    cohort_ids = ?static_cohort_ids,
    group_type_indexes = ?group_type_indexes,
    group_keys = ?group_keys
))]
#[allow(clippy::too_many_arguments)]
pub async fn fetch_and_locally_cache_all_relevant_properties(
    flag_evaluation_state: &mut FlagEvaluationState,
    reader: PostgresReader,
    distinct_id: String,
    team_id: TeamId,
    group_type_indexes: &HashSet<GroupTypeIndex>,
    group_keys: &HashSet<String>,
    static_cohort_ids: Vec<CohortId>,
    config: &Config,
) -> Result<(), FlagError> {
    // Add the test-specific counter increment
    #[cfg(test)]
    increment_fetch_calls_count();

    // Log pool state at function entry to track patterns - use structured logging
    if let Some(stats) = reader.as_ref().get_pool_stats() {
        let utilization =
            (stats.size.saturating_sub(stats.num_idle as u32) as f64) / stats.size as f64;
        if utilization > 0.8 {
            warn!(
                utilization_pct = utilization * 100.0,
                idle = stats.num_idle,
                total = stats.size,
                %team_id,
                %distinct_id,
                "High pool utilization at function entry"
            );
        }
    }

    // Track total function execution time
    let function_start = Instant::now();

    // No longer acquiring a connection here - each query will use the pool directly

    // First query: Get person data from the distinct_id (person_id and person_properties)
    // TRICKY: sometimes we don't have a person_id ingested by the time we get a `/flags` request for a given
    // distinct_id. There's two cases for that:
    // 1. there's a race condition between person ingestion and flag evaluation.  In that case, only the first flag request
    // be missing a person id, and all subsequent requests will have a person id.  That means the first flag evaluation could be wrong, but all subsequent ones will be correct.  Not a huge problem.
    // 2. the distinct_id is associated with an anonymous or cookieless user.  In that case, it's fine to not return a person ID and to never return person properties.  This is handled by just
    // returning an empty HashMap for person properties whenever I actually need them, and then obviously any condition that depends on person properties will return false.
    // That's fine though, we shouldn't error out just because we can't find a person ID.
    let person_query = r#"
        SELECT DISTINCT ON (ppd.distinct_id)
            p.id as person_id,
            p.properties as person_properties
        FROM posthog_persondistinctid ppd
        INNER JOIN posthog_person p
            ON p.id = ppd.person_id
            AND p.team_id = ppd.team_id
        WHERE ppd.distinct_id = $1
            AND ppd.team_id = $2
    "#;

    let _person_timer = QueryTimer::new("Person query", FLAG_PERSON_QUERY_TIME);

    let (person_id, person_props): (Option<PersonId>, Option<Value>) = {
        let mut conn = reader.get_connection().await?;
        // DUAL TIMEOUT APPROACH:
        // 1. Client-side timeout (tokio::time::timeout) - fails fast, doesn't cancel server query
        // 2. Server-side timeout (statement_timeout) - actually cancels long-running queries
        // The server timeout is configured in the connection pool and is slightly higher
        // than client timeouts to allow for network overhead.
        timeout(
            Duration::from_millis(config.flag_person_query_timeout_ms),
            sqlx::query_as(person_query)
                .bind(&distinct_id)
                .bind(team_id)
                .fetch_optional(&mut *conn),
        )
        .await
        .map_err(|_| {
            warn!("Person query timeout");
            FlagError::TimeoutError(Some("Person query".to_string()))
        })?
        .map(|opt| opt.unwrap_or((None, None)))
        .map_err(|e: sqlx::Error| FlagError::from(e))?
    };

    let person_query_duration = _person_timer.elapsed_ms();

    // Use structured logging helper
    log_query_duration("Person query", person_query_duration, config, || {
        let cohort_count = static_cohort_ids.len();
        let group_count = group_type_indexes.len();
        let person_found = person_id.is_some();
        format!(
            "distinct_id={distinct_id}, team_id={team_id}, cohort_count={cohort_count}, group_count={group_count}, person_found={person_found}"
        )
    });
    let person_processing_timer = common_metrics::timing_guard(FLAG_PERSON_PROCESSING_TIME, &[]);
    if let Some(person_id) = person_id {
        // NB: this is where we actually set our person ID in the flag evaluation state.
        flag_evaluation_state.set_person_id(person_id);
        // If we have static cohort IDs to check and a valid person_id, do the cohort query
        if !static_cohort_ids.is_empty() {
            let cohort_query = r#"
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

            let _cohort_timer = QueryTimer::new("Cohort query", FLAG_COHORT_QUERY_TIME);

            let cohort_rows = {
                let mut conn = reader.get_connection().await?;
                // DUAL TIMEOUT APPROACH: Client-side fails fast, server-side cancels query
                timeout(
                    Duration::from_millis(config.flag_cohort_query_timeout_ms),
                    sqlx::query(cohort_query)
                        .bind(&static_cohort_ids)
                        .bind(person_id)
                        .fetch_all(&mut *conn),
                )
                .await
                .map_err(|_| {
                    warn!("Cohort query timeout");
                    FlagError::TimeoutError(Some("Cohort query".to_string()))
                })?
                .map_err(|e: sqlx::Error| FlagError::from(e))?
            };

            let cohort_query_duration = _cohort_timer.elapsed_ms();

            // Use structured logging helper
            log_query_duration("Cohort query", cohort_query_duration, config, || {
                format!(
                    "person_id={person_id}, cohort_ids={static_cohort_ids:?}, team_id={team_id}"
                )
            });

            let cohort_processing_timer =
                common_metrics::timing_guard(FLAG_COHORT_PROCESSING_TIME, &[]);
            let cohort_results: HashMap<CohortId, bool> = cohort_rows
                .into_iter()
                .map(|row| {
                    let cohort_id: CohortId = row.get("cohort_id");
                    let is_member: bool = row.get("is_member");
                    (cohort_id, is_member)
                })
                .collect();

            flag_evaluation_state.set_static_cohort_matches(cohort_results);
            cohort_processing_timer.fin();
        } else {
            // TRICKY: if there are no static cohorts to check, we want to return an empty map to show that
            // we checked the cohorts and found no matches. I want to differentiate from returning None, which
            // would indicate that that we had an error doing this evaluation in the first place.
            // i.e.: if there are no static cohort ID matches, it means we checked, and if there's None, it means something
            // went wrong.  This is handled in the caller.
            flag_evaluation_state.set_static_cohort_matches(HashMap::new());
        }
    }

    // if we have person properties, set them
    let mut all_person_properties: HashMap<String, Value> = if let Some(person_props) = person_props
    {
        person_props
            .as_object()
            .unwrap_or(&serde_json::Map::new())
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect()
    } else {
        HashMap::new()
    };

    // Always add distinct_id to person properties to match Python implementation
    // This allows flags to filter on distinct_id even when no other person properties exist
    all_person_properties.insert(
        "distinct_id".to_string(),
        Value::String(distinct_id.clone()),
    );

    flag_evaluation_state.set_person_properties(all_person_properties);
    person_processing_timer.fin();

    // Only fetch group property data if we have group types to look up
    if !group_type_indexes.is_empty() {
        let group_query = r#"
            SELECT
                group_type_index,
                group_key,
                group_properties
            FROM posthog_group
            WHERE team_id = $1
                AND group_type_index = ANY($2)
                AND group_key = ANY($3)
        "#;

        let group_type_indexes_vec: Vec<GroupTypeIndex> =
            group_type_indexes.iter().copied().collect();
        let group_keys_vec: Vec<String> = group_keys.iter().cloned().collect();

        let _group_timer = QueryTimer::new("Group query", FLAG_GROUP_QUERY_TIME);

        let groups = {
            let mut conn = reader.get_connection().await?;
            // DUAL TIMEOUT APPROACH: Client-side fails fast, server-side cancels query
            timeout(
                Duration::from_millis(config.flag_group_query_timeout_ms),
                sqlx::query(group_query)
                    .bind(team_id)
                    .bind(&group_type_indexes_vec)
                    .bind(&group_keys_vec)
                    .fetch_all(&mut *conn),
            )
            .await
            .map_err(|_| {
                warn!("Group query timeout");
                FlagError::TimeoutError(Some("Group query".to_string()))
            })?
            .map_err(|e: sqlx::Error| FlagError::from(e))?
        };

        let group_query_duration = _group_timer.elapsed_ms();

        // Use structured logging helper
        log_query_duration("Group query", group_query_duration, config, || {
            let results = groups.len();
            format!(
                "team_id={team_id}, group_type_indexes={group_type_indexes_vec:?}, group_keys={group_keys_vec:?}, results={results}"
            )
        });

        let group_processing_timer = common_metrics::timing_guard(FLAG_GROUP_PROCESSING_TIME, &[]);
        for row in groups {
            let group_type_index: GroupTypeIndex = row.get("group_type_index");
            let properties: Value = row.get("group_properties");

            if let Value::Object(props) = properties {
                let properties = props.into_iter().collect();
                flag_evaluation_state.set_group_properties(group_type_index, properties);
            }
        }
        group_processing_timer.fin();
    }

    // Log if the entire function took too long - use structured logging
    let total_duration = function_start.elapsed();
    let total_duration_ms = total_duration.as_millis();

    if total_duration_ms > config.flag_total_execution_error_threshold_ms as u128 {
        error!(
            duration_ms = total_duration_ms,
            %team_id,
            %distinct_id,
            had_person = flag_evaluation_state.get_person_id().is_some(),
            cohort_count = static_cohort_ids.len(),
            group_count = group_type_indexes.len(),
            "CRITICAL: Total property fetch exceeded threshold"
        );
    } else if total_duration_ms > config.flag_total_execution_warn_threshold_ms as u128 {
        warn!(
            duration_ms = total_duration_ms,
            %team_id,
            %distinct_id,
            "Slow total property fetch"
        );
    }

    Ok(())
}

/// Return any locally computable property overrides (non-cohort properties).
/// This returns the subset of overrides that can be computed locally, even if not all flag properties are overridden.
pub fn locally_computable_property_overrides(
    property_overrides: &Option<HashMap<String, Value>>,
    property_filters: &[PropertyFilter],
) -> Option<HashMap<String, Value>> {
    let overrides = property_overrides.as_ref()?;

    // Early return if flag has cohort filters - these require DB lookup
    if has_cohort_filters(property_filters) {
        return None;
    }

    // Only return overrides if they're useful for this flag
    if are_overrides_useful_for_flag(overrides, property_filters) {
        Some(overrides.clone())
    } else {
        None
    }
}

/// Checks if any property filters involve cohorts that require database lookup
fn has_cohort_filters(property_filters: &[PropertyFilter]) -> bool {
    property_filters.iter().any(|prop| prop.is_cohort())
}

/// Determines if the provided overrides contain properties that the flag actually needs
fn are_overrides_useful_for_flag(
    overrides: &HashMap<String, Value>,
    property_filters: &[PropertyFilter],
) -> bool {
    // If flag doesn't need any properties, overrides aren't useful
    if property_filters.is_empty() {
        return false;
    }

    // Check if overrides contain at least one property the flag needs
    property_filters
        .iter()
        .any(|filter| overrides.contains_key(&filter.key))
}

/// Check if a FlagError contains a foreign key constraint violation
fn flag_error_is_foreign_key_constraint(error: &FlagError) -> bool {
    match error {
        FlagError::DatabaseError(sqlx_error, _) => {
            common_database::is_foreign_key_constraint_error(sqlx_error)
        }
        _ => false,
    }
}

/// Determines if a FlagError should trigger a retry
fn should_retry_on_error(error: &FlagError) -> bool {
    match error {
        // Retry on database errors that are likely transient
        FlagError::DatabaseError(sqlx_error, _) => common_database::is_transient_error(sqlx_error),

        // Other error types generally should not be retried
        _ => false,
    }
}

/// Check if all properties match the given filters
pub fn all_properties_match(
    flag_condition_properties: &[PropertyFilter],
    matching_property_values: &HashMap<String, Value>,
) -> bool {
    flag_condition_properties
        .iter()
        .all(|property| match_property(property, matching_property_values, false).unwrap_or(false))
}

pub fn all_flag_condition_properties_match(
    flag_condition_properties: &[PropertyFilter],
    flag_evaluation_results: &HashMap<FeatureFlagId, FlagValue>,
) -> bool {
    flag_condition_properties
        .iter()
        .all(|property| match_flag_value_to_flag_filter(property, flag_evaluation_results))
}

// Attempts to match a flag condition filter that depends on another flag
// evaluation result to a flag evaluation result
pub fn match_flag_value_to_flag_filter(
    filter: &PropertyFilter,
    flag_evaluation_results: &HashMap<FeatureFlagId, FlagValue>,
) -> bool {
    // Flag dependencies must use the flag_evaluates_to operator
    if filter.operator != Some(OperatorType::FlagEvaluatesTo) {
        tracing::error!(
            "Flag filter operator for property type Flag must be `flag_evaluates_to`, skipping flag value matching: {:?}",
            filter
        );
        return false;
    }

    let Some(flag_id) = filter.get_feature_flag_id() else {
        return false;
    };

    let Some(flag_value) = flag_evaluation_results.get(&flag_id) else {
        return false;
    };

    match filter.value {
        Some(Value::Bool(true)) => flag_value != &FlagValue::Boolean(false),
        Some(Value::Bool(false)) => flag_value == &FlagValue::Boolean(false),
        Some(Value::String(ref s)) => {
            matches!(flag_value, FlagValue::String(flag_str) if flag_str == s)
        }
        _ => false,
    }
}

/// Retrieves feature flag hash key overrides for a list of distinct IDs with retry logic.
///
/// This function fetches any hash key overrides that have been set for feature flags
/// for the given distinct IDs. It handles priority by giving precedence to the first
/// distinct ID in the list. The operation is retried up to 3 times with exponential
/// backoff on transient database errors.
pub async fn get_feature_flag_hash_key_overrides(
    reader: PostgresReader,
    team_id: TeamId,
    distinct_id_and_hash_key_override: Vec<String>,
    config: &Config,
) -> Result<HashMap<String, String>, FlagError> {
    let retry_strategy = ExponentialBackoff::from_millis(50)
        .max_delay(Duration::from_millis(300))
        .take(3)
        .map(jitter); // Add jitter to prevent thundering herd

    // Use tokio-retry to automatically retry on transient failures
    Retry::spawn(retry_strategy, || async {
        let result = try_get_feature_flag_hash_key_overrides(
            &reader,
            team_id,
            &distinct_id_and_hash_key_override,
            config,
        )
        .await;

        // Log retry attempts for observability
        if let Err(ref e) = result {
            if should_retry_on_error(e) {
                // Increment retry counter for monitoring
                common_metrics::inc(
                    FLAG_HASH_KEY_RETRIES_COUNTER,
                    &[
                        ("team_id".to_string(), team_id.to_string()),
                        (
                            "operation".to_string(),
                            "get_hash_key_overrides".to_string(),
                        ),
                    ],
                    1,
                );

                tracing::warn!(
                    team_id = %team_id,
                    distinct_ids = ?distinct_id_and_hash_key_override,
                    error = ?e,
                    "Hash key override query failed, will retry"
                );
            }
        }

        result
    })
    .await
}

/// Internal function that performs the actual hash key override retrieval.
/// This is separated to make it easy to retry with tokio-retry.
#[instrument(skip_all, fields(
    team_id = %team_id,
    distinct_ids = ?distinct_id_and_hash_key_override
))]
async fn try_get_feature_flag_hash_key_overrides(
    reader: &PostgresReader,
    team_id: TeamId,
    distinct_id_and_hash_key_override: &[String],
    config: &Config,
) -> Result<HashMap<String, String>, FlagError> {
    let function_start = Instant::now();
    let mut feature_flag_hash_key_overrides = HashMap::new();
    // Get person data and their hash key overrides in one query
    let hash_override_query = r#"
            SELECT
                ppd.person_id,
                ppd.distinct_id,
                fhko.feature_flag_key,
                fhko.hash_key
            FROM posthog_persondistinctid ppd
            LEFT JOIN posthog_featureflaghashkeyoverride fhko
                ON fhko.person_id = ppd.person_id
                AND fhko.team_id = ppd.team_id
            WHERE ppd.team_id = $1
                AND ppd.distinct_id = ANY($2)
        "#;

    let query_start = Instant::now();

    // Get connection, execute query, then immediately release
    let rows = {
        let mut conn = reader.get_connection().await?;
        let query_result = timeout(
            Duration::from_millis(config.flag_hash_key_override_query_timeout_ms),
            sqlx::query(hash_override_query)
                .bind(team_id)
                .bind(distinct_id_and_hash_key_override)
                .fetch_all(&mut *conn),
        )
        .await;

        match query_result {
            Ok(Ok(result)) => result,
            Ok(Err(e)) => return Err(e.into()),
            Err(_) => {
                warn!(
                    "Hash key override query timeout for team_id={}, distinct_ids={:?}",
                    team_id, distinct_id_and_hash_key_override
                );
                return Err(FlagError::TimeoutError(Some(
                    "Hash key override query exceeded 500ms".to_string(),
                )));
            }
        }
    }; // Connection is dropped here

    let query_duration = query_start.elapsed();
    if query_duration.as_millis() > config.flag_query_slow_warn_threshold_ms as u128 {
        warn!(
            "Slow hash key override query: {}ms for team_id={}, distinct_ids={}, results={}",
            query_duration.as_millis(),
            team_id,
            distinct_id_and_hash_key_override.len(),
            rows.len()
        );
    }

    // Process results to build person mapping and collect any existing overrides
    let mut person_id_to_distinct_id = HashMap::new();
    let mut overrides = Vec::new();

    for row in rows {
        let person_id: PersonId = row.get("person_id");
        let distinct_id: String = row.get("distinct_id");

        person_id_to_distinct_id.insert(person_id, distinct_id);

        // Collect overrides where they exist
        if let (Ok(feature_flag_key), Ok(hash_key)) = (
            row.try_get::<String, _>("feature_flag_key"),
            row.try_get::<String, _>("hash_key"),
        ) {
            overrides.push((feature_flag_key, hash_key, person_id));
        }
    }

    // Sort and process overrides, with the distinct_id at the start of the array having priority
    // We want the highest priority to go last in sort order, so it's the latest update in the hashmap
    let mut sorted_overrides = overrides;
    if !distinct_id_and_hash_key_override.is_empty() {
        sorted_overrides.sort_by_key(|(_, _, person_id)| {
            if person_id_to_distinct_id.get(person_id)
                == Some(&distinct_id_and_hash_key_override[0])
            {
                std::cmp::Ordering::Greater
            } else {
                std::cmp::Ordering::Less
            }
        });
    }

    for (feature_flag_key, hash_key, _) in sorted_overrides {
        feature_flag_hash_key_overrides.insert(feature_flag_key, hash_key);
    }

    let total_duration = function_start.elapsed();
    if total_duration.as_millis() > config.flag_query_slow_error_threshold_ms as u128 {
        error!(
            "CRITICAL: Hash key override retrieval took {}ms! team_id={}, distinct_ids={}, overrides_found={}",
            total_duration.as_millis(),
            team_id,
            distinct_id_and_hash_key_override.len(),
            feature_flag_hash_key_overrides.len()
        );
    } else if total_duration.as_millis() > config.flag_query_slow_warn_threshold_ms as u128 {
        warn!(
            "Slow hash key override retrieval: {}ms for team_id={}, distinct_ids={}",
            total_duration.as_millis(),
            team_id,
            distinct_id_and_hash_key_override.len()
        );
    }

    Ok(feature_flag_hash_key_overrides)
}

/// Sets feature flag hash key overrides for a list of distinct IDs.
///
/// This function creates hash key overrides for all active feature flags that have
/// experience continuity enabled. It includes retry logic for handling race conditions
/// with person deletions.
pub async fn set_feature_flag_hash_key_overrides(
    router: &PostgresRouter,
    team_id: TeamId,
    distinct_ids: Vec<String>,
    project_id: ProjectId,
    hash_key_override: String,
    config: &Config,
) -> Result<bool, FlagError> {
    let retry_strategy = ExponentialBackoff::from_millis(100)
        .max_delay(Duration::from_millis(300))
        .take(2)
        .map(jitter); // Add jitter to prevent thundering herd

    // Use tokio-retry to automatically retry on transient failures
    Retry::spawn(retry_strategy, || async {
        let result = try_set_feature_flag_hash_key_overrides(
            router,
            team_id,
            &distinct_ids,
            project_id,
            &hash_key_override,
            config,
        )
        .await;

        // Only retry on foreign key constraint errors (person deletion race condition)
        match &result {
            Err(e) if flag_error_is_foreign_key_constraint(e) => {
                // Increment retry counter for monitoring
                common_metrics::inc(
                    FLAG_HASH_KEY_RETRIES_COUNTER,
                    &[
                        ("team_id".to_string(), team_id.to_string()),
                        (
                            "operation".to_string(),
                            "set_hash_key_overrides".to_string(),
                        ),
                    ],
                    1,
                );

                tracing::info!(
                    team_id = %team_id,
                    distinct_ids = ?distinct_ids,
                    error = ?e,
                    "Hash key override setting failed due to person deletion, will retry"
                );

                // Return error to trigger retry
                result
            }
            // For other errors, don't retry - return immediately to stop retrying
            Err(_) => result,
            // Success case - return the result
            Ok(_) => result,
        }
    })
    .await
}

/// Internal function that performs the actual hash key override setting.
/// This is separated to make it easy to retry with tokio-retry.
#[instrument(skip_all, fields(
    team_id = %team_id,
    distinct_ids = ?distinct_ids,
    project_id = %project_id
))]
async fn try_set_feature_flag_hash_key_overrides(
    router: &PostgresRouter,
    team_id: TeamId,
    distinct_ids: &[String],
    project_id: ProjectId,
    hash_key_override: &str,
    config: &Config,
) -> Result<bool, FlagError> {
    let function_start = Instant::now();
    // Get connection from persons writer for the transaction
    let persons_labels = [
        ("pool".to_string(), "persons_writer".to_string()),
        (
            "operation".to_string(),
            "set_feature_flag_hash_key_overrides".to_string(),
        ),
    ];
    let persons_conn_timer = common_metrics::timing_guard(FLAG_DB_CONNECTION_TIME, &persons_labels);
    let mut persons_conn = router.get_persons_writer().get_connection().await?;
    persons_conn_timer.fin();
    let mut transaction = persons_conn.begin().await?;

    // Query 1: Get all person data - person_ids + existing overrides + validation (person pool)
    let person_data_query = r#"
            SELECT DISTINCT
                p.person_id,
                p.distinct_id,
                existing.feature_flag_key
            FROM posthog_persondistinctid p
            LEFT JOIN posthog_featureflaghashkeyoverride existing
                ON existing.person_id = p.person_id AND existing.team_id = p.team_id
            WHERE p.team_id = $1
                AND p.distinct_id = ANY($2)
                AND EXISTS (SELECT 1 FROM posthog_person WHERE id = p.person_id AND team_id = p.team_id)
        "#;

    // Query 2: Get all active feature flags with experience continuity (non-person pool)
    let flags_query = r#"
            SELECT flag.key
            FROM posthog_featureflag flag
            JOIN posthog_team team ON flag.team_id = team.id
            WHERE team.project_id = $1
                AND flag.ensure_experience_continuity = TRUE
                AND flag.active = TRUE
                AND flag.deleted = FALSE
        "#;

    // Query 3: Bulk insert hash key overrides (person pool)
    let bulk_insert_query = r#"
            INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
            SELECT $1, person_id, flag_key, $2
            FROM UNNEST($3::bigint[], $4::text[]) AS t(person_id, flag_key)
            ON CONFLICT DO NOTHING
        "#;

    let result: Result<u64, FlagError> = async {
        // Step 1: Get all person data (person_ids + existing overrides + validation)
        let person_query_labels = [
            (
                "query".to_string(),
                "person_data_with_overrides".to_string(),
            ),
            (
                "operation".to_string(),
                "set_hash_key_overrides".to_string(),
            ),
        ];
        let person_query_timer =
            common_metrics::timing_guard(FLAG_PERSON_QUERY_TIME, &person_query_labels);

        let person_query_start = Instant::now();
        let person_data_rows = sqlx::query(person_data_query)
            .bind(team_id)
            .bind(distinct_ids)
            .fetch_all(&mut *transaction)
            .await
            .map_err(FlagError::from)?;
        person_query_timer.fin();

        let person_query_duration = person_query_start.elapsed();
        if person_query_duration.as_millis() > config.flag_query_slow_warn_threshold_ms as u128 {
            warn!(
                "Slow person data query in hash key override set: {}ms for team_id={}, distinct_ids={}",
                person_query_duration.as_millis(),
                team_id,
                distinct_ids.len()
            );
        }

        if person_data_rows.is_empty() {
            return Ok(0); // No persons found, nothing to insert
        }

        // Process person data - collect person_ids and existing overrides
        let mut person_ids = HashSet::new();
        let mut existing_overrides = HashSet::new();

        for row in person_data_rows {
            let person_id: i64 = row.get("person_id");
            person_ids.insert(person_id);

            // Handle existing overrides (can be NULL from LEFT JOIN)
            if let Ok(flag_key) = row.try_get::<String, _>("feature_flag_key") {
                existing_overrides.insert((person_id, flag_key));
            }
        }

        let person_ids_vec: Vec<i64> = person_ids.into_iter().collect();

        // Step 2: Get active feature flags (from non-person pool)
        // Get separate connection for non-persons query
        let non_persons_labels = [
            ("pool".to_string(), "non_persons_reader".to_string()),
            (
                "operation".to_string(),
                "set_feature_flag_hash_key_overrides".to_string(),
            ),
        ];
        let non_persons_conn_timer =
            common_metrics::timing_guard(FLAG_DB_CONNECTION_TIME, &non_persons_labels);
        let mut non_persons_conn = router
            .get_non_persons_reader()
            .get_connection()
            .await
            .map_err(|e| {
                sqlx::Error::Configuration(
                    format!("Failed to acquire non-persons connection: {e}").into(),
                )
            })?;
        non_persons_conn_timer.fin();

        let flags_labels = [
            (
                "query".to_string(),
                "active_flags_with_continuity".to_string(),
            ),
            (
                "operation".to_string(),
                "set_hash_key_overrides".to_string(),
            ),
        ];
        let flags_query_timer =
            common_metrics::timing_guard(FLAG_DEFINITION_QUERY_TIME, &flags_labels);

        let flags_query_start = Instant::now();
        let flag_rows = sqlx::query(flags_query)
            .bind(project_id)
            .fetch_all(&mut *non_persons_conn)
            .await
            .map_err(FlagError::from)?;
        flags_query_timer.fin();

        let flags_query_duration = flags_query_start.elapsed();
        if flags_query_duration.as_millis() > config.flag_query_slow_warn_threshold_ms as u128 {
            warn!(
                "Slow flags query in hash key override set: {}ms for project_id={}",
                flags_query_duration.as_millis(),
                project_id
            );
        }

        let flag_keys: Vec<String> = flag_rows
            .iter()
            .map(|row| row.get::<String, _>("key"))
            .collect();

        if flag_keys.is_empty() {
            return Ok(0); // No flags to override
        }

        // Step 3: Build values for bulk insert
        // Create all person-flag combinations that need to be inserted
        let values_to_insert: Vec<(i64, String)> = person_ids_vec
            .iter()
            .flat_map(|pid| flag_keys.iter().map(move |fk| (*pid, fk.clone())))
            .filter(|(pid, fk)| {
                // Skip if override already exists
                !existing_overrides.contains(&(*pid, fk.clone()))
            })
            .collect();

        if values_to_insert.is_empty() {
            return Ok(0); // Nothing to insert
        }

        // Separate the tuples into parallel arrays for UNNEST
        let (person_ids_to_insert, flag_keys_to_insert): (Vec<i64>, Vec<String>) =
            values_to_insert.into_iter().unzip();

        // Step 4: Bulk insert (person pool)
        let insert_labels = [
            ("query".to_string(), "bulk_insert_overrides".to_string()),
            (
                "operation".to_string(),
                "set_hash_key_overrides".to_string(),
            ),
        ];
        let insert_timer = common_metrics::timing_guard(FLAG_PERSON_QUERY_TIME, &insert_labels);

        let insert_start = Instant::now();
        info!(
            "Bulk inserting hash key overrides: {} records for team_id={}",
            person_ids_to_insert.len(),
            team_id
        );

        let result = sqlx::query(bulk_insert_query)
            .bind(team_id)
            .bind(hash_key_override)
            .bind(&person_ids_to_insert)
            .bind(&flag_keys_to_insert)
            .execute(&mut *transaction)
            .await
            .map_err(FlagError::from)?;
        insert_timer.fin();

        let insert_duration = insert_start.elapsed();
        if insert_duration.as_millis() > config.flag_query_slow_error_threshold_ms as u128 {
            error!(
                "CRITICAL: Bulk insert took {}ms! team_id={}, records={}",
                insert_duration.as_millis(),
                team_id,
                person_ids_to_insert.len()
            );
        } else if insert_duration.as_millis() > config.flag_query_slow_warn_threshold_ms as u128 {
            warn!(
                "Slow bulk insert: {}ms for team_id={}, records={}",
                insert_duration.as_millis(),
                team_id,
                person_ids_to_insert.len()
            );
        }

        Ok(result.rows_affected())
    }
    .await;

    let total_duration = function_start.elapsed();

    match result {
        Ok(rows_affected) => {
            // Commit the transaction if successful
            let commit_start = Instant::now();
            transaction.commit().await.map_err(|e| {
                FlagError::DatabaseError(e, Some("Failed to commit transaction".to_string()))
            })?;

            let commit_duration = commit_start.elapsed();
            if commit_duration.as_millis() > config.flag_query_slow_warn_threshold_ms as u128 {
                warn!(
                    "Slow transaction commit: {}ms for team_id={}",
                    commit_duration.as_millis(),
                    team_id
                );
            }

            if total_duration.as_millis() > config.flag_total_execution_error_threshold_ms as u128 {
                error!(
                    "CRITICAL: Total hash key override set took {}ms! team_id={}, distinct_ids={}, rows_affected={}",
                    total_duration.as_millis(),
                    team_id,
                    distinct_ids.len(),
                    rows_affected
                );
            } else if total_duration.as_millis()
                > config.flag_total_execution_warn_threshold_ms as u128
            {
                warn!(
                    "Slow hash key override set: {}ms for team_id={}, distinct_ids={}",
                    total_duration.as_millis(),
                    team_id,
                    distinct_ids.len()
                );
            }

            Ok(rows_affected > 0)
        }
        Err(e) => {
            // Rollback the transaction on error
            transaction.rollback().await.map_err(|e| {
                FlagError::DatabaseError(e, Some("Failed to rollback transaction".to_string()))
            })?;
            Err(e)
        }
    }
}

/// Checks if hash key overrides should be written for a given distinct ID.
///
/// This function determines if there are any active feature flags with experience
/// continuity enabled that don't already have hash key overrides for the given
/// distinct ID.
pub async fn should_write_hash_key_override(
    router: &PostgresRouter,
    team_id: TeamId,
    distinct_id: String,
    project_id: ProjectId,
    hash_key_override: String,
) -> Result<bool, FlagError> {
    let retry_strategy = ExponentialBackoff::from_millis(100)
        .max_delay(Duration::from_millis(300))
        .take(2)
        .map(jitter); // Add jitter to prevent thundering herd

    let distinct_ids = vec![distinct_id.clone(), hash_key_override.clone()];

    // Use tokio-retry to automatically retry on transient failures
    Retry::spawn(retry_strategy, || async {
        let result =
            try_should_write_hash_key_override(router, team_id, &distinct_ids, project_id).await;

        // Only retry on foreign key constraint errors (person deletion race condition)
        match &result {
            Err(e) if flag_error_is_foreign_key_constraint(e) => {
                // Increment retry counter for monitoring
                common_metrics::inc(
                    FLAG_HASH_KEY_RETRIES_COUNTER,
                    &[
                        ("team_id".to_string(), team_id.to_string()),
                        (
                            "operation".to_string(),
                            "should_write_hash_key_override".to_string(),
                        ),
                    ],
                    1,
                );

                tracing::info!(
                    team_id = %team_id,
                    distinct_id = %distinct_id,
                    error = ?e,
                    "Hash key override check failed due to person deletion, will retry"
                );

                // Return error to trigger retry
                result
            }
            // For other errors, don't retry - return immediately to stop retrying
            Err(_) => result,
            // Success case - return the result
            Ok(_) => result,
        }
    })
    .await
}

/// Internal function that performs the actual hash key override check.
/// This is separated to make it easy to retry with tokio-retry.
async fn try_should_write_hash_key_override(
    router: &PostgresRouter,
    team_id: TeamId,
    distinct_ids: &[String],
    project_id: ProjectId,
) -> Result<bool, FlagError> {
    const QUERY_TIMEOUT: Duration = Duration::from_millis(1000);
    let operation_start = Instant::now();

    // Query 1: Get person_ids and existing overrides from person pool in one shot
    let person_data_query = r#"
        SELECT DISTINCT
            p.person_id,
            existing.feature_flag_key
        FROM posthog_persondistinctid p
        LEFT JOIN posthog_featureflaghashkeyoverride existing
            ON existing.person_id = p.person_id AND existing.team_id = p.team_id
        WHERE p.team_id = $1 AND p.distinct_id = ANY($2)
    "#;

    // Query 2: Get feature flags from non-person pool
    let flags_query = r#"
        SELECT key FROM posthog_featureflag flag
        JOIN posthog_team team ON flag.team_id = team.id
        WHERE team.project_id = $1
            AND flag.ensure_experience_continuity = TRUE
            AND flag.active = TRUE
            AND flag.deleted = FALSE
    "#;

    let result = timeout(QUERY_TIMEOUT, async {
        // Log pool states before attempting connections
        let persons_reader_stats = router.get_persons_reader().get_pool_stats();
        let non_persons_reader_stats = router.get_non_persons_reader().get_pool_stats();

        if let (Some(pr_stats), Some(npr_stats)) = (&persons_reader_stats, &non_persons_reader_stats) {
            let pr_utilization = (pr_stats.size - pr_stats.num_idle as u32) as f64 / pr_stats.size as f64;
            let npr_utilization = (npr_stats.size - npr_stats.num_idle as u32) as f64 / npr_stats.size as f64;

            if pr_utilization > 0.8 || npr_utilization > 0.8 {
                warn!(
                    team_id = %team_id,
                    distinct_ids = ?distinct_ids,
                    persons_reader_pool_size = pr_stats.size,
                    persons_reader_idle = pr_stats.num_idle,
                    persons_reader_utilization_pct = pr_utilization * 100.0,
                    non_persons_reader_pool_size = npr_stats.size,
                    non_persons_reader_idle = npr_stats.num_idle,
                    non_persons_reader_utilization_pct = npr_utilization * 100.0,
                    "High pool utilization before should_write_hash_key_override"
                );
            }

            common_metrics::gauge(
                FLAG_POOL_UTILIZATION_GAUGE,
                &[("pool".to_string(), "persons_reader".to_string())],
                pr_utilization,
            );
            common_metrics::gauge(
                FLAG_POOL_UTILIZATION_GAUGE,
                &[("pool".to_string(), "non_persons_reader".to_string())],
                npr_utilization,
            );
        }

        // Get connection from persons pool for person data
        let persons_labels = [
            ("pool".to_string(), "persons_reader".to_string()),
            (
                "operation".to_string(),
                "should_write_hash_key_override".to_string()),
        ];
        let persons_conn_start = Instant::now();
        let persons_conn_timer =
            common_metrics::timing_guard(FLAG_DB_CONNECTION_TIME, &persons_labels);
        let mut persons_conn = router
            .get_persons_reader()
            .get_connection()
            .await
            .map_err(FlagError::from)?;
        persons_conn_timer.fin();
        let persons_conn_acquisition_time = persons_conn_start.elapsed();

        if persons_conn_acquisition_time > Duration::from_millis(100) {
            warn!(
                team_id = %team_id,
                pool = "persons_reader",
                acquisition_ms = persons_conn_acquisition_time.as_millis(),
                "Slow connection acquisition from persons_reader pool"
            );
        }

        // Step 1: Get person data and existing overrides
        let person_query_labels = [
            (
                "query".to_string(),
                "person_data_with_overrides".to_string(),
            ),
            ("operation".to_string(), "should_write_check".to_string()),
        ];
        let person_query_timer =
            common_metrics::timing_guard(FLAG_PERSON_QUERY_TIME, &person_query_labels);
        let person_data_rows = sqlx::query(person_data_query)
            .bind(team_id)
            .bind(distinct_ids)
            .fetch_all(&mut *persons_conn)
            .await
            .map_err(|e| {
                FlagError::DatabaseError(e, Some("Failed to fetch person data".to_string()))
            })?;
        person_query_timer.fin();

        // If no person_ids found, there's nothing to check
        if person_data_rows.is_empty() {
            return Ok(false);
        }

        // Extract existing flag keys from overrides
        let existing_flag_keys: HashSet<String> = person_data_rows
            .iter()
            .filter_map(|row| row.try_get::<String, _>("feature_flag_key").ok())
            .collect();

        // Step 2: Get active feature flags with experience continuity from non-persons pool
        // Get connection from non-persons pool for flag data
        let non_persons_labels = [
            ("pool".to_string(), "non_persons_reader".to_string()),
            (
                "operation".to_string(),
                "should_write_hash_key_override".to_string(),
            ),
        ];

        // Log that we're holding one connection while acquiring another
        info!(
            team_id = %team_id,
            persons_conn_held_ms = persons_conn_start.elapsed().as_millis(),
            "Acquiring non_persons_reader connection while holding persons_reader connection"
        );

        let non_persons_conn_start = Instant::now();
        let non_persons_conn_timer =
            common_metrics::timing_guard(FLAG_DB_CONNECTION_TIME, &non_persons_labels);
        let mut non_persons_conn = router
            .get_non_persons_reader()
            .get_connection()
            .await
            .map_err(FlagError::from)?;
        non_persons_conn_timer.fin();
        let non_persons_conn_acquisition_time = non_persons_conn_start.elapsed();

        if non_persons_conn_acquisition_time > Duration::from_millis(100) {
            warn!(
                team_id = %team_id,
                pool = "non_persons_reader",
                acquisition_ms = non_persons_conn_acquisition_time.as_millis(),
                persons_conn_held_ms = persons_conn_start.elapsed().as_millis(),
                "Slow connection acquisition from non_persons_reader pool while holding persons_reader connection"
            );
        }
        let flags_labels = [
            (
                "query".to_string(),
                "active_flags_with_continuity".to_string(),
            ),
            ("operation".to_string(), "should_write_check".to_string()),
        ];
        let flags_query_timer =
            common_metrics::timing_guard(FLAG_DEFINITION_QUERY_TIME, &flags_labels);
        let flag_rows = sqlx::query(flags_query)
            .bind(project_id)
            .fetch_all(&mut *non_persons_conn)
            .await
            .map_err(|e| FlagError::DatabaseError(e, Some("Failed to fetch flags".to_string())))?;
        flags_query_timer.fin();

        // Check if there are any flags that don't have overrides
        for row in flag_rows {
            let flag_key: String = row.get("key");
            if !existing_flag_keys.contains(&flag_key) {
                return Ok(true); // Found a flag without override
            }
        }

        // Record how long both connections were held
        common_metrics::histogram(
            FLAG_CONNECTION_HOLD_TIME,
            &[
                ("pool".to_string(), "persons_reader".to_string()),
                ("operation".to_string(), "should_write_check".to_string()),
            ],
            persons_conn_start.elapsed().as_millis() as f64,
        );

        Ok::<bool, FlagError>(false) // All flags have overrides
    })
    .await;

    let total_operation_time = operation_start.elapsed();

    match result {
        Ok(Ok(flags_present)) => {
            if total_operation_time > Duration::from_millis(500) {
                warn!(
                    team_id = %team_id,
                    distinct_ids = ?distinct_ids,
                    operation_ms = total_operation_time.as_millis(),
                    result = flags_present,
                    "Slow should_write_hash_key_override operation completed"
                );
            }
            Ok(flags_present)
        }
        Ok(Err(e)) => {
            tracing::error!(
                team_id = %team_id,
                distinct_ids = ?distinct_ids,
                operation_ms = total_operation_time.as_millis(),
                error = ?e,
                "should_write_hash_key_override failed with error"
            );
            Err(e)
        }
        Err(_) => {
            // Capture all pool states on timeout
            let persons_reader_stats = router.get_persons_reader().get_pool_stats();
            let non_persons_reader_stats = router.get_non_persons_reader().get_pool_stats();
            let persons_writer_stats = router.get_persons_writer().get_pool_stats();
            let non_persons_writer_stats = router.get_non_persons_writer().get_pool_stats();

            tracing::error!(
                team_id = %team_id,
                distinct_ids = ?distinct_ids,
                timeout_after_ms = QUERY_TIMEOUT.as_millis(),
                operation_elapsed_ms = total_operation_time.as_millis(),
                persons_reader_pool = ?persons_reader_stats,
                non_persons_reader_pool = ?non_persons_reader_stats,
                persons_writer_pool = ?persons_writer_stats,
                non_persons_writer_pool = ?non_persons_writer_stats,
                "should_write_hash_key_override timed out - capturing all pool states"
            );

            // Emit metrics for timeout with pool states
            if let Some(stats) = persons_writer_stats {
                common_metrics::inc(
                    FLAG_READER_TIMEOUT_WITH_WRITER_STATE_COUNTER,
                    &[
                        (
                            "writer_pool_busy".to_string(),
                            (stats.num_idle == 0).to_string(),
                        ),
                        (
                            "writer_utilization_pct".to_string(),
                            ((((stats.size - stats.num_idle as u32) as f64 / stats.size as f64)
                                * 100.0) as i64)
                                .to_string(),
                        ),
                    ],
                    1,
                );
            }

            Err(FlagError::TimeoutError(Some("query_timeout".to_string())))
        }
    }
}

#[cfg(test)]
pub fn get_fetch_calls_count() -> usize {
    FETCH_CALLS.with(|counter| *counter.borrow())
}

#[cfg(test)]
pub fn reset_fetch_calls_count() {
    FETCH_CALLS.with(|counter| *counter.borrow_mut() = 0);
}

#[cfg(test)]
pub fn increment_fetch_calls_count() {
    FETCH_CALLS.with(|counter| *counter.borrow_mut() += 1);
}

#[cfg(test)]
mod tests {
    use rstest::rstest;
    use serde_json::json;

    use crate::{
        flags::flag_models::{FeatureFlagRow, FlagFilters},
        properties::property_models::{OperatorType, PropertyFilter, PropertyType},
        utils::test_utils::{create_test_flag, TestContext},
    };

    use super::*;

    #[tokio::test]
    async fn test_set_feature_flag_hash_key_overrides_success() {
        let context = TestContext::new(None).await;
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "user2".to_string();

        // Insert person
        context
            .insert_person(team.id, distinct_id.clone(), None)
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
                holdout_groups: None,
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
            version: flag.version,
            evaluation_runtime: flag.evaluation_runtime,
            evaluation_tags: flag.evaluation_tags,
        };

        // Insert the feature flag into the database
        context.insert_flag(team.id, Some(flag_row)).await.unwrap();

        // Set hash key override
        let router = context.create_postgres_router();
        set_feature_flag_hash_key_overrides(
            &router,
            team.id,
            vec![distinct_id.clone()],
            team.project_id,
            "hash_key_2".to_string(),
            &context.config,
        )
        .await
        .unwrap();

        // Retrieve hash key overrides
        let overrides = context
            .get_feature_flag_hash_key_overrides(team.id, vec![distinct_id.clone()])
            .await
            .unwrap();

        assert_eq!(
            overrides.get("test_flag"),
            Some(&"hash_key_2".to_string()),
            "Hash key override should match the set value"
        );
    }

    #[tokio::test]
    async fn test_set_feature_flag_hash_key_overrides_with_multiple_persons() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Create 3 persons
        let person1_id = context
            .insert_person(
                team.id,
                "batch_user1".to_string(),
                Some(json!({"email": "user1@example.com"})),
            )
            .await
            .expect("Failed to insert person1");

        let _person2_id = context
            .insert_person(
                team.id,
                "batch_user2".to_string(),
                Some(json!({"email": "user2@example.com"})),
            )
            .await
            .expect("Failed to insert person2");

        let _person3_id = context
            .insert_person(
                team.id,
                "batch_user3".to_string(),
                Some(json!({"email": "user3@example.com"})),
            )
            .await
            .expect("Failed to insert person3");

        // Add additional distinct_id for person1 to test multiple distinct_ids per person
        let mut conn = context
            .get_persons_connection()
            .await
            .expect("Failed to get connection");
        let mut transaction = conn.begin().await.expect("Failed to begin transaction");

        sqlx::query(
            "INSERT INTO posthog_persondistinctid (team_id, person_id, distinct_id, version)
             VALUES ($1, $2, $3, 0)",
        )
        .bind(team.id)
        .bind(person1_id)
        .bind("batch_user1_alt")
        .execute(&mut *transaction)
        .await
        .expect("Failed to add alt distinct_id");

        transaction
            .commit()
            .await
            .expect("Failed to commit transaction");

        // Create 4 feature flags with experience continuity
        for i in 1..=4 {
            let flag_row = FeatureFlagRow {
                id: 10000 + i,
                team_id: team.id,
                name: Some(format!("Batch Test Flag {i}")),
                key: format!("batch_flag_{i}"),
                filters: json!({"groups": [{"rollout_percentage": 50}]}),
                deleted: false,
                active: true,
                ensure_experience_continuity: Some(true),
                version: Some(1),
                evaluation_runtime: None,
                evaluation_tags: None,
            };
            context
                .insert_flag(team.id, Some(flag_row))
                .await
                .unwrap_or_else(|_| panic!("Failed to insert flag {i}"));
        }

        // Test batch insert with 4 distinct_ids (3 persons, 1 with alt)
        let distinct_ids = vec![
            "batch_user1".to_string(),
            "batch_user1_alt".to_string(),
            "batch_user2".to_string(),
            "batch_user3".to_string(),
        ];
        let hash_key = "batch_hash_key".to_string();

        let router = context.create_postgres_router();
        let result = set_feature_flag_hash_key_overrides(
            &router,
            team.id,
            distinct_ids.clone(),
            team.project_id,
            hash_key.clone(),
            &context.config,
        )
        .await
        .expect("Failed to set hash key overrides");

        assert!(result, "Should have written overrides");

        // Verify all combinations were created correctly
        // Should create overrides for all distinct_ids
        for distinct_id in &distinct_ids {
            let overrides = context
                .get_feature_flag_hash_key_overrides(team.id, vec![distinct_id.clone()])
                .await
                .unwrap_or_else(|_| panic!("Failed to get overrides for {distinct_id}"));

            assert_eq!(
                overrides.len(),
                4,
                "Should have 4 overrides for distinct_id {distinct_id}"
            );

            for i in 1..=4 {
                let flag_key = format!("batch_flag_{i}");
                assert_eq!(
                    overrides.get(&flag_key),
                    Some(&hash_key),
                    "Override for {flag_key} should be set for distinct_id {distinct_id}"
                );
            }
        }

        // Verify the actual count in the database
        // batch_user1 and batch_user1_alt map to same person, so 3 persons * 4 flags = 12 overrides
        let mut conn = context
            .get_persons_connection()
            .await
            .expect("Failed to get connection");
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM posthog_featureflaghashkeyoverride
             WHERE team_id = $1 AND hash_key = $2",
        )
        .bind(team.id)
        .bind(&hash_key)
        .fetch_one(&mut *conn)
        .await
        .expect("Failed to count overrides");

        assert_eq!(
            count, 12,
            "Should have exactly 12 overrides in database (3 persons * 4 flags)"
        );
    }

    #[tokio::test]
    async fn test_set_feature_flag_hash_key_overrides_with_with_existing_overrides() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Create 2 persons
        let person1_id = context
            .insert_person(
                team.id,
                "existing_user1".to_string(),
                Some(json!({"email": "existing1@example.com"})),
            )
            .await
            .expect("Failed to insert person1");

        let _person2_id = context
            .insert_person(
                team.id,
                "existing_user2".to_string(),
                Some(json!({"email": "existing2@example.com"})),
            )
            .await
            .expect("Failed to insert person2");

        // Create 3 flags
        for i in 1..=3 {
            let flag_row = FeatureFlagRow {
                id: 20000 + i,
                team_id: team.id,
                name: Some(format!("Existing Test Flag {i}")),
                key: format!("existing_flag_{i}"),
                filters: json!({"groups": [{"rollout_percentage": 50}]}),
                deleted: false,
                active: true,
                ensure_experience_continuity: Some(true),
                version: Some(1),
                evaluation_runtime: None,
                evaluation_tags: None,
            };
            context
                .insert_flag(team.id, Some(flag_row))
                .await
                .unwrap_or_else(|_| panic!("Failed to insert flag {i}"));
        }

        // Manually insert some existing overrides
        let mut conn = context
            .get_persons_connection()
            .await
            .expect("Failed to get connection");
        let mut transaction = conn.begin().await.expect("Failed to begin transaction");

        // Person1 has override for flag 1
        sqlx::query(
            "INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
             VALUES ($1, $2, $3, $4)",
        )
        .bind(team.id)
        .bind(person1_id)
        .bind("existing_flag_1")
        .bind("old_hash")
        .execute(&mut *transaction)
        .await
        .expect("Failed to insert existing override");

        transaction
            .commit()
            .await
            .expect("Failed to commit transaction");

        // Try batch insert - should only insert the missing combinations
        let distinct_ids = vec!["existing_user1".to_string(), "existing_user2".to_string()];
        let new_hash = "new_batch_hash".to_string();

        let router = context.create_postgres_router();
        let result = set_feature_flag_hash_key_overrides(
            &router,
            team.id,
            distinct_ids.clone(),
            team.project_id,
            new_hash.clone(),
            &context.config,
        )
        .await
        .expect("Failed to set hash key overrides");

        assert!(result, "Should have written new overrides");

        // Verify existing overrides are preserved
        let overrides1 = context
            .get_feature_flag_hash_key_overrides(team.id, vec!["existing_user1".to_string()])
            .await
            .expect("Failed to get overrides");

        assert_eq!(
            overrides1.get("existing_flag_1"),
            Some(&"old_hash".to_string()),
            "Existing override should be preserved"
        );
        assert_eq!(
            overrides1.get("existing_flag_2"),
            Some(&new_hash),
            "New override should be added for flag 2"
        );
        assert_eq!(
            overrides1.get("existing_flag_3"),
            Some(&new_hash),
            "New override should be added for flag 3"
        );

        // Verify the count - should have 6 total (2 existing + 4 new)
        let mut conn = context
            .get_persons_connection()
            .await
            .expect("Failed to get connection");
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM posthog_featureflaghashkeyoverride WHERE team_id = $1",
        )
        .bind(team.id)
        .fetch_one(&mut *conn)
        .await
        .expect("Failed to count overrides");

        assert_eq!(
            count, 6,
            "Should have 6 total overrides (2 existing + 4 new)"
        );
    }

    #[tokio::test]
    async fn test_set_overrides_filters_inactive_and_deleted_flags() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Create a person
        context
            .insert_person(
                team.id,
                "filter_test_user".to_string(),
                Some(json!({"email": "filter@example.com"})),
            )
            .await
            .expect("Failed to insert person");

        // Create various flags with different states
        let active_flag = FeatureFlagRow {
            id: 50001,
            team_id: team.id,
            name: Some("Active Flag".to_string()),
            key: "active_flag".to_string(),
            filters: json!({"groups": [{"rollout_percentage": 50}]}),
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(true),
            version: Some(1),
            evaluation_runtime: None,
            evaluation_tags: None,
        };

        let inactive_flag = FeatureFlagRow {
            id: 50002,
            team_id: team.id,
            name: Some("Inactive Flag".to_string()),
            key: "inactive_flag".to_string(),
            filters: json!({"groups": [{"rollout_percentage": 50}]}),
            deleted: false,
            active: false, // NOT active
            ensure_experience_continuity: Some(true),
            version: Some(1),
            evaluation_runtime: None,
            evaluation_tags: None,
        };

        let deleted_flag = FeatureFlagRow {
            id: 50003,
            team_id: team.id,
            name: Some("Deleted Flag".to_string()),
            key: "deleted_flag".to_string(),
            filters: json!({"groups": [{"rollout_percentage": 50}]}),
            deleted: true, // Deleted
            active: true,
            ensure_experience_continuity: Some(true),
            version: Some(1),
            evaluation_runtime: None,
            evaluation_tags: None,
        };

        let no_continuity_flag = FeatureFlagRow {
            id: 50004,
            team_id: team.id,
            name: Some("No Continuity Flag".to_string()),
            key: "no_continuity_flag".to_string(),
            filters: json!({"groups": [{"rollout_percentage": 50}]}),
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false), // No experience continuity
            version: Some(1),
            evaluation_runtime: None,
            evaluation_tags: None,
        };

        context
            .insert_flag(team.id, Some(active_flag))
            .await
            .expect("Failed to insert active flag");
        context
            .insert_flag(team.id, Some(inactive_flag))
            .await
            .expect("Failed to insert inactive flag");
        context
            .insert_flag(team.id, Some(deleted_flag))
            .await
            .expect("Failed to insert deleted flag");
        context
            .insert_flag(team.id, Some(no_continuity_flag))
            .await
            .expect("Failed to insert no continuity flag");

        // Set overrides
        let router = context.create_postgres_router();
        let result = set_feature_flag_hash_key_overrides(
            &router,
            team.id,
            vec!["filter_test_user".to_string()],
            team.project_id,
            "filter_hash".to_string(),
            &context.config,
        )
        .await
        .expect("Should not error");

        assert!(result, "Should have written override for active flag");

        // Verify only the active flag with experience continuity got an override
        let overrides = context
            .get_feature_flag_hash_key_overrides(team.id, vec!["filter_test_user".to_string()])
            .await
            .expect("Failed to get overrides");

        assert_eq!(overrides.len(), 1, "Should have exactly 1 override");
        assert_eq!(
            overrides.get("active_flag"),
            Some(&"filter_hash".to_string())
        );
        assert_eq!(
            overrides.get("inactive_flag"),
            None,
            "Inactive flag should not have override"
        );
        assert_eq!(
            overrides.get("deleted_flag"),
            None,
            "Deleted flag should not have override"
        );
        assert_eq!(
            overrides.get("no_continuity_flag"),
            None,
            "No continuity flag should not have override"
        );
    }

    #[tokio::test]
    async fn test_should_write_hash_key_override() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Create a person
        context
            .insert_person(
                team.id,
                "should_write_user".to_string(),
                Some(json!({"email": "should_write@example.com"})),
            )
            .await
            .expect("Failed to insert person");

        // Create a flag with experience continuity
        let flag_row = FeatureFlagRow {
            id: 60000,
            team_id: team.id,
            name: Some("Should Write Flag".to_string()),
            key: "should_write_flag".to_string(),
            filters: json!({"groups": [{"rollout_percentage": 50}]}),
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(true),
            version: Some(1),
            evaluation_runtime: None,
            evaluation_tags: None,
        };
        context
            .insert_flag(team.id, Some(flag_row))
            .await
            .expect("Failed to insert flag");

        // Test 1: Should return true when no overrides exist
        let router = context.create_postgres_router();
        let should_write = should_write_hash_key_override(
            &router,
            team.id,
            "should_write_user".to_string(),
            team.project_id,
            "hash_key_1".to_string(),
        )
        .await
        .expect("Should not error");

        assert!(should_write, "Should write when no overrides exist");

        // Now set an override
        let router = context.create_postgres_router();
        set_feature_flag_hash_key_overrides(
            &router,
            team.id,
            vec!["should_write_user".to_string()],
            team.project_id,
            "hash_key_1".to_string(),
            &context.config,
        )
        .await
        .expect("Failed to set override");

        // Test 2: Should return false when override exists
        let router = context.create_postgres_router();
        let should_write = should_write_hash_key_override(
            &router,
            team.id,
            "should_write_user".to_string(),
            team.project_id,
            "hash_key_1".to_string(),
        )
        .await
        .expect("Should not error");

        assert!(
            !should_write,
            "Should not write when override already exists"
        );

        // Test 3: Should return false for non-existent person
        let router = context.create_postgres_router();
        let should_write = should_write_hash_key_override(
            &router,
            team.id,
            "non_existent_user".to_string(),
            team.project_id,
            "hash_key_2".to_string(),
        )
        .await
        .expect("Should not error");

        assert!(!should_write, "Should not write for non-existent person");
    }

    #[tokio::test]
    async fn test_set_overrides_with_no_persons() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Create a flag but NO persons
        let flag_row = FeatureFlagRow {
            id: 70000,
            team_id: team.id,
            name: Some("No Person Flag".to_string()),
            key: "no_person_flag".to_string(),
            filters: json!({"groups": [{"rollout_percentage": 50}]}),
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(true),
            version: Some(1),
            evaluation_runtime: None,
            evaluation_tags: None,
        };
        context
            .insert_flag(team.id, Some(flag_row))
            .await
            .expect("Failed to insert flag");

        // Try to set overrides for non-existent distinct_ids
        let router = context.create_postgres_router();
        let result = set_feature_flag_hash_key_overrides(
            &router,
            team.id,
            vec![
                "nonexistent_user1".to_string(),
                "nonexistent_user2".to_string(),
            ],
            team.project_id,
            "some_hash".to_string(),
            &context.config,
        )
        .await
        .expect("Should not error even with non-existent users");

        assert!(!result, "Should return false when no persons found");

        // Verify no overrides were created
        let mut conn = context
            .get_persons_connection()
            .await
            .expect("Failed to get connection");
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM posthog_featureflaghashkeyoverride WHERE team_id = $1",
        )
        .bind(team.id)
        .fetch_one(&mut *conn)
        .await
        .expect("Failed to count overrides");

        assert_eq!(
            count, 0,
            "Should have no overrides when persons don't exist"
        );
    }

    #[rstest]
    #[case("some_distinct_id", 0.7270002403585725)]
    #[case("test-identifier", 0.4493881716040236)]
    #[case("example_id", 0.9402003475831224)]
    #[case("example_id2", 0.6292740389966519)]
    #[tokio::test]
    async fn test_calculate_hash(#[case] hashed_identifier: &str, #[case] expected_hash: f64) {
        let hash = calculate_hash("holdout-", hashed_identifier, "").unwrap();
        assert!(
            (hash - expected_hash).abs() < f64::EPSILON,
            "Hash {hash} should equal expected value {expected_hash} within floating point precision"
        );
    }

    #[tokio::test]
    async fn test_overrides_locally_computable() {
        let overrides = Some(HashMap::from([
            ("email".to_string(), json!("test@example.com")),
            ("age".to_string(), json!(30)),
        ]));

        // Test case 1: No cohort properties - should return overrides
        let property_filters = vec![
            PropertyFilter {
                key: "email".to_string(),
                value: Some(json!("test@example.com")),
                operator: None,
                prop_type: PropertyType::Person,
                group_type_index: None,
                negation: None,
            },
            PropertyFilter {
                key: "age".to_string(),
                value: Some(json!(25)),
                operator: Some(OperatorType::Gte),
                prop_type: PropertyType::Person,
                group_type_index: None,
                negation: None,
            },
        ];

        let result = locally_computable_property_overrides(&overrides, &property_filters);
        assert!(result.is_some());

        // Test case 2: Property filters include cohort - should return None
        let property_filters_with_cohort = vec![
            PropertyFilter {
                key: "email".to_string(),
                value: Some(json!("test@example.com")),
                operator: None,
                prop_type: PropertyType::Person,
                group_type_index: None,
                negation: None,
            },
            PropertyFilter {
                key: "cohort".to_string(),
                value: Some(json!(1)),
                operator: None,
                prop_type: PropertyType::Cohort,
                group_type_index: None,
                negation: None,
            },
        ];

        let result =
            locally_computable_property_overrides(&overrides, &property_filters_with_cohort);
        assert!(result.is_none());

        // Test case 3: Empty property filters - should return None (no properties needed)
        let empty_filters = vec![];
        let result = locally_computable_property_overrides(&overrides, &empty_filters);
        assert!(result.is_none());

        // Test case 4: Overrides contain some but not all properties from filters - should return None (no complete overlap)
        let property_filters_extra = vec![
            PropertyFilter {
                key: "email".to_string(),
                value: Some(json!("test@example.com")),
                operator: None,
                prop_type: PropertyType::Person,
                group_type_index: None,
                negation: None,
            },
            PropertyFilter {
                key: "missing_property".to_string(), // This property is NOT in overrides
                value: Some(json!("some_value")),
                operator: None,
                prop_type: PropertyType::Person,
                group_type_index: None,
                negation: None,
            },
        ];

        let result = locally_computable_property_overrides(&overrides, &property_filters_extra);
        assert!(result.is_some()); // Should return overrides because there's partial overlap (email)
        let returned_overrides = result.unwrap();
        assert!(returned_overrides.contains_key("email")); // email should be included
        assert!(returned_overrides.contains_key("age")); // age should also be included (all overrides returned)
        assert!(!returned_overrides.contains_key("missing_property")); // missing_property was not in original overrides
        assert_eq!(returned_overrides.len(), 2); // Both email and age should be returned
    }

    #[tokio::test]
    async fn test_person_property_overrides_bug_fix() {
        // This test specifically addresses the bug where person property overrides
        // were ignored if the flag didn't explicitly check for those properties.

        // Simulate sending an override for $feature_enrollment/discussions
        let overrides = Some(HashMap::from([
            ("$feature_enrollment/discussions".to_string(), json!(false)),
            ("email".to_string(), json!("user@example.com")),
        ]));

        // Simulate a flag that only checks for email, not $feature_enrollment/discussions
        let flag_property_filters = vec![PropertyFilter {
            key: "email".to_string(),
            value: Some(json!("user@example.com")),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        }];

        let result = locally_computable_property_overrides(&overrides, &flag_property_filters);
        assert!(result.is_some(), "Person property overrides should be returned even when flag doesn't check for all override properties");

        let returned_overrides = result.unwrap();
        assert_eq!(
            returned_overrides.get("$feature_enrollment/discussions"),
            Some(&json!(false)),
            "The $feature_enrollment/discussions override should be present"
        );
        assert_eq!(
            returned_overrides.get("email"),
            Some(&json!("user@example.com")),
            "The email override should be present"
        );
    }

    #[rstest]
    #[case("1", json!(true), FlagValue::Boolean(true), true)] // filter value true, flag_value is true, so true
    #[case("1", json!(true), FlagValue::Boolean(false), false)] // filter value true, flag_value is false, so false
    #[case("1", json!(true), FlagValue::String("some-variant".to_string()), true)]
    // filter value true, flag_value is "some-variant", so true (filter value true means flag value can be true or any variant)
    #[case("1", json!(true), FlagValue::String("other-variant".to_string()), true)] // filter value true, flag_value is "other-variant", so true (see above)
    #[case("1", json!(false), FlagValue::Boolean(false), true)] // filter value false, flag_value is false, so true
    #[case("1", json!(false), FlagValue::Boolean(true), false)] // filter value false, flag_value is true, so false
    #[case("1", json!(false), FlagValue::String("some-variant".to_string()), false)] // filter value false, flag_value is "some-variant", so false
    #[case("1", json!("some-variant"), FlagValue::String("some-variant".to_string()), true)] // flag value variant matches filter value variant, so true
    #[case("1", json!("some-variant"), FlagValue::String("other-variant".to_string()), false)] // flag value variant doesn't match filter value variant, so false
    #[case("1", json!("some-variant"), FlagValue::Boolean(true), false)] // even though flag value is true, it doesn't match the filter value variant, so false
    #[case("1", json!("some-variant"), FlagValue::Boolean(false), false)] // flag value is false and doesn't match the filter value variant, so false
    #[case("2", json!(true), FlagValue::Boolean(true), false)] // flag referenced by filter does not exist, so false
    #[tokio::test]
    async fn test_match_flag_filter_value(
        #[case] filter_flag_id: i32,
        #[case] filter_value: Value,
        #[case] flag_value: FlagValue,
        #[case] expected: bool,
    ) {
        let flag_evaluation_results = HashMap::from([(1, flag_value)]);

        let filter = PropertyFilter {
            key: filter_flag_id.to_string(),
            value: Some(filter_value),
            operator: Some(OperatorType::FlagEvaluatesTo),
            prop_type: PropertyType::Flag,
            negation: None,
            group_type_index: None,
        };

        let result = match_flag_value_to_flag_filter(&filter, &flag_evaluation_results);
        assert_eq!(result, expected);
    }

    #[tokio::test]
    async fn test_match_flag_value_to_flag_filter_returns_false_if_operator_is_not_exact() {
        let flag_evaluation_results = HashMap::from([(1, FlagValue::Boolean(true))]);

        let filter = PropertyFilter {
            key: "1".to_string(),
            value: Some(json!(true)),
            operator: Some(OperatorType::Icontains),
            prop_type: PropertyType::Flag,
            group_type_index: None,
            negation: None,
        };

        let result = match_flag_value_to_flag_filter(&filter, &flag_evaluation_results);
        assert!(!result);
    }

    #[tokio::test]
    async fn test_should_retry_on_error() {
        use sqlx::Error as SqlxError;

        // Test that database connection errors trigger retries
        let pool_timeout_error = FlagError::DatabaseError(SqlxError::PoolTimedOut, None);
        assert!(should_retry_on_error(&pool_timeout_error));

        let pool_closed_error = FlagError::DatabaseError(SqlxError::PoolClosed, None);
        assert!(should_retry_on_error(&pool_closed_error));

        let io_error = FlagError::DatabaseError(
            SqlxError::Io(std::io::Error::new(
                std::io::ErrorKind::ConnectionRefused,
                "connection refused",
            )),
            None,
        );
        assert!(should_retry_on_error(&io_error));

        // Test Protocol errors with connection issues
        let protocol_connection_error =
            FlagError::DatabaseError(SqlxError::Protocol("connection lost".to_string()), None);
        assert!(should_retry_on_error(&protocol_connection_error));

        let protocol_timeout_error =
            FlagError::DatabaseError(SqlxError::Protocol("operation timeout".to_string()), None);
        assert!(should_retry_on_error(&protocol_timeout_error));

        // Test that configuration errors don't trigger retries
        let config_error = FlagError::DatabaseError(
            SqlxError::Configuration("invalid connection string".into()),
            None,
        );
        assert!(!should_retry_on_error(&config_error));

        let column_error = FlagError::DatabaseError(
            SqlxError::ColumnNotFound("missing_column".to_string()),
            None,
        );
        assert!(!should_retry_on_error(&column_error));

        // Test that other error types don't trigger retries
        let timeout_error_variant = FlagError::TimeoutError(None);
        assert!(!should_retry_on_error(&timeout_error_variant));

        let missing_id_error = FlagError::MissingDistinctId;
        assert!(!should_retry_on_error(&missing_id_error));

        let row_not_found_error = FlagError::RowNotFound;
        assert!(!should_retry_on_error(&row_not_found_error));
    }
}
