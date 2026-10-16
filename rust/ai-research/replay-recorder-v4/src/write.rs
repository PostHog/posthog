//! Writes a flush: image packs and their index first, then one object of sealed session blocks, then their index.
//!
//! The order matters for a crash between writes. A pack without its blocks is unreferenced, which is harmless. A block
//! whose images were never stored would hold references that resolve to nothing.

use std::collections::{BTreeMap, HashSet};
use std::sync::Arc;

use chrono::{DateTime, Utc};
use futures::stream::{self, StreamExt, TryStreamExt};
use posthog_replay_anonymizer::scan::write_json_string;
use rand::Rng;
use replay_core_v4::envelope::{seal_frame, seal_json_envelope, Codec, Context, Version};
use replay_core_v4::inspect::events::event_page_url;
use replay_core_v4::inspect::stats::BlockStats;
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

/// Where one block landed, for the block index.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Written {
    pub session: SessionKey,
    pub key_day: String,
    pub object_key: String,
    /// Inclusive byte range of the sealed frame in the object, as v3 records it.
    pub byte_start: u64,
    pub byte_end: u64,
}

/// The image columns of a block's stats, which the writer fills.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ImageCounts {
    pub extracted: u32,
    pub bytes: u64,
    pub inline: u32,
}

/// A block sealed for one object, with the images it moved out.
pub struct SealedBlock {
    pub session: SessionKey,
    pub key_day: String,
    pub frame: Vec<u8>,
    pub images: Vec<Image>,
    pub counts: ImageCounts,
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

/// Moves a block's images out and builds its lines in the main lane's format: one `["window_id",event]` line per
/// event. `already_stored` names images an earlier flush of this process stored for the same team and day.
pub fn prepare_block(
    block: &Block,
    team_key: &[u8; 32],
    write_day: &str,
    already_stored: &dyn Fn(&str) -> bool,
) -> (Vec<u8>, Vec<Image>, ImageCounts) {
    let content_key = image_content_key(team_key);
    let mut images = Vec::new();
    let mut kept = HashSet::new();
    let mut counts = ImageCounts::default();
    let mut lines =
        Vec::with_capacity(block.stats.byte_size as usize + block.stats.event_count as usize * 16);
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
        counts.extracted += sink.images.len() as u32;
        counts.bytes += sink
            .images
            .iter()
            .map(|i| i.bytes.len() as u64)
            .sum::<u64>();
        counts.inline += sink.left_inline;
        images.extend(sink.images.into_iter().filter(|image| {
            !already_stored(&image.reference) && kept.insert(image.reference.clone())
        }));
    }
    (lines, images, counts)
}

/// Builds, compresses and seals one block.
pub fn seal_block(
    block: &Block,
    key: &Key,
    team_key: &[u8; 32],
    write_day: &str,
    already_stored: &dyn Fn(&str) -> bool,
) -> Result<SealedBlock, WriteError> {
    let (lines, images, counts) = prepare_block(block, team_key, write_day, already_stored);
    let compressed = zstd::bulk::compress(&lines, BLOCK_ZSTD_LEVEL)
        .map_err(|e| WriteError::Seal(e.to_string()))?;
    let frame = seal_frame(
        &key.key,
        Version::V4,
        &block_context(&block.session, &key.key_day),
        &compressed,
    )
    .map_err(|e| WriteError::Seal(e.to_string()))?;
    Ok(SealedBlock {
        session: block.session.clone(),
        key_day: key.key_day.clone(),
        frame,
        images,
        counts,
    })
}

/// The authenticated data of a block frame.
pub fn block_context(session: &SessionKey, key_day: &str) -> Context {
    Context {
        team_id: session.team_id,
        session_id: Some(session.session_id.clone()),
        key_day: Some(key_day.to_owned()),
        kind: "rrweb".to_owned(),
        codec: Some(Codec::Zstd),
        ..Context::default()
    }
}

/// The flush's new images by team, each once.
pub fn new_images(sealed: &mut [SealedBlock]) -> BTreeMap<i64, Vec<Image>> {
    let mut images: BTreeMap<i64, Vec<Image>> = BTreeMap::new();
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
    team_images: &[Image],
    team_key: &[u8; 32],
    write_day: &str,
    pack_key: &str,
) -> Result<(Vec<u8>, Vec<ImageIndexRow>), WriteError> {
    let mut pack = Vec::new();
    let mut rows = Vec::with_capacity(team_images.len());
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
            pack_s3_key: pack_key.to_owned(),
            byte_start,
            byte_end: pack.len() as u64 - 1,
            mime: image.mime.to_owned(),
            byte_size: image.bytes.len() as u64,
        });
    }
    Ok((pack, rows))
}

