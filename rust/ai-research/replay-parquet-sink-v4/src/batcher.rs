//! Buffers v4 index rows across Kafka batches and writes one Parquet file per index and write day on each flush.
//! Offsets are stored only after every file that holds their rows is written, so a failed write replays
//! (at-least-once). A flush that succeeds then writes the watermark files of the partitions this consumer still owns.

use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use async_trait::async_trait;
use serde::Serialize;

use crate::columns::Index;
use crate::metrics;
use crate::parquet;
use crate::row::{parse_index_message, Headers, Row};
use crate::watermark::{CaptureWatermark, CapturedData, CapturedRecord};

/// The batcher rewrites the watermark files on the first flush or poll after this interval, so a file of a running
/// sink is at most this interval plus one poll old. Readers call a file older than about 15 minutes stalled.
pub const WATERMARK_FILE_INTERVAL: Duration = Duration::from_secs(180);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Tp {
    pub topic: &'static str,
    pub partition: i32,
}

#[derive(Debug, Clone)]
pub struct Message<'m> {
    pub tp: Tp,
    pub offset: i64,
    pub headers: Headers,
    pub value: Option<&'m [u8]>,
}

#[derive(Debug, thiserror::Error)]
#[error("{0}")]
pub struct StoreError(pub String);

#[async_trait]
pub trait IndexStore: Send + Sync {
    /// Writes an index file, which must not exist yet. Every key is new, so an existing object means the SDK retried
    /// this same write, and the first write stands.
    async fn put_new(&self, key: &str, body: Vec<u8>) -> Result<(), StoreError>;

    async fn put_json(&self, key: &str, body: Vec<u8>) -> Result<(), StoreError>;
}

pub trait OffsetStore: Send {
    fn store(&self, offsets: &[(Tp, i64)]) -> Result<(), String>;
}

#[derive(Debug, Clone)]
pub struct Options {
    pub flush_interval: Duration,
    pub max_rows: usize,
    pub max_bytes: usize,
    pub row_group_rows: usize,
    /// A flush longer than this can outlast the consumer's poll interval, after which the group may have given the
    /// partitions away, so the flush then leaves the watermark files to the next poll.
    pub owned_for: Duration,
}

#[derive(Debug)]
struct BufferedRow {
    row: Row,
    tp: Tp,
    bytes: usize,
}

#[derive(Debug)]
struct Group {
    index: Index,
    write_day: String,
    rows: Vec<BufferedRow>,
}

pub fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |since| since.as_millis() as i64)
}

pub fn index_file_key(index: Index, write_day: &str, now_ms: i64) -> String {
    format!(
        "index/{}/dt={write_day}/{now_ms}-{:016x}.parquet",
        index.as_str(),
        rand::random::<u64>()
    )
}

pub fn watermark_file_key(index: Index, partition: i32) -> String {
    format!(
        "index/{}/_watermarks/partition={partition:04}.json",
        index.as_str()
    )
}

#[derive(Serialize)]
struct WatermarkFile {
    partition: i32,
    complete_up_to_capture_ms: i64,
    committed_offset: i64,
    written_at_ms: i64,
}

pub struct Batcher<O: OffsetStore> {
    store: Arc<dyn IndexStore>,
    offset_store: O,
    watermark: Arc<Mutex<CaptureWatermark>>,
    options: Options,
    groups: Vec<Group>,
    row_count: usize,
    buffered_bytes: usize,
    pending_offsets: HashMap<Tp, i64>,
    stored_offsets: HashMap<Tp, i64>,
    last_watermark_write_ms: Option<i64>,
    /// Partitions revoked since their last message. Their offsets are the next owner's to store.
    revoked: HashSet<Tp>,
    last_flush_ms: i64,
    clock: fn() -> i64,
}

impl<O: OffsetStore> Batcher<O> {
    pub fn new(
        store: Arc<dyn IndexStore>,
        offset_store: O,
        watermark: Arc<Mutex<CaptureWatermark>>,
        options: Options,
        now_ms: i64,
    ) -> Self {
        Self {
            store,
            offset_store,
            watermark,
            options,
            groups: Vec::new(),
            row_count: 0,
            buffered_bytes: 0,
            pending_offsets: HashMap::new(),
            stored_offsets: HashMap::new(),
            last_watermark_write_ms: None,
            revoked: HashSet::new(),
            last_flush_ms: now_ms,
            clock: self::now_ms,
        }
    }

