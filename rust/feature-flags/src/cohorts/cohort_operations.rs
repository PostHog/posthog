use petgraph::algo::is_cyclic_directed;
use petgraph::algo::toposort;
use petgraph::graph::DiGraph;
use serde_json::Value;
use std::collections::HashMap;
use std::collections::HashSet;
use std::collections::VecDeque;
use std::sync::Arc;
use tracing::instrument;

use super::cohort_models::CohortPropertyType;
use super::cohort_models::CohortValues;
use crate::cohorts::cohort_models::{Cohort, CohortId, CohortProperty, InnerCohortProperty};
use crate::properties::property_matching::match_property;
use crate::properties::property_models::OperatorType;
use crate::{api::errors::FlagError, properties::property_models::PropertyFilter};
use common_database::Client as DatabaseClient;

impl Cohort {
    /// Returns all cohorts for a given team
    #[instrument(skip_all)]
    pub async fn list_from_pg(
        client: Arc<dyn DatabaseClient + Send + Sync>,
        project_id: i64,
    ) -> Result<Vec<Cohort>, FlagError> {
        let mut conn = client.get_connection().await.map_err(|e| {
            tracing::error!("Failed to get database connection: {}", e);
            FlagError::DatabaseUnavailable
        })?;

        let query = r#"
            SELECT c.id,
                  c.name,
                  c.description,
                  c.team_id,
                  c.deleted,
                  c.filters,
                  c.query,
                  c.version,
                  c.pending_version,
                  c.count,
                  c.is_calculating,
                  c.is_static,
                  c.errors_calculating,
                  c.groups,
                  c.created_by_id
              FROM posthog_cohort AS c
              JOIN posthog_team AS t ON (c.team_id = t.id)
            WHERE t.project_id = $1
            AND c.deleted = false
        "#;
        let cohorts = sqlx::query_as::<_, Cohort>(query)
            .bind(project_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!("Failed to fetch cohorts from database: {}", e);
                FlagError::Internal(format!("Database query error: {}", e))
            })?;

        Ok(cohorts)
    }

    /// Parses the filters JSON into a CohortProperty structure
    // TODO: this doesn't handle the deprecated "groups" field, see
    // https://github.com/PostHog/posthog/blob/feat/dynamic-cohorts-rust/posthog/models/cohort/cohort.py#L114-L169
    // I'll handle that in a separate PR.
    pub fn parse_filters(&self) -> Result<Vec<PropertyFilter>, FlagError> {
        let filters = match &self.filters {
            Some(filters) => filters,
            None => return Ok(Vec::new()), // Return empty vec if no filters
        };

        let cohort_property: CohortProperty =
            serde_json::from_value(filters.to_owned()).map_err(|e| {
                tracing::error!("Failed to parse filters for cohort {}: {}", self.id, e);
                FlagError::CohortFiltersParsingError
            })?;

        let mut props = cohort_property.properties.to_inner();
        props.retain(|f| !(f.key == "id" && f.prop_type == "cohort"));
        Ok(props)
    }

    /// Extracts dependent CohortIds from the cohort's filters
    ///
    /// # Returns
    /// * `HashSet<CohortId>` - A set of dependent cohort IDs
    /// * `FlagError` - If there is an error parsing the filters
    pub fn extract_dependencies(&self) -> Result<HashSet<CohortId>, FlagError> {
        let filters = match &self.filters {
            Some(filters) => filters,
            None => return Ok(HashSet::new()), // Return empty set if no filters
        };

        let cohort_property: CohortProperty =
            serde_json::from_value(filters.clone()).map_err(|e| {
                tracing::error!("Failed to parse filters for cohort {}: {}", self.id, e);
                FlagError::CohortFiltersParsingError
            })?;

        let mut dependencies = HashSet::new();
        Self::traverse_filters(&cohort_property.properties, &mut dependencies)?;
        Ok(dependencies)
    }

    /// Recursively traverses the filter tree to find cohort dependencies
    ///
    /// Example filter tree structure:
    /// ```json
    /// {
    ///   "properties": {
    ///     "type": "OR",
    ///     "values": [
    ///       {
    ///         "type": "OR",
    ///         "values": [
    ///           {
    ///             "key": "id",
    ///             "value": 123,
    ///             "type": "cohort",
    ///             "operator": "exact"
    ///           },
    ///           {
    ///             "key": "email",
    ///             "value": "@posthog.com",
    ///             "type": "person",
    ///             "operator": "icontains"
    ///           }
    ///         ]
    ///       }
    ///     ]
    ///   }
    /// }
    /// ```
    fn traverse_filters(
        inner: &InnerCohortProperty,
        dependencies: &mut HashSet<CohortId>,
    ) -> Result<(), FlagError> {
        for cohort_values in &inner.values {
            for filter in &cohort_values.values {
                if filter.is_cohort() {
                    // Assuming the value is a single integer CohortId
                    if let Some(cohort_id) = filter.value.as_ref().and_then(|value| value.as_i64())
                    {
                        dependencies.insert(cohort_id as CohortId);
                    } else {
                        return Err(FlagError::CohortFiltersParsingError);
                    }
                }
                // NB: we don't support nested cohort properties, so we don't need to traverse further
            }
        }
        Ok(())
    }
}