/// Seals each team's new images under its team day key into one pack, stores the packs concurrently, then writes the
/// image index for the flush.
#[allow(clippy::too_many_arguments)]
pub async fn write_images(
    images: BTreeMap<i64, Vec<Image>>,
    keys: &FlushKeys,
    write_day: &str,
    images_bucket: &str,
    rrweb_bucket: &str,
    store: &Arc<dyn BlobStore>,
    at: DateTime<Utc>,
    concurrency: usize,
) -> Result<Vec<ImageIndexRow>, WriteError> {
    let packs: Vec<_> = images
        .into_iter()
        .filter_map(|(team_id, team_images)| {
            let team_key = *keys.team_days.get(&team_id)?;
            let pack_key = format!(
                "images/packs/dt={write_day}/{team_id}/{}",
                unique_suffix(at)
            );
            let write_day = write_day.to_owned();
            let store = store.clone();
            Some(async move {
                let key = pack_key.clone();
                let (pack, rows) =
                    blocking(move || seal_pack(team_id, &team_images, &team_key, &write_day, &key))
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
            key_day: block.key_day.clone(),
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
    tokio::task::spawn_blocking(work)
        .await
        .map_err(|e| WriteError::Seal(e.to_string()))?
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
        key_day(at),
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
    use std::sync::Mutex;

    use aes_gcm::aead::{Aead, KeyInit, Payload};
    use aes_gcm::{Aes256Gcm, Nonce};
    use arrow_array::{Array, ListArray, RecordBatch, StringArray, StructArray, UInt64Array};
    use async_trait::async_trait;
    use base64::engine::general_purpose::STANDARD;
    use base64::Engine;
    use bytes::Bytes;
    use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
    use replay_core_v4::envelope::open_frame;
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
            image_urls: Vec::new(),
        }
    }

    fn uri(bytes: &[u8]) -> String {
        format!("data:image/png;base64,{}", STANDARD.encode(bytes))
    }

    fn session_key(session: &str) -> (SessionId, Key) {
        (
            SessionId {
                team_id: 7,
                session_id: session.to_owned(),
            },
            Key {
                key: [5; 32],
                key_day: "2026-10-14".to_owned(),
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
        let (_, images, counts) = prepare_block(&repeated, &[6; 32], "2026-10-15", &|_| false);
        assert_eq!((images.len(), counts.extracted), (1, 2));
    }

    #[tokio::test]
    async fn stores_images_once_and_blocks_that_point_at_them() {
        let events = json!([
            {"type": 4, "timestamp": 0, "data": {"href": "https://app.example.com/a"}},
            {"type": 2, "timestamp": 1, "data": {"node": {"attributes": {"src": uri(b"new"), "srcset": format!("{} 2x", uri(b"new"))}}}},
            {"type": 3, "timestamp": 2, "data": {"source": 0, "adds": [{"parentId": 1, "node": {"attributes": {"src": uri(b"old")}}}]}},
            {"type": 5, "timestamp": 3, "data": {"tag": "$url_changed", "payload": {"href": "https://app.example.com/b"}}},
        ]);
        let mut blocks = [block("kept", events.clone()), block("again", events)];
        let mut keys = FlushKeys::default();
        for session in ["kept", "again"] {
            let (id, key) = session_key(session);
            keys.sessions.insert(id, key);
        }
        keys.team_days.insert(7, [6; 32]);
        let old_ref = replay_core_v4::refs::image_ref(
            7,
            "2026-10-15",
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
                    "2026-10-15",
                    &|reference| reference == old_ref,
                )
                .unwrap()
            })
            .collect();
        assert_eq!(
            sealed[0].counts,
            ImageCounts {
                extracted: 2,
                bytes: 6,
                inline: 0
            }
        );

        let memory = Arc::new(MemoryStore::default());
        let store: Arc<dyn BlobStore> = memory.clone();
        let rows = write_images(
            new_images(&mut sealed),
            &keys,
            "2026-10-15",
            "images-v4",
            "rrweb-v4",
            &store,
            at(),
            4,
        )
        .await
        .unwrap();
        let written = write_blocks(&sealed, &object, "rrweb-v4", store.as_ref())
            .await
            .unwrap();

        // Both blocks moved the same new image out, and the pack holds it once. The image an earlier flush stored is
        // referenced but not packed again.
        assert_eq!(rows.len(), 1);
        assert_eq!(written.len(), 2);

        let block = &written[0];
        let frame = &memory.get("rrweb-v4", &block.object_key)
            [block.byte_start as usize..=block.byte_end as usize];
        let context = block_context(&blocks[0].session, "2026-10-14");
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
        let pack = memory.get("images-v4", &row.pack_s3_key);
        let image_context = Context {
            team_id: 7,
            key_day: Some("2026-10-15".to_owned()),
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
        assert_eq!(memory.keys("index/images/dt=2026-10-15/").len(), 1);

        // The block index row points at the block, keeps the moments, and seals the visited pages.
        blocks[0].moments = vec![Moment {
            kind: "full_snapshot",
            window_id: "w1".to_owned(),
            ts_ms: 1,
            event_index: 1,
        }];
        let stats = BlockStats::default();
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
        let sealed_urls = STANDARD
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
                    msg: &sealed_urls,
                    aad: aad.as_bytes(),
                },
            )
            .unwrap();
        assert_eq!(
            serde_json::from_slice::<Vec<String>>(&urls).unwrap(),
            ["https://app.example.com/a", "https://app.example.com/b"]
        );
    }
}
