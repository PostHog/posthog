use std::collections::{HashMap, HashSet};

use common_database::PostgresReader;
use common_types::TeamId;
use serde_json::Value;
use sqlx::FromRow;
use tracing::{info, warn};

use metrics::counter;

use crate::{
    api::errors::FlagError,
    cohorts::cohort_models::Cohort,
    database::get_connection_with_metrics,
    flags::flag_models::{FeatureFlag, FeatureFlagRow},
    metrics::consts::TOMBSTONE_COUNTER,
};

/// Build the flag definitions response from PostgreSQL, mirroring Django's
/// `_get_flags_response_for_local_evaluation` endpoint. Called on cache miss
/// so SDKs still get data instead of a 503.
pub async fn load_flag_definitions_from_pg(
    client: PostgresReader,
    team_id: TeamId,
    project_id: i64,
) -> Result<Value, FlagError> {
    // Step A: Load survey flag IDs to exclude from the response
    let survey_flag_ids = load_survey_flag_ids(client.clone(), team_id).await?;

    // Step B: Load eligible flags (excluding survey flags and encrypted remote config)
    let flags = load_flags_for_definitions(client.clone(), team_id, &survey_flag_ids).await?;

    // Step C: Extract cohort IDs referenced in flag filters
    let referenced_cohort_ids = extract_cohort_ids_from_flags(&flags);

    // Step D: Load cohorts with nested dependency resolution
    let cohorts =
        load_cohorts_with_dependencies(client.clone(), project_id, referenced_cohort_ids).await?;

    // Step E: Load group type mappings
    let group_type_mapping =
        load_group_type_mapping_for_definitions(client.clone(), project_id).await?;

    // Step F: Serialize flags and build flag_id_to_key mapping
    let (mut flags_data, flag_id_to_key) = serialize_flags(&flags);

    // Step G: Build cohort properties for response
    let cohort_properties = build_cohort_properties(&flags, &cohorts);

    // Step H: Apply dependency chain transformation and assemble response
    apply_flag_dependency_transformation(&mut flags_data, &flag_id_to_key);

    let response = serde_json::json!({
        "flags": flags_data,
        "group_type_mapping": group_type_mapping,
        "cohorts": cohort_properties,
    });

    info!(
        team_id,
        flags = flags.len(),
        cohorts = cohort_properties.len(),
        "Built flag definitions from database"
    );

    Ok(response)
}

/// Load survey-linked flag IDs so they can be excluded from definitions.
/// Surveys create internal flags that shouldn't be exposed for local evaluation.
async fn load_survey_flag_ids(
    client: PostgresReader,
    team_id: TeamId,
) -> Result<HashSet<i32>, FlagError> {
    let mut conn =
        get_connection_with_metrics(&client, "non_persons_reader", "fetch_survey_flag_ids").await?;

    #[derive(FromRow)]
    struct SurveyFlagIds {
        targeting_flag_id: Option<i32>,
        internal_targeting_flag_id: Option<i32>,
        internal_response_sampling_flag_id: Option<i32>,
    }

    let rows = sqlx::query_as::<_, SurveyFlagIds>(
        r#"SELECT targeting_flag_id, internal_targeting_flag_id, internal_response_sampling_flag_id
           FROM posthog_survey WHERE team_id = $1"#,
    )
    .bind(team_id)
    .fetch_all(&mut *conn)
    .await
    .map_err(|e| FlagError::Internal(format!("Failed to load survey flag IDs: {e}")))?;

    let mut ids = HashSet::new();
    for row in rows {
        if let Some(id) = row.targeting_flag_id {
            ids.insert(id);
        }
        if let Some(id) = row.internal_targeting_flag_id {
            ids.insert(id);
        }
        if let Some(id) = row.internal_response_sampling_flag_id {
            ids.insert(id);
        }
    }

    Ok(ids)
}

