//! Writes a flush: image packs first, then one object of sealed session blocks, and builds the index rows for both.
//!
//! The order matters for a crash between writes. A pack without its blocks is unreferenced, which is harmless. A block
//! whose images were never stored would hold references that resolve to nothing. The rows go out only after both.

use std::borrow::Cow;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::io::{self, Write};
use std::sync::Arc;

use chrono::{DateTime, Utc};
use futures::stream::{self, StreamExt, TryStreamExt};
use metrics::counter;
use rand::Rng;
use replay_core_v4::bytescan::write_json_string;
use replay_core_v4::envelope::{seal_frame, seal_json_envelope, Codec, Context, Version};
use replay_core_v4::inspect::events::event_page_url;
use replay_core_v4::inspect::stats::BlockStats;
use replay_core_v4::inspect::stats::MAX_URL_FINGERPRINTS;
use replay_core_v4::keys::batch::{FlushKeys, SessionId, SessionKey as Key};
use replay_core_v4::refs::url_fingerprint;
use replay_core_v4::scan::cv::{extract_event_images, BeforeImages, Expansion};
use replay_core_v4::scan::images::{Image, ImageLimits, ImageSink};
use replay_core_v4::seal::{image_content_key, url_fingerprint_key};

use tokio::sync::Semaphore;

use crate::batch::{Block, SessionKey};
use crate::index::{BlockIndexRow, ImageIndexRow};
use crate::splice::{DeclinedCopies, Splicer};
use crate::store::{BlobStore, StoreError};

/// Brotli settings for blocks, the same as the v3 lane, which uses the same C encoder. The lane keeps blocks for months
/// and reads them rarely, so it takes the smaller output for more CPU.
const BLOCK_BROTLI_QUALITY: u8 = 9;
const BLOCK_BROTLI_WINDOW_BITS: u8 = 22;
const BLOCK_WRITE_BUFFER: usize = 256 * 1024;

#[derive(Debug, thiserror::Error)]
pub enum WriteError {
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error("sealing failed: {0}")]
    Seal(String),
    #[error("sealing panicked: {0}")]
    Panicked(String),
}

/// Where one block landed, for the block index.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Written {
    pub session: SessionKey,
    pub key_month: String,
    pub object_key: String,
    /// Inclusive byte range of the sealed frame in the object, as v3 records it.
    pub byte_start: u64,
    pub byte_end: u64,
}

/// The columns of a block's stats that the writer fills.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct WriterCounts {
    pub extracted: u32,
    pub bytes: u64,
    pub inline: u32,
    /// The bytes of the lines the writer gives the encoder, and the longest line.
    pub jsonl_bytes: u64,
    pub max_line_bytes: u64,
    /// Why the block must not be stored, as the outcome of its drop: the inspector could not read some of it.
    pub dropped: Option<&'static str>,
    /// Copies of a refused URL that the writer overwrote outside its slot.
    pub overwritten: u64,
}

/// A block compressed once for all the attempts of its flush, with the images it moved out.
pub struct CompressedBlock {
    pub session: SessionKey,
    pub key: Key,
    pub body: Vec<u8>,
    /// Shared, so that each attempt of a flush seals the images without a copy.
    pub images: Vec<Arc<Image>>,
    pub counts: WriterCounts,
    pub url_fingerprints: Vec<String>,
    pub visited_url_fingerprints: Vec<String>,
}

/// A block sealed for one object, with the images it moved out.
pub struct SealedBlock {
    pub session: SessionKey,
    pub key_month: String,
    pub frame: Vec<u8>,
    pub images: Vec<Arc<Image>>,
    pub counts: WriterCounts,
    pub url_fingerprints: Vec<String>,
    pub visited_url_fingerprints: Vec<String>,
}

fn unique_suffix(at: DateTime<Utc>) -> String {
    format!(
        "{}-{:016x}",
        at.timestamp_millis(),
        rand::thread_rng().gen::<u64>()
    )
}

pub fn object_key(write_day: &str, at: DateTime<Utc>) -> String {
    format!("blocks/dt={write_day}/{}", unique_suffix(at))
}

/// Moves a block's images out and writes its lines to `out` in the main lane's format: one `["window_id",event]` line
/// per event. Every image goes into this flush's packs, even one an earlier flush stored: a pack expires by its own
/// write time, so it must be no older than the blocks that reference it.
/// Expanded `cv` events can make a block far larger than its messages, so only one event is held at a time.
fn prepare_block(
    block: &Block,
    team_key: &[u8; 32],
    key_month: &str,
    out: &mut impl Write,
) -> io::Result<(Vec<Image>, WriterCounts)> {
    let content_key = image_content_key(team_key);
    let mut splicer = Splicer::new(&block.edits, block.session.team_id, key_month, team_key);
    let mut declined = DeclinedCopies::new(&block.declined);
    let mut too_many_matches = false;
    let mut images = Vec::new();
    let mut kept = HashSet::new();
    let mut counts = WriterCounts::default();
    let mut event_index = 0;
    for message in &block.messages {
        let mut window = Vec::new();
        write_json_string(
            message.window_id.as_deref().unwrap_or_default(),
            &mut window,
        );
        let mut sink = ImageSink::new(
            &content_key,
            block.session.team_id,
            key_month,
            ImageLimits::default(),
        );
        for event in &message.events {
            let mut overwrite =
                |bytes: &[u8]| match declined.as_mut()?.apply(bytes, &mut counts.overwritten) {
                    Some(Cow::Owned(overwritten)) => Some(overwritten),
                    Some(Cow::Borrowed(_)) => None,
                    None => {
                        too_many_matches = true;
                        None
                    }
                };
            let before_images: Option<&mut BeforeImages<'_>> = Some(&mut overwrite);
            let extracted = match splicer.edits_of(event_index) {
                Some(edits) => {
                    let mut copy = |source, bytes: &[u8], range, out: &mut Vec<u8>| {
                        splicer.copy(edits, source, bytes, range, out)
                    };
                    extract_event_images(
                        &message.inner,
                        event,
                        &mut sink,
                        Some(&mut copy),
                        before_images,
                    )
                }
                None => extract_event_images(&message.inner, event, &mut sink, None, before_images),
            };
            event_index += 1;
            if too_many_matches {
                let counts = WriterCounts {
                    dropped: Some("too_many_declined_copies"),
                    ..WriterCounts::default()
                };
                return Ok((Vec::new(), counts));
            }
            let event_bytes = extracted
                .as_deref()
                .unwrap_or(&message.inner[event.span.0..event.span.1]);
            out.write_all(b"[")?;
            out.write_all(&window)?;
            out.write_all(b",")?;
            out.write_all(event_bytes)?;
            out.write_all(b"]\n")?;
            let line = (window.len() + event_bytes.len() + 4) as u64;
            counts.jsonl_bytes += line;
            counts.max_line_bytes = counts.max_line_bytes.max(line);
        }
        counts.extracted += sink.images.len() as u32;
        counts.bytes += sink
            .images
            .iter()
            .map(|i| i.bytes.len() as u64)
            .sum::<u64>();
        counts.inline += sink.left_inline;
        for (removed, declined) in splicer
            .counters
            .removed_images
            .iter_mut()
            .zip(sink.declined)
        {
            *removed += u64::from(declined);
        }
        images.extend(
            sink.images
                .into_iter()
                .filter(|image| kept.insert(image.reference.clone())),
        );
    }
    splicer.counters.emit();
    Ok((images, counts))
}

/// Why a block must not be stored: the inspector could not read some of it, so a URL there went unchecked.
fn unread(block: &Block) -> Option<&'static str> {
    if block.unplaced {
        return Some("unplaced_slot");
    }
    if let Some(limit) = block.url_limit {
        return Some(limit.label());
    }
    // A block stores such an event as it arrived, with its compressed strings unread.
    let undecoded = block
        .messages
        .iter()
        .flat_map(|message| &message.events)
        .any(|event| {
            matches!(
                event.expansion,
                Some(Expansion::Skipped | Expansion::Failed)
            )
        });
    undecoded.then_some("undecoded_events")
}

/// Writes a block's lines to an output from `open`, or drops a block that the inspector could not read in full.
/// A dropped block gets a new output, so that none of its lines are stored.
pub fn write_block<W: Write>(
    block: &Block,
    team_key: &[u8; 32],
    key_month: &str,
    mut open: impl FnMut() -> io::Result<W>,
) -> io::Result<(W, Vec<Image>, WriterCounts)> {
    if let Some(reason) = unread(block) {
        let counts = WriterCounts {
            dropped: Some(reason),
            ..WriterCounts::default()
        };
        return Ok((open()?, Vec::new(), counts));
    }
    let mut out = open()?;
    let (images, counts) = prepare_block(block, team_key, key_month, &mut out)?;
    if counts.dropped.is_some() {
        return Ok((open()?, images, counts));
    }
    Ok((out, images, counts))
}

fn block_encoder() -> Result<brotlic::BrotliEncoder, WriteError> {
    let seal_error = |e: brotlic::SetParameterError| WriteError::Seal(e.to_string());
    brotlic::BrotliEncoderOptions::new()
        .quality(brotlic::Quality::new(BLOCK_BROTLI_QUALITY).map_err(seal_error)?)
        .window_size(brotlic::WindowSize::new(BLOCK_BROTLI_WINDOW_BITS).map_err(seal_error)?)
        .build()
        .map_err(seal_error)
}

/// Builds, compresses and seals one block for `object_key`. The key is in the frame's authenticated data, so a
/// frame does not open from another object, even one of the same session.
pub fn seal_block(
    block: &Block,
    key: &Key,
    team_key: &[u8; 32],
    key_month: &str,
    object_key: &str,
) -> Result<SealedBlock, WriteError> {
    seal_compressed(
        &compress_block(block, key, team_key, key_month)?,
        object_key,
    )
}

