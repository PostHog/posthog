//! The Redis token bucket both error-tracking limiters are built on.
//!
//! [`TAKE_FN`] and [`GIVE_FN`] are Lua function definitions, not whole scripts:
//! a caller concatenates the ones it needs with its own body. The event limiter
//! ([`crate::modes::processing::stages::rate_limiting`]) fuses two `take` calls
//! into one script; the lifecycle limiter
//! ([`crate::modes::notifications::rate_limit`]) uses the single-key
//! [`TokenBucket`] below.

use std::sync::{Arc, LazyLock};

use async_trait::async_trait;
use chrono::Utc;
use common_redis::{CustomRedisError, RedisClient};

/// Charge `want` tokens against one bucket and return how many were admitted.
/// A bucket holds up to `max` tokens and refills at `rate` tokens per second.
/// A negative `max` disables the limit (admits everything offered to it).
pub const TAKE_FN: &str = r#"
local function take(key, want, max, rate, ttl, now)
  if want <= 0 then return 0 end
  if max < 0 then return want end

  local cur = redis.call('hmget', key, 'ts', 'pool')
  local tokens
  if cur[1] == false then
    tokens = max
  else
    local elapsed = now - tonumber(cur[1])
    if elapsed < 0 then elapsed = 0 end
    tokens = tonumber(cur[2]) + elapsed * rate
    if tokens > max then tokens = max end
  end

  local admit = math.floor(tokens)
  if admit > want then admit = want end

  -- Never regress `ts`. `now` is each pod's wall clock, so a pod with a lagging
  -- clock (now < stored ts) must not drag the timestamp backward, or the next
  -- forward call would compute an inflated `elapsed` and over-refill the bucket.
  -- Matches the non-regression guard in the Node.js token-bucket scripts.
  local ts_to_write = now
  if cur[1] ~= false and now < tonumber(cur[1]) then
    ts_to_write = tonumber(cur[1])
  end

  redis.call('hset', key, 'ts', ts_to_write, 'pool', tokens - admit)

  -- EXPIRE dispatch dominated this primitive's Redis CPU in prod, so refresh the TTL
  -- only on creation or once the remaining TTL drops below ttl/2, and write a 2x
  -- ceiling for headroom (mirrors the Node.js v3 token-bucket script). PTTL's -1 (no
  -- TTL) and -2 (missing key) are both below the threshold, so a lost TTL re-arms.
  if cur[1] == false or redis.call('pttl', key) < (ttl * 500) then
    redis.call('expire', key, ttl * 2)
  end
  return admit
end
"#;

/// Return `n` tokens to a bucket a previous `take` charged, and report whether
/// anything was returned. A missing key is already a full bucket, so a refund
/// into one is a no-op rather than a fresh key with an invented pool. The TTL is
/// left alone: only `take` creates a bucket, so only `take` needs to arm it.
pub const GIVE_FN: &str = r#"
local function give(key, n, max, rate, now)
  if n <= 0 then return 0 end
  if max < 0 then return 0 end

  local cur = redis.call('hmget', key, 'ts', 'pool')
  if cur[1] == false then return 0 end

  local elapsed = now - tonumber(cur[1])
  if elapsed < 0 then elapsed = 0 end
  local tokens = tonumber(cur[2]) + elapsed * rate + n
  if tokens > max then tokens = max end

  local ts_to_write = now
  if now < tonumber(cur[1]) then
    ts_to_write = tonumber(cur[1])
  end

  redis.call('hset', key, 'ts', ts_to_write, 'pool', tokens)
  return 1
end
"#;

static TAKE_SCRIPT: LazyLock<String> = LazyLock::new(|| {
    format!(
        r#"{}
local admitted = take(KEYS[1], tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4]), tonumber(ARGV[5]), tonumber(ARGV[1]))
return {{ admitted }}
"#,
        TAKE_FN
    )
});

static GIVE_SCRIPT: LazyLock<String> = LazyLock::new(|| {
    format!(
        r#"{}
local refunded = give(KEYS[1], tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4]), tonumber(ARGV[1]))
return {{ refunded }}
"#,
        GIVE_FN
    )
});

/// The single Redis operation the limiters need: run the Lua script and decode
/// its integer-array reply. Behind a trait so callers can be unit-tested with an
/// in-memory fake -- including a failing one, to prove they fail open.
/// Production uses the real `RedisClient`.
#[async_trait]
pub trait ScriptRunner: Send + Sync {
    async fn eval_int_vec(
        &self,
        script: &str,
        keys: Vec<String>,
        args: Vec<String>,
    ) -> Result<Vec<i64>, CustomRedisError>;
}

#[async_trait]
impl ScriptRunner for RedisClient {
    async fn eval_int_vec(
        &self,
        script: &str,
        keys: Vec<String>,
        args: Vec<String>,
    ) -> Result<Vec<i64>, CustomRedisError> {
        RedisClient::eval_int_vec(self, script, keys, args).await
    }
}

