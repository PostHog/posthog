//! Write store layer: orchestrates batch execution across parallel chunks,
//! handles per-row fallback with property trimming, and surfaces outcomes
//! as `BatchOutcome` (for batches) or `RowResult` (for single rows).
//!
//! The `PersonDb` trait abstracts the DB layer so orchestration can be
//! unit-tested against a mock. `PgStore` in `pg.rs` is the production impl.
//!
//! The per-row path uses `Result<(), WriteError>` because each row has a
//! single atomic outcome. The per-batch path uses `BatchOutcome` because a
//! batch can partially succeed — some chunks commit while others need
//! transient retry or per-row fallback. Both share the `WriteErrorKind`
//! taxonomy from the DB layer.

use std::sync::Arc;

use async_trait::async_trait;
use futures::stream::{self, StreamExt};
use metrics::{counter, gauge, histogram};
use personhog_proto::personhog::types::v1::Person;
use tokio::task::JoinSet;
use tracing::{error, warn};

// Re-exported so callers importing from `store::` keep working.
pub use crate::error::{FatalError, WriteError, WriteErrorKind};

use crate::properties;

/// The database primitive the store layer orchestrates against. Implemented
/// by `PgStore` for production and by mocks for testing.
#[async_trait]
pub trait PersonDb: Send + Sync {
    /// Execute a single upsert statement covering a chunk of persons.
    async fn execute_chunk(&self, chunk: &[Person]) -> Result<(), WriteError>;

    /// Execute a single-row upsert. If `properties_override` is provided,
    /// that JSON string is used instead of the person's proto bytes.
    async fn execute_row(
        &self,
        person: &Person,
        properties_override: Option<&str>,
    ) -> Result<(), WriteError>;
}

/// Outcome of a batch upsert. Reports which chunks (if any) need retry,
/// grouped by failure class so the caller picks the right strategy:
/// transient chunks are retried as batches after backoff, data-failed
/// chunks fall through to per-row inserts to isolate bad records.
#[derive(Debug)]
pub enum BatchOutcome {
    Success,
    Partial {
        transient: Vec<Person>,
        data_failed: Vec<Person>,
    },
    /// A chunk task panicked. The persons in that chunk are unrecoverable;
    /// the writer must escalate. The Kafka offset has not been committed, so
    /// the underlying records will be redelivered on restart.
    Fatal(FatalError),
}

/// Outcome of writing a single person.
#[derive(Debug)]
pub enum RowResult {
    Written,
    Trimmed(IngestionWarning),
    Skipped(IngestionWarning),
}

/// Information needed to emit an ingestion warning.
#[derive(Debug)]
pub struct IngestionWarning {
    pub team_id: i64,
    pub person_id: i64,
    pub message: String,
}

/// Production person write store. Splits batches into chunks, runs them in
/// parallel against a `PersonDb`, partitions outcomes by failure class, and
/// handles per-row fallback with property trimming.
pub struct PersonWriteStore<D: PersonDb> {
    db: Arc<D>,
    chunk_size: usize,
    row_fallback_concurrency: usize,
}

