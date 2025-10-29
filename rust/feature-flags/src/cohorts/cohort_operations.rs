use serde_json::Value;
use std::collections::HashMap;
use std::collections::HashSet;

use super::cohort_models::CohortPropertyType;
use super::cohort_models::CohortValues;
use crate::cohorts::cohort_models::{Cohort, CohortId, CohortProperty, InnerCohortProperty};
use crate::database::get_connection_with_metrics;
use crate::properties::property_matching::match_property;
use crate::properties::property_models::OperatorType;
use crate::utils::graph_utils::{DependencyGraph, DependencyProvider, DependencyType};
use crate::{api::errors::FlagError, properties::property_models::PropertyFilter};
use common_database::PostgresReader;

impl Cohort {
    /// Returns all cohorts for a given team
    pub async fn list_from_pg(
        client: PostgresReader,
        project_id: i64,
    ) -> Result<Vec<Cohort>, FlagError> {
        let mut conn = get_connection_with_metrics(&client, "non_persons_reader", "fetch_cohorts")
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to get database connection for project {}: {}",
                    project_id,
                    e
                );
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
                tracing::error!(
                    "Failed to fetch cohorts from database for project {}: {}",
                    project_id,
                    e
                );
                FlagError::Internal(format!("Database query error: {e}"))
            })?;

        Ok(cohorts)
    }

    /// Extracts dependent CohortIds from the cohort's filters
    ///
    /// # Returns
    /// * `HashSet<CohortId>` - A set of dependent cohort IDs
    /// * `FlagError` - If there is an error parsing the filters
    pub fn extract_dependencies(&self) -> Result<HashSet<CohortId>, FlagError> {
        // NB: static cohorts have no filters, so they have no dependencies
        // BUT, sometimes instead of having `None` or `{}`, they have an object like this
        // `{"properties": {}}`
        // So we need to explicitly check for this case and just return an empty set rather than trying to parse the filters at all
        if self.is_static {
            return Ok(HashSet::new());
        }

        let filters = match &self.filters {
            Some(filters) => filters,
            None => return Ok(HashSet::new()), // Return empty set if no filters
        };

        let cohort_property: CohortProperty =
            serde_json::from_value(filters.clone()).map_err(|e| {
                tracing::error!(
                    "Failed to parse filters for cohort {} (team {}): {}",
                    self.id,
                    self.team_id,
                    e
                );
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
                    if apply_cohort_membership_logic(std::slice::from_ref(filter), cohort_matches)? {
                        return Ok(true);
                    }
                } else {
                    // Handle regular property check with negation
                    if evaluate_property_with_negation(filter, target_properties) {
                        return Ok(true);
                    }
                }
            }
            Ok(false)
        }
        "AND" | "property" => {
            for filter in &values.values {
                if filter.is_cohort() {
                    // Handle cohort membership check with negation
                    let cohort_result =
                        apply_cohort_membership_logic(std::slice::from_ref(filter), cohort_matches)?;
                    // Apply negation if specified
                    if cohort_result == filter.negation.unwrap_or(false) {
                        return Ok(false);
                    }
                } else {
                    // Handle regular property check with negation
                    if !evaluate_property_with_negation(filter, target_properties) {
                        return Ok(false);
                    }
                }
            }
            Ok(true)
        }
        _ => Err(FlagError::CohortFiltersParsingError),
    }
}

/// Evaluates a property filter against target properties, applying negation if specified.
///
/// Cohort filters use the `negation` field to invert results, unlike flag filters
/// which use specific operators like `NotIContains`.
fn evaluate_property_with_negation(
    filter: &PropertyFilter,
    target_properties: &HashMap<String, Value>,
) -> bool {
    let property_result = match_property(filter, target_properties, false).unwrap_or(false);

    // Apply negation if specified
    if filter.negation.unwrap_or(false) {
        !property_result
    } else {
        property_result
    }
}

