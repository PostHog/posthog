use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct KafkaConfig {
    #[envconfig(default = "20")]
    pub kafka_producer_linger_ms: u32, // Maximum time between producer batches during low traffic

    #[envconfig(default = "400")]
    pub kafka_producer_queue_mib: u32, // Size of the in-memory producer queue in mebibytes

    #[envconfig(default = "20000")]
    pub kafka_message_timeout_ms: u32, // Time before we stop retrying producing a message: 20 seconds

    #[envconfig(default = "none")]
    pub kafka_compression_codec: String, // none, gzip, snappy, lz4, zstd

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,
}
