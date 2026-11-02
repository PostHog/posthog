//! Port of `nodejs/src/logs/services/logs-rate-limiter.service.ts`: per-team KB/s buckets on the
//! v2 script, with a partial batch let through up to the bucket's pre-call balance.

use std::sync::Arc;

use metrics::histogram;

use crate::js::date_parse;
use crate::property_filter::coerce::{js_math_round, js_parse_int, js_trim};

use super::keyed::{
    Clock, KeyRoot, KeyedRateLimitRequest, KeyedRateLimiter, KeyedRateLimiterConfig,
    RateLimiterError, ScriptVersion,
};
use super::redis::TokenBucketRedis;

pub const DEFAULT_LIMITER_NAME: &str = "logs-rate-limiter";

pub fn build_base_redis_key(key_root: KeyRoot, limiter_name: &str) -> String {
    format!("{}/{limiter_name}", key_root.as_str())
}

#[derive(Debug, Clone)]
pub struct LogsRateLimiterConfig {
    pub team_bucket_size_kb: String,
    pub team_refill_rate_kb_per_second: String,
    pub disabled_for_teams: String,
    pub enabled_teams: String,
    pub bucket_size_kb: f64,
    pub refill_rate_kb_per_second: f64,
    pub ttl_seconds: f64,
}

pub trait RateLimitedMessage {
    fn team_id(&self) -> i64;
    fn bytes_uncompressed(&self) -> f64;
    /// The value of the first Kafka header named `created_at`.
    fn created_at_header(&self) -> Option<&[u8]>;
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct LogsRateLimit {
    pub tokens_before: f64,
    pub tokens_after: f64,
    pub is_rate_limited: bool,
}

#[derive(Debug)]
pub struct FilteredMessages<M> {
    pub allowed: Vec<M>,
    pub dropped: Vec<M>,
}

#[derive(Debug, Clone, PartialEq)]
enum TeamList {
    All,
    Teams(Vec<f64>),
}

fn parse_team_id_list(config: &str) -> Option<TeamList> {
    if config == "*" {
        return Some(TeamList::All);
    }
    if config.is_empty() {
        return None;
    }
    Some(TeamList::Teams(
        config
            .split(',')
            .map(|id| js_parse_int(js_trim(id), Some(10)))
            .filter(|n| !n.is_nan())
            .collect(),
    ))
}

/// `parseTeamConfig`: `team:value` pairs; a later pair for a team replaces the earlier value.
fn parse_team_config(config: &str) -> Vec<(f64, f64)> {
    let mut result: Vec<(f64, f64)> = Vec::new();
    if config.is_empty() {
        return result;
    }
    for entry in config.split(',') {
        let mut parts = entry.split(':').map(|s| js_parse_int(js_trim(s), Some(10)));
        let team = parts.next().unwrap_or(f64::NAN);
        let value = parts.next().unwrap_or(f64::NAN);
        if team.is_nan() || value.is_nan() {
            continue;
        }
        match result.iter_mut().find(|(t, _)| *t == team) {
            Some(slot) => slot.1 = value,
            None => result.push((team, value)),
        }
    }
    result
}

fn lookup(pairs: &[(f64, f64)], team: f64) -> Option<f64> {
    pairs.iter().find(|(t, _)| *t == team).map(|(_, v)| *v)
}

fn bytes_to_kb(bytes: f64) -> f64 {
    (bytes / 1000.0).ceil()
}

pub struct LogsRateLimiter {
    config: LogsRateLimiterConfig,
    team_bucket_sizes: Vec<(f64, f64)>,
    team_refill_rates: Vec<(f64, f64)>,
    disabled_team_ids: Option<TeamList>,
    enabled_team_ids: Option<TeamList>,
    rate_limiter: KeyedRateLimiter,
}

impl LogsRateLimiter {
    pub fn new(
        config: LogsRateLimiterConfig,
        redis: Arc<dyn TokenBucketRedis>,
        limiter_name: &str,
        key_root: KeyRoot,
        clock: Clock,
    ) -> Self {
        let mut keyed = KeyedRateLimiterConfig::new(limiter_name, key_root);
        // Throws when Redis fails, as the legacy limiter did.
        keyed.fail_open = Some(false);
        keyed.script_version = ScriptVersion::V2;
        LogsRateLimiter {
            team_bucket_sizes: parse_team_config(&config.team_bucket_size_kb),
            team_refill_rates: parse_team_config(&config.team_refill_rate_kb_per_second),
            disabled_team_ids: parse_team_id_list(&config.disabled_for_teams),
            enabled_team_ids: parse_team_id_list(&config.enabled_teams),
            config,
            rate_limiter: KeyedRateLimiter::with_clock(keyed, redis, clock),
        }
    }

    fn now_seconds(&self) -> f64 {
        js_math_round((self.rate_limiter.clock())() / 1000.0)
    }

    fn timestamp_from_message<M: RateLimitedMessage>(&self, message: &M) -> f64 {
        if let Some(raw) = message.created_at_header() {
            let text = match std::str::from_utf8(raw) {
                Ok(text) => std::borrow::Cow::Borrowed(text),
                Err(_) => String::from_utf8_lossy(raw),
            };
            if !text.is_empty() {
                if let Some(ms) = date_parse(&text) {
                    return js_math_round(ms / 1000.0);
                }
            }
        }
        self.now_seconds()
    }

