use crate::api::FlagError;
use crate::cohort_models::{Cohort, CohortId};
use crate::cohort_operations::sort_cohorts_topologically;
use crate::flag_definitions::{OperatorType, PropertyFilter};
use crate::flag_matching::{PostgresReader, TeamId};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tokio::sync::RwLock;

pub type TeamCohortMap = HashMap<CohortId, Vec<PropertyFilter>>;
pub type TeamSortedCohorts = HashMap<TeamId, Vec<CohortId>>;
pub type TeamCacheMap = HashMap<TeamId, TeamCohortMap>;

#[derive(Debug, Clone)]
pub struct CachedCohort {
    // TODO name this something different
    pub filters: Vec<PropertyFilter>, // Non-cohort property filters
    pub dependencies: Vec<CohortDependencyFilter>, // Dependencies with operators
}

// Add this struct to facilitate handling operators on cohort filters
#[derive(Debug, Clone)]
pub struct CohortDependencyFilter {
    pub cohort_id: CohortId,
    pub operator: OperatorType,
}

/// Threadsafety is ensured using Arc and RwLock
#[derive(Clone, Debug)]
pub struct CohortCache {
    /// Mapping from TeamId to their respective CohortId and associated CachedCohort
    per_team: Arc<RwLock<HashMap<TeamId, HashMap<CohortId, CachedCohort>>>>,
    /// Mapping from TeamId to sorted CohortIds based on dependencies
    sorted_cohorts: Arc<RwLock<HashMap<TeamId, Vec<CohortId>>>>,
}

impl CohortCache {
    /// Creates a new CohortCache instance
    pub fn new() -> Self {
        Self {
            per_team: Arc::new(RwLock::new(HashMap::new())),
            sorted_cohorts: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Fetches, flattens, sorts, and caches all cohorts for a given team if not already cached
    pub async fn fetch_and_cache_cohorts(
        &self,
        team_id: TeamId,
        postgres_reader: PostgresReader,
    ) -> Result<(), FlagError> {
        // Acquire write locks to modify the cache
        let mut cache = self.per_team.write().await;
        let mut sorted = self.sorted_cohorts.write().await;

        // Check if the team's cohorts are already cached
        if cache.contains_key(&team_id) && sorted.contains_key(&team_id) {
            return Ok(());
        }

        // Fetch all cohorts for the team from the database
        let all_cohorts = fetch_all_cohorts(team_id, postgres_reader).await?;

        // Flatten the property filters, resolving dependencies
        let flattened = flatten_cohorts(&all_cohorts).await?;

        // Extract all cohort IDs
        let cohort_ids: HashSet<CohortId> = flattened.keys().cloned().collect();

        // Sort the cohorts topologically based on dependencies
        let sorted_ids = sort_cohorts_topologically(cohort_ids, &flattened)?;

        // Insert the flattened cohorts and their sorted order into the cache
        cache.insert(team_id, flattened);
        sorted.insert(team_id, sorted_ids);

        Ok(())
    }

    /// Retrieves sorted cohort IDs for a team from the cache
    pub async fn get_sorted_cohort_ids(
        &self,
        team_id: TeamId,
        postgres_reader: PostgresReader,
    ) -> Result<Vec<CohortId>, FlagError> {
        {
            // Acquire read locks to check the cache
            let cache = self.per_team.read().await;
            let sorted = self.sorted_cohorts.read().await;
            if let (Some(_cohort_map), Some(sorted_ids)) =
                (cache.get(&team_id), sorted.get(&team_id))
            {
                if !sorted_ids.is_empty() {
                    return Ok(sorted_ids.clone());
                }
            }
        }

        // If not cached, fetch and cache the cohorts
        self.fetch_and_cache_cohorts(team_id, postgres_reader)
            .await?;

        // Acquire read locks to retrieve the sorted list after caching
        let sorted = self.sorted_cohorts.read().await;
        if let Some(sorted_ids) = sorted.get(&team_id) {
            Ok(sorted_ids.clone())
        } else {
            Ok(Vec::new())
        }
    }

    /// Retrieves cached cohorts for a team
    pub async fn get_cached_cohorts(
        &self,
        team_id: TeamId,
    ) -> Result<HashMap<CohortId, CachedCohort>, FlagError> {
        let cache = self.per_team.read().await;
        if let Some(cohort_map) = cache.get(&team_id) {
            Ok(cohort_map.clone())
        } else {
            Ok(HashMap::new())
        }
    }
}

async fn fetch_all_cohorts(
    team_id: TeamId,
    postgres_reader: PostgresReader,
) -> Result<Vec<Cohort>, FlagError> {
    let mut conn = postgres_reader.get_connection().await?;

    let query = r#"
        SELECT *
        FROM posthog_cohort
        WHERE team_id = $1 AND deleted = FALSE
    "#;

    let cohorts: Vec<Cohort> = sqlx::query_as::<_, Cohort>(query)
        .bind(team_id)
        .fetch_all(&mut *conn)
        .await
        .map_err(|e| FlagError::DatabaseError(e.to_string()))?;

    Ok(cohorts)
}

async fn flatten_cohorts(
    all_cohorts: &Vec<Cohort>,
) -> Result<HashMap<CohortId, CachedCohort>, FlagError> {
    let mut flattened = HashMap::new();

    for cohort in all_cohorts {
        let filters = cohort.parse_filters()?;

        // Extract dependencies from cohort filters
        let dependencies = filters
            .iter()
            .filter_map(|f| {
                if f.prop_type == "cohort" {
                    Some(CohortDependencyFilter {
                        cohort_id: f.value.as_i64().unwrap() as CohortId,
                        operator: f.operator.clone().unwrap_or(OperatorType::In),
                    })
                } else {
                    None
                }
            })
            .collect();

        // Filter out cohort filters as they are now represented as dependencies
        let non_cohort_filters: Vec<PropertyFilter> = filters
            .into_iter()
            .filter(|f| f.prop_type != "cohort")
            .collect();
        let cached_cohort = CachedCohort {
            filters: non_cohort_filters,
            dependencies,
        };

        flattened.insert(cohort.id, cached_cohort);
    }

    Ok(flattened)
}
