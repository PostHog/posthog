use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, RwLock};

use common_kafka::config::KafkaConfig;
use metrics::counter;
use personhog_coordination::follow::ChangelogSubscription;
use personhog_coordination::types::ClusterEndpoint;
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, Rebalance, StreamConsumer,
};
use rdkafka::error::KafkaError;
use rdkafka::message::BorrowedMessage;
use rdkafka::types::RDKafkaErrorCode;
use rdkafka::{ClientConfig, ClientContext, TopicPartitionList};
use tokio::sync::mpsc;

/// The partition a row arrived on; a resubscribe changes the topic and
/// keeps the numbers, so offsets, assignments and revocations carry both.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Source {
    pub topic: Arc<str>,
    pub partition: i32,
}

// ── Consumer ────────────────────────────────────────────────────

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct BackfillPace {
    pub live_lag: i64,
    pub paused: bool,
}

fn subscription<'a>(topic: &'a str, backfill_topic: Option<&'a str>) -> Vec<&'a str> {
    std::iter::once(topic).chain(backfill_topic).collect()
}

/// The changelog's own cluster when the config names one, else the process's default brokers.
pub fn changelog_kafka(base: &KafkaConfig, cluster: Option<&ClusterEndpoint>) -> KafkaConfig {
    match cluster {
        Some(cluster) => base.with_endpoint(&cluster.hosts, cluster.tls),
        None => base.clone(),
    }
}

/// Broker address and transport settings alone.
pub fn base_client_config(kafka: &KafkaConfig) -> ClientConfig {
    let mut client_config = ClientConfig::new();
    client_config.set("bootstrap.servers", &kafka.kafka_hosts);
    if kafka.kafka_tls {
        client_config
            .set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    }
    if !kafka.kafka_client_rack.is_empty() {
        client_config.set("client.rack", &kafka.kafka_client_rack);
    }
    client_config
}