/// Capacity and refill for one bucket. `max` is the burst size, `rate` the
/// steady refill in tokens per second.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Bucket {
    pub max: f64,
    pub rate: f64,
}

impl Bucket {
    /// `value` charges per `window_seconds`: burst `value`, refill
    /// `value / window_seconds` per second.
    pub fn per_window(value: f64, window_seconds: f64) -> Self {
        Self {
            max: value,
            rate: value / window_seconds,
        }
    }
}

/// A token bucket over a single caller-supplied Redis key.
pub struct TokenBucket {
    redis: Arc<dyn ScriptRunner>,
    ttl_seconds: u64,
}

impl TokenBucket {
    pub fn new(redis: Arc<dyn ScriptRunner>, ttl_seconds: u64) -> Self {
        Self { redis, ttl_seconds }
    }

    /// Charge `n` tokens and report how many were admitted (`0..=n`).
    pub async fn take(&self, key: String, bucket: Bucket, n: u32) -> Result<u32, CustomRedisError> {
        let args = vec![
            Utc::now().timestamp().to_string(),
            n.to_string(),
            bucket.max.to_string(),
            bucket.rate.to_string(),
            self.ttl_seconds.to_string(),
        ];
        let res = self
            .redis
            .eval_int_vec(TAKE_SCRIPT.as_str(), vec![key], args)
            .await?;

        Ok((res.first().copied().unwrap_or(0).max(0) as u32).min(n))
    }

    /// Return `n` tokens a previous [`TokenBucket::take`] charged.
    pub async fn give(&self, key: String, bucket: Bucket, n: u32) -> Result<(), CustomRedisError> {
        let args = vec![
            Utc::now().timestamp().to_string(),
            n.to_string(),
            bucket.max.to_string(),
            bucket.rate.to_string(),
        ];
        self.redis
            .eval_int_vec(GIVE_SCRIPT.as_str(), vec![key], args)
            .await?;

        Ok(())
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
    /// script are retried — otherwise the first command occasionally races the
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

    fn hourly(value: f64) -> Bucket {
        Bucket::per_window(value, 3600.0)
    }

    #[tokio::test]
    #[ignore]
    async fn take_admits_up_to_capacity_then_denies() {
        let (client, _container) = start_redis().await;
        let bucket = TokenBucket::new(client, 3600);
        let key = "tb/take/1".to_string();

        for _ in 0..3 {
            assert_eq!(bucket.take(key.clone(), hourly(3.0), 1).await.unwrap(), 1);
        }
        assert_eq!(bucket.take(key, hourly(3.0), 1).await.unwrap(), 0);
    }

    #[tokio::test]
    #[ignore]
    async fn give_restores_a_charged_token() {
        let (client, _container) = start_redis().await;
        let bucket = TokenBucket::new(client, 3600);
        let key = "tb/give/1".to_string();

        for _ in 0..2 {
            assert_eq!(bucket.take(key.clone(), hourly(2.0), 1).await.unwrap(), 1);
        }
        assert_eq!(bucket.take(key.clone(), hourly(2.0), 1).await.unwrap(), 0);

        bucket.give(key.clone(), hourly(2.0), 1).await.unwrap();
        assert_eq!(bucket.take(key.clone(), hourly(2.0), 1).await.unwrap(), 1);
        assert_eq!(bucket.take(key, hourly(2.0), 1).await.unwrap(), 0);
    }

    #[tokio::test]
    #[ignore]
    async fn give_never_exceeds_capacity() {
        let (client, _container) = start_redis().await;
        let bucket = TokenBucket::new(client, 3600);
        let key = "tb/give/2".to_string();

        assert_eq!(bucket.take(key.clone(), hourly(2.0), 1).await.unwrap(), 1);
        for _ in 0..10 {
            bucket.give(key.clone(), hourly(2.0), 1).await.unwrap();
        }

        // Capacity is 2, so ten refunds of one token still leave room for two takes.
        assert_eq!(bucket.take(key.clone(), hourly(2.0), 1).await.unwrap(), 1);
        assert_eq!(bucket.take(key.clone(), hourly(2.0), 1).await.unwrap(), 1);
        assert_eq!(bucket.take(key, hourly(2.0), 1).await.unwrap(), 0);
    }

    #[tokio::test]
    #[ignore]
    async fn give_on_a_missing_key_creates_nothing() {
        let (client, _container) = start_redis().await;
        let bucket = TokenBucket::new(client.clone(), 3600);
        let key = "tb/give/3".to_string();

        bucket.give(key.clone(), hourly(2.0), 1).await.unwrap();

        // A full bucket is the correct state for a key that does not exist, so the
        // refund must not write one with an invented pool.
        assert_eq!(
            client
                .eval_int_vec(
                    "return { redis.call('exists', KEYS[1]) }",
                    vec![key],
                    vec![]
                )
                .await
                .unwrap(),
            vec![0]
        );
    }
}
