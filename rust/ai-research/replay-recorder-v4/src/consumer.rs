//! The consume loop: gate and admit each message from its key and headers, buffer it, and flush on time or size.

use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::KafkaContext;
use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, Rebalance, StreamConsumer,
};
use rdkafka::message::{BorrowedMessage, Headers as _, Message as _};
use rdkafka::{ClientConfig, ClientContext, Offset, TopicPartitionList};

use chrono::Utc;
use replay_core_v4::keys::batch::{KeyStore, SessionId};
use replay_core_v4::keys::kms::AwsKms;
use replay_core_v4::keys::rows::key_day;
use replay_core_v4::keys::table::{AwsKeyTable, CachedKeyTable};

use crate::batch::{Batch, Block, Inspectors, Raw, SessionKey};
use crate::limits::{Blocklist, Restrictions};
use crate::process::{admit, sampled, Admitted, Headers, Skip};
use crate::store::BlobStore;
use crate::teams::TeamCache;
use crate::urls::{fetch_jobs, records};
use crate::write::{prepare, write_block_index, write_blocks, write_images, WriteError};
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;

/// Records the partitions each rebalance takes away, so the loop can drop what it buffered for them.
pub struct RebalanceContext {
    revoked: Arc<Mutex<Vec<i32>>>,
}

impl ClientContext for RebalanceContext {}

impl ConsumerContext for RebalanceContext {
    fn pre_rebalance(&self, _: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        if let Rebalance::Revoke(partitions) = rebalance {
            self.revoked
                .lock()
                .unwrap()
                .extend(partitions.elements().iter().map(|e| e.partition()));
        }
    }
}

pub struct RecorderConsumer {
    consumer: StreamConsumer<RebalanceContext>,
    topic: String,
    revoked: Arc<Mutex<Vec<i32>>>,
}

impl RecorderConsumer {
    pub fn new(
        kafka: &KafkaConfig,
        group: &str,
        offset_reset: &str,
        topic: &str,
    ) -> Result<Self, rdkafka::error::KafkaError> {
        let mut config = ClientConfig::new();
        config
            .set("bootstrap.servers", &kafka.kafka_hosts)
            .set("group.id", group)
            .set("auto.offset.reset", offset_reset)
            // Offsets move only after a flush has stored the blocks for them.
            .set("enable.auto.commit", "false")
            .set("enable.auto.offset.store", "false")
            .set("partition.assignment.strategy", "cooperative-sticky");
        if kafka.kafka_tls {
            config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }
        if !kafka.kafka_client_rack.is_empty() {
            config.set("client.rack", &kafka.kafka_client_rack);
        }
        let revoked = Arc::new(Mutex::new(Vec::new()));
        let consumer: StreamConsumer<RebalanceContext> =
            config.create_with_context(RebalanceContext {
                revoked: revoked.clone(),
            })?;
        consumer.subscribe(&[topic])?;
        Ok(Self {
            consumer,
            topic: topic.to_owned(),
            revoked,
        })
    }

    fn take_revoked(&self) -> Vec<i32> {
        std::mem::take(&mut *self.revoked.lock().unwrap())
    }

    /// Commits the next offset of every partition this process still owns.
    fn commit(&self, offsets: &std::collections::HashMap<i32, i64>) {
        let assigned = self.consumer.assignment().unwrap_or_default();
        let mut list = TopicPartitionList::new();
        for (&partition, &offset) in offsets {
            if assigned.find_partition(&self.topic, partition).is_some() {
                if let Err(error) =
                    list.add_partition_offset(&self.topic, partition, Offset::Offset(offset + 1))
                {
                    tracing::warn!(%error, partition, "building the offset commit failed");
                }
            }
        }
        if list.count() > 0 {
            if let Err(error) = self.consumer.commit(&list, CommitMode::Async) {
                tracing::warn!(%error, "committing offsets failed");
                counter!("replay_recorder_v4_commit_failures_total").increment(1);
            }
        }
    }
}

fn header<'m>(message: &'m BorrowedMessage<'_>, name: &str) -> Option<&'m str> {
    message
        .headers()?
        .iter()
        .find(|h| h.key == name)
        .and_then(|h| h.value)
        .and_then(|v| std::str::from_utf8(v).ok())
}

