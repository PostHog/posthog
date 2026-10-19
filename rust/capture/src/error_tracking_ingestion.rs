//! Projects that turned off exception ingestion in their error tracking settings.
//!
//! The error tracking product writes the API tokens of those projects to a Redis sorted set.
//! A background task copies the set into memory, so the request path never calls Redis.
//! When a refresh fails, the last loaded set stays in place: a project that turned ingestion
//! off keeps its exceptions dropped through a Redis outage. A capture pod that cannot load
//! the set at startup drops nothing until a refresh succeeds.

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use arc_swap::ArcSwap;
use common_redis::{Client, CustomRedisError};
use common_types::HasEventName;
use metrics::gauge;
use tracing::warn;

use crate::prometheus::report_dropped_events;

/// Keep in sync with `products/error_tracking/backend/logic/ingestion_switch.py`.
pub const INGESTION_DISABLED_TOKENS_KEY: &str = "@posthog/error-tracking/ingestion-disabled-tokens";

const EXCEPTION_EVENT: &str = "$exception";
const DROP_CAUSE: &str = "error_tracking_ingestion_disabled";
const LOADED_TOKENS_GAUGE: &str = "capture_error_tracking_ingestion_disabled_tokens";

pub struct ErrorTrackingIngestionSwitch {
    disabled_tokens: Arc<ArcSwap<HashSet<String>>>,
}

impl ErrorTrackingIngestionSwitch {
    pub async fn new(
        redis: Arc<dyn Client + Send + Sync>,
        redis_key_prefix: Option<String>,
        refresh_interval: Duration,
    ) -> Self {
        let key = format!(
            "{}{INGESTION_DISABLED_TOKENS_KEY}",
            redis_key_prefix.unwrap_or_default()
        );
        let disabled_tokens = Arc::new(ArcSwap::from_pointee(HashSet::new()));
        refresh(redis.as_ref(), &key, &disabled_tokens).await;

        let background_tokens = disabled_tokens.clone();
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(refresh_interval);
            // The first tick completes at once, and the set is already loaded.
            ticker.tick().await;
            loop {
                ticker.tick().await;
                refresh(redis.as_ref(), &key, &background_tokens).await;
            }
        });

        Self { disabled_tokens }
    }

    pub fn is_disabled(&self, token: &str) -> bool {
        self.disabled_tokens.load().contains(token)
    }

    pub fn drop_exceptions<T: HasEventName>(&self, token: &str, events: &mut Vec<T>) {
        if !self.is_disabled(token) {
            return;
        }
        let before = events.len();
        events.retain(|event| event.event_name() != EXCEPTION_EVENT);
        let dropped = (before - events.len()) as u64;
        if dropped > 0 {
            report_dropped_events(DROP_CAUSE, dropped);
        }
    }
}

async fn refresh(
    redis: &(dyn Client + Send + Sync),
    key: &str,
    disabled_tokens: &ArcSwap<HashSet<String>>,
) {
    match load(redis, key).await {
        Ok(tokens) => {
            gauge!(LOADED_TOKENS_GAUGE).set(tokens.len() as f64);
            disabled_tokens.store(Arc::new(tokens));
        }
        Err(error) => {
            warn!(
                error = ?error,
                "failed to refresh the error tracking ingestion switch, keeping the last loaded tokens"
            );
        }
    }
}

async fn load(
    redis: &(dyn Client + Send + Sync),
    key: &str,
) -> Result<HashSet<String>, CustomRedisError> {
    let tokens = redis
        .zrangebyscore(key.to_string(), "-inf".to_string(), "+inf".to_string())
        .await?;
    Ok(tokens.into_iter().collect())
}

#[cfg(test)]
mod tests {
    use common_redis::MockRedisClient;

    use super::*;

    struct NamedEvent(&'static str);

    impl HasEventName for NamedEvent {
        fn event_name(&self) -> &str {
            self.0
        }
    }

    async fn switch_with(tokens: Vec<&str>) -> ErrorTrackingIngestionSwitch {
        let redis = MockRedisClient::new().zrangebyscore_ret(
            INGESTION_DISABLED_TOKENS_KEY,
            tokens.into_iter().map(String::from).collect(),
        );
        ErrorTrackingIngestionSwitch::new(Arc::new(redis), None, Duration::from_secs(3600)).await
    }

    #[tokio::test]
    async fn drops_only_the_exceptions_of_a_disabled_project() {
        let switch = switch_with(vec!["phc_disabled"]).await;

        let mut disabled = vec![NamedEvent("$exception"), NamedEvent("$pageview")];
        switch.drop_exceptions("phc_disabled", &mut disabled);
        let mut enabled = vec![NamedEvent("$exception"), NamedEvent("$pageview")];
        switch.drop_exceptions("phc_enabled", &mut enabled);

        let names = |events: &[NamedEvent]| events.iter().map(|e| e.0).collect::<Vec<_>>();
        assert_eq!(names(&disabled), vec!["$pageview"]);
        assert_eq!(names(&enabled), vec!["$exception", "$pageview"]);
    }

    #[tokio::test]
    async fn starts_empty_when_the_set_cannot_be_loaded() {
        let redis = MockRedisClient::new();
        let switch =
            ErrorTrackingIngestionSwitch::new(Arc::new(redis), None, Duration::from_secs(3600))
                .await;

        assert!(!switch.is_disabled("phc_disabled"));
    }
}
