use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::RwLock;

use common_kafka::config::KafkaConfig;
use personhog_coordination::follow::ChangelogSubscription;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::message::{BorrowedMessage, Message};
use rdkafka::{ClientConfig, Offset, TopicPartitionList};

/// Broker address and transport settings alone.
pub fn base_client_config(kafka: &KafkaConfig) -> ClientConfig {
    let mut config = ClientConfig::new();
    config.set("bootstrap.servers", &kafka.kafka_hosts);
    if kafka.kafka_tls {
        config
            .set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    }
    if !kafka.kafka_client_rack.is_empty() {
        config.set("client.rack", &kafka.kafka_client_rack);
    }
    config
}

pub fn consumer_client_config(kafka: &KafkaConfig, group: &str) -> ClientConfig {
    let mut config = base_client_config(kafka);
    config
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        // A generation the group never committed on is read from its first record.
        .set("auto.offset.reset", "earliest")
        // The leader produces transactionally; aborted windows must never reach ClickHouse.
        .set("isolation.level", "read_committed")
        .set("partition.assignment.strategy", "cooperative-sticky");
    config
}

/// One changelog record, owned so it outlives the consumer's borrow.
pub struct Record {
    pub topic: String,
    pub partition: i32,
    pub offset: i64,
    /// When the leader produced it, in epoch milliseconds.
    pub timestamp_ms: Option<i64>,
    pub payload: Option<Vec<u8>>,
}

impl Record {
    fn from_message(message: &BorrowedMessage<'_>) -> Self {
        Self {
            topic: message.topic().to_string(),
            partition: message.partition(),
            offset: message.offset(),
            timestamp_ms: message.timestamp().to_millis(),
            payload: message.payload().map(<[u8]>::to_vec),
        }
    }
}

pub struct ChangelogConsumer {
    consumer: StreamConsumer,
    topic: RwLock<String>,
    draining: AtomicBool,
}

impl ChangelogConsumer {
    pub fn new(config: &ClientConfig, topic: String) -> Result<Self, KafkaError> {
        let consumer: StreamConsumer = config.create()?;
        consumer.subscribe(&[&topic])?;
        Ok(Self {
            consumer,
            topic: RwLock::new(topic),
            draining: AtomicBool::new(false),
        })
    }

    pub async fn recv(&self) -> Result<Record, KafkaError> {
        self.consumer
            .recv()
            .await
            .map(|message| Record::from_message(&message))
    }

    /// Commits each partition's next offset after the highest relayed one. A
    /// partition this pod no longer owns is skipped: its new owner relays from
    /// the last commit, so the records repeat rather than go missing.
    pub fn commit(&self, highest: &HashMap<(String, i32), i64>) -> Result<(), KafkaError> {
        let assigned: HashSet<(String, i32)> = self
            .consumer
            .assignment()?
            .elements()
            .iter()
            .map(|e| (e.topic().to_string(), e.partition()))
            .collect();
        let mut tpl = TopicPartitionList::new();
        for ((topic, partition), offset) in highest {
            if assigned.contains(&(topic.clone(), *partition)) {
                tpl.add_partition_offset(topic, *partition, Offset::Offset(offset + 1))?;
            }
        }
        if tpl.count() == 0 {
            return Ok(());
        }
        self.consumer.commit(&tpl, CommitMode::Async)
    }

    pub fn fatal_error(&self) -> Option<(rdkafka::types::RDKafkaErrorCode, String)> {
        self.consumer.client().fatal_error()
    }
}

impl ChangelogSubscription for ChangelogConsumer {
    fn topic(&self) -> String {
        self.topic.read().expect("topic lock poisoned").clone()
    }

    fn resubscribe(&self, topic: &str) -> Result<(), String> {
        self.consumer
            .subscribe(&[topic])
            .map_err(|e| e.to_string())?;
        *self.topic.write().expect("topic lock poisoned") = topic.to_string();
        Ok(())
    }

    fn set_draining(&self, draining: bool) {
        self.draining.store(draining, Ordering::SeqCst);
    }

    fn is_draining(&self) -> bool {
        self.draining.load(Ordering::SeqCst)
    }
}