impl<D: PersonDb + 'static> PersonWriteStore<D> {
    pub fn new(db: D, chunk_size: usize, row_fallback_concurrency: usize) -> Self {
        Self {
            db: Arc::new(db),
            chunk_size: chunk_size.max(1),
            row_fallback_concurrency: row_fallback_concurrency.max(1),
        }
    }

    pub async fn upsert_batch(&self, persons: Vec<Person>) -> BatchOutcome {
        if persons.is_empty() {
            return BatchOutcome::Success;
        }

        let start = std::time::Instant::now();
        let total = persons.len();
        let chunks = split_into_owned_chunks(persons, self.chunk_size);

        // Single-chunk fast path: no spawn, no JoinSet. Normal flushes land
        // here since chunk_size is tuned to match the aggregator flush size.
        let outcome = if chunks.len() == 1 {
            let chunk = chunks.into_iter().next().unwrap();
            match self.db.execute_chunk(&chunk).await {
                Ok(()) => BatchOutcome::Success,
                Err(e) => partial_from_failed_chunk(chunk, e.kind),
            }
        } else {
            self.run_parallel_chunks(chunks).await
        };

        histogram!("personhog_writer_flush_duration_seconds").record(start.elapsed().as_secs_f64());
        histogram!("personhog_writer_flush_rows").record(total as f64);
        outcome
    }

    pub async fn upsert_row(&self, person: &Person) -> RowResult {
        match self.db.execute_row(person, None).await {
            Ok(()) => return RowResult::Written,
            Err(e) if matches!(e.kind, WriteErrorKind::PropertiesSizeViolation) => {
                // Fall through to trim logic
            }
            Err(e) => {
                counter!("personhog_writer_rows_skipped_total").increment(1);
                warn!(
                    team_id = person.team_id,
                    person_id = person.id,
                    error = %e.message,
                    "per-row upsert failed, skipping"
                );
                return RowResult::Skipped(IngestionWarning {
                    team_id: person.team_id,
                    person_id: person.id,
                    message: format!("Person upsert failed: {}", e.message),
                });
            }
        }

        // Size violation: trim and retry
        let props: serde_json::Value = if person.properties.is_empty() {
            serde_json::Value::Object(serde_json::Map::new())
        } else {
            serde_json::from_slice(&person.properties)
                .unwrap_or(serde_json::Value::Object(serde_json::Map::new()))
        };
        let Some(trimmed) =
            properties::trim_properties_to_fit_size(&props, person.team_id, person.id)
        else {
            counter!("personhog_writer_rows_skipped_total").increment(1);
            return RowResult::Skipped(IngestionWarning {
                team_id: person.team_id,
                person_id: person.id,
                message: "Person properties exceeds size limit and was rejected".to_string(),
            });
        };

        let trimmed_str = serde_json::to_string(&trimmed).unwrap_or_default();
        match self.db.execute_row(person, Some(&trimmed_str)).await {
            Ok(()) => {
                counter!("personhog_writer_properties_trimmed_writes_total").increment(1);
                RowResult::Trimmed(IngestionWarning {
                    team_id: person.team_id,
                    person_id: person.id,
                    message: "Person properties exceeded size limit and were trimmed".to_string(),
                })
            }
            Err(_) => {
                counter!("personhog_writer_rows_skipped_total").increment(1);
                RowResult::Skipped(IngestionWarning {
                    team_id: person.team_id,
                    person_id: person.id,
                    message: "Person properties exceeds size limit and was rejected".to_string(),
                })
            }
        }
    }

    /// Run per-row upserts for a batch of persons with bounded concurrency.
    /// Used by the writer when a batch falls back to the per-row path after
    /// chunk-level data failures. pgbouncer handles PG-side backpressure;
    /// our bound is to keep sqlx pool turnover reasonable and cap memory of
    /// in-flight futures.
    pub async fn upsert_rows_parallel(&self, persons: Vec<Person>) -> Vec<RowResult> {
        let start = std::time::Instant::now();
        let concurrency = self.row_fallback_concurrency;
        let results: Vec<RowResult> = stream::iter(persons)
            .map(|p| async move {
                gauge!("personhog_writer_row_fallback_in_flight").increment(1.0);
                let res = self.upsert_row(&p).await;
                gauge!("personhog_writer_row_fallback_in_flight").decrement(1.0);
                res
            })
            .buffer_unordered(concurrency)
            .collect()
            .await;
        histogram!("personhog_writer_row_fallback_duration_seconds")
            .record(start.elapsed().as_secs_f64());
        results
    }

    async fn run_parallel_chunks(&self, chunks: Vec<Vec<Person>>) -> BatchOutcome {
        let mut set: JoinSet<(Vec<Person>, Result<(), WriteError>)> = JoinSet::new();
        for chunk in chunks {
            let db = Arc::clone(&self.db);
            set.spawn(async move {
                let res = db.execute_chunk(&chunk).await;
                (chunk, res)
            });
        }

        let mut transient = Vec::new();
        let mut data_failed = Vec::new();

        while let Some(joined) = set.join_next().await {
            match joined {
                Ok((_chunk, Ok(()))) => {}
                Ok((chunk, Err(e))) => match e.kind {
                    WriteErrorKind::Transient => transient.extend(chunk),
                    WriteErrorKind::Data | WriteErrorKind::PropertiesSizeViolation => {
                        data_failed.extend(chunk);
                    }
                },
                Err(join_err) => {
                    // A spawned task panicked. Abort remaining chunks and
                    // drain so nothing lingers past our return.
                    set.abort_all();
                    while set.join_next().await.is_some() {}
                    return BatchOutcome::Fatal(classify_join_error(join_err));
                }
            }
        }

        if !transient.is_empty() {
            counter!("personhog_writer_chunk_retry_rows_total").increment(transient.len() as u64);
        }
        if !data_failed.is_empty() {
            counter!("personhog_writer_chunk_fallback_rows_total")
                .increment(data_failed.len() as u64);
        }

        if transient.is_empty() && data_failed.is_empty() {
            BatchOutcome::Success
        } else {
            BatchOutcome::Partial {
                transient,
                data_failed,
            }
        }
    }
}

