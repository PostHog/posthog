//! App layer: one chunk's `scan → enqueue → mark → await → confirm` pipeline and the single recovery
//! resolver. Depends on `clickhouse`, `kafka`, `store`, `domain`, and its `app` siblings.
//!
//! The store's `mark_produced` sits between the two deliver phases: deliver owns Kafka, execute owns
//! the store gating. Every halt funnels through [`resolve_halt`], which applies the exact recovery
//! matrix — a pre-mark halt during shutdown unclaims (no attempt spent); everything else fails for
//! retry — encoded once in [`FailureDisposition::resolve`] and pinned by its unit test.

use std::sync::Arc;

use metrics::counter;
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::clickhouse::scanner::ChunkScanner;
use crate::domain::{
    ChunkLease, ChunkSpec, ClaimedChunk, EnqueuedChunk, HaltReason, Halted, PinnedRun,
    ProducedChunk, ScannedChunk,
};
use crate::kafka::pacing::TilePacer;
use crate::kafka::producer::SeedTileProducer;
use crate::observability::metrics::{CHUNKS_CONFIRMED, CHUNKS_FAILED};
use crate::store::chunks::{ChunkStoreError, PgChunkStore};
use crate::store::lease::LeaseHandle;
use crate::store::RenderedError;

use super::deliver::{self, ProduceError};
use super::settings::ProducerSettings;

/// The owned inputs to one chunk's processing task, bundled so the spawn stays tidy.
pub(super) struct ChunkTaskContext {
    pub(super) chunk: ClaimedChunk,
    pub(super) lease: LeaseHandle,
    pub(super) run: Arc<PinnedRun>,
    pub(super) store: PgChunkStore,
    pub(super) scanner: ChunkScanner,
    pub(super) producer: SeedTileProducer,
    pub(super) pacer: TilePacer,
    pub(super) producer_settings: ProducerSettings,
}

pub(super) async fn execute_chunk(
    ctx: ChunkTaskContext,
    shutdown: CancellationToken,
) -> ChunkOutcome {
    let ChunkTaskContext {
        chunk,
        lease,
        run,
        store,
        scanner,
        producer,
        pacer,
        producer_settings,
    } = ctx;
    let lease_cancel = lease.cancellation_token();

    // PreMark: scan history into tiles.
    let scanned = match scanner.scan(chunk, &run, &lease_cancel, &shutdown).await {
        Ok(scanned) => scanned,
        Err(halt) => return resolve_halt(&store, halt, &shutdown).await,
    };
    // PreMark: pace and enqueue every tile, holding the in-flight deliveries.
    let (scanned, inflight) = match deliver::enqueue_tiles(
        &producer,
        scanned,
        &pacer,
        producer_settings,
        &lease_cancel,
        &shutdown,
    )
    .await
    {
        Ok(pair) => pair,
        Err(halt) => return resolve_halt(&store, halt, &shutdown).await,
    };
    // PreMark: CAS `scanning`→`produced` — the row is still `scanning` on failure.
    let enqueued = match store.mark_produced(scanned).await {
        Ok(enqueued) => enqueued,
        Err(halt) => return resolve_halt(&store, mark_produced_halt(halt), &shutdown).await,
    };
    // PostMark: drain the remaining delivery acks and fold the high-water marks.
    let produced = match deliver::await_deliveries(enqueued, inflight, &lease_cancel).await {
        Ok(produced) => produced,
        Err(halt) => return resolve_halt(&store, halt, &shutdown).await,
    };
    // PostMark: the terminal confirm — on failure the row is `produced`, so it is failed for retry.
    let lease = produced.spec().lease;
    let tiles_produced = produced.tiles_produced();
    match store.confirm(produced).await {
        Ok(_) => ChunkOutcome::Confirmed {
            lease,
            tiles_produced,
        },
        Err(halt) => resolve_halt(&store, halt, &shutdown).await,
    }
}

/// Whether a halt struck before or after the store marked the chunk `produced` — the discriminator
/// the recovery matrix turns on. Each chunk state names its stage as a `const` via [`ChunkState`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum FailureStage {
    PreMark,
    PostMark,
}

/// The pipeline states seen by recovery: their [`FailureStage`] and their lease-bearing spec.
trait ChunkState {
    const STAGE: FailureStage;
    fn spec(&self) -> ChunkSpec;
}

impl ChunkState for ClaimedChunk {
    const STAGE: FailureStage = FailureStage::PreMark;
    fn spec(&self) -> ChunkSpec {
        self.spec()
    }
}

impl ChunkState for ScannedChunk {
    const STAGE: FailureStage = FailureStage::PreMark;
    fn spec(&self) -> ChunkSpec {
        self.spec()
    }
}

impl ChunkState for EnqueuedChunk {
    const STAGE: FailureStage = FailureStage::PostMark;
    fn spec(&self) -> ChunkSpec {
        self.spec()
    }
}

