//! Port of `nodejs/src/common/services/keyed-rate-limiter.service.ts` (the client side of the
//! keyed token bucket) and `nodejs/src/logs/services/logs-rate-limiter.service.ts`.
//!
//! Both implementations use the same keys, script text, argument order and time source, so a
//! Rust and a Node consumer that share a Redis also share bucket state.

pub mod keyed;
pub mod logs;
pub mod redis;

pub use keyed::{
    system_clock, Clock, KeyRoot, KeyedRateLimit, KeyedRateLimitRequest, KeyedRateLimiter,
    KeyedRateLimiterConfig, RateLimiterError, ScriptVersion,
};
pub use logs::{
    build_base_redis_key, FilteredMessages, LogsRateLimit, LogsRateLimiter, LogsRateLimiterConfig,
    RateLimitedMessage, DEFAULT_LIMITER_NAME,
};
pub use redis::{
    token_bucket_v2, token_bucket_v3, LuaScript, RedisTokenBucket, ScriptCall, ScriptReply,
    TokenBucketRedis,
};
