use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "USAGE_INGESTION_GRPC_ADDRESS", default = "0.0.0.0:7143")]
    pub grpc_address: String,
    #[envconfig(from = "USAGE_INGESTION_METRICS_ADDRESS", default = "0.0.0.0:7144")]
    pub metrics_address: String,
    #[envconfig(from = "USAGE_INGESTION_DATABASE_URL")]
    pub database_url: String,
    #[envconfig(from = "KAFKA_HOSTS", default = "localhost:9092")]
    pub kafka_hosts: String,
    #[envconfig(from = "KAFKA_TLS", default = "false")]
    pub kafka_tls: bool,
    // These records are small JSON objects that repeat their keys, so they compress well, and
    // WarpStream bills on what it stores. `KafkaConfig` defaults this to "none", and the service
    // builds that struct in code rather than from the environment, so the default has to be set
    // here or nothing an operator does turns compression on.
    //
    // Only "none", "gzip", "snappy" and "lz4" work. "zstd" needs the rdkafka `zstd` feature,
    // which the workspace does not enable, so librdkafka refuses it when it builds the producer.
    #[envconfig(from = "KAFKA_COMPRESSION_CODEC", default = "lz4")]
    pub kafka_compression_codec: String,
    // The knob to reach for if ingest latency matters more than batching. These records never
    // come close to filling a 16 MB batch, so linger, not batch size, decides when a produce
    // goes out, and the ingest RPC waits for that delivery. WarpStream's 100ms is affordable
    // because nothing waits on the RPC in turn: the flags aggregator flushes every 10 seconds
    // through one sender task, and the nodejs producers send from a batch side effect.
    #[envconfig(from = "KAFKA_PRODUCER_LINGER_MS", default = "100")]
    pub kafka_producer_linger_ms: u32,
    #[envconfig(from = "USAGE_INGESTION_MAX_BATCH_SIZE", default = "500")]
    pub max_batch_size: usize,
    // Overridable so a test environment can use the suffixed topic its Kafka engine table reads.
    #[envconfig(
        from = "USAGE_INGESTION_TOPIC",
        default = "clickhouse_billing_usage_records"
    )]
    pub topic: String,
}

/// WarpStream's recommended librdkafka producer settings. Their guidance is that throughput
/// against object storage needs large batches and many concurrent requests, because a single
/// write costs a few hundred milliseconds however small it is.
/// <https://docs.warpstream.com/warpstream/kafka/configure-kafka-client/tuning-for-performance>
const WARPSTREAM_BATCH_SIZE: u32 = 16_000_000;
const WARPSTREAM_BATCH_NUM_MESSAGES: u32 = 100_000;
/// Has to stay above `WARPSTREAM_BATCH_SIZE`: librdkafka caps a produce request at this, so a
/// smaller value here would silently bound the batch instead.
const WARPSTREAM_MESSAGE_MAX_BYTES: u32 = 64_000_000;
const WARPSTREAM_MAX_IN_FLIGHT_PER_CONNECTION: u32 = 1_000_000;
const WARPSTREAM_METADATA_REFRESH_INTERVAL_MS: u32 = 60_000;

impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if self.max_batch_size == 0 || self.max_batch_size > 5_000 {
            return Err("USAGE_INGESTION_MAX_BATCH_SIZE must be between 1 and 5000".to_string());
        }
        Ok(())
    }

    /// `KafkaConfig` defaults every field this does not name, so a setting dropped from here
    /// silently reverts to that default rather than failing. Compression already regressed
    /// that way once, unnoticed until WarpStream reported uncompressed produce requests.
    pub fn kafka_config(&self) -> KafkaConfig {
        KafkaConfig {
            kafka_hosts: self.kafka_hosts.clone(),
            kafka_tls: self.kafka_tls,
            kafka_client_id: "usage-ingestion".to_string(),
            kafka_compression_codec: self.kafka_compression_codec.clone(),
            kafka_producer_linger_ms: self.kafka_producer_linger_ms,
            kafka_producer_batch_size: Some(WARPSTREAM_BATCH_SIZE),
            kafka_producer_batch_num_messages: Some(WARPSTREAM_BATCH_NUM_MESSAGES),
            kafka_producer_message_max_bytes: Some(WARPSTREAM_MESSAGE_MAX_BYTES),
            kafka_producer_max_in_flight_requests_per_connection: Some(
                WARPSTREAM_MAX_IN_FLIGHT_PER_CONNECTION,
            ),
            kafka_producer_topic_metadata_refresh_interval_ms: Some(
                WARPSTREAM_METADATA_REFRESH_INTERVAL_MS,
            ),
            // WarpStream's discovery hands out a different agent per connection, which its docs
            // say collapses throughput and adds latency when librdkafka pins an idempotent
            // producer's sequence numbers to one. Off is also librdkafka's default; naming it
            // means turning it on has to be a decision.
            kafka_producer_enable_idempotence: Some(false),
            // Two settings deliberately left at librdkafka's default, which already matches
            // WarpStream's advice: `acks=all`, because a record that bills a customer must be
            // durable before the service reports it landed, and the `consistent_random`
            // partitioner, which these records reach anyway by carrying no key.
            ..Default::default()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> Config {
        Config {
            grpc_address: "0.0.0.0:7143".to_string(),
            metrics_address: "0.0.0.0:7144".to_string(),
            database_url: "postgres://localhost/test".to_string(),
            kafka_hosts: "localhost:9092".to_string(),
            kafka_tls: false,
            kafka_compression_codec: "lz4".to_string(),
            kafka_producer_linger_ms: 100,
            max_batch_size: 500,
            topic: "clickhouse_billing_usage_records".to_string(),
        }
    }

    #[test]
    fn the_producer_follows_the_warpstream_recommendations() {
        // Every one of these reverts to a librdkafka default if it is dropped from
        // `kafka_config`, with nothing failing and no metric to notice. That is how
        // compression came to be off in production.
        let kafka = config().kafka_config();

        assert_eq!(kafka.kafka_compression_codec, "lz4");
        assert_eq!(kafka.kafka_producer_linger_ms, 100);
        assert_eq!(kafka.kafka_producer_batch_size, Some(16_000_000));
        assert_eq!(kafka.kafka_producer_batch_num_messages, Some(100_000));
        assert_eq!(kafka.kafka_producer_message_max_bytes, Some(64_000_000));
        assert_eq!(
            kafka.kafka_producer_max_in_flight_requests_per_connection,
            Some(1_000_000)
        );
        assert_eq!(
            kafka.kafka_producer_topic_metadata_refresh_interval_ms,
            Some(60_000)
        );
        // WarpStream calls this out as the setting that collapses producer throughput.
        assert_eq!(kafka.kafka_producer_enable_idempotence, Some(false));
    }

    #[test]
    fn a_produce_request_can_carry_a_whole_batch() {
        // librdkafka caps the request at message.max.bytes, so a batch.size above it would be
        // bounded by the wrong setting.
        let kafka = config().kafka_config();

        assert!(
            kafka.kafka_producer_message_max_bytes > kafka.kafka_producer_batch_size,
            "message.max.bytes must exceed batch.size"
        );
    }

    #[test]
    fn an_operator_can_retune_the_cost_latency_tradeoff_without_a_release() {
        let config = Config {
            kafka_compression_codec: "none".to_string(),
            kafka_producer_linger_ms: 5,
            ..config()
        };

        let kafka = config.kafka_config();
        assert_eq!(kafka.kafka_compression_codec, "none");
        assert_eq!(kafka.kafka_producer_linger_ms, 5);
    }
}