    pub fn with_clock(mut self, clock: fn() -> i64) -> Self {
        self.clock = clock;
        self
    }

    pub fn row_count(&self) -> usize {
        self.row_count
    }

    /// Buffers the rows of one batch of messages and takes its offsets. Rejected rows are skipped, and their offsets
    /// still commit, so a bad row cannot wedge its partition.
    pub fn add(&mut self, messages: &[Message<'_>]) {
        let mut captured = Vec::new();
        let mut highest: HashMap<Tp, i64> = HashMap::new();
        for message in messages {
            // A message proves the partition is assigned to this consumer again.
            self.revoked.remove(&message.tp);
            let index = message.headers.index();
            if let (Some(index), Some(captured_at_ms)) = (index, message.headers.captured_at_ms()) {
                captured.push(CapturedRecord {
                    tp: message.tp,
                    offset: message.offset,
                    data: CapturedData::of(index),
                    captured_at_ms,
                });
            }
            match parse_index_message(&message.headers, message.value) {
                Ok(parsed) => self.push(
                    parsed.index,
                    parsed.write_day,
                    BufferedRow {
                        row: parsed.row,
                        tp: message.tp,
                        bytes: message.value.map_or(0, <[u8]>::len),
                    },
                ),
                Err(rejected) => tracing::warn!(
                    reason = rejected.reason.as_str(),
                    partition = message.tp.partition,
                    offset = message.offset,
                    column = rejected.invalid_column.as_deref(),
                    team_id = rejected.team_id,
                    session_id = rejected.session_id.as_deref(),
                    "ai_research_v4_parquet_row_rejected"
                ),
            }
            highest
                .entry(message.tp)
                .and_modify(|offset| *offset = (*offset).max(message.offset))
                .or_insert(message.offset);
        }
        self.watermark.lock().unwrap().hold(&captured);
        for (tp, offset) in highest {
            self.pending_offsets.insert(tp, offset + 1);
        }
    }

    fn push(&mut self, index: Index, write_day: String, buffered: BufferedRow) {
        self.row_count += 1;
        self.buffered_bytes += buffered.bytes;
        match self
            .groups
            .iter_mut()
            .find(|group| group.index == index && group.write_day == write_day)
        {
            Some(group) => group.rows.push(buffered),
            None => self.groups.push(Group {
                index,
                write_day,
                rows: vec![buffered],
            }),
        }
    }

    /// Drops the buffered rows and offsets of revoked partitions. Their new owner reads them again from the committed
    /// offset, so writing them here would only duplicate them, and this consumer can no longer store their offsets.
    pub fn release(&mut self, partitions: &[Tp]) {
        let revoked: HashSet<Tp> = partitions.iter().copied().collect();
        for tp in &revoked {
            self.revoked.insert(*tp);
            self.pending_offsets.remove(tp);
            self.stored_offsets.remove(tp);
        }
        let mut released = 0;
        for group in &mut self.groups {
            group.rows.retain(|buffered| {
                let keep = !revoked.contains(&buffered.tp);
                if !keep {
                    released += 1;
                    self.buffered_bytes -= buffered.bytes;
                }
                keep
            });
        }
        self.groups.retain(|group| !group.rows.is_empty());
        self.row_count -= released;
        metrics::rows_released(released as u64);
        self.watermark.lock().unwrap().forget(partitions);
    }

    pub fn should_flush(&self, now_ms: i64) -> bool {
        if self.row_count >= self.options.max_rows || self.buffered_bytes >= self.options.max_bytes
        {
            return true;
        }
        // Offsets of messages that gave no rows also flush on the interval, so they do not replay forever.
        let has_pending = self.row_count > 0 || !self.pending_offsets.is_empty();
        has_pending && now_ms - self.last_flush_ms >= self.options.flush_interval.as_millis() as i64
    }

    pub fn watermark_files_due(&self, now_ms: i64) -> bool {
        !self.stored_offsets.is_empty()
            && self
                .last_watermark_write_ms
                .is_none_or(|last| now_ms - last >= WATERMARK_FILE_INTERVAL.as_millis() as i64)
    }

    pub async fn flush(&mut self, now_ms: i64) -> Result<(), StoreError> {
        let started = Instant::now();
        self.write_taken(now_ms).await?;
        if started.elapsed() < self.options.owned_for {
            self.write_watermark_files_if_due(now_ms).await;
        }
        Ok(())
    }

    pub async fn write_watermark_files_if_due(&mut self, now_ms: i64) {
        if !self.watermark_files_due(now_ms) {
            return;
        }
        self.last_watermark_write_ms = Some(now_ms);
        self.write_watermark_files((self.clock)()).await;
    }

    async fn write_taken(&mut self, now_ms: i64) -> Result<(), StoreError> {
        self.last_flush_ms = now_ms;
        let groups = std::mem::take(&mut self.groups);
        let offsets = std::mem::take(&mut self.pending_offsets);
        self.row_count = 0;
        self.buffered_bytes = 0;
        let wrote_files = !groups.is_empty();
        let mut unwritten = groups.into_iter();
        while let Some(group) = unwritten.next() {
            let (written, group) = self.write_group(group).await;
            match written {
                Ok((key, bytes)) => {
                    metrics::file_written(group.index, group.rows.len(), bytes);
                    tracing::info!(
                        key,
                        rows = group.rows.len(),
                        bytes,
                        "ai_research_v4_parquet_index_written"
                    );
                }
                Err(error) => {
                    metrics::write_error();
                    self.restore(std::iter::once(group).chain(unwritten), offsets);
                    return Err(error);
                }
            }
        }
        let assigned: Vec<(Tp, i64)> = offsets
            .iter()
            .filter(|(tp, _)| !self.revoked.contains(tp))
            .map(|(tp, offset)| (*tp, *offset))
            .collect();
        if !assigned.is_empty() {
            if let Err(error) = self.offset_store.store(&assigned) {
                self.restore(std::iter::empty(), offsets);
                return Err(StoreError(error));
            }
            // A refused store leaves the records to be read again, so the watermark moves only after it.
            self.watermark
                .lock()
                .unwrap()
                .release(&assigned, (self.clock)());
            self.stored_offsets.extend(assigned);
        }
        if !offsets.is_empty() {
            metrics::flushed(wrote_files);
        }
        Ok(())
    }

    /// Encodes off the async threads, so the health heartbeat keeps running during a long encode.
    async fn write_group(&self, group: Group) -> (Result<(String, usize), StoreError>, Group) {
        let row_group_rows = self.options.row_group_rows;
        let encoded = tokio::task::spawn_blocking(move || {
            let body = parquet::encode(
                group.index,
                group.rows.iter().map(|b| &b.row),
                row_group_rows,
            );
            (body, group)
        })
        .await;
        let (body, group) = match encoded {
            Ok(encoded) => encoded,
            Err(error) => panic!("encoding a v4 index file panicked: {error}"),
        };
        let body = match body {
            Ok(body) => body,
            Err(error) => return (Err(StoreError(format!("encoding failed: {error}"))), group),
        };
        let bytes = body.len();
        let key = index_file_key(group.index, &group.write_day, (self.clock)());
        let written = self.store.put_new(&key, body).await.map(|()| (key, bytes));
        (written, group)
    }

    fn restore(&mut self, unwritten: impl Iterator<Item = Group>, offsets: HashMap<Tp, i64>) {
        for mut group in unwritten {
            group
                .rows
                .retain(|buffered| !self.revoked.contains(&buffered.tp));
            self.row_count += group.rows.len();
            self.buffered_bytes += group
                .rows
                .iter()
                .map(|buffered| buffered.bytes)
                .sum::<usize>();
            match self.groups.iter_mut().find(|current| {
                current.index == group.index && current.write_day == group.write_day
            }) {
                Some(current) => {
                    group.rows.append(&mut current.rows);
                    current.rows = group.rows;
                }
                None if !group.rows.is_empty() => self.groups.push(group),
                None => {}
            }
        }
        for (tp, offset) in offsets {
            if !self.revoked.contains(&tp) {
                self.pending_offsets.entry(tp).or_insert(offset);
            }
        }
    }

    /// A failed write never fails the flush that called it.
    async fn write_watermark_files(&self, now_ms: i64) {
        let captured: HashMap<(Tp, CapturedData), i64> = self
            .watermark
            .lock()
            .unwrap()
            .snapshot(now_ms)
            .into_iter()
            .map(|row| ((row.tp, row.data), row.captured_at_ms))
            .collect();
        let mut writes = Vec::new();
        for (tp, offset) in &self.stored_offsets {
            for index in [Index::Blocks, Index::Images] {
                let Some(complete_up_to_capture_ms) = captured.get(&(*tp, CapturedData::of(index)))
                else {
                    continue;
                };
                let file = WatermarkFile {
                    partition: tp.partition,
                    complete_up_to_capture_ms: *complete_up_to_capture_ms,
                    committed_offset: *offset,
                    written_at_ms: now_ms,
                };
                let key = watermark_file_key(index, tp.partition);
                let store = self.store.clone();
                writes.push(async move {
                    let body = serde_json::to_vec(&file).expect("a watermark file serializes");
                    match store.put_json(&key, body).await {
                        Ok(()) => metrics::watermark_write(index, "written"),
                        Err(error) => {
                            metrics::watermark_write(index, "failed");
                            tracing::warn!(key, %error, "ai_research_v4_parquet_watermark_write_failed");
                        }
                    }
                });
            }
        }
        futures::future::join_all(writes).await;
    }
}

#[cfg(test)]
mod tests {
    use std::cell::Cell;