fn split_into_owned_chunks(mut persons: Vec<Person>, chunk_size: usize) -> Vec<Vec<Person>> {
    let chunk_size = chunk_size.max(1);
    let expected = persons.len().div_ceil(chunk_size);
    let mut out = Vec::with_capacity(expected);
    while !persons.is_empty() {
        let take = chunk_size.min(persons.len());
        out.push(persons.drain(..take).collect());
    }
    out
}

fn partial_from_failed_chunk(chunk: Vec<Person>, kind: WriteErrorKind) -> BatchOutcome {
    match kind {
        WriteErrorKind::Transient => {
            counter!("personhog_writer_chunk_retry_rows_total").increment(chunk.len() as u64);
            BatchOutcome::Partial {
                transient: chunk,
                data_failed: Vec::new(),
            }
        }
        WriteErrorKind::Data | WriteErrorKind::PropertiesSizeViolation => {
            counter!("personhog_writer_chunk_fallback_rows_total").increment(chunk.len() as u64);
            BatchOutcome::Partial {
                transient: Vec::new(),
                data_failed: chunk,
            }
        }
    }
}

fn classify_join_error(e: tokio::task::JoinError) -> FatalError {
    let message = match e.try_into_panic() {
        Ok(payload) => {
            let msg = payload
                .downcast_ref::<&'static str>()
                .map(|s| (*s).to_string())
                .or_else(|| payload.downcast_ref::<String>().cloned())
                .unwrap_or_else(|| "non-string panic payload".to_string());
            format!("chunk task panicked: {msg}")
        }
        Err(e) => format!("chunk task failed unexpectedly: {e}"),
    };
    counter!("personhog_writer_chunk_fatal_total").increment(1);
    error!(%message, "batch chunk task failed fatally");
    FatalError { message }
}

// ── Unit tests ───────────────────────────────────────────────────
//
// These tests exercise the orchestration layer (chunking, parallel
// execution, outcome partitioning, per-row fallback) against a stub DB
// that produces scripted responses. PG correctness is covered separately
// by the integration tests.

#[cfg(test)]
mod tests {
    use super::*;

    use std::collections::HashMap;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex;

    /// Stub DB for unit-testing orchestration. Responses can be scripted
    /// per-chunk (by first-person id) or as a FIFO by call order, with a
    /// default fallback. Per-row responses are separate.
    #[derive(Debug, Clone, Copy)]
    enum ChunkResponse {
        Ok,
        Err(WriteErrorKind),
        Panic,
    }

