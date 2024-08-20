#![allow(dead_code)]

use std::default::Default;
use std::net::SocketAddr;
use std::num::NonZeroU32;
use std::ops::Add;
use std::str::FromStr;
use std::string::ToString;
use std::sync::{Arc, Once};
use std::time::Duration;

use anyhow::bail;
use once_cell::sync::Lazy;
use rand::distributions::Alphanumeric;
use rand::Rng;
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::config::{ClientConfig, FromClientConfig};
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::util::Timeout;
use rdkafka::{Message, TopicPartitionList};
use redis::{Client, Commands};
use time::OffsetDateTime;
use tokio::net::TcpListener;
use tokio::sync::Notify;
use tokio::time::timeout;
use tracing::{debug, warn};

use capture::config::{Config, KafkaConfig};
use capture::limiters::billing::QuotaResource;
use capture::server::serve;

pub static DEFAULT_CONFIG: Lazy<Config> = Lazy::new(|| Config {
    print_sink: false,
    address: SocketAddr::from_str("127.0.0.1:0").unwrap(),
    redis_url: "redis://localhost:6379/".to_string(),
    overflow_enabled: false,
    overflow_burst_limit: NonZeroU32::new(5).unwrap(),
    overflow_per_second_limit: NonZeroU32::new(10).unwrap(),
    overflow_forced_keys: None,
    kafka: KafkaConfig {
        kafka_producer_linger_ms: 0, // Send messages as soon as possible
        kafka_producer_queue_mib: 10,
        kafka_message_timeout_ms: 10000, // 10s, ACKs can be slow on low volumes, should be tuned
        kafka_compression_codec: "none".to_string(),
        kafka_hosts: "kafka:9092".to_string(),
        kafka_topic: "events_plugin_ingestion".to_string(),
        kafka_historical_topic: "events_plugin_ingestion_historical".to_string(),
        kafka_client_ingestion_warning_topic: "events_plugin_ingestion".to_string(),
        kafka_exceptions_topic: "events_plugin_ingestion".to_string(),
        kafka_heatmaps_topic: "events_plugin_ingestion".to_string(),
        kafka_tls: false,
    },
    otel_url: None,
    otel_sampling_rate: 0.0,
    otel_service_name: "capture-testing".to_string(),
    export_prometheus: false,
    redis_key_prefix: None,
});

static TRACING_INIT: Once = Once::new();
pub fn setup_tracing() {
    TRACING_INIT.call_once(|| {
        tracing_subscriber::fmt()
            .with_writer(tracing_subscriber::fmt::TestWriter::new())
            .init()
    });
}
pub struct ServerHandle {
    pub addr: SocketAddr,
    shutdown: Arc<Notify>,
}

impl ServerHandle {
    pub async fn for_topics(main: &EphemeralTopic, historical: &EphemeralTopic) -> Self {
        let mut config = DEFAULT_CONFIG.clone();
        config.kafka.kafka_topic = main.topic_name().to_string();
        config.kafka.kafka_historical_topic = historical.topic_name().to_string();
        Self::for_config(config).await
    }
    pub async fn for_config(config: Config) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let notify = Arc::new(Notify::new());
        let shutdown = notify.clone();

        tokio::spawn(async move {
            serve(config, listener, async move { notify.notified().await }).await
        });
        Self { addr, shutdown }
    }

    pub async fn capture_events<T: Into<reqwest::Body>>(&self, body: T) -> reqwest::Response {
        let client = reqwest::Client::new();
        client
            .post(format!("http://{:?}/i/v0/e", self.addr))
            .body(body)
            .send()
            .await
            .expect("failed to send request")
    }

    pub async fn capture_to_batch<T: Into<reqwest::Body>>(&self, body: T) -> reqwest::Response {
        let client = reqwest::Client::new();
        client
            .post(format!("http://{:?}/batch", self.addr))
            .body(body)
            .send()
            .await
            .expect("failed to send request")
    }
}

impl Drop for ServerHandle {
    fn drop(&mut self) {
        self.shutdown.notify_one()
    }
}

pub struct EphemeralTopic {
    consumer: BaseConsumer,
    read_timeout: Timeout,
    topic_name: String,
}

