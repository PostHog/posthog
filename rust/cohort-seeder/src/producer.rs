use std::collections::VecDeque;
use std::fmt;
use std::num::NonZeroUsize;
use std::time::{Duration, Instant};

use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{create_kafka_producer, KafkaContext};
use common_liveness::SyncLivenessReporter;
use metrics::{counter, histogram};
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::producer::{DeliveryFuture, FutureProducer, FutureRecord, Producer};
use tokio_util::sync::CancellationToken;

use crate::chunks::{EnqueuedChunk, ProduceHwms, ProducedChunk, ScannedChunk};
use crate::observability::metrics::{
    PRODUCE_ACK_SECONDS, TILES_PRODUCED, TILE_PRODUCE_ERRORS, TILE_PRODUCE_QUEUE_FULL,
};
use crate::pacing::TilePacer;
use crate::tile::SeedTile;

const QUEUE_FULL_BACKOFF_CAP: Duration = Duration::from_secs(5);

#[derive(Debug, thiserror::Error)]
pub enum EnqueueError {
    #[error("producer queue full")]
    QueueFull,
    #[error("fatal enqueue error: {0}")]
    Fatal(KafkaError),
}

impl From<KafkaError> for EnqueueError {
    fn from(error: KafkaError) -> Self {
        match error {
            KafkaError::MessageProduction(RDKafkaErrorCode::QueueFull) => Self::QueueFull,
            other => Self::Fatal(other),
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct ProducerSettings {
    max_inflight: NonZeroUsize,
    queue_full_backoff: Duration,
}

impl ProducerSettings {
    pub fn new(
        max_inflight: usize,
        queue_full_backoff: Duration,
    ) -> Result<Self, ProducerSettingsError> {
        let max_inflight =
            NonZeroUsize::new(max_inflight).ok_or(ProducerSettingsError::ZeroMaxInflight)?;
        if queue_full_backoff.is_zero() {
            return Err(ProducerSettingsError::ZeroQueueFullBackoff);
        }
        Ok(Self {
            max_inflight,
            queue_full_backoff: queue_full_backoff.min(QUEUE_FULL_BACKOFF_CAP),
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum ProducerSettingsError {
    #[error("maximum in-flight tiles must be greater than zero")]
    ZeroMaxInflight,
    #[error("queue-full backoff must be greater than zero")]
    ZeroQueueFullBackoff,
}

#[derive(Clone)]
pub struct SeedTileProducer {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl SeedTileProducer {
    pub async fn new(kafka_config: &KafkaConfig, topic: String) -> Result<Self, KafkaError> {
        let producer = create_kafka_producer(kafka_config, AlwaysHealthy).await?;
        Ok(Self { producer, topic })
    }

    pub fn enqueue(&self, tile: &SeedTile) -> Result<DeliveryFuture, EnqueueError> {
        let payload = serde_json::to_vec(tile).expect("SeedTile serialization cannot fail");
        let key = tile.partition_key();
        let record = FutureRecord::to(&self.topic).key(&key).payload(&payload);
        self.producer
            .send_result(record)
            .map_err(|(error, _)| error.into())
    }

    pub async fn produce(
        &self,
        chunk: ScannedChunk,
        pacer: &TilePacer,
        settings: ProducerSettings,
        shutdown: &CancellationToken,
    ) -> Result<ProducedChunk, ProduceFailure> {
        let lease_cancelled = chunk.cancellation_token();
        let mut pending = VecDeque::with_capacity(settings.max_inflight.get());
        let mut hwms = ProduceHwms::default();

        for tile in chunk.tiles() {
            if wait_for_pacer(pacer, shutdown, &lease_cancelled)
                .await
                .is_err()
            {
                return Err(ProduceFailure::BeforeMark {
                    chunk,
                    source: ProduceError::Cancelled,
                });
            }
            let mut backoff = settings.queue_full_backoff;
            loop {
                match self.enqueue(tile) {
                    Ok(delivery) => {
                        pending.push_back(PendingDelivery {
                            delivery,
                            sent_at: Instant::now(),
                        });
                        break;
                    }
                    Err(EnqueueError::QueueFull) => {
                        counter!(TILE_PRODUCE_QUEUE_FULL).increment(1);
                        if wait_for_backoff(backoff, shutdown, &lease_cancelled)
                            .await
                            .is_err()
                        {
                            return Err(ProduceFailure::BeforeMark {
                                chunk,
                                source: ProduceError::Cancelled,
                            });
                        }
                        backoff = next_queue_full_backoff(backoff);
                    }
                    Err(EnqueueError::Fatal(error)) => {
                        counter!(TILE_PRODUCE_ERRORS).increment(1);
                        return Err(ProduceFailure::BeforeMark {
                            chunk,
                            source: ProduceError::Enqueue(error),
                        });
                    }
                }
            }

            if pending.len() >= settings.max_inflight.get() {
                let delivery = pending
                    .pop_front()
                    .expect("the in-flight bound guarantees one delivery");
                if let Err(source) =
                    observe_delivery_before_mark(delivery, &mut hwms, shutdown, &lease_cancelled)
                        .await
                {
                    counter!(TILE_PRODUCE_ERRORS).increment(1);
                    return Err(ProduceFailure::BeforeMark { chunk, source });
                }
            }
        }

        let enqueued = match chunk.mark_enqueued().await {
            Ok(enqueued) => enqueued,
            Err(failure) => {
                let (chunk, source) = failure.into_parts();
                return Err(ProduceFailure::BeforeMark {
                    chunk,
                    source: ProduceError::MarkProduced(source),
                });
            }
        };

        while let Some(delivery) = pending.pop_front() {
            if let Err(source) =
                observe_delivery_after_mark(delivery, &mut hwms, &lease_cancelled).await
            {
                counter!(TILE_PRODUCE_ERRORS).increment(1);
                return Err(ProduceFailure::AfterMark {
                    chunk: enqueued,
                    source,
                });
            }
        }

        let produced = enqueued.finish_deliveries(hwms);
        counter!(TILES_PRODUCED).increment(produced.tiles_produced());
        Ok(produced)
    }

    pub fn flush(&self, timeout: Duration) -> Result<(), KafkaError> {
        self.producer.flush(timeout)
    }
}

#[derive(Clone, Copy)]
struct AlwaysHealthy;

impl SyncLivenessReporter for AlwaysHealthy {
    fn report_healthy(&self) {}

    fn report_unhealthy(&self) {}
}

struct PendingDelivery {
    delivery: DeliveryFuture,
    sent_at: Instant,
}

async fn observe_delivery_before_mark(
    mut pending: PendingDelivery,
    hwms: &mut ProduceHwms,
    shutdown: &CancellationToken,
    lease_cancelled: &CancellationToken,
) -> Result<(), ProduceError> {
    let result = tokio::select! {
        biased;
        _ = shutdown.cancelled() => Err(ProduceError::Cancelled),
        _ = lease_cancelled.cancelled() => Err(ProduceError::Cancelled),
        delivery = resolve_delivery(&mut pending, hwms) => delivery,
    };
    histogram!(PRODUCE_ACK_SECONDS).record(pending.sent_at.elapsed().as_secs_f64());
    result
}

async fn observe_delivery_after_mark(
    mut pending: PendingDelivery,
    hwms: &mut ProduceHwms,
    lease_cancelled: &CancellationToken,
) -> Result<(), ProduceError> {
    let result = tokio::select! {
        biased;
        _ = lease_cancelled.cancelled() => Err(ProduceError::Cancelled),
        delivery = resolve_delivery(&mut pending, hwms) => delivery,
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
    lease_cancelled: &CancellationToken,
) -> Result<(), Cancelled> {
    tokio::select! {
        biased;
        _ = shutdown.cancelled() => Err(Cancelled),
        _ = lease_cancelled.cancelled() => Err(Cancelled),
        _ = pacer.until_ready() => Ok(()),
    }
}

async fn wait_for_backoff(
    backoff: Duration,
    shutdown: &CancellationToken,
    lease_cancelled: &CancellationToken,
) -> Result<(), Cancelled> {
    tokio::select! {
        biased;
        _ = shutdown.cancelled() => Err(Cancelled),
        _ = lease_cancelled.cancelled() => Err(Cancelled),
        _ = tokio::time::sleep(backoff) => Ok(()),
    }
}

fn next_queue_full_backoff(current: Duration) -> Duration {
    current.saturating_mul(2).min(QUEUE_FULL_BACKOFF_CAP)
}

#[derive(Debug, Clone, Copy)]
struct Cancelled;

#[derive(Debug, thiserror::Error)]
pub enum ProduceError {
    #[error("tile production was cancelled")]
    Cancelled,
    #[error("fatal tile enqueue error: {0}")]
    Enqueue(KafkaError),
    #[error("tile delivery failed: {0}")]
    Delivery(KafkaError),
    #[error("marking the chunk produced failed: {0}")]
    MarkProduced(crate::chunks::ChunkError),
}

pub enum ProduceFailure {
    BeforeMark {
        chunk: ScannedChunk,
        source: ProduceError,
    },
    AfterMark {
        chunk: EnqueuedChunk,
        source: ProduceError,
    },
}

impl fmt::Debug for ProduceFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::BeforeMark { chunk, source } => formatter
                .debug_struct("ProduceFailure::BeforeMark")
                .field("chunk", chunk)
                .field("source", source)
                .finish(),
            Self::AfterMark { source, .. } => formatter
                .debug_struct("ProduceFailure::AfterMark")
                .field("source", source)
                .finish_non_exhaustive(),
        }
    }
}

impl fmt::Display for ProduceFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::BeforeMark { source, .. } | Self::AfterMark { source, .. } => {
                write!(formatter, "chunk production failed: {source}")
            }
        }
    }
}

impl std::error::Error for ProduceFailure {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn enqueue_error_splits_queue_full_from_fatal() {
        assert!(matches!(
            EnqueueError::from(KafkaError::MessageProduction(RDKafkaErrorCode::QueueFull)),
            EnqueueError::QueueFull
        ));
        assert!(matches!(
            EnqueueError::from(KafkaError::MessageProduction(
                RDKafkaErrorCode::MessageSizeTooLarge
            )),
            EnqueueError::Fatal(_)
        ));
        assert!(matches!(
            EnqueueError::from(KafkaError::Canceled),
            EnqueueError::Fatal(_)
        ));
    }

    #[test]
    fn producer_bounds_and_backoff_reject_unbounded_settings() {
        assert_eq!(
            ProducerSettings::new(0, Duration::from_millis(1)).unwrap_err(),
            ProducerSettingsError::ZeroMaxInflight
        );
        assert_eq!(
            ProducerSettings::new(1, Duration::ZERO).unwrap_err(),
            ProducerSettingsError::ZeroQueueFullBackoff
        );
        assert_eq!(
            next_queue_full_backoff(Duration::from_secs(4)),
            QUEUE_FULL_BACKOFF_CAP
        );
        assert_eq!(
            next_queue_full_backoff(QUEUE_FULL_BACKOFF_CAP),
            QUEUE_FULL_BACKOFF_CAP
        );
        assert_eq!(
            ProducerSettings::new(1, Duration::from_secs(60))
                .unwrap()
                .queue_full_backoff,
            QUEUE_FULL_BACKOFF_CAP
        );
    }
}