/// What a flush needs to store blocks. Without it the recorder runs dry.
pub struct Writer {
    pub keys: KeyStore<CachedKeyTable<AwsKeyTable>, AwsKms>,
    pub store: Arc<dyn BlobStore>,
    pub rrweb_bucket: String,
    pub images_bucket: String,
    /// Images this process stored for their team and day, so a later flush references them without packing them again.
    pub stored_images: moka::sync::Cache<String, ()>,
    pub producer: FutureProducer<KafkaContext>,
    pub image_fetch_topic: String,
    /// Remote image references this process sent to the fetcher for their team and day.
    pub sent_urls: moka::sync::Cache<String, ()>,
}

#[derive(Debug, thiserror::Error)]
pub enum FlushError {
    #[error(transparent)]
    Keys(#[from] replay_core_v4::keys::batch::KeyError),
    #[error(transparent)]
    Write(#[from] WriteError),
    #[error("producing image fetch jobs failed: {0}")]
    Produce(String),
}

pub struct Settings {
    pub sample_percentage: f64,
    pub flush_interval: Duration,
    pub flush_max_bytes: usize,
    pub session_idle: Duration,
    /// The main topic, when the main lane moves its force-overflow messages to the overflow topic.
    pub redirecting_topic: Option<String>,
}

/// What the consume loop reads besides Kafka.
pub struct Sources {
    pub teams: Arc<TeamCache>,
    pub restrictions: Restrictions,
    pub blocklist: Arc<dyn Blocklist>,
}

pub async fn run(
    consumer: RecorderConsumer,
    settings: Settings,
    sources: Sources,
    writer: Option<Writer>,
    handle: Handle,
) {
    let shutdown = handle.shutdown_signal();
    tokio::pin!(shutdown);
    let mut batch = Batch::default();
    let mut inspectors = Inspectors::default();
    let mut tick = tokio::time::interval(Duration::from_secs(1));
    loop {
        tokio::select! {
            _ = &mut shutdown => break,
            _ = tick.tick() => {}
            received = consumer.consumer.recv() => match received {
                Ok(message) => handle_message(&message, &consumer, &settings, &sources, &mut batch).await,
                Err(error) => {
                    tracing::warn!(%error, "kafka receive failed");
                    counter!("replay_recorder_v4_kafka_errors_total").increment(1);
                }
            },
        }
        handle.report_healthy();
        let revoked = consumer.take_revoked();
        if !revoked.is_empty() {
            batch.drop_partitions(&revoked);
            inspectors.drop_partitions(&revoked);
        }
        if batch.should_flush(settings.flush_interval, settings.flush_max_bytes) {
            let mut flushed = std::mem::take(&mut batch);
            drop_blocked(&mut flushed, sources.blocklist.as_ref()).await;
            let (mut blocks, offsets) = inspectors.inspect(flushed);
            if let Err(error) = flush(&mut blocks, writer.as_ref()).await {
                // Nothing of this flush is committed, so a restart reads it again from the last commit.
                tracing::error!(%error, "flush failed");
                handle.signal_failure(format!("flush failed: {error}"));
                break;
            }
            consumer.commit(&offsets);
            inspectors.evict_idle(settings.session_idle);
        }
    }
}

async fn handle_message(
    message: &BorrowedMessage<'_>,
    consumer: &RecorderConsumer,
    settings: &Settings,
    sources: &Sources,
    batch: &mut Batch,
) {
    match admit_message(message, &consumer.topic, settings, sources).await {
        Ok(admitted) => {
            counter!("replay_recorder_v4_messages_total", "outcome" => "admitted").increment(1);
            let session = SessionKey {
                team_id: admitted.team_id,
                session_id: admitted.session_id,
            };
            let raw = Raw {
                offset: message.offset(),
                payload: message.payload().unwrap_or_default().to_vec(),
                content_encoding: header(message, "content-encoding").map(str::to_owned),
            };
            batch.add(message.partition(), session, raw);
        }
        Err(skip) => {
            counter!("replay_recorder_v4_messages_total", "outcome" => skip.as_str()).increment(1);
            batch.handled(message.partition(), message.offset());
        }
    }
}

/// Everything before the payload: the gate on the Kafka key, then the headers, restrictions and team.
async fn admit_message(
    message: &BorrowedMessage<'_>,
    topic: &str,
    settings: &Settings,
    sources: &Sources,
) -> Result<Admitted, Skip> {
    sampled(message.key(), settings.sample_percentage)?;
    let now_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_millis() as i64);
    let headers = Headers {
        token: header(message, "token"),
        session_id: header(message, "session_id"),
        distinct_id: header(message, "distinct_id"),
        event: header(message, "event"),
        uuid: header(message, "uuid"),
    };
    let restriction = sources.restrictions.get(&headers, now_ms / 1000).await;
    let team = headers.token.and_then(|token| sources.teams.get(token));
    let redirect_overflow = settings.redirecting_topic.as_deref() == Some(topic);
    admit(&headers, restriction, redirect_overflow, team, now_ms)
}

/// Drops the sessions the replay lanes blocked, before anything is decoded. The main lane blocks a session when it
/// first sees it. Checking at the flush gives it that time.
async fn drop_blocked(batch: &mut Batch, blocklist: &dyn Blocklist) {
    let sessions: Vec<SessionKey> = batch
        .sessions
        .keys()
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let blocked = blocklist.blocked(&sessions).await;
    if blocked.is_empty() {
        return;
    }
    let messages: usize = batch
        .sessions
        .iter()
        .filter(|(session, _)| blocked.contains(session))
        .map(|(_, pending)| pending.messages.len())
        .sum();
    counter!("replay_recorder_v4_messages_total", "outcome" => Skip::Blocked.as_str())
        .increment(messages as u64);
    batch
        .sessions
        .retain(|session, _| !blocked.contains(session));
}

/// Stores a flush's blocks, or only reports them when the recorder runs dry.
async fn flush(blocks: &mut [Block], writer: Option<&Writer>) -> Result<(), FlushError> {
    counter!("replay_recorder_v4_blocks_total").increment(blocks.len() as u64);
    for block in blocks.iter() {
        counter!("replay_recorder_v4_block_events_total").increment(block.stats.event_count);
        if block.stats.cold_start {
            counter!("replay_recorder_v4_cold_start_blocks_total").increment(1);
        }
        if block.stats.orphan_mutations > 0 {
            counter!("replay_recorder_v4_orphan_mutation_blocks_total").increment(1);
        }
    }
    let Some(writer) = writer else { return Ok(()) };
    let now = Utc::now();
    let day = key_day(now);
    let sessions: Vec<SessionId> = blocks
        .iter()
        .map(|b| SessionId {
            team_id: b.session.team_id,
            session_id: b.session.session_id.clone(),
        })
        .collect();
    // Keys are stored before anything is sealed with them, as in v3.
    let keys = writer.keys.keys_for_flush(&sessions, &day).await?;
    counter!("replay_recorder_v4_dropped_sessions_total").increment(keys.dropped.len() as u64);
    let stored = &writer.stored_images;
    let prepared = prepare(blocks, &keys, &day, &|reference| {
        stored.contains_key(reference)
    });
    // Before the index is written: building the jobs counts each block's image URLs into its stats.
    let jobs = fetch_jobs(blocks, &keys, &day, now.timestamp_millis(), &|reference| {
        writer.sent_urls.contains_key(reference)
    });
    let rows = write_images(
        &prepared.images,
        &keys,
        &day,
        &writer.images_bucket,
        &writer.rrweb_bucket,
        writer.store.as_ref(),
        now,
    )
    .await?;
    for row in &rows {
        stored.insert(row.image_ref.clone(), ());
    }
    counter!("replay_recorder_v4_stored_images_total").increment(rows.len() as u64);
    let written = write_blocks(
        &prepared.blocks,
        &writer.rrweb_bucket,
        writer.store.as_ref(),
        now,
    )
    .await?;
    counter!("replay_recorder_v4_written_blocks_total").increment(written.len() as u64);
    write_block_index(
        blocks,
        &written,
        &keys,
        &writer.rrweb_bucket,
        writer.store.as_ref(),
        now,
    )
    .await?;
    produce_jobs(writer, jobs, now.timestamp_millis()).await?;
    Ok(())
}

/// Sends the flush's fetch jobs and waits for every delivery before the flush commits, as the v3 mirror does.
async fn produce_jobs(
    writer: &Writer,
    jobs: std::collections::BTreeMap<String, Vec<serde_json::Value>>,
    now_ms: i64,
) -> Result<(), FlushError> {
    let captured_at = now_ms.to_string();
    let mut sent = Vec::new();
    for (domain, payload, references) in records(jobs) {
        let headers = OwnedHeaders::new().insert(Header {
            key: "capture-timestamp-ms",
            value: Some(&captured_at),
        });
        let record = FutureRecord::to(&writer.image_fetch_topic)
            .key(&domain)
            .payload(&payload)
            .headers(headers);
        writer
            .producer
            .send(record, Timeout::After(Duration::from_secs(30)))
            .await
            .map_err(|(error, _)| FlushError::Produce(error.to_string()))?;
        sent.extend(references);
    }
    counter!("replay_recorder_v4_image_fetch_jobs_total").increment(sent.len() as u64);
    for reference in sent {
        writer.sent_urls.insert(reference, ());
    }
    Ok(())
}
