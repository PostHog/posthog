//! Writes a flush: image packs and their index first, then one object of sealed session blocks.
//!
//! The order matters for a crash between writes. A pack without its blocks is unreferenced, which is harmless. A block
//! whose images were never stored would hold references that resolve to nothing.

use std::collections::{BTreeMap, HashSet};
use std::io::Write;

use chrono::{DateTime, Utc};
use metrics::counter;
use rand::Rng;
use replay_core_v4::bytescan::write_json_string;
use replay_core_v4::envelope::{seal_frame, seal_json_envelope, Codec, Context, Version};
use replay_core_v4::inspect::events::event_page_url;
use replay_core_v4::inspect::stats::MAX_URL_FINGERPRINTS;
use replay_core_v4::keys::batch::{FlushKeys, SessionId, SessionKey as Key};
use replay_core_v4::keys::rows::write_day;
use replay_core_v4::refs::url_fingerprint;
use replay_core_v4::scan::cv::extract_event_images;
use replay_core_v4::scan::images::{Image, ImageLimits, ImageSink};
use replay_core_v4::seal::{image_content_key, url_fingerprint_key};

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

#[derive(Debug, thiserror::Error)]
pub enum WriteError {
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error(transparent)]
    Index(#[from] IndexError),
    #[error("sealing failed: {0}")]
    Seal(String),
}

/// Where one session's block landed, for the block index.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Written {
    pub session: SessionKey,
    pub key_month: String,
    pub object_key: String,
    /// Inclusive byte range of the sealed frame in the object, as v3 records it.
    pub byte_start: u64,
    pub byte_end: u64,
}

/// A session's block, ready to seal: its key, and its lines with the images moved out.
pub struct PreparedBlock {
    pub session: SessionKey,
    pub key: Key,
    pub lines: Vec<u8>,
}

fn block_encoder() -> Result<brotlic::BrotliEncoder, WriteError> {
    let seal_error = |e: brotlic::SetParameterError| WriteError::Seal(e.to_string());
    brotlic::BrotliEncoderOptions::new()
        .quality(brotlic::Quality::new(BLOCK_BROTLI_QUALITY).map_err(seal_error)?)
        .window_size(brotlic::WindowSize::new(BLOCK_BROTLI_WINDOW_BITS).map_err(seal_error)?)
        .build()
        .map_err(seal_error)
}