/// Builds and compresses one block. This is most of the work of a flush, so a retry does not do it again.
pub fn compress_block(
    block: &Block,
    key: &Key,
    team_key: &[u8; 32],
    key_month: &str,
) -> Result<CompressedBlock, WriteError> {
    let seal_error = |e: io::Error| WriteError::Seal(e.to_string());
    // Lines go into the encoder as they are built, so memory follows the compressed block and not its plaintext.
    // A brotli stream does not state its decompressed size, so a reader decompresses it as a stream.
    // The encoder works on each write it gets, so small writes cost far more CPU than the same bytes in one.
    let open = || {
        block_encoder()
            .map(|encoder| {
                io::BufWriter::with_capacity(
                    BLOCK_WRITE_BUFFER,
                    brotlic::CompressorWriter::with_encoder(encoder, Vec::new()),
                )
            })
            .map_err(|e| io::Error::other(e.to_string()))
    };
    let (lines, images, counts) =
        write_block(block, team_key, key_month, open).map_err(seal_error)?;
    counter!("ai_research_v4_recorder_overwritten_declined_copies_total")
        .increment(counts.overwritten);
    let encoder = lines.into_inner().map_err(|e| seal_error(e.into_error()))?;
    let body = encoder
        .into_inner()
        .map_err(|e| WriteError::Seal(e.to_string()))?;
    Ok(CompressedBlock {
        session: block.session.clone(),
        key: key.clone(),
        body,
        images: images.into_iter().map(Arc::new).collect(),
        counts,
        url_fingerprints: url_fingerprints(&key.key, &block_urls(block)),
        visited_url_fingerprints: visited_url_fingerprints(&key.key, &block.visited_urls),
    })
}

/// Seals a compressed block for one attempt's `object_key`.
pub fn seal_compressed(
    block: &CompressedBlock,
    object_key: &str,
) -> Result<SealedBlock, WriteError> {
    let frame = seal_frame(
        &block.key.key,
        Version::V4,
        &block_context(&block.session, &block.key.key_month, object_key),
        &block.body,
    )
    .map_err(|e| WriteError::Seal(e.to_string()))?;
    Ok(SealedBlock {
        session: block.session.clone(),
        key_month: block.key.key_month.clone(),
        frame,
        images: block.images.clone(),
        counts: block.counts,
        url_fingerprints: block.url_fingerprints.clone(),
        visited_url_fingerprints: block.visited_url_fingerprints.clone(),
    })
}

/// The authenticated data of a block frame.
pub fn block_context(session: &SessionKey, key_month: &str, object_key: &str) -> Context {
    Context {
        team_id: session.team_id,
        session_id: Some(session.session_id.clone()),
        key_month: Some(key_month.to_owned()),
        kind: "rrweb".to_owned(),
        codec: Some(Codec::Brotli),
        reference: Some(object_key.to_owned()),
        ..Context::default()
    }
}

/// The frames the flush's packs would hold if each session sealed its images under its own key: one per distinct
/// (session, reference) pair, where [`new_images`] keeps one per reference.
pub fn session_keyed_frames(sealed: &[SealedBlock]) -> u64 {
    let pairs: HashSet<(&str, &str)> = sealed
        .iter()
        .flat_map(|block| {
            let session = block.session.session_id.as_str();
            block
                .images
                .iter()
                .map(move |image| (session, image.reference.as_str()))
        })
        .collect();
    pairs.len() as u64
}

/// The flush's new images by team, each once.
pub fn new_images(sealed: &mut [SealedBlock]) -> BTreeMap<i64, Vec<Arc<Image>>> {
    let mut images: BTreeMap<i64, Vec<Arc<Image>>> = BTreeMap::new();
    let mut seen: HashSet<String> = HashSet::new();
    for block in sealed {
        for image in std::mem::take(&mut block.images) {
            if seen.insert(image.reference.clone()) {
                images.entry(block.session.team_id).or_default().push(image);
            }
        }
    }
    images
}

fn seal_pack(
    team_id: i64,
    team_images: &[Arc<Image>],
    team_key: &[u8; 32],
    key_month: &str,
    pack_key: &str,
) -> Result<(Vec<u8>, Vec<ImageIndexRow>), WriteError> {
    let mut pack = Vec::new();
    let mut rows = Vec::with_capacity(team_images.len());
    for image in team_images {
        let context = Context {
            team_id,
            key_month: Some(key_month.to_owned()),
            kind: "image".to_owned(),
            codec: Some(Codec::None),
            reference: Some(image.reference.clone()),
            ..Context::default()
        };
        let frame = seal_frame(team_key, Version::V4, &context, &image.bytes)
            .map_err(|e| WriteError::Seal(e.to_string()))?;
        let byte_start = pack.len() as u64;
        pack.extend_from_slice(&frame);
        rows.push(ImageIndexRow {
            team_id,
            key_month: key_month.to_owned(),
            image_ref: image.reference.clone(),
            pack_s3_key: pack_key.to_owned(),
            byte_start,
            byte_end: pack.len() as u64 - 1,
            mime: image.mime.to_owned(),
            byte_size: image.bytes.len() as u64,
        });
    }
    Ok((pack, rows))
}

/// Seals each team's images under its team month key into one pack and stores the packs concurrently. Returns the
/// image index rows of the stored packs.
#[allow(clippy::too_many_arguments)]
pub async fn write_images(
    images: BTreeMap<i64, Vec<Arc<Image>>>,
    keys: &FlushKeys,
    write_day: &str,
    key_month: &str,
    images_bucket: &str,
    store: &Arc<dyn BlobStore>,
    at: DateTime<Utc>,
    concurrency: usize,
    permits: &Arc<Semaphore>,
) -> Result<Vec<ImageIndexRow>, WriteError> {
    let packs: Vec<_> = images
        .into_iter()
        .filter_map(|(team_id, team_images)| {
            let team_key = *keys.team_months.get(&team_id)?;
            let pack_key = format!(
                "images/packs/dt={write_day}/{team_id}/{}",
                unique_suffix(at)
            );
            let key_month = key_month.to_owned();
            let store = store.clone();
            Some(async move {
                let key = pack_key.clone();
                let (pack, rows) = seal_blocking(permits, move || {
                    seal_pack(team_id, &team_images, &team_key, &key_month, &key)
                })
                .await?;
                store.put_new(images_bucket, &pack_key, pack).await?;
                Ok::<_, WriteError>(rows)
            })
        })
        .collect();
    Ok(stream::iter(packs)
        .buffer_unordered(concurrency.max(1))
        .try_collect::<Vec<_>>()
        .await?
        .into_iter()
        .flatten()
        .collect())
}

/// Writes the flush's sealed blocks as one object. Returns where each landed, in the same order.
pub async fn write_blocks(
    blocks: &[SealedBlock],
    object_key: &str,
    bucket: &str,
    store: &dyn BlobStore,
) -> Result<Vec<Written>, WriteError> {
    let mut object = Vec::with_capacity(blocks.iter().map(|b| b.frame.len()).sum());
    let mut written = Vec::with_capacity(blocks.len());
    for block in blocks {
        let byte_start = object.len() as u64;
        object.extend_from_slice(&block.frame);
        written.push(Written {
            session: block.session.clone(),
            key_month: block.key_month.clone(),
            object_key: object_key.to_owned(),
            byte_start,
            byte_end: object.len() as u64 - 1,
        });
    }
    if !written.is_empty() {
        store.put_new(bucket, object_key, object).await?;
    }
    Ok(written)
}

/// Runs CPU work off the async runtime.
pub async fn blocking<T: Send + 'static>(
    work: impl FnOnce() -> Result<T, WriteError> + Send + 'static,
) -> Result<T, WriteError> {
    tokio::task::spawn_blocking(work).await.map_err(|e| {
        if e.is_panic() {
            WriteError::Panicked(e.to_string())
        } else {
            WriteError::Seal(e.to_string())
        }
    })?
}

/// Runs a seal off the async runtime under one of `permits`. The seal holds its permit until it ends, so the seals of
/// an attempt that timed out still count against the limit.
pub async fn seal_blocking<T: Send + 'static>(
    permits: &Arc<Semaphore>,
    work: impl FnOnce() -> Result<T, WriteError> + Send + 'static,
) -> Result<T, WriteError> {
    let permit = permits
        .clone()
        .acquire_owned()
        .await
        .map_err(|e| WriteError::Seal(e.to_string()))?;
    blocking(move || {
        let _permit = permit;
        work()
    })
    .await
}

/// The pages a block visited, from its Meta events, in order and without repeats in a row.
/// An SPA navigation, as a `$url_changed` custom event, counts as a visit too.
pub fn block_urls(block: &Block) -> Vec<String> {
    let mut urls: Vec<String> = Vec::new();
    for message in &block.messages {
        for event in &message.events {
            if let Some(href) = event_page_url(&message.inner, event) {
                if urls.last() != Some(&href) {
                    urls.push(href);
                }
            }
        }
    }
    urls
}

/// The most visited pages a block index row keeps, the longest page it keeps and their bytes together. The sealed list
/// then stays far below the index producer's message limit of 1,000,000 bytes with the row's other columns, and a
/// Parquet page of these values stays small.
const MAX_INDEX_URLS: usize = 100;
const MAX_INDEX_URL_BYTES: usize = 2048;
const MAX_INDEX_URLS_BYTES: usize = 32 * 1024;

