//! The consume loop: gate, read and admit each message, buffer it, and flush on time or size.

use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use common_kafka::config::KafkaConfig;
use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, Rebalance, StreamConsumer,
};
use rdkafka::message::{BorrowedMessage, Headers, Message as _};
use rdkafka::{ClientConfig, ClientContext, Offset, TopicPartitionList};

use chrono::Utc;
use replay_core_v4::keys::batch::{KeyStore, SessionId};
use replay_core_v4::keys::kms::AwsKms;
use replay_core_v4::keys::rows::{key_month, write_day};
use replay_core_v4::keys::table::{AwsKeyTable, CachedKeyTable};

use crate::batch::{Batch, Block, Inspectors, SessionKey};
use crate::process::{admit, read, sampled};
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
                counter!("ai_research_v4_recorder_commit_failures_total").increment(1);
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
    pub producer: FutureProducer,
    pub image_fetch_topic: String,
    /// Remote image references this process sent to the fetcher, by UTC day. A reference goes out again each day, so
    /// the fetcher sees it within every refresh interval and keeps the image as long as the blocks that reference it.
    pub sent_urls: moka::sync::Cache<(String, String), ()>,
}

#[derive(Debug, thiserror::Error)]
pub enum FlushError {
    #[error(transparent)]
    Keys(#[from] replay_core_v4::keys::batch::KeyError),
    #[error(transparent)]
    Write(#[from] WriteError),
}

pub struct Settings {
    pub sample_percentage: f64,
    pub flush_interval: Duration,
    pub flush_max_bytes: usize,
    pub session_idle: Duration,
}

pub async fn run(
    consumer: RecorderConsumer,
    settings: Settings,
    teams: Arc<TeamCache>,
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
                Ok(message) => handle_message(&message, &settings, &teams, &mut batch),
                Err(error) => {
                    tracing::warn!(%error, "kafka receive failed");
                    counter!("ai_research_v4_recorder_kafka_errors_total").increment(1);
                    // A fatal error disables the client for good, so only a restart recovers.
                    if let Some((code, reason)) = consumer.consumer.client().fatal_error() {
                        handle.signal_failure(format!("kafka consumer fatal error {code}: {reason}"));
                        return;
                    }
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
            let (mut blocks, offsets) = inspectors.inspect(std::mem::take(&mut batch));
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

fn handle_message(
    message: &BorrowedMessage<'_>,
    settings: &Settings,
    teams: &TeamCache,
    batch: &mut Batch,
) {
    let now_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_millis() as i64);
    let admitted = sampled(message.key(), settings.sample_percentage)
        .and_then(|()| {
            read(
                message.payload().unwrap_or_default(),
                header(message, "content-encoding"),
            )
        })
        .and_then(|read| {
            let team = header(message, "token").and_then(|token| teams.get(token));
            admit(&read, team, now_ms).map(|team_id| (team_id, read))
        });
    match admitted {
        Ok((team_id, read)) => {
            counter!("ai_research_v4_recorder_messages_total", "outcome" => "recorded")
                .increment(1);
            let session = SessionKey {
                team_id,
                session_id: read.session_id.clone(),
            };
            batch.add(message.partition(), message.offset(), session, read);
        }
        Err(skip) => {
            counter!("ai_research_v4_recorder_messages_total", "outcome" => skip.as_str())
                .increment(1);
            batch.handled(message.partition(), message.offset());
        }
    }
}

/// Stores a flush's blocks, or only reports them when the recorder runs dry.
async fn flush(blocks: &mut [Block], writer: Option<&Writer>) -> Result<(), FlushError> {
    counter!("ai_research_v4_recorder_blocks_total").increment(blocks.len() as u64);
    for block in blocks.iter() {
        counter!("ai_research_v4_recorder_block_events_total").increment(block.stats.event_count);
        if block.stats.cold_start {
            counter!("ai_research_v4_recorder_cold_start_blocks_total").increment(1);
        }
        if block.stats.orphan_mutations > 0 {
            counter!("ai_research_v4_recorder_orphan_mutation_blocks_total").increment(1);
        }
    }
    let Some(writer) = writer else { return Ok(()) };
    let now = Utc::now();
    let day = write_day(now);
    let month = key_month(&day);
    let sessions: Vec<SessionId> = blocks
        .iter()
        .map(|b| SessionId {
            team_id: b.session.team_id,
            session_id: b.session.session_id.clone(),
        })
        .collect();
    // Keys are stored before anything is sealed with them, as in v3.
    let keys = writer.keys.keys_for_flush(&sessions, &day).await?;
    counter!("ai_research_v4_recorder_dropped_sessions_total").increment(keys.dropped.len() as u64);
    let prepared = prepare(blocks, &keys, month);
    // Before the index is written: building the jobs counts each block's image URLs into its stats.
    // A dropped block's images are not stored, so the fetcher does not fetch them.
    let kept = blocks
        .iter_mut()
        .zip(&prepared.kept)
        .filter_map(|(block, &kept)| kept.then_some(block));
    let jobs = fetch_jobs(kept, &keys, month, now.timestamp_millis(), &|reference| {
        writer
            .sent_urls
            .contains_key(&(day.clone(), reference.to_owned()))
    });
    let rows = write_images(
        &prepared.images,
        &keys,
        &day,
        month,
        &writer.images_bucket,
        &writer.rrweb_bucket,
        writer.store.as_ref(),
        now,
    )
    .await?;
    counter!("ai_research_v4_recorder_stored_images_total").increment(rows.len() as u64);
    // What sealing images under session keys would store, to compare with the frames above.
    counter!("ai_research_v4_recorder_session_keyed_image_frames_total")
        .increment(prepared.session_frames);
    let written = write_blocks(
        &prepared.blocks,
        &writer.rrweb_bucket,
        writer.store.as_ref(),
        now,
    )
    .await?;
    counter!("ai_research_v4_recorder_written_blocks_total").increment(written.len() as u64);
    write_block_index(
        blocks,
        &written,
        &keys,
        &writer.rrweb_bucket,
        writer.store.as_ref(),
        now,
    )
    .await?;
    produce_jobs(writer, jobs, &day, now.timestamp_millis()).await;
    Ok(())
}

/// Sends the flush's fetch jobs and waits for their delivery before the flush commits, as the v3 mirror does. A send
/// that fails does not fail the flush, because its blocks are stored by then. The references it did not send stay
/// unmarked, so a later flush that sees them sends them again.
async fn produce_jobs(
    writer: &Writer,
    jobs: std::collections::BTreeMap<String, Vec<serde_json::Value>>,
    day: &str,
    now_ms: i64,
) {
    let captured_at = now_ms.to_string();
    let records = records(jobs);
    let total: usize = records
        .iter()
        .map(|(_, _, references)| references.len())
        .sum();
    let mut sent = Vec::new();
    for (domain, payload, references) in records {
        let headers = OwnedHeaders::new().insert(Header {
            key: "capture-timestamp-ms",
            value: Some(&captured_at),
        });
        let record = FutureRecord::to(&writer.image_fetch_topic)
            .key(&domain)
            .payload(&payload)
            .headers(headers);
        if let Err((error, _)) = writer
            .producer
            .send(record, Timeout::After(Duration::from_secs(30)))
            .await
        {
            // The next record would wait as long on the same broker.
            tracing::warn!(%error, "sending image fetch jobs failed");
            break;
        }
        sent.extend(references);
    }
    counter!("ai_research_v4_recorder_image_fetch_jobs_total").increment(sent.len() as u64);
    counter!("ai_research_v4_recorder_image_fetch_jobs_unsent_total")
        .increment((total - sent.len()) as u64);
    for reference in sent {
        writer.sent_urls.insert((day.to_owned(), reference), ());
    }
    metrics::gauge!("ai_research_v4_recorder_sent_urls").set(writer.sent_urls.entry_count() as f64);
}
