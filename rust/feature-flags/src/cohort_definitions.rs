use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::Arc;
use tracing::instrument;

use crate::{api::FlagError, database::Client as DatabaseClient, flag_definitions::PropertyFilter};

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

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
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
    pub fn parse_filters(&self) -> Result<Vec<PropertyFilter>, FlagError> {
        let cohort_property: CohortProperty = serde_json::from_value(self.filters.clone())?;
        Ok(cohort_property.to_property_filters())
    }
}

type CohortId = i32;

// Assuming CohortOrEmpty is an enum or struct representing a Cohort or an empty value
pub enum CohortOrEmpty {
    Cohort(Cohort),
    Empty,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "UPPERCASE")]
pub enum CohortPropertyType {
    AND,
    OR,
}

// TODO this should serialize to "properties" in the DB
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CohortProperty {
    #[serde(rename = "type")]
    prop_type: CohortPropertyType, // TODO make this an AND|OR string enum
    values: Vec<CohortValues>,
}

impl CohortProperty {
    pub fn to_property_filters(&self) -> Vec<PropertyFilter> {
        self.values
            .iter()
            .flat_map(|value| &value.values)
            .cloned()
            .collect()
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CohortValues {
    #[serde(rename = "type")]
    prop_type: String,
    values: Vec<PropertyFilter>,
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

pub async fn get_dependent_cohorts(
    cohort: &Cohort,
    seen_cohorts_cache: &mut HashMap<CohortId, CohortOrEmpty>,
    team_id: i32,
    db_client: Arc<dyn DatabaseClient + Send + Sync>,
) -> Result<Vec<Cohort>, FlagError> {
    let mut dependent_cohorts = Vec::new();
    let mut seen_cohort_ids = HashSet::new();
    seen_cohort_ids.insert(cohort.id);

    let mut queue = VecDeque::new();

    let property_filters = match cohort.parse_filters() {
        Ok(filters) => filters,
        Err(e) => {
            tracing::error!("Failed to parse filters for cohort {}: {}", cohort.id, e);
            return Err(FlagError::Internal(format!(
                "Failed to parse cohort filters: {}",
                e
            )));
        }
    };

    // Initial queue population
    for filter in &property_filters {
        if filter.prop_type == "cohort" {
            if let Some(id) = filter.value.as_i64().map(|n| n as CohortId).or_else(|| {
                filter
                    .value
                    .as_str()
                    .and_then(|s| s.parse::<CohortId>().ok())
            }) {
                queue.push_back(id);
            }
        }
    }

    while let Some(cohort_id) = queue.pop_front() {
        let current_cohort = match seen_cohorts_cache.get(&cohort_id) {
            Some(CohortOrEmpty::Cohort(c)) => c.clone(),
            Some(CohortOrEmpty::Empty) => continue,
            None => {
                // Fetch the cohort from the database
                match Cohort::from_pg(db_client.clone(), cohort_id, team_id).await {
                    Ok(c) => {
                        seen_cohorts_cache.insert(cohort_id, CohortOrEmpty::Cohort(c.clone()));
                        c
                    }
                    Err(e) => {
                        tracing::warn!("Failed to fetch cohort {}: {}", cohort_id, e);
                        seen_cohorts_cache.insert(cohort_id, CohortOrEmpty::Empty);
                        continue;
                    }
                }
            }
        };

        if !seen_cohort_ids.contains(&current_cohort.id) {
            dependent_cohorts.push(current_cohort.clone());
            seen_cohort_ids.insert(current_cohort.id);

            // Parse filters for the current cohort
            if let Ok(current_filters) = current_cohort.parse_filters() {
                // Add new cohort dependencies to the queue
                for filter in current_filters {
                    if filter.prop_type == "cohort" {
                        if let Some(id) =
                            filter.value.as_i64().map(|n| n as CohortId).or_else(|| {
                                filter
                                    .value
                                    .as_str()
                                    .and_then(|s| s.parse::<CohortId>().ok())
                            })
                        {
                            queue.push_back(id);
                        }
                    }
                }
            }
        }
    }

    Ok(dependent_cohorts)
}
