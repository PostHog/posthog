use rdkafka::config::ClientConfig;
use rdkafka::consumer::BaseConsumer;
use rdkafka::error::KafkaResult;

use crate::config::Config;

/// Group id used by message-fetching consumers. Distinct from any real
/// ingestion group so inspection can never touch production offsets.
pub const INSPECTOR_GROUP_ID: &str = "ingestion-control-plane-inspector";

fn base_client_config(config: &Config) -> ClientConfig {
    let mut cfg = ClientConfig::new();
    cfg.set("bootstrap.servers", &config.kafka_hosts);
    // Certificate verification is disabled against MSK across the whole
    // workspace (see common-kafka and ingestion-consumer's kafka_config);
    // stay consistent with the fleet.
    if config.kafka_tls {
        cfg.set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    }
    if let Some(rack) = config
        .kafka_client_rack
        .as_deref()
        .filter(|r| !r.is_empty())
    {
        cfg.set("client.rack", rack);
    }
    cfg
}

/// Lightweight client for metadata and watermark queries: no group id,
/// never subscribes or polls.
pub fn metadata_consumer(config: &Config) -> KafkaResult<BaseConsumer> {
    base_client_config(config).create()
}

/// Client for reading a consumer group's committed offsets. Auto commit and
/// auto offset store are disabled so instantiating it with the real group id
/// can never mutate that group's stored offsets.
pub fn group_offsets_consumer(config: &Config, group: &str) -> KafkaResult<BaseConsumer> {
    let mut cfg = base_client_config(config);
    cfg.set("group.id", group)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false");
    cfg.create()
}

/// Client for fetching message ranges during an analysis. Uses the inspector
/// group id and bounds librdkafka's prefetch queue so a partition of large
/// messages doesn't balloon memory.
pub fn fetch_consumer(config: &Config) -> KafkaResult<BaseConsumer> {
    let mut cfg = base_client_config(config);
    cfg.set("group.id", INSPECTOR_GROUP_ID)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .set("queued.max.messages.kbytes", "65536")
        .set("fetch.message.max.bytes", "10485760");
    cfg.create()
}
