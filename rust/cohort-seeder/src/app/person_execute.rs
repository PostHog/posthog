//! App layer: one person chunk's `stream-scan → eval → paced enqueue → mark → await → confirm`
//! pipeline. Depends on `clickhouse`, `kafka`, `store`, `domain`, and its `app` siblings.
//!
//! The scan is interleaved, never buffered: each row is evaluated and its seed enqueued before the
//! next row is read, so a chunk's memory stays constant. At stream end the chunk CASes
//! `scanning`→`produced` with the emitted count, then the remaining acks drain and the terminal
//! confirm runs — the behavioral post-mark machinery reused verbatim.

use std::sync::Arc;

use metrics::counter;
use tokio_util::sync::CancellationToken;

use cohort_core::hogvm::VmErrorClass;

use clickhouse::query::RowCursor;

use crate::clickhouse::person_scanner::{PersonRow, PersonScanError, PersonScanner};
use crate::clickhouse::person_sql::PersonScanSpec;
use crate::clickhouse::scan_volume::{self, ScanKind};
use crate::domain::{
    CancelCause, ClaimedChunk, Halted, PersonChunkSpecError, PersonEmissionPolicy, PersonEvaluator,
    PersonRowOutcome, PersonSeedContext, PinnedPersonRun, RecordStats, RetryBackoffPolicy,
    StreamedChunk,
};
use crate::kafka::pacing::TilePacer;
use crate::kafka::producer::SeedTileProducer;
use crate::observability::metrics::{
    MetricTimer, PERSONS_SCANNED, PERSON_CHUNK_SCAN_DURATION_SECONDS, PERSON_CONDITIONS_SHORTCUT,
    PERSON_HOGVM_ERRORS, PERSON_NONMATCHERS_SKIPPED, PERSON_ROWS_PRUNED, PERSON_ROWS_SKIPPED,
    PERSON_SCAN_FILTER, PERSON_SEEDS_PRODUCED, PRUNE_REASON_IRRELEVANT,
};
use crate::store::chunks::PgChunkStore;
use crate::store::lease::LeaseHandle;

use super::deliver::{self, InFlight, ProduceError, ProduceStop};
use super::execute::{mark_produced_halt, resolve_halt, ChunkOutcome, ConfirmedDetail};
use super::settings::ProducerSettings;

/// The owned inputs to one person chunk's processing task.
pub(super) struct PersonChunkTaskContext {
    pub(super) chunk: ClaimedChunk,
    pub(super) lease: LeaseHandle,
    pub(super) run: Arc<PinnedPersonRun>,
    pub(super) store: PgChunkStore,
    pub(super) scanner: PersonScanner,
    pub(super) producer: SeedTileProducer,
    pub(super) pacer: TilePacer,
    pub(super) producer_settings: ProducerSettings,
    pub(super) emission: PersonEmissionPolicy,
    pub(super) retry_backoff: RetryBackoffPolicy,
}

/// What one person chunk's fold came to, rendered on the `chunk confirmed` line so a run's shape is
/// legible without joining four counters.
#[derive(Debug, Default, Clone, Copy)]
pub(super) struct PersonChunkStats {
    pub(super) persons_scanned: u64,
    pub(super) nonmatchers: u64,
    pub(super) pruned: u64,
    pub(super) shortcut_evaluations: u64,
}

