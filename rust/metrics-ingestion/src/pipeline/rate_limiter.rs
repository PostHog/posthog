//! `metrics-rate-limiter.service.ts`. It shares the v2 token-bucket script and key layout with the keyed limiter, but a
//! reply that is missing for one team falls back to the global bucket size, not the team's, as in Node.

use std::collections::HashMap;
use std::sync::Arc;

use logs_ingestion::js::{date_parse, number_to_string};
use logs_ingestion::property_filter::coerce::{js_math_round, js_parse_int, js_trim};
use logs_ingestion::rate_limiter::redis::ioredis_integer;
use logs_ingestion::rate_limiter::{token_bucket_v2, Clock, KeyRoot, ScriptCall, TokenBucketRedis};

use super::config::MetricsLimiterConfig;
use super::types::MetricsIngestionMessage;

pub const LIMITER_NAME: &str = "metrics-rate-limiter";

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

/// A later pair for a team replaces the earlier value, as `Map.set` does.
fn parse_team_config(config: &str) -> Vec<(f64, f64)> {
    let mut result: Vec<(f64, f64)> = Vec::new();
    for entry in config.split(',').filter(|_| !config.is_empty()) {
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

fn bytes_to_kb(bytes: u64) -> f64 {
    (bytes as f64 / 1000.0).ceil()
}

#[derive(Debug, thiserror::Error)]
#[error("Failed to rate limit")]
pub struct RateLimitFailed;

pub struct MetricsRateLimiter {
    config: MetricsLimiterConfig,
    team_bucket_sizes: Vec<(f64, f64)>,
    team_refill_rates: Vec<(f64, f64)>,
    disabled_team_ids: Option<TeamList>,
    enabled_team_ids: Option<TeamList>,
    redis: Arc<dyn TokenBucketRedis>,
    key_prefix: String,
    clock: Clock,
}

impl MetricsRateLimiter {
    pub fn new(
        config: MetricsLimiterConfig,
        redis: Arc<dyn TokenBucketRedis>,
        key_root: KeyRoot,
        clock: Clock,
    ) -> Self {
        Self {
            team_bucket_sizes: parse_team_config(&config.team_bucket_size_kb),
            team_refill_rates: parse_team_config(&config.team_refill_rate_kb_per_second),
            disabled_team_ids: parse_team_id_list(&config.disabled_for_teams),
            enabled_team_ids: parse_team_id_list(&config.enabled_teams),
            config,
            redis,
            key_prefix: format!("{}/{LIMITER_NAME}/tokens", key_root.as_str()),
            clock,
        }
    }

    fn now_seconds(&self) -> f64 {
        js_math_round((self.clock)() / 1000.0)
    }

    /// The first `created_at` header with a value, as `getHeaderValue` reads it. An empty or unparsable value falls back to now.
    fn timestamp_seconds(&self, message: &MetricsIngestionMessage) -> f64 {
        let raw = message
            .message
            .headers
            .iter()
            .filter(|(key, _)| key == "created_at")
            .find_map(|(_, value)| value.as_deref());
        if let Some(raw) = raw.filter(|raw| !raw.is_empty()) {
            if let Some(ms) = date_parse(&String::from_utf8_lossy(raw)) {
                return js_math_round(ms / 1000.0);
            }
        }
        self.now_seconds()
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

    /// `rateLimitMany`: tokens before each team's deduction. A failed pipeline is an error, so the batch replays.
    async fn tokens_before(&self, team_costs: &[(i64, f64, f64)]) -> anyhow::Result<Vec<f64>> {
        if team_costs.is_empty() {
            return Ok(Vec::new());
        }
        let calls: Vec<ScriptCall> = team_costs
            .iter()
            .map(|(team, cost, now)| {
                let team_number = *team as f64;
                let bucket = lookup(&self.team_bucket_sizes, team_number)
                    .unwrap_or(self.config.bucket_size_kb);
                let refill = lookup(&self.team_refill_rates, team_number)
                    .unwrap_or(self.config.refill_rate_kb_per_second);
                ScriptCall {
                    key: format!("{}/{team}", self.key_prefix),
                    args: [*now, *cost, bucket, refill, self.config.ttl_seconds]
                        .into_iter()
                        .map(number_to_string)
                        .collect(),
                }
            })
            .collect();
        let replies = match self.redis.eval_pipeline(token_bucket_v2(), &calls).await {
            Ok(replies) => replies,
            Err(error) => {
                tracing::error!(%error, "Redis call metrics-rate-limiter failed");
                return Err(anyhow::Error::new(RateLimitFailed));
            }
        };
        Ok((0..calls.len())
            .map(|i| {
                replies
                    .get(i)
                    .and_then(|reply| reply.as_ref().ok())
                    .and_then(|reply| reply.first())
                    .map(|n| ioredis_integer(*n))
                    .unwrap_or(self.config.bucket_size_kb)
            })
            .collect())
    }

    /// `filterMessages`, as one `dropped` flag per message in input order.
    pub async fn dropped(
        &self,
        messages: &[&MetricsIngestionMessage],
    ) -> anyhow::Result<Vec<bool>> {
        // Vectors keep the insertion order of Node's `Map`s.
        let mut team_costs: Vec<(i64, f64)> = Vec::new();
        let mut team_span: Vec<(i64, f64, f64)> = Vec::new();
        for message in messages {
            let ts = self.timestamp_seconds(message);
            match team_span.iter_mut().find(|(t, _, _)| *t == message.team_id) {
                Some((_, oldest, newest)) => {
                    *oldest = oldest.min(ts);
                    *newest = newest.max(ts);
                }
                None => team_span.push((message.team_id, ts, ts)),
            }
            if !self.is_enabled_for_team(message.team_id) {
                continue;
            }
            let cost = bytes_to_kb(message.sizes.bytes_uncompressed);
            match team_costs.iter_mut().find(|(t, _)| *t == message.team_id) {
                Some((_, total)) => *total += cost,
                None => team_costs.push((message.team_id, cost)),
            }
        }
        let now = self.now_seconds();
        for (_, oldest, _) in &team_span {
            metrics::histogram!("metrics_rate_limiter_message_lag_seconds").record(now - oldest);
        }
        // The newest timestamp per team gives a catch-up batch refill credit for the span it covers.
        let requests: Vec<(i64, f64, f64)> = team_costs
            .iter()
            .map(|(team, cost)| {
                let newest = team_span
                    .iter()
                    .find(|(t, _, _)| t == team)
                    .map(|(_, _, newest)| *newest)
                    .unwrap_or(now);
                (*team, *cost, newest)
            })
            .collect();
        let before = self.tokens_before(&requests).await?;
        let available: HashMap<i64, f64> = requests
            .iter()
            .zip(before)
            .map(|((team, _, _), tokens)| (*team, tokens))
            .collect();

        let mut used: HashMap<i64, f64> = HashMap::new();
        Ok(messages
            .iter()
            .map(|message| {
                let Some(tokens_before) = available.get(&message.team_id) else {
                    return false;
                };
                let kb_used = used.get(&message.team_id).copied().unwrap_or(0.0);
                let message_kb = bytes_to_kb(message.sizes.bytes_uncompressed);
                if kb_used + message_kb <= *tokens_before {
                    used.insert(message.team_id, kb_used + message_kb);
                    false
                } else {
                    true
                }
            })
            .collect())
    }
}
