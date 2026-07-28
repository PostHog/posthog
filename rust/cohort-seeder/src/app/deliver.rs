//! App layer, Kafka produce sequencing: the two-phase enqueue/await split. Depends on `domain`,
//! `kafka`, `store`, and `app::settings`; never imported by a lower layer.
//!
//! The sequence `enqueue_tiles → store.mark_produced → await_deliveries` (composed by `execute`) is
//! byte-equivalent to the former monolithic produce: enqueue every tile honoring the in-flight bound
//! and draining overflow acks before the mark, then drain the remaining acks after it, folding all
//! delivery high-water marks into one accumulator carried across the mark by [`InFlight`].

use std::collections::VecDeque;
use std::time::{Duration, Instant};

use metrics::{counter, histogram};
use rdkafka::error::KafkaError;
use rdkafka::producer::DeliveryFuture;
use tokio_util::sync::CancellationToken;

use crate::domain::{CancelCause, EnqueuedChunk, Halted, ProduceHwms, ProducedChunk, ScannedChunk};
use crate::kafka::pacing::TilePacer;
use crate::kafka::producer::{EnqueueError, SeedTileProducer};
use crate::observability::metrics::{
    PRODUCE_ACK_SECONDS, TILES_PRODUCED, TILE_PRODUCE_ERRORS, TILE_PRODUCE_QUEUE_FULL,
};
use crate::store::chunks::ChunkStoreError;

use super::settings::ProducerSettings;

/// The ceiling the queue-full backoff doubles up to; also clamps [`ProducerSettings`] at construction.
pub(super) const QUEUE_FULL_BACKOFF_CAP: Duration = Duration::from_secs(5);

/// The pending deliveries and folded high-water marks handed from the pre-mark enqueue phase to the
/// post-mark await phase, so both phases fold into the same accumulator in the same order.
pub(super) struct InFlight {
    pending: VecDeque<PendingDelivery>,
    hwms: ProduceHwms,
}

/// Phase one (pre-mark): pace and enqueue every tile honoring the in-flight bound, draining overflow
/// acks into the HWMs. Returns the still-`scanning` chunk (for the store's mark) plus the in-flight
/// deliveries. Every error hands the [`ScannedChunk`] back so the caller can release or fail it.
pub(super) async fn enqueue_tiles(
    producer: &SeedTileProducer,
    chunk: ScannedChunk,
    pacer: &TilePacer,
    settings: ProducerSettings,
    lease_cancel: &CancellationToken,
    shutdown: &CancellationToken,
) -> Result<(ScannedChunk, InFlight), Halted<ScannedChunk, ProduceError>> {
    let mut pending = VecDeque::with_capacity(settings.max_inflight.get());
    let mut hwms = ProduceHwms::default();

    for tile in chunk.tiles() {
        if let Err(cause) = wait_for_pacer(pacer, shutdown, lease_cancel).await {
            return Err(Halted::cancelled(chunk, cause));
        }
        let mut backoff = settings.queue_full_backoff;
        loop {
            match producer.enqueue(tile) {
                Ok(delivery) => {
                    pending.push_back(PendingDelivery {
                        delivery,
                        sent_at: Instant::now(),
                    });
                    break;
                }
                Err(EnqueueError::QueueFull) => {
                    counter!(TILE_PRODUCE_QUEUE_FULL).increment(1);
                    if let Err(cause) = wait_for_backoff(backoff, shutdown, lease_cancel).await {
                        return Err(Halted::cancelled(chunk, cause));
                    }
                    backoff = next_queue_full_backoff(backoff);
                }
                Err(EnqueueError::Fatal(error)) => {
                    counter!(TILE_PRODUCE_ERRORS).increment(1);
                    return Err(Halted::failed(chunk, ProduceError::Enqueue(error)));
                }
            }
        }

        if pending.len() >= settings.max_inflight.get() {
            let delivery = pending
                .pop_front()
                .expect("the in-flight bound guarantees one delivery");
            if let Err(stop) =
                observe_delivery_before_mark(delivery, &mut hwms, shutdown, lease_cancel).await
            {
                counter!(TILE_PRODUCE_ERRORS).increment(1);
                return Err(stop.into_halted(chunk));
            }
        }
    }

    Ok((chunk, InFlight { pending, hwms }))
}

