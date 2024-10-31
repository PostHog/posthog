use crate::api::FlagError;
use crate::cohort_models::{Cohort, CohortId};
use crate::flag_matching::PostgresReader;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;

/// CohortCache manages the in-memory cache of cohorts
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
    /// Creates a new CohortCache instance
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
    async fn fetch_and_cache_all_cohorts(
        &self,
        team_id: i32,
        postgres_reader: PostgresReader,
    ) -> Result<(), FlagError> {
        // Fetch all cohorts for the team
        let cohorts = Cohort::list_from_pg(postgres_reader, team_id).await?;

        // Cache the cohorts without flattening
        let mut cache = self.per_team_cohorts.write().await;
        cache.insert(team_id, cohorts);

        Ok(())
    }

    /// Retrieves all cohorts for a given team
    pub async fn get_all_cohorts(&self, team_id: i32) -> Result<Vec<Cohort>, FlagError> {
        let cache = self.per_team_cohorts.read().await;
        cache
            .get(&team_id)
            .cloned()
            .ok_or_else(|| FlagError::CohortNotFound("No cohorts found for the team".to_string()))
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
