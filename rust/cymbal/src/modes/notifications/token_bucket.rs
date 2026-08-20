//! The per-team token bucket behind the lifecycle rate limit.
//!
//! Independent of the per-event limiter in
//! [`crate::modes::processing::stages::rate_limiting`]. That one runs at event
//! volume, charges a variable number of tokens against two fused keys, and
//! carries optimizations this one does not need. This bucket charges exactly one
//! token against one key, and can return it.

use std::sync::{Arc, LazyLock};

use async_trait::async_trait;
use chrono::Utc;
use common_redis::{CustomRedisError, RedisClient};

const SECONDS_PER_HOUR: f64 = 3600.0;

/// Tokens available to a bucket right now: what was left at the stored
/// timestamp, plus what has refilled since, capped at `max`. Also returns the
/// timestamp to write back.
const REFILL_FN: &str = r#"
local function refill(key, max, rate, now)
  local cur = redis.call('hmget', key, 'ts', 'pool')
  if cur[1] == false then
    return max, now
  end

  local stored_ts = tonumber(cur[1])
  local elapsed = now - stored_ts
  if elapsed < 0 then elapsed = 0 end

  local tokens = tonumber(cur[2]) + elapsed * rate
  if tokens > max then tokens = max end

  -- Never move `ts` backwards. `now` is the calling pod's wall clock, so a pod
  -- running behind would otherwise inflate `elapsed` on the next forward call
  -- and over-refill the bucket.
  if now < stored_ts then
    return tokens, stored_ts
  end
  return tokens, now
end
"#;

/// Spend one token. Returns 1 when the bucket paid, 0 when it was empty. An
/// empty bucket still writes back its refill, so the next call does not
/// recompute the same elapsed window.
static CHARGE_SCRIPT: LazyLock<String> = LazyLock::new(|| {
    format!(
        r#"{}
local max, rate, ttl, now = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4])
local tokens, ts = refill(KEYS[1], max, rate, now)

local admitted = 0
if tokens >= 1 then
  admitted = 1
  tokens = tokens - 1
end

redis.call('hset', KEYS[1], 'ts', ts, 'pool', tokens)
redis.call('expire', KEYS[1], ttl)
return {{ admitted }}
"#,
        REFILL_FN
    )
});

/// Put one token back, never above capacity.
static REFUND_SCRIPT: LazyLock<String> = LazyLock::new(|| {
    format!(
        r#"{}
local max, rate, ttl, now = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4])
local tokens, ts = refill(KEYS[1], max, rate, now)

redis.call('hset', KEYS[1], 'ts', ts, 'pool', math.min(tokens + 1, max))
redis.call('expire', KEYS[1], ttl)
return {{ 1 }}
"#,
        REFILL_FN
    )
});

/// The one Redis operation this bucket needs. Behind a trait so the limiter can
/// be unit-tested against an in-memory fake, including a failing one that proves
/// the limiter fails open. Production uses the real `RedisClient`.
#[async_trait]
pub trait LuaRunner: Send + Sync {
    async fn eval_int_vec(
        &self,
        script: &str,
        keys: Vec<String>,
        args: Vec<String>,
    ) -> Result<Vec<i64>, CustomRedisError>;
}

#[async_trait]
impl LuaRunner for RedisClient {
    async fn eval_int_vec(
        &self,
        script: &str,
        keys: Vec<String>,
        args: Vec<String>,
    ) -> Result<Vec<i64>, CustomRedisError> {
        RedisClient::eval_int_vec(self, script, keys, args).await
    }
}

/// One bucket per team, holding `max` tokens and refilling at `rate` per second.
pub struct TokenBucket {
    redis: Arc<dyn LuaRunner>,
    key_prefix: String,
    max: f64,
    rate: f64,
    ttl_seconds: u64,
}

impl TokenBucket {
    /// A bucket that bursts to `per_hour` and sustains the same rate.
    pub fn per_hour(
        redis: Arc<dyn LuaRunner>,
        key_prefix: String,
        per_hour: f64,
        ttl_seconds: u64,
    ) -> Self {
        Self {
            redis,
            key_prefix,
            max: per_hour,
            rate: per_hour / SECONDS_PER_HOUR,
            ttl_seconds,
        }
    }

