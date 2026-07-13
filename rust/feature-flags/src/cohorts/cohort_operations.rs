use serde_json::Value;
use std::borrow::Borrow;
use std::collections::HashMap;
use std::collections::HashSet;

use super::cohort_models::CohortPropertyType;
use super::cohort_models::CohortValues;
use crate::cohorts::cohort_cache_manager::CohortFetchError;
use crate::cohorts::cohort_models::{
    Cohort, CohortId, CohortProperty, CohortValuesItem, InnerCohortProperty,
};
use crate::database::get_connection_with_metrics;
use crate::properties::property_matching::match_property;
use crate::properties::property_models::OperatorType;
use crate::utils::graph_utils::{DependencyGraph, DependencyProvider, DependencyType};
use crate::{api::errors::FlagError, properties::property_models::PropertyFilter};
use chrono_tz::Tz;
use common_database::PostgresReader;
use common_types::TeamId;

/// Maximum cohort filter group nesting depth walked during evaluation and dependency
/// extraction. The cohort UI tops out at 3-4 levels; this generous bound guards the hot
/// `/flags` path against stack overflow from an adversarially deep filter tree.
const MAX_COHORT_FILTER_DEPTH: usize = 64;

/// Column list for `posthog_cohort` queries. Must match the fields in `Cohort` (sqlx::FromRow).
const COHORT_COLUMNS: &str = r#"
    c.id, c.name, c.description, c.team_id, c.deleted, c.filters,
    c.query, c.version, c.pending_version, c.count, c.is_calculating,
    c.is_static, c.errors_calculating, c.groups, c.created_by_id,
    c.cohort_type, c.last_backfill_person_properties_at
"#;

impl Cohort {
    /// Returns all cohorts for a given team
    pub async fn list_from_pg(
        client: PostgresReader,
        team_id: TeamId,
    ) -> Result<Vec<Cohort>, CohortFetchError> {
        let mut conn = get_connection_with_metrics(&client, "non_persons_reader", "fetch_cohorts")
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to get database connection for team {}: {}",
                    team_id,
                    e
                );
                CohortFetchError::DatabaseUnavailable
            })?;

        let query = format!(
            "SELECT {COHORT_COLUMNS} FROM posthog_cohort AS c \
             JOIN posthog_team AS t ON (c.team_id = t.id) \
             WHERE t.id = $1 AND c.deleted = false"
        );
        let cohorts = sqlx::query_as::<_, Cohort>(&query)
            .bind(team_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to fetch cohorts from database for team {}: {}",
                    team_id,
                    e
                );
                CohortFetchError::QueryFailed(format!("Database query error: {e}"))
            })?;

        Ok(cohorts)
    }

    /// Fetch cohorts by a set of IDs, filtered to non-deleted cohorts for the given team.
    /// Used by the cache builder for BFS cohort dependency resolution.
    pub async fn list_by_ids_from_pg(
        client: &PostgresReader,
        team_id: TeamId,
        ids: &[CohortId],
    ) -> Result<Vec<Cohort>, CohortFetchError> {
        if ids.is_empty() {
            return Ok(vec![]);
        }

        let mut conn =
            get_connection_with_metrics(client, "non_persons_reader", "fetch_cohorts_for_cache")
                .await
                .map_err(|e| {
                    tracing::error!(
                        "Failed to get database connection for team {}: {}",
                        team_id,
                        e
                    );
                    CohortFetchError::DatabaseUnavailable
                })?;

        let query = format!(
            "SELECT {COHORT_COLUMNS} FROM posthog_cohort AS c \
             WHERE c.id = ANY($1) AND c.deleted = false AND c.team_id = $2"
        );

        let cohorts = sqlx::query_as::<_, Cohort>(&query)
            .bind(ids)
            .bind(team_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to fetch cohorts from database for team {}: {}",
                    team_id,
                    e
                );
                CohortFetchError::QueryFailed(format!("Database query error: {e}"))
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
        for item in &inner.values {
            Self::traverse_item(item, dependencies, 0)?;
        }
        Ok(())
    }

    /// Visits a group-or-filter entry, recursing into nested groups.
    fn traverse_item(
        item: &CohortValuesItem,
        dependencies: &mut HashSet<CohortId>,
        depth: usize,
    ) -> Result<(), FlagError> {
        if depth > MAX_COHORT_FILTER_DEPTH {
            return Err(FlagError::CohortFiltersParsingError);
        }
        match item {
            CohortValuesItem::Group(group) => {
                for nested in &group.values {
                    Self::traverse_item(nested, dependencies, depth + 1)?;
                }
            }
            CohortValuesItem::Filter(filter) => {
                if filter.is_cohort() {
                    if let Some(cohort_id) = filter.get_cohort_id() {
                        dependencies.insert(cohort_id);
                    } else {
                        return Err(FlagError::CohortFiltersParsingError);
                    }
                }
            }
        }
        Ok(())
    }
}

