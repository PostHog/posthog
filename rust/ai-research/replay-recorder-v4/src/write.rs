//! Writes a flush: image packs and their index first, then one object of sealed session blocks.
//!
//! The order matters for a crash between writes. A pack without its blocks is unreferenced, which is harmless. A block
//! whose images were never stored would hold references that resolve to nothing.

use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use posthog_replay_anonymizer::scan::{self, write_json_string};
use rand::Rng;
use replay_core_v4::envelope::{seal_frame, seal_json_envelope, Codec, Context, Version};
use replay_core_v4::inspect::rrweb::META;
use replay_core_v4::keys::batch::{FlushKeys, SessionId, SessionKey as Key};
use replay_core_v4::keys::rows::key_day;
use replay_core_v4::scan::cv::extract_event_images;
use replay_core_v4::scan::images::{Image, ImageLimits, ImageSink};
use replay_core_v4::seal::image_content_key;

use crate::batch::{Block, SessionKey};
use crate::index::{
    block_index, image_index, write_parquet, BlockIndexRow, ImageIndexRow, IndexError,
};
use crate::store::{BlobStore, StoreError};

/// zstd level for blocks: raw data lives 7 days, so CPU matters more than the last few percent of size.
const BLOCK_ZSTD_LEVEL: i32 = 3;

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
    pub key_day: String,
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

