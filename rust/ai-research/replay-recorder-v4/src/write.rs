//! Writes a flush: image packs and their index first, then one object of sealed session blocks, then their index.
//!
//! The order matters for a crash between writes. A pack without its blocks is unreferenced, which is harmless. A block
//! whose images were never stored would hold references that resolve to nothing.

use std::collections::{BTreeMap, HashSet};
use std::io::{self, Write};
use std::sync::Arc;

use chrono::{DateTime, Utc};
use futures::stream::{self, StreamExt, TryStreamExt};
use rand::Rng;
use replay_core_v4::bytescan::write_json_string;
use replay_core_v4::envelope::{seal_frame, seal_json_envelope, Codec, Context, Version};
use replay_core_v4::inspect::events::event_page_url;
use replay_core_v4::inspect::stats::BlockStats;
use replay_core_v4::inspect::stats::MAX_URL_FINGERPRINTS;
use replay_core_v4::keys::batch::{FlushKeys, SessionId, SessionKey as Key};
use replay_core_v4::keys::rows::write_day;
use replay_core_v4::refs::url_fingerprint;
use replay_core_v4::scan::cv::extract_event_images;
use replay_core_v4::scan::images::{Image, ImageLimits, ImageSink};
use replay_core_v4::seal::{image_content_key, url_fingerprint_key};

use tokio::sync::Semaphore;

use crate::batch::{Block, SessionKey};
use crate::index::{
    block_index, image_index, write_parquet, BlockIndexRow, ImageIndexRow, IndexError,
};
use crate::rewrite::{canonical_strings, UrlRewrite};
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
    #[error(transparent)]
    Index(#[from] IndexError),
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
    /// Why the block must not be stored, as the outcome of its drop: a URL the policy declines stays in it, or the
    /// inspector did not name all its URLs.
    pub dropped: Option<&'static str>,
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
}

/// A block sealed for one object, with the images it moved out.
pub struct SealedBlock {
    pub session: SessionKey,
    pub key_month: String,
    pub frame: Vec<u8>,
    pub images: Vec<Arc<Image>>,
    pub counts: WriterCounts,
    pub url_fingerprints: Vec<String>,
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
pub fn prepare_block(
    block: &Block,
    team_key: &[u8; 32],
    key_month: &str,
    out: &mut impl Write,
) -> io::Result<(Vec<Image>, WriterCounts)> {
    // Fail closed: a URL the inspector did not name could be one the policy declines.
    if let Some(limit) = block.url_limit {
        let dropped = Some(limit.label());
        return Ok((
            Vec::new(),
            WriterCounts {
                dropped,
                ..WriterCounts::default()
            },
        ));
    }
    let content_key = image_content_key(team_key);
    let mut rewrite = UrlRewrite::new(
        &block.remote_urls,
        block.session.team_id,
        key_month,
        team_key,
    );
    let mut images = Vec::new();
    let mut kept = HashSet::new();
    let mut counts = WriterCounts::default();
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
            let event_bytes = rewrite.apply(&canonical);
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
        images.extend(
            sink.images
                .into_iter()
                .filter(|image| kept.insert(image.reference.clone())),
        );
    }
    // Fail closed: the flush drops a block that still holds a declined URL, a credential or a private host.
    if !rewrite.finish() {
        counts.dropped = Some("declined_unrewritten");
    }
    Ok((images, counts))
}

fn block_encoder() -> Result<brotlic::BrotliEncoder, WriteError> {
    let seal_error = |e: brotlic::SetParameterError| WriteError::Seal(e.to_string());
    brotlic::BrotliEncoderOptions::new()
        .quality(brotlic::Quality::new(BLOCK_BROTLI_QUALITY).map_err(seal_error)?)
        .window_size(brotlic::WindowSize::new(BLOCK_BROTLI_WINDOW_BITS).map_err(seal_error)?)
        .build()
        .map_err(seal_error)
}

