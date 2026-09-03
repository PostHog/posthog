//! Write store layer: orchestrates batch execution across parallel chunks,
//! handles per-row fallback, and surfaces outcomes as `BatchOutcome` (for
//! batches) or `RowFallbackOutcome` (for the per-row isolation pass).
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
use std::time::Instant;

use async_trait::async_trait;
use futures::stream::{self, StreamExt};
use metrics::{counter, gauge, histogram};
use personhog_proto::personhog::types::v1::Person;
use tokio::sync::Semaphore;
use tokio::task::{JoinError, JoinSet};
use tracing::error;

// Re-exported so callers importing from `store::` keep working.
pub use crate::error::{FatalError, WriteError, WriteErrorKind};

/// The database primitive the store layer orchestrates against. Implemented
/// by `PgStore` for production and by mocks for testing.
#[async_trait]
pub trait PersonDb: Send + Sync {
    /// Execute a single upsert statement covering a chunk of persons.
    async fn execute_chunk(&self, chunk: &[Person]) -> Result<(), WriteError>;

    /// Execute a single-row upsert.
    async fn execute_row(&self, person: &Person) -> Result<(), WriteError>;
}

/// Outcome of a batch upsert. Reports which chunks (if any) need retry,
/// grouped by failure class so the caller picks the right strategy:
/// transient chunks are retried as batches after backoff, saturated chunks
/// are retried without counting toward failure escalation, data-failed
/// chunks fall through to per-row inserts to isolate bad records.
#[derive(Debug)]
pub enum BatchOutcome {
    Success,
    Partial {
        transient: Vec<Person>,
        saturated: Vec<Person>,
        data_failed: Vec<Person>,
    },
    /// A chunk task panicked. The persons in that chunk are unrecoverable;
    /// the writer must escalate. The Kafka offset has not been committed, so
    /// the underlying records will be redelivered on restart.
    Fatal(FatalError),
}

/// A person Postgres cannot apply for a non-transient reason. The leader
/// admits every record against the writer's own rejection surface, so a
/// violation means admission has a gap — the writer refuses to commit past
/// it rather than skip (a skip would permanently diverge PG from the
/// cache and changelog, since every later snapshot for the person builds
/// on the same unapplyable state).
#[derive(Debug)]
pub struct RowViolation {
    pub team_id: i64,
    pub person_id: i64,
    pub kind: WriteErrorKind,
}

/// Outcome of the per-row fallback pass over a data-failed chunk.
#[derive(Debug, Default)]
pub struct RowFallbackOutcome {
    /// Rows that failed transiently; the caller retries them with backoff.
    pub transient: Vec<Person>,
    /// Rows that hit local pool saturation; the caller retries them
    /// without counting the round toward failure escalation.
    pub saturated: Vec<Person>,
    /// Rows PG cannot apply — invariant violations that must halt the
    /// flush without committing.
    pub violations: Vec<RowViolation>,
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
}

/// Production person write store. Splits batches into chunks, runs them in
/// parallel against a `PersonDb`, partitions outcomes by failure class, and
/// handles per-row fallback.
///
/// Every statement — chunk or row — first takes a permit from `permits`,
/// which main shares across all lanes' stores. That makes the permit count
/// the pod-wide ceiling on in-flight statements: a backlogged flush queues
/// at the semaphore (an unbounded, cheap wait) instead of oversubscribing
/// the pool and converting its own burst into acquire timeouts.
pub struct PersonWriteStore<D: PersonDb> {
    db: Arc<D>,
    chunk_size: usize,
    row_fallback_concurrency: usize,
    permits: Arc<Semaphore>,
}

