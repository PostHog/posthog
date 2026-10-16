//! One attempt to store a flush's blocks. It writes nothing that a retry cannot write again: object names are unique,
//! and the block index rows name their attempt.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use common_kafka::kafka_producer::KafkaContext;
use futures::stream::{self, StreamExt, TryStreamExt};
use metrics::counter;
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use replay_core_v4::inspect::stats::BlockStats;
use replay_core_v4::keys::batch::{KeyStore, SessionId};
use replay_core_v4::keys::kms::AwsKms;
use replay_core_v4::keys::rows::key_day;
use replay_core_v4::keys::table::{AwsKeyTable, CachedKeyTable};

use crate::batch::Block;
use crate::store::BlobStore;
use crate::urls::{fetch_jobs, records};
use crate::write::{
    blocking, new_images, object_key, seal_block, write_block_index, write_blocks, write_images,
    FlushAttempt, WriteError,
};

/// How long a fetch job may wait for room in the producer queue.
const ENQUEUE_TIMEOUT: Duration = Duration::from_secs(10);

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

/// Stores the blocks once. Up to `concurrency` blocks are sealed at once off the async runtime, and the packs, and
/// the fetch jobs, go out concurrently.
pub async fn write_flush(
    blocks: &[Arc<Block>],
    writer: &Writer,
    concurrency: usize,
) -> Result<(), FlushError> {
    let now = Utc::now();
    let day = key_day(now);
    let attempt = FlushAttempt::new(now);
    let sessions: Vec<SessionId> = blocks
        .iter()
        .map(|b| SessionId {
            team_id: b.session.team_id,
            session_id: b.session.session_id.clone(),
        })
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    // Keys are stored before anything is sealed with them, as in v3.
    let keys = Arc::new(writer.keys.keys_for_flush(&sessions, &day).await?);
    counter!("replay_recorder_v4_dropped_sessions_total").increment(keys.dropped.len() as u64);

    let object_key = object_key(&day, now);
    let seals: Vec<_> = blocks
        .iter()
        .enumerate()
        .filter_map(|(index, block)| {
            let id = SessionId {
                team_id: block.session.team_id,
                session_id: block.session.session_id.clone(),
            };
            let key = keys.sessions.get(&id)?.clone();
            let team_key = *keys.team_days.get(&block.session.team_id)?;
            let (block, object_key, day) = (block.clone(), object_key.clone(), day.clone());
            let stored = writer.stored_images.clone();
            Some(blocking(move || {
                seal_block(&block, &key, &team_key, &day, &object_key, &|reference| {
                    stored.contains_key(reference)
                })
                .map(|sealed| (index, sealed))
            }))
        })
        .collect();
    let (indices, mut sealed): (Vec<usize>, Vec<_>) = stream::iter(seals)
        .buffered(concurrency.max(1))
        .try_collect::<Vec<_>>()
        .await?
        .into_iter()
        .unzip();

    // This attempt's own copy: a retry fills the writer's columns again from zero.
    let mut stats: Vec<BlockStats> = blocks.iter().map(|b| b.stats.clone()).collect();
    for (&index, block) in indices.iter().zip(&sealed) {
        stats[index].images_extracted += block.counts.extracted;
        stats[index].image_bytes += block.counts.bytes;
        stats[index].images_inline += block.counts.inline;
    }
    // Before the index is written: building the jobs counts each block's image URLs into its stats.
    let jobs = fetch_jobs(
        blocks.iter().map(|b| &**b).zip(stats.iter_mut()),
        &keys,
        &day,
        now.timestamp_millis(),
        &|reference| writer.sent_urls.contains_key(reference),
    );

    let rows = write_images(
        new_images(&mut sealed),
        &keys,
        &day,
        &writer.images_bucket,
        &writer.rrweb_bucket,
        &writer.store,
        now,
        concurrency,
    )
    .await?;
    for row in &rows {
        writer.stored_images.insert(row.image_ref.clone(), ());
    }
    counter!("replay_recorder_v4_stored_images_total").increment(rows.len() as u64);

    let written = write_blocks(
        &sealed,
        &object_key,
        &writer.rrweb_bucket,
        writer.store.as_ref(),
    )
    .await?;
    drop(sealed);
    counter!("replay_recorder_v4_written_blocks_total").increment(written.len() as u64);
    let entries: Vec<_> = indices
        .iter()
        .zip(&written)
        .map(|(&index, written)| (&*blocks[index], &stats[index], written))
        .collect();
    write_block_index(
        &entries,
        &keys,
        &attempt,
        &writer.rrweb_bucket,
        writer.store.as_ref(),
        now,
    )
    .await?;
    produce_jobs(writer, jobs, now.timestamp_millis()).await
}

/// Sends every fetch job of the flush, then waits for all deliveries before the flush commits, as the v3 mirror does.
async fn produce_jobs(
    writer: &Writer,
    jobs: BTreeMap<String, Vec<serde_json::Value>>,
    now_ms: i64,
) -> Result<(), FlushError> {
    let captured_at = now_ms.to_string();
    let deliveries: Vec<_> = records(jobs)
        .into_iter()
        .map(|(domain, payload, references)| {
            let captured_at = &captured_at;
            async move {
                let headers = OwnedHeaders::new().insert(Header {
                    key: "capture-timestamp-ms",
                    value: Some(captured_at),
                });
                let record = FutureRecord::to(&writer.image_fetch_topic)
                    .key(&domain)
                    .payload(&payload)
                    .headers(headers);
                writer
                    .producer
                    .send(record, Timeout::After(ENQUEUE_TIMEOUT))
                    .await
                    .map_err(|(error, _)| FlushError::Produce(error.to_string()))?;
                Ok::<_, FlushError>(references)
            }
        })
        .collect();
    let sent: Vec<String> = futures::future::try_join_all(deliveries)
        .await?
        .into_iter()
        .flatten()
        .collect();
    counter!("replay_recorder_v4_image_fetch_jobs_total").increment(sent.len() as u64);
    for reference in sent {
        writer.sent_urls.insert(reference, ());
    }
    Ok(())
}
