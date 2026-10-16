//! Writes a flush: keys first, then one object of sealed session blocks.

use chrono::{DateTime, Utc};
use posthog_replay_anonymizer::scan::write_json_string;
use rand::Rng;
use replay_core_v4::envelope::{seal_frame, Codec, Context, Version};
use replay_core_v4::keys::batch::{FlushKeys, SessionId};
use replay_core_v4::keys::rows::key_day;

use crate::batch::{Block, SessionKey};
use crate::store::{BlobStore, StoreError};

/// zstd level for blocks: raw data lives 7 days, so CPU matters more than the last few percent of size.
const BLOCK_ZSTD_LEVEL: i32 = 3;

#[derive(Debug, thiserror::Error)]
pub enum WriteError {
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error("sealing a block failed: {0}")]
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

/// The block in the main lane's format: one `["window_id",event]` line per event.
pub fn block_lines(block: &Block) -> Vec<u8> {
    let mut lines =
        Vec::with_capacity(block.stats.byte_size as usize + block.stats.event_count as usize * 16);
    for message in &block.messages {
        let mut window = Vec::new();
        write_json_string(
            message.window_id.as_deref().unwrap_or_default(),
            &mut window,
        );
        for event in &message.events {
            lines.push(b'[');
            lines.extend_from_slice(&window);
            lines.push(b',');
            lines.extend_from_slice(&message.inner[event.span.0..event.span.1]);
            lines.extend_from_slice(b"]\n");
        }
    }
    lines
}

pub fn object_key(write_day: &str, at: DateTime<Utc>) -> String {
    format!(
        "blocks/dt={write_day}/{}-{:016x}",
        at.timestamp_millis(),
        rand::thread_rng().gen::<u64>()
    )
}

/// Seals each block under its session key into one object. Blocks whose session has no key, because a deletion
/// tombstoned it, are left out.
pub async fn write_blocks(
    blocks: &[Block],
    keys: &FlushKeys,
    bucket: &str,
    store: &dyn BlobStore,
    at: DateTime<Utc>,
) -> Result<Vec<Written>, WriteError> {
    let object_key = object_key(&key_day(at), at);
    let mut object = Vec::new();
    let mut written = Vec::new();
    for block in blocks {
        let id = SessionId {
            team_id: block.session.team_id,
            session_id: block.session.session_id.clone(),
        };
        let Some(session_key) = keys.sessions.get(&id) else {
            continue;
        };
        let compressed = zstd::bulk::compress(&block_lines(block), BLOCK_ZSTD_LEVEL)
            .map_err(|e| WriteError::Seal(e.to_string()))?;
        let context = Context {
            team_id: block.session.team_id,
            session_id: Some(block.session.session_id.clone()),
            key_day: Some(session_key.key_day.clone()),
            kind: "rrweb".to_owned(),
            codec: Some(Codec::Zstd),
            ..Context::default()
        };
        let frame = seal_frame(&session_key.key, Version::V4, &context, &compressed)
            .map_err(|e| WriteError::Seal(e.to_string()))?;
        let byte_start = object.len() as u64;
        object.extend_from_slice(&frame);
        written.push(Written {
            session: block.session.clone(),
            key_day: session_key.key_day.clone(),
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
    use std::sync::Mutex;

    use async_trait::async_trait;
    use replay_core_v4::envelope::open_frame;
    use replay_core_v4::inspect::stats::BlockStats;
    use replay_core_v4::keys::batch::SessionKey as Key;
    use replay_core_v4::scan::message::read_message;
    use serde_json::{json, Value};

    use super::*;

    #[derive(Default)]
    struct MemoryStore {
        objects: Mutex<HashMap<(String, String), Vec<u8>>>,
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
        let inner = json!({"event": "$snapshot_items", "properties": {"$session_id": session, "$window_id": "w\"1", "$snapshot_items": events}});
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

    #[tokio::test]
    async fn seals_each_kept_session_into_one_object_by_byte_range() {
        let events = json!([{"type": 4, "timestamp": 1, "data": {"href": "https://example.com"}}, {"type": 3, "timestamp": 2, "data": {"source": 1}}]);
        let blocks = [
            block("kept", events.clone()),
            block("tombstoned", events.clone()),
        ];
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
        let store = MemoryStore::default();
        let at = DateTime::parse_from_rfc3339("2026-10-15T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);

        let written = write_blocks(&blocks, &keys, "rrweb-v4", &store, at)
            .await
            .unwrap();
        assert_eq!(
            written
                .iter()
                .map(|w| w.session.session_id.as_str())
                .collect::<Vec<_>>(),
            vec!["kept"]
        );
        let block = &written[0];
        assert!(block.object_key.starts_with("blocks/dt=2026-10-15/"));
        assert_eq!(block.key_day, "2026-10-14");

        let object = store.objects.lock().unwrap()
            [&("rrweb-v4".to_owned(), block.object_key.clone())]
            .clone();
        let frame = &object[block.byte_start as usize..=block.byte_end as usize];
        let context = Context {
            team_id: 7,
            session_id: Some("kept".to_owned()),
            key_day: Some("2026-10-14".to_owned()),
            kind: "rrweb".to_owned(),
            codec: Some(Codec::Zstd),
            ..Context::default()
        };
        let lines =
            zstd::decode_all(&open_frame(&[5; 32], Version::V4, &context, frame).unwrap()[..])
                .unwrap();
        let lines: Vec<Value> = String::from_utf8(lines)
            .unwrap()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect();
        let expected: Vec<Value> = events
            .as_array()
            .unwrap()
            .iter()
            .map(|e| json!(["w\"1", e]))
            .collect();
        assert_eq!(lines, expected);

        let nothing = write_blocks(&blocks[1..], &keys, "rrweb-v4", &store, at)
            .await
            .unwrap();
        assert!(nothing.is_empty());
        assert_eq!(store.objects.lock().unwrap().len(), 1);
    }
}