/// Load feature flags eligible for local evaluation definitions.
/// Excludes survey flags and encrypted remote config flags, matching Django's queryset.
async fn load_flags_for_definitions(
    client: PostgresReader,
    team_id: TeamId,
    survey_flag_ids: &HashSet<i32>,
) -> Result<Vec<FeatureFlag>, FlagError> {
    let mut conn =
        get_connection_with_metrics(&client, "non_persons_reader", "fetch_flags_for_definitions")
            .await?;

    let survey_ids: Vec<i32> = survey_flag_ids.iter().copied().collect();

    let query = r#"
        SELECT f.id,
              f.team_id,
              f.name,
              f.key,
              f.filters,
              f.deleted,
              f.active,
              f.ensure_experience_continuity,
              f.has_encrypted_payloads,
              f.version,
              f.evaluation_runtime,
              COALESCE(
                  ARRAY_AGG(tag.name) FILTER (WHERE tag.name IS NOT NULL),
                  '{}'::text[]
              ) AS evaluation_tags,
              f.bucketing_identifier
          FROM posthog_featureflag AS f
          JOIN posthog_team AS t ON (f.team_id = t.id)
          LEFT JOIN posthog_featureflagevaluationtag AS et ON (f.id = et.feature_flag_id)
          LEFT JOIN posthog_tag AS tag ON (et.tag_id = tag.id)
        WHERE t.id = $1
          AND f.deleted = false
          AND NOT (f.is_remote_configuration IS TRUE AND f.has_encrypted_payloads IS TRUE)
          AND f.id != ALL($2)
        GROUP BY f.id, f.team_id, f.name, f.key, f.filters, f.deleted, f.active,
                 f.ensure_experience_continuity, f.has_encrypted_payloads, f.version,
                 f.evaluation_runtime
        ORDER BY f.key
    "#;

    let rows = sqlx::query_as::<_, FeatureFlagRow>(query)
        .bind(team_id)
        .bind(&survey_ids)
        .fetch_all(&mut *conn)
        .await
        .map_err(|e| FlagError::Internal(format!("Failed to load flags for definitions: {e}")))?;

    let flags: Vec<FeatureFlag> = rows
        .into_iter()
        .filter_map(|row| match serde_json::from_value(row.filters) {
            Ok(filters) => Some(FeatureFlag {
                id: row.id,
                team_id: row.team_id,
                name: row.name,
                key: row.key,
                filters,
                deleted: row.deleted,
                active: row.active,
                ensure_experience_continuity: row.ensure_experience_continuity,
                has_encrypted_payloads: row.has_encrypted_payloads,
                version: row.version,
                evaluation_runtime: row.evaluation_runtime,
                evaluation_tags: row.evaluation_tags,
                bucketing_identifier: row.bucketing_identifier,
            }),
            Err(e) => {
                warn!(
                    flag_key = row.key,
                    team_id = row.team_id,
                    "Failed to deserialize filters: {e}"
                );
                counter!(
                    TOMBSTONE_COUNTER,
                    "namespace" => "feature_flags",
                    "operation" => "flag_filter_deserialization_error",
                    "component" => "flag_definitions_from_pg",
                )
                .increment(1);
                None
            }
        })
        .collect();

    Ok(flags)
}

