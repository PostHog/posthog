use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct KafkaConfig {
    #[envconfig(default = "20")]
    pub kafka_producer_linger_ms: u32, // Maximum time between producer batches during low traffic

    #[envconfig(default = "400")]
    pub kafka_producer_queue_mib: u32, // Size of the in-memory producer queue in mebibytes

    #[envconfig(default = "10000000")]
    pub kafka_producer_queue_messages: u32, // Maximum number of messages in the in-memory producer queue

    #[envconfig(default = "20000")]
    pub kafka_message_timeout_ms: u32, // Time before we stop retrying producing a message: 20 seconds

    #[envconfig(default = "none")]
    pub kafka_compression_codec: String, // none, gzip, snappy, lz4, zstd

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "")]
    pub kafka_client_rack: String,

    #[envconfig(default = "")]
    pub kafka_client_id: String,

    // WarpStream producer tuning — None means "let librdkafka pick its default".
    // Reference: https://docs.warpstream.com/warpstream/kafka/configure-kafka-client/tuning-for-performance
    pub kafka_producer_batch_size: Option<u32>,

    pub kafka_producer_batch_num_messages: Option<u32>,

    pub kafka_producer_enable_idempotence: Option<bool>,

    pub kafka_producer_max_in_flight_requests_per_connection: Option<u32>,

    pub kafka_producer_topic_metadata_refresh_interval_ms: Option<u32>,

    pub kafka_producer_message_max_bytes: Option<u32>,

    pub kafka_producer_sticky_partitioning_linger_ms: Option<u32>,

    // Set to "murmur2_random" to co-partition a keyed topic with Kafka-Java/python-kafka/Node
    // producers; `None` uses librdkafka's CRC32-based default, which routes keys differently.
    pub kafka_producer_partitioner: Option<String>,

    // `None` means "let librdkafka pick its default" (acks=all, effectively unbounded retries
    // within message.timeout.ms) — existing callers are unaffected. Fire-and-forget producers
    // (e.g. best-effort warning emitters) set these explicitly to acks="1"/retries=0 so a slow
    // broker times out and drops instead of retrying.
    pub kafka_producer_acks: Option<String>,

    pub kafka_producer_retries: Option<u32>,
}

// Keep these values in sync with the `#[envconfig(default = ...)]` attributes
// above: `KafkaConfig::default()` must match `init_from_env()` with no env set,
// so callers that build a config with `..Default::default()` get the same base
// as env-driven callers.
impl Default for KafkaConfig {
    fn default() -> Self {
        Self {
            kafka_producer_linger_ms: 20,
            kafka_producer_queue_mib: 400,
            kafka_producer_queue_messages: 10_000_000,
            kafka_message_timeout_ms: 20_000,
            kafka_compression_codec: "none".to_string(),
            kafka_tls: false,
            kafka_hosts: "localhost:9092".to_string(),
            kafka_client_rack: String::new(),
            kafka_client_id: String::new(),
            kafka_producer_batch_size: None,
            kafka_producer_batch_num_messages: None,
            kafka_producer_enable_idempotence: None,
            kafka_producer_max_in_flight_requests_per_connection: None,
            kafka_producer_topic_metadata_refresh_interval_ms: None,
            kafka_producer_message_max_bytes: None,
            kafka_producer_sticky_partitioning_linger_ms: None,
            kafka_producer_partitioner: None,
            kafka_producer_acks: None,
            kafka_producer_retries: None,
        }
    }
}

#[derive(Envconfig, Clone)]
pub struct ConsumerConfig {
    pub kafka_consumer_group: String,
    pub kafka_consumer_topic: String,

    // We default to "earliest" for this, but if you're bringing up a new service, you probably want "latest"
    #[envconfig(default = "earliest")]
    pub kafka_consumer_offset_reset: String, // earliest, latest

    // Note: consumers used in a transactional fashion should disable auto offset commits,
    // as their offsets should be committed via the transactional producer. All consumers
    // disable auto offset /storing/.
    pub kafka_consumer_auto_commit: bool,

    // expose override config for interval (in milliseconds) between
    // Kafka offset commit attempts
    #[envconfig(default = "5000")]
    pub kafka_consumer_auto_commit_interval_ms: i32,

    // Fetch tuning — None means "use librdkafka default" (i.e. don't override).
    // WarpStream reads from object storage and benefits from larger, less frequent fetches.
    pub kafka_consumer_fetch_wait_max_ms: Option<u32>,

    pub kafka_consumer_fetch_min_bytes: Option<u32>,

