use std::{
    future::Future,
    sync::{Arc, OnceLock},
    time::Duration,
};

use tokio::sync::Semaphore;

use common_redis::{Client, CompressionConfig, CustomRedisError, RedisClient, RedisValueFormat};
use tracing::warn;

use crate::modes::processing::redis_heal::{is_connection_error, HealGate};

const SHADOW_DEADLINE: Duration = Duration::from_millis(200);
const MAX_IN_FLIGHT_SHADOW_WRITES: usize = 128;
static SHADOW_PERMITS: OnceLock<Arc<Semaphore>> = OnceLock::new();
static SHADOW_HEAL_GATE: OnceLock<HealGate> = OnceLock::new();

pub async fn connect(
    url: Option<&str>,
    primary_urls: &[&str],
    format: RedisValueFormat,
    response_timeout_ms: u64,
    connection_timeout_ms: u64,
) -> Option<Arc<RedisClient>> {
    let url = url.filter(|url| !url.trim().is_empty())?;
    if primary_urls.contains(&url) {
        metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => "connect", "outcome" => "same_endpoint").increment(1);
        warn!("shadow Redis URL matches a primary Redis URL; shadow writes disabled");
        return None;
    }
    match RedisClient::with_config(
        url.to_string(),
        CompressionConfig::disabled(),
        format,
        Some(Duration::from_millis(response_timeout_ms.max(1).min(200))),
        Some(Duration::from_millis(
            connection_timeout_ms.max(1).min(1000),
        )),
    )
    .await
    {
        Ok(client) => {
            metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => "connect", "outcome" => "ok").increment(1);
            Some(Arc::new(client))
        }
        Err(error) => {
            metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => "connect", "outcome" => "error").increment(1);
            warn!(%error, "shadow Redis connection unavailable; primary remains active");
            None
        }
    }
}

pub fn submit<T: Send + 'static>(
    operation: &'static str,
    write: impl Future<Output = Result<T, CustomRedisError>> + Send + 'static,
    heal: impl Future<Output = ()> + Send + 'static,
) {
    let permits =
        SHADOW_PERMITS.get_or_init(|| Arc::new(Semaphore::new(MAX_IN_FLIGHT_SHADOW_WRITES)));
    submit_with_permits(permits, operation, write, heal);
}

fn submit_with_permits<T: Send + 'static>(
    permits: &Arc<Semaphore>,
    operation: &'static str,
    write: impl Future<Output = Result<T, CustomRedisError>> + Send + 'static,
    heal: impl Future<Output = ()> + Send + 'static,
) {
    let Ok(permit) = permits.clone().try_acquire_owned() else {
        metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => operation, "outcome" => "dropped").increment(1);
        return;
    };
    tokio::spawn(async move {
        let _permit = permit;
        match tokio::time::timeout(SHADOW_DEADLINE, write).await {
            Ok(Ok(_)) => metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => operation, "outcome" => "ok").increment(1),
            Ok(Err(error)) => {
                metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => operation, "outcome" => "error").increment(1);
                warn!(%error, operation, "shadow Redis write failed");
                if is_connection_error(&error) {
                    SHADOW_HEAL_GATE.get_or_init(HealGate::new).spawn_heal(heal);
                }
            }
            Err(_) => {
                metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => operation, "outcome" => "timeout").increment(1);
                warn!(operation, "shadow Redis write timed out");
            }
        }
    });
}

pub fn set_bytes(
    shadow: Option<&Arc<dyn Client + Send + Sync>>,
    key: String,
    payload: Vec<u8>,
    ttl_seconds: u64,
) {
    if let Some(shadow) = shadow {
        let shadow = shadow.clone();
        let healing = shadow.clone();
        submit(
            "event_properties",
            async move { shadow.set_bytes(key, payload, Some(ttl_seconds)).await },
            async move { healing.heal().await },
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use metrics_util::debugging::DebuggingRecorder;

    #[tokio::test]
    async fn exact_primary_url_cannot_be_shadowed() {
        let shadow = connect(
            Some("redis://localhost:6379/"),
            &["redis://localhost:6379/"],
            RedisValueFormat::Utf8,
            100,
            100,
        )
        .await;
        assert!(shadow.is_none());
    }

    #[test]
    fn saturated_shadow_capacity_records_dropped_write() {
        let recorder = DebuggingRecorder::new();
        metrics::with_local_recorder(&recorder, || {
            submit_with_permits(
                &Arc::new(Semaphore::new(0)),
                "issue_buckets",
                async { Ok::<(), CustomRedisError>(()) },
                async {},
            );
        });
        let snapshot = recorder.snapshotter().snapshot().into_vec();
        assert!(snapshot.iter().any(|(key, _, _, _)| {
            key.key().name() == "cymbal_shadow_redis_operations_total"
                && key
                    .key()
                    .labels()
                    .any(|label| label.key() == "outcome" && label.value() == "dropped")
        }));
    }
}
