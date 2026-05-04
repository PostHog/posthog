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

use std::str::from_utf8;
use std::sync::Arc;
use std::time::Instant;

use async_trait::async_trait;
use futures::stream::{self, StreamExt};
use metrics::{counter, gauge, histogram};
use personhog_proto::personhog::types::v1::Person;
use tokio::task::{JoinError, JoinSet};
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

/// Knobs that shape how the store batches, parallelizes, and trims. Scoped
/// to just what the store needs so the store doesn't depend on the
/// service-wide `Config` type.
///
/// No `Default` impl: production values live in envconfig (and are mapped
/// via `Config`), and test values are in test-only helpers. Keeping these
/// apart prevents accidental reliance on hardcoded defaults in prod code.
#[derive(Debug, Clone)]
pub struct StoreConfig {
    pub chunk_size: usize,
    pub row_fallback_concurrency: usize,
    pub properties_size_threshold: usize,
    pub properties_trim_target: usize,
}

/// Production person write store. Splits batches into chunks, runs them in
/// parallel against a `PersonDb`, partitions outcomes by failure class, and
/// handles per-row fallback with property trimming.
pub struct PersonWriteStore<D: PersonDb> {
    db: Arc<D>,
    chunk_size: usize,
    row_fallback_concurrency: usize,
    properties_size_threshold: usize,
    properties_trim_target: usize,
}

