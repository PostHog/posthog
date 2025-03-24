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
