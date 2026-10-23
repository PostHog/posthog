//! One attempt to store a flush's blocks. It writes nothing that a retry cannot write again: object names are
//! unique.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::{Arc, Mutex, OnceLock, PoisonError};
use std::time::Duration;

use chrono::Utc;
use common_kafka::kafka_producer::KafkaContext;
use futures::stream::{self, StreamExt};
use metrics::counter;
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use replay_core_v4::inspect::stats::BlockStats;
use replay_core_v4::keys::batch::{FlushKeys, KeyStore, SessionId};
use replay_core_v4::keys::kms::AwsKms;
use replay_core_v4::keys::rows::{key_month, write_day};
use replay_core_v4::keys::table::{AwsKeyTable, CachedKeyTable};
use tokio::sync::Semaphore;

use crate::batch::Block;
use crate::store::BlobStore;
use crate::urls::{fetch_jobs, records};
use crate::write::{
    compress_block, new_images, object_key, seal_blocking, seal_compressed, session_keyed_frames,
    write_block_index, write_blocks, write_images, CompressedBlock, WriteError,
};

/// How long a fetch job may wait for room in the producer queue.
const ENQUEUE_TIMEOUT: Duration = Duration::from_secs(10);

/// Fetch job records sent at once, so a slow broker slows the flush instead of filling the producer queue.
const SENDS_IN_FLIGHT: usize = 64;

/// What a flush needs to store blocks. Without it the recorder runs dry.
pub struct Writer {
    pub keys: KeyStore<CachedKeyTable<AwsKeyTable>, AwsKms>,
    pub store: Arc<dyn BlobStore>,
    pub rrweb_bucket: String,
    pub images_bucket: String,
    pub producer: FutureProducer<KafkaContext>,
    pub image_fetch_topic: String,
    /// Remote image references this process sent to the fetcher, by UTC day. A reference goes out again each day, so
    /// the fetcher sees it within every refresh interval and keeps the image as long as the blocks that reference it.
    pub sent_urls: moka::sync::Cache<(String, String), ()>,
    /// Seals running at once, over all attempts: the flush concurrency.
    pub seal_permits: Arc<Semaphore>,
}

#[derive(Debug, thiserror::Error)]
pub enum FlushError {
    #[error(transparent)]
    Keys(#[from] replay_core_v4::keys::batch::KeyError),
    #[error(transparent)]
    Write(#[from] WriteError),
}

/// What the attempts of one flush share: the keys, the write day they are for, and each block compressed. A retry then
/// only seals again, and a compression that an attempt timed out on goes on and serves the next attempt.
#[derive(Default)]
pub struct FlushWork {
    keys: tokio::sync::Mutex<Option<(String, Arc<FlushKeys>)>>,
    compressed: Mutex<HashMap<usize, Arc<Compressing>>>,
}

type Compressing = OnceLock<Result<Arc<CompressedBlock>, String>>;

impl FlushWork {
    /// The block compressed once. `block` names it by its address, which its `Arc` keeps. A second caller waits for
    /// the first one's result.
    fn compressed(
        &self,
        block: usize,
        compress: impl FnOnce() -> Result<CompressedBlock, WriteError>,
    ) -> Result<Arc<CompressedBlock>, WriteError> {
        let cell = self
            .compressed
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .entry(block)
            .or_default()
            .clone();
        cell.get_or_init(|| compress().map(Arc::new).map_err(|e| e.to_string()))
            .clone()
            .map_err(WriteError::Seal)
    }
}

/// Resolves the keys of the flush's sessions. Keys are stored before anything is sealed with them, as in v3.
async fn resolve_keys(
    blocks: &[Arc<Block>],
    writer: &Writer,
    day: &str,
) -> Result<FlushKeys, FlushError> {
    let sessions: Vec<SessionId> = blocks
        .iter()
        .map(|b| SessionId {
            team_id: b.session.team_id,
            session_id: b.session.session_id.clone(),
        })
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let keys = writer.keys.keys_for_flush(&sessions, day).await?;
    counter!("ai_research_v4_recorder_dropped_sessions_total").increment(keys.dropped.len() as u64);
    Ok(keys)
}

/// Stores the blocks once. Up to `concurrency` blocks are sealed at once off the async runtime, and the packs, and
/// the fetch jobs, go out concurrently.
pub async fn write_flush(
    blocks: &[Arc<Block>],
    writer: &Writer,
    concurrency: usize,
    work: &Arc<FlushWork>,
) -> Result<(), FlushError> {
    let now = Utc::now();
    let mut resolved = work.keys.lock().await;
    let (day, keys) = match &*resolved {
        Some(done) => done.clone(),
        None => {
            let day = write_day(now);
            let keys = Arc::new(resolve_keys(blocks, writer, &day).await?);
            resolved.insert((day, keys)).clone()
        }
    };
    drop(resolved);
    let month = key_month(&day);

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
            let team_key = *keys.team_months.get(&block.session.team_id)?;
            let (block, month, work) = (block.clone(), month.to_owned(), work.clone());
            Some(seal_blocking(&writer.seal_permits, move || {
                let compressed = work.compressed(Arc::as_ptr(&block) as usize, || {
                    compress_block(&block, &key, &team_key, &month)
                })?;
                seal_compressed(&compressed).map(|sealed| (index, sealed))
            }))
        })
        .collect();
    let mut done = Vec::with_capacity(seals.len());
    let results: Vec<_> = stream::iter(seals)
        .buffer_unordered(concurrency.max(1))
        .collect()
        .await;
    for result in results {
        match result {
            Ok(sealed) => done.push(sealed),
            // A panic in one block loses that block only. Its messages are committed with the rest of the flush.
            Err(WriteError::Panicked(error)) => {
                tracing::error!(%error, "sealing a block panicked: the block is dropped");
                counter!("ai_research_v4_recorder_dropped_blocks_total", "outcome" => "panicked")
                    .increment(1);
            }
            Err(error) => return Err(error.into()),
        }
    }
    // Fail closed: a block that still holds a declined URL, a credential or a private host, is not stored.
    done.retain(|(_, block)| {
        let Some(outcome) = block.counts.dropped else {
            return true;
        };
        counter!("ai_research_v4_recorder_dropped_blocks_total", "outcome" => outcome).increment(1);
        false
    });
    let (indices, mut sealed): (Vec<usize>, Vec<_>) = done.into_iter().unzip();