    /// Spend one of the team's tokens. `false` means the team is out of budget.
    pub async fn charge(&self, team_id: i32) -> Result<bool, CustomRedisError> {
        let res = self.eval(CHARGE_SCRIPT.as_str(), team_id).await?;
        Ok(res.first().copied().unwrap_or(0) > 0)
    }

    /// Put back a token a previous [`TokenBucket::charge`] spent.
    pub async fn refund(&self, team_id: i32) -> Result<(), CustomRedisError> {
        self.eval(REFUND_SCRIPT.as_str(), team_id).await?;
        Ok(())
    }

    async fn eval(&self, script: &str, team_id: i32) -> Result<Vec<i64>, CustomRedisError> {
        let args = vec![
            self.max.to_string(),
            self.rate.to_string(),
            self.ttl_seconds.to_string(),
            Utc::now().timestamp().to_string(),
        ];
        self.redis
            .eval_int_vec(script, vec![self.key(team_id)], args)
            .await
    }

    fn key(&self, team_id: i32) -> String {
        // The braces are a Redis Cluster hash tag, so a team's keys share one slot.
        format!("{}/{{{team_id}}}/lifecycle", self.key_prefix)
    }
}

/// Bucket tests against a real `redis:7-alpine` (via testcontainers). Ignored by
/// default (they need Docker, and they are slower). Run with:
/// ```sh
/// cargo test -p cymbal token_bucket::tests -- --ignored --test-threads=1
/// ```
#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::{CompressionConfig, RedisValueFormat};
    use std::time::Duration;
    use testcontainers::core::{IntoContainerPort, WaitFor};
    use testcontainers::runners::AsyncRunner;
    use testcontainers::{ContainerAsync, GenericImage};

    /// Boot a throwaway Redis and return a connected client. The readiness banner
    /// can land a hair before the socket accepts, so both the connect and a probe
    /// script are retried, otherwise the first command occasionally races the
    /// container and flakes with "connection refused".
    async fn start_redis() -> (Arc<RedisClient>, ContainerAsync<GenericImage>) {
        let container = GenericImage::new("redis", "7-alpine")
            .with_exposed_port(6379.tcp())
            .with_wait_for(WaitFor::message_on_stdout("Ready to accept connections"))
            .start()
            .await
            .unwrap();
        let host = container.get_host().await.unwrap();
        let port = container.get_host_port_ipv4(6379).await.unwrap();
        let url = format!("redis://{host}:{port}");

        for _ in 0..20 {
            if let Ok(client) = RedisClient::with_config(
                url.clone(),
                CompressionConfig::disabled(),
                RedisValueFormat::Utf8,
                None,
                None,
            )
            .await
            {
                if client
                    .eval_int_vec("return { 1 }", vec![], vec![])
                    .await
                    .is_ok()
                {
                    return (Arc::new(client), container);
                }
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        panic!("redis container never became ready");
    }

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
    async fn teams_hold_separate_budgets() {
        let (client, _container) = start_redis().await;
        let bucket = bucket(client, "tb/teams", 1.0);

        assert!(bucket.charge(1).await.unwrap());
        assert!(!bucket.charge(1).await.unwrap());
        assert!(bucket.charge(2).await.unwrap());
    }

    #[tokio::test]
    #[ignore]
    async fn refund_restores_one_spent_token() {
        let (client, _container) = start_redis().await;
        let bucket = bucket(client, "tb/refund", 2.0);

        for _ in 0..2 {
            assert!(bucket.charge(1).await.unwrap());
        }
        assert!(!bucket.charge(1).await.unwrap());

        bucket.refund(1).await.unwrap();
        assert!(bucket.charge(1).await.unwrap());
        assert!(!bucket.charge(1).await.unwrap());
    }

    #[tokio::test]
    #[ignore]
    async fn refund_never_exceeds_capacity() {
        let (client, _container) = start_redis().await;
        let bucket = bucket(client, "tb/cap", 2.0);

        assert!(bucket.charge(1).await.unwrap());
        for _ in 0..10 {
            bucket.refund(1).await.unwrap();
        }

        // Capacity is 2, so ten refunds of one token still leave room for two charges.
        assert!(bucket.charge(1).await.unwrap());
        assert!(bucket.charge(1).await.unwrap());
        assert!(!bucket.charge(1).await.unwrap());
    }
}
