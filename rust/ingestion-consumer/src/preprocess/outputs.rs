//! Wiring the preprocess pipeline's redirect/DLQ outputs to real Kafka topics.
//!
//! Builds a `common-pipelines` [`OutputRegistry`] backed by a `common-kafka`
//! `FutureProducer`. Only constructed in enforce mode when at least one output
//! topic is configured; otherwise verdicts fail open to dispatch.

use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use common_pipelines::{EffectProducer, OutputRegistry, RdKafkaEffectProducer};
use envconfig::Envconfig;

use crate::config::Config;

use super::context::PreprocessOutput;

/// Build the output registry (overflow topic + DLQ) backed by a Kafka producer.
/// Returns `None` when neither the DLQ nor overflow topic is configured, so the
/// caller leaves verdicts to fail open. Fails startup if a configured topic
/// cannot be registered (the design's `outputs.checkTopics()` analog).
pub async fn build_output_registry(
    config: &Config,
    liveness: lifecycle::Handle,
) -> anyhow::Result<Option<OutputRegistry<PreprocessOutput>>> {
    let has_dlq = !config.ingestion_output_dlq_topic.is_empty();
    let has_overflow = !config.ingestion_output_overflow_topic.is_empty();
    if !has_dlq && !has_overflow {
        return Ok(None);
    }

    // Reuse the consumer's liveness handle as the producer's liveness reporter.
    // (POC: a dedicated producer component would isolate liveness accounting.)
    let kafka_config = common_kafka::config::KafkaConfig::init_from_env()
        .context("loading KafkaConfig for the preprocess producer")?;
    let producer = common_kafka::kafka_producer::create_kafka_producer(&kafka_config, liveness)
        .await
        .context("creating the preprocess Kafka producer")?;
    let effect_producer: Arc<dyn EffectProducer> = Arc::new(RdKafkaEffectProducer::new(
        Arc::new(producer),
        Duration::from_millis(config.http_timeout_ms),
    ));

    let mut registry = OutputRegistry::new();
    if has_overflow {
        registry.register(
            PreprocessOutput::Overflow,
            &config.ingestion_output_overflow_topic,
            Arc::clone(&effect_producer),
        );
        registry
            .check(&[PreprocessOutput::Overflow])
            .context("preprocess overflow output topic check")?;
    }
    if has_dlq {
        registry.with_dlq(&config.ingestion_output_dlq_topic, effect_producer);
    }

    Ok(Some(registry))
}
