use std::borrow::Cow;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use crate::config::Config;
use chrono::Utc;
use common_redis::Client;
use limiters::global_rate_limiter::{
    EvalResult, GlobalRateLimitResponse, GlobalRateLimiter as CommonGlobalRateLimiter,
    GlobalRateLimiterConfig, GlobalRateLimiterImpl as CommonGlobalRateLimiterImpl,
};
use tracing::{error, info};

#[cfg(test)]
use chrono::DateTime;

const MAX_DISTINCT_ID_CHARS: usize = 128;

fn truncate_str(s: &str, max_chars: usize) -> &str {
    match s.char_indices().nth(max_chars) {
        Some((idx, _)) => &s[..idx],
        None => s,
    }
}

pub enum GlobalRateLimitKey<'a> {
    Token(&'a str),
    TokenDistinctId(&'a str, &'a str),
}

impl<'a> GlobalRateLimitKey<'a> {
    pub fn to_cache_key(&self) -> Cow<'a, str> {
        match self {
            Self::Token(t) => Cow::Borrowed(t),
            Self::TokenDistinctId(t, d) => {
                Cow::Owned(format!("{t}:{}", truncate_str(d, MAX_DISTINCT_ID_CHARS)))
            }
        }
    }
}

pub struct GlobalRateLimiter {
    limiter: Box<dyn CommonGlobalRateLimiter>,
}

impl GlobalRateLimiter {
    /// Build both rate limiter instances from the capture config, sharing a single
    /// Redis client. If a dedicated Redis URL is configured, creates a separate client
    /// (optionally with read/write split). Falls back to `shared_redis` when no
    /// dedicated URL is set.
    ///
    /// Returns `(token_distinct_id_limiter, token_limiter)`.
    pub async fn try_from_config(
        config: &Config,
        shared_redis: Arc<dyn Client + Send + Sync>,
    ) -> anyhow::Result<(Self, Self)> {
        let redis_client = Self::build_redis_client(config, shared_redis).await?;
        let redis_instances = vec![redis_client];
        let td_limiter = Self::new_token_distinct_id(config, redis_instances.clone())?;
        let token_limiter = Self::new_token(config, redis_instances)?;
        Ok((td_limiter, token_limiter))
    }

    /// Create a per-(token, distinct_id) rate limiter sharing the given Redis instances.
    pub fn new_token_distinct_id(
        config: &Config,
        redis_instances: Vec<Arc<dyn Client + Send + Sync>>,
    ) -> anyhow::Result<Self> {
        let prefix = format!(
            "@ph/grl/capture/tok_distid/{}",
            config.capture_mode.as_tag()
        );
        Self::build(
            config,
            redis_instances,
            config.global_rate_limit_token_distinctid_threshold,
            config
                .global_rate_limit_token_distinctid_overrides_csv
                .as_ref(),
            config.global_rate_limit_token_distinctid_local_cache_max_entries,
            &prefix,
        )
    }

    /// Create a per-token rate limiter sharing the given Redis instances.
    pub fn new_token(
        config: &Config,
        redis_instances: Vec<Arc<dyn Client + Send + Sync>>,
    ) -> anyhow::Result<Self> {
        let prefix = format!("@ph/grl/capture/token/{}", config.capture_mode.as_tag());
        Self::build(
            config,
            redis_instances,
            config.global_rate_limit_token_threshold,
            config.global_rate_limit_token_overrides_csv.as_ref(),
            config.global_rate_limit_token_local_cache_max_entries,
            &prefix,
        )
    }

    fn build(
        config: &Config,
        redis_instances: Vec<Arc<dyn Client + Send + Sync>>,
        threshold: u64,
        custom_keys_csv: Option<&String>,
        local_cache_max_entries: u64,
        redis_key_prefix: &str,
    ) -> anyhow::Result<Self> {
        let grl_config = GlobalRateLimiterConfig {
            global_threshold: threshold,
            window_interval: Duration::from_secs(config.global_rate_limit_window_interval_secs),
            sync_interval: Duration::from_secs(config.global_rate_limit_sync_interval_secs),
            tick_interval: Duration::from_millis(config.global_rate_limit_tick_interval_ms),
            redis_key_prefix: redis_key_prefix.to_string(),
            custom_keys: Self::format_custom_keys(custom_keys_csv),
            local_cache_max_entries,
            ..Default::default()
        };

        let limiter = match CommonGlobalRateLimiterImpl::new(grl_config, redis_instances) {
            Ok(l) => l,
            Err(e) => {
                error!(error = %e, "Failed to initialize GlobalRateLimiter");
                return Err(e);
            }
        };

        Ok(Self {
            limiter: Box::new(limiter),
        })
    }