pub(super) async fn execute_person_chunk(
    ctx: PersonChunkTaskContext,
    shutdown: CancellationToken,
) -> ChunkOutcome {
    let PersonChunkTaskContext {
        chunk,
        lease,
        run,
        store,
        scanner,
        producer,
        pacer,
        producer_settings,
        emission,
        retry_backoff,
    } = ctx;
    let lease_cancel = lease.cancellation_token();

    // PreMark: stream the range scan, evaluating and enqueueing one seed per emitted person.
    let (streamed, inflight, stats) = match stream_chunk(
        chunk,
        &run,
        &scanner,
        &producer,
        &pacer,
        producer_settings,
        emission,
        &lease_cancel,
        &shutdown,
    )
    .await
    {
        Ok(triple) => triple,
        Err(halt) => return resolve_halt(&store, halt, &shutdown, retry_backoff).await,
    };
    // PreMark: CAS `scanning`→`produced` — the row is still `scanning` on failure.
    let enqueued = match store.mark_produced_streamed(streamed).await {
        Ok(enqueued) => enqueued,
        Err(halt) => {
            return resolve_halt(&store, mark_produced_halt(halt), &shutdown, retry_backoff).await
        }
    };
    // PostMark: drain the remaining delivery acks, then the terminal confirm.
    let produced = match deliver::await_deliveries(enqueued, inflight, &lease_cancel).await {
        Ok(produced) => produced,
        Err(halt) => return resolve_halt(&store, halt, &shutdown, retry_backoff).await,
    };
    let lease = produced.spec().lease;
    let seeds_produced = produced.tiles_produced();
    match store.confirm(produced).await {
        Ok(_) => ChunkOutcome::Confirmed {
            lease,
            tiles_produced: seeds_produced,
            detail: ConfirmedDetail::Person(stats),
        },
        Err(halt) => resolve_halt(&store, halt, &shutdown, retry_backoff).await,
    }
}

#[allow(clippy::too_many_arguments)]
async fn stream_chunk(
    chunk: ClaimedChunk,
    run: &Arc<PinnedPersonRun>,
    scanner: &PersonScanner,
    producer: &SeedTileProducer,
    pacer: &TilePacer,
    settings: ProducerSettings,
    emission: PersonEmissionPolicy,
    lease_cancel: &CancellationToken,
    shutdown: &CancellationToken,
) -> Result<(StreamedChunk, InFlight, PersonChunkStats), Halted<ClaimedChunk, PersonChunkError>> {
    let spec = match run.chunk_spec(&chunk.spec()) {
        Ok(spec) => spec,
        Err(error) => return Err(Halted::failed(chunk, PersonChunkError::Spec(error))),
    };
    let scan_spec = PersonScanSpec::new(
        spec.team_id,
        run.scan_since,
        spec.range,
        run.scan_key_filter(emission),
    );
    counter!(PERSON_SCAN_FILTER, "outcome" => scan_spec.filter_outcome().as_str()).increment(1);
    let mut cursor = match scanner.scan_rows(&scan_spec, chunk.spec()) {
        Ok(cursor) => cursor,
        Err(error) => return Err(Halted::failed(chunk, PersonChunkError::Scan(error))),
    };
    let mut evaluator = PersonEvaluator::new(run, emission);
    let seed_ctx = PersonSeedContext {
        scanned_at: spec.scanned_at,
        run_id: spec.lease.run_id(),
        claim_epoch: spec.lease.epoch(),
    };
    let mut inflight = InFlight::new(settings.max_inflight.get());
    let mut stats = PersonChunkStats::default();
    let mut seeds_produced: u64 = 0;
    // Started after setup so the spec/cursor early returns don't seed the histogram with
    // near-zero samples.
    let _timer = MetricTimer::start(PERSON_CHUNK_SCAN_DURATION_SECONDS);

    // Every way out of the fold funnels back here, so the volume is metered once whether the scan
    // finished, was cancelled, or failed mid-stream.
    let folded = fold_person_rows(
        &mut cursor,
        &mut evaluator,
        &seed_ctx,
        producer,
        &mut inflight,
        pacer,
        settings,
        &mut stats,
        &mut seeds_produced,
        lease_cancel,
        shutdown,
    )
    .await;
    let volume = scan_volume::observe(ScanKind::Person, &cursor);
    match folded {
        Ok(()) => Ok((chunk.into_streamed(seeds_produced, volume), inflight, stats)),
        Err(stop) => Err(stop.into_halt(chunk)),
    }
}