pub struct Prepared {
    pub blocks: Vec<PreparedBlock>,
    /// The flush's new images by team, each stored once.
    pub images: BTreeMap<i64, Vec<Image>>,
    /// The frames the packs would hold if each session sealed its images under its own key: one per distinct
    /// (session, reference) pair, where `images` holds one per reference.
    pub session_frames: u64,
    /// Which of the blocks it was given are stored. The fetch jobs come from these only.
    pub kept: Vec<bool>,
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

/// Moves each kept session's images out and builds its lines in the main lane's format: one `["window_id",event]`
/// line per event. Fills the image and written size columns of each block's stats. Every image goes into this
/// flush's packs, even one an earlier flush stored: a pack expires by its own write time, so it must be no older than
/// the blocks that reference it.
pub fn prepare(blocks: &mut [Block], keys: &FlushKeys, key_month: &str) -> Prepared {
    let mut prepared = Prepared {
        blocks: Vec::new(),
        images: BTreeMap::new(),
        session_frames: 0,
        kept: vec![false; blocks.len()],
    };
    // A reference names its team, so it names one frame of the flush.
    let mut seen: HashSet<String> = HashSet::new();
    let mut seen_in_session: HashSet<(String, String)> = HashSet::new();
    for (index, block) in blocks.iter_mut().enumerate() {
        let id = SessionId {
            team_id: block.session.team_id,
            session_id: block.session.session_id.clone(),
        };
        let (Some(key), Some(team_key)) = (
            keys.sessions.get(&id),
            keys.team_months.get(&block.session.team_id),
        ) else {
            continue;
        };
        // Fail closed: the inspector did not name every URL, so one it missed could be declined.
        if let Some(limit) = block.url_limit {
            counter!("ai_research_v4_recorder_dropped_blocks_total", "outcome" => limit.label())
                .increment(1);
            continue;
        }
        let content_key = image_content_key(team_key);
        let mut rewrite = UrlRewrite::new(
            &block.remote_urls,
            block.session.team_id,
            key_month,
            team_key,
        );
        block.stats.url_fingerprints = url_fingerprints(&key.key, &block_urls(block));
        let mut block_images = Vec::new();
        let mut lines = Vec::with_capacity(
            block.stats.byte_size as usize + block.stats.event_count as usize * 16,
        );
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
                let line_start = lines.len();
                lines.push(b'[');
                lines.extend_from_slice(&window);
                lines.push(b',');
                let canonical = canonical_strings(
                    extracted
                        .as_deref()
                        .unwrap_or(&message.inner[event.span.0..event.span.1]),
                );
                lines.extend_from_slice(&rewrite.apply(&canonical));
                lines.extend_from_slice(b"]\n");
                let line = (lines.len() - line_start) as u64;
                block.stats.written_jsonl_bytes += line;
                block.stats.max_written_event_bytes = block.stats.max_written_event_bytes.max(line);
            }
            block.stats.images_extracted += sink.images.len() as u32;
            block.stats.image_bytes += sink
                .images
                .iter()
                .map(|i| i.bytes.len() as u64)
                .sum::<u64>();
            block.stats.images_inline += sink.left_inline;
            block_images.extend(sink.images);
        }
        // Fail closed: a declined URL, a credential or a private host, must not reach storage.
        if !rewrite.finish() {
            counter!("ai_research_v4_recorder_dropped_blocks_total", "outcome" => "declined_unrewritten")
                .increment(1);
            continue;
        }
        let images = prepared.images.entry(block.session.team_id).or_default();
        for image in block_images {
            if seen_in_session.insert((id.session_id.clone(), image.reference.clone())) {
                prepared.session_frames += 1;
            }
            if seen.insert(image.reference.clone()) {
                images.push(image);
            }
        }
        prepared.kept[index] = true;
        prepared.blocks.push(PreparedBlock {
            session: block.session.clone(),
            key: key.clone(),
            lines,
        });
    }
    prepared.images.retain(|_, images| !images.is_empty());
    prepared
}

/// Seals each team's images under its team month key into one pack, then writes the image index for the flush.
#[allow(clippy::too_many_arguments)]
pub async fn write_images(
    images: &BTreeMap<i64, Vec<Image>>,
    keys: &FlushKeys,
    write_day: &str,
    key_month: &str,
    images_bucket: &str,
    rrweb_bucket: &str,
    store: &dyn BlobStore,
    at: DateTime<Utc>,
) -> Result<Vec<ImageIndexRow>, WriteError> {
    let mut rows = Vec::new();
    for (&team_id, team_images) in images {
        let Some(team_key) = keys.team_months.get(&team_id) else {
            continue;
        };
        let pack_key = format!(
            "images/packs/dt={write_day}/{team_id}/{}",
            unique_suffix(at)
        );
        let mut pack = Vec::new();
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
                pack_s3_key: pack_key.clone(),
                byte_start,
                byte_end: pack.len() as u64 - 1,
                mime: image.mime.to_owned(),
                byte_size: image.bytes.len() as u64,
            });
        }
        store.put_new(images_bucket, &pack_key, pack).await?;
    }
    if !rows.is_empty() {
        let index_key = format!("index/images/dt={write_day}/{}.parquet", unique_suffix(at));
        store
            .put_new(
                rrweb_bucket,
                &index_key,
                write_parquet(&image_index(&rows)?)?,
            )
            .await?;
    }
    Ok(rows)
}

