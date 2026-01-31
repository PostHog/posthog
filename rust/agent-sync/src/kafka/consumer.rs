use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::ClientConfig;
use std::sync::Arc;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

use crate::error::{AppError, Result};
use crate::streaming::FanoutRouter;
use crate::types::AgentEvent;

const METRIC_KAFKA_DESERIALIZE_ERRORS: &str = "agent_sync_kafka_deserialize_errors_total";

pub fn create_consumer(brokers: &str, group_id: &str, topic: &str) -> Result<StreamConsumer> {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", brokers)
        .set("group.id", group_id)
        .set("enable.auto.commit", "true")
        .set("auto.offset.reset", "latest")
        .set("session.timeout.ms", "10000")
        .create()
        .map_err(|e| AppError::Kafka(e.to_string()))?;

    consumer
        .subscribe(&[topic])
        .map_err(|e| AppError::Kafka(e.to_string()))?;

    Ok(consumer)
}

pub async fn run_consumer(
    consumer: StreamConsumer,
    router: Arc<FanoutRouter>,
    shutdown: CancellationToken,
) {
    use futures_util::StreamExt;

    let mut stream = consumer.stream();

    loop {
        tokio::select! {
            _ = shutdown.cancelled() => {
                tracing::info!("Kafka consumer shutting down");
                break;
            }
            result = stream.next() => {
                let Some(result) = result else {
                    tokio::time::sleep(Duration::from_millis(100)).await;
                    continue;
                };

                let msg = match result {
                    Ok(m) => m,
                    Err(e) => {
                        tracing::error!(error = %e, "Kafka consumer error");
                        tokio::time::sleep(Duration::from_millis(100)).await;
                        continue;
                    }
                };

                let Some(key_bytes) = msg.key() else {
                    continue;
                };

                let Ok(key) = std::str::from_utf8(key_bytes) else {
                    continue;
                };

                let run_id = key.split(':').nth(1).unwrap_or("");

                if !router.has_subscribers(run_id) {
                    continue;
                }

                let Some(payload) = msg.payload() else {
                    continue;
                };

                match serde_json::from_slice::<AgentEvent>(payload) {
                    Ok(event) => {
                        router.route(event).await;
                    }
                    Err(e) => {
                        tracing::warn!(error = %e, run_id = %run_id, "Failed to deserialize event");
                        let labels = vec![("run_id".to_string(), run_id.to_string())];
                        common_metrics::inc(METRIC_KAFKA_DESERIALIZE_ERRORS, &labels, 1);
                    }
                }
            }
        }
    }
}
