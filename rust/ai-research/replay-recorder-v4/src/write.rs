//! Writes a flush: image packs first, then one object of sealed session blocks, and builds the index rows for both.
//!
//! The order matters for a crash between writes. A pack without its blocks is unreferenced, which is harmless. A block
//! whose images were never stored would hold references that resolve to nothing. The rows go out only after both.

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
use replay_core_v4::scan::cv::extract_event_images;
use replay_core_v4::scan::images::{Image, ImageLimits, ImageSink};
use replay_core_v4::seal::{image_content_key, url_fingerprint_key};

use tokio::sync::Semaphore;

use crate::batch::{Block, SessionKey};
use crate::index::{BlockIndexRow, ImageIndexRow};
use crate::rewrite::{canonical_strings, Fallback, RewriteReport, UrlRewrite};
use crate::scrub::Scrub;
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
    /// Why the block must not be stored, as the outcome of its drop: a URL the policy declines stays in it even after
    /// the fallback.
    pub dropped: Option<&'static str>,
    /// Why the writer used a fallback to keep the block, as a metric label.
    pub fallback: Option<&'static str>,
    /// The URL tokens the fallback replaced.
    pub scrubbed: u64,
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
    fallback: &Fallback,
    out: &mut impl Write,
) -> io::Result<(Vec<Image>, WriterCounts, RewriteReport)> {
    let content_key = image_content_key(team_key);
    let mut rewrite = UrlRewrite::new(
        &block.remote_urls,
        &block.srcsets,
        block.session.team_id,
        key_month,
        team_key,
    )
    .with_fallback(fallback.clone());
    let mut images = Vec::new();
    let mut kept = HashSet::new();
    let mut counts = WriterCounts::default();
    let mut removed_avif = 0u64;
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
            let extracted = extract_event_images(&message.inner, event, &mut sink);
            out.write_all(b"[")?;
            out.write_all(&window)?;
            out.write_all(b",")?;
            let canonical = canonical_strings(
                extracted
                    .as_deref()
                    .unwrap_or(&message.inner[event.span.0..event.span.1]),
            );
            // The inspector reads image slots in full snapshots and mutations only.
            let dom_event =
                event.kind == Some(2) || (event.kind == Some(3) && event.source == Some(0));
            let event_bytes = rewrite.apply(&canonical, dom_event);
            out.write_all(&event_bytes)?;
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
        removed_avif += u64::from(sink.removed_avif);
        images.extend(
            sink.images
                .into_iter()
                .filter(|image| kept.insert(image.reference.clone())),
        );
    }
    let mut report = rewrite.finish();
    report.counters.removed_avif = removed_avif;
    counts.scrubbed = report.scrubbed;
    Ok((images, counts, report))
}

/// A block whose URLs the inspector did not all name has every remote URL token it did not name scrubbed, so that the
/// block is kept without a URL nobody checked.
fn first_fallback(block: &Block) -> Fallback {
    match block.url_limit {
        Some(limit) => Fallback {
            overwrite_declined: true,
            scrub: Scrub::AllRemote,
            reason: Some(limit.label()),
        },
        None => Fallback::default(),
    }
}

/// What the second pass does about what the first left unsafe: it overwrites each declined URL wherever it is, and
/// scrubs the tokens that hold the host of a declined URL the stored bytes do not hold as the inspector read it.
fn second_fallback(first: &Fallback, report: &RewriteReport) -> Fallback {
    let scrub = match (&first.scrub, &report.unfound_hosts) {
        (Scrub::AllRemote, _) | (_, None) => Scrub::AllRemote,
        (_, Some(hosts)) if hosts.is_empty() => Scrub::Nothing,
        (_, Some(hosts)) => Scrub::Hosts(hosts.clone()),
    };
    let reason = if report.unfound_hosts.as_ref().is_some_and(Vec::is_empty) {
        "declined_kept"
    } else {
        "declined_unfound"
    };
    Fallback {
        overwrite_declined: true,
        scrub,
        reason: first.reason.or(Some(reason)),
    }
}