/// Phase two (post-mark): drain the remaining acks into the HWMs, fold them onto the marked chunk,
/// and emit `TILES_PRODUCED`. A delivery failure hands the [`EnqueuedChunk`] back for fail-on-retry.
pub(super) async fn await_deliveries(
    enqueued: EnqueuedChunk,
    inflight: InFlight,
    lease_cancel: &CancellationToken,
) -> Result<ProducedChunk, Halted<EnqueuedChunk, ProduceError>> {
    let InFlight {
        mut pending,
        mut hwms,
    } = inflight;

    while let Some(delivery) = pending.pop_front() {
        if let Err(stop) = observe_delivery_after_mark(delivery, &mut hwms, lease_cancel).await {
            counter!(TILE_PRODUCE_ERRORS).increment(1);
            return Err(stop.into_halted(enqueued));
        }
    }

    let produced = enqueued.into_produced(hwms);
    counter!(TILES_PRODUCED).increment(produced.tiles_produced());
    Ok(produced)
}

struct PendingDelivery {
    delivery: DeliveryFuture,
    sent_at: Instant,
}

/// A stop signal from awaiting one delivery: a cancellation cause or a terminal delivery error.
enum ProduceStop {
    Cancelled(CancelCause),
    Failed(ProduceError),
}

impl ProduceStop {
    fn into_halted<S>(self, state: S) -> Halted<S, ProduceError> {
        match self {
            Self::Cancelled(cause) => Halted::cancelled(state, cause),
            Self::Failed(error) => Halted::failed(state, error),
        }
    }
}

async fn observe_delivery_before_mark(
    mut pending: PendingDelivery,
    hwms: &mut ProduceHwms,
    shutdown: &CancellationToken,
    lease_cancel: &CancellationToken,
) -> Result<(), ProduceStop> {
    let result = tokio::select! {
        biased;
        _ = shutdown.cancelled() => Err(ProduceStop::Cancelled(CancelCause::Shutdown)),
        _ = lease_cancel.cancelled() => Err(ProduceStop::Cancelled(CancelCause::LeaseLost)),
        delivery = resolve_delivery(&mut pending, hwms) => delivery.map_err(ProduceStop::Failed),
    };
    histogram!(PRODUCE_ACK_SECONDS).record(pending.sent_at.elapsed().as_secs_f64());
    result
}

async fn observe_delivery_after_mark(
    mut pending: PendingDelivery,
    hwms: &mut ProduceHwms,
    lease_cancel: &CancellationToken,
) -> Result<(), ProduceStop> {
    let result = tokio::select! {
        biased;
        _ = lease_cancel.cancelled() => Err(ProduceStop::Cancelled(CancelCause::LeaseLost)),
        delivery = resolve_delivery(&mut pending, hwms) => delivery.map_err(ProduceStop::Failed),
    };
    histogram!(PRODUCE_ACK_SECONDS).record(pending.sent_at.elapsed().as_secs_f64());
    result
}

async fn resolve_delivery(
    pending: &mut PendingDelivery,
    hwms: &mut ProduceHwms,
) -> Result<(), ProduceError> {
    match (&mut pending.delivery).await {
        Ok(Ok((partition, offset))) => {
            hwms.observe(partition, offset);
            Ok(())
        }
        Ok(Err((error, _))) => Err(ProduceError::Delivery(error)),
        Err(_) => Err(ProduceError::Delivery(KafkaError::Canceled)),
    }
}

async fn wait_for_pacer(
    pacer: &TilePacer,
    shutdown: &CancellationToken,
    lease_cancel: &CancellationToken,
) -> Result<(), CancelCause> {
    tokio::select! {
        biased;
        _ = shutdown.cancelled() => Err(CancelCause::Shutdown),
        _ = lease_cancel.cancelled() => Err(CancelCause::LeaseLost),
        _ = pacer.until_ready() => Ok(()),
    }
}

async fn wait_for_backoff(
    backoff: Duration,
    shutdown: &CancellationToken,
    lease_cancel: &CancellationToken,
) -> Result<(), CancelCause> {
    tokio::select! {
        biased;
        _ = shutdown.cancelled() => Err(CancelCause::Shutdown),
        _ = lease_cancel.cancelled() => Err(CancelCause::LeaseLost),
        _ = tokio::time::sleep(backoff) => Ok(()),
    }
}

fn next_queue_full_backoff(current: Duration) -> Duration {
    current.saturating_mul(2).min(QUEUE_FULL_BACKOFF_CAP)
}

#[derive(Debug, thiserror::Error)]
pub(super) enum ProduceError {
    #[error("fatal tile enqueue error: {0}")]
    Enqueue(KafkaError),
    #[error("tile delivery failed: {0}")]
    Delivery(KafkaError),
    #[error("marking the chunk produced failed")]
    MarkProduced(#[source] ChunkStoreError),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn queue_full_backoff_doubles_and_caps() {
        assert_eq!(
            next_queue_full_backoff(Duration::from_secs(4)),
            QUEUE_FULL_BACKOFF_CAP
        );
        assert_eq!(
            next_queue_full_backoff(QUEUE_FULL_BACKOFF_CAP),
            QUEUE_FULL_BACKOFF_CAP
        );
    }
}
