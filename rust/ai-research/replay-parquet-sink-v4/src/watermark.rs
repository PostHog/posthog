//! The capture watermark: per partition and captured data, the earliest capture time among the records this lane holds
//! or finished in the last 10 minutes. It feeds the `ml_replay_capture_watermark_timestamp_seconds` gauge, which the
//! other ML replay lanes report too, and the index watermark files.

use std::collections::HashMap;
use std::fmt::Write as _;

use crate::batcher::Tp;
use crate::columns::Index;

/// A finished record does not prove that the next records on the partition are newer, so it holds the watermark for
/// this long.
const FINISHED_WINDOW_MS: i64 = 10 * 60 * 1000;
/// Finished batches merge into one bucket per this span, so a busy partition keeps a bounded number of buckets.
const FINISHED_BUCKET_MS: i64 = 60 * 1000;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum CapturedData {
    EventMetadata,
    InlineImages,
}

impl CapturedData {
    pub fn of(index: Index) -> Self {
        match index {
            Index::Blocks => Self::EventMetadata,
            Index::Images => Self::InlineImages,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::EventMetadata => "event_metadata",
            Self::InlineImages => "inline_images",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CapturedRecord {
    pub tp: Tp,
    pub offset: i64,
    pub data: CapturedData,
    pub captured_at_ms: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WatermarkRow {
    pub tp: Tp,
    pub data: CapturedData,
    pub captured_at_ms: i64,
}

#[derive(Debug)]
struct HeldBatch {
    last_offset: i64,
    earliest_captured_at_ms: i64,
}

#[derive(Debug)]
struct FinishedBucket {
    started_at_ms: i64,
    last_finished_at_ms: i64,
    earliest_captured_at_ms: i64,
}

#[derive(Debug, Default)]
struct DataWatermark {
    held: Vec<HeldBatch>,
    finished: Vec<FinishedBucket>,
    last_expired_captured_at_ms: Option<i64>,
}

impl DataWatermark {
    fn expire_finished(&mut self, now_ms: i64) {
        let expired = self
            .finished
            .iter()
            .take_while(|bucket| now_ms - bucket.last_finished_at_ms > FINISHED_WINDOW_MS)
            .count();
        if let Some(last) = self.finished.drain(..expired).next_back() {
            self.last_expired_captured_at_ms = Some(last.earliest_captured_at_ms);
        }
    }

    fn finish(&mut self, earliest_captured_at_ms: i64, now_ms: i64) {
        self.expire_finished(now_ms);
        match self.finished.last_mut() {
            Some(last) if now_ms - last.started_at_ms < FINISHED_BUCKET_MS => {
                last.last_finished_at_ms = now_ms;
                last.earliest_captured_at_ms =
                    last.earliest_captured_at_ms.min(earliest_captured_at_ms);
            }
            _ => self.finished.push(FinishedBucket {
                started_at_ms: now_ms,
                last_finished_at_ms: now_ms,
                earliest_captured_at_ms,
            }),
        }
    }
}

#[derive(Debug, Default)]
pub struct CaptureWatermark {
    partitions: HashMap<Tp, Vec<(CapturedData, DataWatermark)>>,
}

impl CaptureWatermark {
    fn data_watermark(&mut self, tp: Tp, data: CapturedData) -> &mut DataWatermark {
        let watermarks = self.partitions.entry(tp).or_default();
        let position = match watermarks.iter().position(|(d, _)| *d == data) {
            Some(position) => position,
            None => {
                watermarks.push((data, DataWatermark::default()));
                watermarks.len() - 1
            }
        };
        &mut watermarks[position].1
    }

    /// Holds the capture time of each record until a stored offset passes it. One call is one batch.
    pub fn hold(&mut self, records: &[CapturedRecord]) {
        let mut batches: Vec<(Tp, CapturedData, HeldBatch)> = Vec::new();
        for record in records {
            match batches
                .iter_mut()
                .find(|(tp, data, _)| *tp == record.tp && *data == record.data)
            {
                Some((_, _, batch)) => {
                    batch.last_offset = batch.last_offset.max(record.offset);
                    batch.earliest_captured_at_ms =
                        batch.earliest_captured_at_ms.min(record.captured_at_ms);
                }
                None => batches.push((
                    record.tp,
                    record.data,
                    HeldBatch {
                        last_offset: record.offset,
                        earliest_captured_at_ms: record.captured_at_ms,
                    },
                )),
            }
        }
        for (tp, data, batch) in batches {
            self.data_watermark(tp, data).held.push(batch);
        }
    }

    /// `offsets` are what Kafka stores: the next offset to read on each partition.
    pub fn release(&mut self, offsets: &[(Tp, i64)], now_ms: i64) {
        for (tp, offset) in offsets {
            let Some(watermarks) = self.partitions.get_mut(tp) else {
                continue;
            };
            for (_, watermark) in watermarks.iter_mut() {
                let held = std::mem::take(&mut watermark.held);
                for batch in held {
                    if batch.last_offset < *offset {
                        watermark.finish(batch.earliest_captured_at_ms, now_ms);
                    } else {
                        watermark.held.push(batch);
                    }
                }
            }
        }
    }

    /// Called on revoke, so that only the next owner of the partition reports it.
    pub fn forget(&mut self, partitions: &[Tp]) {
        for tp in partitions {
            self.partitions.remove(tp);
        }
    }

    pub fn snapshot(&mut self, now_ms: i64) -> Vec<WatermarkRow> {
        let mut rows = Vec::new();
        for (tp, watermarks) in &mut self.partitions {
            for (data, watermark) in watermarks.iter_mut() {
                watermark.expire_finished(now_ms);
                let earliest = watermark
                    .held
                    .iter()
                    .map(|batch| batch.earliest_captured_at_ms)
                    .chain(
                        watermark
                            .finished
                            .iter()
                            .map(|bucket| bucket.earliest_captured_at_ms),
                    )
                    .min();
                // A partition that stops delivering records keeps its last value instead of disappearing, so the
                // minimum across partitions still includes a stalled consumer.
                if let Some(captured_at_ms) = earliest.or(watermark.last_expired_captured_at_ms) {
                    rows.push(WatermarkRow {
                        tp: *tp,
                        data: *data,
                        captured_at_ms,
                    });
                }
            }
        }
        rows
    }

    /// The gauge in the Prometheus text format, computed when it is scraped, so a partition this process gave up is no
    /// longer listed.
    pub fn render_gauge(&mut self, now_ms: i64) -> String {
        let mut earliest: HashMap<(i32, CapturedData), i64> = HashMap::new();
        for row in self.snapshot(now_ms) {
            earliest
                .entry((row.tp.partition, row.data))
                .and_modify(|ms| *ms = (*ms).min(row.captured_at_ms))
                .or_insert(row.captured_at_ms);
        }
        let mut rows: Vec<_> = earliest.into_iter().collect();
        rows.sort();
        let mut out = String::new();
        out.push_str("# HELP ml_replay_capture_watermark_timestamp_seconds Unix time of the earliest capture among the records that this lane holds on the partition or finished in the last 10 minutes. The lane finished every record that it read with an earlier capture time. A record that the lane has not read yet can be older. The minimum over the lanes on a data path is how far back that data is complete\n");
        out.push_str("# TYPE ml_replay_capture_watermark_timestamp_seconds gauge\n");
        for ((partition, data), captured_at_ms) in rows {
            let _ = writeln!(
                out,
                "ml_replay_capture_watermark_timestamp_seconds{{partition=\"{partition}\",data=\"{}\"}} {}",
                data.as_str(),
                captured_at_ms as f64 / 1000.0
            );
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TP: Tp = Tp {
        topic: "index",
        partition: 3,
    };

    fn record(offset: i64, data: CapturedData, captured_at_ms: i64) -> CapturedRecord {
        CapturedRecord {
            tp: TP,
            offset,
            data,
            captured_at_ms,
        }
    }

    fn value(watermark: &mut CaptureWatermark, data: CapturedData, now_ms: i64) -> Option<i64> {
        watermark
            .snapshot(now_ms)
            .into_iter()
            .find(|row| row.data == data)
            .map(|row| row.captured_at_ms)
    }

    #[test]
    fn holds_records_until_their_offsets_are_stored_then_for_the_finished_window() {
        use CapturedData::{EventMetadata, InlineImages};
        let mut watermark = CaptureWatermark::default();
        watermark.hold(&[
            record(10, EventMetadata, 5_000),
            record(11, EventMetadata, 4_000),
        ]);
        watermark.hold(&[
            record(12, EventMetadata, 9_000),
            record(12, InlineImages, 8_000),
        ]);
        assert_eq!(value(&mut watermark, EventMetadata, 0), Some(4_000));

        // Offset 12 is the next to read, so the first batch finishes and the second stays held.
        watermark.release(&[(TP, 12)], 100_000);
        assert_eq!(value(&mut watermark, EventMetadata, 100_000), Some(4_000));
        watermark.release(&[(TP, 13)], 130_000);
        assert_eq!(value(&mut watermark, InlineImages, 130_000), Some(8_000));

        // Both finished batches share one bucket, which expires 10 minutes after its last finish and is kept as the
        // value of a partition that stopped delivering.
        assert_eq!(
            value(&mut watermark, EventMetadata, 130_000 + FINISHED_WINDOW_MS),
            Some(4_000)
        );
        watermark.hold(&[record(13, EventMetadata, 20_000)]);
        assert_eq!(
            value(&mut watermark, EventMetadata, 130_001 + FINISHED_WINDOW_MS),
            Some(20_000)
        );
        watermark.release(&[(TP, 14)], 140_000 + FINISHED_WINDOW_MS);
        assert_eq!(
            value(
                &mut watermark,
                EventMetadata,
                150_000 + 2 * FINISHED_WINDOW_MS
            ),
            Some(20_000)
        );

        let gauge = watermark.render_gauge(150_000 + 2 * FINISHED_WINDOW_MS);
        assert!(gauge.contains(
            "ml_replay_capture_watermark_timestamp_seconds{partition=\"3\",data=\"event_metadata\"} 20\n"
        ));
        watermark.forget(&[TP]);
        assert!(watermark.snapshot(0).is_empty());
    }
}
