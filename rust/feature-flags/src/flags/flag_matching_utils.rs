use std::collections::{HashMap, HashSet};

use common_types::{PersonId, ProjectId, TeamId};
use serde_json::Value;
use sha1::{Digest, Sha1};
use sqlx::{postgres::PgQueryResult, Acquire, Row};
use std::time::Duration;
use tokio::time::{sleep, timeout};
use tracing::info;

use crate::{
    api::errors::FlagError,
    cohorts::cohort_models::CohortId,
    metrics::consts::{
        FLAG_COHORT_PROCESSING_TIME, FLAG_COHORT_QUERY_TIME, FLAG_DB_CONNECTION_TIME,
        FLAG_GROUP_PROCESSING_TIME, FLAG_GROUP_QUERY_TIME, FLAG_PERSON_PROCESSING_TIME,
        FLAG_PERSON_QUERY_TIME,
    },
    properties::{property_matching::match_property, property_models::PropertyFilter},
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

    let person_query_timer = common_metrics::timing_guard(FLAG_PERSON_QUERY_TIME, &[]);
    let (person_id, person_props): (Option<PersonId>, Option<Value>) = sqlx::query_as(person_query)
        .bind(&distinct_id)
        .bind(team_id)
        .fetch_optional(&mut *conn)
        .await?
        .unwrap_or((None, None));
    person_query_timer.fin();

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

            let cohort_timer = common_metrics::timing_guard(FLAG_COHORT_QUERY_TIME, &[]);
            let cohort_rows = sqlx::query(cohort_query)
                .bind(&static_cohort_ids)
                .bind(person_id)
                .fetch_all(&mut *conn)
                .await?;
            cohort_timer.fin();

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
    if let Some(person_props) = person_props {
        flag_evaluation_state.set_person_properties(
            person_props
                .as_object()
                .unwrap_or(&serde_json::Map::new())
                .iter()
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
        );
    }
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

        let group_query_timer = common_metrics::timing_guard(FLAG_GROUP_QUERY_TIME, &[]);
        let groups = sqlx::query(group_query)
            .bind(team_id)
            .bind(&group_type_indexes_vec)
            .bind(&group_keys_vec)
            .fetch_all(&mut *conn)
            .await?;
        group_query_timer.fin();

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

/// Check if all required properties are present in the overrides
/// and none of them are of type "cohort" – if so, return the overrides,
/// otherwise return None, because we can't locally compute cohort properties
pub fn locally_computable_property_overrides(
    property_overrides: &Option<HashMap<String, Value>>,
    property_filters: &[PropertyFilter],
) -> Option<HashMap<String, Value>> {
    property_overrides.as_ref().and_then(|overrides| {
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
pub fn all_properties_match(
    flag_condition_properties: &[PropertyFilter],
    matching_property_values: &HashMap<String, Value>,
) -> bool {
    flag_condition_properties
        .iter()
        .all(|property| match_property(property, matching_property_values, false).unwrap_or(false))
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
        properties::property_models::OperatorType,
        utils::test_utils::{
            create_test_flag, insert_flag_for_team_in_pg, insert_person_for_team_in_pg,
            setup_pg_reader_client, setup_pg_writer_client,
        },
    };
    use common_models::test_utils::insert_new_team_in_pg;

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

        let property_filters = vec![
            PropertyFilter {
                key: "email".to_string(),
                value: Some(json!("test@example.com")),
                operator: None,
                prop_type: "person".to_string(),
                group_type_index: None,
                negation: None,
            },
            PropertyFilter {
                key: "age".to_string(),
                value: Some(json!(25)),
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
                value: Some(json!("test@example.com")),
                operator: None,
                prop_type: "person".to_string(),
                group_type_index: None,
                negation: None,
            },
            PropertyFilter {
                key: "cohort".to_string(),
                value: Some(json!(1)),
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
}
