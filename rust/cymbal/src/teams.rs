use std::{collections::HashMap, sync::Arc, time::Duration};

use common_types::{GroupType, Team, TeamId};
use moka::sync::{Cache, CacheBuilder};
use tracing::warn;

use crate::{
    app_context::AppContext,
    assignment_rules::AssignmentRule,
    config::Config,
    error::{PipelineFailure, UnhandledError},
    fingerprinting::grouping_rules::GroupingRule,
    metric_consts::ANCILLARY_CACHE,
    pipeline::IncomingEvent,
    sanitize_string,
    spike_config::SpikeDetectionConfig,
    suppression_rules::SuppressionRule,
    WithIndices,
};

#[derive(Clone)]
pub struct TeamManager {
    pub token_cache: Cache<String, Option<Team>>,
    pub assignment_rules: Cache<TeamId, Vec<AssignmentRule>>,
    pub grouping_rules: Cache<TeamId, Vec<GroupingRule>>,
    pub suppression_rules: Cache<TeamId, Vec<SuppressionRule>>,
    pub group_type_indices: Cache<TeamId, Vec<GroupType>>,
    pub spike_detection_configs: Cache<TeamId, Option<SpikeDetectionConfig>>,
}

impl TeamManager {
    pub fn new(config: &Config) -> Self {
        let cache = CacheBuilder::new(config.max_team_cache_size)
            .time_to_live(Duration::from_secs(config.team_cache_ttl_secs))
            .build();

        let group_type_indices = CacheBuilder::new(config.max_team_cache_size)
            .time_to_live(Duration::from_secs(config.team_cache_ttl_secs))
            .build();

        let assignment_rules = CacheBuilder::new(config.max_assignment_rule_cache_size)
            .time_to_live(Duration::from_secs(config.assignment_rule_cache_ttl_secs))
            .weigher(|_, v: &Vec<AssignmentRule>| {
                v.iter()
                    .map(|rule| rule.bytecode.as_array().map_or(0, Vec::len) as u32)
                    .sum()
            })
            .build();

        let grouping_rules = CacheBuilder::new(config.max_grouping_rule_cache_size)
            .time_to_live(Duration::from_secs(config.grouping_rule_cache_ttl_secs))
            .weigher(|_, v: &Vec<GroupingRule>| {
                v.iter()
                    .map(|rule| rule.bytecode.as_array().map_or(0, Vec::len) as u32)
                    .sum()
            })
            .build();

        let suppression_rules = CacheBuilder::new(config.max_suppression_rule_cache_size)
            .time_to_live(Duration::from_secs(config.suppression_rule_cache_ttl_secs))
            .weigher(|_, v: &Vec<SuppressionRule>| {
                v.iter()
                    .map(|rule| rule.bytecode.as_array().map_or(0, Vec::len) as u32)
                    .sum()
            })
            .build();

        let spike_detection_configs = CacheBuilder::new(config.max_team_cache_size)
            .time_to_live(Duration::from_secs(config.team_cache_ttl_secs))
            .build();

        Self {
            token_cache: cache,
            assignment_rules,
            grouping_rules,
            suppression_rules,
            group_type_indices,
            spike_detection_configs,
        }
    }