impl InnerCohortProperty {
    /// Evaluates a cohort property based on its type (AND/OR) and values.
    ///
    /// This function recursively evaluates the cohort property tree structure, handling both
    /// property matches and nested cohort membership checks.
    pub fn evaluate(
        &self,
        target_properties: &HashMap<String, Value>,
        cohort_matches: &HashMap<CohortId, bool>,
        team_timezone: Tz,
    ) -> Result<bool, FlagError> {
        match self.prop_type {
            CohortPropertyType::OR => {
                for item in &self.values {
                    if evaluate_cohort_item(
                        item,
                        target_properties,
                        cohort_matches,
                        0,
                        team_timezone,
                    )? {
                        return Ok(true);
                    }
                }
                Ok(false)
            }
            CohortPropertyType::AND => {
                for item in &self.values {
                    if !evaluate_cohort_item(
                        item,
                        target_properties,
                        cohort_matches,
                        0,
                        team_timezone,
                    )? {
                        return Ok(false);
                    }
                }
                Ok(true)
            }
        }
    }
}

/// Evaluates a group-or-filter entry, recursing into nested groups.
fn evaluate_cohort_item(
    item: &CohortValuesItem,
    target_properties: &HashMap<String, Value>,
    cohort_matches: &HashMap<CohortId, bool>,
    depth: usize,
    team_timezone: Tz,
) -> Result<bool, FlagError> {
    if depth > MAX_COHORT_FILTER_DEPTH {
        return Err(FlagError::CohortFiltersParsingError);
    }
    match item {
        CohortValuesItem::Group(group) => evaluate_cohort_values(
            group,
            target_properties,
            cohort_matches,
            depth,
            team_timezone,
        ),
        CohortValuesItem::Filter(filter) => {
            evaluate_cohort_filter(filter, target_properties, cohort_matches, team_timezone)
        }
    }
}

/// Evaluates a leaf property filter, applying `negation` for both filter kinds.
fn evaluate_cohort_filter(
    filter: &PropertyFilter,
    target_properties: &HashMap<String, Value>,
    cohort_matches: &HashMap<CohortId, bool>,
    team_timezone: Tz,
) -> Result<bool, FlagError> {
    if filter.is_cohort() {
        // Handle cohort membership check with negation
        let cohort_result =
            apply_cohort_membership_logic(std::slice::from_ref(filter), cohort_matches)?;
        Ok(cohort_result != filter.negation.unwrap_or(false))
    } else {
        // Handle regular property check with negation
        Ok(evaluate_property_with_negation(
            filter,
            target_properties,
            team_timezone,
        ))
    }
}

