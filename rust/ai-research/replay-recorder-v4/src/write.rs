//! Writes a flush: image packs and their index first, then one object of sealed session blocks.
//!
//! The order matters for a crash between writes. A pack without its blocks is unreferenced, which is harmless. A block
//! whose images were never stored would hold references that resolve to nothing.

use std::collections::{BTreeMap, HashSet};
use std::io::Write;

use chrono::{DateTime, Utc};
use rand::Rng;
use replay_core_v4::bytescan::write_json_string;
use replay_core_v4::envelope::{seal_frame, Codec, Context, Version};
use replay_core_v4::keys::batch::{FlushKeys, SessionId, SessionKey as Key};
use replay_core_v4::keys::rows::write_day;
use replay_core_v4::scan::cv::extract_event_images;
use replay_core_v4::scan::images::{Image, ImageLimits, ImageSink};
use replay_core_v4::seal::image_content_key;

use crate::batch::{Block, SessionKey};
use crate::index::{image_index, write_parquet, ImageIndexRow, IndexError};
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
    };
    // A reference names its team, so it names one frame of the flush.
    let mut seen: HashSet<String> = HashSet::new();
    let mut seen_in_session: HashSet<(String, String)> = HashSet::new();
    for block in blocks.iter_mut() {
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
        let content_key = image_content_key(team_key);
        let images = prepared.images.entry(block.session.team_id).or_default();
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
                lines.extend_from_slice(
                    extracted
                        .as_deref()
                        .unwrap_or(&message.inner[event.span.0..event.span.1]),
                );
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
            for image in sink.images {
                if seen_in_session.insert((id.session_id.clone(), image.reference.clone())) {
                    prepared.session_frames += 1;
                }
                if seen.insert(image.reference.clone()) {
                    images.push(image);
                }
            }
        }
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

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::io::{self, Read};
    use std::sync::Mutex;

    use async_trait::async_trait;
    use base64::engine::general_purpose::STANDARD;
    use base64::Engine;
    use replay_core_v4::envelope::open_frame;
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
        let inner = json!({"event": "$snapshot_items", "properties": {"$session_id": session, "$window_id": "w1", "$snapshot_items": events}});
        let message = read_message(
            json!({"distinct_id": "d", "data": inner.to_string()})
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

    #[tokio::test]
    async fn stores_images_once_and_blocks_that_point_at_them() {
        let events = json!([
            {"type": 2, "timestamp": 1, "data": {"node": {"attributes": {"src": uri(b"new"), "srcset": format!("{} 2x", uri(b"new"))}}}},
            {"type": 3, "timestamp": 2, "data": {"source": 0, "adds": [{"parentId": 1, "node": {"attributes": {"src": uri(b"old")}}}]}},
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
        let first: Value = serde_json::from_str(lines.lines().next().unwrap()).unwrap();
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
    }
}
