//! The consume loop.

use std::time::Duration;

use common_kafka::config::KafkaConfig;
use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::message::{Headers, Message as _};
use rdkafka::ClientConfig;

use crate::process::{read, sampled};

pub fn create_consumer(
    kafka: &KafkaConfig,
    group: &str,
    offset_reset: &str,
    topic: &str,
) -> Result<StreamConsumer, rdkafka::error::KafkaError> {
    let mut config = ClientConfig::new();
    config
        .set("bootstrap.servers", &kafka.kafka_hosts)
        .set("group.id", group)
        .set("auto.offset.reset", offset_reset)
        .set("enable.auto.offset.store", "false")
        .set("partition.assignment.strategy", "cooperative-sticky");
    if kafka.kafka_tls {
        config
            .set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    }
    if !kafka.kafka_client_rack.is_empty() {
        config.set("client.rack", &kafka.kafka_client_rack);
    }
    let consumer: StreamConsumer = config.create()?;
    consumer.subscribe(&[topic])?;
    Ok(consumer)
}

fn header<'m>(message: &'m impl rdkafka::Message, name: &str) -> Option<&'m str> {
    message
        .headers()?
        .iter()
        .find(|h| h.key == name)
        .and_then(|h| h.value)
        .and_then(|v| std::str::from_utf8(v).ok())
}

/// Reads sampled messages and counts what they hold. Offsets are stored once a message is handled.
pub async fn run(consumer: StreamConsumer, percentage: f64, handle: Handle) {
    let shutdown = handle.shutdown_signal();
    tokio::pin!(shutdown);
    loop {
        let message = tokio::select! {
            _ = &mut shutdown => break,
            message = consumer.recv() => message,
        };
        handle.report_healthy();
        let message = match message {
            Ok(message) => message,
            Err(error) => {
                tracing::warn!(%error, "kafka receive failed");
                counter!("replay_recorder_v4_kafka_errors_total").increment(1);
                tokio::time::sleep(Duration::from_millis(100)).await;
                continue;
            }
        };
        let outcome = sampled(message.key(), percentage).and_then(|()| {
            read(
                message.payload().unwrap_or_default(),
                header(&message, "content-encoding"),
            )
        });
        match outcome {
            Ok(read) => {
                counter!("replay_recorder_v4_messages_total", "outcome" => "read").increment(1);
                counter!("replay_recorder_v4_events_total").increment(read.events.len() as u64);
            }
            Err(skip) => counter!("replay_recorder_v4_messages_total", "outcome" => skip.as_str())
                .increment(1),
        }
        if let Err(error) = consumer.store_offset_from_message(&message) {
            tracing::warn!(%error, "storing an offset failed");
        }
    }
}
