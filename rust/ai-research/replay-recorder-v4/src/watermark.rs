//! The recorder's watermark files. The format is in `products/ai_training/docs/replay-data.md`, section "Recorder watermark files".

use std::collections::{BTreeMap, HashMap};
use std::ops::Range;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use chrono::{DateTime, Utc};
use metrics::counter;
use replay_core_v4::keys::rows::write_day;
use serde::Serialize;

use crate::batch::Tp;
use crate::store::BlobStore;

pub const WATERMARK_FILE_INTERVAL: Duration = Duration::from_secs(180);

/// A later offset can hold a record captured earlier, by up to its producer's delivery timeout. This is well over the delivery timeouts of capture and of the replay lane that moves records to the overflow topic.
pub const CAPTURE_ORDER_SLACK_MS: i64 = 5 * 60 * 1000;

const PUT_TIMEOUT: Duration = Duration::from_secs(10);

/// The previous owner's last index rows are delivered or failed within the index delivery timeout of the assignment. The extra minute covers clock differences between processes, which pick write days by their own clocks.
pub fn assignment_grace(index_delivery_timeout: Duration) -> Duration {
    index_delivery_timeout + Duration::from_secs(60)
}

#[derive(Default)]
pub struct Progress {
    partitions: HashMap<Tp, Partition>,
    flushes: Vec<PendingFlush>,
}

struct Partition {
    epoch: u64,
    next_offset: i64,
    last_captured_at_ms: Option<i64>,
    buffered_earliest_ms: Option<i64>,
}

impl Partition {
    fn new(epoch: u64, first_offset: i64) -> Self {
        Self {
            epoch,
            next_offset: first_offset,
            last_captured_at_ms: None,
            buffered_earliest_ms: None,
        }
    }
}

struct PendingFlush {
    earliest_ms: HashMap<Tp, (u64, i64)>,
    done: FlushDone,
}

/// Set once a flush has stored its blocks and each of its index rows was delivered or failed.
#[derive(Clone, Default)]
pub struct FlushDone(Arc<AtomicBool>);

impl FlushDone {
    pub fn finish(&self) {
        self.0.store(true, Ordering::Release);
    }