impl InnerCohortProperty {
    /// Flattens the nested cohort property structure into a list of property filters.
    ///
    /// The cohort property structure in Postgres looks like:
    /// ```json
    /// {
    ///   "type": "OR",
    ///   "values": [
    ///     {
    ///       "type": "OR",
    ///       "values": [
    ///         {
    ///           "key": "email",
    ///           "value": "@posthog.com",
    ///           "type": "person",
    ///           "operator": "icontains"
    ///         },
    ///         {
    ///           "key": "age",
    ///           "value": 25,
    ///           "type": "person",
    ///           "operator": "gt"
    ///         }
    ///       ]
    ///     }
    ///   ]
    /// }
    /// ```
    pub fn to_inner(self) -> Vec<PropertyFilter> {
        self.values
            .into_iter()
            .flat_map(|value| value.values)
            .collect()
    }

    /// Evaluates a cohort property based on its type (AND/OR) and values.
    ///
    /// This function recursively evaluates the cohort property tree structure, handling both
    /// property matches and nested cohort membership checks.
    pub fn evaluate(
        &self,
        target_properties: &HashMap<String, Value>,
        cohort_matches: &HashMap<CohortId, bool>,
    ) -> Result<bool, FlagError> {
        match self.prop_type {
            CohortPropertyType::OR => {
                for cohort_values in &self.values {
                    if evaluate_cohort_values(cohort_values, target_properties, cohort_matches)? {
                        return Ok(true);
                    }
                }
                Ok(false)
            }
            CohortPropertyType::AND => {
                for cohort_values in &self.values {
                    if !evaluate_cohort_values(cohort_values, target_properties, cohort_matches)? {
                        return Ok(false);
                    }
                }
                Ok(true)
            }
        }
    }
}

/// Evaluates a set of cohort values against target properties.
///
/// This function handles both regular property matching and cohort membership checks
/// based on the property type (OR/AND/property).
fn evaluate_cohort_values(
    values: &CohortValues,
    target_properties: &HashMap<String, Value>,
    cohort_matches: &HashMap<CohortId, bool>,
) -> Result<bool, FlagError> {
    match values.prop_type.as_str() {
        "OR" => {
            for filter in &values.values {
                if filter.is_cohort() {
                    // Handle cohort membership check
                    if apply_cohort_membership_logic(&[filter.clone()], cohort_matches)? {
                        return Ok(true);
                    }
                } else {
                    // Handle regular property check
                    if match_property(filter, target_properties, false).unwrap_or(false) {
                        return Ok(true);
                    }
                }
            }
            Ok(false)
        }
        "AND" | "property" => {
            for filter in &values.values {
                if filter.is_cohort() {
                    // Handle cohort membership check
                    if !apply_cohort_membership_logic(&[filter.clone()], cohort_matches)? {
                        return Ok(false);
                    }
                } else {
                    // Handle regular property check
                    if !match_property(filter, target_properties, false).unwrap_or(false) {
                        return Ok(false);
                    }
                }
            }
            Ok(true)
        }
        _ => Err(FlagError::CohortFiltersParsingError),
    }
}

