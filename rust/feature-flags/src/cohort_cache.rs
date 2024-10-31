use crate::api::FlagError;
use crate::cohort_models::{Cohort, CohortId};
use crate::flag_matching::PostgresReader;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;

/// CohortCache manages the in-memory cache of cohorts
///
/// Example cache structure:
/// ```text
/// per_team_cohorts: {
///   1: [
///     Cohort { id: 101, name: "Active Users", filters: [...] },
///     Cohort { id: 102, name: "Power Users", filters: [...] }
///   ],
///   2: [
///     Cohort { id: 201, name: "New Users", filters: [...] },
///     Cohort { id: 202, name: "Churned Users", filters: [...] }
///   ]
/// }
/// ```
#[derive(Clone)]
pub struct CohortCache {
    pub per_team_cohorts: Arc<RwLock<HashMap<i32, Vec<Cohort>>>>, // team_id -> list of Cohorts
}

impl Default for CohortCache {
    fn default() -> Self {
        Self::new()
    }
}

impl CohortCache {
    pub fn new() -> Self {
        Self {
            per_team_cohorts: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Asynchronous constructor that initializes the CohortCache by fetching and caching cohorts for the given team_id
    pub async fn new_with_team(
        team_id: i32,
        postgres_reader: PostgresReader,
    ) -> Result<Self, FlagError> {
        let cache = Self {
            per_team_cohorts: Arc::new(RwLock::new(HashMap::new())),
        };
        cache
            .fetch_and_cache_all_cohorts(team_id, postgres_reader)
            .await?;
        Ok(cache)
    }

    /// Fetches and caches all cohorts for a given team
    ///
    /// Cache structure:
    /// ```text
    /// per_team_cohorts: {
    ///   team_id_1: [
    ///     Cohort { id: 1, filters: [...], ... },
    ///     Cohort { id: 2, filters: [...], ... },
    ///     ...
    ///   ],
    ///   team_id_2: [
    ///     Cohort { id: 3, filters: [...], ... },
    ///     ...
    ///   ]
    /// }
    /// ```
    async fn fetch_and_cache_all_cohorts(
        &self,
        team_id: i32,
        postgres_reader: PostgresReader,
    ) -> Result<(), FlagError> {
        let cohorts = Cohort::list_from_pg(postgres_reader, team_id).await?;
        let mut cache = self.per_team_cohorts.write().await;
        cache.insert(team_id, cohorts);

        Ok(())
    }

    /// Retrieves a specific cohort by ID for a given team
    pub async fn get_cohort_by_id(
        &self,
        team_id: i32,
        cohort_id: CohortId,
    ) -> Result<Cohort, FlagError> {
        let cache = self.per_team_cohorts.read().await;
        if let Some(cohorts) = cache.get(&team_id) {
            if let Some(cohort) = cohorts.iter().find(|c| c.id == cohort_id) {
                return Ok(cohort.clone());
            }
        }
        Err(FlagError::CohortNotFound(cohort_id.to_string()))
    }
}