    use ::parquet::record::Field;
    use serde_json::{json, Value};

    use super::*;
    use crate::row::{CAPTURE_TIMESTAMP_HEADER, INDEX_HEADER, WRITE_DAY_HEADER};
    use crate::testing::{block_row, image_row, read_column};

    const TOPIC: &str = "ai_research_v4_index";
    const WALL_CLOCK_MS: i64 = 1_790_000_000_000;
    thread_local! {
        /// Each test runs on its own thread, so each has its own clock.
        static CLOCK: Cell<i64> = const { Cell::new(WALL_CLOCK_MS) };
    }

    fn clock() -> i64 {
        CLOCK.get()
    }

    fn set_clock(ms: i64) {
        CLOCK.set(ms);
    }

    fn tp(partition: i32) -> Tp {
        Tp {
            topic: TOPIC,
            partition,
        }
    }

    #[derive(Default)]
    struct FakeStore {
        puts: Mutex<Vec<(String, Vec<u8>)>>,
        failing: Mutex<Option<(String, usize)>>,
        steps: Arc<Mutex<Vec<String>>>,
    }

    impl FakeStore {
        fn fail(&self, key_part: &str, times: usize) {
            *self.failing.lock().unwrap() = Some((key_part.to_owned(), times));
        }

        fn record(&self, key: &str, body: Vec<u8>) -> Result<(), StoreError> {
            let mut failing = self.failing.lock().unwrap();
            if let Some((part, times)) = failing.as_mut() {
                if *times > 0 && key.contains(part.as_str()) {
                    *times -= 1;
                    return Err(StoreError("s3 down".to_owned()));
                }
            }
            self.steps.lock().unwrap().push(key.to_owned());
            self.puts.lock().unwrap().push((key.to_owned(), body));
            Ok(())
        }