    /// `rateLimitMany(idCosts)`: `(team id, cost in KB, now in seconds)`.
    pub async fn rate_limit_many(
        &self,
        id_costs: &[(String, f64, f64)],
    ) -> Result<Vec<(String, LogsRateLimit)>, RateLimiterError> {
        let requests: Vec<KeyedRateLimitRequest> = id_costs
            .iter()
            .map(|(id, cost, now)| {
                let team = js_parse_int(id, Some(10));
                KeyedRateLimitRequest {
                    id: id.clone(),
                    cost: *cost,
                    now: Some(*now),
                    bucket_size: Some(
                        lookup(&self.team_bucket_sizes, team).unwrap_or(self.config.bucket_size_kb),
                    ),
                    refill_rate: Some(
                        lookup(&self.team_refill_rates, team)
                            .unwrap_or(self.config.refill_rate_kb_per_second),
                    ),
                    ttl_seconds: Some(self.config.ttl_seconds),
                }
            })
            .collect();
        let results = self.rate_limiter.rate_limit_many(&requests).await?;
        Ok(results
            .into_iter()
            .map(|(id, r)| {
                (
                    id,
                    LogsRateLimit {
                        tokens_before: r.tokens_before,
                        tokens_after: r.tokens,
                        is_rate_limited: r.is_rate_limited,
                    },
                )
            })
            .collect())
    }

    fn is_enabled_for_team(&self, team_id: i64) -> bool {
        let team = team_id as f64;
        match &self.disabled_team_ids {
            Some(TeamList::All) => return false,
            Some(TeamList::Teams(ids)) if ids.contains(&team) => return false,
            _ => {}
        }
        match &self.enabled_team_ids {
            Some(TeamList::All) => true,
            None => false,
            Some(TeamList::Teams(ids)) => ids.contains(&team),
        }
    }

    pub async fn filter_messages<M: RateLimitedMessage>(
        &self,
        messages: Vec<M>,
    ) -> Result<FilteredMessages<M>, RateLimiterError> {
        let mut team_costs: Vec<(i64, f64)> = Vec::new();
        let mut team_oldest: Vec<(i64, f64)> = Vec::new();
        let mut team_newest: Vec<(i64, f64)> = Vec::new();
        for message in &messages {
            let ts = self.timestamp_from_message(message);
            let team = message.team_id();
            match team_oldest.iter_mut().find(|(t, _)| *t == team) {
                Some(slot) if ts < slot.1 => slot.1 = ts,
                Some(_) => {}
                None => team_oldest.push((team, ts)),
            }
            match team_newest.iter_mut().find(|(t, _)| *t == team) {
                Some(slot) if ts > slot.1 => slot.1 = ts,
                Some(_) => {}
                None => team_newest.push((team, ts)),
            }
            if !self.is_enabled_for_team(team) {
                continue;
            }
            let cost = bytes_to_kb(message.bytes_uncompressed());
            match team_costs.iter_mut().find(|(t, _)| *t == team) {
                Some(slot) => slot.1 += cost,
                None => team_costs.push((team, cost)),
            }
        }

        let now = self.now_seconds();
        for (_, ts) in &team_oldest {
            histogram!("logs_rate_limiter_message_lag_seconds").record(now - ts);
        }

        let id_costs: Vec<(String, f64, f64)> = team_costs
            .iter()
            .map(|(team, cost)| {
                let newest = team_newest
                    .iter()
                    .find(|(t, _)| t == team)
                    .map(|(_, ts)| *ts)
                    .unwrap_or_else(|| self.now_seconds());
                (team.to_string(), *cost, newest)
            })
            .collect();
        let results = self.rate_limit_many(&id_costs).await?;
        let limits: Vec<(f64, LogsRateLimit)> = results
            .into_iter()
            .map(|(id, r)| (js_parse_int(&id, Some(10)), r))
            .collect();

        let mut allowed = Vec::new();
        let mut dropped = Vec::new();
        let mut used: Vec<(i64, f64)> = Vec::new();
        for message in messages {
            let team = message.team_id();
            let Some(limit) = limits
                .iter()
                .find(|(t, _)| *t == team as f64)
                .map(|(_, l)| *l)
            else {
                allowed.push(message);
                continue;
            };
            let kb_used = used
                .iter()
                .find(|(t, _)| *t == team)
                .map_or(0.0, |(_, u)| *u);
            let message_kb = bytes_to_kb(message.bytes_uncompressed());
            if kb_used + message_kb <= limit.tokens_before {
                match used.iter_mut().find(|(t, _)| *t == team) {
                    Some(slot) => slot.1 = kb_used + message_kb,
                    None => used.push((team, kb_used + message_kb)),
                }
                allowed.push(message);
            } else {
                dropped.push(message);
            }
        }
        Ok(FilteredMessages { allowed, dropped })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn team_settings_parse_like_parse_int() {
        assert_eq!(parse_team_id_list(""), None);
        assert_eq!(parse_team_id_list("*"), Some(TeamList::All));
        assert_eq!(
            parse_team_id_list(" 1, 2x,abc, *,-0"),
            Some(TeamList::Teams(vec![1.0, 2.0, -0.0]))
        );
        assert_eq!(
            parse_team_config("1:10, 2 : 20x,3,4:,1:11"),
            vec![(1.0, 11.0), (2.0, 20.0)]
        );
    }
}
