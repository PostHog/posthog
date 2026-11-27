use std::{
    collections::HashMap,
    time::{Duration, Instant},
};

use common_types::{GroupType, Team, TeamId};
use moka::sync::{Cache, CacheBuilder};
use sqlx::PgPool;
use tracing::warn;

use crate::{
    error::UnhandledError,
    metric_consts::ANCILLARY_CACHE,
    modes::processing::config::ProcessingConfig,
    modes::processing::rules::assignment::AssignmentRule,
    modes::processing::rules::bypass::BypassRule,
    modes::processing::rules::grouping::GroupingRule,
    modes::processing::rules::rate_limit::RateLimitSettings,
    modes::processing::rules::severity::SeverityRule,
    modes::processing::rules::spike::SpikeDetectionConfig,
    modes::processing::rules::suppression::SuppressionRule,
    stages::linking::receipt::{EntryDeadline, EntryWithDeadline},
};

const AUTO_RESOLVE_OPT_IN_TTL: Duration = Duration::from_secs(60);

#[derive(Clone)]
pub struct TeamManager {
    pub token_cache: Cache<String, Option<Team>>,
    pub assignment_rules: Cache<TeamId, Vec<AssignmentRule>>,
    pub severity_rules: Cache<TeamId, Vec<SeverityRule>>,
    pub grouping_rules: Cache<TeamId, Vec<GroupingRule>>,
    pub suppression_rules: Cache<TeamId, Vec<SuppressionRule>>,
    pub bypass_rules: Cache<TeamId, Vec<BypassRule>>,
    pub group_type_indices: Cache<TeamId, Vec<GroupType>>,
    pub spike_detection_configs: Cache<TeamId, Option<SpikeDetectionConfig>>,
    pub rate_limit_settings: Cache<TeamId, Option<RateLimitSettings>>,
    auto_resolve_enabled: moka::future::Cache<TeamId, EntryWithDeadline<bool>>,
}

