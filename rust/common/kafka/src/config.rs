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