    pub kafka_consumer_fetch_max_bytes: Option<u32>,

    pub kafka_consumer_max_partition_fetch_bytes: Option<u32>,

    // Consumer group protocol tuning for WarpStream rebalance resilience.
    // Set to a stable pod identity to enable static group membership (avoids
    // rebalances when a pod restarts within the session timeout window).
    pub kafka_consumer_group_instance_id: Option<String>,

    // Override partition assignment strategy, e.g. "cooperative-sticky" for
    // incremental rebalancing instead of the default eager "range" protocol.
    // During migration, use "range,cooperative-sticky" then drop "range".
    pub kafka_consumer_partition_strategy: Option<String>,

    // WarpStream recommends "0" so the kernel auto-tunes TCP buffers.
    pub kafka_consumer_socket_send_buffer_bytes: Option<String>,
    pub kafka_consumer_socket_receive_buffer_bytes: Option<String>,

    // WarpStream recommends 60000 for faster Agent scaling responsiveness.
    pub kafka_consumer_metadata_refresh_interval_ms: Option<u32>,
}

impl ConsumerConfig {
    /// Because the consumer config is so application specific, we
    /// can't set good defaults in the derive macro, so we expose a way
    /// for users to set them here before init'ing their main config struct
    pub fn set_defaults(consumer_group: &str, consumer_topic: &str, auto_commit: bool) {
        if std::env::var("KAFKA_CONSUMER_GROUP").is_err() {
            std::env::set_var("KAFKA_CONSUMER_GROUP", consumer_group);
        };
        if std::env::var("KAFKA_CONSUMER_TOPIC").is_err() {
            std::env::set_var("KAFKA_CONSUMER_TOPIC", consumer_topic);
        };

        if std::env::var("KAFKA_CONSUMER_AUTO_COMMIT").is_err() {
            std::env::set_var("KAFKA_CONSUMER_AUTO_COMMIT", auto_commit.to_string());
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use envconfig::Envconfig;

    use super::KafkaConfig;

    // Guards the two-spot-defaults hazard: `Default` must stay byte-identical to
    // the `#[envconfig(default = ...)]` values, so `..Default::default()`
    // callers get the same base as env-driven ones. Uses an empty hashmap
    // (not process env) to stay deterministic under any CI environment.
    #[test]
    fn default_matches_envconfig_defaults() {
        let d = KafkaConfig::default();
        let e = KafkaConfig::init_from_hashmap(&HashMap::new())
            .expect("envconfig must initialize from its declared defaults");

        assert_eq!(d.kafka_producer_linger_ms, e.kafka_producer_linger_ms);
        assert_eq!(d.kafka_producer_queue_mib, e.kafka_producer_queue_mib);
        assert_eq!(
            d.kafka_producer_queue_messages,
            e.kafka_producer_queue_messages
        );
        assert_eq!(d.kafka_message_timeout_ms, e.kafka_message_timeout_ms);
        assert_eq!(d.kafka_compression_codec, e.kafka_compression_codec);
        assert_eq!(d.kafka_tls, e.kafka_tls);
        assert_eq!(d.kafka_hosts, e.kafka_hosts);
        assert_eq!(d.kafka_client_rack, e.kafka_client_rack);
        assert_eq!(d.kafka_client_id, e.kafka_client_id);
        assert_eq!(d.kafka_producer_batch_size, e.kafka_producer_batch_size);
        assert_eq!(
            d.kafka_producer_batch_num_messages,
            e.kafka_producer_batch_num_messages
        );
        assert_eq!(
            d.kafka_producer_enable_idempotence,
            e.kafka_producer_enable_idempotence
        );
        assert_eq!(
            d.kafka_producer_max_in_flight_requests_per_connection,
            e.kafka_producer_max_in_flight_requests_per_connection
        );
        assert_eq!(
            d.kafka_producer_topic_metadata_refresh_interval_ms,
            e.kafka_producer_topic_metadata_refresh_interval_ms
        );
        assert_eq!(
            d.kafka_producer_message_max_bytes,
            e.kafka_producer_message_max_bytes
        );
        assert_eq!(
            d.kafka_producer_sticky_partitioning_linger_ms,
            e.kafka_producer_sticky_partitioning_linger_ms
        );
        assert_eq!(d.kafka_producer_partitioner, e.kafka_producer_partitioner);
        assert_eq!(d.kafka_producer_acks, e.kafka_producer_acks);
        assert_eq!(d.kafka_producer_retries, e.kafka_producer_retries);
    }
}
