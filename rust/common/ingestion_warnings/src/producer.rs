//! Fire-and-forget Kafka producer for ingestion warnings.
//!
//! Dedicated `FutureProducer` with its own `ClientConfig` — never shared with
//! event sinks — enqueuing via `send_result()` and dropping the returned
//! `DeliveryFuture` (the personhog-writer pattern). Delivery is never awaited:
//! a full queue or broker outage costs the caller one synchronous enqueue
//! attempt and the warning, nothing else. Do not use `common_kafka::send_*`
//! helpers here — those await delivery futures.

use std::time::Duration;

use rdkafka::error::KafkaError;
use rdkafka::message::OwnedHeaders;
use rdkafka::producer::{DeliveryFuture, FutureProducer, FutureRecord, Producer};
use rdkafka::ClientConfig;

/// Connection and tuning knobs for the warnings producer. Callers map these
/// from their own env config namespace (e.g. `CAPTURE_INGESTION_WARNINGS_*`).
#[derive(Debug, Clone)]
pub struct WarningProducerConfig {
    pub kafka_hosts: String,
    pub kafka_topic: String,
    pub kafka_tls: bool,
    /// Time before rdkafka gives up delivering a queued message.
    pub message_timeout_ms: u32,
    /// Bound on the in-memory queue; `QueueFull` drops the warning, never blocks.
    pub queue_max_messages: u32,
    /// Broker acks ("0", "1", or "all").
    pub acks: String,
    pub linger_ms: u32,
}

impl Default for WarningProducerConfig {
    fn default() -> Self {
        Self {
            kafka_hosts: String::new(),
            kafka_topic: "client_ingestion_warning".to_string(),
            kafka_tls: false,
            message_timeout_ms: 5000,
            queue_max_messages: 10_000,
            acks: "1".to_string(),
            linger_ms: 100,
        }
    }
}

/// Thin fire-and-forget wrapper over a dedicated `FutureProducer`.
pub struct WarningProducer {
    producer: FutureProducer,
    topic: String,
}

impl WarningProducer {
    pub fn new(config: &WarningProducerConfig) -> Result<Self, KafkaError> {
        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &config.kafka_hosts)
            .set("message.timeout.ms", config.message_timeout_ms.to_string())
            .set(
                "queue.buffering.max.messages",
                config.queue_max_messages.to_string(),
            )
            .set("acks", &config.acks)
            .set("linger.ms", config.linger_ms.to_string())
            // Warnings are best-effort: never retry, drop on timeout instead.
            .set("retries", "0");

        if config.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }

        let producer: FutureProducer = client_config.create()?;
        Ok(Self {
            producer,
            topic: config.kafka_topic.clone(),
        })
    }

    /// Enqueue a message and return immediately with the delivery future.
    /// `Err` means the message never entered the queue (e.g. `QueueFull`).
    /// Callers may await the returned future off the hot path to observe
    /// delivery outcomes, or drop it — enqueue is complete either way.
    pub fn send(
        &self,
        key: &str,
        headers: OwnedHeaders,
        payload: &[u8],
    ) -> Result<DeliveryFuture, KafkaError> {
        let record = FutureRecord::to(&self.topic)
            .key(key)
            .headers(headers)
            .payload(payload);
        match self.producer.send_result(record) {
            Ok(delivery_future) => Ok(delivery_future),
            Err((err, _record)) => Err(err),
        }
    }

    /// Drain the internal queue, waiting up to `timeout`. Advisory: called
    /// only at graceful shutdown; errors are ignored.
    pub fn flush(&self, timeout: Duration) {
        drop(self.producer.flush(timeout));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rdkafka::types::RDKafkaErrorCode;

    fn unreachable_config(queue_max_messages: u32) -> WarningProducerConfig {
        WarningProducerConfig {
            // Reserved TEST-NET-1 address: connection attempts fail fast and
            // messages stay queued, without touching any real broker.
            kafka_hosts: "192.0.2.1:9092".to_string(),
            queue_max_messages,
            // rdkafka requires message.timeout.ms > linger.ms at client creation.
            message_timeout_ms: 500,
            linger_ms: 5,
            ..WarningProducerConfig::default()
        }
    }

    #[test]
    fn send_is_non_blocking_with_unreachable_broker() {
        let producer = WarningProducer::new(&unreachable_config(10)).unwrap();
        let start = std::time::Instant::now();
        drop(
            producer
                .send("tok", OwnedHeaders::new(), b"{}")
                .expect("enqueue must succeed"),
        );
        assert!(
            start.elapsed() < Duration::from_millis(500),
            "send must never block on broker availability"
        );
    }

    #[test]
    fn queue_full_is_reported_not_blocked_on() {
        // rdkafka enforces a floor on the queue bound; fill whatever the
        // effective bound is and assert the overflow attempt fails fast with
        // QueueFull instead of blocking.
        let producer = WarningProducer::new(&unreachable_config(1)).unwrap();
        let start = std::time::Instant::now();
        let mut saw_queue_full = false;
        for i in 0..100_000 {
            if let Err(err) = producer.send(
                "tok",
                OwnedHeaders::new(),
                format!("{{\"i\":{i}}}").as_bytes(),
            ) {
                assert!(
                    matches!(
                        err,
                        KafkaError::MessageProduction(RDKafkaErrorCode::QueueFull)
                    ),
                    "unexpected enqueue error: {err}"
                );
                saw_queue_full = true;
                break;
            }
        }
        assert!(saw_queue_full, "bounded queue must eventually report full");
        assert!(
            start.elapsed() < Duration::from_secs(5),
            "queue-full handling must not block"
        );
    }
}