impl EphemeralTopic {
    pub async fn new() -> Self {
        let mut config = ClientConfig::new();
        config.set("group.id", "capture_integration_tests");
        config.set(
            "bootstrap.servers",
            DEFAULT_CONFIG.kafka.kafka_hosts.clone(),
        );
        config.set("debug", "all");

        // TODO: check for name collision?
        let topic_name = random_string("events_", 16);
        let admin = AdminClient::from_config(&config).expect("failed to create admin client");
        admin
            .create_topics(
                &[NewTopic {
                    name: &topic_name,
                    num_partitions: 1,
                    replication: TopicReplication::Fixed(1),
                    config: vec![],
                }],
                &AdminOptions::default(),
            )
            .await
            .expect("failed to create topic");

        let consumer: BaseConsumer = config.create().expect("failed to create consumer");
        let mut assignment = TopicPartitionList::new();
        assignment.add_partition(&topic_name, 0);
        consumer
            .assign(&assignment)
            .expect("failed to assign topic");

        Self {
            consumer,
            read_timeout: Timeout::After(Duration::from_secs(5)),
            topic_name,
        }
    }

    pub fn next_event(&self) -> anyhow::Result<serde_json::Value> {
        match self.consumer.poll(self.read_timeout) {
            Some(Ok(message)) => {
                let body = message.payload().expect("empty kafka message");
                let event = serde_json::from_slice(body)?;
                Ok(event)
            }
            Some(Err(err)) => bail!("kafka read error: {}", err),
            None => bail!("kafka read timeout"),
        }
    }
    pub fn next_message_key(&self) -> anyhow::Result<Option<String>> {
        match self.consumer.poll(self.read_timeout) {
            Some(Ok(message)) => {
                let key = message.key();

                if let Some(key) = key {
                    let key = std::str::from_utf8(key)?;
                    let key = String::from_str(key)?;

                    Ok(Some(key))
                } else {
                    Ok(None)
                }
            }
            Some(Err(err)) => bail!("kafka read error: {}", err),
            None => bail!("kafka read timeout"),
        }
    }

    pub(crate) fn assert_empty(&self) {
        assert!(
            self.consumer
                .poll(Timeout::After(Duration::from_secs(1)))
                .is_none(),
            "topic holds more messages"
        )
    }

    pub fn topic_name(&self) -> &str {
        &self.topic_name
    }
}

impl Drop for EphemeralTopic {
    fn drop(&mut self) {
        debug!("dropping EphemeralTopic {}...", self.topic_name);
        self.consumer.unsubscribe();
        match futures::executor::block_on(timeout(
            Duration::from_secs(10),
            delete_topic(self.topic_name.clone()),
        )) {
            Ok(_) => debug!("dropped topic"),
            Err(err) => warn!("failed to drop topic: {}", err),
        }
    }
}

async fn delete_topic(topic: String) {
    let mut config = ClientConfig::new();
    config.set(
        "bootstrap.servers",
        DEFAULT_CONFIG.kafka.kafka_hosts.clone(),
    );
    let admin = AdminClient::from_config(&config).expect("failed to create admin client");
    admin
        .delete_topics(&[&topic], &AdminOptions::default())
        .await
        .expect("failed to delete topic");
}

pub struct PrefixedRedis {
    key_prefix: String,
    client: Client,
}

impl PrefixedRedis {
    pub async fn new() -> Self {
        Self {
            key_prefix: random_string("test", 8) + "/",
            client: Client::open(DEFAULT_CONFIG.redis_url.clone())
                .expect("failed to create redis client"),
        }
    }

    pub fn key_prefix(&self) -> Option<String> {
        Some(self.key_prefix.to_string())
    }

    pub fn add_billing_limit(&self, res: QuotaResource, token: &str, until: time::Duration) {
        let key = format!("{}@posthog/quota-limits/{}", self.key_prefix, res.as_str());
        let score = OffsetDateTime::now_utc().add(until).unix_timestamp();
        self.client
            .get_connection()
            .expect("failed to get connection")
            .zadd::<String, i64, &str, i64>(key, token, score)
            .expect("failed to insert in redis");
    }
}

pub fn random_string(prefix: &str, length: usize) -> String {
    let suffix: String = rand::thread_rng()
        .sample_iter(Alphanumeric)
        .take(length)
        .map(char::from)
        .collect();
    format!("{}_{}", prefix, suffix)
}