/// Evaluates a set of cohort values against target properties.
///
/// Entries may be property filters or nested groups, combined with the group's
/// logical type (OR/AND/property, where "property" is a legacy alias for AND).
/// `depth` is the caller's depth; the recursion guard lives in `evaluate_cohort_item`,
/// which every nested entry routes back through.
fn evaluate_cohort_values(
    values: &CohortValues,
    target_properties: &HashMap<String, Value>,
    cohort_matches: &HashMap<CohortId, bool>,
    depth: usize,
    team_timezone: Tz,
) -> Result<bool, FlagError> {
    match values.prop_type.as_str() {
        "OR" => {
            for item in &values.values {
                if evaluate_cohort_item(
                    item,
                    target_properties,
                    cohort_matches,
                    depth + 1,
                    team_timezone,
                )? {
                    return Ok(true);
                }
            }
            Ok(false)
        }
        "AND" | "property" => {
            for item in &values.values {
                if !evaluate_cohort_item(
                    item,
                    target_properties,
                    cohort_matches,
                    depth + 1,
                    team_timezone,
                )? {
                    return Ok(false);
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
    team_timezone: Tz,
) -> bool {
    let property_result =
        match_property(filter, target_properties, false, team_timezone).unwrap_or(false);

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
    team_timezone: Tz,
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
        .evaluate(target_properties, evaluation_results, team_timezone)
}

pub fn evaluate_dynamic_cohorts(
    initial_cohort_id: CohortId,
    target_properties: &HashMap<String, Value>,
    cohorts: &[Cohort],
    static_cohort_matches: &HashMap<CohortId, bool>,
    team_timezone: Tz,
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
        // If this is a static cohort dependency, use the cached result
        if cohort.is_static {
            let cached_result = static_cohort_matches
                .get(&cohort.id)
                .copied()
                .unwrap_or(false);
            *result = cached_result;
            return Ok(());
        }

        *result = evaluate_single_cohort(cohort, target_properties, results, team_timezone)?;
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
pub fn apply_cohort_membership_logic<F: Borrow<PropertyFilter>>(
    cohort_filters: &[F],
    cohort_matches: &HashMap<CohortId, bool>,
) -> Result<bool, FlagError> {
    for filter in cohort_filters {
        let filter = filter.borrow();
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
    use crate::utils::test_utils::TestContext;
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

        let cohorts = Cohort::list_from_pg(context.non_persons_reader, team.id)
            .await
            .expect("Failed to list cohorts");

        assert_eq!(cohorts.len(), 2);
        let names: HashSet<String> = cohorts.into_iter().filter_map(|c| c.name).collect();
        assert!(names.contains("Cohort 1"));
        assert!(names.contains("Cohort 2"));
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

        let cohorts = Cohort::list_from_pg(context.non_persons_reader.clone(), team.id)
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
            cohort_type: None,
            last_backfill_person_properties_at: None,
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
            cohort_type: None,
            last_backfill_person_properties_at: None,
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
            cohort_type: None,
            last_backfill_person_properties_at: None,
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
            cohort_type: None,
            last_backfill_person_properties_at: None,
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
    fn test_evaluate_dynamic_cohorts_with_static_cohort_dependency() {
        // Create a static cohort (cohort 10)
        let static_cohort = Cohort {
            id: 10,
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
            cohort_type: None,
            last_backfill_person_properties_at: None,
        };

        // Create a dynamic cohort (cohort 20) that depends on the static cohort
        let dynamic_cohort = Cohort {
            id: 20,
            name: Some("Dynamic Cohort with Static Dependency".to_string()),
            description: None,
            team_id: 1,
            deleted: false,
            filters: Some(json!({
                "properties": {
                    "type": "OR",
                    "values": [{
                        "type": "OR",
                        "values": [{
                            "key": "id",
                            "type": "cohort",
                            "value": 10,
                            "negation": false
                        }]
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
            cohort_type: None,
            last_backfill_person_properties_at: None,
        };

        let cohorts = vec![static_cohort, dynamic_cohort];
        let target_properties = HashMap::new();

        // Test case 1: Static cohort is in cache and matches
        let mut static_cohort_matches = HashMap::new();
        static_cohort_matches.insert(10, true);

        let result = evaluate_dynamic_cohorts(
            20,
            &target_properties,
            &cohorts,
            &static_cohort_matches,
            Tz::UTC,
        )
        .unwrap();
        assert!(
            result,
            "Dynamic cohort should match when its static cohort dependency matches"
        );

        // Test case 2: Static cohort is in cache but doesn't match
        let mut static_cohort_matches = HashMap::new();
        static_cohort_matches.insert(10, false);

        let result = evaluate_dynamic_cohorts(
            20,
            &target_properties,
            &cohorts,
            &static_cohort_matches,
            Tz::UTC,
        )
        .unwrap();
        assert!(
            !result,
            "Dynamic cohort should not match when its static cohort dependency doesn't match"
        );

        // Test case 3: Static cohort is not in cache (defaults to false)
        let static_cohort_matches = HashMap::new();

        let result = evaluate_dynamic_cohorts(
            20,
            &target_properties,
            &cohorts,
            &static_cohort_matches,
            Tz::UTC,
        )
        .unwrap();
        assert!(
            !result,
            "Dynamic cohort should not match when static cohort is not in cache"
        );
    }

    #[test]
    fn test_dynamic_cohort_datetime_filter_uses_team_timezone() {
        // A dynamic cohort with a naive datetime person-property filter must be
        // evaluated in the team timezone so Rust flag membership agrees with the
        // HogQL/ClickHouse cohort path. For a Pacific team, the filter "2024-06-01"
        // (is_date_after) resolves to 2024-06-01 07:00 UTC (PDT, UTC-7 in June).
        let cohort = Cohort {
            id: 30,
            name: Some("Datetime Cohort".to_string()),
            description: None,
            team_id: 1,
            deleted: false,
            filters: Some(json!({
                "properties": {
                    "type": "OR",
                    "values": [{
                        "type": "OR",
                        "values": [{
                            "key": "joined_at",
                            "type": "person",
                            "value": "2024-06-01",
                            "negation": false,
                            "operator": "is_date_after"
                        }]
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
            cohort_type: None,
            last_backfill_person_properties_at: None,
        };

        let cohorts = vec![cohort];
        let static_matches = HashMap::new();

        // Person joined 03:00 UTC on June 1 — after UTC midnight, but before
        // Pacific midnight (07:00 UTC). This is the offset window where the two
        // timezone interpretations disagree.
        let person = HashMap::from([("joined_at".to_string(), json!("2024-06-01T03:00:00Z"))]);

        // Pacific: the person is not strictly after the local-midnight boundary,
        // so they are not a member — matching HogQL cohort membership.
        assert!(!evaluate_dynamic_cohorts(
            30,
            &person,
            &cohorts,
            &static_matches,
            Tz::America__Los_Angeles
        )
        .unwrap());

        // UTC (the pre-fix interpretation) would include them, proving the team
        // timezone actually changes the cohort decision in this window.
        assert!(evaluate_dynamic_cohorts(30, &person, &cohorts, &static_matches, Tz::UTC).unwrap());
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
            cohort_type: None,
            last_backfill_person_properties_at: None,
        };

        let cohorts = vec![cohort_with_negation];
        let static_cohort_matches = HashMap::new();

        // Test case 1: User with @example.com email but NOT excluded
        // Should match because: regex matches AND (icontains doesn't match -> negated to true)
        let mut target_properties = HashMap::new();
        target_properties.insert("email".to_string(), json!("test.user@example.com"));

        let result = evaluate_dynamic_cohorts(
            1,
            &target_properties,
            &cohorts,
            &static_cohort_matches,
            Tz::UTC,
        )
        .unwrap();
        assert!(
            result,
            "User with @example.com email should match when not excluded"
        );

        // Test case 2: User with @example.com email but IS excluded
        // Should NOT match because: regex matches BUT (icontains matches -> negated to false)
        target_properties.insert("email".to_string(), json!("excluded.user@example.com"));

        let result = evaluate_dynamic_cohorts(
            1,
            &target_properties,
            &cohorts,
            &static_cohort_matches,
            Tz::UTC,
        )
        .unwrap();
        assert!(
            !result,
            "User with @example.com email should NOT match when excluded"
        );

        // Test case 3: User without @example.com email
        // Should NOT match because: regex doesn't match (regardless of negation)
        target_properties.insert("email".to_string(), json!("test.user@other.com"));

        let result = evaluate_dynamic_cohorts(
            1,
            &target_properties,
            &cohorts,
            &static_cohort_matches,
            Tz::UTC,
        )
        .unwrap();
        assert!(!result, "User without @example.com email should NOT match");

        // Test case 4: User with excluded term but wrong domain
        // Should NOT match because: regex doesn't match (regardless of negation)
        target_properties.insert("email".to_string(), json!("excluded.user@other.com"));

        let result = evaluate_dynamic_cohorts(
            1,
            &target_properties,
            &cohorts,
            &static_cohort_matches,
            Tz::UTC,
        )
        .unwrap();
        assert!(
            !result,
            "User with wrong domain should NOT match regardless of exclusion"
        );
    }

    fn create_dynamic_cohort_with_filters(id: CohortId, filters: serde_json::Value) -> Cohort {
        Cohort {
            id,
            name: Some(format!("Cohort {id}")),
            description: None,
            team_id: 1,
            deleted: false,
            filters: Some(filters),
            query: None,
            version: None,
            pending_version: None,
            count: None,
            is_calculating: false,
            is_static: false,
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: None,
            cohort_type: None,
            last_backfill_person_properties_at: None,
        }
    }

    #[test]
    fn test_extract_dependencies_with_flat_and_nested_filters() {
        // Cohorts created via the API can place property filters (including cohort
        // references) directly inside `properties.values` without an inner group, and
        // can nest groups deeper than the UI does.
        let cohort = create_dynamic_cohort_with_filters(
            1,
            json!({
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"},
                        {"key": "id", "type": "cohort", "value": 5, "negation": false},
                        {"type": "OR", "values": [
                            {"type": "AND", "values": [
                                {"key": "id", "type": "cohort", "value": 6, "negation": false}
                            ]}
                        ]}
                    ]
                }
            }),
        );

        let dependencies = cohort
            .extract_dependencies()
            .expect("Flat and nested cohort filters should parse");
        let expected_dependencies: HashSet<CohortId> = [5, 6].iter().cloned().collect();
        assert_eq!(dependencies, expected_dependencies);
    }

    #[test]
    fn test_evaluate_dynamic_cohorts_with_flat_person_property_filters() {
        // Regression test: flags referencing a cohort with this shape returned
        // `cohort_filters_parsing_error`, even though the cohort itself worked fine in
        // the rest of the product (the Python query layer accepts it).
        let cohort = create_dynamic_cohort_with_filters(
            1,
            json!({
                "properties": {
                    "type": "OR",
                    "values": [
                        {"key": "tenantId", "type": "person", "value": ["A", "B", "C"], "operator": "exact", "negation": false}
                    ]
                }
            }),
        );

        let cohorts = vec![cohort];
        let static_cohort_matches = HashMap::new();

        let test_cases = [
            (json!("B"), true),  // listed tenantId should match
            (json!("Z"), false), // unlisted tenantId should NOT match
        ];

        for (tenant_id, expected) in test_cases {
            let target_properties = HashMap::from([("tenantId".to_string(), tenant_id.clone())]);
            let result = evaluate_dynamic_cohorts(
                1,
                &target_properties,
                &cohorts,
                &static_cohort_matches,
                Tz::UTC,
            )
            .unwrap();
            assert_eq!(
                result, expected,
                "tenantId={tenant_id} should evaluate to {expected}"
            );
        }
    }

    #[test]
    fn test_evaluate_dynamic_cohorts_with_nested_groups() {
        // Matches people with: email contains @example.com AND (plan = pro OR age > 30)
        let cohort = create_dynamic_cohort_with_filters(
            1,
            json!({
                "properties": {
                    "type": "AND",
                    "values": [{
                        "type": "AND",
                        "values": [
                            {"key": "email", "type": "person", "value": "@example.com", "operator": "icontains"},
                            {"type": "OR", "values": [
                                {"key": "plan", "type": "person", "value": "pro", "operator": "exact"},
                                {"key": "age", "type": "person", "value": 30, "operator": "gt"}
                            ]}
                        ]
                    }]
                }
            }),
        );

        let cohorts = vec![cohort];
        let static_cohort_matches = HashMap::new();

        let test_cases = [
            (json!("a@example.com"), json!("pro"), json!(25), true),
            (json!("a@example.com"), json!("free"), json!(40), true),
            (json!("a@example.com"), json!("free"), json!(25), false),
            (json!("a@other.com"), json!("pro"), json!(40), false),
        ];

        for (email, plan, age, expected) in test_cases {
            let target_properties = HashMap::from([
                ("email".to_string(), email.clone()),
                ("plan".to_string(), plan.clone()),
                ("age".to_string(), age.clone()),
            ]);
            let result = evaluate_dynamic_cohorts(
                1,
                &target_properties,
                &cohorts,
                &static_cohort_matches,
                Tz::UTC,
            )
            .unwrap();
            assert_eq!(
                result, expected,
                "email={email}, plan={plan}, age={age} should evaluate to {expected}"
            );
        }
    }

    #[test]
    fn test_evaluate_dynamic_cohorts_with_negated_cohort_reference_in_or_group() {
        // A "not in cohort" criterion is saved as a cohort reference with
        // `negation: true` and no operator — the negation must be respected inside OR
        // groups, not just AND groups.
        let inner_cohort = create_dynamic_cohort_with_filters(
            1,
            json!({
                "properties": {"type": "OR", "values": [{"type": "OR", "values": [
                    {"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"}
                ]}]}
            }),
        );
        let outer_cohort = create_dynamic_cohort_with_filters(
            2,
            json!({
                "properties": {"type": "OR", "values": [{"type": "OR", "values": [
                    {"key": "id", "type": "cohort", "value": 1, "negation": true}
                ]}]}
            }),
        );

        let cohorts = vec![inner_cohort, outer_cohort];
        let static_cohort_matches = HashMap::new();

        let test_cases = [
            (json!("someone@posthog.com"), false), // in the negated cohort -> should NOT match
            (json!("someone@example.com"), true),  // outside the negated cohort -> should match
        ];

        for (email, expected) in test_cases {
            let target_properties = HashMap::from([("email".to_string(), email.clone())]);
            let result = evaluate_dynamic_cohorts(
                2,
                &target_properties,
                &cohorts,
                &static_cohort_matches,
                Tz::UTC,
            )
            .unwrap();
            assert_eq!(
                result, expected,
                "email={email} should evaluate to {expected}"
            );
        }
    }

    /// Wraps `leaf` in `levels` nested AND groups: {type: AND, values: [{type: AND, values: [... leaf]}]}.
    fn nest_in_groups(leaf: serde_json::Value, levels: usize) -> serde_json::Value {
        let mut current = leaf;
        for _ in 0..levels {
            current = json!({"type": "AND", "values": [current]});
        }
        current
    }

    #[test]
    fn test_deeply_nested_cohort_filters_error_instead_of_overflowing() {
        // A filter tree deeper than MAX_COHORT_FILTER_DEPTH must fail with a parsing
        // error rather than recursing until the worker thread's stack overflows.
        let leaf = json!({"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"});
        let deep_properties = nest_in_groups(leaf, MAX_COHORT_FILTER_DEPTH + 10);
        let cohort =
            create_dynamic_cohort_with_filters(1, json!({ "properties": deep_properties }));

        // Dependency extraction bails out with the parsing error.
        assert!(matches!(
            cohort.extract_dependencies(),
            Err(FlagError::CohortFiltersParsingError)
        ));

        // Evaluation surfaces the same error instead of overflowing the stack.
        let cohorts = vec![cohort];
        let target_properties = HashMap::from([("email".to_string(), json!("a@posthog.com"))]);
        assert!(matches!(
            evaluate_dynamic_cohorts(1, &target_properties, &cohorts, &HashMap::new(), Tz::UTC),
            Err(FlagError::CohortFiltersParsingError)
        ));
    }

    #[test]
    fn test_cohort_filters_at_max_depth_still_evaluate() {
        // The deepest tree the guard allows must still evaluate, not error — pins the
        // off-by-one so a future tweak to MAX_COHORT_FILTER_DEPTH can't silently start
        // rejecting legitimate cohorts. InnerCohortProperty::evaluate consumes the
        // outermost group at depth 0, so the leaf sits at depth N-1; N = MAX + 1 is the
        // largest tree whose leaf lands exactly on the depth limit.
        let leaf = json!({"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"});
        let at_limit = nest_in_groups(leaf, MAX_COHORT_FILTER_DEPTH + 1);
        let cohort = create_dynamic_cohort_with_filters(1, json!({ "properties": at_limit }));

        cohort
            .extract_dependencies()
            .expect("a tree at the depth limit should parse");

        let cohorts = vec![cohort];
        let target_properties = HashMap::from([("email".to_string(), json!("a@posthog.com"))]);
        assert!(matches!(
            evaluate_dynamic_cohorts(1, &target_properties, &cohorts, &HashMap::new(), Tz::UTC),
            Ok(true)
        ));
    }

    #[test]
    fn test_evaluate_dynamic_cohorts_with_legacy_property_group_type() {
        // The cohort UI emits "property" as the inner group type — a legacy alias that
        // must behave like "AND".
        let cohort = create_dynamic_cohort_with_filters(
            1,
            json!({
                "properties": {
                    "type": "OR",
                    "values": [{
                        "type": "property",
                        "values": [
                            {"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"},
                            {"key": "plan", "type": "person", "value": "pro", "operator": "exact"}
                        ]
                    }]
                }
            }),
        );

        let cohorts = vec![cohort];
        let static_cohort_matches = HashMap::new();

        let test_cases = [
            (json!("a@posthog.com"), json!("pro"), true), // both match -> AND true
            (json!("a@posthog.com"), json!("free"), false), // plan fails -> AND false
            (json!("a@other.com"), json!("pro"), false),  // email fails -> AND false
        ];

        for (email, plan, expected) in test_cases {
            let target_properties = HashMap::from([
                ("email".to_string(), email.clone()),
                ("plan".to_string(), plan.clone()),
            ]);
            let result = evaluate_dynamic_cohorts(
                1,
                &target_properties,
                &cohorts,
                &static_cohort_matches,
                Tz::UTC,
            )
            .unwrap();
            assert_eq!(
                result, expected,
                "email={email}, plan={plan} should evaluate to {expected}"
            );
        }
    }

    #[test]
    fn test_evaluate_dynamic_cohorts_with_unknown_group_type_errors() {
        // An unrecognized group type must fail loudly rather than silently matching or
        // not matching.
        let cohort = create_dynamic_cohort_with_filters(
            1,
            json!({
                "properties": {
                    "type": "OR",
                    "values": [{
                        "type": "XOR",
                        "values": [
                            {"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"}
                        ]
                    }]
                }
            }),
        );

        let cohorts = vec![cohort];
        let target_properties = HashMap::from([("email".to_string(), json!("a@posthog.com"))]);
        assert!(matches!(
            evaluate_dynamic_cohorts(1, &target_properties, &cohorts, &HashMap::new(), Tz::UTC),
            Err(FlagError::CohortFiltersParsingError)
        ));
    }
}