    pub fn is_finished(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PartitionProgress {
    pub next_offset: i64,
    pub last_captured_at_ms: Option<i64>,
    pub earliest_unfinished_ms: Option<i64>,
}

impl Progress {
    pub fn handled(
        &mut self,
        tp: Tp,
        epoch: u64,
        offset: i64,
        captured_at_ms: Option<i64>,
        admitted: bool,
    ) {
        let partition = self
            .partitions
            .entry(tp)
            .or_insert_with(|| Partition::new(epoch, offset));
        if partition.epoch != epoch {
            *partition = Partition::new(epoch, offset);
        }
        partition.next_offset = partition.next_offset.max(offset + 1);
        let Some(captured_at_ms) = captured_at_ms.filter(|ms| *ms > 0) else {
            return;
        };
        partition.last_captured_at_ms = Some(captured_at_ms);
        if admitted {
            partition.buffered_earliest_ms = Some(
                partition
                    .buffered_earliest_ms
                    .map_or(captured_at_ms, |earliest| earliest.min(captured_at_ms)),
            );
        }
    }

    pub fn flush_started(&mut self) -> FlushDone {
        self.flushes.retain(|flush| !flush.done.is_finished());
        let done = FlushDone::default();
        let earliest_ms: HashMap<Tp, (u64, i64)> = self
            .partitions
            .iter_mut()
            .filter_map(|(tp, p)| Some((*tp, (p.epoch, p.buffered_earliest_ms.take()?))))
            .collect();
        if !earliest_ms.is_empty() {
            self.flushes.push(PendingFlush {
                earliest_ms,
                done: done.clone(),
            });
        }
        done
    }

    /// A flush that lost its partitions never finishes, so this is also what removes it.
    pub fn retain(&mut self, keep: impl Fn(Tp, u64) -> bool) {
        self.partitions.retain(|tp, p| keep(*tp, p.epoch));
        for flush in &mut self.flushes {
            flush.earliest_ms.retain(|tp, (epoch, _)| keep(*tp, *epoch));
        }
        self.flushes
            .retain(|flush| !flush.earliest_ms.is_empty() && !flush.done.is_finished());
    }

    pub fn of(&self, tp: Tp, epoch: u64) -> Option<PartitionProgress> {
        let partition = self.partitions.get(&tp).filter(|p| p.epoch == epoch)?;
        let unfinished = self
            .flushes
            .iter()
            .filter(|flush| !flush.done.is_finished())
            .filter_map(|flush| match flush.earliest_ms.get(&tp) {
                Some(&(flush_epoch, earliest)) if flush_epoch == epoch => Some(earliest),
                _ => None,
            });
        Some(PartitionProgress {
            next_offset: partition.next_offset,
            last_captured_at_ms: partition.last_captured_at_ms,
            earliest_unfinished_ms: unfinished.chain(partition.buffered_earliest_ms).min(),
        })
    }
}

/// `offsets` runs from the partition's low watermark to its high watermark, read at `offsets_read_at_ms`.
pub fn complete_up_to_capture_ms(
    progress: Option<PartitionProgress>,
    committed_offset: Option<i64>,
    offsets: &Range<i64>,
    offsets_read_at_ms: i64,
) -> Option<i64> {
    // A partition that holds no record has nothing to read, wherever the consumer starts.
    let next_offset = progress
        .map(|p| p.next_offset)
        .or(committed_offset)
        .or(offsets.is_empty().then_some(offsets.end))?;
    // Every record appended before the read is handled, and one appended after it was captured at most the slack before the read.
    let read_to_end_at_ms = (next_offset >= offsets.end).then_some(offsets_read_at_ms);
    let newest_ms = progress
        .and_then(|p| p.last_captured_at_ms)
        .max(read_to_end_at_ms)?;
    let frontier_ms = newest_ms - CAPTURE_ORDER_SLACK_MS;
    Some(
        progress
            .and_then(|p| p.earliest_unfinished_ms)
            .map_or(frontier_ms, |earliest| earliest.min(frontier_ms)),
    )
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KafkaEnds {
    pub reads_started_at_ms: i64,
    pub input_offsets: HashMap<Tp, Range<i64>>,
    pub input_partitions: BTreeMap<&'static str, usize>,
    pub index_end_offsets: Vec<i64>,
}

#[derive(Serialize)]
struct WatermarkFile<'a> {
    topic: &'a str,
    partition: i32,
    complete_up_to_capture_ms: i64,
    index_end_offsets: &'a [i64],
    input_partitions: &'a BTreeMap<&'static str, usize>,
    written_at_ms: i64,
}

pub fn watermark_key(write_day: &str, tp: Tp) -> String {
    format!(
        "index/_recorder_watermarks/dt={write_day}/topic={}/partition={:04}.json",
        tp.topic, tp.partition
    )
}

/// `written_at` must be read after the Kafka reads, so that the file's day is no earlier than the write day of any flush that the progress counts.
pub fn watermark_files(
    owned: &[(Tp, Option<PartitionProgress>)],
    committed_offsets: &HashMap<Tp, i64>,
    ends: &KafkaEnds,
    written_at: DateTime<Utc>,
) -> Result<Vec<(String, Vec<u8>)>, serde_json::Error> {
    let day = write_day(written_at);
    let mut files = Vec::with_capacity(owned.len());
    for &(tp, progress) in owned {
        let Some(offsets) = ends.input_offsets.get(&tp) else {
            continue;
        };
        let Some(complete_up_to_capture_ms) = complete_up_to_capture_ms(
            progress,
            committed_offsets.get(&tp).copied(),
            offsets,
            ends.reads_started_at_ms,
        ) else {
            continue;
        };
        let body = serde_json::to_vec(&WatermarkFile {
            topic: tp.topic,
            partition: tp.partition,
            complete_up_to_capture_ms,
            index_end_offsets: &ends.index_end_offsets,
            input_partitions: &ends.input_partitions,
            written_at_ms: written_at.timestamp_millis(),
        })?;
        files.push((watermark_key(&day, tp), body));
    }
    Ok(files)
}

pub struct WatermarkFiles {
    pub progress: Mutex<Progress>,
    pub store: Arc<dyn BlobStore>,
    pub bucket: String,
    pub index_topic: String,
    pub grace: Duration,
}

impl WatermarkFiles {
    pub async fn put(&self, files: Vec<(String, Vec<u8>)>) {
        let writes = files.into_iter().map(|(key, body)| async move {
            match tokio::time::timeout(PUT_TIMEOUT, self.store.put(&self.bucket, &key, body)).await
            {
                Ok(Ok(())) => Ok(()),
                Ok(Err(error)) => Err(error.to_string()),
                Err(_) => Err(format!("timed out after {PUT_TIMEOUT:?}")),
            }
        });
        let mut failed = 0;
        for written in futures::future::join_all(writes).await {
            let outcome = match written {
                Ok(()) => "written",
                Err(error) => {
                    if failed == 0 {
                        tracing::warn!(%error, "writing a watermark file failed");
                    }
                    failed += 1;
                    "failed"
                }
            };
            counter!("ai_research_v4_recorder_watermark_files_total", "outcome" => outcome)
                .increment(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const MAIN: Tp = Tp {
        topic: "main",
        partition: 7,
    };

    fn progress(
        next_offset: i64,
        last_captured_at_ms: Option<i64>,
        earliest_unfinished_ms: Option<i64>,
    ) -> Option<PartitionProgress> {
        Some(PartitionProgress {
            next_offset,
            last_captured_at_ms,
            earliest_unfinished_ms,
        })
    }

    #[test]
    fn the_value_is_the_earliest_unfinished_record_or_the_reading_frontier() {
        const SLACK: i64 = CAPTURE_ORDER_SLACK_MS;
        // (progress, committed offset, low and high watermarks, expected), all read at 10_000_000.
        let cases = [
            (
                progress(10, Some(9_000_000), Some(4_000_000)),
                None,
                0..20,
                Some(4_000_000),
            ),
            (
                progress(10, Some(9_000_000), None),
                None,
                0..20,
                Some(9_000_000 - SLACK),
            ),
            (
                progress(20, Some(9_000_000), None),
                None,
                0..20,
                Some(10_000_000 - SLACK),
            ),
            (
                progress(20, Some(9_000_000), Some(4_000_000)),
                None,
                0..20,
                Some(4_000_000),
            ),
            (None, Some(20), 0..20, Some(10_000_000 - SLACK)),
            (None, Some(10), 0..20, None),
            (None, None, 0..20, None),
            (None, None, 20..20, Some(10_000_000 - SLACK)),
            (progress(10, None, None), None, 0..20, None),
        ];
        for (progress, committed, offsets, expected) in cases {
            assert_eq!(
                complete_up_to_capture_ms(progress, committed, &offsets, 10_000_000),
                expected,
                "{progress:?} {committed:?} {offsets:?}"
            );
        }
    }

    #[test]
    fn an_admitted_record_holds_its_partition_until_its_flush_finishes() {
        let mut state = Progress::default();
        state.handled(MAIN, 1, 10, Some(1_000), false);
        state.handled(MAIN, 1, 11, Some(2_000), true);
        state.handled(MAIN, 1, 12, Some(3_000), true);
        assert_eq!(state.of(MAIN, 1), progress(13, Some(3_000), Some(2_000)));
        assert_eq!(state.of(MAIN, 2), None);

        let first = state.flush_started();
        state.handled(MAIN, 1, 13, Some(4_000), true);
        let second = state.flush_started();
        second.finish();
        assert_eq!(state.of(MAIN, 1), progress(14, Some(4_000), Some(2_000)));
        first.finish();
        assert_eq!(state.of(MAIN, 1), progress(14, Some(4_000), None));

        // A round can read the progress before the consume loop drops the earlier assignment.
        state.handled(MAIN, 1, 14, Some(5_000), true);
        let _lost = state.flush_started();
        state.handled(MAIN, 2, 14, Some(6_000), false);
        assert_eq!(state.of(MAIN, 2), progress(15, Some(6_000), None));
    }

    #[test]
    fn a_file_names_its_day_and_partition_and_carries_the_index_end_offsets() {
        let overflow = Tp {
            topic: "overflow",
            partition: 3,
        };
        let ends = KafkaEnds {
            reads_started_at_ms: 10_000_000,
            input_offsets: HashMap::from([(MAIN, 0..20), (overflow, 0..9)]),
            input_partitions: BTreeMap::from([("main", 64), ("overflow", 8)]),
            index_end_offsets: vec![100, 200],
        };
        let written_at = DateTime::from_timestamp_millis(1_793_059_200_123).unwrap();
        let files = watermark_files(
            &[
                (MAIN, progress(10, Some(9_000_000), None)),
                (overflow, None),
            ],
            &HashMap::from([(overflow, 5)]),
            &ends,
            written_at,
        )
        .unwrap();
        let files: Vec<(String, serde_json::Value)> = files
            .into_iter()
            .map(|(key, body)| (key, serde_json::from_slice(&body).unwrap()))
            .collect();
        assert_eq!(
            files,
            [(
                "index/_recorder_watermarks/dt=2026-10-27/topic=main/partition=0007.json"
                    .to_owned(),
                serde_json::json!({
                    "topic": "main",
                    "partition": 7,
                    "complete_up_to_capture_ms": 9_000_000 - CAPTURE_ORDER_SLACK_MS,
                    "index_end_offsets": [100, 200],
                    "input_partitions": {"main": 64, "overflow": 8},
                    "written_at_ms": 1_793_059_200_123i64,
                })
            )]
        );
    }
}
