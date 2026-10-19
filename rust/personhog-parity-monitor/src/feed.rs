//! One reader per topic, every partition assigned at the end of the log,
//! nothing committed: a consumer group would split the partitions between
//! replicas and break the cross-feed join, and a restart resumes nothing.

use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::{bail, Context, Result};
use health::HealthHandle;
use personhog_common::cdc_parity::{DecodeError, DistinctIdRow, MergeEvent};
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::message::BorrowedMessage;
use rdkafka::{ClientConfig, Message, Offset, TopicPartitionList};
use tokio::sync::mpsc;
use tracing::{debug, error, warn};

use crate::config::FeedConfig;
use crate::join::{Event, Kind, Record, Topic};

const METADATA_TIMEOUT: Duration = Duration::from_secs(10);
/// Bounds a `recv` on a quiet topic so the reader still reports liveness.
const RECV_TIMEOUT: Duration = Duration::from_secs(5);
const HEALTH_REPORT_INTERVAL: Duration = Duration::from_secs(1);
const ERROR_BACKOFF: Duration = Duration::from_secs(1);
/// librdkafka's default prefetch is 64 MiB per consumer.
const PREFETCH_KBYTES: &str = "16384";

pub struct TopicReader {
    topic: Topic,
    name: String,
    consumer: StreamConsumer,
}

impl TopicReader {
    pub fn connect(feed: &FeedConfig, kind: Kind) -> Result<(Self, u32)> {
        let name = match kind {
            Kind::DistinctIds => feed.distinct_id_topic.clone(),
            Kind::MergeEvents => feed.merge_events_topic.clone(),
        };
        let topic = Topic {
            side: feed.side,
            kind,
        };
        let mut client = ClientConfig::new();
        client
            .set("bootstrap.servers", &feed.kafka_hosts)
            .set("group.id", "personhog-parity-monitor")
            .set("enable.auto.commit", "false")
            .set("enable.auto.offset.store", "false")
            .set("auto.offset.reset", "latest")
            .set("queued.max.messages.kbytes", PREFETCH_KBYTES)
            .set(
                "client.id",
                format!("personhog-parity-monitor-{}", feed.side.label()),
            );
        if feed.kafka_tls {
            client
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }
        let consumer: StreamConsumer = client
            .create()
            .with_context(|| format!("creating the {} reader for {name}", feed.side.label()))?;
        let metadata = consumer
            .fetch_metadata(Some(&name), METADATA_TIMEOUT)
            .with_context(|| format!("fetching metadata of {name}"))?;
        let partitions: Vec<i32> = metadata
            .topics()
            .iter()
            .find(|entry| entry.name() == name)
            .map(|entry| entry.partitions().iter().map(|p| p.id()).collect())
            .unwrap_or_default();
        if partitions.is_empty() {
            bail!("topic {name} has no partitions on {}", feed.kafka_hosts);
        }
        let mut assignment = TopicPartitionList::new();
        for partition in &partitions {
            assignment.add_partition_offset(&name, *partition, Offset::End)?;
        }
        consumer
            .assign(&assignment)
            .with_context(|| format!("assigning {name}"))?;
        Ok((
            Self {
                topic,
                name,
                consumer,
            },
            partitions.len() as u32,
        ))
    }

    pub fn topic(&self) -> Topic {
        self.topic
    }

    /// The first decode failure per topic is logged in full; the counter is the signal.
    pub async fn run(self, events: mpsc::Sender<Event>, health: HealthHandle) {
        let feed = self.topic.side.label();
        let kind = self.topic.kind.label();
        let messages =
            metrics::counter!("personhog_parity_messages_total", "feed" => feed, "topic" => kind);
        let read_errors = metrics::counter!("personhog_parity_read_errors_total", "feed" => feed, "topic" => kind);
        let decode_failures = metrics::counter!(
            "personhog_parity_decode_failures_total",
            "feed" => feed,
            "topic" => kind
        );
        let mut last_health_report = Instant::now() - HEALTH_REPORT_INTERVAL;
        let mut decode_failure_logged = false;
        loop {
            if last_health_report.elapsed() >= HEALTH_REPORT_INTERVAL {
                health.report_healthy().await;
                last_health_report = Instant::now();
            }
            let message = match tokio::time::timeout(RECV_TIMEOUT, self.consumer.recv()).await {
                Err(_) => continue,
                // The consumer cannot recover; the reader stops reporting, so
                // liveness fails and the pod restarts into a fresh window.
                Ok(Err(KafkaError::MessageConsumptionFatal(code))) => {
                    error!(topic = %self.name, %code, "the consumer failed for good; stopping the reader");
                    read_errors.increment(1);
                    return;
                }
                Ok(Err(error)) => {
                    warn!(topic = %self.name, %error, "reading the topic failed");
                    read_errors.increment(1);
                    tokio::time::sleep(ERROR_BACKOFF).await;
                    continue;
                }
                Ok(Ok(message)) => message,
            };
            messages.increment(1);
            let record = match self.decode(&message) {
                Ok(record) => record,
                Err(error) => {
                    decode_failures.increment(1);
                    if decode_failure_logged {
                        debug!(topic = %self.name, %error, "undecodable message");
                    } else {
                        warn!(topic = %self.name, %error, "undecodable message; further ones are counted only");
                        decode_failure_logged = true;
                    }
                    continue;
                }
            };
            let event = Event::Arrival {
                topic: self.topic,
                partition: message.partition(),
                timestamp_ms: message.timestamp().to_millis().unwrap_or_else(now_ms),
                record,
            };
            if events.send(event).await.is_err() {
                return;
            }
        }
    }

    fn decode(&self, message: &BorrowedMessage<'_>) -> Result<Record, DecodeError> {
        let payload = message.payload().unwrap_or_default();
        match self.topic.kind {
            Kind::DistinctIds => DistinctIdRow::decode(payload).map(Record::Mapping),
            Kind::MergeEvents => MergeEvent::decode(message.key(), payload).map(Record::Merge),
        }
    }
}

pub fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| elapsed.as_millis() as i64)
}