    struct StubDb {
        chunk_by_first_id: Mutex<HashMap<i64, ChunkResponse>>,
        chunk_fifo: Mutex<Vec<ChunkResponse>>,
        chunk_default: ChunkResponse,
        chunk_calls: AtomicUsize,
        row_fifo: Mutex<Vec<ChunkResponse>>,
        row_default: ChunkResponse,
        row_calls: AtomicUsize,
    }

    impl StubDb {
        fn new() -> Self {
            Self {
                chunk_by_first_id: Mutex::new(HashMap::new()),
                chunk_fifo: Mutex::new(Vec::new()),
                chunk_default: ChunkResponse::Ok,
                chunk_calls: AtomicUsize::new(0),
                row_fifo: Mutex::new(Vec::new()),
                row_default: ChunkResponse::Ok,
                row_calls: AtomicUsize::new(0),
            }
        }

        fn with_chunk_default(mut self, r: ChunkResponse) -> Self {
            self.chunk_default = r;
            self
        }

        fn with_row_default(mut self, r: ChunkResponse) -> Self {
            self.row_default = r;
            self
        }

        fn script_chunk_for_id(self, id: i64, r: ChunkResponse) -> Self {
            self.chunk_by_first_id.lock().unwrap().insert(id, r);
            self
        }

        fn lookup_chunk_response(&self, chunk: &[Person]) -> ChunkResponse {
            if let Some(first) = chunk.first() {
                if let Some(r) = self.chunk_by_first_id.lock().unwrap().get(&first.id) {
                    return *r;
                }
            }
            let mut fifo = self.chunk_fifo.lock().unwrap();
            if !fifo.is_empty() {
                return fifo.remove(0);
            }
            self.chunk_default
        }

        fn lookup_row_response(&self) -> ChunkResponse {
            let mut fifo = self.row_fifo.lock().unwrap();
            if !fifo.is_empty() {
                return fifo.remove(0);
            }
            self.row_default
        }
    }

    #[async_trait]
    impl PersonDb for StubDb {
        async fn execute_chunk(&self, chunk: &[Person]) -> Result<(), WriteError> {
            self.chunk_calls.fetch_add(1, Ordering::SeqCst);
            match self.lookup_chunk_response(chunk) {
                ChunkResponse::Ok => Ok(()),
                ChunkResponse::Err(kind) => Err(WriteError {
                    message: format!("stub error: {kind:?}"),
                    kind,
                }),
                ChunkResponse::Panic => panic!("stub db chunk panic"),
            }
        }

        async fn execute_row(
            &self,
            _person: &Person,
            _override: Option<&str>,
        ) -> Result<(), WriteError> {
            self.row_calls.fetch_add(1, Ordering::SeqCst);
            match self.lookup_row_response() {
                ChunkResponse::Ok => Ok(()),
                ChunkResponse::Err(kind) => Err(WriteError {
                    message: format!("stub row error: {kind:?}"),
                    kind,
                }),
                ChunkResponse::Panic => panic!("stub db row panic"),
            }
        }
    }

    fn p(id: i64) -> Person {
        Person {
            id,
            team_id: 1,
            uuid: uuid::Uuid::new_v4().to_string(),
            version: 1,
            ..Default::default()
        }
    }

    // ── Split helper ────────────────────────────────────────────

    #[test]
    fn split_preserves_order_and_count() {
        let persons: Vec<Person> = (0..11).map(p).collect();
        let chunks = split_into_owned_chunks(persons, 4);
        assert_eq!(chunks.len(), 3);
        assert_eq!(chunks[0].len(), 4);
        assert_eq!(chunks[1].len(), 4);
        assert_eq!(chunks[2].len(), 3);
        assert_eq!(chunks[0][0].id, 0);
        assert_eq!(chunks[2][2].id, 10);
    }

    #[test]
    fn split_exact_multiple() {
        let persons: Vec<Person> = (0..6).map(p).collect();
        let chunks = split_into_owned_chunks(persons, 3);
        assert_eq!(chunks.len(), 2);
        assert_eq!(chunks[0].len(), 3);
        assert_eq!(chunks[1].len(), 3);
    }