/// Evaluates a dynamic cohort and its dependencies using topological sorting.
///
/// This function:
/// 1. Checks if the cohort is static (returns early if it is)
/// 2. Builds a dependency graph of all related cohorts
/// 3. Sorts dependencies topologically to ensure proper evaluation order
/// 4. Evaluates each cohort in the correct order, respecting dependencies
pub fn evaluate_dynamic_cohorts(
    initial_cohort_id: CohortId,
    target_properties: &HashMap<String, Value>,
    cohorts: &[Cohort],
) -> Result<bool, FlagError> {
    // First check if this is a static cohort
    let initial_cohort = cohorts
        .iter()
        .find(|c| c.id == initial_cohort_id)
        .ok_or(FlagError::CohortNotFound(initial_cohort_id.to_string()))?;

    // If it's static, we don't need to evaluate dependencies
    if initial_cohort.is_static {
        return Ok(false); // Static cohorts are handled by evaluate_static_cohorts
    }

    let cohort_dependency_graph = build_cohort_dependency_graph(initial_cohort_id, cohorts)?;

    // Keep the topological sort to handle dependencies correctly
    let sorted_cohort_ids_as_graph_nodes =
        toposort(&cohort_dependency_graph, None).map_err(|e| {
            FlagError::CohortDependencyCycle(format!("Cyclic dependency detected: {:?}", e))
        })?;

    let mut evaluation_results = HashMap::new();

    // Iterate through the sorted nodes in reverse order
    for node in sorted_cohort_ids_as_graph_nodes.into_iter().rev() {
        let cohort_id = cohort_dependency_graph[node];
        let cohort = cohorts
            .iter()
            .find(|c| c.id == cohort_id)
            .ok_or(FlagError::CohortNotFound(cohort_id.to_string()))?;

        let dependencies = cohort.extract_dependencies()?;

        // Check if all dependencies have been met
        let dependencies_met = dependencies
            .iter()
            .all(|dep_id| evaluation_results.get(dep_id).copied().unwrap_or(false));

        // If dependencies are not met, mark as not matched and continue
        if !dependencies_met {
            evaluation_results.insert(cohort_id, false);
            continue;
        }

        // Here's where we use our new hierarchical evaluation
        let filters = match &cohort.filters {
            Some(filters) => filters,
            None => {
                evaluation_results.insert(cohort_id, false);
                continue;
            }
        };

        // Parse and evaluate using the hierarchical structure
        let cohort_property: CohortProperty = match serde_json::from_value(filters.clone()) {
            Ok(prop) => prop,
            Err(_) => {
                evaluation_results.insert(cohort_id, false);
                continue;
            }
        };

        // Use our new evaluation method that respects OR/AND structure
        let matches = cohort_property
            .properties
            .evaluate(target_properties, &evaluation_results)?;

        evaluation_results.insert(cohort_id, matches);
    }

    // Return the evaluation result for the initial cohort
    evaluation_results
        .get(&initial_cohort_id)
        .copied()
        .ok_or_else(|| FlagError::CohortNotFound(initial_cohort_id.to_string()))
}