/// Writes a block's lines to an output from `open`. A block that the first pass leaves unsafe is written again to a
/// fresh output with the fallback that makes it safe, so a block is dropped only when even that fails. Moves the
/// images out and returns them with the output.
pub fn write_block<W: Write>(
    block: &Block,
    team_key: &[u8; 32],
    key_month: &str,
    mut open: impl FnMut() -> io::Result<W>,
) -> io::Result<(W, Vec<Image>, WriterCounts)> {
    let first = first_fallback(block);
    let mut out = open()?;
    let (images, mut counts, report) = prepare_block(block, team_key, key_month, &first, &mut out)?;
    if report.safe {
        report.counters.emit();
        counts.fallback = first.reason;
        return Ok((out, images, counts));
    }
    let second = second_fallback(&first, &report);
    if let Some(key) = &report.kept_in {
        tracing::info!(
            team_id = block.session.team_id,
            key,
            "a declined URL stayed inside a longer token"
        );
    }
    // The second pass copies every image again, so the first pass's output and images go before it starts.
    drop(out);
    drop(images);
    let mut out = open()?;
    let (images, mut counts, report) =
        prepare_block(block, team_key, key_month, &second, &mut out)?;
    report.counters.emit();
    counts.fallback = second.reason;
    // Fail closed only when the fallback could not make the block safe either.
    if !report.safe {
        counts.dropped = Some("declined_unrewritten");
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
    if let Some(reason) = counts.fallback {
        counter!("ai_research_v4_recorder_url_fallbacks_total", "reason" => reason).increment(1);
        counter!("ai_research_v4_recorder_scrubbed_urls_total", "reason" => reason)
            .increment(counts.scrubbed);
    }
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
    use replay_core_v4::inspect::dom::MAX_BLOCK_REMOTE_URLS;

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
            remote_urls: Vec::new(),
            url_limit: None,
            srcsets: Vec::new(),
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
    fn stored_lines(events: &str, extra: &[&str]) -> String {
        let mut inspected = block_of("kept", events);
        let mut inspector = replay_core_v4::inspect::session::SessionInspector::default();
        let mut inspection = replay_core_v4::inspect::session::BlockInspection::default();
        for message in &inspected.messages {
            inspector.observe_message(&mut inspection, message);
        }
        let found = inspection.finish();
        inspected.remote_urls = found.remote_urls;
        inspected.url_limit = found.url_limit;
        inspected.srcsets = found.srcsets;
        inspected
            .remote_urls
            .extend(extra.iter().map(|url| (*url).to_owned()));
        let (lines, _, counts) =
            write_block(&inspected, &[6; 32], "2026-10", || Ok(Vec::new())).unwrap();
        if counts.dropped.is_some() {
            return String::new();
        }
        String::from_utf8(lines).unwrap()
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
        let lines = stored_lines(&events, &[]);
        let reference = crate::urls::url_reference(
            public,
            7,
            "2026-10",
            &replay_core_v4::seal::image_url_key(&[6; 32]),
        )
        .unwrap()
        .1;
        assert!(
            lines.contains(&format!(
                r#""src":"{}","srcset":"{reference} 2x""#,
                crate::rewrite::declined_marker("credential")
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
        let long_lines = stored_lines(&long(16 * 1024), &[]);
        assert!(
            long_lines.contains(&crate::rewrite::declined_marker("too_long")),
            "{long_lines}"
        );
        // Keys written with escapes hide no URL.
        let escaped = events
            .replace(r#""src""#, r#""\u0073rc""#)
            .replace(r#""srcset""#, r#""src\u0073et""#);
        assert_eq!(stored_lines(&escaped, &[]), lines);
        // A browser reads backslashes after the scheme as slashes, so such a URL is replaced like its `https://` form.
        for backslashed in [
            r"https:\\user:secret@cdn.example.com/a.png",
            r"https:/\user:secret@cdn.example.com/a.png",
            "https:user:secret@cdn.example.com/a.png",
        ] {
            let events = json!([{"type": 3, "timestamp": 1, "data": {"source": 0, "adds": [], "removes": [], "texts": [],
                "attributes": [{"id": 99, "attributes": {"src": backslashed}}]}}])
            .to_string();
            let lines = stored_lines(&events, &[]);
            assert!(
                lines.contains(&crate::rewrite::declined_marker("credential"))
                    && !lines.contains("secret"),
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
            let lines = stored_lines(&events, &[]);
            assert!(
                lines.contains(&crate::rewrite::declined_marker("credential"))
                    && !lines.contains("X-Amz-Signature"),
                "{lines}"
            );
        }
        // A declined URL the inspector named but the stored bytes do not show as it read it no longer fails the block:
        // the writer scrubs every token that holds its host, and keeps the rest.
        let event = json!([{"type": 4, "timestamp": 1, "data": {"href": "https://app.example.com/", "img": "https\\3a //bucket.s3.amazonaws.com/avatar.png"}}])
            .to_string();
        let lines = stored_lines(&event, &[signed]);
        assert!(
            lines.contains("https://app.example.com/")
                && !lines.contains("bucket.s3.amazonaws.com"),
            "{lines}"
        );
        assert!(!stored_lines(&event, &[public]).is_empty());
        // A declined URL that a longer URL also holds is overwritten there too, and the block is kept.
        let events = json!([{"type": 3, "timestamp": 1, "data": {"source": 0, "adds": [], "removes": [], "texts": [],
            "attributes": [{"id": 99, "attributes": {"src": signed, "alt": format!("{signed}&size=2")}}]}}])
        .to_string();
        let lines = stored_lines(&events, &[]);
        assert!(
            !lines.is_empty() && !lines.contains("X-Amz-Signature"),
            "{lines}"
        );
    }

    #[test]
    fn keeps_a_block_past_the_url_limit_without_a_url_it_did_not_check() {
        let urls = MAX_BLOCK_REMOTE_URLS + 1;
        let nodes: Vec<_> = (0..urls)
            .map(|i| json!({"type": 2, "tagName": "img", "attributes": {"src": format!("https://cdn.example.com/{i}.png")}, "childNodes": [], "id": i + 2}))
            .collect();
        let events = json!([{"type": 2, "timestamp": 1, "data": {"node": {"type": 0, "id": 1, "childNodes": nodes}}}]).to_string();
        let lines = stored_lines(&events, &[]);
        // The inspector named the first URLs, which keep their references; the fallback scrubbed the rest.
        assert!(
            lines.contains("imageurl:v4:7:2026-10:"),
            "named URLs keep their references"
        );
        assert!(lines.contains(crate::scrub::UNCHECKED_MARKER));
        assert!(!lines.contains("https://"));
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
        let shared = "https://cdn.example.com/shared.webp";
        let other_avif = format!(
            "data:image/avif;base64,{}",
            STANDARD.encode(b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1other")
        );
        // The dataset keeps no AVIF, so an inline one leaves the list too.
        let inline_avif = format!(
            "data:image/avif;base64,{}",
            STANDARD.encode(b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf")
        );
        let picture = json!({"type": 2, "tagName": "picture", "attributes": {}, "id": 2, "childNodes": [
            source(6, json!({"type": "image/svg+xml", "srcset": format!("{svg} 1x")})),
            source(7, json!({"type": "image/svg+xml", "srcset": format!("{remote_svg} 1x")})),
            source(3, json!({"type": "image/avif", "srcset": format!("{avif} 1x, {inline_avif} 2x")})),
            // A bare srcset equal to the img's src below: only the srcset empties.
            source(8, json!({"type": "image/avif", "srcset": bare})),
            // Values that read the same once their inline AVIFs leave merge their policies, so the WebP source keeps
            // the shared candidate.
            source(11, json!({"type": "image/avif", "srcset": format!("{shared} 1x, {inline_avif} 2x")})),
            source(12, json!({"type": "image/webp", "srcset": format!("{shared} 1x, {other_avif} 2x")})),
            // An empty type gives no hint, so the source keeps its candidate.
            source(9, json!({"type": "", "srcset": format!("{typeless} 1x")})),
            source(4, json!({"type": "image/webp", "srcset": format!("{signed} 2x, {webp} 1x")})),
            {"type": 2, "tagName": "img", "attributes": {"src": fallback}, "childNodes": [], "id": 5},
        ]});
        let img = json!({"type": 2, "tagName": "img", "attributes": {"src": bare}, "childNodes": [], "id": 10});
        let events = json!([{"type": 2, "timestamp": 1, "data": {"node": {"type": 0, "id": 1, "childNodes": [picture, img]}}}]).to_string();

        let block = block_of("kept", &events);
        let mut inspector = replay_core_v4::inspect::session::SessionInspector::default();
        let mut inspection = replay_core_v4::inspect::session::BlockInspection::default();
        for message in &block.messages {
            inspector.observe_message(&mut inspection, message);
        }
        // The fetcher stores no AVIF, so the AVIF source gets no fetch job.
        assert!(!inspection.finish().image_urls.iter().any(|u| u == avif));

        let lines = stored_lines(&events, &[]);
        let reference = |url: &str| {
            crate::urls::url_reference(
                url,
                7,
                "2026-10",
                &replay_core_v4::seal::image_url_key(&[6; 32]),
            )
            .unwrap()
            .1
        };
        // The AVIF source has no candidate left and the declined one leaves the list, so the browser takes the WebP.
        assert!(lines.contains(r#""srcset":"""#), "{lines}");
        assert!(
            lines.contains(&format!(r#""srcset":"{svg} 1x""#)),
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
        // The `\/` escapes keep the PNG inline, and the writer then writes them as `/`.
        let png = STANDARD.encode(png(&[0xff; 30]));
        assert!(png.contains('/'));
        let inline = format!("data:image/png;base64,{png}");
        let events = format!(
            r#"[{{"type":3,"timestamp":1,"data":{{"source":0,"adds":[],"removes":[],"texts":[],"attributes":[{{"id":99,"attributes":{{"srcset":"{} 1x, https://10.0.0.7/a.png 2x"}}}}]}}}}]"#,
            inline.replace('/', "\\/")
        );
        let lines = stored_lines(&events, &[]);
        assert!(
            lines.contains(&format!(r#""srcset":"{inline} 1x""#)),
            "{lines}"
        );
        assert!(
            !lines.contains("declined") && !lines.contains("10.0.0.7"),
            "{lines}"
        );

        // A srcset key outside an image slot, here in a custom event, is no srcset of the DOM and stays as it is. With
        // the same value as an inspected image slot, only the slot is rebuilt, and the custom event gets the rewrite of
        // each URL that every copy of a named URL gets.
        let value = "https://cdn.example.com/a.png 1x, https://10.0.0.7/a.png 2x";
        let both = format!(
            r#"[{{"type":3,"timestamp":1,"data":{{"source":0,"adds":[],"removes":[],"texts":[],"attributes":[{{"id":99,"attributes":{{"srcset":"{value}"}}}}]}}}},{{"type":5,"timestamp":2,"data":{{"tag":"app","payload":{{"srcset":"{value}"}}}}}}]"#
        );
        let lines = stored_lines(&both, &[]);
        let reference = crate::urls::url_reference(
            "https://cdn.example.com/a.png",
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
            custom.contains(&format!(
                r#""srcset":"{reference} 1x, {} 2x""#,
                crate::rewrite::declined_marker("non_public_host")
            )),
            "{custom}"
        );
        let custom = r#"[{"type":5,"timestamp":1,"data":{"tag":"app","payload":{"srcset":"https://cdn.example.com/a.png 1x, https://10.0.0.7/a.png 2x"}}}]"#;
        let lines = stored_lines(custom, &[]);
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
        let events = json!([{"type": 2, "timestamp": 1, "data": {"node": {"attributes": {"src": fetched, "srcset": format!("{declined} 2x")}}}}]);
        let mut block = block("kept", events);
        block.image_urls = vec![fetched.to_owned()];
        block.remote_urls = vec![fetched.to_owned(), declined.to_owned()];
        let mut keys = FlushKeys::default();
        let (id, key) = session_key("kept");
        keys.sessions.insert(id, key);
        keys.team_months.insert(7, [6; 32]);
        let mut stats = BlockStats::default();
        let jobs = crate::urls::fetch_jobs([(&block, &mut stats)], &keys, "2026-10", 1, &|_| false);
        let (lines, _, _) = write_block(&block, &[6; 32], "2026-10", || Ok(Vec::new())).unwrap();

        let lines = String::from_utf8(lines).unwrap();
        let reference = jobs["example.com"][0]["originalRef"].as_str().unwrap();
        assert!(
            lines.contains(&format!(r#""src":"{reference}""#)),
            "{lines}"
        );
        assert!(lines.contains(&format!(
            r#""srcset":"{} 2x""#,
            crate::rewrite::declined_marker("credential")
        )));
        assert!(!lines.contains("cdn.example.com"));
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
        let old_ref = replay_core_v4::refs::image_ref(
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
