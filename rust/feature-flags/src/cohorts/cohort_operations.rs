use crate::{
    api::errors::FlagError,
    clients::database::Client as DatabaseClient,
    cohorts::cohort_models::{Cohort, CohortId, CohortOrEmpty, CohortRow, InnerCohortProperty},
    properties::property_models::PropertyFilter,
};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tracing::instrument;

impl Cohort {
    /// Returns a list of cohorts from postgres given a list of cohort_ids and team_id
    #[instrument(skip_all)]
    pub async fn list_from_pg(
        client: Arc<dyn DatabaseClient + Send + Sync>,
        cohort_ids: &[i32],
        team_id: i32,
    ) -> Result<Vec<Cohort>, FlagError> {
        let mut conn = client.get_connection().await.map_err(|e| {
            // TODO should I model my errors more generally?  Like, yes, everything behind this API is technically a FlagError,
            // but I'm not sure if accessing Cohort definitions should be a FlagError (vs idk, a CohortError?  A more general API error?)
            tracing::error!("Failed to get database connection: {}", e);
            FlagError::DatabaseUnavailable
        })?;

        let query = "SELECT id, name, description, team_id, deleted, filters, query, version, pending_version, count, is_calculating, is_static, errors_calculating, groups, created_by_id FROM posthog_cohort WHERE id = ANY($1) AND team_id = $2";
        let cohort_rows = sqlx::query_as::<_, CohortRow>(query)
            .bind(cohort_ids)
            .bind(team_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!("Failed to fetch cohorts from database: {}", e);
                FlagError::Internal(format!("Database query error: {}", e))
            })?;

        let cohorts = cohort_rows
            .into_iter()
            .map(|row| Cohort {
                id: row.id,
                name: row.name,
                description: row.description,
                team_id: row.team_id,
                deleted: row.deleted,
                filters: row.filters,
                query: row.query,
                version: row.version,
                pending_version: row.pending_version,
                count: row.count,
                is_calculating: row.is_calculating,
                is_static: row.is_static,
                errors_calculating: row.errors_calculating,
                groups: row.groups,
                created_by_id: row.created_by_id,
            })
            .collect();

        Ok(cohorts)
    }

    /// Parses the filters JSON into a CohortProperty structure
    // TODO: this needs to the deprecated "groups" field as well
    pub fn parse_filters(&self) -> Result<Vec<PropertyFilter>, FlagError> {
        let wrapper: serde_json::Value = serde_json::from_value(self.filters.clone())?;
        let cohort_property: InnerCohortProperty =
            serde_json::from_value(wrapper["properties"].clone())?;
        Ok(cohort_property.to_property_filters())
    }
}

impl InnerCohortProperty {
    pub fn to_property_filters(&self) -> Vec<PropertyFilter> {
        self.values
            .iter()
            .flat_map(|value| &value.values)
            .cloned()
            .collect()
    }
}

