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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_utils::{
        insert_cohort_for_team_in_pg, insert_new_team_in_pg, setup_pg_reader_client,
        setup_pg_writer_client,
    };
    use serde_json::json;
    use std::collections::HashSet;

    #[tokio::test]
    async fn test_default_cache_is_empty() {
        let cache = CohortCache::default();
        let cache_guard = cache.per_team_cohorts.read().await;
        assert!(cache_guard.is_empty(), "Default cache should be empty");
    }

    #[tokio::test]
    async fn test_new_with_team_initializes_cache() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;

        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .expect("Failed to insert team");

        // Insert cohorts for the team
        insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            Some("Active Users".to_string()),
            json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$active", "type": "person", "value": [true], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert Active Users cohort");

        insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            Some("Power Users".to_string()),
            json!({"properties": {"type": "AND", "values": [{"type": "property", "values": [{"key": "usage", "type": "person", "value": [100], "negation": false, "operator": "gt"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert Power Users cohort");

        // Initialize the cache with the team
        let cache = CohortCache::new_with_team(team.id, postgres_reader.clone())
            .await
            .expect("Failed to initialize CohortCache with team");

        let cache_guard = cache.per_team_cohorts.read().await;
        assert!(
            cache_guard.contains_key(&team.id),
            "Cache should contain the team_id"
        );

        let cohorts = cache_guard.get(&team.id).unwrap();
        assert_eq!(cohorts.len(), 2, "There should be 2 cohorts for the team");
        let cohort_names: HashSet<String> = cohorts.iter().map(|c| c.name.clone()).collect();
        assert!(
            cohort_names.contains("Active Users"),
            "Cache should contain 'Active Users' cohort"
        );
        assert!(
            cohort_names.contains("Power Users"),
            "Cache should contain 'Power Users' cohort"
        );
    }

    #[tokio::test]
    async fn test_get_cohort_by_id_success() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;

        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .expect("Failed to insert team");

        let cohort = insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            Some("Active Users".to_string()),
            json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$active", "type": "person", "value": [true], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert Active Users cohort");

        let cache = CohortCache::new_with_team(team.id, postgres_reader.clone())
            .await
            .expect("Failed to initialize CohortCache with team");

        let fetched_cohort = cache
            .get_cohort_by_id(team.id, cohort.id)
            .await
            .expect("Failed to retrieve cohort by ID");

        assert_eq!(
            fetched_cohort.id, cohort.id,
            "Fetched cohort ID should match"
        );
        assert_eq!(
            fetched_cohort.name, "Active Users",
            "Fetched cohort name should match"
        );
    }

    #[tokio::test]
    async fn test_get_cohort_by_id_not_found() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;

        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .expect("Failed to insert team");

        // Insert a cohort to ensure the team has at least one cohort
        insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            Some("Active Users".to_string()),
            json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$active", "type": "person", "value": [true], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert Active Users cohort");

        let cache = CohortCache::new_with_team(team.id, postgres_reader.clone())
            .await
            .expect("Failed to initialize CohortCache with team");

        let non_existent_cohort_id = 9999;
        let result = cache
            .get_cohort_by_id(team.id, non_existent_cohort_id)
            .await;

        assert!(
            matches!(result, Err(FlagError::CohortNotFound(_))),
            "Should return CohortNotFound error for non-existent cohort ID"
        );
    }

    #[tokio::test]
    async fn test_fetch_and_cache_all_cohorts() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;

        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .expect("Failed to insert team");

        // Insert multiple cohorts for the team
        insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            Some("Active Users".to_string()),
            json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$active", "type": "person", "value": [true], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert Active Users cohort");

        insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            Some("Power Users".to_string()),
            json!({"properties": {"type": "AND", "values": [{"type": "property", "values": [{"key": "usage", "type": "person", "value": [100], "negation": false, "operator": "gt"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert Power Users cohort");

        let cache = CohortCache::new();

        // Fetch and cache all cohorts for the team
        cache
            .fetch_and_cache_all_cohorts(team.id, postgres_reader.clone())
            .await
            .expect("Failed to fetch and cache all cohorts");

        let cache_guard = cache.per_team_cohorts.read().await;
        assert!(
            cache_guard.contains_key(&team.id),
            "Cache should contain the team_id"
        );

        let cohorts = cache_guard.get(&team.id).unwrap();
        assert_eq!(
            cohorts.len(),
            2,
            "There should be 2 cohorts cached for the team"
        );

        let cohort_names: HashSet<String> = cohorts.iter().map(|c| c.name.clone()).collect();
        assert!(
            cohort_names.contains("Active Users"),
            "Cache should contain 'Active Users' cohort"
        );
        assert!(
            cohort_names.contains("Power Users"),
            "Cache should contain 'Power Users' cohort"
        );
    }

    #[tokio::test]
    async fn test_cache_updates_on_new_cohort() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;

        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .expect("Failed to insert team");

        // Initialize the cache
        let cache = CohortCache::new();

        // Fetch and cache all cohorts for the team (initially, there should be none)
        cache
            .fetch_and_cache_all_cohorts(team.id, postgres_reader.clone())
            .await
            .expect("Failed to fetch and cache cohorts");

        // Assert that the cache now contains the team_id with an empty vector
        {
            let cache_guard = cache.per_team_cohorts.read().await;
            assert!(
                cache_guard.contains_key(&team.id),
                "Cache should contain the team_id after initial fetch"
            );
            let cohorts = cache_guard.get(&team.id).unwrap();
            assert!(
                cohorts.is_empty(),
                "Cache for team_id should be empty initially"
            );
        }

        // Insert a new cohort for the team
        insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            Some("New Cohort".to_string()),
            json!({
                "properties": {
                    "type": "AND",
                    "values": [{
                        "type": "property",
                        "values": [{
                            "key": "subscription",
                            "type": "person",
                            "value": ["premium"],
                            "negation": false,
                            "operator": "exact"
                        }]
                    }]
                }
            }),
            false,
        )
        .await
        .expect("Failed to insert New Cohort");

        // Update the cache by fetching again after inserting the new cohort
        cache
            .fetch_and_cache_all_cohorts(team.id, postgres_reader.clone())
            .await
            .expect("Failed to update cache with new cohort");

        // Verify the cache has been updated with the new cohort
        {
            let cache_guard = cache.per_team_cohorts.read().await;
            assert!(
                cache_guard.contains_key(&team.id),
                "Cache should contain the team_id after update"
            );

            let cohorts = cache_guard.get(&team.id).unwrap();
            assert_eq!(
                cohorts.len(),
                1,
                "There should be 1 cohort cached for the team after update"
            );
            assert_eq!(
                cohorts[0].name, "New Cohort",
                "Cached cohort should be 'New Cohort'"
            );
        }
    }

    #[tokio::test]
    async fn test_cache_handles_multiple_teams() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;

        // Insert two teams
        let team1 = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .expect("Failed to insert team1");
        let team2 = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .expect("Failed to insert team2");

        // Insert cohorts for team1
        insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team1.id,
            Some("Team1 Cohort1".to_string()),
            json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "feature_x", "type": "feature", "value": [true], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert Team1 Cohort1");

        insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team1.id,
            Some("Team1 Cohort2".to_string()),
            json!({"properties": {"type": "AND", "values": [{"type": "property", "values": [{"key": "usage", "type": "feature", "value": [50], "negation": false, "operator": "gt"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert Team1 Cohort2");

        // Insert cohorts for team2
        insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team2.id,
            Some("Team2 Cohort1".to_string()),
            json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "region", "type": "geo", "value": ["NA"], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert Team2 Cohort1");

        // Initialize and cache cohorts for both teams
        let cache = CohortCache::new();

        cache
            .fetch_and_cache_all_cohorts(team1.id, postgres_reader.clone())
            .await
            .expect("Failed to cache team1 cohorts");

        cache
            .fetch_and_cache_all_cohorts(team2.id, postgres_reader.clone())
            .await
            .expect("Failed to cache team2 cohorts");

        // Verify team1's cache
        {
            let cache_guard = cache.per_team_cohorts.read().await;
            assert!(
                cache_guard.contains_key(&team1.id),
                "Cache should contain team1"
            );
            let team1_cohorts = cache_guard.get(&team1.id).unwrap();
            let team1_names: HashSet<String> =
                team1_cohorts.iter().map(|c| c.name.clone()).collect();
            assert!(
                team1_names.contains("Team1 Cohort1"),
                "Cache should contain 'Team1 Cohort1'"
            );
            assert!(
                team1_names.contains("Team1 Cohort2"),
                "Cache should contain 'Team1 Cohort2'"
            );
        }

        // Verify team2's cache
        {
            let cache_guard = cache.per_team_cohorts.read().await;
            assert!(
                cache_guard.contains_key(&team2.id),
                "Cache should contain team2"
            );
            let team2_cohorts = cache_guard.get(&team2.id).unwrap();
            let team2_names: HashSet<String> =
                team2_cohorts.iter().map(|c| c.name.clone()).collect();
            assert!(
                team2_names.contains("Team2 Cohort1"),
                "Cache should contain 'Team2 Cohort1'"
            );
        }
    }
}