    /// Check if a key is rate limited. Routes to custom or global check based on
    /// whether the key is registered in the custom_keys map. Exactly one check
    /// fires per call — no double-enqueue to the Redis batch channel.
    pub async fn is_limited(&self, key: &str, count: u64) -> Option<GlobalRateLimitResponse> {
        if self.limiter.is_custom_key(key) {
            self.is_custom_key_limited(key, count).await
        } else {
            self.is_global_key_limited(key, count).await
        }
    }

    async fn is_global_key_limited(
        &self,
        key: &str,
        count: u64,
    ) -> Option<GlobalRateLimitResponse> {
        match self.limiter.check_limit(key, count, Some(Utc::now())).await {
            EvalResult::Limited(response) => Some(response),
            _ => None,
        }
    }

    async fn is_custom_key_limited(
        &self,
        key: &str,
        count: u64,
    ) -> Option<GlobalRateLimitResponse> {
        match self
            .limiter
            .check_custom_limit(key, count, Some(Utc::now()))
            .await
        {
            EvalResult::Limited(response) => Some(response),
            _ => None,
        }
    }

    // trigger shutdown and stop pushing updates to global cache
    pub fn shutdown(&mut self) {
        self.limiter.shutdown();
    }

    pub async fn build_redis_client(
        config: &Config,
        shared_redis: Arc<dyn Client + Send + Sync>,
    ) -> anyhow::Result<Arc<dyn Client + Send + Sync>> {
        let Some(ref writer_url) = config.global_rate_limit_redis_url else {
            return Ok(shared_redis);
        };

        let response_timeout = config
            .global_rate_limit_redis_response_timeout_ms
            .unwrap_or(config.redis_response_timeout_ms);
        let connection_timeout = config
            .global_rate_limit_redis_connection_timeout_ms
            .unwrap_or(config.redis_connection_timeout_ms);
        let response_timeout = if response_timeout == 0 {
            None
        } else {
            Some(Duration::from_millis(response_timeout))
        };
        let connection_timeout = if connection_timeout == 0 {
            None
        } else {
            Some(Duration::from_millis(connection_timeout))
        };

        if let Some(ref reader_url) = config.global_rate_limit_redis_reader_url {
            info!("Global rate limiter using read/write split Redis client");
            let rw_config = common_redis::ReadWriteClientConfig::new(
                writer_url.clone(),
                reader_url.clone(),
                common_redis::CompressionConfig::disabled(),
                common_redis::RedisValueFormat::default(),
                response_timeout,
                connection_timeout,
            );
            Ok(Arc::new(rw_config.build().await?))
        } else {
            Ok(Arc::new(
                common_redis::RedisClient::with_config(
                    writer_url.clone(),
                    common_redis::CompressionConfig::disabled(),
                    common_redis::RedisValueFormat::default(),
                    response_timeout,
                    connection_timeout,
                )
                .await?,
            ))
        }
    }

    #[cfg(test)]
    fn new_with(limiter: impl CommonGlobalRateLimiter + 'static) -> Self {
        Self {
            limiter: Box::new(limiter),
        }
    }