impl TeamManager {
    pub fn new(config: &ProcessingConfig) -> Self {
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

        let severity_rules = CacheBuilder::new(config.max_severity_rule_cache_size)
            .time_to_live(Duration::from_secs(config.severity_rule_cache_ttl_secs))
            .weigher(|_, rules: &Vec<SeverityRule>| {
                rules
                    .iter()
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

        let bypass_rules = CacheBuilder::new(config.max_bypass_rule_cache_size)
            .time_to_live(Duration::from_secs(config.bypass_rule_cache_ttl_secs))
            .weigher(|_, v: &Vec<BypassRule>| {
                v.iter()
                    .map(|rule| rule.bytecode.as_array().map_or(0, Vec::len) as u32)
                    .sum()
            })
            .build();

        let spike_detection_configs = CacheBuilder::new(config.max_team_cache_size)
            .time_to_live(Duration::from_secs(config.team_cache_ttl_secs))
            .build();

        let rate_limit_settings = CacheBuilder::new(config.max_team_cache_size)
            .time_to_live(Duration::from_secs(config.team_cache_ttl_secs))
            .build();

        Self {
            token_cache: cache,
            assignment_rules,
            severity_rules,
            grouping_rules,
            suppression_rules,
            bypass_rules,
            group_type_indices,
            spike_detection_configs,
            rate_limit_settings,
            auto_resolve_enabled: moka::future::Cache::builder()
                .max_capacity(config.max_team_cache_size)
                .expire_after(EntryDeadline)
                .build(),
        }
    }

    pub(crate) async fn tracks_issue_receipts(
        &self,
        pool: &PgPool,
        team_id: TeamId,
    ) -> Result<bool, UnhandledError> {
        loop {
            let entry = self
                .auto_resolve_enabled
                .try_get_with(team_id, async {
                    let expires_at = Instant::now() + AUTO_RESOLVE_OPT_IN_TTL;
                    let value = sqlx::query_scalar(
                        "SELECT EXISTS (SELECT 1 FROM posthog_errortrackingsettings \
                         WHERE team_id = $1 AND auto_resolve_after_days IS NOT NULL)",
                    )
                    .bind(team_id)
                    .fetch_one(pool)
                    .await?;
                    Ok::<_, sqlx::Error>(EntryWithDeadline { value, expires_at })
                })
                .await
                .map_err(|error| UnhandledError::Other(error.to_string()))?;
            if entry.value || entry.expires_at > Instant::now() {
                return Ok(entry.value);
            }
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

    pub async fn get_severity_rules<'c, E>(
        &self,
        executor: E,
        team_id: TeamId,
    ) -> Result<Vec<SeverityRule>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        if let Some(rules) = self.severity_rules.get(&team_id) {
            metrics::counter!(ANCILLARY_CACHE, "type" => "severity_rules", "outcome" => "hit")
                .increment(1);
            return Ok(rules.clone());
        }
        metrics::counter!(ANCILLARY_CACHE, "type" => "severity_rules", "outcome" => "miss")
            .increment(1);
        let rules = SeverityRule::load_for_team(executor, team_id).await?;
        self.severity_rules.insert(team_id, rules.clone());
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

    pub async fn get_bypass_rules<'c, E>(
        &self,
        e: E,
        team_id: TeamId,
    ) -> Result<Vec<BypassRule>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        if let Some(rules) = self.bypass_rules.get(&team_id) {
            metrics::counter!(ANCILLARY_CACHE, "type" => "bypass_rules", "outcome" => "hit")
                .increment(1);
            return Ok(rules.clone());
        }
        metrics::counter!(ANCILLARY_CACHE, "type" => "bypass_rules", "outcome" => "miss")
            .increment(1);
        let rules = BypassRule::load_for_team(e, team_id).await?;
        self.bypass_rules.insert(team_id, rules.clone());
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

    pub async fn get_rate_limit_setting<'c, E>(
        &self,
        e: E,
        team_id: TeamId,
    ) -> Result<Option<RateLimitSettings>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        if let Some(cached) = self.rate_limit_settings.get(&team_id) {
            metrics::counter!(ANCILLARY_CACHE, "type" => "rate_limit_settings", "outcome" => "hit")
                .increment(1);
            return Ok(cached);
        }
        metrics::counter!(ANCILLARY_CACHE, "type" => "rate_limit_settings", "outcome" => "miss")
            .increment(1);
        // We cache the "no settings row" result too (None), so opt-out teams don't re-query.
        let settings = RateLimitSettings::load_for_team(e, team_id).await?;
        self.rate_limit_settings.insert(team_id, settings.clone());
        Ok(settings)
    }

    /// Batch-load rate-limit settings for the teams in a request. Teams with no
    /// settings row (opted out) or a load error are omitted from the map, so the
    /// rate-limiting stage simply skips them.
    pub async fn get_rate_limit_settings(
        &self,
        pool: &sqlx::PgPool,
        team_ids: impl IntoIterator<Item = i32>,
    ) -> HashMap<TeamId, RateLimitSettings> {
        let unique_ids: std::collections::HashSet<i32> = team_ids.into_iter().collect();

        let tasks: Vec<(i32, _)> = unique_ids
            .into_iter()
            .map(|team_id| {
                let manager = self.clone();
                let pool = pool.clone();
                let task =
                    tokio::spawn(
                        async move { manager.get_rate_limit_setting(&pool, team_id).await },
                    );
                (team_id, task)
            })
            .collect();

        let mut result = HashMap::new();
        for (team_id, task) in tasks {
            match task.await.expect("Task was not cancelled") {
                Ok(Some(settings)) => {
                    result.insert(team_id, settings);
                }
                Ok(None) => {}
                Err(e) => {
                    warn!("Failed to load rate limit settings for team {team_id}: {e}");
                }
            }
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
