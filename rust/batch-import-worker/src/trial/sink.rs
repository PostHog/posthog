use std::sync::Arc;

use anyhow::{Context, Error};
use object_store::{path::Path, ObjectStore, ObjectStoreExt, PutPayload};
use serde::Serialize;
use tracing::info;

use super::{TrialProgress, TrialRecord};

/// Writes trial output to object storage as size-bounded JSONL pages plus a
/// final `summary.json`, under `{prefix}/`. Page indices are deterministic:
/// a resumed trial that re-fetches a chunk rewrites the same objects, so page
/// writes are idempotent as long as they happen before the progress flush.
pub struct TrialSink {
    store: Arc<dyn ObjectStore>,
    prefix: String,
    records_per_page: usize,
}

/// One JSONL line in a page: the record plus its stable global sequence number.
#[derive(Serialize)]
struct PageRecord<'a> {
    seq: u64,
    #[serde(flatten)]
    record: &'a TrialRecord,
}

/// The completed trial's `summary.json`: pagination metadata plus the
/// accumulated aggregates.
#[derive(Serialize)]
struct FinalSummary<'a> {
    records: u64,
    pages: u32,
    records_per_page: usize,
    #[serde(flatten)]
    summary: &'a super::TrialSummary,
}

impl TrialSink {
    pub fn new(store: Arc<dyn ObjectStore>, prefix: String, records_per_page: usize) -> Self {
        Self {
            store,
            prefix,
            records_per_page: records_per_page.max(1),
        }
    }

    fn page_path(&self, index: u32) -> Path {
        Path::from(format!("{}/pages/{:05}.jsonl", self.prefix, index))
    }

    /// Write one chunk's records as pages starting at index `first_page`, with
    /// global sequence numbers starting at `first_seq`. Returns the number of
    /// pages written. The last page of a chunk may be short — page boundaries
    /// never span chunks, so a chunk's pages depend only on its own records.
    pub async fn write_pages(
        &self,
        first_page: u32,
        first_seq: u64,
        records: &[TrialRecord],
    ) -> Result<u32, Error> {
        let mut pages_written = 0u32;
        for (page_offset, page) in records.chunks(self.records_per_page).enumerate() {
            let mut body = Vec::new();
            for (i, record) in page.iter().enumerate() {
                let line = serde_json::to_vec(&PageRecord {
                    seq: first_seq + (page_offset * self.records_per_page + i) as u64,
                    record,
                })?;
                body.extend_from_slice(&line);
                body.push(b'\n');
            }
            let path = self.page_path(first_page + page_offset as u32);
            self.store
                .put(&path, PutPayload::from(body))
                .await
                .with_context(|| format!("Writing trial page {path}"))?;
            pages_written += 1;
        }
        Ok(pages_written)
    }

    pub async fn write_summary(&self, progress: &TrialProgress) -> Result<(), Error> {
        let path = Path::from(format!("{}/summary.json", self.prefix));
        let body = serde_json::to_vec(&FinalSummary {
            records: progress.records_emitted,
            pages: progress.pages_written,
            records_per_page: self.records_per_page,
            summary: &progress.summary,
        })?;
        self.store
            .put(&path, PutPayload::from(body))
            .await
            .with_context(|| format!("Writing trial summary {path}"))?;
        info!(
            "Wrote trial summary to {path} ({} records, {} pages)",
            progress.records_emitted, progress.pages_written
        );
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use object_store::memory::InMemory;
    use object_store::ObjectStoreExt;
    use serde_json::Value;

    use super::*;

    fn record(n: usize) -> TrialRecord {
        TrialRecord {
            source: serde_json::json!({"n": n}),
            outputs: vec![],
            error: None,
        }
    }

    async fn read_lines(store: &Arc<InMemory>, path: &str) -> Vec<Value> {
        let bytes = store
            .get(&Path::from(path))
            .await
            .unwrap()
            .bytes()
            .await
            .unwrap();
        String::from_utf8(bytes.to_vec())
            .unwrap()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect()
    }

    #[tokio::test]
    async fn pages_are_size_bounded_with_continuous_seq_across_chunks() {
        let store = Arc::new(InMemory::new());
        let sink = TrialSink::new(store.clone(), "trial_runs/team_1/job_x".to_string(), 2);

        // First chunk: 5 records -> pages 0,1 full and page 2 short
        let chunk_one: Vec<_> = (0..5).map(record).collect();
        let pages = sink.write_pages(0, 0, &chunk_one).await.unwrap();
        assert_eq!(pages, 3);

        // Second chunk continues numbering after the first
        let chunk_two: Vec<_> = (5..8).map(record).collect();
        let pages = sink.write_pages(3, 5, &chunk_two).await.unwrap();
        assert_eq!(pages, 2);

        let mut seqs = vec![];
        for (page, expected_len) in [(0, 2), (1, 2), (2, 1), (3, 2), (4, 1)] {
            let lines = read_lines(
                &store,
                &format!("trial_runs/team_1/job_x/pages/{page:05}.jsonl"),
            )
            .await;
            assert_eq!(lines.len(), expected_len, "page {page}");
            for line in &lines {
                seqs.push(line["seq"].as_u64().unwrap());
                assert_eq!(line["source"]["n"].as_u64(), line["seq"].as_u64());
            }
        }
        assert_eq!(seqs, (0..8).collect::<Vec<u64>>());
    }

    #[tokio::test]
    async fn summary_carries_pagination_metadata_and_aggregates() {
        let store = Arc::new(InMemory::new());
        let sink = TrialSink::new(store.clone(), "p".to_string(), 500);

        let mut progress = super::super::TrialProgress::default();
        progress.absorb(&[record(0), record(1)], 1);
        sink.write_summary(&progress).await.unwrap();

        let bytes = store
            .get(&Path::from("p/summary.json"))
            .await
            .unwrap()
            .bytes()
            .await
            .unwrap();
        let summary: Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(summary["records"], 2);
        assert_eq!(summary["pages"], 1);
        assert_eq!(summary["records_per_page"], 500);
        assert_eq!(summary["source_records"], 2);
        assert_eq!(summary["skipped_records"], 2);
    }
}