    // In capture deploys, the custom keys and rate limit thresholds should be
    // supplied as a CSV list of <string_key>=<u64_value> elements. malformed
    // elements will be logged and skipped during limiter initialization
    fn format_custom_keys(custom_keys_csv: Option<&String>) -> HashMap<String, u64> {
        let mut custom_keys = HashMap::new();

        if custom_keys_csv.is_none() || custom_keys_csv.unwrap().is_empty() {
            return custom_keys;
        }

        for elem in custom_keys_csv.unwrap().split(',') {
            let (key, limit) = match elem.split_once('=') {
                Some((k, l)) => (k, l),
                None => {
                    error!(
                        input = elem,
                        "Global rate limiter: failed to split custom key-value pair"
                    );
                    continue;
                }
            };
            let key = key.trim();
            match limit.trim().parse::<u64>() {
                Ok(value) => custom_keys.insert(key.to_string(), value),
                Err(e) => {
                    error!(
                        error = e.to_string(),
                        key, limit, "Global rate limiter: failed to parse custom key value"
                    );
                    continue;
                }
            };
        }

        custom_keys
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use std::collections::HashSet;
    use std::sync::Mutex;
    use std::time::Duration;

    type CallLog = Arc<Mutex<Vec<&'static str>>>;

    struct MockLimiter {
        custom_keys: HashSet<String>,
        check_limit_result: EvalResult,
        check_custom_limit_result: EvalResult,
        calls: CallLog,
    }

    impl MockLimiter {
        fn new(
            custom_keys: HashSet<String>,
            check_limit_result: EvalResult,
            check_custom_limit_result: EvalResult,
        ) -> (Self, CallLog) {
            let calls: CallLog = Arc::new(Mutex::new(Vec::new()));
            let mock = Self {
                custom_keys,
                check_limit_result,
                check_custom_limit_result,
                calls: calls.clone(),
            };
            (mock, calls)
        }
    }

    #[async_trait]
    impl CommonGlobalRateLimiter for MockLimiter {
        async fn check_limit(
            &self,
            _key: &str,
            _count: u64,
            _timestamp: Option<DateTime<Utc>>,
        ) -> EvalResult {
            self.calls.lock().unwrap().push("check_limit");
            self.check_limit_result.clone()
        }

        async fn check_custom_limit(
            &self,
            _key: &str,
            _count: u64,
            _timestamp: Option<DateTime<Utc>>,
        ) -> EvalResult {
            self.calls.lock().unwrap().push("check_custom_limit");
            self.check_custom_limit_result.clone()
        }

        fn is_custom_key(&self, key: &str) -> bool {
            self.calls.lock().unwrap().push("is_custom_key");
            self.custom_keys.contains(key)
        }

        fn shutdown(&mut self) {}
    }

    fn make_limited_response(is_custom: bool) -> EvalResult {
        EvalResult::Limited(GlobalRateLimitResponse {
            key: "test".to_string(),
            current_count: 100.0,
            threshold: 10,
            window_interval: Duration::from_secs(60),
            sync_interval: Duration::from_secs(15),
            is_custom_limited: is_custom,
        })
    }

    #[tokio::test]
    async fn test_is_limited_routes_to_global_for_unknown_key() {
        let (mock, calls) = MockLimiter::new(
            HashSet::new(),
            make_limited_response(false),
            EvalResult::NotApplicable,
        );
        let wrapper = GlobalRateLimiter::new_with(mock);

        let result = wrapper.is_limited("unknown_key", 1).await;

        assert!(result.is_some());
        assert!(!result.unwrap().is_custom_limited);
        assert_eq!(*calls.lock().unwrap(), vec!["is_custom_key", "check_limit"]);
    }

    #[tokio::test]
    async fn test_is_limited_routes_to_custom_for_registered_key() {
        let (mock, calls) = MockLimiter::new(
            HashSet::from(["registered".to_string()]),
            EvalResult::Allowed,
            make_limited_response(true),
        );
        let wrapper = GlobalRateLimiter::new_with(mock);

        let result = wrapper.is_limited("registered", 1).await;

        assert!(result.is_some());
        assert!(result.unwrap().is_custom_limited);
        assert_eq!(
            *calls.lock().unwrap(),
            vec!["is_custom_key", "check_custom_limit"]
        );
    }

    #[tokio::test]
    async fn test_is_limited_custom_key_allowed_does_not_fall_through_to_global() {
        let (mock, calls) = MockLimiter::new(
            HashSet::from(["custom".to_string()]),
            EvalResult::Allowed,
            EvalResult::Allowed,
        );
        let wrapper = GlobalRateLimiter::new_with(mock);

        let result = wrapper.is_limited("custom", 1).await;

        assert!(result.is_none());
        assert_eq!(
            *calls.lock().unwrap(),
            vec!["is_custom_key", "check_custom_limit"],
            "must NOT call check_limit when key is registered as custom"
        );
    }

    #[test]
    fn test_global_rate_limit_key_to_cache_key() {
        let cases: Vec<(GlobalRateLimitKey, &str, bool)> = vec![
            (GlobalRateLimitKey::Token("abc"), "abc", true),
            (GlobalRateLimitKey::Token(""), "", true),
            (
                GlobalRateLimitKey::TokenDistinctId("abc", "xyz"),
                "abc:xyz",
                false,
            ),
            (
                GlobalRateLimitKey::TokenDistinctId("abc", ""),
                "abc:",
                false,
            ),
        ];

        for (key, expected, expect_borrowed) in cases {
            let result = key.to_cache_key();
            assert_eq!(&*result, expected, "key={expected}");
            assert_eq!(
                matches!(result, Cow::Borrowed(_)),
                expect_borrowed,
                "key={expected}: expected borrowed={expect_borrowed}"
            );
        }
    }

    #[test]
    fn test_truncate_str() {
        let short = "hello";
        let exactly_128 = "a".repeat(128);
        let over_128 = "b".repeat(200);
        let truncated_128 = "b".repeat(128);
        // Multi-byte: é is 2 bytes in UTF-8
        let multibyte_at_boundary = format!("{}{}", "x".repeat(127), "é");

        let cases: Vec<(&str, usize, &str)> = vec![
            ("", 128, ""),
            (short, 128, short),
            (&exactly_128, 128, &exactly_128),
            (&over_128, 128, &truncated_128),
            (&multibyte_at_boundary, 128, &multibyte_at_boundary),
        ];

        for (input, max, expected) in &cases {
            let result = truncate_str(input, *max);
            assert_eq!(
                result,
                *expected,
                "truncate_str({:?}, {max}) = {:?}, expected {:?}",
                &input[..input.len().min(20)],
                result,
                expected
            );
        }
    }

    #[test]
    fn test_token_distinct_id_cache_key_truncates_long_distinct_id() {
        let token = "phc_abc";
        let long_id = "d".repeat(300);
        let key = GlobalRateLimitKey::TokenDistinctId(token, &long_id);
        let result = key.to_cache_key();

        let expected = format!("{token}:{}", &"d".repeat(MAX_DISTINCT_ID_CHARS));
        assert_eq!(&*result, &expected);
        assert_eq!(
            result.len(),
            token.len() + 1 + MAX_DISTINCT_ID_CHARS,
            "cache key should be token + ':' + 128 chars"
        );
    }

    #[test]
    fn test_token_distinct_id_cache_key_preserves_short_distinct_id() {
        let key = GlobalRateLimitKey::TokenDistinctId("tok", "short");
        assert_eq!(&*key.to_cache_key(), "tok:short");
    }

    #[test]
    fn test_token_distinct_id_truncation_utf8_safe() {
        // 127 ASCII chars + a 2-byte UTF-8 char = 128 chars, 129 bytes
        let prefix = "x".repeat(127);
        let distinct_id = format!("{}é", prefix);
        assert_eq!(distinct_id.chars().count(), 128);

        let key = GlobalRateLimitKey::TokenDistinctId("t", &distinct_id);
        let result = key.to_cache_key();
        // Should keep all 128 chars (not split the é)
        assert_eq!(&*result, &format!("t:{distinct_id}"));

        // Now 128 ASCII + é = 129 chars, should truncate to 128
        let prefix_129 = "x".repeat(128);
        let distinct_id_129 = format!("{}é", prefix_129);
        assert_eq!(distinct_id_129.chars().count(), 129);

        let key2 = GlobalRateLimitKey::TokenDistinctId("t", &distinct_id_129);
        let result2 = key2.to_cache_key();
        assert_eq!(&*result2, &format!("t:{prefix_129}"));
    }
}