/// The visited pages that fit in a block index row, in order, and whether any page was left out.
pub fn index_urls(urls: Vec<String>) -> (Vec<String>, bool) {
    let mut kept = Vec::new();
    let mut bytes = 0;
    let mut truncated = false;
    for url in urls {
        if kept.len() >= MAX_INDEX_URLS || bytes + url.len() > MAX_INDEX_URLS_BYTES {
            truncated = true;
            break;
        }
        if url.len() > MAX_INDEX_URL_BYTES {
            truncated = true;
            continue;
        }
        bytes += url.len();
        kept.push(url);
    }
    (kept, truncated)
}

/// The block's distinct pages as fingerprints under the session's fingerprint key, the first
/// [`MAX_URL_FINGERPRINTS`] in the order the block saw them.
pub fn url_fingerprints(session_key: &[u8; 32], urls: &[String]) -> Vec<String> {
    let key = url_fingerprint_key(session_key);
    let mut fingerprints = Vec::new();
    for url in urls {
        if fingerprints.len() >= MAX_URL_FINGERPRINTS {
            break;
        }
        let fingerprint = url_fingerprint(&key, url);
        if !fingerprints.contains(&fingerprint) {
            fingerprints.push(fingerprint);
        }
    }
    fingerprints
}

/// The block's distinct visited pages for its surfacing features, as fingerprints under the session's fingerprint key,
/// sorted.
pub fn visited_url_fingerprints(session_key: &[u8; 32], urls: &[String]) -> Vec<String> {
    let key = url_fingerprint_key(session_key);
    let mut fingerprints: Vec<String> = urls.iter().map(|url| url_fingerprint(&key, url)).collect();
    fingerprints.sort_unstable();
    fingerprints.dedup();
    fingerprints
}

/// Numbers the rows of each partition in order and gives each row the count of its partition.
fn number_rows(rows: &mut [BlockIndexRow<'_>]) {
    let mut counts: HashMap<(&str, i32), u32> = HashMap::new();
    for row in rows.iter_mut() {
        let count = counts.entry((row.topic, row.partition)).or_default();
        row.flush_row_index = *count;
        *count += 1;
    }
    for row in rows.iter_mut() {
        row.flush_row_count = counts[&(row.topic, row.partition)];
    }
}

/// Which flush attempt wrote a block index row. See `crate::index` for how readers use it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FlushAttempt {
    pub flush_id: String,
    pub flushed_at_ms: i64,
}

impl FlushAttempt {
    pub fn new(at: DateTime<Utc>) -> Self {
        Self {
            flush_id: format!("{:016x}", rand::thread_rng().gen::<u64>()),
            flushed_at_ms: at.timestamp_millis(),
        }
    }
}