fn group_client_config(kafka: &KafkaConfig, consumer_group: &str) -> ClientConfig {
    let mut client_config = base_client_config(kafka);
    client_config
        .set("group.id", consumer_group)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false");
    client_config
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OwnershipEvent {
    Assigned(Source, u64),
    Revoked(Source, u64),
}

/// A fresh generation per assignment lets work tell a partition that moved and came back.
struct Ownership {
    next: AtomicU64,
    current: Mutex<HashMap<Source, u64>>,
    events: mpsc::UnboundedSender<OwnershipEvent>,
}

/// Records the partitions each rebalance takes away, so the consume loop can
/// drop their buffered rows before the new owner starts reading them.
struct RebalanceContext {
    revoked: Arc<Mutex<Vec<Source>>>,
    joined: Arc<AtomicBool>,
    ownership: Arc<Ownership>,
}

impl ClientContext for RebalanceContext {
    /// End-of-partition is the drain's signal, not an error; the callback reports it as a global code.
    fn error(&self, error: KafkaError, reason: &str) {
        if !matches!(
            error,
            KafkaError::PartitionEOF(_) | KafkaError::Global(RDKafkaErrorCode::PartitionEOF)
        ) {
            tracing::error!(%error, reason, "librdkafka");
        }
    }
}

impl ConsumerContext for RebalanceContext {
    fn pre_rebalance(&self, _base_consumer: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        match rebalance {
            Rebalance::Assign(partitions) => {
                self.joined.store(true, Ordering::SeqCst);
                let mut current = self.ownership.current.lock().unwrap();
                for source in sources(partitions) {
                    let generation = self.ownership.next.fetch_add(1, Ordering::SeqCst) + 1;
                    current.insert(source.clone(), generation);
                    self.ownership
                        .events
                        .send(OwnershipEvent::Assigned(source, generation))
                        .ok();
                }
            }
            Rebalance::Revoke(partitions) => {
                let revoked_sources = sources(partitions);
                let mut current = self.ownership.current.lock().unwrap();
                for source in &revoked_sources {
                    if let Some(generation) = current.remove(source) {
                        self.ownership
                            .events
                            .send(OwnershipEvent::Revoked(source.clone(), generation))
                            .ok();
                    }
                }
                drop(current);
                self.revoked.lock().unwrap().extend(revoked_sources);
            }
            Rebalance::Error(_) => {}
        }
    }
}

fn sources(partitions: &TopicPartitionList) -> Vec<Source> {
    partitions
        .elements()
        .iter()
        .map(|e| Source {
            topic: Arc::from(e.topic()),
            partition: e.partition(),
        })
        .collect()
}

/// Wraps a Kafka StreamConsumer with its topic, providing a clean
/// interface for receiving messages and committing offsets.
pub struct PersonConsumer {
    consumer: StreamConsumer<RebalanceContext>,
    topic: RwLock<String>,
    cluster: Option<ClusterEndpoint>,
    backfill_topic: Option<String>,
    /// Set while the subscribed topic is a sealed generation.
    draining: AtomicBool,
    revoked: Arc<Mutex<Vec<Source>>>,
    joined: Arc<AtomicBool>,
    ownership: Arc<Ownership>,
    ownership_events: Mutex<Option<mpsc::UnboundedReceiver<OwnershipEvent>>>,
}

impl PersonConsumer {
    /// Client-level fatal state, queryable even after the event that
    /// set it was consumed. A fatal client never recovers, so the
    /// caller must exit rather than keep polling it.
    pub fn fatal_error(&self) -> Option<(rdkafka::error::RDKafkaErrorCode, String)> {
        self.consumer.client().fatal_error()
    }

    pub fn from_config(
        kafka: &KafkaConfig,
        consumer_group: &str,
        topic: String,
    ) -> Result<Self, rdkafka::error::KafkaError> {
        Self::subscribed(kafka, consumer_group, topic, None)
    }

    /// The range assignor puts partition N of both topics on one pod.
    pub fn for_backfill(
        kafka: &KafkaConfig,
        consumer_group: &str,
        topic: String,
        backfill_topic: String,
    ) -> Result<Self, rdkafka::error::KafkaError> {
        Self::subscribed(kafka, consumer_group, topic, Some(backfill_topic))
    }

    fn subscribed(
        kafka: &KafkaConfig,
        consumer_group: &str,
        topic: String,
        backfill_topic: Option<String>,
    ) -> Result<Self, rdkafka::error::KafkaError> {
        let mut client_config = group_client_config(kafka, consumer_group);
        client_config
            // A generation the group never committed on must be read from its first record.
            .set("auto.offset.reset", "earliest")
            // Only committed transactions: with the leader's epoch fencing
            // on, aborted windows and zombie leftovers must never reach
            // Postgres. Identical behavior on a non-transactional topic.
            // The price is a liveness coupling: this consumer cannot
            // advance past an open window, so a leader that stops
            // mid-window holds the partition at its last stable offset
            // until the broker abandons the transaction — bounded by the
            // leader's derived broker transaction timeout (about 6s at
            // the production lease).
            .set("isolation.level", "read_committed")
            // Lets the consume loop flush a sealed partition's tail as soon as it reaches the end.
            .set("enable.partition.eof", "true")
            // Cooperative-sticky: during scale events, only partitions that need
            // to move are revoked. Non-moving partitions keep being consumed.
            .set("partition.assignment.strategy", "cooperative-sticky");

        // Static group membership: the broker holds partition assignments for
        // session.timeout.ms after a pod disappears, so quick restarts
        // (deploys, OOM kills) don't trigger a rebalance at all.
        // Requires stable pod names (StatefulSet) so the same ID reconnects.
        if !kafka.kafka_client_id.is_empty() {
            client_config
                .set("client.id", &kafka.kafka_client_id)
                .set("group.instance.id", &kafka.kafka_client_id);
        }

        if backfill_topic.is_some() {
            client_config.set("partition.assignment.strategy", "range");
        }

        Self::with_topics(&client_config, topic, backfill_topic)
    }

    /// Create from a raw `ClientConfig`. Useful in tests where you control
    /// the config directly (e.g., mock clusters).
    pub fn new(config: &ClientConfig, topic: String) -> Result<Self, rdkafka::error::KafkaError> {
        Self::with_topics(config, topic, None)
    }

    pub fn with_topics(
        config: &ClientConfig,
        topic: String,
        backfill_topic: Option<String>,
    ) -> Result<Self, rdkafka::error::KafkaError> {
        let revoked = Arc::new(Mutex::new(Vec::new()));
        let joined = Arc::new(AtomicBool::new(false));
        let (events, ownership_events) = mpsc::unbounded_channel();
        let ownership = Arc::new(Ownership {
            next: AtomicU64::new(0),
            current: Mutex::new(HashMap::new()),
            events,
        });
        let consumer: StreamConsumer<RebalanceContext> =
            config.create_with_context(RebalanceContext {
                revoked: Arc::clone(&revoked),
                joined: Arc::clone(&joined),
                ownership: Arc::clone(&ownership),
            })?;
        consumer.subscribe(&subscription(&topic, backfill_topic.as_deref()))?;
        Ok(Self {
            consumer,
            topic: RwLock::new(topic),
            cluster: None,
            backfill_topic,
            draining: AtomicBool::new(false),
            revoked,
            joined,
            ownership,
            ownership_events: Mutex::new(Some(ownership_events)),
        })
    }

    pub fn on_cluster(mut self, cluster: Option<ClusterEndpoint>) -> Self {
        self.cluster = cluster;
        self
    }

    /// Only called once the group has drained the current topic.
    pub fn resubscribe(&self, topic: String) -> Result<(), rdkafka::error::KafkaError> {
        self.consumer
            .subscribe(&subscription(&topic, self.backfill_topic.as_deref()))?;
        *self.topic.write().expect("topic lock poisoned") = topic;
        Ok(())
    }

    pub fn set_draining(&self, draining: bool) {
        self.draining.store(draining, Ordering::SeqCst);
    }

    pub fn is_draining(&self) -> bool {
        self.draining.load(Ordering::SeqCst)
    }

    pub async fn recv(&self) -> Result<BorrowedMessage<'_>, rdkafka::error::KafkaError> {
        self.consumer.recv().await
    }

    pub fn take_ownership_events(&self) -> Option<mpsc::UnboundedReceiver<OwnershipEvent>> {
        self.ownership_events.lock().unwrap().take()
    }

    pub fn generation(&self, source: &Source) -> Option<u64> {
        self.ownership.current.lock().unwrap().get(source).copied()
    }

    /// Blocking metadata lookup; call off the async runtime.
    pub fn partition_count(
        &self,
        topic: &str,
        timeout: std::time::Duration,
    ) -> Result<u32, rdkafka::error::KafkaError> {
        let metadata = self.consumer.fetch_metadata(Some(topic), timeout)?;
        metadata
            .topics()
            .iter()
            .find(|t| t.name() == topic)
            .map(|t| t.partitions().len() as u32)
            .filter(|&count| count > 0)
            .ok_or(rdkafka::error::KafkaError::MetadataFetch(
                RDKafkaErrorCode::UnknownTopicOrPartition,
            ))
    }

    /// A partition that has not fetched yet lags from its committed offset, or the log start.
    /// Blocking: call off the async runtime.
    pub fn pace_backfill(
        &self,
        max_lag: i64,
        timeout: std::time::Duration,
    ) -> Result<BackfillPace, rdkafka::error::KafkaError> {
        let Some(backfill_topic) = self.backfill_topic.as_deref() else {
            return Ok(BackfillPace::default());
        };
        let positions = self.consumer.position()?;
        let mut committed = None;
        let mut live_lag = 0;
        let mut backfill = TopicPartitionList::new();
        for e in positions.elements() {
            if e.topic() == backfill_topic {
                backfill.add_partition(e.topic(), e.partition());
                continue;
            }
            let (low, high) = self
                .consumer
                .fetch_watermarks(e.topic(), e.partition(), timeout)?;
            let next = match e.offset() {
                rdkafka::Offset::Offset(next) => next,
                _ => {
                    if committed.is_none() {
                        committed = Some(self.consumer.committed(timeout)?);
                    }
                    committed
                        .as_ref()
                        .and_then(|c| c.find_partition(e.topic(), e.partition()))
                        .and_then(|c| match c.offset() {
                            rdkafka::Offset::Offset(next) => Some(next),
                            _ => None,
                        })
                        .unwrap_or(low)
                }
            };
            live_lag += (high - next).max(0);
        }
        let paused = live_lag > max_lag;
        if backfill.count() > 0 {
            if paused {
                self.consumer.pause(&backfill)?;
            } else {
                self.consumer.resume(&backfill)?;
            }
        }
        Ok(BackfillPace { live_lag, paused })
    }

    pub fn take_revoked(&self) -> Vec<Source> {
        std::mem::take(&mut *self.revoked.lock().unwrap())
    }

    /// `None` until the first assignment arrives: before that, an empty
    /// assignment means the group is still forming, not that this pod owns
    /// nothing.
    pub fn assigned_partitions(
        &self,
    ) -> Result<Option<HashSet<Source>>, rdkafka::error::KafkaError> {
        if !self.joined.load(Ordering::SeqCst) {
            return Ok(None);
        }
        Ok(Some(
            self.consumer
                .assignment()?
                .elements()
                .iter()
                .map(|e| Source {
                    topic: Arc::from(e.topic()),
                    partition: e.partition(),
                })
                .collect(),
        ))
    }

    pub fn positions(&self) -> Result<HashMap<Source, i64>, rdkafka::error::KafkaError> {
        Ok(self
            .consumer
            .position()?
            .elements()
            .iter()
            .filter_map(|e| match e.offset() {
                rdkafka::Offset::Offset(next) => Some((
                    Source {
                        topic: Arc::from(e.topic()),
                        partition: e.partition(),
                    },
                    next,
                )),
                _ => None,
            })
            .collect())
    }

    pub fn commit_offsets(
        &self,
        offsets: &HashMap<Source, i64>,
    ) -> Result<(), rdkafka::error::KafkaError> {
        if offsets.is_empty() {
            return Ok(());
        }

        // A partition revoked while its batch was in flight belongs to another pod
        // now. The topic comes from the rows: a resubscribe reuses the numbers.
        let assigned = self.assigned_partitions()?.unwrap_or_default();
        let mut tpl = TopicPartitionList::new();
        let mut skipped: u64 = 0;
        for (source, offset) in offsets {
            if !assigned.contains(source) {
                skipped += 1;
                continue;
            }
            tpl.add_partition_offset(
                &source.topic,
                source.partition,
                rdkafka::Offset::Offset(offset + 1),
            )?;
        }
        if skipped > 0 {
            counter!("personhog_writer_offset_commits_skipped_total", "reason" => "unassigned")
                .increment(skipped);
        }
        if tpl.count() == 0 {
            return Ok(());
        }

        self.consumer.commit(&tpl, CommitMode::Async)?;
        Ok(())
    }

    pub fn topic(&self) -> String {
        self.topic.read().expect("topic lock poisoned").clone()
    }
}

impl ChangelogSubscription for PersonConsumer {
    fn topic(&self) -> String {
        PersonConsumer::topic(self)
    }

    fn cluster(&self) -> Option<ClusterEndpoint> {
        self.cluster.clone()
    }

    fn resubscribe(&self, topic: &str) -> Result<(), String> {
        PersonConsumer::resubscribe(self, topic.to_string()).map_err(|e| e.to_string())
    }

    fn set_draining(&self, draining: bool) {
        PersonConsumer::set_draining(self, draining)
    }

    fn is_draining(&self) -> bool {
        PersonConsumer::is_draining(self)
    }
}