/// Seals each prepared block under its session key into one object.
pub async fn write_blocks(
    blocks: &[PreparedBlock],
    bucket: &str,
    store: &dyn BlobStore,
    at: DateTime<Utc>,
) -> Result<Vec<Written>, WriteError> {
    let object_key = object_key(&write_day(at), at);
    let mut object = Vec::new();
    let mut written = Vec::new();
    for block in blocks {
        let mut encoder = brotlic::CompressorWriter::with_encoder(block_encoder()?, Vec::new());
        encoder
            .write_all(&block.lines)
            .map_err(|e| WriteError::Seal(e.to_string()))?;
        let compressed = encoder
            .into_inner()
            .map_err(|e| WriteError::Seal(e.to_string()))?;
        let context = Context {
            team_id: block.session.team_id,
            session_id: Some(block.session.session_id.clone()),
            key_month: Some(block.key.key_month.clone()),
            kind: "rrweb".to_owned(),
            codec: Some(Codec::Brotli),
            ..Context::default()
        };
        let frame = seal_frame(&block.key.key, Version::V4, &context, &compressed)
            .map_err(|e| WriteError::Seal(e.to_string()))?;
        let byte_start = object.len() as u64;
        object.extend_from_slice(&frame);
        written.push(Written {
            session: block.session.clone(),
            key_month: block.key.key_month.clone(),
            object_key: object_key.clone(),
            byte_start,
            byte_end: object.len() as u64 - 1,
        });
    }
    if !written.is_empty() {
        store.put_new(bucket, &object_key, object).await?;
    }
    Ok(written)
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
pub async fn write_block_index(
    blocks: &[Block],
    written: &[Written],
    keys: &FlushKeys,
    rrweb_bucket: &str,
    store: &dyn BlobStore,
    at: DateTime<Utc>,
) -> Result<usize, WriteError> {
    let by_session: BTreeMap<&SessionKey, &Block> =
        blocks.iter().map(|b| (&b.session, b)).collect();
    let mut rows = Vec::with_capacity(written.len());
    for written in written {
        let Some(block) = by_session.get(&written.session) else {
            continue;
        };
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
            stats: &block.stats,
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
    store
        .put_new(
            rrweb_bucket,
            &index_key,
            write_parquet(&block_index(&rows)?)?,
        )
        .await?;
    Ok(rows.len())
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::io::{self, Read};
    use std::sync::Mutex;

    use aes_gcm::aead::{Aead, KeyInit, Payload};
    use aes_gcm::{Aes256Gcm, Nonce};
    use arrow_array::{Array, Int64Array, ListArray, StringArray, StructArray};
    use arrow_schema::DataType;
    use async_trait::async_trait;
    use base64::engine::general_purpose::STANDARD;
    use base64::Engine;
    use bytes::Bytes;
    use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
    use replay_core_v4::envelope::open_frame;
    use replay_core_v4::inspect::dom::MAX_REMOTE_URL_BYTES;
    use replay_core_v4::inspect::session::Moment;
    use replay_core_v4::inspect::stats::BlockStats;
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

    /// The length of each line, its line break included.
    fn lines_of(lines: &[u8]) -> impl Iterator<Item = u64> + '_ {
        lines
            .split_inclusive(|&b| b == b'\n')
            .map(|line| line.len() as u64)
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
        let mut keys = FlushKeys::default();
        keys.sessions.insert(
            SessionId {
                team_id: 7,
                session_id: "kept".to_owned(),
            },
            Key {
                key: [5; 32],
                key_month: "2026-10".to_owned(),
            },
        );
        keys.team_months.insert(7, [6; 32]);
        let mut blocks = vec![inspected];
        let prepared = prepare(&mut blocks, &keys, "2026-10");
        prepared
            .blocks
            .first()
            .map(|b| String::from_utf8(b.lines.clone()).unwrap())
            .unwrap_or_default()
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
        let mut blocks = vec![block("kept", events.clone()), block("dropped", events)];
        for block in &mut blocks {
            block.image_urls = vec![fetched.to_owned()];
            block.remote_urls = vec![fetched.to_owned(), declined.to_owned()];
        }
        blocks[1].url_limit = Some(replay_core_v4::inspect::dom::UrlLimit::UrlLength);
        let mut keys = FlushKeys::default();
        for session in ["kept", "dropped"] {
            keys.sessions.insert(
                SessionId {
                    team_id: 7,
                    session_id: session.to_owned(),
                },
                Key {
                    key: [5; 32],
                    key_month: "2026-10".to_owned(),
                },
            );
        }
        keys.team_months.insert(7, [6; 32]);
        let prepared = prepare(&mut blocks, &keys, "2026-10");
        // Only a stored block sends fetch jobs.
        assert_eq!(prepared.kept, [true, false]);
        let jobs = crate::urls::fetch_jobs(&mut blocks[..1], &keys, "2026-10", 1, &|_| false);
        let lines = String::from_utf8(prepared.blocks[0].lines.clone()).unwrap();
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

    #[tokio::test]
    async fn stores_images_once_and_blocks_that_point_at_them() {
        let events = json!([
            {"type": 4, "timestamp": 0, "data": {"href": "https://app.example.com/a"}},
            {"type": 2, "timestamp": 1, "data": {"node": {"attributes": {"src": uri(b"new"), "srcset": format!("{} 2x", uri(b"new"))}}}},
            {"type": 3, "timestamp": 2, "data": {"source": 0, "adds": [{"parentId": 1, "node": {"attributes": {"src": uri(b"old")}}}]}},
            {"type": 5, "timestamp": 3, "data": {"tag": "$url_changed", "payload": {"href": "https://app.example.com/b"}}},
            {"type": 4, "timestamp": 4, "data": {"href": "https://app.example.com/a"}},
        ]);
        let mut blocks = vec![block("kept", events.clone()), block("tombstoned", events)];
        let mut keys = FlushKeys::default();
        keys.sessions.insert(
            SessionId {
                team_id: 7,
                session_id: "kept".to_owned(),
            },
            Key {
                key: [5; 32],
                key_month: "2026-09".to_owned(),
            },
        );
        keys.team_months.insert(7, [6; 32]);
        let old_ref = replay_core_v4::refs::image_ref(
            7,
            "2026-10",
            &replay_core_v4::refs::reference_hash(&image_content_key(&[6; 32]), b"old"),
        );
        let prepared = prepare(&mut blocks, &keys, "2026-10");

        // The same image in two sessions of the team is one frame and one index row.
        let same = json!([{"type": 2, "timestamp": 1, "data": {"node": {"attributes": {"src": uri(b"shared")}}}}]);
        let mut two = vec![block("kept", same.clone()), block("other", same)];
        let mut both = FlushKeys::default();
        both.team_months.insert(7, [6; 32]);
        for (session, key) in [("kept", [5; 32]), ("other", [4; 32])] {
            both.sessions.insert(
                SessionId {
                    team_id: 7,
                    session_id: session.to_owned(),
                },
                Key {
                    key,
                    key_month: "2026-10".to_owned(),
                },
            );
        }
        // A key per session would need a frame in each.
        let shared = prepare(&mut two, &both, "2026-10");
        assert_eq!((shared.images[&7].len(), shared.session_frames), (1, 2));

        let store = MemoryStore::default();
        let at = DateTime::parse_from_rfc3339("2026-10-15T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let rows = write_images(
            &prepared.images,
            &keys,
            "2026-10-15",
            "2026-10",
            "images-v4",
            "rrweb-v4",
            &store,
            at,
        )
        .await
        .unwrap();
        let written = write_blocks(&prepared.blocks, "rrweb-v4", &store, at)
            .await
            .unwrap();

        // The pack holds both images, also the one an earlier flush stored.
        assert_eq!(rows.len(), 2);
        assert!(rows.iter().any(|row| row.image_ref == old_ref));
        assert_eq!(
            (
                blocks[0].stats.images_extracted,
                blocks[0].stats.images_inline
            ),
            (2, 0)
        );
        let longest = lines_of(&prepared.blocks[0].lines).max().unwrap();
        assert_eq!(
            (
                blocks[0].stats.written_jsonl_bytes,
                blocks[0].stats.max_written_event_bytes
            ),
            (prepared.blocks[0].lines.len() as u64, longest)
        );
        assert_eq!(
            written
                .iter()
                .map(|w| w.session.session_id.as_str())
                .collect::<Vec<_>>(),
            vec!["kept"]
        );

        let block = &written[0];
        let frame = &store.get("rrweb-v4", &block.object_key)
            [block.byte_start as usize..=block.byte_end as usize];
        let context = Context {
            team_id: 7,
            session_id: Some("kept".to_owned()),
            key_month: Some("2026-09".to_owned()),
            kind: "rrweb".to_owned(),
            codec: Some(Codec::Brotli),
            ..Context::default()
        };
        let lines = String::from_utf8(
            decompress(&open_frame(&[5; 32], Version::V4, &context, frame).unwrap()).unwrap(),
        )
        .unwrap();
        let first: Value = serde_json::from_str(lines.lines().nth(1).unwrap()).unwrap();
        let reference = first[1]["data"]["node"]["attributes"]["src"]
            .as_str()
            .unwrap();
        assert_eq!(reference, rows[0].image_ref);
        assert!(lines.contains(&old_ref) && !lines.contains("base64"));

        // The reference resolves through the index to the image's bytes in the pack.
        let row = &rows[0];
        let pack = store.get("images-v4", &row.pack_s3_key);
        let image_context = Context {
            team_id: 7,
            key_month: Some("2026-10".to_owned()),
            kind: "image".to_owned(),
            codec: Some(Codec::None),
            reference: Some(row.image_ref.clone()),
            ..Context::default()
        };
        let sealed = &pack[row.byte_start as usize..=row.byte_end as usize];
        assert_eq!(
            open_frame(&[6; 32], Version::V4, &image_context, sealed).unwrap(),
            b"new"
        );
        // The team month key seals images, as the fetcher's, so the session key does not open them.
        assert!(open_frame(&[5; 32], Version::V4, &image_context, sealed).is_err());
        assert_eq!(
            store
                .objects
                .lock()
                .unwrap()
                .keys()
                .filter(|(_, key)| key.starts_with("index/images/dt=2026-10-15/"))
                .count(),
            1
        );

        // The block index row points at the block, keeps the moments, and seals the visited pages.
        blocks[0].stats.window_ids = vec!["w1".to_owned()];
        blocks[0].moments = vec![Moment {
            kind: "full_snapshot",
            window_id: "w1".into(),
            ts_ms: 1,
            event_index: 1,
        }];
        assert_eq!(
            write_block_index(&blocks, &written, &keys, "rrweb-v4", &store, at)
                .await
                .unwrap(),
            1
        );
        let index_key = store
            .objects
            .lock()
            .unwrap()
            .keys()
            .find(|(_, key)| key.starts_with("index/blocks/"))
            .unwrap()
            .1
            .clone();
        let batch = ParquetRecordBatchReaderBuilder::try_new(Bytes::from(
            store.get("rrweb-v4", &index_key),
        ))
        .unwrap()
        .build()
        .unwrap()
        .next()
        .unwrap()
        .unwrap();
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
        // The page the block sees again keeps its first place, under the session's own fingerprint key.
        let fingerprint_key = replay_core_v4::seal::url_fingerprint_key(&[5; 32]);
        let fingerprint = |path: &str| {
            url_fingerprint(&fingerprint_key, &format!("https://app.example.com{path}"))
        };
        assert_eq!(
            strings("url_fingerprints"),
            [fingerprint("/a"), fingerprint("/b")]
        );
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
        let sealed = STANDARD
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
                    msg: &sealed,
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