        fn keys(&self, prefix: &str) -> Vec<String> {
            self.puts
                .lock()
                .unwrap()
                .iter()
                .map(|(key, _)| key.clone())
                .filter(|key| key.starts_with(prefix))
                .collect()
        }

        fn body(&self, key: &str) -> Vec<u8> {
            self.puts
                .lock()
                .unwrap()
                .iter()
                .find(|(k, _)| k == key)
                .unwrap()
                .1
                .clone()
        }

        fn watermark_files(&self) -> Vec<(String, Value)> {
            self.puts
                .lock()
                .unwrap()
                .iter()
                .filter(|(key, _)| key.contains("/_watermarks/"))
                .map(|(key, body)| (key.clone(), serde_json::from_slice(body).unwrap()))
                .collect()
        }
    }

    #[async_trait]
    impl IndexStore for FakeStore {
        async fn put_new(&self, key: &str, body: Vec<u8>) -> Result<(), StoreError> {
            self.record(key, body)
        }

        async fn put_json(&self, key: &str, body: Vec<u8>) -> Result<(), StoreError> {
            self.record(key, body)
        }
    }

    type StoredOffsets = Vec<(Tp, i64)>;

    #[derive(Clone, Default)]
    struct FakeOffsets {
        stored: Arc<Mutex<Vec<StoredOffsets>>>,
        steps: Arc<Mutex<Vec<String>>>,
    }