    #[test]
    fn split_empty() {
        let chunks = split_into_owned_chunks(Vec::<Person>::new(), 5);
        assert!(chunks.is_empty());
    }

    // ── Empty + success paths ───────────────────────────────────

    #[tokio::test]
    async fn upsert_batch_empty_returns_success() {
        let store = PersonWriteStore::new(StubDb::new(), 10, 4);
        assert!(matches!(
            store.upsert_batch(Vec::new()).await,
            BatchOutcome::Success
        ));
    }

    #[tokio::test]
    async fn upsert_batch_single_chunk_success() {
        let store = PersonWriteStore::new(StubDb::new(), 10, 4);
        let persons: Vec<Person> = (0..5).map(p).collect();
        assert!(matches!(
            store.upsert_batch(persons).await,
            BatchOutcome::Success
        ));
    }

    #[tokio::test]
    async fn upsert_batch_parallel_all_succeed() {
        // 6 persons, chunk_size 2 → 3 parallel chunks
        let store = PersonWriteStore::new(StubDb::new(), 2, 4);
        let persons: Vec<Person> = (0..6).map(p).collect();
        assert!(matches!(
            store.upsert_batch(persons).await,
            BatchOutcome::Success
        ));
    }

    // ── Single-chunk fast path, each failure kind ──────────────

