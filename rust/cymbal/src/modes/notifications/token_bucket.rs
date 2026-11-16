//! The per-team token bucket behind the issue-created rate limit.
//!
//! The Lua is deliberately not shared with the per-event limiter in
//! [`crate::modes::processing::stages::rate_limiting`], because sharing would move
//! that script's SHA and put a load-bearing ingestion path in reach of a change
//! made for this one.

use std::sync::Arc;

use chrono::Utc;
use common_redis::{CustomRedisError, ScriptRunner};
use tracing::warn;

use crate::modes::processing::redis_heal::HealGate;

const SECONDS_PER_HOUR: f64 = 3600.0;

/// Spend one token. Returns 1 when the bucket paid, 0 when it was empty. An empty
/// bucket still writes back its refill, so the next call does not recompute the
/// same elapsed window.
const CHARGE_SCRIPT: &str = r#"
local key = KEYS[1]
local max, rate, ttl, now = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4])

local cur = redis.call('hmget', key, 'ts', 'pool')
local tokens, ts
if cur[1] == false then
  tokens, ts = max, now
else
  local stored_ts = tonumber(cur[1])
  local elapsed = now - stored_ts
  if elapsed < 0 then elapsed = 0 end

  tokens = tonumber(cur[2]) + elapsed * rate
  if tokens > max then tokens = max end

  -- Never move `ts` backwards. `now` is the calling pod's wall clock, so a lagging
  -- pod would inflate `elapsed` on the next forward call and over-refill.
  ts = now
  if now < stored_ts then ts = stored_ts end
end

local admitted = 0
if tokens >= 1 then
  admitted = 1
  tokens = tokens - 1
end

redis.call('hset', key, 'ts', ts, 'pool', tokens)
redis.call('expire', key, ttl)
return { admitted }
"#;

/// Put one token back. Returns 1 when the bucket took it, 0 when there was no
/// bucket to credit.
const REFUND_SCRIPT: &str = r#"
local key = KEYS[1]
local max, ttl = tonumber(ARGV[1]), tonumber(ARGV[2])

-- A missing bucket is already a full one, so there is nothing to credit and no
-- reason to allocate a key.
local pool = redis.call('hget', key, 'pool')
if pool == false then return { 0 } end

local tokens = tonumber(pool) + 1
if tokens > max then tokens = max end

-- `ts` is left where it is. The charge script refills from it, so the window
-- since the last charge survives this write.
redis.call('hset', key, 'pool', tokens)
redis.call('expire', key, ttl)
return { 1 }
"#;

pub struct TokenBucket {
    redis: Arc<dyn ScriptRunner>,
    key_prefix: String,
    max: f64,
    rate: f64,
    ttl_seconds: u64,
    heal_gate: HealGate,
}

impl TokenBucket {
    /// A bucket that bursts to `per_hour` and sustains the same rate. `max /
    /// rate` is therefore always one hour, and `ttl_seconds` is raised to match:
    /// a shorter TTL drops a partly refilled bucket and hands the next caller a
    /// full one, which loosens the very limit the operator was tuning.
    pub fn per_hour(
        redis: Arc<dyn ScriptRunner>,
        key_prefix: String,
        per_hour: f64,
        ttl_seconds: u64,
    ) -> Self {
        let refill_window_seconds = SECONDS_PER_HOUR as u64;
        if ttl_seconds < refill_window_seconds {
            warn!(
                requested = ttl_seconds,
                using = refill_window_seconds,
                "issue-created bucket TTL raised to the refill window",
            );
        }

        Self {
            redis,
            key_prefix,
            max: per_hour,
            rate: per_hour / SECONDS_PER_HOUR,
            ttl_seconds: ttl_seconds.max(refill_window_seconds),
            heal_gate: HealGate::new(),
        }
    }

    /// Kick a background heal of the bucket's Redis connection, for a caller
    /// that saw a connection-class error. `MultiplexedConnection` never
    /// reconnects on its own, so without this one failover leaves the limiter
    /// admitting everything until the pod restarts. Never blocks the caller.
    pub fn spawn_heal(&self) {
        let redis = self.redis.clone();
        self.heal_gate.spawn_heal(async move { redis.heal().await });
    }

    /// Spend one of the team's tokens. `false` means the team is out of budget.
    pub async fn charge(&self, team_id: i32) -> Result<bool, CustomRedisError> {
        let args = vec![
            self.max.to_string(),
            self.rate.to_string(),
            self.ttl_seconds.to_string(),
            Utc::now().timestamp().to_string(),
        ];
        let res = self
            .redis
            .eval_int_vec(CHARGE_SCRIPT, vec![self.key(team_id)], args)
            .await?;
        Ok(res.first().copied().unwrap_or(0) > 0)
    }

    /// Give one token back, for a charge that bought nothing. A bucket that has
    /// since expired stays missing, because a missing bucket is already a full
    /// one.
    pub async fn refund(&self, team_id: i32) -> Result<(), CustomRedisError> {
        let args = vec![self.max.to_string(), self.ttl_seconds.to_string()];
        self.redis
            .eval_int_vec(REFUND_SCRIPT, vec![self.key(team_id)], args)
            .await?;
        Ok(())
    }

    fn key(&self, team_id: i32) -> String {
        // The braces are a Redis Cluster hash tag, so a team's keys share one slot.
        format!("{}/{{{team_id}}}/issue_created", self.key_prefix)
    }
}

/// The Redis-backed tests are ignored by default, because they need Docker. Run
/// them with:
/// ```sh
/// cargo test -p cymbal token_bucket::tests -- --ignored --test-threads=1
/// ```
#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::{start_redis, FakeRunner};
    use common_redis::RedisClient;

    fn bucket(client: Arc<RedisClient>, prefix: &str, per_hour: f64) -> TokenBucket {
        TokenBucket::per_hour(client, prefix.to_string(), per_hour, 3600)
    }

    #[tokio::test]
    #[ignore]
    async fn charge_admits_up_to_capacity_then_denies() {
        let (client, _container) = start_redis().await;
        let bucket = bucket(client, "tb/charge", 3.0);

        for _ in 0..3 {
            assert!(bucket.charge(1).await.unwrap());
        }
        assert!(!bucket.charge(1).await.unwrap());
    }

    #[tokio::test]
    #[ignore]
    async fn a_refund_hands_the_token_back() {
        let (client, _container) = start_redis().await;
        let bucket = bucket(client, "tb/refund", 1.0);

        assert!(bucket.charge(1).await.unwrap());
        assert!(!bucket.charge(1).await.unwrap());

        bucket.refund(1).await.unwrap();
        assert!(bucket.charge(1).await.unwrap());
    }

    #[test]
    fn a_ttl_below_the_refill_window_is_raised_to_it() {
        let bucket = TokenBucket::per_hour(
            FakeRunner::returning(vec![1]),
            "tb/ttl".to_string(),
            1000.0,
            60,
        );

        assert_eq!(bucket.ttl_seconds, SECONDS_PER_HOUR as u64);
    }

    #[tokio::test]
    #[ignore]
    async fn teams_hold_separate_budgets() {
        let (client, _container) = start_redis().await;
        let bucket = bucket(client, "tb/teams", 1.0);

        assert!(bucket.charge(1).await.unwrap());
        assert!(!bucket.charge(1).await.unwrap());
        assert!(bucket.charge(2).await.unwrap());
    }
}