    impl OffsetStore for FakeOffsets {
        fn store(&self, offsets: &[(Tp, i64)]) -> Result<(), String> {
            let mut offsets = offsets.to_vec();
            offsets.sort();
            self.stored.lock().unwrap().push(offsets);
            self.steps.lock().unwrap().push("store offsets".to_owned());
            Ok(())
        }
    }

    struct Fixture {
        store: Arc<FakeStore>,
        offsets: FakeOffsets,
        batcher: Batcher<FakeOffsets>,
    }

    fn fixture(max_rows: usize) -> Fixture {
        set_clock(WALL_CLOCK_MS);
        let steps = Arc::new(Mutex::new(Vec::new()));
        let store = Arc::new(FakeStore {
            steps: steps.clone(),
            ..FakeStore::default()
        });
        let offsets = FakeOffsets {
            steps,
            ..FakeOffsets::default()
        };
        let batcher = Batcher::new(
            store.clone(),
            offsets.clone(),
            Arc::new(Mutex::new(CaptureWatermark::default())),
            Options {
                flush_interval: Duration::from_millis(600_000),
                max_rows,
                max_bytes: 1024 * 1024,
                row_group_rows: 1_000,
                owned_for: Duration::from_secs(3_600),
            },
            0,
        )
        .with_clock(clock);
        Fixture {
            store,
            offsets,
            batcher,
        }
    }

    struct Raw {
        partition: i32,
        offset: i64,
        index: &'static str,
        write_day: &'static str,
        captured_at_ms: Option<i64>,
        value: Vec<u8>,
    }

    fn raw(offset: i64, index: &'static str, write_day: &'static str, row: &Value) -> Raw {
        Raw {
            partition: 0,
            offset,
            index,
            write_day,
            captured_at_ms: None,
            value: serde_json::to_vec(row).unwrap(),
        }
    }

    impl Raw {
        fn on(mut self, partition: i32) -> Self {
            self.partition = partition;
            self
        }

        fn captured(mut self, captured_at_ms: i64) -> Self {
            self.captured_at_ms = Some(captured_at_ms);
            self
        }
    }

    fn add(batcher: &mut Batcher<FakeOffsets>, raws: &[Raw]) {
        let captured: Vec<String> = raws
            .iter()
            .map(|raw| {
                raw.captured_at_ms
                    .map(|ms| ms.to_string())
                    .unwrap_or_default()
            })
            .collect();
        let messages: Vec<Message<'_>> = raws
            .iter()
            .zip(&captured)
            .map(|(raw, captured)| {
                let mut pairs = vec![
                    (INDEX_HEADER, Some(raw.index.as_bytes())),
                    (WRITE_DAY_HEADER, Some(raw.write_day.as_bytes())),
                ];
                if raw.captured_at_ms.is_some() {
                    pairs.push((CAPTURE_TIMESTAMP_HEADER, Some(captured.as_bytes())));
                }
                Message {
                    tp: tp(raw.partition),
                    offset: raw.offset,
                    headers: Headers::from_pairs(pairs),
                    value: Some(&raw.value),
                }
            })
            .collect();
        batcher.add(&messages);
    }

    async fn poll(
        batcher: &mut Batcher<FakeOffsets>,
        raws: &[Raw],
        now_ms: i64,
    ) -> Result<(), StoreError> {
        add(batcher, raws);
        if batcher.should_flush(now_ms) {
            batcher.flush(now_ms).await
        } else {
            batcher.write_watermark_files_if_due(now_ms).await;
            Ok(())
        }
    }

    fn strings(fields: Vec<Field>) -> Vec<String> {
        fields
            .into_iter()
            .map(|field| match field {
                Field::Str(value) => value,
                other => panic!("{other:?}"),
            })
            .collect()
    }

