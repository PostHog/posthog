use crate::api::FlagError;
use crate::cohort_models::{Cohort, CohortId, CohortProperty};
use crate::flag_definitions::PropertyFilter;
use crate::flag_matching::PostgresReader;
use petgraph::algo::toposort;
use petgraph::graphmap::DiGraphMap;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tokio::sync::RwLock;

// Flattened Cohort Map: CohortId -> Combined PropertyFilters
pub type FlattenedCohortMap = HashMap<CohortId, Vec<PropertyFilter>>;

/// CohortCache manages the in-memory cache of flattened cohorts
#[derive(Clone)]
pub struct CohortCache {
    pub per_team_flattened: Arc<RwLock<HashMap<i32, FlattenedCohortMap>>>, // team_id -> (cohort_id -> filters)
}

impl CohortCache {
    /// Creates a new CohortCache instance
    pub fn new() -> Self {
        Self {
            per_team_flattened: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Asynchronous constructor that initializes the CohortCache by fetching and caching cohorts for the given team_id
    pub async fn new_with_team(
        team_id: i32,
        postgres_reader: PostgresReader,
    ) -> Result<Self, FlagError> {
        let cache = Self {
            per_team_flattened: Arc::new(RwLock::new(HashMap::new())),
        };
        cache
            .fetch_and_cache_all_cohorts(team_id, postgres_reader)
            .await?;
        Ok(cache)
    }

    /// Fetches, parses, and caches all cohorts for a given team
    async fn fetch_and_cache_all_cohorts(
        &self,
        team_id: i32,
        postgres_reader: PostgresReader,
    ) -> Result<(), FlagError> {
        // Fetch all cohorts for the team
        let cohorts = Cohort::list_from_pg(postgres_reader, team_id).await?;

        // Build a mapping from cohort_id to Cohort
        let mut cohort_map: HashMap<CohortId, Cohort> = HashMap::new();
        for cohort in cohorts {
            cohort_map.insert(cohort.id, cohort);
        }

        // Build dependency graph
        let dependency_graph = Self::build_dependency_graph(&cohort_map)?;

        // Perform topological sort
        let sorted_cohorts = toposort(&dependency_graph, None).map_err(|_| {
            FlagError::CohortDependencyCycle("Cycle detected in cohort dependencies".to_string())
        })?;

        // Reverse to process dependencies first
        let sorted_cohorts: Vec<CohortId> = sorted_cohorts.into_iter().rev().collect();

        // Flatten cohorts
        let flattened = Self::flatten_cohorts(&sorted_cohorts, &cohort_map)?;

        // Cache the flattened cohort filters
        let mut cache = self.per_team_flattened.write().await;
        cache.insert(team_id, flattened);

        Ok(())
    }

    /// Retrieves flattened filters for a given team and cohort
    pub async fn get_flattened_filters(
        &self,
        team_id: i32,
        cohort_id: CohortId,
    ) -> Result<Vec<PropertyFilter>, FlagError> {
        let cache = self.per_team_flattened.read().await;
        if let Some(team_map) = cache.get(&team_id) {
            if let Some(filters) = team_map.get(&cohort_id) {
                Ok(filters.clone())
            } else {
                Err(FlagError::CohortNotFound(cohort_id.to_string()))
            }
        } else {
            Err(FlagError::CohortNotFound(cohort_id.to_string()))
        }
    }

    /// Builds a dependency graph where an edge from A to B means A depends on B
    fn build_dependency_graph(
        cohort_map: &HashMap<CohortId, Cohort>,
    ) -> Result<DiGraphMap<CohortId, ()>, FlagError> {
        let mut graph = DiGraphMap::new();

        // Add all cohorts as nodes
        for &cohort_id in cohort_map.keys() {
            graph.add_node(cohort_id);
        }

        // Add edges based on dependencies
        for (&cohort_id, cohort) in cohort_map.iter() {
            let dependencies = Self::extract_dependencies(cohort.filters.clone())?;
            for dep_id in dependencies {
                if !cohort_map.contains_key(&dep_id) {
                    return Err(FlagError::CohortNotFound(dep_id.to_string()));
                }
                graph.add_edge(cohort_id, dep_id, ()); // A depends on B: A -> B
            }
        }

        Ok(graph)
    }

    /// Extracts all dependent CohortIds from the filters
    fn extract_dependencies(
        filters_as_json: serde_json::Value,
    ) -> Result<HashSet<CohortId>, FlagError> {
        let filters: CohortProperty = serde_json::from_value(filters_as_json)?;
        let mut dependencies = HashSet::new();
        Self::traverse_filters(&filters.properties, &mut dependencies)?;
        Ok(dependencies)
    }

    /// Recursively traverses the filter tree to find cohort dependencies
    fn traverse_filters(
        inner: &crate::cohort_models::InnerCohortProperty,
        dependencies: &mut HashSet<CohortId>,
    ) -> Result<(), FlagError> {
        for cohort_values in &inner.values {
            for filter in &cohort_values.values {
                if filter.prop_type == "cohort" && filter.key == "id" {
                    // Assuming the value is a single integer CohortId
                    if let Some(cohort_id) = filter.value.as_i64() {
                        dependencies.insert(cohort_id as CohortId);
                    } else {
                        return Err(FlagError::CohortFiltersParsingError); // TODO more data here?
                    }
                }
                // Handle nested properties if necessary
                // If the filter can contain nested properties with more conditions, traverse them here
            }
        }
        Ok(())
    }

    /// Flattens the filters based on sorted cohorts, including only property filters
    fn flatten_cohorts(
        sorted_cohorts: &[CohortId],
        cohort_map: &HashMap<CohortId, Cohort>,
    ) -> Result<FlattenedCohortMap, FlagError> {
        let mut flattened: FlattenedCohortMap = HashMap::new();

        for &cohort_id in sorted_cohorts {
            let cohort = cohort_map
                .get(&cohort_id)
                .ok_or(FlagError::CohortNotFound(cohort_id.to_string()))?;

            // Use the updated parse_property_filters method
            let property_filters = cohort.parse_filters()?;

            // Extract dependencies using Cohort's method
            let dependencies = cohort.extract_dependencies()?;

            let mut combined_filters = Vec::new();

            // Include filters from dependencies
            for dep_id in &dependencies {
                if let Some(dep_filters) = flattened.get(dep_id) {
                    combined_filters.extend(dep_filters.clone());
                } else {
                    return Err(FlagError::CohortNotFound(dep_id.to_string()));
                }
            }

            // Include own filters
            combined_filters.extend(property_filters);

            // Insert into flattened map
            flattened.insert(cohort_id, combined_filters);
        }

        Ok(flattened)
    }
}
