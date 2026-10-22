//! One reader per topic, every partition assigned at the end of the log,
//! nothing committed: a consumer group would split the partitions between
//! replicas and break the cross-feed join, and a restart resumes nothing.

use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::{bail, Context, Result};
use health::HealthHandle;
use personhog_common::cdc_parity::{DecodeError, DistinctIdRow, MergeEvent, PersonRow};
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::message::BorrowedMessage;
use rdkafka::{ClientConfig, Message, Offset, TopicPartitionList};
use tokio::sync::mpsc;
use tracing::{debug, error, info, warn};

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
    consumer: Arc<StreamConsumer>,
    partitions: Vec<i32>,
}

impl TopicReader {
    pub fn connect(feed: &FeedConfig, kind: Kind) -> Result<(Self, u32)> {
        let name = match kind {
            Kind::DistinctIds => feed.distinct_id_topic.clone(),
            Kind::MergeEvents => feed.merge_events_topic.clone(),
            Kind::Persons => feed
                .person_topic
                .clone()
                .context("a person reader without a person topic")?,
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
        let partitions = fetch_partitions(&consumer, &name)
            .with_context(|| format!("on {}", feed.kafka_hosts))?;
        let mut assignment = TopicPartitionList::new();
        for partition in &partitions {
            // The end offset is read here, before anyone learns the reader is
            // up; `Offset::End` would resolve later, in the fetcher, and a row
            // produced in between would be skipped.
            let (_, end) = consumer
                .fetch_watermarks(&name, *partition, METADATA_TIMEOUT)
                .with_context(|| format!("fetching the end offset of {name}/{partition}"))?;
            assignment.add_partition_offset(&name, *partition, Offset::Offset(end))?;
        }
        consumer
            .assign(&assignment)
            .with_context(|| format!("assigning {name}"))?;
        let count = partitions.len() as u32;
        Ok((
            Self {
                topic,
                name,
                consumer: Arc::new(consumer),
                partitions,
            },
            count,
        ))
    }

    pub fn topic(&self) -> Topic {
        self.topic
    }

    /// The first decode failure per topic is logged in full; the counter is the signal.
    pub async fn run(
        mut self,
        events: mpsc::Sender<Event>,
        health: HealthHandle,
        metadata_poll: Duration,
    ) {
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
        let metadata_errors = metrics::counter!(
            "personhog_parity_metadata_errors_total",
            "feed" => feed,
            "topic" => kind
        );
        let mut last_health_report = Instant::now() - HEALTH_REPORT_INTERVAL;
        let mut next_metadata_poll = Instant::now() + metadata_poll;
        let mut decode_failure_logged = false;
        loop {
            if last_health_report.elapsed() >= HEALTH_REPORT_INTERVAL {
                health.report_healthy().await;
                last_health_report = Instant::now();
            }
            if Instant::now() >= next_metadata_poll {
                match self.assign_new_partitions().await {
                    Ok(Some(partitions)) => {
                        let assigned = Event::Assigned {
                            topic: self.topic,
                            partitions,
                        };
                        if events.send(assigned).await.is_err() {
                            return;
                        }
                    }
                    Ok(None) => {}
                    Err(error) => {
                        warn!(topic = %self.name, %error, "refreshing the partition list failed");
                        metadata_errors.increment(1);
                    }
                }
                // Armed after the request, so a slow one cannot leave the
                // next poll already due and starve the reads between polls.
                next_metadata_poll = Instant::now() + metadata_poll;
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

    /// New partitions are read from their beginning: they were empty at
    /// creation, so the end would skip rows that landed before this poll.
    async fn assign_new_partitions(&mut self) -> Result<Option<u32>> {
        let consumer = Arc::clone(&self.consumer);
        let name = self.name.clone();
        let current = tokio::task::spawn_blocking(move || fetch_partitions(&consumer, &name))
            .await
            .context("the metadata task panicked")??;
        let added: Vec<i32> = current
            .into_iter()
            .filter(|partition| !self.partitions.contains(partition))
            .collect();
        if added.is_empty() {
            return Ok(None);
        }
        let mut assignment = TopicPartitionList::new();
        for partition in &added {
            assignment.add_partition_offset(&self.name, *partition, Offset::Beginning)?;
        }
        self.consumer
            .incremental_assign(&assignment)
            .with_context(|| format!("assigning the new partitions of {}", self.name))?;
        info!(topic = %self.name, ?added, "assigned new partitions from their beginning");
        self.partitions.extend(added);
        Ok(Some(self.partitions.len() as u32))
    }

    fn decode(&self, message: &BorrowedMessage<'_>) -> Result<Record, DecodeError> {
        let payload = message.payload().unwrap_or_default();
        match self.topic.kind {
            Kind::DistinctIds => DistinctIdRow::decode(payload).map(Record::Mapping),
            Kind::MergeEvents => MergeEvent::decode(message.key(), payload).map(Record::Merge),
            Kind::Persons => PersonRow::decode(payload).map(Record::Person),
        }
    }
}

fn fetch_partitions(consumer: &StreamConsumer, name: &str) -> Result<Vec<i32>> {
    let metadata = consumer
        .fetch_metadata(Some(name), METADATA_TIMEOUT)
        .with_context(|| format!("fetching metadata of {name}"))?;
    let partitions: Vec<i32> = metadata
        .topics()
        .iter()
        .find(|entry| entry.name() == name)
        .map(|entry| entry.partitions().iter().map(|p| p.id()).collect())
        .unwrap_or_default();
    if partitions.is_empty() {
        bail!("topic {name} has no partitions");
    }
    Ok(partitions)
}

pub fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| elapsed.as_millis() as i64)
}