/// Sorts the given cohorts in an order where cohorts with no dependencies are placed first,
/// followed by cohorts that depend on the preceding ones. It ensures that each cohort in the sorted list
/// only depends on cohorts that appear earlier in the list.
pub fn sort_cohorts_topologically(
    cohort_ids: HashSet<CohortId>,
    seen_cohorts_cache: &HashMap<CohortId, CohortOrEmpty>,
) -> Vec<CohortId> {
    if cohort_ids.is_empty() {
        return Vec::new();
    }

    let mut dependency_graph: HashMap<CohortId, Vec<CohortId>> = HashMap::new();
    let mut seen = HashSet::new();

    // Build graph (adjacency list)
    fn traverse(
        cohort: &Cohort,
        dependency_graph: &mut HashMap<CohortId, Vec<CohortId>>,
        seen_cohorts: &mut HashSet<CohortId>,
        seen_cohorts_cache: &HashMap<CohortId, CohortOrEmpty>,
    ) {
        if seen_cohorts.contains(&cohort.id) {
            return;
        }
        seen_cohorts.insert(cohort.id);

        // Parse the filters into PropertyFilters
        let property_filters = match cohort.parse_filters() {
            Ok(filters) => filters,
            Err(e) => {
                tracing::error!("Error parsing filters for cohort {}: {}", cohort.id, e);
                return;
            }
        };

        // Iterate through the property filters to find dependencies
        for filter in property_filters {
            if filter.prop_type == "cohort" {
                let child_id = match filter.value {
                    serde_json::Value::Number(num) => num.as_i64().map(|n| n as CohortId),
                    serde_json::Value::String(ref s) => s.parse::<CohortId>().ok(),
                    _ => None,
                };

                if let Some(child_id) = child_id {
                    dependency_graph
                        .entry(cohort.id)
                        .or_default()
                        .push(child_id);

                    if let Some(CohortOrEmpty::Cohort(child_cohort)) =
                        seen_cohorts_cache.get(&child_id)
                    {
                        traverse(
                            child_cohort,
                            dependency_graph,
                            seen_cohorts,
                            seen_cohorts_cache,
                        );
                    }
                }
            }
        }
    }

    for &cohort_id in &cohort_ids {
        if let Some(CohortOrEmpty::Cohort(cohort)) = seen_cohorts_cache.get(&cohort_id) {
            traverse(cohort, &mut dependency_graph, &mut seen, seen_cohorts_cache);
        }
    }

    // Post-order DFS (children first, then the parent)
    fn dfs(
        node: CohortId,
        seen: &mut HashSet<CohortId>,
        sorted_arr: &mut Vec<CohortId>,
        dependency_graph: &HashMap<CohortId, Vec<CohortId>>,
    ) {
        if let Some(neighbors) = dependency_graph.get(&node) {
            for &neighbor in neighbors {
                if !seen.contains(&neighbor) {
                    dfs(neighbor, seen, sorted_arr, dependency_graph);
                }
            }
        }
        sorted_arr.push(node);
        seen.insert(node);
    }

    let mut sorted_cohort_ids = Vec::new();
    let mut seen = HashSet::new();
    for &cohort_id in &cohort_ids {
        if !seen.contains(&cohort_id) {
            seen.insert(cohort_id);
            dfs(
                cohort_id,
                &mut seen,
                &mut sorted_cohort_ids,
                &dependency_graph,
            );
        }
    }

    sorted_cohort_ids
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        cohorts::cohort_models::{CohortPropertyType, CohortValues},
        utils::test_utils::{
            insert_cohort_for_team_in_pg, insert_new_team_in_pg, setup_pg_reader_client,
            setup_pg_writer_client,
        },
    };
    use serde_json::json;

    #[test]
    fn test_cohort_parse_filters() {
        let cohort = Cohort {
            id: 1,
            name: "Test Cohort".to_string(),
            description: None,
            team_id: 1,
            deleted: false,
            filters: json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$initial_browser_version", "type": "person", "value": ["125"], "negation": false, "operator": "exact"}]}]}}),
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
        assert_eq!(result[0].value, json!(["125"]));
        assert_eq!(result[0].prop_type, "person");
    }

    #[test]
    fn test_sort_cohorts_topologically() {
        let mut cohorts = HashMap::new();
        cohorts.insert(
            1,
            CohortOrEmpty::Cohort(Cohort {
                id: 1,
                name: "Cohort 1".to_string(),
                description: None,
                team_id: 1,
                deleted: false,
                filters: json!({"properties": {"type": "AND", "values": []}}),
                query: None,
                version: None,
                pending_version: None,
                count: None,
                is_calculating: false,
                is_static: false,
                errors_calculating: 0,
                groups: json!({}),
                created_by_id: None,
            }),
        );
        cohorts.insert(2, CohortOrEmpty::Cohort(Cohort {
            id: 2,
            name: "Cohort 2".to_string(),
            description: None,
            team_id: 1,
            deleted: false,
            filters: json!({"properties": {"type": "AND", "values": [{"type": "property", "values": [{"key": "cohort", "value": 1, "type": "cohort"}]}]}}),
            query: None,
            version: None,
            pending_version: None,
            count: None,
            is_calculating: false,
            is_static: false,
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: None,
        }));
        cohorts.insert(3, CohortOrEmpty::Cohort(Cohort {
            id: 3,
            name: "Cohort 3".to_string(),
            description: None,
            team_id: 1,
            deleted: false,
            filters: json!({"properties": {"type": "AND", "values": [{"type": "property", "values": [{"key": "cohort", "value": 2, "type": "cohort"}]}]}}),
            query: None,
            version: None,
            pending_version: None,
            count: None,
            is_calculating: false,
            is_static: false,
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: None,
        }));

        let cohort_ids: HashSet<CohortId> = vec![1, 2, 3].into_iter().collect();
        let result = sort_cohorts_topologically(cohort_ids, &cohorts);
        assert_eq!(result, vec![1, 2, 3]);
    }

    #[test]
    fn test_cohort_property_to_property_filters() {
        let cohort_property = InnerCohortProperty {
            prop_type: CohortPropertyType::AND,
            values: vec![CohortValues {
                prop_type: "property".to_string(),
                values: vec![
                    PropertyFilter {
                        key: "email".to_string(),
                        value: json!("test@example.com"),
                        operator: None,
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    },
                    PropertyFilter {
                        key: "age".to_string(),
                        value: json!(25),
                        operator: None,
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    },
                ],
            }],
        };

        let result = cohort_property.to_property_filters();
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].key, "email");
        assert_eq!(result[0].value, json!("test@example.com"));
        assert_eq!(result[1].key, "age");
        assert_eq!(result[1].value, json!(25));
    }

    #[tokio::test]
    async fn test_cohort_list_from_pg() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;

        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .expect("Failed to insert team");

        // Insert first cohort
        let cohort1 = insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            Some("Test Cohort 1".to_string()),
            json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$initial_browser_version", "type": "person", "value": ["125"], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert cohort 1");

        // Insert second cohort
        let cohort2 = insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            Some("Test Cohort 2".to_string()),
            json!({"properties": {"type": "AND", "values": [{"type": "AND", "values": [{"key": "email", "type": "person", "value": ["test@example.com"], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert cohort 2");

        // Test case 1: List with multiple cohort IDs
        let fetched_cohorts =
            Cohort::list_from_pg(postgres_reader.clone(), &[cohort1.id, cohort2.id], team.id)
                .await
                .expect("Failed to fetch cohorts");

        assert_eq!(fetched_cohorts.len(), 2);
        assert_eq!(fetched_cohorts[0].id, cohort1.id);
        assert_eq!(fetched_cohorts[0].name, "Test Cohort 1");
        assert_eq!(fetched_cohorts[0].team_id, team.id);
        assert_eq!(fetched_cohorts[1].id, cohort2.id);
        assert_eq!(fetched_cohorts[1].name, "Test Cohort 2");
        assert_eq!(fetched_cohorts[1].team_id, team.id);

        // Test case 2: List with a single cohort ID
        let fetched_single_cohort = Cohort::list_from_pg(postgres_reader, &[cohort1.id], team.id)
            .await
            .expect("Failed to fetch single cohort");

        assert_eq!(fetched_single_cohort.len(), 1);
        assert_eq!(fetched_single_cohort[0].id, cohort1.id);
        assert_eq!(fetched_single_cohort[0].name, "Test Cohort 1");
        assert_eq!(fetched_single_cohort[0].team_id, team.id);
    }
}