    // This attempt's own copy: a retry fills the writer's columns again from zero.
    let mut stats: Vec<BlockStats> = blocks.iter().map(|b| b.stats.clone()).collect();
    for (&index, block) in indices.iter().zip(&mut sealed) {
        stats[index].images_extracted += block.counts.extracted;
        stats[index].image_bytes += block.counts.bytes;
        stats[index].images_inline += block.counts.inline;
        stats[index].written_jsonl_bytes += block.counts.jsonl_bytes;
        stats[index].max_written_event_bytes = block.counts.max_line_bytes;
        stats[index].url_fingerprints = std::mem::take(&mut block.url_fingerprints);
    }
    // Before the index is written: building the jobs counts each block's image URLs into its stats. A dropped block's
    // images are not stored, so the fetcher does not fetch them.
    let mut kept = vec![false; blocks.len()];
    for &index in &indices {
        kept[index] = true;
    }
    let jobs = fetch_jobs(
        blocks
            .iter()
            .map(|b| &**b)
            .zip(stats.iter_mut())
            .zip(kept)
            .filter_map(|(pair, kept)| kept.then_some(pair)),
        &keys,
        month,
        now.timestamp_millis(),
        &|reference| {
            writer
                .sent_urls
                .contains_key(&(day.clone(), reference.to_owned()))
        },
    );

    let session_frames = session_keyed_frames(&sealed);
    let rows = write_images(
        new_images(&mut sealed),
        &keys,
        &day,
        month,
        &writer.images_bucket,
        &writer.rrweb_bucket,
        &writer.store,
        now,
        concurrency,
        &writer.seal_permits,
    )
    .await?;
    counter!("ai_research_v4_recorder_stored_images_total").increment(rows.len() as u64);
    // What sealing images under session keys would store, to compare with the frames above.
    counter!("ai_research_v4_recorder_session_keyed_image_frames_total").increment(session_frames);

    let written = write_blocks(
        &sealed,
        &object_key,
        &writer.rrweb_bucket,
        writer.store.as_ref(),
    )
    .await?;
    drop(sealed);
    counter!("ai_research_v4_recorder_written_blocks_total").increment(written.len() as u64);
    let entries: Vec<_> = indices
        .iter()
        .zip(&written)
        .map(|(&index, written)| (&*blocks[index], &stats[index], written))
        .collect();
    write_block_index(
        &entries,
        &keys,
        &writer.rrweb_bucket,
        writer.store.as_ref(),
        now,
    )
    .await?;
    produce_jobs(writer, jobs, &day, now.timestamp_millis()).await;
    Ok(())
}

/// Sends every fetch job of the flush, then waits for all deliveries before the flush commits, as the v3 mirror does.
/// A send that fails does not fail the flush, because its blocks are stored by then. The references it did not send
/// stay unmarked, so a later flush that sees them sends them again.
async fn produce_jobs(
    writer: &Writer,
    jobs: BTreeMap<String, Vec<serde_json::Value>>,
    day: &str,
    now_ms: i64,
) {
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
                match writer
                    .producer
                    .send(record, Timeout::After(ENQUEUE_TIMEOUT))
                    .await
                {
                    Ok(_) => Ok(references),
                    Err((error, _)) => Err((references.len(), error)),
                }
            }
        })
        .collect();
    let delivered: Vec<_> = stream::iter(deliveries)
        .buffer_unordered(SENDS_IN_FLIGHT)
        .collect()
        .await;
    let mut sent = Vec::new();
    let mut unsent = 0;
    for delivery in delivered {
        match delivery {
            Ok(references) => sent.extend(references),
            Err((references, error)) => {
                if unsent == 0 {
                    tracing::warn!(%error, "sending image fetch jobs failed");
                }
                unsent += references;
            }
        }
    }
    counter!("ai_research_v4_recorder_image_fetch_jobs_total").increment(sent.len() as u64);
    counter!("ai_research_v4_recorder_image_fetch_jobs_unsent_total").increment(unsent as u64);
    for reference in sent {
        writer.sent_urls.insert((day.to_owned(), reference), ());
    }
    metrics::gauge!("ai_research_v4_recorder_sent_urls").set(writer.sent_urls.entry_count() as f64);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_retry_reuses_the_compressed_block() {
        let work = FlushWork::default();
        let compress = || Err(WriteError::Seal("once".to_owned()));
        assert!(work.compressed(1, compress).is_err());
        let again = work.compressed(1, || panic!("compressed a second time"));
        assert!(matches!(again, Err(WriteError::Seal(e)) if e == "sealing failed: once"));
    }
}