    #[tokio::test]
    async fn upsert_batch_transient_routes_to_transient_bucket() {
        let db = StubDb::new().with_chunk_default(ChunkResponse::Err(WriteErrorKind::Transient));
        let store = PersonWriteStore::new(db, 10, 4);
        let persons: Vec<Person> = (0..3).map(p).collect();
        match store.upsert_batch(persons).await {
            BatchOutcome::Partial {
                transient,
                data_failed,
            } => {
                assert_eq!(transient.len(), 3);
                assert!(data_failed.is_empty());
            }
            other => panic!("expected Partial, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn upsert_batch_data_error_routes_to_data_bucket() {
        let db = StubDb::new().with_chunk_default(ChunkResponse::Err(WriteErrorKind::Data));
        let store = PersonWriteStore::new(db, 10, 4);
        let persons: Vec<Person> = (0..3).map(p).collect();
        match store.upsert_batch(persons).await {
            BatchOutcome::Partial {
                transient,
                data_failed,
            } => {
                assert!(transient.is_empty());
                assert_eq!(data_failed.len(), 3);
            }
            other => panic!("expected Partial, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn upsert_batch_size_violation_routes_to_data_bucket() {
        let db = StubDb::new()
            .with_chunk_default(ChunkResponse::Err(WriteErrorKind::PropertiesSizeViolation));
        let store = PersonWriteStore::new(db, 10, 4);
        let persons: Vec<Person> = (0..3).map(p).collect();
        match store.upsert_batch(persons).await {
            BatchOutcome::Partial {
                transient,
                data_failed,
            } => {
                assert!(transient.is_empty());
                assert_eq!(data_failed.len(), 3);
            }
            other => panic!("expected Partial, got {other:?}"),
        }
    }

    // ── Parallel mixed outcomes ────────────────────────────────

    #[tokio::test]
    async fn upsert_batch_parallel_mixed_partitions_correctly() {
        // 6 persons with ids 0..5, chunk_size 2 → chunks [0,1], [2,3], [4,5]
        // Script first-id 0 → Ok, first-id 2 → transient, first-id 4 → data
        let db = StubDb::new()
            .script_chunk_for_id(0, ChunkResponse::Ok)
            .script_chunk_for_id(2, ChunkResponse::Err(WriteErrorKind::Transient))
            .script_chunk_for_id(4, ChunkResponse::Err(WriteErrorKind::Data));
        let store = PersonWriteStore::new(db, 2, 4);
        let persons: Vec<Person> = (0..6).map(p).collect();

        match store.upsert_batch(persons).await {
            BatchOutcome::Partial {
                transient,
                data_failed,
            } => {
                assert_eq!(transient.len(), 2);
                assert_eq!(transient[0].id, 2);
                assert_eq!(transient[1].id, 3);
                assert_eq!(data_failed.len(), 2);
                assert_eq!(data_failed[0].id, 4);
                assert_eq!(data_failed[1].id, 5);
            }
            other => panic!("expected Partial, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn upsert_batch_parallel_all_transient_returns_all_rows() {
        let db = StubDb::new().with_chunk_default(ChunkResponse::Err(WriteErrorKind::Transient));
        let store = PersonWriteStore::new(db, 2, 4);
        let persons: Vec<Person> = (0..6).map(p).collect();
        match store.upsert_batch(persons).await {
            BatchOutcome::Partial {
                transient,
                data_failed,
            } => {
                assert_eq!(transient.len(), 6);
                assert!(data_failed.is_empty());
            }
            other => panic!("expected Partial, got {other:?}"),
        }
    }

    // ── Panic handling ─────────────────────────────────────────

    #[tokio::test]
    async fn upsert_batch_chunk_panic_returns_fatal() {
        // One chunk panics, others return Ok. In parallel path we expect Fatal.
        let db = StubDb::new()
            .script_chunk_for_id(0, ChunkResponse::Ok)
            .script_chunk_for_id(2, ChunkResponse::Panic)
            .script_chunk_for_id(4, ChunkResponse::Ok);
        let store = PersonWriteStore::new(db, 2, 4);
        let persons: Vec<Person> = (0..6).map(p).collect();
        match store.upsert_batch(persons).await {
            BatchOutcome::Fatal(fatal) => {
                assert!(
                    fatal.message.contains("panicked"),
                    "fatal message should reference panic, got: {}",
                    fatal.message
                );
            }
            other => panic!("expected Fatal, got {other:?}"),
        }
    }

    // ── upsert_row ─────────────────────────────────────────────

    #[tokio::test]
    async fn upsert_row_success_returns_written() {
        let store = PersonWriteStore::new(StubDb::new(), 10, 4);
        assert!(matches!(store.upsert_row(&p(1)).await, RowResult::Written));
    }

    #[tokio::test]
    async fn upsert_row_transient_returns_skipped() {
        let db = StubDb::new().with_row_default(ChunkResponse::Err(WriteErrorKind::Transient));
        let store = PersonWriteStore::new(db, 10, 4);
        match store.upsert_row(&p(1)).await {
            RowResult::Skipped(warning) => {
                assert_eq!(warning.person_id, 1);
                assert!(warning.message.contains("Person upsert failed"));
            }
            other => panic!("expected Skipped, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn upsert_row_data_error_returns_skipped() {
        let db = StubDb::new().with_row_default(ChunkResponse::Err(WriteErrorKind::Data));
        let store = PersonWriteStore::new(db, 10, 4);
        assert!(matches!(
            store.upsert_row(&p(1)).await,
            RowResult::Skipped(_)
        ));
    }

    // ── upsert_rows_parallel ──────────────────────────────────

    #[tokio::test]
    async fn upsert_rows_parallel_returns_a_result_per_person() {
        let store = PersonWriteStore::new(StubDb::new(), 10, 4);
        let persons: Vec<Person> = (0..10).map(p).collect();
        let results = store.upsert_rows_parallel(persons).await;
        assert_eq!(results.len(), 10);
        assert!(results.iter().all(|r| matches!(r, RowResult::Written)));
    }

    #[tokio::test]
    async fn upsert_rows_parallel_surfaces_errors_as_skipped() {
        let db = StubDb::new().with_row_default(ChunkResponse::Err(WriteErrorKind::Data));
        let store = PersonWriteStore::new(db, 10, 4);
        let persons: Vec<Person> = (0..5).map(p).collect();
        let results = store.upsert_rows_parallel(persons).await;
        assert_eq!(results.len(), 5);
        assert!(results.iter().all(|r| matches!(r, RowResult::Skipped(_))));
    }
}