/// Extract cohort IDs from flag filter properties.
fn extract_cohort_ids_from_flags(flags: &[FeatureFlag]) -> HashSet<i32> {
    let mut cohort_ids = HashSet::new();
    for flag in flags {
        for group in &flag.filters.groups {
            if let Some(props) = &group.properties {
                for prop in props {
                    if prop.prop_type == crate::properties::property_models::PropertyType::Cohort {
                        if let Some(value) = &prop.value {
                            if let Some(id) = value.as_i64() {
                                cohort_ids.insert(id as i32);
                            } else if let Some(s) = value.as_str() {
                                if let Ok(id) = s.parse::<i32>() {
                                    cohort_ids.insert(id);
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    cohort_ids
}

/// Load cohorts by project_id with iterative nested dependency resolution,
/// matching Django's loop in `_get_flags_response_for_local_evaluation_batch`.
async fn load_cohorts_with_dependencies(
    client: PostgresReader,
    project_id: i64,
    initial_ids: HashSet<i32>,
) -> Result<HashMap<i32, Cohort>, FlagError> {
    if initial_ids.is_empty() {
        return Ok(HashMap::new());
    }

    let mut loaded: HashMap<i32, Cohort> = HashMap::new();
    let mut ids_to_load: HashSet<i32> = initial_ids;
    let mut all_requested: HashSet<i32> = HashSet::new();

    let mut conn =
        get_connection_with_metrics(&client, "non_persons_reader", "fetch_cohorts_for_defs")
            .await?;

    while !ids_to_load.is_empty() {
        let ids_vec: Vec<i32> = ids_to_load.iter().copied().collect();
        all_requested.extend(&ids_to_load);

        let cohorts = sqlx::query_as::<_, Cohort>(
            r#"SELECT c.id, c.name, c.description, c.team_id, c.deleted, c.filters,
                      c.query, c.version, c.pending_version, c.count, c.is_calculating,
                      c.is_static, c.errors_calculating, c.groups, c.created_by_id
               FROM posthog_cohort AS c
               JOIN posthog_team AS t ON (c.team_id = t.id)
              WHERE t.project_id = $1
                AND c.id = ANY($2)
                AND c.deleted = false
                AND c.is_static = false"#,
        )
        .bind(project_id)
        .bind(&ids_vec)
        .fetch_all(&mut *conn)
        .await
        .map_err(|e| FlagError::Internal(format!("Failed to load cohorts: {e}")))?;

        // Extract nested IDs from newly loaded cohorts
        let mut nested_ids: HashSet<i32> = HashSet::new();
        for cohort in cohorts {
            match cohort.extract_dependencies() {
                Ok(deps) => {
                    nested_ids.extend(deps);
                }
                Err(e) => {
                    warn!(
                        cohort_id = cohort.id,
                        team_id = cohort.team_id,
                        error = %e,
                        "Failed to extract cohort dependencies; nested resolution may be incomplete"
                    );
                }
            }
            loaded.insert(cohort.id, cohort);
        }

        // Only load IDs we haven't already requested
        ids_to_load = nested_ids.difference(&all_requested).copied().collect();
    }

    Ok(loaded)
}

/// Load group type mappings by project_id, formatted as Django does:
/// `{"0": "project", "1": "organization"}`.
async fn load_group_type_mapping_for_definitions(
    client: PostgresReader,
    project_id: i64,
) -> Result<HashMap<String, String>, FlagError> {
    let mut conn = get_connection_with_metrics(
        &client,
        "non_persons_reader",
        "fetch_group_type_mapping_for_defs",
    )
    .await?;

    #[derive(FromRow)]
    struct GroupTypeRow {
        group_type: String,
        group_type_index: i32,
    }

    let rows = sqlx::query_as::<_, GroupTypeRow>(
        "SELECT group_type, group_type_index FROM posthog_grouptypemapping WHERE project_id = $1",
    )
    .bind(project_id)
    .fetch_all(&mut *conn)
    .await
    .map_err(|e| FlagError::Internal(format!("Failed to load group type mappings: {e}")))?;

    Ok(rows
        .into_iter()
        .map(|r| (r.group_type_index.to_string(), r.group_type))
        .collect())
}

/// Serialize flags to JSON values and build the id-to-key mapping.
fn serialize_flags(flags: &[FeatureFlag]) -> (Vec<Value>, HashMap<String, String>) {
    let mut flags_data = Vec::with_capacity(flags.len());
    let mut flag_id_to_key = HashMap::with_capacity(flags.len());

    for flag in flags {
        if let Ok(value) = serde_json::to_value(flag) {
            flag_id_to_key.insert(flag.id.to_string(), flag.key.clone());
            flags_data.push(value);
        }
    }

    (flags_data, flag_id_to_key)
}

/// Build cohort properties for the response, keyed by cohort ID as string.
/// Extracts the `properties` field from each cohort's filters, matching
/// Django's `cohort.properties.to_dict()`.
fn build_cohort_properties(
    flags: &[FeatureFlag],
    cohorts: &HashMap<i32, Cohort>,
) -> HashMap<String, Value> {
    // Collect the cohort IDs actually referenced by flags
    let referenced_ids = extract_cohort_ids_from_flags(flags);
    let mut result = HashMap::new();

    for id in referenced_ids {
        if let Some(cohort) = cohorts.get(&id) {
            if let Some(props) = extract_cohort_filter_properties(cohort) {
                result.insert(id.to_string(), props);
            }
        }
    }

    // Also include any transitively loaded cohorts that are referenced by other cohorts
    for (id, cohort) in cohorts {
        let str_id = id.to_string();
        if let std::collections::hash_map::Entry::Vacant(e) = result.entry(str_id) {
            if let Some(props) = extract_cohort_filter_properties(cohort) {
                e.insert(props);
            }
        }
    }

    result
}

/// Extract the `properties` value from a cohort's filters JSON.
fn extract_cohort_filter_properties(cohort: &Cohort) -> Option<Value> {
    cohort.filters.as_ref()?.get("properties").cloned()
}

// ---------------------------------------------------------------------------
// Dependency chain transformation (ported from Django local_evaluation.py)
// ---------------------------------------------------------------------------

/// Iterate over all flag properties of type "flag" in a flag's filters.
fn get_flag_properties(flag_data: &Value) -> Vec<(usize, usize)> {
    let mut positions = Vec::new();
    if let Some(groups) = flag_data
        .get("filters")
        .and_then(|f| f.get("groups"))
        .and_then(|g| g.as_array())
    {
        for (gi, group) in groups.iter().enumerate() {
            if let Some(props) = group.get("properties").and_then(|p| p.as_array()) {
                for (pi, prop) in props.iter().enumerate() {
                    if prop.get("type").and_then(|t| t.as_str()) == Some("flag") {
                        positions.push((gi, pi));
                    }
                }
            }
        }
    }
    positions
}

/// Normalize flag ID references to flag keys and collect unique dependency targets.
fn normalize_and_collect_dependency_keys(
    flags_data: &mut [Value],
    flag_id_to_key: &HashMap<String, String>,
) -> HashSet<String> {
    let mut unique_deps = HashSet::new();

    for flag_data in flags_data.iter_mut() {
        let positions = get_flag_properties(flag_data);
        for (gi, pi) in positions {
            if let Some(prop) = flag_data
                .get_mut("filters")
                .and_then(|f| f.get_mut("groups"))
                .and_then(|g| g.get_mut(gi))
                .and_then(|g| g.get_mut("properties"))
                .and_then(|p| p.get_mut(pi))
            {
                let key_ref = prop
                    .get("key")
                    .and_then(|k| k.as_str())
                    .unwrap_or("")
                    .to_string();
                let resolved_key = flag_id_to_key.get(&key_ref).cloned().unwrap_or(key_ref);
                prop["key"] = Value::String(resolved_key.clone());
                unique_deps.insert(resolved_key);
            }
        }
    }

    unique_deps
}

/// DFS-based dependency chain builder with cycle detection and memoization.
struct DependencyChainBuilder {
    all_flags: HashMap<String, Value>,
    memo: HashMap<String, Vec<String>>,
}

impl DependencyChainBuilder {
    fn new(all_flags: HashMap<String, Value>) -> Self {
        Self {
            all_flags,
            memo: HashMap::new(),
        }
    }

    fn build_chain(&mut self, flag_key: &str) -> Vec<String> {
        if let Some(chain) = self.memo.get(flag_key) {
            return chain.clone();
        }

        if self.has_self_dependency(flag_key) {
            warn!(flag_key, "Self-dependency detected in feature flag");
            self.memo.insert(flag_key.to_string(), Vec::new());
            return Vec::new();
        }

        let mut visited = HashSet::new();
        let mut temp_visited = HashSet::new();
        let mut chain = Vec::new();

        if !self.dfs(flag_key, &mut visited, &mut temp_visited, &mut chain) {
            warn!(
                flag_key,
                "Flag cannot be evaluated due to circular or missing dependencies"
            );
            self.memo.insert(flag_key.to_string(), Vec::new());
            return Vec::new();
        }

        self.memo.insert(flag_key.to_string(), chain.clone());
        chain
    }

    fn has_self_dependency(&self, flag_key: &str) -> bool {
        let Some(flag_data) = self.all_flags.get(flag_key) else {
            return false;
        };
        let positions = get_flag_properties(flag_data);
        for (gi, pi) in positions {
            if let Some(dep_key) = flag_data
                .get("filters")
                .and_then(|f| f.get("groups"))
                .and_then(|g| g.get(gi))
                .and_then(|g| g.get("properties"))
                .and_then(|p| p.get(pi))
                .and_then(|p| p.get("key"))
                .and_then(|k| k.as_str())
            {
                if dep_key == flag_key {
                    return true;
                }
            }
        }
        false
    }

    fn dfs(
        &self,
        current_key: &str,
        visited: &mut HashSet<String>,
        temp_visited: &mut HashSet<String>,
        chain: &mut Vec<String>,
    ) -> bool {
        if temp_visited.contains(current_key) {
            warn!(circular_at = current_key, "Circular dependency detected");
            return false;
        }

        if visited.contains(current_key) {
            return true;
        }

        temp_visited.insert(current_key.to_string());

        if !self.all_flags.contains_key(current_key) {
            warn!(
                flag_key = current_key,
                "Dependency references non-existent flag"
            );
            return false;
        }

        // Recurse into dependencies
        let flag_data = self.all_flags.get(current_key).unwrap();
        let positions = get_flag_properties(flag_data);
        for (gi, pi) in positions {
            if let Some(dep_key) = flag_data
                .get("filters")
                .and_then(|f| f.get("groups"))
                .and_then(|g| g.get(gi))
                .and_then(|g| g.get("properties"))
                .and_then(|p| p.get(pi))
                .and_then(|p| p.get("key"))
                .and_then(|k| k.as_str())
            {
                if dep_key != current_key {
                    if !self.all_flags.contains_key(dep_key) {
                        warn!(
                            flag = current_key,
                            missing_dependency = dep_key,
                            "Flag dependency references non-existent flag"
                        );
                        return false;
                    }
                    if !self.dfs(dep_key, visited, temp_visited, chain) {
                        return false;
                    }
                }
            }
        }

        temp_visited.remove(current_key);
        visited.insert(current_key.to_string());
        chain.push(current_key.to_string());
        true
    }
}

/// Apply dependency chain transformation to the flags data, mutating in place.
/// This is the Rust port of Django's `_apply_flag_dependency_transformation`.
fn apply_flag_dependency_transformation(
    flags_data: &mut [Value],
    flag_id_to_key: &HashMap<String, String>,
) {
    let unique_deps = normalize_and_collect_dependency_keys(flags_data, flag_id_to_key);

    if unique_deps.is_empty() {
        return;
    }

    let all_flags_by_key: HashMap<String, Value> = flags_data
        .iter()
        .filter_map(|f| {
            f.get("key")
                .and_then(|k| k.as_str())
                .map(|k| (k.to_string(), f.clone()))
        })
        .collect();

    let mut builder = DependencyChainBuilder::new(all_flags_by_key);

    // Pre-populate cache for all dependency targets
    for dep_key in &unique_deps {
        builder.build_chain(dep_key);
    }

    // Set dependency_chain on each flag property of type "flag"
    for flag_data in flags_data.iter_mut() {
        let positions = get_flag_properties(flag_data);
        for (gi, pi) in positions {
            let dep_key = flag_data
                .get("filters")
                .and_then(|f| f.get("groups"))
                .and_then(|g| g.get(gi))
                .and_then(|g| g.get("properties"))
                .and_then(|p| p.get(pi))
                .and_then(|p| p.get("key"))
                .and_then(|k| k.as_str())
                .unwrap_or("")
                .to_string();

            let chain = builder.build_chain(&dep_key);

            if let Some(prop) = flag_data
                .get_mut("filters")
                .and_then(|f| f.get_mut("groups"))
                .and_then(|g| g.get_mut(gi))
                .and_then(|g| g.get_mut("properties"))
                .and_then(|p| p.get_mut(pi))
            {
                prop["dependency_chain"] = serde_json::to_value(&chain).unwrap_or_default();
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // -----------------------------------------------------------------------
    // Cohort ID extraction
    // -----------------------------------------------------------------------

    #[test]
    fn test_extract_cohort_ids_from_flags_empty() {
        let flags: Vec<FeatureFlag> = vec![];
        assert!(extract_cohort_ids_from_flags(&flags).is_empty());
    }

    #[test]
    fn test_extract_cohort_ids_from_flags_with_cohort_property() {
        use crate::flags::flag_models::FlagFilters;
        use crate::properties::property_models::{PropertyFilter, PropertyType};

        let flag = FeatureFlag {
            id: 1,
            team_id: 1,
            name: None,
            key: "test".to_string(),
            filters: FlagFilters {
                groups: vec![crate::flags::flag_models::FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(42)),
                        operator: None,
                        prop_type: PropertyType::Cohort,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: None,
                    variant: None,
                }],
                ..Default::default()
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: None,
            has_encrypted_payloads: None,
            version: None,
            evaluation_runtime: None,
            evaluation_tags: None,
            bucketing_identifier: None,
        };

        let ids = extract_cohort_ids_from_flags(&[flag]);
        assert_eq!(ids, HashSet::from([42]));
    }

    // -----------------------------------------------------------------------
    // Cohort filter property extraction
    // -----------------------------------------------------------------------

    #[test]
    fn test_extract_cohort_filter_properties() {
        let cohort = Cohort {
            id: 1,
            name: None,
            description: None,
            team_id: 1,
            deleted: false,
            filters: Some(json!({
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": []}]
                }
            })),
            query: None,
            version: None,
            pending_version: None,
            count: None,
            is_calculating: false,
            is_static: false,
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: None,
        };

        let props = extract_cohort_filter_properties(&cohort);
        assert!(props.is_some());
        assert_eq!(
            props.unwrap().get("type").and_then(|t| t.as_str()),
            Some("OR")
        );
    }

    #[test]
    fn test_extract_cohort_filter_properties_none_filters() {
        let cohort = Cohort {
            id: 1,
            name: None,
            description: None,
            team_id: 1,
            deleted: false,
            filters: None,
            query: None,
            version: None,
            pending_version: None,
            count: None,
            is_calculating: false,
            is_static: false,
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: None,
        };

        assert!(extract_cohort_filter_properties(&cohort).is_none());
    }

    // -----------------------------------------------------------------------
    // Dependency chain transformation
    // -----------------------------------------------------------------------

    #[test]
    fn test_dependency_chain_simple() {
        // flag_b depends on flag_a
        let mut flags_data = vec![
            json!({
                "id": 1, "key": "flag_a", "filters": {
                    "groups": [{"properties": []}]
                }
            }),
            json!({
                "id": 2, "key": "flag_b", "filters": {
                    "groups": [{"properties": [
                        {"key": "flag_a", "type": "flag", "value": "true"}
                    ]}]
                }
            }),
        ];

        let id_to_key = HashMap::from([
            ("1".to_string(), "flag_a".to_string()),
            ("2".to_string(), "flag_b".to_string()),
        ]);

        apply_flag_dependency_transformation(&mut flags_data, &id_to_key);

        // flag_b's property should have a dependency_chain
        let chain = flags_data[1]["filters"]["groups"][0]["properties"][0]
            .get("dependency_chain")
            .and_then(|c| c.as_array())
            .unwrap();
        assert_eq!(chain, &[json!("flag_a")]);
    }

    #[test]
    fn test_dependency_chain_self_dependency() {
        let mut flags_data = vec![json!({
            "id": 1, "key": "flag_a", "filters": {
                "groups": [{"properties": [
                    {"key": "flag_a", "type": "flag", "value": "true"}
                ]}]
            }
        })];

        let id_to_key = HashMap::from([("1".to_string(), "flag_a".to_string())]);
        apply_flag_dependency_transformation(&mut flags_data, &id_to_key);

        let chain = flags_data[0]["filters"]["groups"][0]["properties"][0]
            .get("dependency_chain")
            .and_then(|c| c.as_array())
            .unwrap();
        assert!(chain.is_empty(), "Self-dependency should yield empty chain");
    }

    #[test]
    fn test_dependency_chain_circular() {
        let mut flags_data = vec![
            json!({
                "id": 1, "key": "flag_a", "filters": {
                    "groups": [{"properties": [
                        {"key": "flag_b", "type": "flag", "value": "true"}
                    ]}]
                }
            }),
            json!({
                "id": 2, "key": "flag_b", "filters": {
                    "groups": [{"properties": [
                        {"key": "flag_a", "type": "flag", "value": "true"}
                    ]}]
                }
            }),
        ];

        let id_to_key = HashMap::from([
            ("1".to_string(), "flag_a".to_string()),
            ("2".to_string(), "flag_b".to_string()),
        ]);
        apply_flag_dependency_transformation(&mut flags_data, &id_to_key);

        // Both should get empty chains due to the cycle
        for flag in &flags_data {
            let chain = flag["filters"]["groups"][0]["properties"][0]
                .get("dependency_chain")
                .and_then(|c| c.as_array())
                .unwrap();
            assert!(
                chain.is_empty(),
                "Circular dependency should yield empty chain"
            );
        }
    }

    #[test]
    fn test_dependency_chain_missing_dependency() {
        let mut flags_data = vec![json!({
            "id": 1, "key": "flag_a", "filters": {
                "groups": [{"properties": [
                    {"key": "nonexistent_flag", "type": "flag", "value": "true"}
                ]}]
            }
        })];

        let id_to_key = HashMap::from([("1".to_string(), "flag_a".to_string())]);
        apply_flag_dependency_transformation(&mut flags_data, &id_to_key);

        let chain = flags_data[0]["filters"]["groups"][0]["properties"][0]
            .get("dependency_chain")
            .and_then(|c| c.as_array())
            .unwrap();
        assert!(
            chain.is_empty(),
            "Missing dependency should yield empty chain"
        );
    }

    #[test]
    fn test_dependency_chain_diamond() {
        // flag_d -> flag_b, flag_c; flag_b -> flag_a; flag_c -> flag_a
        let mut flags_data = vec![
            json!({"id": 1, "key": "flag_a", "filters": {"groups": [{"properties": []}]}}),
            json!({"id": 2, "key": "flag_b", "filters": {"groups": [{"properties": [
                {"key": "flag_a", "type": "flag", "value": "true"}
            ]}]}}),
            json!({"id": 3, "key": "flag_c", "filters": {"groups": [{"properties": [
                {"key": "flag_a", "type": "flag", "value": "true"}
            ]}]}}),
            json!({"id": 4, "key": "flag_d", "filters": {"groups": [{"properties": [
                {"key": "flag_b", "type": "flag", "value": "true"},
                {"key": "flag_c", "type": "flag", "value": "true"}
            ]}]}}),
        ];

        let id_to_key = HashMap::from([
            ("1".to_string(), "flag_a".to_string()),
            ("2".to_string(), "flag_b".to_string()),
            ("3".to_string(), "flag_c".to_string()),
            ("4".to_string(), "flag_d".to_string()),
        ]);
        apply_flag_dependency_transformation(&mut flags_data, &id_to_key);

        // flag_d's first dependency (flag_b) should have chain [flag_a, flag_b]
        let chain_b = flags_data[3]["filters"]["groups"][0]["properties"][0]
            .get("dependency_chain")
            .and_then(|c| c.as_array())
            .unwrap();
        assert!(chain_b.contains(&json!("flag_a")));
        assert!(chain_b.contains(&json!("flag_b")));

        // flag_d's second dependency (flag_c) should have chain [flag_a, flag_c]
        let chain_c = flags_data[3]["filters"]["groups"][0]["properties"][1]
            .get("dependency_chain")
            .and_then(|c| c.as_array())
            .unwrap();
        assert!(chain_c.contains(&json!("flag_a")));
        assert!(chain_c.contains(&json!("flag_c")));
    }

    #[test]
    fn test_dependency_chain_id_to_key_resolution() {
        // Property references flag by ID ("1"), should be resolved to key ("flag_a")
        let mut flags_data = vec![
            json!({"id": 1, "key": "flag_a", "filters": {"groups": [{"properties": []}]}}),
            json!({"id": 2, "key": "flag_b", "filters": {"groups": [{"properties": [
                {"key": "1", "type": "flag", "value": "true"}
            ]}]}}),
        ];

        let id_to_key = HashMap::from([
            ("1".to_string(), "flag_a".to_string()),
            ("2".to_string(), "flag_b".to_string()),
        ]);
        apply_flag_dependency_transformation(&mut flags_data, &id_to_key);

        // The key should have been normalized from "1" to "flag_a"
        let resolved_key = flags_data[1]["filters"]["groups"][0]["properties"][0]["key"]
            .as_str()
            .unwrap();
        assert_eq!(resolved_key, "flag_a");
    }

    #[test]
    fn test_no_flag_dependencies_is_noop() {
        let mut flags_data = vec![
            json!({"id": 1, "key": "flag_a", "filters": {"groups": [{"properties": [
                {"key": "email", "type": "person", "value": "test@test.com"}
            ]}]}}),
        ];

        let id_to_key = HashMap::from([("1".to_string(), "flag_a".to_string())]);
        let original = flags_data.clone();
        apply_flag_dependency_transformation(&mut flags_data, &id_to_key);

        // No flag-type properties, so data should be unchanged
        assert_eq!(flags_data, original);
    }

    #[test]
    fn test_group_type_mapping_format() {
        // Verify the format is {"0": "project"} not {"project": 0}
        let mapping: HashMap<String, String> = vec![
            ("0".to_string(), "project".to_string()),
            ("1".to_string(), "organization".to_string()),
        ]
        .into_iter()
        .collect();

        let json_val = serde_json::to_value(&mapping).unwrap();
        assert_eq!(json_val.get("0").and_then(|v| v.as_str()), Some("project"));
        assert_eq!(
            json_val.get("1").and_then(|v| v.as_str()),
            Some("organization")
        );
    }
}