impl<D: PersonDb + 'static> PersonWriteStore<D> {
    pub fn new(db: D, cfg: StoreConfig, permits: Arc<Semaphore>) -> Self {
        Self {
            db: Arc::new(db),
            chunk_size: cfg.chunk_size.max(1),
            row_fallback_concurrency: cfg.row_fallback_concurrency.max(1),
            permits,
        }
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
            let _permit = self.acquire_permit().await;
            match self.db.execute_chunk(&chunk).await {
                Ok(()) => BatchOutcome::Success,
                Err(e) => partial_from_failed_chunk(chunk, e.kind),
            }
        } else {
            self.run_parallel_chunks(chunks).await
        };

        histogram!("personhog_writer_flush_duration_ms")
            .record(start.elapsed().as_secs_f64() * 1000.0);
        histogram!("personhog_writer_flush_rows").record(total as f64);
        outcome
    }

    pub async fn upsert_row(&self, person: &Person) -> Result<(), WriteError> {
        let _permit = self.acquire_permit().await;
        self.db.execute_row(person).await
    }

    async fn acquire_permit(&self) -> tokio::sync::SemaphorePermit<'_> {
        self.permits
            .acquire()
            .await
            .expect("upsert permit semaphore is never closed")
    }

    /// Run per-row upserts for a batch of persons with bounded concurrency,
    /// isolating which rows a data-failed chunk actually cannot apply.
    /// The effective bound is min(`row_fallback_concurrency`, free permits):
    /// each row also takes an upsert permit, so fallback traffic counts
    /// against the same pod-wide statement ceiling as chunks.
    ///
    /// Transient failures are returned for retry. Non-transient failures
    /// are invariant violations (the leader admitted an unapplyable
    /// record): logged loudly and returned so the caller halts the flush.
    pub async fn upsert_rows_parallel(&self, persons: Vec<Person>) -> RowFallbackOutcome {
        let start = Instant::now();
        let concurrency = self.row_fallback_concurrency;
        let results: Vec<(Person, Result<(), WriteError>)> = stream::iter(persons)
            .map(|p| async move {
                gauge!("personhog_writer_row_fallback_in_flight").increment(1.0);
                let res = self.upsert_row(&p).await;
                gauge!("personhog_writer_row_fallback_in_flight").decrement(1.0);
                (p, res)
            })
            .buffer_unordered(concurrency)
            .collect()
            .await;
        histogram!("personhog_writer_row_fallback_duration_ms")
            .record(start.elapsed().as_secs_f64() * 1000.0);

        let mut outcome = RowFallbackOutcome::default();
        for (person, result) in results {
            match result {
                Ok(()) => {}
                Err(e) if matches!(e.kind, WriteErrorKind::Transient) => {
                    outcome.transient.push(person);
                }
                Err(e) if matches!(e.kind, WriteErrorKind::Saturation) => {
                    outcome.saturated.push(person);
                }
                Err(e) => {
                    counter!(
                        "personhog_writer_unapplyable_rows_total",
                        "kind" => kind_label(e.kind)
                    )
                    .increment(1);
                    error!(
                        team_id = person.team_id,
                        person_id = person.id,
                        kind = ?e.kind,
                        error = %e.message,
                        "PG cannot apply a leader-admitted record; admission \
                         has a gap — halting without committing"
                    );
                    outcome.violations.push(RowViolation {
                        team_id: person.team_id,
                        person_id: person.id,
                        kind: e.kind,
                    });
                }
            }
        }
        outcome
    }

    async fn run_parallel_chunks(&self, chunks: Vec<Vec<Person>>) -> BatchOutcome {
        let mut set: JoinSet<(Vec<Person>, Result<(), WriteError>)> = JoinSet::new();
        for chunk in chunks {
            let db = Arc::clone(&self.db);
            let permits = Arc::clone(&self.permits);
            set.spawn(async move {
                let _permit = permits
                    .acquire_owned()
                    .await
                    .expect("upsert permit semaphore is never closed");
                let res = db.execute_chunk(&chunk).await;
                (chunk, res)
            });
        }

        let mut transient = Vec::new();
        let mut saturated = Vec::new();
        let mut data_failed = Vec::new();

        while let Some(joined) = set.join_next().await {
            match joined {
                Ok((_chunk, Ok(()))) => {}
                Ok((chunk, Err(e))) => match e.kind {
                    WriteErrorKind::Transient => transient.extend(chunk),
                    WriteErrorKind::Saturation => saturated.extend(chunk),
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
        if !saturated.is_empty() {
            counter!("personhog_writer_chunk_saturated_rows_total")
                .increment(saturated.len() as u64);
        }
        if !data_failed.is_empty() {
            counter!("personhog_writer_chunk_fallback_rows_total")
                .increment(data_failed.len() as u64);
        }

        if transient.is_empty() && saturated.is_empty() && data_failed.is_empty() {
            BatchOutcome::Success
        } else {
            BatchOutcome::Partial {
                transient,
                saturated,
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
                saturated: Vec::new(),
                data_failed: Vec::new(),
            }
        }
        WriteErrorKind::Saturation => {
            counter!("personhog_writer_chunk_saturated_rows_total").increment(chunk.len() as u64);
            BatchOutcome::Partial {
                transient: Vec::new(),
                saturated: chunk,
                data_failed: Vec::new(),
            }
        }
        WriteErrorKind::Data | WriteErrorKind::PropertiesSizeViolation => {
            counter!("personhog_writer_chunk_fallback_rows_total").increment(chunk.len() as u64);
            BatchOutcome::Partial {
                transient: Vec::new(),
                saturated: Vec::new(),
                data_failed: chunk,
            }
        }
    }
}

/// Stable metric-label form of a non-transient error kind.
fn kind_label(kind: WriteErrorKind) -> &'static str {
    match kind {
        WriteErrorKind::PropertiesSizeViolation => "size",
        WriteErrorKind::Data => "data",
        WriteErrorKind::Transient => "transient",
        WriteErrorKind::Saturation => "saturation",
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

        async fn execute_row(&self, _person: &Person) -> Result<(), WriteError> {
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

    /// Store with a permit budget large enough to never constrain a test.
    fn test_store(db: StubDb, cfg: StoreConfig) -> PersonWriteStore<StubDb> {
        PersonWriteStore::new(db, cfg, Arc::new(Semaphore::new(64)))
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
        let store = test_store(StubDb::new(), StoreConfig::test_default());
        assert!(matches!(
            store.upsert_batch(Vec::new()).await,
            BatchOutcome::Success
        ));
    }

    #[tokio::test]
    async fn upsert_batch_single_chunk_success() {
        let store = test_store(StubDb::new(), StoreConfig::test_default());
        let persons: Vec<Person> = (0..5).map(p).collect();
        assert!(matches!(
            store.upsert_batch(persons).await,
            BatchOutcome::Success
        ));
    }

    #[tokio::test]
    async fn upsert_batch_parallel_all_succeed() {
        // 6 persons, chunk_size 2 → 3 parallel chunks
        let store = test_store(
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
        let store = test_store(db, StoreConfig::test_default());
        let persons: Vec<Person> = (0..3).map(p).collect();
        match store.upsert_batch(persons).await {
            BatchOutcome::Partial {
                transient,
                saturated,
                data_failed,
            } => {
                assert_eq!(transient.len(), 3);
                assert!(saturated.is_empty());
                assert!(data_failed.is_empty());
            }
            other => panic!("expected Partial, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn upsert_batch_data_error_routes_to_data_bucket() {
        let db = StubDb::new().with_chunk_default(ChunkResponse::Err(WriteErrorKind::Data));
        let store = test_store(db, StoreConfig::test_default());
        let persons: Vec<Person> = (0..3).map(p).collect();
        match store.upsert_batch(persons).await {
            BatchOutcome::Partial {
                transient,
                saturated,
                data_failed,
            } => {
                assert!(transient.is_empty());
                assert!(saturated.is_empty());
                assert_eq!(data_failed.len(), 3);
            }
            other => panic!("expected Partial, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn upsert_batch_size_violation_routes_to_data_bucket() {
        let db = StubDb::new()
            .with_chunk_default(ChunkResponse::Err(WriteErrorKind::PropertiesSizeViolation));
        let store = test_store(db, StoreConfig::test_default());
        let persons: Vec<Person> = (0..3).map(p).collect();
        match store.upsert_batch(persons).await {
            BatchOutcome::Partial {
                transient,
                saturated,
                data_failed,
            } => {
                assert!(transient.is_empty());
                assert!(saturated.is_empty());
                assert_eq!(data_failed.len(), 3);
            }
            other => panic!("expected Partial, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn upsert_batch_saturation_routes_to_saturated_bucket() {
        let db = StubDb::new().with_chunk_default(ChunkResponse::Err(WriteErrorKind::Saturation));
        let store = test_store(db, StoreConfig::test_default());
        let persons: Vec<Person> = (0..3).map(p).collect();
        match store.upsert_batch(persons).await {
            BatchOutcome::Partial {
                transient,
                saturated,
                data_failed,
            } => {
                assert!(transient.is_empty());
                assert_eq!(saturated.len(), 3);
                assert!(data_failed.is_empty());
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
        let store = test_store(
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
                saturated,
                data_failed,
            } => {
                assert_eq!(transient.len(), 2);
                assert!(saturated.is_empty());
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
        let store = test_store(
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
                saturated,
                data_failed,
            } => {
                assert_eq!(transient.len(), 6);
                assert!(saturated.is_empty());
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
        let store = test_store(
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

    // ── upsert_rows_parallel ──────────────────────────────────

    #[tokio::test]
    async fn upsert_rows_parallel_applies_every_row_cleanly() {
        let store = test_store(StubDb::new(), StoreConfig::test_default());
        let persons: Vec<Person> = (0..10).map(p).collect();
        let outcome = store.upsert_rows_parallel(persons).await;
        assert!(outcome.transient.is_empty());
        assert!(outcome.violations.is_empty());
    }

    #[tokio::test]
    async fn upsert_rows_parallel_returns_transient_failures_for_retry() {
        let db = StubDb::new().with_row_default(ChunkResponse::Err(WriteErrorKind::Transient));
        let store = test_store(db, StoreConfig::test_default());
        let persons: Vec<Person> = (0..5).map(p).collect();
        let outcome = store.upsert_rows_parallel(persons).await;
        assert_eq!(outcome.transient.len(), 5);
        assert!(outcome.violations.is_empty());
    }

    #[tokio::test]
    async fn upsert_rows_parallel_returns_saturated_rows_for_retry() {
        let db = StubDb::new().with_row_default(ChunkResponse::Err(WriteErrorKind::Saturation));
        let store = test_store(db, StoreConfig::test_default());
        let persons: Vec<Person> = (0..5).map(p).collect();
        let outcome = store.upsert_rows_parallel(persons).await;
        assert!(outcome.transient.is_empty());
        assert_eq!(outcome.saturated.len(), 5);
        assert!(outcome.violations.is_empty());
    }

    // ── Permit bound ───────────────────────────────────────────

    #[tokio::test(start_paused = true)]
    async fn parallel_chunks_respect_the_shared_permit_bound() {
        struct ConcurrencyDb {
            current: Arc<AtomicUsize>,
            max: Arc<AtomicUsize>,
        }

        #[async_trait]
        impl PersonDb for ConcurrencyDb {
            async fn execute_chunk(&self, _chunk: &[Person]) -> Result<(), WriteError> {
                let now = self.current.fetch_add(1, Ordering::SeqCst) + 1;
                self.max.fetch_max(now, Ordering::SeqCst);
                tokio::time::sleep(std::time::Duration::from_millis(10)).await;
                self.current.fetch_sub(1, Ordering::SeqCst);
                Ok(())
            }

            async fn execute_row(&self, _person: &Person) -> Result<(), WriteError> {
                Ok(())
            }
        }

        let current = Arc::new(AtomicUsize::new(0));
        let max = Arc::new(AtomicUsize::new(0));
        let store = PersonWriteStore::new(
            ConcurrencyDb {
                current: Arc::clone(&current),
                max: Arc::clone(&max),
            },
            StoreConfig {
                chunk_size: 1,
                row_fallback_concurrency: 4,
            },
            Arc::new(Semaphore::new(2)),
        );

        // 8 persons at chunk_size 1 spawn 8 chunk tasks at once; the permit
        // budget of 2 must be the only thing bounding them.
        let persons: Vec<Person> = (0..8).map(p).collect();
        assert!(matches!(
            store.upsert_batch(persons).await,
            BatchOutcome::Success
        ));
        assert_eq!(max.load(Ordering::SeqCst), 2);
    }

    #[tokio::test]
    async fn upsert_rows_parallel_surfaces_unapplyable_rows_as_violations() {
        let db = StubDb::new().with_row_default(ChunkResponse::Err(WriteErrorKind::Data));
        let store = test_store(db, StoreConfig::test_default());
        let persons: Vec<Person> = (0..5).map(p).collect();
        let outcome = store.upsert_rows_parallel(persons).await;
        assert!(outcome.transient.is_empty());
        assert_eq!(outcome.violations.len(), 5);
        assert!(outcome
            .violations
            .iter()
            .all(|v| matches!(v.kind, WriteErrorKind::Data)));
    }
}