    pub async fn get_team<'c, E>(
        &self,
        e: E,
        api_token: &str,
    ) -> Result<Option<Team>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        match self.token_cache.get(api_token) {
            // We cache "no team" results too, so we don't have to query the database again
            Some(maybe_team) => {
                metrics::counter!(ANCILLARY_CACHE, "type" => "team", "outcome" => "hit")
                    .increment(1);
                Ok(maybe_team)
            }
            None => {
                metrics::counter!(ANCILLARY_CACHE, "type" => "team", "outcome" => "miss")
                    .increment(1);
                let team = Team::load_by_token(e, api_token).await?;
                self.token_cache.insert(api_token.to_string(), team.clone());
                Ok(team)
            }
        }
    }

    pub async fn get_assignment_rules<'c, E>(
        &self,
        e: E,
        team_id: TeamId,
    ) -> Result<Vec<AssignmentRule>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        if let Some(rules) = self.assignment_rules.get(&team_id) {
            metrics::counter!(ANCILLARY_CACHE, "type" => "assignment_rules", "outcome" => "hit")
                .increment(1);
            return Ok(rules.clone());
        }
        metrics::counter!(ANCILLARY_CACHE, "type" => "assignment_rules", "outcome" => "miss")
            .increment(1);
        // If we have no rules for the team, we just put an empty vector in the cache
        let rules = AssignmentRule::load_for_team(e, team_id).await?;
        self.assignment_rules.insert(team_id, rules.clone());
        Ok(rules)
    }

    pub async fn get_grouping_rules<'c, E>(
        &self,
        e: E,
        team_id: TeamId,
    ) -> Result<Vec<GroupingRule>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        if let Some(rules) = self.grouping_rules.get(&team_id) {
            metrics::counter!(ANCILLARY_CACHE, "type" => "grouping_rules", "outcome" => "hit")
                .increment(1);
            return Ok(rules.clone());
        }
        metrics::counter!(ANCILLARY_CACHE, "type" => "grouping_rules", "outcome" => "miss")
            .increment(1);
        // If we have no rules for the team, we just put an empty vector in the cache
        let rules = GroupingRule::load_for_team(e, team_id).await?;
        self.grouping_rules.insert(team_id, rules.clone());
        Ok(rules)
    }

    pub async fn get_suppression_rules<'c, E>(
        &self,
        e: E,
        team_id: TeamId,
    ) -> Result<Vec<SuppressionRule>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        if let Some(rules) = self.suppression_rules.get(&team_id) {
            metrics::counter!(ANCILLARY_CACHE, "type" => "suppression_rules", "outcome" => "hit")
                .increment(1);
            return Ok(rules.clone());
        }
        metrics::counter!(ANCILLARY_CACHE, "type" => "suppression_rules", "outcome" => "miss")
            .increment(1);
        let rules = SuppressionRule::load_for_team(e, team_id).await?;
        self.suppression_rules.insert(team_id, rules.clone());
        Ok(rules)
    }

    pub async fn get_spike_detection_config<'c, E>(
        &self,
        e: E,
        team_id: TeamId,
    ) -> Result<SpikeDetectionConfig, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        if let Some(cached) = self.spike_detection_configs.get(&team_id) {
            metrics::counter!(ANCILLARY_CACHE, "type" => "spike_detection_config", "outcome" => "hit")
                .increment(1);
            return Ok(cached.unwrap_or_default());
        }
        metrics::counter!(ANCILLARY_CACHE, "type" => "spike_detection_config", "outcome" => "miss")
            .increment(1);
        let config = SpikeDetectionConfig::load_for_team(e, team_id).await?;
        self.spike_detection_configs.insert(team_id, config.clone());
        Ok(config.unwrap_or_default())
    }

    pub async fn get_spike_detection_configs(
        &self,
        pool: &sqlx::PgPool,
        team_ids: impl IntoIterator<Item = i32>,
    ) -> HashMap<TeamId, SpikeDetectionConfig> {
        let unique_ids: std::collections::HashSet<i32> = team_ids.into_iter().collect();

        let tasks: Vec<(i32, _)> = unique_ids
            .into_iter()
            .map(|team_id| {
                let manager = self.clone();
                let pool = pool.clone();
                let task = tokio::spawn(async move {
                    manager.get_spike_detection_config(&pool, team_id).await
                });
                (team_id, task)
            })
            .collect();

        let mut result = HashMap::new();
        for (team_id, task) in tasks {
            let config = match task.await.expect("Task was not cancelled") {
                Ok(config) => config,
                Err(e) => {
                    warn!("Failed to load spike detection config for team {team_id}, using defaults: {e}");
                    SpikeDetectionConfig::default()
                }
            };
            result.insert(team_id, config);
        }
        result
    }

    pub async fn get_group_types<'c, E>(
        &self,
        e: E,
        team_id: TeamId,
    ) -> Result<Vec<GroupType>, UnhandledError>
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
        // If we have no indices for the team, we just put an empty vector in the cache
        let indices = GroupType::for_team(e, team_id).await?;
        self.group_type_indices.insert(team_id, indices.clone());
        Ok(indices)
    }
}

pub async fn do_team_lookups(
    context: Arc<AppContext>,
    events: &[IncomingEvent],
) -> Result<HashMap<String, Option<Team>>, PipelineFailure> {
    let mut team_lookups: HashMap<_, WithIndices<_>> = HashMap::new();
    for (index, event) in events.iter().enumerate() {
        let IncomingEvent::Captured(event) = event else {
            continue; // We don't need to look up teams that already have a team_id
        };

        if team_lookups.contains_key(&event.token) {
            team_lookups
                .get_mut(&event.token)
                .unwrap()
                .indices
                .push(index);
            continue;
        }

        let token = sanitize_string(event.token.clone());

        let m_ctx = context.clone();
        let m_token = token.clone();
        let fut = async move {
            m_ctx
                .team_manager
                .get_team(&m_ctx.posthog_pool, &m_token)
                .await
        };
        let lookup = WithIndices {
            indices: vec![index],
            inner: tokio::spawn(fut),
        };
        team_lookups.insert(token, lookup);
    }

    let mut results = HashMap::new();
    for (token, lookup) in team_lookups {
        let (indices, task) = (lookup.indices, lookup.inner);
        match task.await.expect("Task was not cancelled") {
            Ok(maybe_team) => {
                if maybe_team.is_none() {
                    warn!("Received event for unknown team token: {}", token);
                }
                results.insert(token, maybe_team);
            }
            Err(err) => return Err((indices[0], err).into()),
        };
    }

    Ok(results)
}