    #[tokio::test]
    async fn writes_one_file_per_index_and_write_day_then_stores_the_next_offset_of_each_partition()
    {
        let Fixture {
            store,
            offsets,
            mut batcher,
        } = fixture(4);
        poll(
            &mut batcher,
            &[
                raw(10, "blocks", "2026-10-15", &block_row("s1")),
                raw(
                    11,
                    "images",
                    "2026-10-15",
                    &image_row("image:v4:7:2026-10:a"),
                ),
                raw(5, "blocks", "2026-10-16", &block_row("s3")).on(1),
            ],
            1,
        )
        .await
        .unwrap();
        assert!(store.keys("").is_empty());

        poll(
            &mut batcher,
            &[raw(12, "blocks", "2026-10-15", &block_row("s2"))],
            2,
        )
        .await
        .unwrap();

        let blocks = store.keys("index/blocks/");
        assert_eq!(blocks.len(), 2);
        let day15 = blocks
            .iter()
            .find(|key| key.contains("dt=2026-10-15"))
            .unwrap();
        let day16 = blocks
            .iter()
            .find(|key| key.contains("dt=2026-10-16"))
            .unwrap();
        let name = day15.rsplit('/').next().unwrap();
        let (millis, random) = name.trim_end_matches(".parquet").split_once('-').unwrap();
        assert_eq!(millis, WALL_CLOCK_MS.to_string());
        assert!(random.len() == 16 && random.chars().all(|c| c.is_ascii_hexdigit()));
        assert_eq!(
            strings(read_column(&store.body(day15), "session_id")),
            ["s1", "s2"]
        );
        assert_eq!(
            strings(read_column(&store.body(day16), "session_id")),
            ["s3"]
        );
        let images = store.keys("index/images/dt=2026-10-15/");
        assert_eq!(
            strings(read_column(&store.body(&images[0]), "image_ref")),
            ["image:v4:7:2026-10:a"]
        );
        assert_eq!(
            *offsets.stored.lock().unwrap(),
            [vec![(tp(0), 13), (tp(1), 6)]]
        );
    }

    #[tokio::test]
    async fn rejects_a_bad_row_and_still_moves_past_it() {
        let mut row = block_row("s1");
        row["clicks"] = json!(2_i64.pow(31));
        let cases = [
            ("blocks", "2026-10-15", b"{not json".to_vec()),
            ("blocks", "2026-10-15", serde_json::to_vec(&row).unwrap()),
            (
                "images",
                "2026-10-15",
                serde_json::to_vec(&block_row("s1")).unwrap(),
            ),
            (
                "sessions",
                "2026-10-15",
                serde_json::to_vec(&block_row("s1")).unwrap(),
            ),
            (
                "blocks",
                "2026-02-30",
                serde_json::to_vec(&block_row("s1")).unwrap(),
            ),
        ];
        for (index, write_day, value) in cases {
            let Fixture {
                store,
                offsets,
                mut batcher,
            } = fixture(1_000);
            let bad = Raw {
                partition: 0,
                offset: 1,
                index,
                write_day,
                captured_at_ms: None,
                value,
            };
            poll(&mut batcher, &[bad], 600_000).await.unwrap();
            assert!(store.keys("").is_empty(), "{index} {write_day}");
            assert_eq!(*offsets.stored.lock().unwrap(), [vec![(tp(0), 2)]]);
        }
    }

    #[tokio::test]
    async fn stores_no_offsets_when_a_write_fails_and_writes_only_the_unwritten_files_on_the_next_flush(
    ) {
        let Fixture {
            store,
            offsets,
            mut batcher,
        } = fixture(1_000);
        add(
            &mut batcher,
            &[
                raw(1, "blocks", "2026-10-15", &block_row("s1")),
                raw(
                    2,
                    "images",
                    "2026-10-15",
                    &image_row("image:v4:7:2026-10:a"),
                ),
            ],
        );
        store.fail("index/images/", 1);

        assert!(batcher.flush(2).await.is_err());
        assert!(offsets.stored.lock().unwrap().is_empty());
        assert_eq!(store.keys("index/blocks/").len(), 1);
        assert_eq!(batcher.row_count(), 1);

        batcher.flush(3).await.unwrap();
        assert_eq!(store.keys("index/blocks/").len(), 1);
        assert_eq!(store.keys("index/images/").len(), 1);
        assert_eq!(*offsets.stored.lock().unwrap(), [vec![(tp(0), 3)]]);
    }