/// Builds, compresses and seals one block.
pub fn seal_block(
    block: &Block,
    key: &Key,
    team_key: &[u8; 32],
    key_month: &str,
) -> Result<SealedBlock, WriteError> {
    seal_compressed(&compress_block(block, key, team_key, key_month)?)
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
    let encoder = brotlic::CompressorWriter::with_encoder(block_encoder()?, Vec::new());
    // The encoder works on each write it gets, so small writes cost far more CPU than the same bytes in one.
    let mut lines = io::BufWriter::with_capacity(BLOCK_WRITE_BUFFER, encoder);
    let (images, counts) =
        prepare_block(block, team_key, key_month, &mut lines).map_err(seal_error)?;
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
    })
}

/// Seals a compressed block for one attempt.
pub fn seal_compressed(block: &CompressedBlock) -> Result<SealedBlock, WriteError> {
    let frame = seal_frame(
        &block.key.key,
        Version::V4,
        &block_context(&block.session, &block.key.key_month),
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
    })
}

/// The authenticated data of a block frame.
pub fn block_context(session: &SessionKey, key_month: &str) -> Context {
    Context {
        team_id: session.team_id,
        session_id: Some(session.session_id.clone()),
        key_month: Some(key_month.to_owned()),
        kind: "rrweb".to_owned(),
        codec: Some(Codec::Brotli),
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

/// Seals each team's images under its team month key into one pack, stores the packs concurrently, then writes the
/// image index for the flush.
#[allow(clippy::too_many_arguments)]
pub async fn write_images(
    images: BTreeMap<i64, Vec<Arc<Image>>>,
    keys: &FlushKeys,
    write_day: &str,
    key_month: &str,
    images_bucket: &str,
    rrweb_bucket: &str,
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
    let rows: Vec<ImageIndexRow> = stream::iter(packs)
        .buffer_unordered(concurrency.max(1))
        .try_collect::<Vec<_>>()
        .await?
        .into_iter()
        .flatten()
        .collect();
    if !rows.is_empty() {
        let index_key = format!("index/images/dt={write_day}/{}.parquet", unique_suffix(at));
        let batch = image_index(&rows)?;
        let file = blocking(move || write_parquet(&batch).map_err(WriteError::from)).await?;
        store.put_new(rrweb_bucket, &index_key, file).await?;
    }
    Ok(rows)
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

/// Writes one block index file for the flush, after its blocks, so no row points at a block that is not stored.
/// Each entry is a block, its stats as this attempt filled them, and where it landed.
pub async fn write_block_index(
    entries: &[(&Block, &BlockStats, &Written)],
    keys: &FlushKeys,
    rrweb_bucket: &str,
    store: &dyn BlobStore,
    at: DateTime<Utc>,
) -> Result<usize, WriteError> {
    let mut rows = Vec::with_capacity(entries.len());
    for &(block, stats, written) in entries {
        let id = SessionId {
            team_id: written.session.team_id,
            session_id: written.session.session_id.clone(),
        };
        let Some(key) = keys.sessions.get(&id) else {
            continue;
        };
        let urls = block_urls(block);
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
            written,
            stats,
            moments: &block.moments,
            snapshot_source: first.and_then(|m| m.snapshot_source.as_deref()),
            snapshot_library: first.and_then(|m| m.library.as_deref()),
            urls,
        });
    }
    if rows.is_empty() {
        return Ok(0);
    }
    let index_key = format!(
        "index/blocks/dt={}/{}.parquet",
        write_day(at),
        unique_suffix(at)
    );
    let count = rows.len();
    let batch = block_index(&rows)?;
    let file = blocking(move || write_parquet(&batch).map_err(WriteError::from)).await?;
    store.put_new(rrweb_bucket, &index_key, file).await?;
    Ok(count)
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::io::Read;
    use std::sync::Mutex;

    use aes_gcm::aead::{Aead, KeyInit, Payload};
    use aes_gcm::{Aes256Gcm, Nonce};
    use arrow_array::{Array, Int64Array, ListArray, RecordBatch, StringArray, StructArray};
    use arrow_schema::DataType;
    use async_trait::async_trait;
    use base64::engine::general_purpose::STANDARD;
    use base64::Engine;
    use bytes::Bytes;
    use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
    use replay_core_v4::envelope::open_frame;
    use replay_core_v4::inspect::dom::MAX_REMOTE_URL_BYTES;
    use replay_core_v4::inspect::session::Moment;
    use replay_core_v4::scan::message::read_message;
    use serde_json::{json, Value};

    use super::*;

    #[derive(Default)]
    struct MemoryStore {
        objects: Mutex<HashMap<(String, String), Vec<u8>>>,
    }

    impl MemoryStore {
        fn get(&self, bucket: &str, key: &str) -> Vec<u8> {
            self.objects.lock().unwrap()[&(bucket.to_owned(), key.to_owned())].clone()
        }

        fn keys(&self, prefix: &str) -> Vec<String> {
            let mut keys: Vec<String> = self
                .objects
                .lock()
                .unwrap()
                .keys()
                .filter(|(_, key)| key.starts_with(prefix))
                .map(|(_, key)| key.clone())
                .collect();
            keys.sort();
            keys
        }

        fn parquet(&self, key: &str) -> RecordBatch {
            ParquetRecordBatchReaderBuilder::try_new(Bytes::from(self.get("rrweb-v4", key)))
                .unwrap()
                .build()
                .unwrap()
                .next()
                .unwrap()
                .unwrap()
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
            messages: vec![message],
            stats: BlockStats::default(),
            moments: Vec::new(),
            image_urls: Vec::new(),
            remote_urls: Vec::new(),
            url_limit: None,
        }
    }

    fn uri(bytes: &[u8]) -> String {
        format!("data:image/png;base64,{}", STANDARD.encode(bytes))
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
        inspected
            .remote_urls
            .extend(extra.iter().map(|url| (*url).to_owned()));
        let mut lines = Vec::new();
        let (_, counts) = prepare_block(&inspected, &[6; 32], "2026-10", &mut lines).unwrap();
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
        // A URL past the length cap is not named, so the block is not stored.
        let long = |len: usize| {
            let url = format!("https://cdn.example.com/{}", "a".repeat(len - 24));
            json!([{"type": 3, "timestamp": 1, "data": {"source": 0, "adds": [], "removes": [], "texts": [],
                "attributes": [{"id": 99, "attributes": {"src": url}}]}}])
            .to_string()
        };
        assert!(!stored_lines(&long(MAX_REMOTE_URL_BYTES), &[]).is_empty());
        assert_eq!(stored_lines(&long(MAX_REMOTE_URL_BYTES + 1), &[]), "");
        // Keys written with escapes hide no URL.
        let escaped = events
            .replace(r#""src""#, r#""\u0073rc""#)
            .replace(r#""srcset""#, r#""src\u0073et""#);
        assert_eq!(stored_lines(&escaped, &[]), lines);
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
        // A declined URL the inspector named but the stored bytes do not show as it read it fails the whole block.
        let event =
            json!([{"type": 4, "timestamp": 1, "data": {"href": "https://app.example.com/"}}])
                .to_string();
        assert_eq!(stored_lines(&event, &[signed]), "");
        assert!(!stored_lines(&event, &[public]).is_empty());
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
        let mut lines = Vec::new();
        prepare_block(&block, &[6; 32], "2026-10", &mut lines).unwrap();
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
    fn keeps_one_copy_of_an_image_that_several_messages_repeat() {
        let events = json!([{"type": 2, "timestamp": 1, "data": {"node": {"attributes": {"src": uri(b"logo")}}}}]);
        let mut repeated = block("s", events.clone());
        repeated.messages.extend(block("s", events).messages);
        let (images, counts) =
            prepare_block(&repeated, &[6; 32], "2026-10", &mut io::sink()).unwrap();
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
        let mut keys = FlushKeys::default();
        for session in ["kept", "again"] {
            let (id, key) = session_key(session);
            keys.sessions.insert(id, key);
        }
        keys.team_months.insert(7, [6; 32]);
        let old_ref = replay_core_v4::refs::image_ref(
            7,
            "2026-10",
            &replay_core_v4::refs::reference_hash(&image_content_key(&[6; 32]), b"old"),
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
                )
                .unwrap()
            })
            .collect();
        assert_eq!(
            sealed[0].counts,
            WriterCounts {
                extracted: 2,
                bytes: 6,
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

        let session_frames = session_keyed_frames(&sealed);
        let memory = Arc::new(MemoryStore::default());
        let store: Arc<dyn BlobStore> = memory.clone();
        let rows = write_images(
            new_images(&mut sealed),
            &keys,
            "2026-10-15",
            "2026-10",
            "images-v4",
            "rrweb-v4",
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
        let context = block_context(&blocks[0].session, "2026-09");
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
            b"new"
        );
        // The team month key seals images, as the fetcher's, so a session key does not open them.
        assert!(open_frame(&[5; 32], Version::V4, &image_context, sealed_image).is_err());
        assert_eq!(memory.keys("index/images/dt=2026-10-15/").len(), 1);

        // The block index row points at the block, keeps the moments, and seals the visited pages.
        blocks[0].moments = vec![Moment {
            kind: "full_snapshot",
            window_id: "w1".into(),
            ts_ms: 1,
            event_index: 1,
        }];
        let stats = BlockStats {
            url_fingerprints: sealed[0].url_fingerprints.clone(),
            window_ids: vec!["w1".to_owned()],
            ..BlockStats::default()
        };
        assert_eq!(
            write_block_index(
                &[(&blocks[0], &stats, &written[0])],
                &keys,
                "rrweb-v4",
                store.as_ref(),
                at()
            )
            .await
            .unwrap(),
            1
        );
        let batch = memory.parquet(&memory.keys("index/blocks/")[0]);
        let column = |name: &str| {
            batch
                .column_by_name(name)
                .unwrap_or_else(|| panic!("no column {name}"))
                .clone()
        };
        let text = |name: &str| {
            column(name)
                .as_any()
                .downcast_ref::<StringArray>()
                .unwrap()
                .value(0)
                .to_owned()
        };
        assert_eq!(text("block_s3_key"), block.object_key);
        assert_eq!(
            column("block_byte_end")
                .as_any()
                .downcast_ref::<Int64Array>()
                .unwrap()
                .value(0),
            i64::try_from(block.byte_end).unwrap()
        );
        for (name, data_type) in [
            ("orphan_mutations", DataType::Int32),
            ("active_ms", DataType::Int64),
            ("rage_clicks", DataType::Int32),
            ("cold_start", DataType::Boolean),
            ("viewport_width", DataType::Int32),
            ("image_urls", DataType::Int32),
            ("decode_failures", DataType::Int32),
            ("mouse_interactions", DataType::Int32),
            ("touch_moves", DataType::Int32),
            ("moments_truncated", DataType::Boolean),
            ("written_jsonl_bytes", DataType::Int64),
            ("max_written_event_bytes", DataType::Int64),
        ] {
            assert_eq!(column(name).data_type(), &data_type, "{name}");
        }
        let strings = |name: &str| -> Vec<String> {
            let list = column(name);
            let values = list.as_any().downcast_ref::<ListArray>().unwrap().value(0);
            let values = values.as_any().downcast_ref::<StringArray>().unwrap();
            values.iter().map(|v| v.unwrap().to_owned()).collect()
        };
        assert_eq!(strings("url_fingerprints"), stats.url_fingerprints);
        assert_eq!(strings("window_ids"), ["w1"]);
        let moments = column("moments");
        let moments = moments
            .as_any()
            .downcast_ref::<ListArray>()
            .unwrap()
            .value(0);
        let moments = moments.as_any().downcast_ref::<StructArray>().unwrap();
        assert_eq!(
            moments.column_by_name("event_index").unwrap().data_type(),
            &DataType::Int32
        );
        let kinds = moments.column_by_name("kind").unwrap().clone();
        assert_eq!(
            kinds
                .as_any()
                .downcast_ref::<StringArray>()
                .unwrap()
                .value(0),
            "full_snapshot"
        );
        let envelope: Value = serde_json::from_str(&text("urls")).unwrap();
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
}