pub struct Prepared {
    pub blocks: Vec<PreparedBlock>,
    /// The flush's new images by team, each stored once.
    pub images: BTreeMap<i64, Vec<Image>>,
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
/// line per event. Fills the image columns of each block's stats. `already_stored` names images an earlier flush
/// of this process stored for the same team and day.
pub fn prepare(
    blocks: &mut [Block],
    keys: &FlushKeys,
    write_day: &str,
    already_stored: &dyn Fn(&str) -> bool,
) -> Prepared {
    let mut prepared = Prepared {
        blocks: Vec::new(),
        images: BTreeMap::new(),
    };
    for block in blocks.iter_mut() {
        let id = SessionId {
            team_id: block.session.team_id,
            session_id: block.session.session_id.clone(),
        };
        let (Some(key), Some(team_key)) = (
            keys.sessions.get(&id),
            keys.team_days.get(&block.session.team_id),
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
                write_day,
                ImageLimits::default(),
            );
            for event in &message.events {
                let extracted = extract_event_images(&message.inner, event, &mut sink);
                lines.push(b'[');
                lines.extend_from_slice(&window);
                lines.push(b',');
                lines.extend_from_slice(
                    extracted
                        .as_deref()
                        .unwrap_or(&message.inner[event.span.0..event.span.1]),
                );
                lines.extend_from_slice(b"]\n");
            }
            block.stats.images_extracted += sink.images.len() as u32;
            block.stats.image_bytes += sink
                .images
                .iter()
                .map(|i| i.bytes.len() as u64)
                .sum::<u64>();
            block.stats.images_inline += sink.left_inline;
            for image in sink.images {
                if !already_stored(&image.reference)
                    && !images.iter().any(|i| i.reference == image.reference)
                {
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

/// Seals each team's new images under its team day key into one pack, then writes the image index for the flush.
pub async fn write_images(
    images: &BTreeMap<i64, Vec<Image>>,
    keys: &FlushKeys,
    write_day: &str,
    images_bucket: &str,
    rrweb_bucket: &str,
    store: &dyn BlobStore,
    at: DateTime<Utc>,
) -> Result<Vec<ImageIndexRow>, WriteError> {
    let mut rows = Vec::new();
    for (&team_id, team_images) in images {
        let Some(team_key) = keys.team_days.get(&team_id) else {
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
                key_day: Some(write_day.to_owned()),
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
                key_day: write_day.to_owned(),
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
    let object_key = object_key(&key_day(at), at);
    let mut object = Vec::new();
    let mut written = Vec::new();
    for block in blocks {
        let compressed = zstd::bulk::compress(&block.lines, BLOCK_ZSTD_LEVEL)
            .map_err(|e| WriteError::Seal(e.to_string()))?;
        let context = Context {
            team_id: block.session.team_id,
            session_id: Some(block.session.session_id.clone()),
            key_day: Some(block.key.key_day.clone()),
            kind: "rrweb".to_owned(),
            codec: Some(Codec::Zstd),
            ..Context::default()
        };
        let frame = seal_frame(&block.key.key, Version::V4, &context, &compressed)
            .map_err(|e| WriteError::Seal(e.to_string()))?;
        let byte_start = object.len() as u64;
        object.extend_from_slice(&frame);
        written.push(Written {
            session: block.session.clone(),
            key_day: block.key.key_day.clone(),
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
pub fn block_urls(block: &Block) -> Vec<String> {
    let mut urls: Vec<String> = Vec::new();
    for message in &block.messages {
        for event in message.events.iter().filter(|e| e.kind == Some(META)) {
            let Some(data) = event.data.filter(|&d| scan::is_object(&message.inner, d)) else {
                continue;
            };
            let Ok(entries) = scan::object_entries(&message.inner, data) else {
                continue;
            };
            let href = entries
                .filter_map(Result::ok)
                .find(|e| !e.key_escaped && &message.inner[e.key.0..e.key.1] == b"href")
                .filter(|e| scan::is_string(&message.inner, e.value))
                .and_then(|e| scan::unescape(&message.inner, e.value).ok());
            if let Some(href) = href {
                if urls.last().map(String::as_str) != Some(&*href) {
                    urls.push(href.into_owned());
                }
            }
        }
    }
    urls
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
                key_day: Some(key.key_day.clone()),
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
        key_day(at),
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
    use std::sync::Mutex;

    use aes_gcm::aead::{Aead, KeyInit, Payload};
    use aes_gcm::{Aes256Gcm, Nonce};
    use arrow_array::{Array, ListArray, StringArray, StructArray, UInt64Array};
    use async_trait::async_trait;
    use base64::engine::general_purpose::STANDARD;
    use base64::Engine;
    use bytes::Bytes;
    use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
    use replay_core_v4::envelope::open_frame;
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

    fn uri(bytes: &[u8]) -> String {
        format!("data:image/png;base64,{}", STANDARD.encode(bytes))
    }

    #[tokio::test]
    async fn stores_images_once_and_blocks_that_point_at_them() {
        let events = json!([
            {"type": 4, "timestamp": 0, "data": {"href": "https://app.example.com/a"}},
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
                key_day: "2026-10-14".to_owned(),
            },
        );
        keys.team_days.insert(7, [6; 32]);
        let old_ref = replay_core_v4::refs::image_ref(
            7,
            "2026-10-15",
            &replay_core_v4::refs::reference_hash(&image_content_key(&[6; 32]), b"old"),
        );
        let prepared = prepare(&mut blocks, &keys, "2026-10-15", &|reference| {
            reference == old_ref
        });

        let store = MemoryStore::default();
        let at = DateTime::parse_from_rfc3339("2026-10-15T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let rows = write_images(
            &prepared.images,
            &keys,
            "2026-10-15",
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

        // The image an earlier flush stored is referenced but not packed again.
        assert_eq!(rows.len(), 1);
        assert_eq!(
            (
                blocks[0].stats.images_extracted,
                blocks[0].stats.images_inline
            ),
            (2, 0)
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
            key_day: Some("2026-10-14".to_owned()),
            kind: "rrweb".to_owned(),
            codec: Some(Codec::Zstd),
            ..Context::default()
        };
        let lines = String::from_utf8(
            zstd::decode_all(&open_frame(&[5; 32], Version::V4, &context, frame).unwrap()[..])
                .unwrap(),
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
            key_day: Some("2026-10-15".to_owned()),
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
        blocks[0].moments = vec![Moment {
            kind: "full_snapshot",
            window_id: "w1".to_owned(),
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
                .downcast_ref::<UInt64Array>()
                .unwrap()
                .value(0),
            block.byte_end
        );
        for name in [
            "orphan_mutations",
            "active_ms",
            "rage_clicks",
            "cold_start",
            "viewport_width",
            "image_urls",
        ] {
            column(name);
        }
        let moments = column("moments");
        let moments = moments
            .as_any()
            .downcast_ref::<ListArray>()
            .unwrap()
            .value(0);
        let kinds = moments
            .as_any()
            .downcast_ref::<StructArray>()
            .unwrap()
            .column_by_name("kind")
            .unwrap()
            .clone();
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
            key_day: Some("2026-10-14".to_owned()),
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
            ["https://app.example.com/a"]
        );
    }
}