/// Applies cohort membership logic for a set of cohort filters.
///
/// This function evaluates whether a person matches a set of cohort filters by:
/// 1. Checking each filter's cohort ID
/// 2. Looking up the match result in the cohort_matches map
/// 3. Applying the appropriate operator (IN/NOT_IN)
pub fn apply_cohort_membership_logic(
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
    cohorts: &[Cohort],
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
            let is_new_dep = !node_map.contains_key(&dep_id);
            let dep_node = node_map
                .entry(dep_id)
                .or_insert_with(|| graph.add_node(dep_id));
            graph.add_edge(current_node, *dep_node, ());
            if is_new_dep {
                queue.push_back(dep_id);
            }
        }
    }

    if is_cyclic_directed(&graph) {
        return Err(FlagError::CohortDependencyCycle(format!(
            "Cyclic dependency detected starting at cohort {}",
            initial_cohort_id
        )));
    }

    Ok(graph)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        cohorts::cohort_models::{CohortPropertyType, CohortValues},
        utils::test_utils::{
            insert_cohort_for_team_in_pg, setup_pg_reader_client, setup_pg_writer_client,
        },
    };
    use common_models::test_utils::insert_new_team_in_pg;
    use serde_json::json;

    #[tokio::test]
    async fn test_list_from_pg() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
            .await
            .expect("Failed to insert team");

        // Insert multiple cohorts for the team
        insert_cohort_for_team_in_pg(
            writer.clone(),
            team.id,
            Some("Cohort 1".to_string()),
            json!({"properties": {"type": "AND", "values": [{"type": "property", "values": [{"key": "age", "type": "person", "value": [30], "negation": false, "operator": "gt"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert cohort1");

        insert_cohort_for_team_in_pg(
            writer.clone(),
            team.id,
            Some("Cohort 2".to_string()),
            json!({"properties": {"type": "OR", "values": [{"type": "property", "values": [{"key": "country", "type": "person", "value": ["USA"], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert cohort2");

        let cohorts = Cohort::list_from_pg(reader, team.project_id)
            .await
            .expect("Failed to list cohorts");

        assert_eq!(cohorts.len(), 2);
        let names: HashSet<String> = cohorts.into_iter().filter_map(|c| c.name).collect();
        assert!(names.contains("Cohort 1"));
        assert!(names.contains("Cohort 2"));
    }

    #[test]
    fn test_cohort_parse_filters() {
        let cohort = Cohort {
            id: 1,
            name: Some("Test Cohort".to_string()),
            description: None,
            team_id: 1,
            deleted: false,
            filters: Some(
                json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$initial_browser_version", "type": "person", "value": ["125"], "negation": false, "operator": "exact"}]}]}}),
            ),
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

        let result = cohort.parse_filters().unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].key, "$initial_browser_version");
        assert_eq!(result[0].value, Some(json!(["125"])));
        assert_eq!(result[0].prop_type, "person");
    }

    #[test]
    fn test_cohort_property_to_inner() {
        let cohort_property = InnerCohortProperty {
            prop_type: CohortPropertyType::AND,
            values: vec![CohortValues {
                prop_type: "property".to_string(),
                values: vec![
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
                        operator: None,
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    },
                ],
            }],
        };

        let result = cohort_property.to_inner();
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].key, "email");
        assert_eq!(result[0].value, Some(json!("test@example.com")));
        assert_eq!(result[1].key, "age");
        assert_eq!(result[1].value, Some(json!(25)));
    }

    #[tokio::test]
    async fn test_extract_dependencies() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
            .await
            .expect("Failed to insert team");

        // Insert a single cohort that is dependent on another cohort
        let dependent_cohort = insert_cohort_for_team_in_pg(
            writer.clone(),
            team.id,
            Some("Dependent Cohort".to_string()),
            json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$browser", "type": "person", "value": ["Safari"], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert dependent_cohort");

        // Insert main cohort with a single dependency
        let main_cohort = insert_cohort_for_team_in_pg(
                writer.clone(),
                team.id,
                Some("Main Cohort".to_string()),
                json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "id", "type": "cohort", "value": dependent_cohort.id, "negation": false}]}]}}),
                false,
            )
            .await
            .expect("Failed to insert main_cohort");

        let cohorts = Cohort::list_from_pg(reader.clone(), team.project_id)
            .await
            .expect("Failed to fetch cohorts");

        let fetched_main_cohort = cohorts
            .into_iter()
            .find(|c| c.id == main_cohort.id)
            .expect("Failed to find main cohort");

        let dependencies = fetched_main_cohort.extract_dependencies().unwrap();
        let expected_dependencies: HashSet<CohortId> =
            [dependent_cohort.id].iter().cloned().collect();

        assert_eq!(dependencies, expected_dependencies);
    }
}
