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

use crate::clickhouse::person_scanner::{PersonScanError, PersonScanner};
use crate::clickhouse::person_sql::PersonScanSpec;
use crate::domain::{
    CancelCause, ClaimedChunk, Halted, PersonChunkSpecError, PersonEvaluator, PersonRowOutcome,
    PersonSeedContext, PinnedPersonRun, RecordStats, StreamedChunk,
};
use crate::kafka::pacing::TilePacer;
use crate::kafka::producer::SeedTileProducer;
use crate::observability::metrics::{
    MetricTimer, PERSONS_SCANNED, PERSON_CHUNK_SCAN_DURATION_SECONDS, PERSON_HOGVM_ERRORS,
    PERSON_NONMATCHERS_SKIPPED, PERSON_ROWS_SKIPPED, PERSON_SEEDS_PRODUCED,
};
use crate::store::chunks::PgChunkStore;
use crate::store::lease::LeaseHandle;

use super::deliver::{self, InFlight, ProduceError, ProduceStop};
use super::execute::{mark_produced_halt, resolve_halt, ChunkOutcome};
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
    pub(super) emit_nonmatchers: bool,
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
        emit_nonmatchers,
    } = ctx;
    let lease_cancel = lease.cancellation_token();

    // PreMark: stream the range scan, evaluating and enqueueing one seed per emitted person.
    let (streamed, inflight) = match stream_chunk(
        chunk,
        &run,
        &scanner,
        &producer,
        &pacer,
        producer_settings,
        emit_nonmatchers,
        &lease_cancel,
        &shutdown,
    )
    .await
    {
        Ok(pair) => pair,
        Err(halt) => return resolve_halt(&store, halt, &shutdown).await,
    };
    // PreMark: CAS `scanning`→`produced` — the row is still `scanning` on failure.
    let enqueued = match store.mark_produced_streamed(streamed).await {
        Ok(enqueued) => enqueued,
        Err(halt) => return resolve_halt(&store, mark_produced_halt(halt), &shutdown).await,
    };
    // PostMark: drain the remaining delivery acks, then the terminal confirm.
    let produced = match deliver::await_deliveries(enqueued, inflight, &lease_cancel).await {
        Ok(produced) => produced,
        Err(halt) => return resolve_halt(&store, halt, &shutdown).await,
    };
    let lease = produced.spec().lease;
    let seeds_produced = produced.tiles_produced();
    match store.confirm(produced).await {
        Ok(_) => ChunkOutcome::Confirmed {
            lease,
            tiles_produced: seeds_produced,
        },
        Err(halt) => resolve_halt(&store, halt, &shutdown).await,
    }
}

#[allow(clippy::too_many_arguments)]
async fn stream_chunk(
    chunk: ClaimedChunk,
    run: &PinnedPersonRun,
    scanner: &PersonScanner,
    producer: &SeedTileProducer,
    pacer: &TilePacer,
    settings: ProducerSettings,
    emit_nonmatchers: bool,
    lease_cancel: &CancellationToken,
    shutdown: &CancellationToken,
) -> Result<(StreamedChunk, InFlight), Halted<ClaimedChunk, PersonChunkError>> {
    let spec = match run.chunk_spec(&chunk.spec()) {
        Ok(spec) => spec,
        Err(error) => return Err(Halted::failed(chunk, PersonChunkError::Spec(error))),
    };
    let scan_spec = PersonScanSpec::new(spec.team_id, run.scan_since, spec.range);
    let mut cursor = match scanner.scan_rows(&scan_spec) {
        Ok(cursor) => cursor,
        Err(error) => return Err(Halted::failed(chunk, PersonChunkError::Scan(error))),
    };
    let mut evaluator =
        PersonEvaluator::new(spec.team_id, run.conditions.clone(), emit_nonmatchers);
    let seed_ctx = PersonSeedContext {
        scanned_at: spec.scanned_at,
        run_id: spec.lease.run_id(),
        claim_epoch: spec.lease.epoch(),
    };
    let mut inflight = InFlight::new(settings.max_inflight.get());
    let mut seeds_produced: u64 = 0;
    // Started after setup so the spec/cursor early returns don't seed the histogram with
    // near-zero samples.
    let _timer = MetricTimer::start(PERSON_CHUNK_SCAN_DURATION_SECONDS);

    loop {
        let row = tokio::select! {
            biased;
            _ = shutdown.cancelled() => {
                return Err(Halted::cancelled(chunk, CancelCause::Shutdown));
            }
            _ = lease_cancel.cancelled() => {
                return Err(Halted::cancelled(chunk, CancelCause::LeaseLost));
            }
            row = cursor.next() => match row {
                Ok(row) => row,
                Err(error) => {
                    return Err(Halted::failed(chunk, PersonChunkError::Cursor(error)));
                }
            },
        };
        let Some(row) = row else {
            break;
        };
        counter!(PERSONS_SCANNED).increment(1);
        let (outcome, stats) = evaluator.evaluate_row(&row.id, &row.properties, &seed_ctx);
        record_row_stats(stats);
        match outcome {
            PersonRowOutcome::Seed(seed) => {
                if let Err(stop) = deliver::enqueue_one(
                    || producer.enqueue_person(&seed),
                    &mut inflight,
                    pacer,
                    settings,
                    lease_cancel,
                    shutdown,
                )
                .await
                {
                    return Err(produce_halt(chunk, stop));
                }
                seeds_produced += 1;
                counter!(PERSON_SEEDS_PRODUCED).increment(1);
            }
            PersonRowOutcome::NonMatcher => {
                counter!(PERSON_NONMATCHERS_SKIPPED).increment(1);
            }
            PersonRowOutcome::Skipped(skip) => {
                counter!(PERSON_ROWS_SKIPPED, "reason" => skip.as_str()).increment(1);
            }
        }
    }

    Ok((chunk.into_streamed(seeds_produced), inflight))
}

fn produce_halt(chunk: ClaimedChunk, stop: ProduceStop) -> Halted<ClaimedChunk, PersonChunkError> {
    match stop {
        ProduceStop::Cancelled(cause) => Halted::cancelled(chunk, cause),
        ProduceStop::Failed(error) => Halted::failed(chunk, PersonChunkError::Produce(error)),
    }
}

fn record_row_stats(stats: RecordStats) {
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
