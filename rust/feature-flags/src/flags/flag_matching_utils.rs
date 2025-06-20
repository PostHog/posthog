use std::collections::{HashMap, HashSet};

use common_types::{PersonId, ProjectId, TeamId};
use serde_json::Value;
use sha1::{Digest, Sha1};
use sqlx::{postgres::PgQueryResult, Acquire, Row};
use std::time::{Duration, Instant};
use tokio::time::{sleep, timeout};
use tracing::{info, warn};

use crate::{
    api::{errors::FlagError, types::FlagValue},
    cohorts::cohort_models::CohortId,
    flags::flag_models::FeatureFlagId,
    metrics::consts::{
        FLAG_COHORT_PROCESSING_TIME, FLAG_COHORT_QUERY_TIME, FLAG_DB_CONNECTION_TIME,
        FLAG_GROUP_PROCESSING_TIME, FLAG_GROUP_QUERY_TIME, FLAG_PERSON_PROCESSING_TIME,
        FLAG_PERSON_QUERY_TIME,
    },
    properties::{
        property_matching::match_property,
        property_models::{OperatorType, PropertyFilter, PropertyType},
    },
};

use super::{
    flag_group_type_mapping::GroupTypeIndex,
    flag_matching::{FlagEvaluationState, PostgresReader, PostgresWriter},
};

const LONG_SCALE: u64 = 0xfffffffffffffff;

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
    let hash_key = format!("{}{}{}", prefix, hashed_identifier, salt);
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
pub async fn fetch_and_locally_cache_all_relevant_properties(
    flag_evaluation_state: &mut FlagEvaluationState,
    reader: PostgresReader,
    distinct_id: String,
    team_id: TeamId,
    group_type_indexes: &HashSet<GroupTypeIndex>,
    group_keys: &HashSet<String>,
    static_cohort_ids: Vec<CohortId>,
) -> Result<(), FlagError> {
    let conn_timer = common_metrics::timing_guard(FLAG_DB_CONNECTION_TIME, &[]);
    let mut conn = reader.as_ref().get_connection().await?;
    conn_timer.fin();

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

    let person_query_start = Instant::now();
    let person_query_timer = common_metrics::timing_guard(FLAG_PERSON_QUERY_TIME, &[]);
    let (person_id, person_props): (Option<PersonId>, Option<Value>) = sqlx::query_as(person_query)
        .bind(&distinct_id)
        .bind(team_id)
        .fetch_optional(&mut *conn)
        .await?
        .unwrap_or((None, None));
    person_query_timer.fin();

    let person_query_duration = person_query_start.elapsed();

    if person_query_duration.as_millis() > 500 {
        warn!(
            "Slow person query detected: {}ms for distinct_id={}, team_id={}",
            person_query_duration.as_millis(),
            distinct_id,
            team_id
        );
    } else {
        info!(
            "Person query completed: {}ms for distinct_id={}, team_id={}",
            person_query_duration.as_millis(),
            distinct_id,
            team_id,
        );
    }
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

            let cohort_query_start = Instant::now();
            let cohort_timer = common_metrics::timing_guard(FLAG_COHORT_QUERY_TIME, &[]);
            let cohort_rows = sqlx::query(cohort_query)
                .bind(&static_cohort_ids)
                .bind(person_id)
                .fetch_all(&mut *conn)
                .await?;
            cohort_timer.fin();

            let cohort_query_duration = cohort_query_start.elapsed();

            if cohort_query_duration.as_millis() > 200 {
                warn!(
                    "Slow cohort query detected: {}ms for person_id={}, cohort_count={}",
                    cohort_query_duration.as_millis(),
                    person_id,
                    static_cohort_ids.len()
                );
            } else {
                info!(
                    "Cohort query completed: {}ms for person_id={}, cohort_count={}",
                    cohort_query_duration.as_millis(),
                    person_id,
                    static_cohort_ids.len()
                );
            }

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
            group_type_indexes.iter().cloned().collect();
        let group_keys_vec: Vec<String> = group_keys.iter().cloned().collect();

        let group_query_start = Instant::now();
        let group_query_timer = common_metrics::timing_guard(FLAG_GROUP_QUERY_TIME, &[]);
        let groups = sqlx::query(group_query)
            .bind(team_id)
            .bind(&group_type_indexes_vec)
            .bind(&group_keys_vec)
            .fetch_all(&mut *conn)
            .await?;
        group_query_timer.fin();

        let group_query_duration = group_query_start.elapsed();

        if group_query_duration.as_millis() > 300 {
            warn!(
                "Slow group query detected: {}ms for team_id={}, group_types={}, group_keys={}",
                group_query_duration.as_millis(),
                team_id,
                group_type_indexes_vec.len(),
                group_keys_vec.len()
            );
        } else {
            info!(
                "Group query completed: {}ms for team_id={}, group_types={}, group_keys={}, results={}",
                group_query_duration.as_millis(),
                team_id,
                group_type_indexes_vec.len(),
                group_keys_vec.len(),
                groups.len()
            );
        }

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

    // Filter out metadata that isn't a real property override
    let real_overrides = extract_real_property_overrides(overrides);
    if real_overrides.is_empty() {
        return None;
    }

    // Only return overrides if they're useful for this flag
    if are_overrides_useful_for_flag(&real_overrides, property_filters) {
        Some(real_overrides)
    } else {
        None
    }
}

