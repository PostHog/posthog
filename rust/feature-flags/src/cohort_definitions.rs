use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use std::sync::Arc;
use tracing::instrument;

use crate::{
    api::FlagError,
    database::Client as DatabaseClient,
    flag_definitions::{OperatorType, PropertyFilter},
};

#[derive(Debug, FromRow)]
struct CohortRow {
    id: i32,
    name: String,
    description: Option<String>,
    team_id: i32,
    deleted: bool,
    filters: serde_json::Value,
    query: Option<serde_json::Value>,
    version: Option<i32>,
    pending_version: Option<i32>,
    count: Option<i32>,
    is_calculating: bool,
    is_static: bool,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
pub struct Cohort {
    pub id: i32,
    pub name: String,
    pub description: Option<String>,
    pub team_id: i32,
    pub deleted: bool,
    pub filters: serde_json::Value,
    pub query: Option<serde_json::Value>,
    pub version: Option<i32>,
    pub pending_version: Option<i32>,
    pub count: Option<i32>,
    pub is_calculating: bool,
    pub is_static: bool,
}

impl Cohort {
    /// Returns a cohort from postgres given a cohort_id and team_id
    #[instrument(skip_all)]
    pub async fn from_pg(
        client: Arc<dyn DatabaseClient + Send + Sync>,
        cohort_id: i32,
        team_id: i32,
    ) -> Result<Cohort, FlagError> {
        let mut conn = client.get_connection().await.map_err(|e| {
            tracing::error!("Failed to get database connection: {}", e);
            // TODO should I model my errors more generally?  Like, yes, everything behind this API is technically a FlagError,
            // but I'm not sure if accessing Cohort definitions should be a FlagError (vs idk, a CohortError?  A more general API error?)
            FlagError::DatabaseUnavailable
        })?;

        let query = "SELECT id, name, description, team_id, deleted, filters, query, version, pending_version, count, is_calculating, is_static FROM posthog_cohort WHERE id = $1 AND team_id = $2";
        let cohort_row = sqlx::query_as::<_, CohortRow>(query)
            .bind(cohort_id)
            .bind(team_id)
            .fetch_optional(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!("Failed to fetch cohort from database: {}", e);
                FlagError::Internal(format!("Database query error: {}", e))
            })?;

        match cohort_row {
            Some(row) => Ok(Cohort {
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
            }),
            None => Err(FlagError::DatabaseError(format!(
                "Cohort with id {} not found for team {}",
                cohort_id, team_id
            ))),
        }
    }

    /// Parses the filters JSON into a CohortProperty structure
    fn parse_filters(&self) -> Result<CohortProperty, FlagError> {
        serde_json::from_value(self.filters.clone()).map_err(|e| {
            tracing::error!("Failed to parse filters: {}", e);
            FlagError::Internal(format!("Invalid filters format: {}", e))
        })
    }
}

use std::collections::{HashMap, HashSet};

type CohortId = i32;

// Assuming CohortOrEmpty is an enum or struct representing a Cohort or an empty value
enum CohortOrEmpty {
    Cohort(Cohort),
    Empty,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "UPPERCASE")]
enum CohortPropertyType {
    AND,
    OR,
}

// TODO this should serialize to "properties" in the DB
#[derive(Debug, Clone, Deserialize, Serialize)]
struct CohortProperty {
    #[serde(rename = "type")]
    prop_type: CohortPropertyType, // TODO make this an AND|OR string enum
    values: Vec<CohortValues>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
struct CohortValues {
    #[serde(rename = "type")]
    prop_type: String,
    values: Vec<PropertyFilter>,
}

fn sort_cohorts_topologically(
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

        // Parse the filters into CohortProperty
        let cohort_property = match cohort.parse_filters() {
            Ok(property) => property,
            Err(e) => {
                tracing::error!("Error parsing filters for cohort {}: {}", cohort.id, e);
                return;
            }
        };

        // Iterate through the properties to find dependencies
        for value in &cohort_property.values {
            if value.prop_type == "cohort" {
                if let Some(id) = value.value.as_i64() {
                    let child_id = id as CohortId;
                    dependency_graph
                        .entry(cohort.id)
                        .or_insert_with(Vec::new)
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
                } else if let Some(id_str) = value.value.as_str() {
                    if let Ok(child_id) = id_str.parse::<CohortId>() {
                        dependency_graph
                            .entry(cohort.id)
                            .or_insert_with(Vec::new)
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

            // Handle nested properties recursively if needed
            if let Some(nested_values) = &value.values {
                for nested in nested_values {
                    if nested.prop_type == "cohort" {
                        if let Some(id) = nested.value.as_i64() {
                            let child_id = id as CohortId;
                            dependency_graph
                                .entry(cohort.id)
                                .or_insert_with(Vec::new)
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