    #[tokio::test]
    async fn leaves_out_the_rows_and_offsets_of_a_revoked_partition() {
        let Fixture {
            store,
            offsets,
            mut batcher,
        } = fixture(1_000);
        add(
            &mut batcher,
            &[
                raw(1, "blocks", "2026-10-15", &block_row("kept")),
                raw(7, "blocks", "2026-10-15", &block_row("gone")).on(1),
            ],
        );

        batcher.release(&[tp(1)]);
        batcher.flush(2).await.unwrap();

        let keys = store.keys("index/blocks/");
        assert_eq!(
            strings(read_column(&store.body(&keys[0]), "session_id")),
            ["kept"]
        );
        assert_eq!(*offsets.stored.lock().unwrap(), [vec![(tp(0), 2)]]);

        // A message after the revoke proves the partition came back, so its offsets are stored again.
        add(
            &mut batcher,
            &[raw(9, "blocks", "2026-10-15", &block_row("back")).on(1)],
        );
        batcher.flush(3).await.unwrap();
        assert_eq!(offsets.stored.lock().unwrap()[1], [(tp(1), 10)]);
    }

    #[tokio::test]
    async fn writes_the_watermark_files_after_the_index_files_and_the_offsets() {
        let Fixture {
            store, mut batcher, ..
        } = fixture(1_000);
        add(
            &mut batcher,
            &[
                raw(10, "blocks", "2026-10-15", &block_row("s1")).captured(5_000),
                raw(
                    11,
                    "images",
                    "2026-10-15",
                    &image_row("image:v4:7:2026-10:a"),
                )
                .captured(4_000),
            ],
        );
        batcher.flush(2).await.unwrap();
        // This row is buffered and not written, so it holds the blocks watermark down.
        add(
            &mut batcher,
            &[raw(12, "blocks", "2026-10-15", &block_row("s2")).captured(3_000)],
        );
        set_clock(WALL_CLOCK_MS + 1);
        batcher.last_watermark_write_ms = None;
        batcher.write_watermark_files_if_due(3).await;

        let steps: Vec<String> = store
            .steps
            .lock()
            .unwrap()
            .iter()
            .map(|step| match step.rsplit_once('/') {
                Some((dir, _)) if step.ends_with(".parquet") => format!("{dir}/{{file}}"),
                _ => step.clone(),
            })
            .collect();
        assert_eq!(
            steps,
            [
                "index/blocks/dt=2026-10-15/{file}",
                "index/images/dt=2026-10-15/{file}",
                "store offsets",
                "index/blocks/_watermarks/partition=0000.json",
                "index/images/_watermarks/partition=0000.json",
                "index/blocks/_watermarks/partition=0000.json",
                "index/images/_watermarks/partition=0000.json",
            ]
        );
        let files = store.watermark_files();
        assert_eq!(
            files[0],
            (
                "index/blocks/_watermarks/partition=0000.json".to_owned(),
                json!({"partition": 0, "complete_up_to_capture_ms": 5_000, "committed_offset": 12, "written_at_ms": WALL_CLOCK_MS})
            )
        );
        assert_eq!(
            files[2].1,
            json!({"partition": 0, "complete_up_to_capture_ms": 3_000, "committed_offset": 12, "written_at_ms": WALL_CLOCK_MS + 1})
        );
        assert_eq!(files[3].1["complete_up_to_capture_ms"], json!(4_000));
        assert!(String::from_utf8(store.body("index/images/_watermarks/partition=0000.json"))
            .unwrap()
            .starts_with("{\"partition\":0,\"complete_up_to_capture_ms\":4000,\"committed_offset\":12,\"written_at_ms\":"));
    }