/// Evaluates a single cohort against target properties and existing evaluation results.
/// Returns true if the cohort matches, false otherwise.
fn evaluate_single_cohort(
    cohort: &Cohort,
    target_properties: &HashMap<String, Value>,
    evaluation_results: &HashMap<CohortId, bool>,
) -> Result<bool, FlagError> {
    // Get the filters for this cohort
    let filters = match &cohort.filters {
        Some(filters) => filters,
        None => return Ok(false),
    };

    // Parse and evaluate using the hierarchical structure
    let cohort_property: CohortProperty = match serde_json::from_value(filters.clone()) {
        Ok(prop) => prop,
        Err(_) => return Ok(false),
    };

    // Use our evaluation method that respects OR/AND structure
    cohort_property
        .properties
        .evaluate(target_properties, evaluation_results)
}

pub fn evaluate_dynamic_cohorts(
    initial_cohort_id: CohortId,
    target_properties: &HashMap<String, Value>,
    cohorts: &[Cohort],
) -> Result<bool, FlagError> {
    // First check if this is a static cohort
    let initial_cohort = cohorts
        .iter()
        .find(|c| c.id == initial_cohort_id)
        .ok_or_else(|| {
            FlagError::DependencyNotFound(DependencyType::Cohort, initial_cohort_id.into())
        })?
        .clone();

    // If it's static, we don't need to evaluate dependencies
    if initial_cohort.is_static {
        return Ok(false); // Static cohorts are handled by evaluate_static_cohorts
    }

    // Build the dependency graph
    let graph = DependencyGraph::new(initial_cohort, cohorts)?;

    // Use for_each_dependencies_first to evaluate each cohort in the correct order
    let results = graph.for_each_dependencies_first(|cohort, results, result| {
        *result = evaluate_single_cohort(cohort, target_properties, results)?;
        Ok(())
    })?;

    // Return the evaluation result for the initial cohort
    results.get(&initial_cohort_id).copied().ok_or_else(|| {
        FlagError::DependencyNotFound(DependencyType::Cohort, initial_cohort_id.into())
    })
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

// Implement DependencyProvider for Cohort
impl DependencyProvider for Cohort {
    type Id = CohortId;
    type Error = FlagError;

    fn get_id(&self) -> Self::Id {
        self.id
    }

    fn extract_dependencies(&self) -> Result<HashSet<Self::Id>, Self::Error> {
        self.extract_dependencies()
    }

    fn dependency_type() -> DependencyType {
        DependencyType::Cohort
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        cohorts::cohort_models::{CohortPropertyType, CohortValues},
        properties::property_models::PropertyType,
        utils::test_utils::TestContext,
    };
    use serde_json::json;

    #[tokio::test]
    async fn test_list_from_pg() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Insert multiple cohorts for the team
        context
            .insert_cohort(
                team.id,
                Some("Cohort 1".to_string()),
                json!({"properties": {"type": "AND", "values": [{"type": "property", "values": [{"key": "age", "type": "person", "value": [30], "negation": false, "operator": "gt"}]}]}}),
                false,
            )
            .await
            .expect("Failed to insert cohort1");

        context
            .insert_cohort(
                team.id,
                Some("Cohort 2".to_string()),
                json!({"properties": {"type": "OR", "values": [{"type": "property", "values": [{"key": "country", "type": "person", "value": ["USA"], "negation": false, "operator": "exact"}]}]}}),
                false,
            )
            .await
            .expect("Failed to insert cohort2");

        let cohorts = Cohort::list_from_pg(context.non_persons_reader, team.project_id)
            .await
            .expect("Failed to list cohorts");

        assert_eq!(cohorts.len(), 2);
        let names: HashSet<String> = cohorts.into_iter().filter_map(|c| c.name).collect();
        assert!(names.contains("Cohort 1"));
        assert!(names.contains("Cohort 2"));
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
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    },
                    PropertyFilter {
                        key: "age".to_string(),
                        value: Some(json!(25)),
                        operator: None,
                        prop_type: PropertyType::Person,
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
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Insert a single cohort that is dependent on another cohort
        let dependent_cohort = context
            .insert_cohort(
                team.id,
                Some("Dependent Cohort".to_string()),
                json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$browser", "type": "person", "value": ["Safari"], "negation": false, "operator": "exact"}]}]}}),
                false,
            )
            .await
            .expect("Failed to insert dependent_cohort");

        // Insert main cohort with a single dependency
        let main_cohort = context
            .insert_cohort(
                team.id,
                Some("Main Cohort".to_string()),
                json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "id", "type": "cohort", "value": dependent_cohort.id, "negation": false}]}]}}),
                false,
            )
            .await
            .expect("Failed to insert main_cohort");

        let cohorts = Cohort::list_from_pg(context.non_persons_reader.clone(), team.project_id)
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

    #[tokio::test]
    async fn test_static_cohort_with_malformed_filters() {
        // Test that static cohorts with malformed filters don't cause parsing errors
        let static_cohort_with_bad_filters = Cohort {
            id: 999,
            name: Some("Static Cohort with Bad Filters".to_string()),
            description: None,
            team_id: 1,
            deleted: false,
            // This is the problematic case - static cohorts sometimes have {"properties": {}}
            // instead of null, which would fail JSON parsing if we tried to parse it
            filters: Some(json!({"properties": {}})),
            query: None,
            version: None,
            pending_version: None,
            count: Some(100),
            is_calculating: false,
            is_static: true, // This is the key - it's static
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: None,
        };

        // This should not fail even though the filters are malformed
        let dependencies = static_cohort_with_bad_filters
            .extract_dependencies()
            .unwrap();
        assert_eq!(dependencies, HashSet::new());

        // Test another malformed case - empty object
        let static_cohort_empty_filters = Cohort {
            id: 998,
            name: Some("Static Cohort Empty".to_string()),
            description: None,
            team_id: 1,
            deleted: false,
            filters: Some(json!({})), // Empty object
            query: None,
            version: None,
            pending_version: None,
            count: Some(50),
            is_calculating: false,
            is_static: true,
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: None,
        };

        let dependencies = static_cohort_empty_filters.extract_dependencies().unwrap();
        assert_eq!(dependencies, HashSet::new());

        // Verify that a dynamic cohort with the same malformed filters WOULD fail
        let dynamic_cohort_with_bad_filters = Cohort {
            id: 997,
            name: Some("Dynamic Cohort with Bad Filters".to_string()),
            description: None,
            team_id: 1,
            deleted: false,
            filters: Some(json!({"properties": {}})), // Same malformed filters
            query: None,
            version: None,
            pending_version: None,
            count: None,
            is_calculating: false,
            is_static: false, // This is dynamic, so it should fail
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: None,
        };

        // This should fail because it's dynamic and the filters are malformed
        let result = dynamic_cohort_with_bad_filters.extract_dependencies();
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            FlagError::CohortFiltersParsingError
        ));
    }

    fn create_test_cohort_instance(id: CohortId, depends_on: Option<CohortId>) -> Cohort {
        Cohort {
            id,
            name: Some(format!("Cohort {id}")),
            description: None,
            team_id: 1,
            deleted: false,
            filters: depends_on.map(|dep_id| {
                json!({
                    "properties": {
                        "type": "OR",
                        "values": [{
                            "type": "OR",
                            "values": [{
                                "key": "id",
                                "type": "cohort",
                                "value": dep_id,
                                "negation": false
                            }]
                        }]
                    }
                })
            }),
            query: None,
            version: None,
            pending_version: None,
            count: None,
            is_calculating: false,
            is_static: false,
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: None,
        }
    }

    #[test]
    fn test_build_cohort_dependency_graph_cycle_detection() {
        // Create four cohorts that form a cycle: 2 -> 3 -> 4 -> 2
        // Cohort 1 is not part of the cycle but depends on 2
        let cohort_1 = create_test_cohort_instance(1, Some(2)); // 1 depends on 2
        let cohort_2 = create_test_cohort_instance(2, Some(3)); // 2 depends on 3
        let cohort_3 = create_test_cohort_instance(3, Some(4)); // 3 depends on 4
        let cohort_4 = create_test_cohort_instance(4, Some(2)); // 4 depends on 2 (starts the cycle)

        let cohorts = vec![cohort_1.clone(), cohort_2, cohort_3, cohort_4];

        // Try to build the graph starting from cohort 1
        let result = DependencyGraph::new(cohort_1, &cohorts);

        // Verify we got a cycle error
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(
            err,
            FlagError::DependencyCycle(DependencyType::Cohort, 4)
        ));
    }

    #[test]
    fn test_evaluate_dynamic_cohorts_static_cohort_early_exit() {
        // Create a static cohort
        let static_cohort = Cohort {
            id: 1,
            name: Some("Static Cohort".to_string()),
            description: None,
            team_id: 1,
            deleted: false,
            filters: None,
            query: None,
            version: None,
            pending_version: None,
            count: Some(100),
            is_calculating: false,
            is_static: true,
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: None,
        };

        let cohorts = vec![static_cohort];
        let target_properties = HashMap::new();

        // evaluate_dynamic_cohorts should return false early for static cohorts
        let result = evaluate_dynamic_cohorts(1, &target_properties, &cohorts).unwrap();
        assert!(
            !result,
            "Static cohorts should return false from evaluate_dynamic_cohorts"
        );
    }

    #[test]
    fn test_evaluate_dynamic_cohorts_with_negation_filters() {
        // Create a cohort with filters that include negation
        // This cohort should match people with emails ending in @example.com
        // BUT exclude those containing "excluded.user"
        let cohort_with_negation = Cohort {
            id: 1,
            name: Some("Cohort with Negation".to_string()),
            description: None,
            team_id: 1,
            deleted: false,
            filters: Some(json!({
                "properties": {
                    "type": "OR",
                    "values": [{
                        "type": "AND",
                        "values": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "^.*@example.com$",
                                "negation": false,
                                "operator": "regex"
                            },
                            {
                                "key": "email",
                                "type": "person",
                                "value": "excluded.user",
                                "negation": true,  // This should be inverted
                                "operator": "icontains"
                            }
                        ]
                    }]
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

        let cohorts = vec![cohort_with_negation];

        // Test case 1: User with @example.com email but NOT excluded
        // Should match because: regex matches AND (icontains doesn't match -> negated to true)
        let mut target_properties = HashMap::new();
        target_properties.insert("email".to_string(), json!("test.user@example.com"));

        let result = evaluate_dynamic_cohorts(1, &target_properties, &cohorts).unwrap();
        assert!(
            result,
            "User with @example.com email should match when not excluded"
        );

        // Test case 2: User with @example.com email but IS excluded
        // Should NOT match because: regex matches BUT (icontains matches -> negated to false)
        target_properties.insert("email".to_string(), json!("excluded.user@example.com"));

        let result = evaluate_dynamic_cohorts(1, &target_properties, &cohorts).unwrap();
        assert!(
            !result,
            "User with @example.com email should NOT match when excluded"
        );

        // Test case 3: User without @example.com email
        // Should NOT match because: regex doesn't match (regardless of negation)
        target_properties.insert("email".to_string(), json!("test.user@other.com"));

        let result = evaluate_dynamic_cohorts(1, &target_properties, &cohorts).unwrap();
        assert!(!result, "User without @example.com email should NOT match");

        // Test case 4: User with excluded term but wrong domain
        // Should NOT match because: regex doesn't match (regardless of negation)
        target_properties.insert("email".to_string(), json!("excluded.user@other.com"));

        let result = evaluate_dynamic_cohorts(1, &target_properties, &cohorts).unwrap();
        assert!(
            !result,
            "User with wrong domain should NOT match regardless of exclusion"
        );
    }
}