impl ChunkState for ProducedChunk {
    const STAGE: FailureStage = FailureStage::PostMark;
    fn spec(&self) -> ChunkSpec {
        self.spec()
    }
}

/// The recovery decision: unclaim the chunk (refunding the attempt) or fail it for retry.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum FailureDisposition {
    Unclaim,
    Fail,
}

impl FailureDisposition {
    /// Today's exact matrix: a pre-mark halt during shutdown unclaims; every other case fails —
    /// post-mark never unclaims, since the row is already `produced`.
    const fn resolve(stage: FailureStage, shutting_down: bool) -> Self {
        match (stage, shutting_down) {
            (FailureStage::PreMark, true) => Self::Unclaim,
            (FailureStage::PreMark, false) => Self::Fail,
            (FailureStage::PostMark, _) => Self::Fail,
        }
    }
}

/// Apply the recovery matrix to a halted state: render the operator detail, decide the disposition
/// from the state's stage and the shutdown flag, and drive the fencing store write.
async fn resolve_halt<S: ChunkState, E: std::error::Error>(
    store: &PgChunkStore,
    halt: Halted<S, E>,
    shutdown: &CancellationToken,
) -> ChunkOutcome {
    let lease = halt.state.spec().lease;
    let detail = render_reason(&halt.reason);
    match FailureDisposition::resolve(S::STAGE, shutdown.is_cancelled()) {
        FailureDisposition::Unclaim => match store.unclaim(lease).await {
            Ok(()) => ChunkOutcome::Unclaimed { lease },
            Err(recovery) => ChunkOutcome::RecoveryFailed {
                lease,
                detail: detail.as_str().to_string(),
                recovery,
            },
        },
        FailureDisposition::Fail => match store.fail(lease, &detail).await {
            Ok(()) => ChunkOutcome::Failed {
                lease,
                detail: detail.as_str().to_string(),
            },
            Err(recovery) => ChunkOutcome::RecoveryFailed {
                lease,
                detail: detail.as_str().to_string(),
                recovery,
            },
        },
    }
}

/// Re-wrap the store's mark error as the produce error the recovery path renders, preserving the
/// persisted `marking the chunk produced failed: …` text while the store stays store-typed.
fn mark_produced_halt(
    halt: Halted<ScannedChunk, ChunkStoreError>,
) -> Halted<ScannedChunk, ProduceError> {
    let Halted { state, reason } = halt;
    let reason = match reason {
        HaltReason::Failed(error) => HaltReason::Failed(ProduceError::MarkProduced(error)),
        HaltReason::Cancelled(cause) => HaltReason::Cancelled(cause),
    };
    Halted { state, reason }
}

fn render_reason<E: std::error::Error>(reason: &HaltReason<E>) -> RenderedError {
    match reason {
        HaltReason::Failed(error) => RenderedError::render(error),
        HaltReason::Cancelled(cause) => RenderedError::from_message(cause.as_str()),
    }
}

#[derive(Debug)]
pub(super) enum ChunkOutcome {
    Confirmed {
        lease: ChunkLease,
        tiles_produced: u64,
    },
    Failed {
        lease: ChunkLease,
        detail: String,
    },
    Unclaimed {
        lease: ChunkLease,
    },
    RecoveryFailed {
        lease: ChunkLease,
        detail: String,
        recovery: ChunkStoreError,
    },
}

pub(super) fn record_task_result(result: Result<ChunkOutcome, tokio::task::JoinError>) {
    match result {
        Ok(ChunkOutcome::Confirmed {
            lease,
            tiles_produced,
        }) => {
            counter!(CHUNKS_CONFIRMED).increment(1);
            info!(?lease, tiles_produced, "chunk confirmed");
        }
        Ok(ChunkOutcome::Failed { lease, detail }) => {
            counter!(CHUNKS_FAILED).increment(1);
            warn!(?lease, error = %detail, "chunk failed and was released for retry");
        }
        Ok(ChunkOutcome::Unclaimed { lease }) => {
            info!(?lease, "chunk unclaimed during shutdown");
        }
        Ok(ChunkOutcome::RecoveryFailed {
            lease,
            detail,
            recovery,
        }) => {
            counter!(CHUNKS_FAILED).increment(1);
            warn!(?lease, error = %detail, recovery_error = %recovery, "chunk recovery update did not apply");
        }
        Err(error) => {
            counter!(CHUNKS_FAILED).increment(1);
            warn!(error = %error, "chunk task failed unexpectedly");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn failure_disposition_encodes_the_recovery_matrix() {
        assert_eq!(
            FailureDisposition::resolve(FailureStage::PreMark, true),
            FailureDisposition::Unclaim
        );
        assert_eq!(
            FailureDisposition::resolve(FailureStage::PreMark, false),
            FailureDisposition::Fail
        );
        assert_eq!(
            FailureDisposition::resolve(FailureStage::PostMark, true),
            FailureDisposition::Fail
        );
        assert_eq!(
            FailureDisposition::resolve(FailureStage::PostMark, false),
            FailureDisposition::Fail
        );
    }
}