    #[tokio::test]
    async fn rewrites_the_watermark_files_once_per_interval_also_on_idle_polls_and_only_for_partitions_it_owns(
    ) {
        let interval = WATERMARK_FILE_INTERVAL.as_millis() as i64;
        let Fixture {
            store, mut batcher, ..
        } = fixture(1_000);
        add(
            &mut batcher,
            &[
                raw(1, "blocks", "2026-10-15", &block_row("s1")).captured(1_000),
                raw(1, "blocks", "2026-10-15", &block_row("s2"))
                    .on(1)
                    .captured(2_000),
            ],
        );
        batcher.flush(0).await.unwrap();
        batcher.release(&[tp(1)]);
        add(
            &mut batcher,
            &[raw(2, "blocks", "2026-10-15", &block_row("s1")).captured(3_000)],
        );
        batcher.flush(interval - 1).await.unwrap();
        assert_eq!(store.watermark_files().len(), 2);

        set_clock(WALL_CLOCK_MS + interval);
        poll(&mut batcher, &[], interval).await.unwrap();

        let files = store.watermark_files();
        let keys: Vec<&str> = files.iter().map(|(key, _)| key.as_str()).collect();
        let mut first_round = keys[..2].to_vec();
        first_round.sort();
        assert_eq!(
            first_round,
            [
                "index/blocks/_watermarks/partition=0000.json",
                "index/blocks/_watermarks/partition=0001.json"
            ]
        );
        assert_eq!(keys[2..], ["index/blocks/_watermarks/partition=0000.json"]);
        // The rows the first flush finished hold the value for the 10-minute finished window.
        assert_eq!(
            files[2].1,
            json!({"partition": 0, "complete_up_to_capture_ms": 1_000, "committed_offset": 3, "written_at_ms": WALL_CLOCK_MS + interval})
        );
    }

    #[tokio::test]
    async fn keeps_a_flush_successful_when_a_watermark_write_fails_and_writes_the_file_after_the_interval(
    ) {
        let interval = WATERMARK_FILE_INTERVAL.as_millis() as i64;
        let Fixture {
            store,
            offsets,
            mut batcher,
        } = fixture(1_000);
        add(
            &mut batcher,
            &[raw(1, "blocks", "2026-10-15", &block_row("s1")).captured(1_000)],
        );
        store.fail("/_watermarks/", 1);

        batcher.flush(2).await.unwrap();
        assert_eq!(*offsets.stored.lock().unwrap(), [vec![(tp(0), 2)]]);
        assert!(store.watermark_files().is_empty());

        set_clock(WALL_CLOCK_MS + interval);
        poll(&mut batcher, &[], 2 + interval - 1).await.unwrap();
        assert!(store.watermark_files().is_empty());
        poll(&mut batcher, &[], 2 + interval).await.unwrap();
        assert_eq!(
            store.watermark_files(),
            [(
                "index/blocks/_watermarks/partition=0000.json".to_owned(),
                json!({"partition": 0, "complete_up_to_capture_ms": 1_000, "committed_offset": 2, "written_at_ms": WALL_CLOCK_MS + interval})
            )]
        );
    }

    #[tokio::test]
    async fn leaves_the_watermark_files_to_the_next_poll_after_a_flush_that_outlasts_the_poll_interval(
    ) {
        let Fixture {
            store,
            offsets,
            mut batcher,
        } = fixture(1_000);
        batcher.options.owned_for = Duration::ZERO;
        add(
            &mut batcher,
            &[raw(1, "blocks", "2026-10-15", &block_row("s1")).captured(1_000)],
        );

        batcher.flush(2).await.unwrap();
        assert_eq!(*offsets.stored.lock().unwrap(), [vec![(tp(0), 2)]]);
        assert!(store.watermark_files().is_empty());

        poll(&mut batcher, &[], 3).await.unwrap();
        assert_eq!(store.watermark_files().len(), 1);
    }

    #[tokio::test]
    async fn flushes_on_the_row_and_byte_limits_and_on_the_interval_with_only_offsets_pending() {
        let Fixture { mut batcher, .. } = fixture(2);
        add(
            &mut batcher,
            &[raw(1, "blocks", "2026-10-15", &block_row("s1"))],
        );
        assert!(!batcher.should_flush(1));
        add(
            &mut batcher,
            &[raw(2, "blocks", "2026-10-15", &block_row("s2"))],
        );
        assert!(batcher.should_flush(1));

        let Fixture { mut batcher, .. } = fixture(1_000);
        batcher.options.max_bytes = 10;
        add(
            &mut batcher,
            &[raw(1, "images", "2026-10-15", &image_row("a"))],
        );
        assert!(batcher.should_flush(1));

        let Fixture { mut batcher, .. } = fixture(1_000);
        assert!(!batcher.should_flush(600_000));
        add(
            &mut batcher,
            &[raw(1, "sessions", "2026-10-15", &block_row("s1"))],
        );
        assert!(!batcher.should_flush(599_999));
        assert!(batcher.should_flush(600_000));
    }
}