impl<D: PersonDb + 'static> PersonWriteStore<D> {
    pub fn new(db: D, cfg: StoreConfig) -> Self {
        Self {
            db: Arc::new(db),
            chunk_size: cfg.chunk_size.max(1),
            row_fallback_concurrency: cfg.row_fallback_concurrency.max(1),
            properties_size_threshold: cfg.properties_size_threshold,
            properties_trim_target: cfg.properties_trim_target,
        }
    }

    /// Preflight oversized persons out of a batch. For each person whose raw
    /// properties bytes exceed the configured threshold, attempt to trim via
    /// `properties::trim_properties_to_fit_size`; if the trim brings it below
    /// the threshold the person rejoins the batch with its properties replaced,
    /// otherwise it's skipped with an ingestion warning.
    ///
    /// This avoids a single oversized row forcing the whole chunk down the
    /// per-row fallback path.
    pub fn preflight_trim_batch(
        &self,
        persons: Vec<Person>,
    ) -> (Vec<Person>, Vec<IngestionWarning>) {
        let mut kept = Vec::with_capacity(persons.len());
        let mut warnings = Vec::new();

        for mut person in persons {
            if person.properties.len() <= self.properties_size_threshold {
                kept.push(person);
                continue;
            }

            counter!("personhog_writer_properties_preempted_total").increment(1);

            match self.try_trim_properties(&person) {
                TrimOutcome::Trimmed(bytes) => {
                    counter!("personhog_writer_properties_trimmed_writes_total").increment(1);
                    person.properties = bytes;
                    warnings.push(trimmed_warning(&person));
                    kept.push(person);
                }
                TrimOutcome::InvalidJson => {
                    counter!("personhog_writer_invalid_json_total").increment(1);
                    counter!("personhog_writer_rows_skipped_total").increment(1);
                    warn!(
                        team_id = person.team_id,
                        person_id = person.id,
                        "oversized person has invalid JSON properties, skipping"
                    );
                    warnings.push(invalid_json_warning(&person));
                }
                TrimOutcome::CannotFit => {
                    counter!("personhog_writer_rows_skipped_total").increment(1);
                    warnings.push(rejected_warning(&person));
                }
            }
        }

        (kept, warnings)
    }

    /// Attempt to trim a person's properties to fit under `properties_trim_target`.
    /// `trim_properties_to_fit_size` returns `None` when it can't reach the
    /// target (e.g. protected-only keys exceed it), so we don't need a
    /// second post-trim size check here.
    ///
    /// Pure computation (no IO); used by both the preflight batch path and
    /// the defensive per-row fallback after a PG size-violation error.
    fn try_trim_properties(&self, person: &Person) -> TrimOutcome {
        let value: serde_json::Value = match serde_json::from_slice(&person.properties) {
            Ok(v) => v,
            Err(_) => return TrimOutcome::InvalidJson,
        };

        let Some(trimmed) = properties::trim_properties_to_fit_size(
            &value,
            person.team_id,
            person.id,
            self.properties_trim_target,
        ) else {
            return TrimOutcome::CannotFit;
        };

        let bytes = serde_json::to_vec(&trimmed).unwrap_or_default();
        if bytes.is_empty() {
            return TrimOutcome::CannotFit;
        }
        TrimOutcome::Trimmed(bytes)
    }

    pub async fn upsert_batch(&self, persons: Vec<Person>) -> BatchOutcome {
        if persons.is_empty() {
            return BatchOutcome::Success;
        }

        let start = Instant::now();
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

        // Size violation: defensive trim-and-retry. The preflight path usually
        // catches oversized persons first; this branch fires for the edge case
        // where raw bytes fit the threshold but JSONB encoding pushes us over.
        //
        // `try_trim_properties` may return `CannotFit` for either the "untrimable
        // (protected keys already oversized)" case or the rare "raw bytes look
        // fine but JSONB is big" case. Either way skipping is correct: the same
        // raw bytes already failed at PG, and we have no smaller version to try.
        match self.try_trim_properties(person) {
            TrimOutcome::Trimmed(bytes) => {
                let trimmed_str = from_utf8(&bytes).unwrap_or("{}");
                match self.db.execute_row(person, Some(trimmed_str)).await {
                    Ok(()) => {
                        counter!("personhog_writer_properties_trimmed_writes_total").increment(1);
                        RowResult::Trimmed(trimmed_warning(person))
                    }
                    Err(_) => {
                        counter!("personhog_writer_rows_skipped_total").increment(1);
                        RowResult::Skipped(rejected_warning(person))
                    }
                }
            }
            TrimOutcome::InvalidJson | TrimOutcome::CannotFit => {
                counter!("personhog_writer_rows_skipped_total").increment(1);
                RowResult::Skipped(rejected_warning(person))
            }
        }
    }

    /// Run per-row upserts for a batch of persons with bounded concurrency.
    /// Used by the writer when a batch falls back to the per-row path after
    /// chunk-level data failures. pgbouncer handles PG-side backpressure;
    /// our bound is to keep sqlx pool turnover reasonable and cap memory of
    /// in-flight futures.
    pub async fn upsert_rows_parallel(&self, persons: Vec<Person>) -> Vec<RowResult> {
        let start = Instant::now();
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

/// Result of attempting to trim a person's properties down to a size that
/// fits the configured threshold. Used by both the preflight batch path
/// and the defensive per-row fallback.
enum TrimOutcome {
    /// Trim succeeded; these bytes are guaranteed to be under the threshold.
    Trimmed(Vec<u8>),
    /// The person's properties weren't valid JSON. Skip.
    InvalidJson,
    /// Trim ran but the result still exceeds the threshold. Typically means
    /// protected properties alone are oversized, or the value wasn't a JSON
    /// object. Skip.
    CannotFit,
}

fn trimmed_warning(p: &Person) -> IngestionWarning {
    IngestionWarning {
        team_id: p.team_id,
        person_id: p.id,
        message: "Person properties exceeded size limit and were trimmed".to_string(),
    }
}

fn rejected_warning(p: &Person) -> IngestionWarning {
    IngestionWarning {
        team_id: p.team_id,
        person_id: p.id,
        message: "Person properties exceeds size limit and was rejected".to_string(),
    }
}

fn invalid_json_warning(p: &Person) -> IngestionWarning {
    IngestionWarning {
        team_id: p.team_id,
        person_id: p.id,
        message: "Person properties are invalid JSON and exceed size limit — rejected".to_string(),
    }
}

fn classify_join_error(e: JoinError) -> FatalError {
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

// ── Test-only helpers ────────────────────────────────────────────
//
// `test_default` provides a `StoreConfig` with values tuned for unit tests
// (small chunk sizes, small concurrency). It's gated on `#[cfg(test)]` so it
// can never be reached from production code. Integration tests (separate
// crate) have their own helper in `tests/common/mod.rs`.

#[cfg(test)]
impl StoreConfig {
    pub(crate) fn test_default() -> Self {
        Self {
            chunk_size: 100,
            row_fallback_concurrency: 4,
            properties_size_threshold: 655_360,
            properties_trim_target: 524_288,
        }
    }
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
        let store = PersonWriteStore::new(StubDb::new(), StoreConfig::test_default());
        assert!(matches!(
            store.upsert_batch(Vec::new()).await,
            BatchOutcome::Success
        ));
    }

    #[tokio::test]
    async fn upsert_batch_single_chunk_success() {
        let store = PersonWriteStore::new(StubDb::new(), StoreConfig::test_default());
        let persons: Vec<Person> = (0..5).map(p).collect();
        assert!(matches!(
            store.upsert_batch(persons).await,
            BatchOutcome::Success
        ));
    }

    #[tokio::test]
    async fn upsert_batch_parallel_all_succeed() {
        // 6 persons, chunk_size 2 → 3 parallel chunks
        let store = PersonWriteStore::new(
            StubDb::new(),
            StoreConfig {
                chunk_size: 2,
                ..StoreConfig::test_default()
            },
        );
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
        let store = PersonWriteStore::new(db, StoreConfig::test_default());
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
        let store = PersonWriteStore::new(db, StoreConfig::test_default());
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
        let store = PersonWriteStore::new(db, StoreConfig::test_default());
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
        let store = PersonWriteStore::new(
            db,
            StoreConfig {
                chunk_size: 2,
                ..StoreConfig::test_default()
            },
        );
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
        let store = PersonWriteStore::new(
            db,
            StoreConfig {
                chunk_size: 2,
                ..StoreConfig::test_default()
            },
        );
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
        let store = PersonWriteStore::new(
            db,
            StoreConfig {
                chunk_size: 2,
                ..StoreConfig::test_default()
            },
        );
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
        let store = PersonWriteStore::new(StubDb::new(), StoreConfig::test_default());
        assert!(matches!(store.upsert_row(&p(1)).await, RowResult::Written));
    }

    #[tokio::test]
    async fn upsert_row_transient_returns_skipped() {
        let db = StubDb::new().with_row_default(ChunkResponse::Err(WriteErrorKind::Transient));
        let store = PersonWriteStore::new(db, StoreConfig::test_default());
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
        let store = PersonWriteStore::new(db, StoreConfig::test_default());
        assert!(matches!(
            store.upsert_row(&p(1)).await,
            RowResult::Skipped(_)
        ));
    }

    // ── upsert_rows_parallel ──────────────────────────────────

    #[tokio::test]
    async fn upsert_rows_parallel_returns_a_result_per_person() {
        let store = PersonWriteStore::new(StubDb::new(), StoreConfig::test_default());
        let persons: Vec<Person> = (0..10).map(p).collect();
        let results = store.upsert_rows_parallel(persons).await;
        assert_eq!(results.len(), 10);
        assert!(results.iter().all(|r| matches!(r, RowResult::Written)));
    }

    #[tokio::test]
    async fn upsert_rows_parallel_surfaces_errors_as_skipped() {
        let db = StubDb::new().with_row_default(ChunkResponse::Err(WriteErrorKind::Data));
        let store = PersonWriteStore::new(db, StoreConfig::test_default());
        let persons: Vec<Person> = (0..5).map(p).collect();
        let results = store.upsert_rows_parallel(persons).await;
        assert_eq!(results.len(), 5);
        assert!(results.iter().all(|r| matches!(r, RowResult::Skipped(_))));
    }

    // ── preflight_trim_batch ───────────────────────────────────

    #[test]
    fn preflight_leaves_normal_persons_untouched() {
        let store = PersonWriteStore::new(StubDb::new(), StoreConfig::test_default());
        let persons: Vec<Person> = (0..5).map(p).collect();
        let (kept, warnings) = store.preflight_trim_batch(persons);
        assert_eq!(kept.len(), 5);
        assert!(warnings.is_empty());
    }

    #[test]
    fn preflight_trims_oversized_and_keeps_them_in_batch() {
        // Small threshold so we can exercise the path without megabytes of JSON.
        let store = PersonWriteStore::new(
            StubDb::new(),
            StoreConfig {
                properties_size_threshold: 1024,
                properties_trim_target: 512,
                ..StoreConfig::test_default()
            },
        );
        let normal = p(1);
        // Oversized person: a single trimmable key with lots of content.
        let mut oversized = p(2);
        oversized.properties = serde_json::to_vec(&serde_json::json!({
            "email": "protected@example.com",
            "bloat": "x".repeat(2_000),
        }))
        .unwrap();

        let (kept, warnings) = store.preflight_trim_batch(vec![normal, oversized]);

        assert_eq!(kept.len(), 2, "both persons should remain after trim");
        // The trimmed person's properties should now be within threshold.
        let trimmed = kept.iter().find(|p| p.id == 2).unwrap();
        assert!(trimmed.properties.len() <= 1024);
        assert_eq!(warnings.len(), 1);
        assert!(warnings[0].message.contains("trimmed"));
    }

    #[test]
    fn preflight_skips_oversized_when_only_protected_keys_exceed() {
        // 1 KiB threshold; protected `email` alone exceeds it.
        let store = PersonWriteStore::new(
            StubDb::new(),
            StoreConfig {
                properties_size_threshold: 1024,
                properties_trim_target: 512,
                ..StoreConfig::test_default()
            },
        );
        let mut untrimable = p(1);
        untrimable.properties = serde_json::to_vec(&serde_json::json!({
            "email": "x".repeat(2_000),
        }))
        .unwrap();

        let (kept, warnings) = store.preflight_trim_batch(vec![untrimable]);

        assert!(kept.is_empty());
        assert_eq!(warnings.len(), 1);
        assert!(warnings[0].message.contains("rejected"));
    }

    #[test]
    fn preflight_skips_invalid_json() {
        let store = PersonWriteStore::new(
            StubDb::new(),
            StoreConfig {
                properties_size_threshold: 16,
                properties_trim_target: 8,
                ..StoreConfig::test_default()
            },
        );
        let mut bad = p(1);
        bad.properties = vec![b'n'; 32]; // "nnnn..." — not valid JSON and > 16 bytes

        let (kept, warnings) = store.preflight_trim_batch(vec![bad]);

        assert!(kept.is_empty());
        assert_eq!(warnings.len(), 1);
        assert!(warnings[0].message.contains("invalid JSON"));
    }

    #[test]
    fn preflight_preserves_content_for_untouched_persons() {
        let store = PersonWriteStore::new(StubDb::new(), StoreConfig::test_default());
        let original: Vec<Person> = (0..3).map(p).collect();

        let (kept, warnings) = store.preflight_trim_batch(original.clone());

        assert_eq!(kept.len(), 3);
        assert!(warnings.is_empty());
        for (a, b) in original.iter().zip(kept.iter()) {
            assert_eq!(a.id, b.id);
            assert_eq!(a.properties, b.properties);
        }
    }
}
