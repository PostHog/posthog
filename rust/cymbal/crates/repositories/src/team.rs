use std::time::Duration;

use common_types::{GroupType, Team, TeamId};
use moka::sync::{Cache, CacheBuilder};

const ANCILLARY_CACHE: &str = "cymbal_ancillary_cache";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TeamRepositoryConfig {
    pub max_team_cache_size: u64,
    pub team_cache_ttl_secs: u64,
}

#[derive(Clone)]
pub struct CachedTeamRepository {
    pub token_cache: Cache<String, Option<Team>>,
    pub group_type_indices: Cache<TeamId, Vec<GroupType>>,
}

impl CachedTeamRepository {
    pub fn new(config: &TeamRepositoryConfig) -> Self {
        let token_cache = CacheBuilder::new(config.max_team_cache_size)
            .time_to_live(Duration::from_secs(config.team_cache_ttl_secs))
            .build();

        let group_type_indices = CacheBuilder::new(config.max_team_cache_size)
            .time_to_live(Duration::from_secs(config.team_cache_ttl_secs))
            .build();

        Self {
            token_cache,
            group_type_indices,
        }
    }

    pub async fn get_team<'c, E>(
        &self,
        executor: E,
        api_token: &str,
    ) -> Result<Option<Team>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        match self.token_cache.get(api_token) {
            // We cache "no team" results too, so we don't have to query the database again.
            Some(maybe_team) => {
                metrics::counter!(ANCILLARY_CACHE, "type" => "team", "outcome" => "hit")
                    .increment(1);
                Ok(maybe_team)
            }
            None => {
                metrics::counter!(ANCILLARY_CACHE, "type" => "team", "outcome" => "miss")
                    .increment(1);
                let team = Team::load_by_token(executor, api_token).await?;
                self.token_cache.insert(api_token.to_string(), team.clone());
                Ok(team)
            }
        }
    }

    pub async fn get_group_types<'c, E>(
        &self,
        executor: E,
        team_id: TeamId,
    ) -> Result<Vec<GroupType>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        if let Some(indices) = self.group_type_indices.get(&team_id) {
            metrics::counter!(ANCILLARY_CACHE, "type" => "group_type_indices", "outcome" => "hit")
                .increment(1);
            return Ok(indices.clone());
        }
        metrics::counter!(ANCILLARY_CACHE, "type" => "group_type_indices", "outcome" => "miss")
            .increment(1);
        // If we have no indices for the team, we just put an empty vector in the cache.
        let indices = GroupType::for_team(executor, team_id).await?;
        self.group_type_indices.insert(team_id, indices.clone());
        Ok(indices)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cached_team_repository_starts_empty() {
        let repository = CachedTeamRepository::new(&TeamRepositoryConfig {
            max_team_cache_size: 10,
            team_cache_ttl_secs: 60,
        });

        assert!(repository.token_cache.get("missing").is_none());
        assert!(repository.group_type_indices.get(&1).is_none());
    }
}