/// Drive the person cursor into the evaluator and the paced producer until it is exhausted,
/// cancelled, or fails. Returns rather than metering, so the caller owns the single recording site.
#[allow(clippy::too_many_arguments)]
async fn fold_person_rows(
    cursor: &mut RowCursor<PersonRow>,
    evaluator: &mut PersonEvaluator,
    seed_ctx: &PersonSeedContext,
    producer: &SeedTileProducer,
    inflight: &mut InFlight,
    pacer: &TilePacer,
    settings: ProducerSettings,
    stats: &mut PersonChunkStats,
    seeds_produced: &mut u64,
    lease_cancel: &CancellationToken,
    shutdown: &CancellationToken,
) -> Result<(), PersonStreamStop> {
    loop {
        let row = tokio::select! {
            biased;
            _ = shutdown.cancelled() => {
                return Err(PersonStreamStop::Cancelled(CancelCause::Shutdown));
            }
            _ = lease_cancel.cancelled() => {
                return Err(PersonStreamStop::Cancelled(CancelCause::LeaseLost));
            }
            row = cursor.next() => match row {
                Ok(row) => row,
                Err(error) => {
                    return Err(PersonStreamStop::Failed(PersonChunkError::Cursor(error)));
                }
            },
        };
        let Some(row) = row else {
            return Ok(());
        };
        counter!(PERSONS_SCANNED).increment(1);
        stats.persons_scanned += 1;
        let (outcome, row_stats) = evaluator.evaluate_row(&row.id, &row.properties, seed_ctx);
        stats.shortcut_evaluations += u64::from(row_stats.shortcut_evaluations);
        record_row_stats(row_stats);
        match outcome {
            PersonRowOutcome::Seed(seed) => {
                if let Err(stop) = deliver::enqueue_one(
                    || producer.enqueue_person(&seed),
                    inflight,
                    pacer,
                    settings,
                    lease_cancel,
                    shutdown,
                )
                .await
                {
                    return Err(stop.into());
                }
                *seeds_produced += 1;
                counter!(PERSON_SEEDS_PRODUCED).increment(1);
            }
            PersonRowOutcome::NonMatcher => {
                stats.nonmatchers += 1;
                counter!(PERSON_NONMATCHERS_SKIPPED).increment(1);
            }
            PersonRowOutcome::Irrelevant => {
                stats.pruned += 1;
                counter!(PERSON_ROWS_PRUNED, "reason" => PRUNE_REASON_IRRELEVANT).increment(1);
            }
            PersonRowOutcome::Skipped(skip) => {
                counter!(PERSON_ROWS_SKIPPED, "reason" => skip.as_str()).increment(1);
            }
        }
    }
}

/// Why the person fold stopped, carried without the chunk so the caller can meter the cursor before
/// giving the chunk up to [`Halted`].
enum PersonStreamStop {
    Cancelled(CancelCause),
    Failed(PersonChunkError),
}

impl PersonStreamStop {
    fn into_halt(self, chunk: ClaimedChunk) -> Halted<ClaimedChunk, PersonChunkError> {
        match self {
            Self::Cancelled(cause) => Halted::cancelled(chunk, cause),
            Self::Failed(error) => Halted::failed(chunk, error),
        }
    }
}

impl From<ProduceStop> for PersonStreamStop {
    fn from(stop: ProduceStop) -> Self {
        match stop {
            ProduceStop::Cancelled(cause) => Self::Cancelled(cause),
            ProduceStop::Failed(error) => Self::Failed(PersonChunkError::Produce(error)),
        }
    }
}

fn record_row_stats(stats: RecordStats) {
    if stats.shortcut_evaluations > 0 {
        counter!(PERSON_CONDITIONS_SHORTCUT).increment(u64::from(stats.shortcut_evaluations));
    }
    if stats.unknown_functions > 0 {
        counter!(PERSON_HOGVM_ERRORS, "class" => VmErrorClass::UnknownFunction.as_str())
            .increment(u64::from(stats.unknown_functions));
    }
    for (class, count) in stats.vm_failures.iter().filter(|(_, count)| *count > 0) {
        counter!(PERSON_HOGVM_ERRORS, "class" => class.as_str()).increment(u64::from(count));
    }
}

#[derive(Debug, thiserror::Error)]
enum PersonChunkError {
    #[error("resolving the person chunk spec")]
    Spec(#[from] PersonChunkSpecError),
    #[error(transparent)]
    Scan(#[from] PersonScanError),
    #[error("streaming ClickHouse person scan cursor")]
    Cursor(#[source] clickhouse::error::Error),
    #[error(transparent)]
    Produce(ProduceError),
}