/// Checks if any property filters involve cohorts that require database lookup
fn has_cohort_filters(property_filters: &[PropertyFilter]) -> bool {
    property_filters
        .iter()
        .any(|prop| prop.prop_type == PropertyType::Cohort)
}

/// Extracts real property overrides, filtering out metadata like $group_key
fn extract_real_property_overrides(overrides: &HashMap<String, Value>) -> HashMap<String, Value> {
    overrides
        .iter()
        .filter(|(key, _)| *key != "$group_key")
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect()
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
    // If the operator is not exact, we can't match the flag value to the flag filter
    if filter.operator != Some(OperatorType::Exact) {
        // Should we log this?
        tracing::error!(
            "Flag filter operator for property type Flag is not `exact`, skipping flag value matching: {:?}",
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

/// Retrieves feature flag hash key overrides for a list of distinct IDs.
///
/// This function fetches any hash key overrides that have been set for feature flags
/// for the given distinct IDs. It handles priority by giving precedence to the first
/// distinct ID in the list.
pub async fn get_feature_flag_hash_key_overrides(
    reader: PostgresReader,
    team_id: TeamId,
    distinct_id_and_hash_key_override: Vec<String>,
) -> Result<HashMap<String, String>, FlagError> {
    let mut feature_flag_hash_key_overrides = HashMap::new();
    let mut conn = reader.as_ref().get_connection().await?;

    let person_and_distinct_id_query = r#"
            SELECT person_id, distinct_id 
            FROM posthog_persondistinctid 
            WHERE team_id = $1 AND distinct_id = ANY($2)
        "#;

    let person_and_distinct_ids: Vec<(PersonId, String)> =
        sqlx::query_as(person_and_distinct_id_query)
            .bind(team_id)
            .bind(&distinct_id_and_hash_key_override)
            .fetch_all(&mut *conn)
            .await?;

    let person_id_to_distinct_id: HashMap<PersonId, String> =
        person_and_distinct_ids.into_iter().collect();
    let person_ids: Vec<PersonId> = person_id_to_distinct_id.keys().cloned().collect();

    // Get hash key overrides
    let hash_key_override_query = r#"
            SELECT feature_flag_key, hash_key, person_id 
            FROM posthog_featureflaghashkeyoverride 
            WHERE team_id = $1 AND person_id = ANY($2)
        "#;

    let overrides: Vec<(String, String, PersonId)> = sqlx::query_as(hash_key_override_query)
        .bind(team_id)
        .bind(&person_ids)
        .fetch_all(&mut *conn)
        .await?;

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

    Ok(feature_flag_hash_key_overrides)
}

/// Sets feature flag hash key overrides for a list of distinct IDs.
///
/// This function creates hash key overrides for all active feature flags that have
/// experience continuity enabled. It includes retry logic for handling race conditions
/// with person deletions.
pub async fn set_feature_flag_hash_key_overrides(
    writer: PostgresWriter,
    team_id: TeamId,
    distinct_ids: Vec<String>,
    project_id: ProjectId,
    hash_key_override: String,
) -> Result<bool, FlagError> {
    const MAX_RETRIES: u32 = 2;
    const RETRY_DELAY: Duration = Duration::from_millis(100);

    for retry in 0..MAX_RETRIES {
        let mut conn = writer.get_connection().await?;
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
                SELECT flag.key FROM posthog_featureflag flag
                JOIN posthog_team team ON flag.team_id = team.id
                WHERE team.project_id = $3 
                AND flag.ensure_experience_continuity = TRUE 
                AND flag.active = TRUE 
                AND flag.deleted = FALSE
                AND flag.key NOT IN (SELECT feature_flag_key FROM existing_overrides)
            )
            INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
                SELECT team_id, person_id, key, $4
                FROM flags_to_override, target_person_ids
                WHERE EXISTS (SELECT 1 FROM posthog_person WHERE id = person_id AND team_id = $1)
            ON CONFLICT DO NOTHING
        "#;

        let result: Result<PgQueryResult, sqlx::Error> = sqlx::query(query)
            .bind(team_id)
            .bind(&distinct_ids)
            .bind(project_id)
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

/// Checks if hash key overrides should be written for a given distinct ID.
///
/// This function determines if there are any active feature flags with experience
/// continuity enabled that don't already have hash key overrides for the given
/// distinct ID.
pub async fn should_write_hash_key_override(
    reader: PostgresReader,
    team_id: TeamId,
    distinct_id: String,
    project_id: ProjectId,
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
        SELECT key FROM posthog_featureflag flag
        JOIN posthog_team team ON flag.team_id = team.id
        WHERE team.project_id = $3
            AND flag.ensure_experience_continuity = TRUE AND flag.active = TRUE AND flag.deleted = FALSE
            AND key NOT IN (SELECT feature_flag_key FROM existing_overrides)
    "#;

    for retry in 0..MAX_RETRIES {
        let result = timeout(QUERY_TIMEOUT, async {
            let mut conn = reader.get_connection().await.map_err(|e| {
                FlagError::DatabaseError(format!("Failed to acquire connection: {}", e))
            })?;

            let rows = sqlx::query(query)
                .bind(team_id)
                .bind(&distinct_ids)
                .bind(project_id)
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
    use rstest::rstest;
    use serde_json::json;

    use crate::{
        flags::flag_models::{FeatureFlagRow, FlagFilters},
        properties::property_models::{OperatorType, PropertyFilter},
        utils::test_utils::{
            create_test_flag, insert_flag_for_team_in_pg, insert_new_team_in_pg,
            insert_person_for_team_in_pg, setup_pg_reader_client, setup_pg_writer_client,
        },
    };

    use super::*;

    #[tokio::test]
    async fn test_set_feature_flag_hash_key_overrides_success() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
        let distinct_id = "user2".to_string();

        // Insert person
        insert_person_for_team_in_pg(reader.clone(), team.id, distinct_id.clone(), None)
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
        };

        // Insert the feature flag into the database
        insert_flag_for_team_in_pg(writer.clone(), team.id, Some(flag_row))
            .await
            .unwrap();

        // Set hash key override
        set_feature_flag_hash_key_overrides(
            writer.clone(),
            team.id,
            vec![distinct_id.clone()],
            team.project_id,
            "hash_key_2".to_string(),
        )
        .await
        .unwrap();

        // Retrieve hash key overrides
        let overrides =
            get_feature_flag_hash_key_overrides(reader.clone(), team.id, vec![distinct_id.clone()])
                .await
                .unwrap();

        assert_eq!(
            overrides.get("test_flag"),
            Some(&"hash_key_2".to_string()),
            "Hash key override should match the set value"
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
            "Hash {} should equal expected value {} within floating point precision",
            hash,
            expected_hash
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
            operator: Some(OperatorType::Exact),
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
}
