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
use tracing::error;

#[cfg(test)]
use chrono::DateTime;

pub struct GlobalRateLimiter {
    limiter: Box<dyn CommonGlobalRateLimiter>,
}

impl GlobalRateLimiter {
    pub fn new(
        config: &Config,
        redis_instances: Vec<Arc<dyn Client + Send + Sync>>,
    ) -> anyhow::Result<Self> {
        let redis_prefix = format!(
            "@posthog/capture/global_rate_limiter/{}",
            config.capture_mode.as_tag()
        );

        let grl_config = GlobalRateLimiterConfig {
            global_threshold: config.global_rate_limit_threshold,
            window_interval: Duration::from_secs(config.global_rate_limit_window_interval_secs),
            bucket_interval: Duration::from_secs(config.global_rate_limit_bucket_interval_secs),
            redis_key_prefix: redis_prefix,
            custom_keys: Self::format_custom_keys(config.global_rate_limit_overrides_csv.as_ref()),
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
        let now = Utc::now();
        EvalResult::Limited(GlobalRateLimitResponse {
            key: "test".to_string(),
            current_count: 100,
            threshold: 10,
            window_start: now - chrono::Duration::seconds(60),
            window_end: now,
            window_interval: Duration::from_secs(60),
            update_interval: Duration::from_secs(10),
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
}
