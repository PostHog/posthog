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

    /// Evaluate key for global rate limit. Response with metadata is returned if limited.
    pub async fn is_limited(&self, key: &str, count: u64) -> Option<GlobalRateLimitResponse> {
        // call is instrumented internally
        match self.limiter.check_limit(key, count, Some(Utc::now())).await {
            EvalResult::Limited(response) => Some(response),
            _ => None, // Allowed, NotApplicable, FailOpen all treated as "not limited"
        }
    }

    /// Evaluate a custom key candidate. If it was registered when the limiter was
    /// created, evaluate the key against the custom limit. Otherwise, return None.
    pub async fn is_custom_key_limited(
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
            _ => None, // Allowed, NotApplicable, FailOpen all treated as "not limited"
        }
    }

    // trigger shutdown and stop pushing updates to global cache
    pub fn shutdown(&mut self) {
        self.limiter.shutdown();
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
