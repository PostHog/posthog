use crate::config::KafkaConfig;

use health::HealthHandle;
use rdkafka::error::KafkaError;
use rdkafka::producer::FutureProducer;
use rdkafka::ClientConfig;
use tracing::debug;

pub struct KafkaContext {
    liveness: HealthHandle,
}

impl rdkafka::ClientContext for KafkaContext {
    fn stats(&self, _: rdkafka::Statistics) {
        // Signal liveness, as the main rdkafka loop is running and calling us
        self.liveness.report_healthy_blocking();

        // TODO: Take stats recording pieces that we want from `capture-rs`.
    }
}

pub async fn create_kafka_producer(
    config: &KafkaConfig,
    liveness: HealthHandle,
) -> Result<FutureProducer<KafkaContext>, KafkaError> {
    let mut client_config = ClientConfig::new();
    client_config
        .set("bootstrap.servers", &config.kafka_hosts)
        .set("statistics.interval.ms", "10000")
        .set("linger.ms", config.kafka_producer_linger_ms.to_string())
        .set(
            "message.timeout.ms",
            config.kafka_message_timeout_ms.to_string(),
        )
        .set(
            "compression.codec",
            config.kafka_compression_codec.to_owned(),
        )
        .set(
            "queue.buffering.max.kbytes",
            (config.kafka_producer_queue_mib * 1024).to_string(),
        );

    if config.kafka_tls {
        client_config
            .set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    };

    debug!("rdkafka configuration: {:?}", client_config);
    let api: FutureProducer<KafkaContext> =
        client_config.create_with_context(KafkaContext { liveness })?;

    // TODO: ping the kafka brokers to confirm configuration is OK (copy capture)

    Ok(api)
}
