//! `IngestionOutputs` over Kafka: the output registry of `logs/outputs/registry.ts` with the
//! producers of `logs/outputs/producer-registry.ts`. Every send waits for its delivery report,
//! as `KafkaProducerWrapper.produce` awaits the callback.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use futures::future::join_all;
use ingestion_framework::{IngestionOutputs, OutputMessage};
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use rdkafka::util::Timeout;
use rdkafka::ClientConfig;

use crate::pipeline::NamedError;

use super::config::OutputRoute;

/// `KafkaProducerWrapper.PRODUCER_DEFAULTS`. Env values from the producer's config map win.
pub fn producer_client_config(
    overrides: &[(String, String)],
    client_rack: Option<&str>,
) -> ClientConfig {
    let mut config = ClientConfig::new();
    let host = hostname();
    for (k, v) in [
        ("client.id", host.as_str()),
        ("metadata.broker.list", "kafka:9092"),
        ("linger.ms", "20"),
        ("log_level", "4"),
        ("batch.size", "8388608"),
        ("queue.buffering.max.messages", "100000"),
        ("compression.codec", "snappy"),
        ("enable.idempotence", "true"),
        ("metadata.max.age.ms", "30000"),
        ("retry.backoff.ms", "500"),
        ("socket.timeout.ms", "30000"),
        ("max.in.flight.requests.per.connection", "5"),
        ("statistics.interval.ms", "30000"),
    ] {
        config.set(k, v);
    }
    if let Some(rack) = client_rack {
        config.set("client.rack", rack);
    }
    for (k, v) in overrides {
        config.set(k, v);
    }
    config
}

pub fn hostname() -> String {
    std::env::var("HOSTNAME").unwrap_or_else(|_| "logs-ingestion".to_string())
}

/// How a failed produce reaches the pipeline, as `KafkaProducerWrapper.produce` throws it.
/// node-rdkafka sets `isRetriable` only on transactional errors, so no produce error becomes
/// `DependencyUnavailableError` there, and every one except a too-large message quarantines.
pub fn classify_produce_error(error: KafkaError) -> anyhow::Error {
    match error.rdkafka_error_code() {
        Some(RDKafkaErrorCode::MessageSizeTooLarge) => {
            anyhow::Error::new(NamedError::new("MessageSizeTooLarge", error.to_string()))
        }
        _ => anyhow::Error::new(NamedError::new("Error", error.to_string())),
    }
}

struct Route {
    topic: String,
    producer: FutureProducer,
}

pub struct KafkaOutputs {
    routes: HashMap<&'static str, Route>,
    producers: Vec<FutureProducer>,
    queue_timeout: Duration,
}

impl KafkaOutputs {
    /// `producers` maps a producer name to its client. A route that names a missing producer is
    /// a startup error.
    pub fn new(
        routes: &[OutputRoute],
        producers: &HashMap<String, FutureProducer>,
    ) -> anyhow::Result<Self> {
        let mut out = HashMap::new();
        for r in routes {
            let producer = producers
                .get(&r.producer)
                .ok_or_else(|| anyhow::anyhow!("no producer {} for {}", r.producer, r.output))?
                .clone();
            out.insert(
                r.output,
                Route {
                    topic: r.topic.clone(),
                    producer,
                },
            );
        }
        Ok(Self {
            routes: out,
            producers: producers.values().cloned().collect(),
            queue_timeout: Duration::from_secs(10),
        })
    }

    pub fn topic(&self, output: &str) -> Option<&str> {
        self.routes.get(output).map(|r| r.topic.as_str())
    }

    pub fn flush(&self, timeout: Duration) {
        for p in &self.producers {
            if let Err(error) = p.flush(Timeout::After(timeout)) {
                tracing::error!(error = %error, "producer flush failed");
            }
        }
    }

    async fn send(&self, route: &Route, message: &OutputMessage) -> anyhow::Result<()> {
        let mut headers = OwnedHeaders::new_with_capacity(message.headers.len());
        for (k, v) in message.headers.iter() {
            headers = headers.insert(Header {
                key: k,
                value: Some(v.as_bytes()),
            });
        }
        let mut record: FutureRecord<'_, [u8], [u8]> =
            FutureRecord::to(&route.topic).headers(headers);
        if let Some(key) = &message.key {
            record = record.key(key.as_slice());
        }
        if let Some(value) = &message.value {
            record = record.payload(value.as_ref());
        }
        let topic: Arc<str> = Arc::from(route.topic.as_str());
        match route
            .producer
            .send(record, Timeout::After(self.queue_timeout))
            .await
        {
            Ok(_) => {
                metrics::counter!("logs_ingestion_kafka_produced_total", "topic" => topic)
                    .increment(1);
                Ok(())
            }
            Err((error, _)) => {
                tracing::error!(error = %error, topic = %route.topic, "kafka_produce_error");
                metrics::counter!("logs_ingestion_kafka_produce_failed_total", "topic" => topic)
                    .increment(1);
                Err(classify_produce_error(error))
            }
        }
    }
}

#[async_trait]
impl IngestionOutputs for KafkaOutputs {
    async fn produce(&self, output: &str, message: OutputMessage) -> anyhow::Result<()> {
        self.queue_messages(output, vec![message]).await
    }

    async fn queue_messages(
        &self,
        output: &str,
        messages: Vec<OutputMessage>,
    ) -> anyhow::Result<()> {
        let route = self
            .routes
            .get(output)
            .ok_or_else(|| anyhow::anyhow!("Unknown output: {output}"))?;
        let results = join_all(messages.iter().map(|m| self.send(route, m))).await;
        results.into_iter().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pipeline::errors::{error_name, is_dependency_unavailable};

    #[test]
    fn produce_errors_classify_like_the_node_wrapper() {
        let too_large = classify_produce_error(KafkaError::MessageProduction(
            RDKafkaErrorCode::MessageSizeTooLarge,
        ));
        assert_eq!(error_name(&too_large), "MessageSizeTooLarge");
        for code in [
            RDKafkaErrorCode::QueueFull,
            RDKafkaErrorCode::MessageTimedOut,
            RDKafkaErrorCode::TopicAuthorizationFailed,
        ] {
            let error = classify_produce_error(KafkaError::MessageProduction(code));
            assert_eq!(error_name(&error), "Error", "{code:?}");
            assert!(!is_dependency_unavailable(&error), "{code:?}");
        }
    }
}