/// The flush's block index rows, built after its blocks are stored, so no row points at a block that is not.
/// Each entry is a block, its stats as this attempt filled them, and where it landed.
pub fn block_index_rows<'a>(
    entries: &[(&'a Block, &'a BlockStats, &'a Written)],
    keys: &FlushKeys,
    attempt: &'a FlushAttempt,
) -> Result<Vec<BlockIndexRow<'a>>, WriteError> {
    let mut rows = Vec::with_capacity(entries.len());
    for &(block, stats, written) in entries {
        let id = SessionId {
            team_id: written.session.team_id,
            session_id: written.session.session_id.clone(),
        };
        let Some(key) = keys.sessions.get(&id) else {
            continue;
        };
        let (urls, urls_truncated) = index_urls(block_urls(block));
        if urls_truncated {
            counter!("ai_research_v4_recorder_index_urls_truncated_total").increment(1);
        }
        let urls = if urls.is_empty() {
            None
        } else {
            let context = Context {
                team_id: id.team_id,
                session_id: Some(id.session_id.clone()),
                key_month: Some(key.key_month.clone()),
                kind: "index".to_owned(),
                reference: Some("urls".to_owned()),
                ..Context::default()
            };
            let json = serde_json::to_vec(&urls).map_err(|e| WriteError::Seal(e.to_string()))?;
            Some(
                seal_json_envelope(&key.key, Version::V4, &context, &json)
                    .map_err(|e| WriteError::Seal(e.to_string()))?
                    .to_string(),
            )
        };
        let first = block.messages.first();
        rows.push(BlockIndexRow {
            team_id: written.session.team_id,
            session_id: &written.session.session_id,
            key_month: &written.key_month,
            block_s3_key: &written.object_key,
            topic: block.origin.tp.topic,
            partition: block.origin.tp.partition,
            start_offset: block.origin.start_offset,
            end_offset: block.origin.end_offset,
            flush_end_offset: block.origin.flush_end_offset,
            flush_row_count: 0,
            flush_row_index: 0,
            flush_id: &attempt.flush_id,
            flushed_at_ms: attempt.flushed_at_ms,
            block_byte_start: written.byte_start,
            block_byte_end: written.byte_end,
            stats,
            snapshot_source: first.and_then(|m| m.snapshot_source.as_deref()),
            snapshot_library: first.and_then(|m| m.library.as_deref()),
            moments: &block.moments,
            urls,
            urls_truncated,
            captured_at_ms: block.captured_at_ms,
        });
    }
    number_rows(&mut rows);
    Ok(rows)
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::io::Read;
    use std::sync::Mutex;

    use aes_gcm::aead::{Aead, KeyInit, Payload};
    use aes_gcm::{Aes256Gcm, Nonce};
    use async_trait::async_trait;
    use base64::engine::general_purpose::STANDARD;
    use base64::Engine;
    use replay_core_v4::envelope::open_frame;
    use replay_core_v4::inspect::session::Moment;
    use replay_core_v4::scan::message::read_message;
    use serde_json::{json, Value};

    use super::*;
    use crate::batch::{Origin, Tp};
    use replay_core_v4::refs::UrlAsset;

    #[derive(Default)]
    struct MemoryStore {
        objects: Mutex<HashMap<(String, String), Vec<u8>>>,
    }

    impl MemoryStore {
        fn get(&self, bucket: &str, key: &str) -> Vec<u8> {
            self.objects.lock().unwrap()[&(bucket.to_owned(), key.to_owned())].clone()
        }
    }

    fn decompress(compressed: &[u8]) -> io::Result<Vec<u8>> {
        let mut plain = Vec::new();
        brotlic::DecompressorReader::new(compressed).read_to_end(&mut plain)?;
        Ok(plain)
    }

    #[async_trait]
    impl BlobStore for MemoryStore {
        async fn put_new(&self, bucket: &str, key: &str, body: Vec<u8>) -> Result<(), StoreError> {
            self.objects
                .lock()
                .unwrap()
                .entry((bucket.to_owned(), key.to_owned()))
                .or_insert(body);
            Ok(())
        }

        async fn put(&self, bucket: &str, key: &str, body: Vec<u8>) -> Result<(), StoreError> {
            self.objects
                .lock()
                .unwrap()
                .insert((bucket.to_owned(), key.to_owned()), body);
            Ok(())
        }
    }

    fn origin(partition: i32, start_offset: i64, end_offset: i64) -> Origin {
        Origin {
            tp: Tp {
                topic: "main",
                partition,
            },
            start_offset,
            end_offset,
            flush_end_offset: end_offset,
        }
    }

    fn block(session: &str, events: Value) -> Block {
        block_of(session, &events.to_string())
    }

    /// A block of the events JSON as it is written, escapes included.
    fn block_of(session: &str, events: &str) -> Block {
        let inner = format!(
            r#"{{"event":"$snapshot_items","properties":{{"$session_id":"{session}","$window_id":"w1","$snapshot_items":{events}}}}}"#
        );
        let message = read_message(
            json!({"distinct_id": "d", "data": inner})
                .to_string()
                .into_bytes(),
        )
        .unwrap();
        Block {
            session: SessionKey {
                team_id: 7,
                session_id: session.to_owned(),
            },
            origin: origin(0, 100, 105),
            messages: vec![message],
            stats: BlockStats::default(),
            moments: Vec::new(),
            image_urls: Vec::new(),
            font_urls: Vec::new(),
            url_limit: None,
            edits: Vec::new(),
            declined: Vec::new(),
            unplaced: false,
            visited_urls: Vec::new(),
            captured_at_ms: None,
        }
    }

    /// PNG bytes: the signature, then `body`. The image scan takes only bytes of a raster format.
    fn png(body: &[u8]) -> Vec<u8> {
        [b"\x89PNG\r\n\x1a\n".as_slice(), body].concat()
    }

    fn uri(body: &[u8]) -> String {
        format!("data:image/png;base64,{}", STANDARD.encode(png(body)))
    }

    /// The block's stored lines, after the inspector named its remote URLs.
    fn stored_lines(events: &str) -> String {
        stored(block_of("kept", events))
    }

    fn stored(inspected: Block) -> String {
        let (lines, counts) = written(inspected);
        if counts.dropped.is_some() {
            return String::new();
        }
        lines
    }

    fn written(block: Block) -> (String, WriterCounts) {
        let inspected = inspected(block);
        let (lines, _, counts) =
            write_block(&inspected, &[6; 32], "2026-10", || Ok(Vec::new())).unwrap();
        (String::from_utf8(lines).unwrap(), counts)
    }

    /// The block with what the session inspector finds in it, as a flush hands it to the writer.
    fn inspected(mut inspected: Block) -> Block {
        let mut inspector = replay_core_v4::inspect::session::SessionInspector::default();
        let mut inspection = replay_core_v4::inspect::session::BlockInspection::default();
        for message in &inspected.messages {
            inspector.observe_message(&mut inspection, message);
        }
        let found = inspection.finish();
        inspected.image_urls = found.image_urls;
        inspected.font_urls = found.font_urls;
        inspected.url_limit = found.url_limit;
        inspected.edits = found.edits;
        inspected.declined = found.declined;
        inspected.unplaced = found.unplaced;
        inspected
    }

    #[test]
    fn replaces_the_sources_of_a_node_the_inspector_does_not_know() {
        let (signed, public) = (
            "https://bucket.s3.amazonaws.com/avatar.png?X-Amz-Signature=abc123",
            "HTTPS://cdn.example.com/avatar.png",
        );
        // This process never saw node 99: the session started before a restart.
        let events = json!([{"type": 3, "timestamp": 1, "data": {"source": 0, "adds": [], "removes": [], "texts": [],
            "attributes": [{"id": 99, "attributes": {"src": signed, "srcset": format!("{public} 2x")}}]}}])
        .to_string();
        let lines = stored_lines(&events);
        let reference = crate::urls::url_reference(
            public,
            replay_core_v4::refs::UrlAsset::Image,
            7,
            "2026-10",
            &replay_core_v4::seal::image_url_key(&[6; 32]),
        )
        .unwrap()
        .1;
        assert!(
            lines.contains(&format!(
                r#""src":"imageurl:v4:declined:credential","srcset":"{reference} 2x""#
            )),
            "{lines}"
        );
        // A URL past the length the fetcher takes is named and declined.
        let long = |len: usize| {
            let url = format!("https://cdn.example.com/{}", "a".repeat(len - 24));
            json!([{"type": 3, "timestamp": 1, "data": {"source": 0, "adds": [], "removes": [], "texts": [],
                "attributes": [{"id": 99, "attributes": {"src": url}}]}}])
            .to_string()
        };
        // A URL too long to fetch is declined, and the block is kept.
        let long_lines = stored_lines(&long(16 * 1024));
        assert!(
            long_lines.contains("imageurl:v4:declined:too_long"),
            "{long_lines}"
        );
        // Keys written with escapes hide no URL.
        let escaped = events
            .replace(r#""src""#, r#""\u0073rc""#)
            .replace(r#""srcset""#, r#""src\u0073et""#);
        assert_eq!(stored_lines(&escaped), lines);
        // A browser reads backslashes after the scheme as slashes, so such a URL is replaced like its `https://` form.
        for backslashed in [
            r"https:\\user:secret@cdn.example.com/a.png",
            r"https:/\user:secret@cdn.example.com/a.png",
            "https:user:secret@cdn.example.com/a.png",
        ] {
            let events = json!([{"type": 3, "timestamp": 1, "data": {"source": 0, "adds": [], "removes": [], "texts": [],
                "attributes": [{"id": 99, "attributes": {"src": backslashed}}]}}])
            .to_string();
            let lines = stored_lines(&events);
            assert!(
                lines.contains("imageurl:v4:declined:credential") && !lines.contains("secret"),
                "{lines}"
            );
        }
        // The player loads the last of a repeated attribute, so the inspector names that one.
        for events in [
            format!(
                r#"[{{"type":3,"timestamp":1,"data":{{"source":0,"adds":[],"removes":[],"texts":[],"attributes":[{{"id":99,"attributes":{{"src":"{public}","src":"{signed}"}}}}]}}}}]"#
            ),
            format!(
                r#"[{{"type":3,"timestamp":1,"data":{{"source":0,"adds":[{{"parentId":1,"node":{{"type":2,"tagName":"img","attributes":{{"src":"{public}","src":"{signed}"}},"childNodes":[],"id":5}}}}],"removes":[],"texts":[],"attributes":[]}}}}]"#
            ),
        ] {
            let lines = stored_lines(&events);
            assert!(
                lines.contains("imageurl:v4:declined:credential")
                    && !lines.contains("X-Amz-Signature"),
                "{lines}"
            );
        }
        // A declined URL that a longer URL also holds is overwritten there too, and the block is kept, also for a bundled font, which names no URL, and for an escaped font URL, as the scan decodes it, of a bundled family too.
        let bundled_font = json!({"parentId": 1, "node": {"type": 2, "tagName": "style",
            "attributes": {"_cssText": format!("@font-face{{font-family:Roboto;src:url({signed})}}")}, "childNodes": [], "id": 5}});
        let escaped_font = |family: &str, host: &str| {
            json!({"parentId": 1, "node": {"type": 2, "tagName": "style",
            "attributes": {"_cssText": format!("@font-face{{font-family:{family};src:url(https://{host}/f\\2e woff2?X-Amz-Signature=abc123)}}")}, "childNodes": [], "id": 6}})
        };
        let overlapping =
            "https://a.example/?X-Amz-Signature=x&next=https://b.example/?X-Amz-Signature=abc123";
        // Image extraction changes the copy's inline image, so the writer overwrites the copy before it.
        let with_inline_image = "https://cdn.example.com/a?X-Amz-Signature=abc123&x=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
        let decoded_font_copy =
            |host: &str| json!({"alt": format!("https://{host}/f.woff2?X-Amz-Signature=abc123")});
        for (adds, attributes) in [
            (
                json!([]),
                json!({"src": signed, "alt": format!("{signed}&size=2")}),
            ),
            (
                json!([bundled_font]),
                json!({"alt": format!("{signed}&size=2")}),
            ),
            (
                json!([escaped_font("Brand", "bucket.s3.amazonaws.com")]),
                decoded_font_copy("bucket.s3.amazonaws.com"),
            ),
            // The URL parser lowercases the host, and a copy keeps the spelling the page wrote.
            (
                json!([escaped_font("Brand", "CDN.example.com")]),
                decoded_font_copy("CDN.example.com"),
            ),
            // A text copy of the rule keeps its CSS escapes.
            (
                json!([escaped_font("Brand", "bucket.s3.amazonaws.com")]),
                json!({"alt": "url(https://bucket.s3.amazonaws.com/f\\2e woff2?X-Amz-Signature=abc123)"}),
            ),
            (
                json!([]),
                json!({"src": with_inline_image, "alt": with_inline_image}),
            ),
            (
                json!([escaped_font("Roboto", "bucket.s3.amazonaws.com")]),
                decoded_font_copy("bucket.s3.amazonaws.com"),
            ),
            (
                json!([{"parentId": 1, "node": {"type": 2, "tagName": "div", "attributes": {"style": "background-image:url('\\2f \\2f cdn.example.com/a.png?X-Amz-Signature=abc123')"}, "childNodes": [], "id": 9}}]),
                json!({"alt": "//cdn.example.com/a.png?X-Amz-Signature=abc123"}),
            ),
            (
                json!([
                    {"parentId": 1, "node": {"type": 2, "tagName": "img", "attributes": {"src": "https://a.example/?X-Amz-Signature=x&next=https://b.example/"}, "childNodes": [], "id": 7}},
                    {"parentId": 1, "node": {"type": 2, "tagName": "img", "attributes": {"src": "https://b.example/?X-Amz-Signature=abc123"}, "childNodes": [], "id": 8}},
                ]),
                json!({"alt": format!("{overlapping} {} {overlapping}", "x".repeat(200))}),
            ),
        ] {
            let events = json!([{"type": 3, "timestamp": 1, "data": {"source": 0, "adds": adds, "removes": [], "texts": [],
                "attributes": [{"id": 99, "attributes": attributes}]}}])
            .to_string();
            let lines = stored_lines(&events);
            assert!(
                !lines.is_empty() && !lines.contains("X-Amz-Signature"),
                "{lines}"
            );
        }
    }

    #[test]
    fn names_every_url_in_place_however_many_a_block_holds() {
        let link = || json!({"type": 2, "tagName": "a", "attributes": {"href": "https://app.example.com/pricing"}, "childNodes": [], "id": 1_000_000});
        let mut images: Vec<_> = (0..=10_000)
            .map(|i| json!({"type": 2, "tagName": "img", "attributes": {"src": format!("https://cdn.example.com/{i}.png")}, "childNodes": [], "id": i + 2}))
            .collect();
        images.push(link());
        let faces: String = (0..=4_096)
            .map(|i| format!("@font-face{{font-family:Brand{i};src:url(https://fonts.example.com/{i}.woff2)}}"))
            .collect();
        let fonts = vec![
            json!({"type": 2, "tagName": "style", "attributes": {"_cssText": faces}, "childNodes": [], "id": 2}),
            link(),
            json!({"type": 2, "tagName": "style", "attributes": {"_cssText": "@\\66 ont-face{font-family:Escaped;src:url(https://fonts.example.com/escaped.woff2)}"}, "childNodes": [], "id": 4}),
        ];
        // An escaped URL takes a rewrite of its whole `url()`, also where a line continuation splits its scheme.
        let escaped_faces: String = (0..=10_000)
            .map(|i| format!("@font-face{{font-family:Escaped{i};src:url(https://fonts.example.com/{i}\\2e woff2)}}"))
            .collect();
        let split_face = "@font-face{font-family:Split;src:url(\"htt\\\nps://fonts.example.com/split.woff2?token=secret\")}";
        let escaped_fonts = vec![
            json!({"type": 2, "tagName": "style", "attributes": {"_cssText": escaped_faces}, "childNodes": [], "id": 2}),
            link(),
            json!({"type": 2, "tagName": "style", "attributes": {"_cssText": split_face}, "childNodes": [], "id": 4}),
        ];
        for (nodes, named, references, declined) in [
            (images, "imageurl:v4:7:2026-10:", 10_001, 0),
            (fonts, "fonturl:v4:7:2026-10:", 4_098, 0),
            (escaped_fonts, "fonturl:v4:7:2026-10:", 10_001, 1),
        ] {
            let events = json!([{"type": 2, "timestamp": 1, "data": {"node": {"type": 0, "id": 1, "childNodes": nodes}}}]).to_string();
            let lines = stored_lines(&events);
            assert_eq!(lines.matches(named).count(), references);
            assert_eq!(
                lines.matches("fonturl:v4:declined:credential").count(),
                declined
            );
            for raw in [
                "https://cdn.",
                "https://fonts.",
                "token=secret",
                "declined:unchecked",
            ] {
                assert!(!lines.contains(raw), "{raw}");
            }
            assert!(lines.contains("https://app.example.com/pricing"));
        }
    }

    #[test]
    fn drops_a_block_the_inspector_could_not_read_in_full() {
        let deep_face = format!(
            "{}@font-face{{font-family:Deep;src:url(\"https://fonts.example.com/deep.woff2?token=secret\")}}{}",
            "@media all{".repeat(80),
            "}".repeat(80)
        );
        let deep_value = format!(
            "background-image:{}url('https://cdn.example.com/deep.png?token=secret'){}",
            "var(--a,".repeat(80),
            ")".repeat(80)
        );
        for node in [
            json!({"type": 2, "tagName": "style", "attributes": {"_cssText": deep_face}, "childNodes": [], "id": 2}),
            json!({"type": 2, "tagName": "div", "attributes": {"style": deep_value}, "childNodes": [], "id": 2}),
        ] {
            let events = json!([{"type": 2, "timestamp": 1, "data": {"node": {"type": 0, "id": 1, "childNodes": [node]}}}]).to_string();
            let (_, counts) = written(block_of("kept", &events));
            assert_eq!(counts.dropped, Some("too_many_nested_blocks"));
        }
        let refused: Vec<_> = (0..2_000)
            .map(|i| json!({"type": 2, "tagName": "img", "attributes": {"src": format!("https://cdn.example.com/{i}/{}.png?token=x", "a".repeat(600))}, "childNodes": [], "id": i + 2}))
            .collect();
        let events = json!([{"type": 2, "timestamp": 1, "data": {"node": {"type": 0, "id": 1, "childNodes": refused}}}]).to_string();
        let (_, counts) = written(block_of("kept", &events));
        assert_eq!(counts.dropped, Some("too_many_declined_urls"));
        // Each copy of the longest of these refused URLs holds a match of every one of them.
        let nested: Vec<_> = (1..=1_000)
            .map(|i| json!({"type": 2, "tagName": "img", "attributes": {"src": format!("https://10.0.0.7/{}", "a".repeat(i))}, "childNodes": [], "id": i + 1}))
            .collect();
        let copies = format!("https://10.0.0.7/{} ", "a".repeat(1_000)).repeat(1_001);
        let events = json!([
            {"type": 2, "timestamp": 1, "data": {"node": {"type": 0, "id": 1, "childNodes": nested}}},
            {"type": 5, "timestamp": 2, "data": {"tag": "copies", "payload": {"text": copies}}},
        ])
        .to_string();
        let (lines, counts) = written(block_of("kept", &events));
        assert_eq!(
            (lines.as_str(), counts.dropped),
            ("", Some("too_many_declined_copies"))
        );
        // cssparser reads a NUL in a string as U+FFFD, so the decoded URL is not in its token, only in the comment.
        let nul_url = "url(\"https://cdn.example.com/a.png?X-Amz-Signature=abc123#\u{0}\"/*https://cdn.example.com/a.png?X-Amz-Signature=abc123#\u{FFFD}*/)";
        // A set keeps its candidate as the page wrote it, so it cannot keep an escaped one.
        for style in [
            format!("background-image:{nul_url}"),
            format!("background-image:image-set({nul_url} 1x)"),
            "background-image:image-set(url('\\2f \\2f cdn.example.com/a.png?token=secret') 1x)"
                .to_owned(),
        ] {
            let node = json!({"type": 2, "tagName": "div", "attributes": {"style": style}, "childNodes": [], "id": 2});
            let events = json!([{"type": 2, "timestamp": 1, "data": {"node": {"type": 0, "id": 1, "childNodes": [node]}}}]).to_string();
            let (_, counts) = written(block_of("kept", &events));
            assert_eq!(counts.dropped, Some("unplaced_slot"), "{style}");
        }
        // The block would store an event that the flush did not decode as it arrived, with its URLs unread.
        let events = json!([{"type": 2, "timestamp": 1, "data": {"node": {"type": 0, "id": 1, "childNodes": []}}}]).to_string();
        for expansion in [Expansion::Skipped, Expansion::Failed] {
            let mut block = block_of("kept", &events);
            block.messages[0].events[0].expansion = Some(expansion);
            let (_, counts) = written(block);
            assert_eq!(counts.dropped, Some("undecoded_events"));
        }
    }

    #[test]
    fn leaves_css_only_images_and_fonts_an_offline_render_can_load() {
        let compressed: String = replay_core_v4::compression::gzip(
            json!([{"rule": ".a{background:url(/img/a.png)} .q{content:\"url(/img/a.png)\"} .b{background-image:image-set(url(https://cdn.example.com/1x.png) 1x, url(https://cdn.example.com/2x.png) 2x)} .c{background:url(/c.png?X-Amz-Signature=abc123)} .bg-\\[url\\(https\\:\\/\\/cdn\\.example\\.com\\/t\\.png\\)\\]{background-image:url(https://cdn.example.com/t.png)} .s-\\[url\\(https\\:\\/\\/cdn\\.example\\.com\\/s\\.png\\?X-Amz-Signature\\=abc123\\)\\]{background-image:url(https://cdn.example.com/s.png?X-Amz-Signature=abc123)}", "index": 0}])
                .to_string()
                .as_bytes(),
        )
        .unwrap()
        .iter()
        .map(|&b| char::from(b))
        .collect();
        let events = json!([
            {"type": 4, "timestamp": 1, "data": {"href": "http://app.example.com/shop/item", "width": 800, "height": 600}},
            {"type": 3, "timestamp": 2, "cv": "2024-10", "data": {"source": 8, "id": 3, "adds": compressed}},
            {"type": 3, "timestamp": 3, "data": {"source": 0, "adds": [], "removes": [], "texts": [], "attributes": [{"id": 9, "attributes": {"class": "bg-[url(/img/a.png)]"}}, {"id": 10, "attributes": {"class": "bg-[url(https://cdn.example.com/t.png)]"}}]}},
            {"type": 3, "timestamp": 4, "data": {"source": 8, "id": 3, "replaceSync": ".\\/\\/cdn\\.example\\.com\\/p\\.png\\?X-Amz-Signature\\=abc123{background:url(//cdn.example.com/p.png?X-Amz-Signature=abc123)}"}},
            {"type": 3, "timestamp": 5, "data": {"source": 8, "id": 4, "replaceSync": "@font-face{font-family:Brand;src:url(/fonts/brand.woff2)}@font-face{font-family:Roboto;src:url(/fonts/roboto.woff2)}@font-face{font-family:Escaped;src:url(https://fonts.example.com/escaped\\2e woff2)} .e{background:url(https://cdn.example.com/escaped\\2e png)}"}},
        ]);
        let lines = stored_lines(&events.to_string());
        let reference = |url: &str| {
            crate::urls::url_reference(
                url,
                UrlAsset::Image,
                7,
                "2026-10",
                &replay_core_v4::seal::image_url_key(&[6; 32]),
            )
            .unwrap()
            .1
        };
        for expected in [
            format!(
                r#"url(\"{}\")"#,
                reference("https://app.example.com/img/a.png")
            ),
            format!(
                r#"image-set(url({}) 2x)"#,
                reference("https://cdn.example.com/2x.png")
            ),
            r#"url(\"imageurl:v4:declined:credential\")"#.to_owned(),
            format!(
                r#"src:url(\"{}\")"#,
                crate::urls::url_reference(
                    "https://app.example.com/fonts/brand.woff2",
                    UrlAsset::Font,
                    7,
                    "2026-10",
                    &replay_core_v4::seal::image_url_key(&[6; 32]),
                )
                .unwrap()
                .1
            ),
            r#"src:url(\"fonturl:v4:bundled:roboto\")"#.to_owned(),
            format!(
                r#".e{{background:url(\"{}\")}}"#,
                reference("https://cdn.example.com/escaped.png")
            ),
            format!(
                r#"src:url(\"{}\")"#,
                crate::urls::url_reference(
                    "https://fonts.example.com/escaped.woff2",
                    UrlAsset::Font,
                    7,
                    "2026-10",
                    &replay_core_v4::seal::image_url_key(&[6; 32]),
                )
                .unwrap()
                .1
            ),
        ] {
            assert!(lines.contains(&expected), "{expected} in {lines}");
        }
        for kept in [
            r#""class":"bg-[url(/img/a.png)]""#,
            r#".q{content:\"url(/img/a.png)\"}"#,
        ] {
            assert!(lines.contains(kept), "{kept} in {lines}");
        }
        // A copy of an accepted URL outside an image slot stays as the page wrote it, as a link does.
        for kept in [
            r#""class":"bg-[url(https://cdn.example.com/t.png)]""#,
            r".bg-\\[url\\(https\\:\\/\\/cdn\\.example\\.com\\/t\\.png\\)\\]",
        ] {
            assert!(lines.contains(kept), "{kept} in {lines}");
        }
        assert!(
            lines.contains(r".s-\\[url\\(imageurl\\:v4\\:declined\\:credential\\)\\]"),
            "{lines}"
        );
        for gone in [
            ":url(/img/a.png)",
            "1x.png",
            "1x,",
            "Signature",
            "/fonts/",
            "fonts.example.com",
        ] {
            assert!(!lines.contains(gone), "{gone} in {lines}");
        }
    }

    #[test]
    fn resolves_a_relative_url_against_the_page_of_its_own_window() {
        let window = |id: &str, href: &str| {
            let mut message = block_of(
                "kept",
                &json!([
                    {"type": 4, "timestamp": 1, "data": {"href": href, "width": 800, "height": 600}},
                    {"type": 3, "timestamp": 2, "data": {"source": 8, "id": 3, "replaceSync": ".a{background:url(/a.png)}"}},
                ])
                .to_string(),
            )
            .messages
            .remove(0);
            message.window_id = Some(Arc::from(id));
            message
        };
        let mut block = block_of("kept", "[]");
        block.messages = vec![
            window("w1", "http://10.0.0.5/admin"),
            window("w2", "https://app.example.com/shop"),
        ];
        let lines = stored(block);
        let reference = crate::urls::url_reference(
            "https://app.example.com/a.png",
            UrlAsset::Image,
            7,
            "2026-10",
            &replay_core_v4::seal::image_url_key(&[6; 32]),
        )
        .unwrap()
        .1;
        for expected in [
            r#""href":"http://10.0.0.5/admin""#.to_owned(),
            r#""href":"https://app.example.com/shop""#.to_owned(),
            r#"url(\"imageurl:v4:declined:non_public_host\")"#.to_owned(),
            format!(r#"url(\"{reference}\")"#),
        ] {
            assert!(lines.contains(&expected), "{expected} in {lines}");
        }
        assert!(!lines.contains("url(/a.png)"), "{lines}");
    }

    #[test]
    fn leaves_a_picture_only_the_sources_that_can_load() {
        let (avif, webp, signed, fallback) = (
            "https://cdn.example.com/a.avif",
            "https://cdn.example.com/a.webp",
            "https://bucket.s3.amazonaws.com/a.webp?X-Amz-Signature=abc123",
            "https://cdn.example.com/a.png",
        );
        let source = |id: i64, attributes: serde_json::Value| json!({"type": 2, "tagName": "source", "attributes": attributes, "childNodes": [], "id": id});
        let (bare, typeless) = (
            "https://cdn.example.com/b.avif",
            "https://cdn.example.com/c.webp",
        );
        // The scan leaves an SVG inline, so the browser can load it from the block. The fetcher stores a remote SVG.
        let svg =
            "data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%2F%3E";
        let remote_svg = "https://cdn.example.com/a.svg";
        let avif_typed_svg = "data:image/svg+xml,%3Csvg%2F%3E";
        let shared = "https://cdn.example.com/shared.webp";
        let (beside_img_src, img_src) = (
            "https://cdn.example.com/beside-img-src.png",
            "https://cdn.example.com/img-src.png",
        );
        let (also_in_webp, webp_1x) = (
            "https://cdn.example.com/also-in-webp.png",
            "https://cdn.example.com/webp-1x.webp",
        );
        let other_avif = format!(
            "data:image/avif;base64,{}",
            STANDARD.encode(b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1other")
        );
        let bitmap = format!("data:image/bmp;base64,{}", STANDARD.encode(b"BMbitmap"));
        // The dataset keeps no AVIF, so an inline one leaves the list too.
        let inline_avif = format!(
            "data:image/avif;base64,{}",
            STANDARD.encode(b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf")
        );
        let picture = json!({"type": 2, "tagName": "picture", "attributes": {}, "id": 2, "childNodes": [
            source(6, json!({"type": "image/svg+xml", "srcset": format!("{svg} 1x")})),
            source(7, json!({"type": "image/svg+xml", "srcset": format!("{remote_svg} 1x")})),
            source(3, json!({"type": "image/avif", "srcset": format!("{avif} 1x, {inline_avif} 2x")})),
            // An inline candidate needs no fetch job, so it stays whatever the type.
            source(15, json!({"type": "image/avif", "srcset": format!("{avif} 2x, {avif_typed_svg} 1x")})),
            // A bare srcset equal to the img's src below: only the srcset empties.
            source(8, json!({"type": "image/avif", "srcset": bare})),
            // Values that read the same once their inline AVIFs leave merge their policies, so the WebP source keeps
            // the shared candidate.
            source(11, json!({"type": "image/avif", "srcset": format!("{shared} 1x, {inline_avif} 2x")})),
            source(12, json!({"type": "image/webp", "srcset": format!("{shared} 1x, {other_avif} 2x")})),
            // The WebP source keeps its other candidate, so no source fetches the URL the two share.
            source(13, json!({"type": "image/avif", "srcset": format!("{also_in_webp} 1x")})),
            source(14, json!({"type": "image/webp", "srcset": format!("{also_in_webp} 2x, {webp_1x} 1x")})),
            // Neither this source nor the img below with the same srcset shows the candidate, so neither keeps it.
            source(16, json!({"type": "image/avif", "srcset": format!("{beside_img_src} 2x")})),
            // An empty type gives no hint, so the source keeps its candidate.
            source(9, json!({"type": "", "srcset": format!("{typeless} 1x")})),
            // Only the kept candidate stays, so a declined URL and an inline image the image scrub cannot read leave too.
            source(4, json!({"type": "image/webp", "srcset": format!("{webp} 1x, {signed} 2x, {bitmap} 3x")})),
            {"type": 2, "tagName": "img", "attributes": {"src": fallback}, "childNodes": [], "id": 5},
        ]});
        let img = json!({"type": 2, "tagName": "img", "attributes": {"src": bare}, "childNodes": [], "id": 10});
        let img_with_src = json!({"type": 2, "tagName": "img", "attributes": {"src": img_src, "srcset": format!("{beside_img_src} 2x")}, "childNodes": [], "id": 17});
        let events = json!([{"type": 2, "timestamp": 1, "data": {"node": {"type": 0, "id": 1, "childNodes": [picture, img, img_with_src]}}}]).to_string();

        let block = block_of("kept", &events);
        let mut inspector = replay_core_v4::inspect::session::SessionInspector::default();
        let mut inspection = replay_core_v4::inspect::session::BlockInspection::default();
        for message in &block.messages {
            inspector.observe_message(&mut inspection, message);
        }
        // The fetcher stores no AVIF, so the AVIF source gets no fetch job.
        let fetched = inspection.finish().image_urls;
        assert!(!fetched
            .iter()
            .any(|u| u == avif || u == also_in_webp || u == beside_img_src));
        assert!(fetched.iter().any(|u| u == img_src));
        assert!(fetched.iter().any(|u| u == webp_1x));

        let lines = stored_lines(&events);
        let reference = |url: &str| {
            crate::urls::url_reference(
                url,
                replay_core_v4::refs::UrlAsset::Image,
                7,
                "2026-10",
                &replay_core_v4::seal::image_url_key(&[6; 32]),
            )
            .unwrap()
            .1
        };
        // The AVIF source has no candidate left, so the browser takes the WebP.
        assert!(lines.contains(r#""srcset":"""#), "{lines}");
        assert!(
            lines.contains(&format!(r#""srcset":"{svg} 1x""#))
                && lines.contains(&format!(r#""srcset":"{avif_typed_svg} 1x""#)),
            "{lines}"
        );
        assert!(
            lines.contains(&format!(r#""srcset":"{} 1x""#, reference(remote_svg))),
            "{lines}"
        );
        assert!(
            lines.contains(&format!(r#""srcset":"{} 1x""#, reference(webp))),
            "{lines}"
        );
        assert!(lines.contains(&reference(fallback)), "{lines}");
        assert!(
            lines.contains(&format!(r#""srcset":"{} 1x""#, reference(shared))),
            "{lines}"
        );
        assert!(
            lines.contains(&format!(r#""srcset":"{} 1x""#, reference(webp_1x)))
                && !lines.contains(&reference(also_in_webp))
                && !lines.contains(&reference(beside_img_src)),
            "{lines}"
        );
        assert!(
            lines.contains(&format!(r#""src":"{}""#, reference(bare))),
            "{lines}"
        );
        assert!(
            lines.contains(&format!(r#""srcset":"{} 1x""#, reference(typeless))),
            "{lines}"
        );
        assert!(
            !lines.contains("a.avif")
                && !lines.contains("ftypavif")
                && !lines.contains("data:image/avif")
                && !lines.contains("X-Amz-Signature")
                && !lines.contains("declined"),
            "{lines}"
        );
    }

    #[test]
    fn rebuilds_a_srcset_as_the_block_holds_it_after_escapes_are_written_again() {
        // An SVG stays inline, and the writer writes its `\/` escapes as `/`.
        let svg = STANDARD.encode(b"<svg><!--??? --></svg>");
        assert!(svg.contains('/'));
        let inline = format!("data:image/svg+xml;base64,{svg}");
        let events = format!(
            r#"[{{"type":3,"timestamp":1,"data":{{"source":0,"adds":[],"removes":[],"texts":[],"attributes":[{{"id":99,"attributes":{{"srcset":"{} 1x, https://10.0.0.7/a.png 2x"}}}}]}}}}]"#,
            inline.replace('/', "\\/")
        );
        let lines = stored_lines(&events);
        assert!(
            lines.contains(&format!(r#""srcset":"{inline} 1x""#)),
            "{lines}"
        );
        assert!(
            !lines.contains("declined") && !lines.contains("10.0.0.7"),
            "{lines}"
        );

        // A srcset key outside an image slot, here in a custom event, is no srcset of the DOM and stays as it is. With
        // the same value as an inspected image slot, only the slot is rebuilt, and the custom event loses only the URL
        // that the policy refuses.
        let value = "https://cdn.example.com/a.png 1x, https://10.0.0.7/a.png 2x";
        let both = format!(
            r#"[{{"type":3,"timestamp":1,"data":{{"source":0,"adds":[],"removes":[],"texts":[],"attributes":[{{"id":99,"attributes":{{"srcset":"{value}"}}}}]}}}},{{"type":5,"timestamp":2,"data":{{"tag":"app","payload":{{"srcset":"{value}"}}}}}}]"#
        );
        let lines = stored_lines(&both);
        let reference = crate::urls::url_reference(
            "https://cdn.example.com/a.png",
            replay_core_v4::refs::UrlAsset::Image,
            7,
            "2026-10",
            &replay_core_v4::seal::image_url_key(&[6; 32]),
        )
        .unwrap()
        .1;
        let (dom, custom) = lines.split_once('\n').unwrap();
        assert!(
            dom.contains(&format!(r#""srcset":"{reference} 1x""#)),
            "{dom}"
        );
        assert!(
            custom.contains(
                r#""srcset":"https://cdn.example.com/a.png 1x, imageurl:v4:declined:non_public_host 2x""#
            ),
            "{custom}"
        );
        let custom = r#"[{"type":5,"timestamp":1,"data":{"tag":"app","payload":{"srcset":"https://cdn.example.com/a.png 1x, https://10.0.0.7/a.png 2x"}}}]"#;
        let lines = stored_lines(custom);
        assert!(
            lines.contains(
                r#""srcset":"https://cdn.example.com/a.png 1x, https://10.0.0.7/a.png 2x""#
            ),
            "{lines}"
        );
    }

    #[test]
    fn keeps_the_sealed_urls_of_a_row_under_the_message_limit() {
        let page = |i: usize| format!("https://app.example.com/{i}/{}", "p".repeat(1000));
        let (kept, truncated) = index_urls((0..1000).map(page).collect());
        assert!(truncated);
        assert!(
            kept.len() <= MAX_INDEX_URLS
                && kept.iter().map(String::len).sum::<usize>() <= MAX_INDEX_URLS_BYTES
        );
        let long = format!(
            "https://app.example.com/{}",
            "l".repeat(MAX_INDEX_URL_BYTES)
        );
        assert_eq!(
            index_urls(vec![page(1), long, page(2)]),
            (vec![page(1), page(2)], true)
        );
        assert_eq!(index_urls(vec![page(1)]), (vec![page(1)], false));
    }

    #[test]
    fn a_block_carries_the_reference_its_fetch_job_names() {
        let (fetched, declined) = (
            "https://cdn.example.com/a.png",
            "https://cdn.example.com/a.png?token=secret",
        );
        let (font, bundled, public) = (
            "https://fonts.example.com/brand.woff2",
            "https://fonts.example.com/inter.woff2",
            "https://fonts.gstatic.com/s/roboto/v30/KFOmCnqEu92Fr1Mu4mxK.woff2",
        );
        let css = format!("@font-face{{font-family:Brand;src:url({font})}}@font-face{{font-family:Inter;src:url({bundled})}}@font-face{{font-family:Brand Display;src:url({public})}}");
        let events = json!([{"type": 2, "timestamp": 1, "data": {"node": {"type": 0, "id": 1, "childNodes": [
            {"type": 2, "tagName": "img", "attributes": {"src": fetched, "srcset": format!("{declined} 2x")}, "childNodes": [], "id": 2},
            {"type": 2, "tagName": "style", "attributes": {"_cssText": css}, "childNodes": [], "id": 3},
        ]}}}]);
        let block = inspected(block("kept", events));
        let mut keys = FlushKeys::default();
        let (id, key) = session_key("kept");
        keys.sessions.insert(id, key);
        keys.team_months.insert(7, [6; 32]);
        let mut stats = BlockStats::default();
        let urls = crate::urls::FlushUrls::new([&block], &keys, "2026-10", &|_| false);
        let jobs = crate::urls::fetch_jobs(&urls, [(0, &block, &mut stats)], 1, &|_| false);
        let (lines, _, _) = write_block(&block, &[6; 32], "2026-10", || Ok(Vec::new())).unwrap();
        let lines = String::from_utf8(lines).unwrap();
        let references: Vec<_> = jobs
            .iter()
            .flat_map(|((_, asset), jobs)| {
                jobs.iter()
                    .map(move |job| (*asset, job["originalRef"].as_str().unwrap()))
            })
            .collect();
        let [(UrlAsset::Image, image_reference), (UrlAsset::Font, font_reference), (UrlAsset::Font, public_reference)] =
            references.as_slice()
        else {
            panic!("a job each for the image and the fetched fonts, none for the bundled font: {references:?}");
        };
        assert!(font_reference.starts_with("fonturl:v4:7:2026-10:"));
        assert_eq!(
            *public_reference,
            "fonturl:v4:public:I6bjVBXgjPcaYLPITibNM4"
        );
        for expected in [
            format!(r#""src":"{image_reference}""#),
            // The srcset keeps only the candidate it shows, and the policy refuses that one.
            r#""srcset":"""#.to_owned(),
            format!("src:url({font_reference})"),
            "src:url(fonturl:v4:bundled:inter)".to_owned(),
            format!("src:url({public_reference})"),
        ] {
            assert!(lines.contains(&expected), "{expected} in {lines}");
        }
        assert!(!lines.contains("example.com/"), "{lines}");
        assert!(!lines.contains("gstatic.com/"), "{lines}");
    }

    fn session_key(session: &str) -> (SessionId, Key) {
        (
            SessionId {
                team_id: 7,
                session_id: session.to_owned(),
            },
            Key {
                key: [5; 32],
                key_month: "2026-09".to_owned(),
            },
        )
    }

    fn at() -> DateTime<Utc> {
        DateTime::parse_from_rfc3339("2026-10-15T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc)
    }

    #[test]
    fn block_context_reproduces_the_shared_vector() {
        // The Node writers and readers in other languages check themselves against the same file.
        let vector: Value = serde_json::from_str(include_str!(
            "../../../../nodejs/src/ingestion/pipelines/sessionreplay/ai-research/v4-keys/encryption-vector-v4.json"
        ))
        .unwrap();
        let block = &vector["block"];
        let context = &block["context"];
        let session = SessionKey {
            team_id: context["teamId"].as_i64().unwrap(),
            session_id: context["sessionId"].as_str().unwrap().to_owned(),
        };
        let built = block_context(
            &session,
            context["keyMonth"].as_str().unwrap(),
            context["ref"].as_str().unwrap(),
        );
        assert_eq!(
            built.authenticated_data(Version::V4),
            block["aad"].as_str().unwrap()
        );
        let body = STANDARD.decode(block["body"].as_str().unwrap()).unwrap();
        assert_eq!(
            decompress(&body).unwrap(),
            STANDARD.decode(block["plain"].as_str().unwrap()).unwrap()
        );
    }

    #[test]
    fn keeps_one_copy_of_an_image_that_several_messages_repeat() {
        let events = json!([{"type": 2, "timestamp": 1, "data": {"node": {"attributes": {"src": uri(b"logo")}}}}]);
        let mut repeated = block("s", events.clone());
        repeated.messages.extend(block("s", events).messages);
        let (_, images, counts) =
            write_block(&repeated, &[6; 32], "2026-10", || Ok(io::sink())).unwrap();
        assert_eq!((images.len(), counts.extracted), (1, 2));
    }

    #[tokio::test]
    async fn a_seal_of_an_abandoned_attempt_keeps_its_permit() {
        let permits = Arc::new(Semaphore::new(1));
        let (release, wait) = std::sync::mpsc::channel::<()>();
        let abandoned = seal_blocking(&permits, move || {
            wait.recv().ok();
            Ok(())
        });
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(50), abandoned)
                .await
                .is_err()
        );
        assert_eq!(permits.available_permits(), 0);
        release.send(()).unwrap();
        seal_blocking(&permits, || Ok(())).await.unwrap();
        // The flush drops a block whose seal panicked and keeps the others, so a panic is told apart.
        let panicked = seal_blocking(&permits, || -> Result<(), WriteError> { panic!("seal") });
        assert!(matches!(panicked.await, Err(WriteError::Panicked(_))));
    }

    #[tokio::test]
    async fn stores_images_once_and_blocks_that_point_at_them() {
        let events = json!([
            {"type": 4, "timestamp": 0, "data": {"href": "https://app.example.com/a"}},
            {"type": 2, "timestamp": 1, "data": {"node": {"attributes": {"src": uri(b"new"), "srcset": format!("{} 2x", uri(b"new"))}}}},
            {"type": 3, "timestamp": 2, "data": {"source": 0, "adds": [{"parentId": 1, "node": {"attributes": {"src": uri(b"old")}}}]}},
            {"type": 5, "timestamp": 3, "data": {"tag": "$url_changed", "payload": {"href": "https://app.example.com/b"}}},
            {"type": 4, "timestamp": 4, "data": {"href": "https://app.example.com/a"}},
        ]);
        let mut blocks = [block("kept", events.clone()), block("again", events)];
        blocks[0].visited_urls = ["/b", "/a"]
            .map(|path| format!("https://app.example.com{path}"))
            .to_vec();
        let mut keys = FlushKeys::default();
        for session in ["kept", "again"] {
            let (id, key) = session_key(session);
            keys.sessions.insert(id, key);
        }
        keys.team_months.insert(7, [6; 32]);
        let old_ref = replay_core_v4::v4_image_refs::image_ref(
            7,
            "2026-10",
            &replay_core_v4::refs::reference_hash(&image_content_key(&[6; 32]), &png(b"old")),
        );
        let object = object_key("2026-10-15", at());
        let mut sealed: Vec<SealedBlock> = blocks
            .iter()
            .map(|b| {
                seal_block(
                    b,
                    &keys.sessions[&session_key(&b.session.session_id).0],
                    &[6; 32],
                    "2026-10",
                    &object,
                )
                .unwrap()
            })
            .collect();
        assert_eq!(
            sealed[0].counts,
            WriterCounts {
                extracted: 2,
                bytes: 2 * 8 + 6,
                inline: 0,
                ..sealed[0].counts
            }
        );
        // The page the block sees again keeps its first place, under the session's own fingerprint key.
        let fingerprint_key = url_fingerprint_key(&[5; 32]);
        let fingerprint = |path: &str| {
            url_fingerprint(&fingerprint_key, &format!("https://app.example.com{path}"))
        };
        assert_eq!(
            sealed[0].url_fingerprints,
            [fingerprint("/a"), fingerprint("/b")]
        );
        let mut visited = [fingerprint("/a"), fingerprint("/b")];
        visited.sort_unstable();
        assert_eq!(sealed[0].visited_url_fingerprints, visited);

        let session_frames = session_keyed_frames(&sealed);
        let memory = Arc::new(MemoryStore::default());
        let store: Arc<dyn BlobStore> = memory.clone();
        let rows = write_images(
            new_images(&mut sealed),
            &keys,
            "2026-10-15",
            "2026-10",
            "images-v4",
            &store,
            at(),
            4,
            &Arc::new(Semaphore::new(4)),
        )
        .await
        .unwrap();
        let written = write_blocks(&sealed, &object, "rrweb-v4", store.as_ref())
            .await
            .unwrap();

        // Both blocks moved the same two images out, and the pack holds each once.
        assert_eq!(rows.len(), 2);
        // A key per session would need each session's copy.
        assert_eq!(session_frames, 4);
        assert!(rows.iter().any(|row| row.image_ref == old_ref));
        assert_eq!(written.len(), 2);

        let block = &written[0];
        let frame = &memory.get("rrweb-v4", &block.object_key)
            [block.byte_start as usize..=block.byte_end as usize];
        let context = block_context(&blocks[0].session, "2026-09", &object);
        let lines = String::from_utf8(
            decompress(&open_frame(&[5; 32], Version::V4, &context, frame).unwrap()).unwrap(),
        )
        .unwrap();
        let longest = lines.split_inclusive('\n').map(str::len).max().unwrap();
        assert_eq!(
            (
                sealed[0].counts.jsonl_bytes,
                sealed[0].counts.max_line_bytes
            ),
            (lines.len() as u64, longest as u64)
        );
        // The frame is bound to its object: it does not open as a block of another one.
        let elsewhere = block_context(&blocks[0].session, "2026-09", "blocks/dt=2026-10-15/other");
        assert!(open_frame(&[5; 32], Version::V4, &elsewhere, frame).is_err());
        let first: Value = serde_json::from_str(lines.lines().nth(1).unwrap()).unwrap();
        let reference = first[1]["data"]["node"]["attributes"]["src"]
            .as_str()
            .unwrap();
        assert_eq!(reference, rows[0].image_ref);
        assert!(lines.contains(&old_ref) && !lines.contains("base64"));

        // The reference resolves through the index to the image's bytes in the pack.
        let row = &rows[0];
        let pack = memory.get("images-v4", &row.pack_s3_key);
        let image_context = Context {
            team_id: 7,
            key_month: Some("2026-10".to_owned()),
            kind: "image".to_owned(),
            codec: Some(Codec::None),
            reference: Some(row.image_ref.clone()),
            ..Context::default()
        };
        let sealed_image = &pack[row.byte_start as usize..=row.byte_end as usize];
        assert_eq!(
            open_frame(&[6; 32], Version::V4, &image_context, sealed_image).unwrap(),
            png(b"new")
        );
        // The team month key seals images, as the fetcher's, so a session key does not open them.
        assert!(open_frame(&[5; 32], Version::V4, &image_context, sealed_image).is_err());

        // The block index row points at the block, keeps the moments, and seals the visited pages.
        blocks[0].moments = vec![Moment {
            kind: "full_snapshot",
            window_id: "w1".into(),
            ts_ms: 1,
            event_index: 1,
        }];
        let stats = BlockStats::default();
        let attempt = FlushAttempt::new(at());
        let index =
            block_index_rows(&[(&blocks[0], &stats, &written[0])], &keys, &attempt).unwrap();
        let [row] = index.as_slice() else {
            panic!("one row per stored block");
        };
        assert_eq!(
            (row.block_s3_key, row.block_byte_end),
            (block.object_key.as_str(), block.byte_end)
        );
        assert_eq!(row.moments, blocks[0].moments);
        let envelope: Value = serde_json::from_str(row.urls.as_deref().unwrap()).unwrap();
        let sealed_urls = STANDARD
            .decode(envelope["ciphertext"].as_str().unwrap())
            .unwrap();
        let nonce = STANDARD
            .decode(envelope["nonce"].as_str().unwrap())
            .unwrap();
        let aad = Context {
            team_id: 7,
            session_id: Some("kept".to_owned()),
            key_month: Some("2026-09".to_owned()),
            kind: "index".to_owned(),
            reference: Some("urls".to_owned()),
            ..Context::default()
        }
        .authenticated_data(Version::V4);
        let urls = Aes256Gcm::new_from_slice(&[5; 32])
            .unwrap()
            .decrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: &sealed_urls,
                    aad: aad.as_bytes(),
                },
            )
            .unwrap();
        assert_eq!(
            serde_json::from_slice::<Vec<String>>(&urls).unwrap(),
            [
                "https://app.example.com/a",
                "https://app.example.com/b",
                "https://app.example.com/a"
            ]
        );
    }

    #[test]
    fn readers_drop_the_rows_of_earlier_attempts_that_a_retry_covers() {
        let mut keys = FlushKeys::default();
        for session in ["a", "b", "c"] {
            let (id, key) = session_key(session);
            keys.sessions.insert(id, key);
        }
        let mouse = json!([{"type": 3, "timestamp": 3, "data": {"source": 1, "positions": []}}]);
        let stats = BlockStats::default();
        let written = |session: &str| Written {
            session: SessionKey {
                team_id: 7,
                session_id: session.to_owned(),
            },
            key_month: "2026-09".to_owned(),
            object_key: format!("blocks/{session}"),
            byte_start: 0,
            byte_end: 9,
        };
        // Two attempts wrote their rows and failed before the commit: offsets 100-105 and 106-110 of partition 0.
        // The retry starts at the committed offset 100, reads both ranges in one flush, and also writes partition 1.
        let a = block("a", mouse.clone());
        let mut early_b = block("b", mouse.clone());
        early_b.origin = origin(0, 106, 110);
        let mut retried_a = block("a", mouse.clone());
        retried_a.origin.flush_end_offset = 110;
        let mut b = block("b", mouse.clone());
        b.origin = origin(0, 100, 110);
        let mut c = block("c", mouse);
        c.origin = origin(1, 40, 41);
        let (wa, wb, wc) = (written("a"), written("b"), written("c"));
        let first = FlushAttempt {
            flush_id: "0000000000000001".to_owned(),
            flushed_at_ms: 1_000,
        };
        let between = FlushAttempt {
            flush_id: "0000000000000003".to_owned(),
            flushed_at_ms: 1_500,
        };
        let second = FlushAttempt {
            flush_id: "0000000000000002".to_owned(),
            flushed_at_ms: 2_000,
        };
        let mut rows = Vec::new();
        let mut positions = Vec::new();
        for (attempt, entries) in [
            (&first, vec![(&a, &stats, &wa)]),
            (&between, vec![(&early_b, &stats, &wb)]),
            (
                &second,
                vec![
                    (&retried_a, &stats, &wa),
                    (&b, &stats, &wb),
                    (&c, &stats, &wc),
                ],
            ),
        ] {
            for row in block_index_rows(&entries, &keys, attempt).unwrap() {
                positions.push((
                    row.flush_id.to_owned(),
                    row.partition,
                    row.flush_end_offset,
                    row.flush_row_count,
                    row.flush_row_index,
                ));
                rows.push((
                    (row.topic.to_owned(), row.partition),
                    (row.start_offset, row.end_offset),
                    (row.flushed_at_ms, row.flush_id.to_owned()),
                    row.session_id.to_owned(),
                ));
            }
        }
        assert_eq!(rows.len(), 5);
        // Each partition of a flush numbers its rows, so a reader can tell that all of them arrived.
        positions.sort();
        let retry: Vec<_> = positions
            .iter()
            .filter(|p| p.0 == "0000000000000002")
            .map(|p| (p.1, p.2, p.3, p.4))
            .collect();
        assert_eq!(retry, [(0, 110, 2, 0), (0, 110, 2, 1), (1, 41, 1, 0)]);

        // The documented rule, per (topic, partition): a flush covers its start offset to its highest end offset.
        // Walk the flushes from the latest and keep one only if it overlaps no flush already kept.
        type Flush = ((String, i32), (i64, String));
        let mut ranges: HashMap<Flush, (i64, i64)> = HashMap::new();
        for (tp, (start, end), flush, _) in &rows {
            let range = ranges
                .entry((tp.clone(), flush.clone()))
                .or_insert((*start, *end));
            range.1 = range.1.max(*end);
        }
        let mut flushes: Vec<_> = ranges.into_iter().collect();
        flushes.sort_by(|a, b| b.0 .1.cmp(&a.0 .1));
        let mut kept_flushes: Vec<(Flush, (i64, i64))> = Vec::new();
        for (flush, range) in flushes {
            let overlaps = kept_flushes
                .iter()
                .any(|(k, r)| k.0 == flush.0 && range.0 <= r.1 && r.0 <= range.1);
            if !overlaps {
                kept_flushes.push((flush, range));
            }
        }
        let mut kept: Vec<_> = rows
            .iter()
            .filter(|(tp, _, flush, _)| {
                kept_flushes
                    .iter()
                    .any(|(k, _)| k.0 == *tp && k.1 == *flush)
            })
            .map(|(_, _, flush, session)| (session.as_str(), flush.1.as_str()))
            .collect();
        kept.sort();
        assert_eq!(
            kept,
            [
                ("a", "0000000000000002"),
                ("b", "0000000000000002"),
                ("c", "0000000000000002")
            ]
        );
    }
}
