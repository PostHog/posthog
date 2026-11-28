use std::sync::Arc;
use std::time::{Duration, Instant};

use common_redis::Client;
use metrics::{counter, gauge, histogram};
use tokio::task::JoinHandle;

use crate::redis::{limiter_key, QuotaResource, RedisLimiter, ServiceName};

/// Reads a limiter's set from a second cache and reports what it finds. It shares no state with
/// any limiter, so what it reads never changes a limit.
pub fn spawn_observation(
    interval: Duration,
    redis: Arc<dyn Client + Send + Sync>,
    limiter_cache_key: String,
    redis_key_prefix: Option<String>,
    resource: QuotaResource,
    service_name: ServiceName,
) -> JoinHandle<()> {
    let key = limiter_key(redis_key_prefix, &limiter_cache_key, &resource);
    let cache_key: Arc<str> = Arc::from(key.as_str());
    let service_name = service_name.as_string();

    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(interval);
        loop {
            ticker.tick().await;
            let started = Instant::now();
            match RedisLimiter::fetch_limited(&redis, &key).await {
                Ok(set) => {
                    histogram!(
                        format!("{service_name}_billing_limits_observe_duration_seconds"),
                        "cache_key" => cache_key.clone(),
                    )
                    .record(started.elapsed().as_secs_f64());
                    gauge!(
                        format!("{service_name}_billing_limits_observed_tokens"),
                        "cache_key" => cache_key.clone(),
                    )
                    .set(set.len() as f64);
                }
                Err(_) => counter!(
                    format!("{service_name}_billing_limits_observe_errors_total"),
                    "cache_key" => cache_key.clone(),
                )
                .increment(1),
            }
        }
    })
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use chrono::Utc;
    use common_redis::MockRedisClient;
    use metrics_util::debugging::{DebugValue, DebuggingRecorder};

    use super::*;
    use crate::redis::QUOTA_LIMITER_CACHE_KEY;

    #[tokio::test(start_paused = true)]
    async fn limiter_and_observer_report_each_key_on_its_own() {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);
        let client: Arc<dyn Client + Send + Sync> =
            Arc::new(MockRedisClient::new().zrangebyscore_ret(
                "@posthog/quota-limits/events",
                vec!["apple".to_string(), "banana".to_string()],
            ));
        let before = Utc::now().timestamp() as f64;

        // The mock holds no set for the exceptions key, so every read of it fails.
        let runners: Vec<JoinHandle<()>> = [QuotaResource::Events, QuotaResource::Exceptions]
            .into_iter()
            .map(|resource| {
                RedisLimiter::new(
                    Duration::from_secs(5),
                    client.clone(),
                    QUOTA_LIMITER_CACHE_KEY.to_string(),
                    None,
                    resource.clone(),
                    ServiceName::Capture,
                )
                .unwrap();
                spawn_observation(
                    Duration::from_secs(5),
                    client.clone(),
                    QUOTA_LIMITER_CACHE_KEY.to_string(),
                    None,
                    resource,
                    ServiceName::Capture,
                )
            })
            .collect();
        // Reads at 0 s, 5 s and 10 s.
        tokio::time::sleep(Duration::from_secs(12)).await;
        let after = Utc::now().timestamp() as f64;
        for runner in &runners {
            runner.abort();
        }

        let metrics: HashMap<(String, String), DebugValue> = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .filter_map(|(key, _, _, value)| {
                let cache_key = key.key().labels().find(|l| l.key() == "cache_key")?;
                let name = key.key().name().to_string();
                Some(((name, cache_key.value().to_string()), value))
            })
            .collect();
        let metric = |name: &str, cache_key: &str| {
            metrics.get(&(
                format!("capture_billing_limits_{name}"),
                cache_key.to_string(),
            ))
        };
        let events = "@posthog/quota-limits/events";
        let exceptions = "@posthog/quota-limits/exceptions";

        assert!(
            matches!(metric("observed_tokens", events), Some(DebugValue::Gauge(size)) if size.into_inner() == 2.0)
        );
        assert_eq!(metric("observed_tokens", exceptions), None);
        assert_eq!(metric("observe_errors_total", events), None);
        assert_eq!(
            metric("observe_errors_total", exceptions),
            Some(&DebugValue::Counter(3))
        );
        assert!(
            matches!(metric("observe_duration_seconds", events), Some(DebugValue::Histogram(reads)) if reads.len() == 3)
        );
        assert_eq!(metric("observe_duration_seconds", exceptions), None);
        assert!(
            matches!(metric("last_success_timestamp_seconds", events), Some(DebugValue::Gauge(timestamp)) if (before..=after).contains(&timestamp.into_inner()))
        );
        assert_eq!(metric("last_success_timestamp_seconds", exceptions), None);
    }
}
