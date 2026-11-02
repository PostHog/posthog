use std::collections::HashMap;
use std::sync::Arc;

use metrics::counter;

use crate::js::number_to_string;
use crate::property_filter::coerce::js_math_round;

use super::redis::{
    ioredis_integer, token_bucket_v2, token_bucket_v3, LuaScript, ScriptCall, TokenBucketRedis,
};

/// The root of every key: `@posthog-test` under `NODE_ENV=test`, else `@posthog`. `Shadow` is
/// the Rust shadow deployment's own namespace, so it never spends the Node consumer's tokens.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeyRoot {
    Production,
    Test,
    Shadow,
}

impl KeyRoot {
    pub fn from_env() -> KeyRoot {
        if std::env::var("NODE_ENV").as_deref() == Ok("test") {
            KeyRoot::Test
        } else {
            KeyRoot::Production
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            KeyRoot::Production => "@posthog",
            KeyRoot::Test => "@posthog-test",
            KeyRoot::Shadow => "@posthog-logs-rust-shadow",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScriptVersion {
    V2,
    V3,
}

#[derive(Debug, Clone)]
pub struct KeyedRateLimiterConfig {
    pub name: String,
    pub key_root: KeyRoot,
    pub bucket_size: Option<f64>,
    pub refill_rate: Option<f64>,
    pub ttl_seconds: Option<f64>,
    /// `Some(false)` makes a failed pipeline an error; anything else allows every request.
    pub fail_open: Option<bool>,
    /// `scriptVersion`: anything but `'v3'` runs the v2 script in `rate_limit_many`.
    pub script_version: ScriptVersion,
}

impl KeyedRateLimiterConfig {
    pub fn new(name: &str, key_root: KeyRoot) -> Self {
        KeyedRateLimiterConfig {
            name: name.to_string(),
            key_root,
            bucket_size: None,
            refill_rate: None,
            ttl_seconds: None,
            fail_open: None,
            script_version: ScriptVersion::V2,
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct KeyedRateLimitRequest {
    pub id: String,
    pub cost: f64,
    pub bucket_size: Option<f64>,
    pub refill_rate: Option<f64>,
    pub ttl_seconds: Option<f64>,
    /// Default: `Math.round(Date.now() / 1000)`.
    pub now: Option<f64>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct KeyedRateLimit {
    /// The token count before the deduction, uncapped.
    pub tokens_before: f64,
    /// The token count after the deduction; -1 when the cost exceeded the budget.
    pub tokens: f64,
    pub is_rate_limited: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RateLimiterError {
    /// A request had no bucket size. Node throws this before it calls Redis.
    MissingBucketSize {
        limiter: String,
        id: String,
    },
    PipelineFailed {
        limiter: String,
    },
}

impl std::fmt::Display for RateLimiterError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RateLimiterError::MissingBucketSize { limiter, id } => {
                write!(
                    f,
                    "KeyedRateLimiterService({limiter}): missing bucketSize for {id}"
                )
            }
            RateLimiterError::PipelineFailed { limiter } => {
                write!(
                    f,
                    "KeyedRateLimiterService({limiter}): rate-limit pipeline failed"
                )
            }
        }
    }
}

impl std::error::Error for RateLimiterError {}

pub type Clock = Arc<dyn Fn() -> f64 + Send + Sync>;

pub fn system_clock() -> Clock {
    Arc::new(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_millis() as f64)
            .unwrap_or(0.0)
    })
}

pub struct KeyedRateLimiter {
    config: KeyedRateLimiterConfig,
    key_prefix: String,
    redis: Arc<dyn TokenBucketRedis>,
    clock: Clock,
    name_label: Arc<str>,
}

impl KeyedRateLimiter {
    pub fn new(config: KeyedRateLimiterConfig, redis: Arc<dyn TokenBucketRedis>) -> Self {
        Self::with_clock(config, redis, system_clock())
    }

    pub fn with_clock(
        config: KeyedRateLimiterConfig,
        redis: Arc<dyn TokenBucketRedis>,
        clock: Clock,
    ) -> Self {
        let key_prefix = format!("{}/{}/tokens", config.key_root.as_str(), config.name);
        let name_label = Arc::from(config.name.as_str());
        KeyedRateLimiter {
            config,
            key_prefix,
            redis,
            clock,
            name_label,
        }
    }

    pub fn key_prefix(&self) -> &str {
        &self.key_prefix
    }

    pub fn clock(&self) -> &Clock {
        &self.clock
    }

    fn bucket_size(&self, req: &KeyedRateLimitRequest) -> Result<f64, RateLimiterError> {
        req.bucket_size.or(self.config.bucket_size).ok_or_else(|| {
            RateLimiterError::MissingBucketSize {
                limiter: self.config.name.clone(),
                id: req.id.clone(),
            }
        })
    }

    /// `None` is the throw inside the pipeline callback, which `usePipeline` reports as a failed pipeline.
    fn call(&self, req: &KeyedRateLimitRequest) -> Option<ScriptCall> {
        let now = req
            .now
            .unwrap_or_else(|| js_math_round((self.clock)() / 1000.0));
        let bucket_size = req.bucket_size.or(self.config.bucket_size)?;
        let refill_rate = req.refill_rate.or(self.config.refill_rate)?;
        let ttl_seconds = req.ttl_seconds.or(self.config.ttl_seconds)?;
        Some(ScriptCall {
            key: format!("{}/{}", self.key_prefix, req.id),
            args: [now, req.cost, bucket_size, refill_rate, ttl_seconds]
                .into_iter()
                .map(number_to_string)
                .collect(),
        })
    }

    /// `None` when the pipeline or its callback fails, as `usePipeline` with `failOpen: true` gives.
    async fn run(
        &self,
        script: &LuaScript,
        requests: &[KeyedRateLimitRequest],
    ) -> Option<Vec<Option<Vec<i64>>>> {
        let calls: Option<Vec<ScriptCall>> = requests.iter().map(|r| self.call(r)).collect();
        let Some(calls) = calls else {
            tracing::error!(limiter = %self.config.name, "rate-limit arguments missing");
            return None;
        };
        match self.redis.eval_pipeline(script, &calls).await {
            Ok(replies) => Some(replies.into_iter().map(Result::ok).collect()),
            Err(error) => {
                tracing::error!(limiter = %self.config.name, %error, "Redis rate-limit pipeline failed");
                None
            }
        }
    }

    fn count_requests(&self, method: &'static str, outcome: &'static str, n: usize) {
        if n > 0 {
            counter!("keyed_rate_limiter_requests_total", "name" => self.name_label.clone(), "method" => method, "outcome" => outcome)
                .increment(n as u64);
        }
    }

    pub async fn rate_limit_many(
        &self,
        requests: &[KeyedRateLimitRequest],
    ) -> Result<Vec<(String, KeyedRateLimit)>, RateLimiterError> {
        if requests.is_empty() {
            return Ok(Vec::new());
        }
        let bucket_sizes = requests
            .iter()
            .map(|r| self.bucket_size(r))
            .collect::<Result<Vec<_>, _>>()?;
        let script = match self.config.script_version {
            ScriptVersion::V3 => token_bucket_v3(),
            ScriptVersion::V2 => token_bucket_v2(),
        };
        let res = self.run(script, requests).await;
        counter!("keyed_rate_limiter_redis_calls_total", "name" => self.name_label.clone(), "method" => "rateLimitMany")
            .increment(requests.len() as u64);
        let Some(replies) = res else {
            if self.config.fail_open == Some(false) {
                return Err(RateLimiterError::PipelineFailed {
                    limiter: self.config.name.clone(),
                });
            }
            self.count_requests("rateLimitMany", "allowed", requests.len());
            return Ok(requests
                .iter()
                .zip(bucket_sizes)
                .map(|(req, size)| {
                    (
                        req.id.clone(),
                        KeyedRateLimit {
                            tokens_before: size,
                            tokens: size,
                            is_rate_limited: false,
                        },
                    )
                })
                .collect());
        };
        let mut allowed = 0;
        let mut limited = 0;
        let out = requests
            .iter()
            .enumerate()
            .map(|(i, req)| {
                let reply = replies.get(i).cloned().flatten();
                let at = |k: usize| {
                    reply
                        .as_ref()
                        .and_then(|r| r.get(k))
                        .map(|n| ioredis_integer(*n))
                };
                let tokens_before = at(0).unwrap_or(bucket_sizes[i]);
                let tokens = at(1).unwrap_or(bucket_sizes[i]);
                let is_rate_limited = tokens <= 0.0;
                if is_rate_limited {
                    limited += 1;
                } else {
                    allowed += 1;
                }
                (
                    req.id.clone(),
                    KeyedRateLimit {
                        tokens_before,
                        tokens,
                        is_rate_limited,
                    },
                )
            })
            .collect();
        self.count_requests("rateLimitMany", "allowed", allowed);
        self.count_requests("rateLimitMany", "limited", limited);
        Ok(out)
    }

    /// Bucket parameters come from the first request for each id.
    pub async fn rate_limit_grouped(
        &self,
        requests: &[KeyedRateLimitRequest],
    ) -> Result<Vec<(String, KeyedRateLimit)>, RateLimiterError> {
        if requests.is_empty() {
            return Ok(Vec::new());
        }
        let mut items: Vec<KeyedRateLimitRequest> = Vec::new();
        let mut index_by_id: HashMap<&str, usize> = HashMap::new();
        for req in requests {
            match index_by_id.get(req.id.as_str()) {
                Some(&i) => items[i].cost += req.cost,
                None => {
                    index_by_id.insert(req.id.as_str(), items.len());
                    items.push(req.clone());
                }
            }
        }
        let bucket_sizes = items
            .iter()
            .map(|r| self.bucket_size(r))
            .collect::<Result<Vec<_>, _>>()?;
        let res = self.run(token_bucket_v3(), &items).await;
        counter!("keyed_rate_limiter_redis_calls_total", "name" => self.name_label.clone(), "method" => "rateLimitGrouped")
            .increment(items.len() as u64);
        let Some(replies) = res else {
            if self.config.fail_open == Some(false) {
                return Err(RateLimiterError::PipelineFailed {
                    limiter: self.config.name.clone(),
                });
            }
            self.count_requests("rateLimitGrouped", "allowed", requests.len());
            return Ok(requests
                .iter()
                .map(|req| {
                    let size = bucket_sizes[index_by_id[req.id.as_str()]];
                    (
                        req.id.clone(),
                        KeyedRateLimit {
                            tokens_before: size,
                            tokens: size,
                            is_rate_limited: false,
                        },
                    )
                })
                .collect());
        };
        let mut budget: Vec<f64> = items
            .iter()
            .enumerate()
            .map(|(i, _)| {
                replies
                    .get(i)
                    .cloned()
                    .flatten()
                    .and_then(|r| r.first().map(|n| ioredis_integer(*n)))
                    .unwrap_or(bucket_sizes[i])
            })
            .collect();
        let mut allowed = 0;
        let mut limited = 0;
        let out = requests
            .iter()
            .map(|req| {
                let i = index_by_id[req.id.as_str()];
                let tokens_before = budget[i];
                if tokens_before >= req.cost {
                    let next = tokens_before - req.cost;
                    budget[i] = next;
                    allowed += 1;
                    (
                        req.id.clone(),
                        KeyedRateLimit {
                            tokens_before,
                            tokens: next,
                            is_rate_limited: false,
                        },
                    )
                } else {
                    limited += 1;
                    (
                        req.id.clone(),
                        KeyedRateLimit {
                            tokens_before,
                            tokens: -1.0,
                            is_rate_limited: true,
                        },
                    )
                }
            })
            .collect();
        self.count_requests("rateLimitGrouped", "allowed", allowed);
        self.count_requests("rateLimitGrouped", "limited", limited);
        Ok(out)
    }
}
