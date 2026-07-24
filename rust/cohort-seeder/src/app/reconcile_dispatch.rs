//! Manual reconcile dispatch orchestration. Database validation and partition-layout verification
//! finish before the first control tile is enqueued; all enqueued deliveries are drained before an
//! error is returned.

use std::collections::{BTreeMap, VecDeque};
use std::future::Future;
use std::num::NonZeroUsize;
use std::pin::Pin;
use std::time::Duration;

use cohort_core::partitioner::COHORT_PARTITION_COUNT;
use rdkafka::error::KafkaError;
use sqlx::PgPool;

use crate::domain::{ReconcileTile, RunId};
use crate::kafka::producer::{
    EnqueueError, PartitionCountError, SeedPartition, SeedPartitionCountError, SeedTileProducer,
};
use crate::store::chunks::{ChunkStoreError, PgChunkStore};
use crate::store::runs::{load_reconcile_run, ReconcileRun, ReconcileRunError, RunStatus};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CompletionRequirement {
    Complete,
    AllowIncomplete,
}

/// Operator attestation that this run's data tiles were seeded or replayed after membership-register
/// writers were deployed.
///
/// The database does not persist a writer-version boundary, so pre-register runs cannot prove that
/// their Stage 2 scan domain is complete. Requiring this capability at the dispatch boundary keeps
/// that residual explicit instead of emitting a false completion certificate.
#[must_use]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RegisterBackfillConfirmation(());

impl RegisterBackfillConfirmation {
    pub const fn confirmed_by_operator() -> Self {
        Self(())
    }
}

/// A run capability minted only after its status, active participations, hashes, and chunk ledger
/// satisfy the operator's completion requirement.
#[derive(Debug)]
pub struct PreparedReconcileDispatch {
    run: ReconcileRun,
    total_chunks: u64,
    remaining_chunks: u64,
}

impl PreparedReconcileDispatch {
    pub const fn run_id(&self) -> RunId {
        self.run.run_id()
    }

    pub fn cohort_count(&self) -> usize {
        self.run.cohort_count()
    }

    pub const fn total_chunks(&self) -> u64 {
        self.total_chunks
    }

    pub const fn remaining_chunks(&self) -> u64 {
        self.remaining_chunks
    }
}

pub async fn prepare_reconcile_dispatch(
    pool: &PgPool,
    run_id: RunId,
    completion: CompletionRequirement,
    _register_backfill: RegisterBackfillConfirmation,
) -> Result<PreparedReconcileDispatch, PrepareReconcileDispatchError> {
    let run = load_reconcile_run(pool, run_id).await?;
    let progress = PgChunkStore::new(pool.clone())
        .chunk_progress(run_id)
        .await?;
    validate_completion(
        run_id,
        run.status(),
        progress.total(),
        progress.remaining(),
        completion,
    )?;
    Ok(PreparedReconcileDispatch {
        run,
        total_chunks: progress.total(),
        remaining_chunks: progress.remaining(),
    })
}

fn validate_completion(
    run_id: RunId,
    status: RunStatus,
    total_chunks: u64,
    remaining_chunks: u64,
    completion: CompletionRequirement,
) -> Result<(), PrepareReconcileDispatchError> {
    if completion == CompletionRequirement::Complete {
        if remaining_chunks != 0 {
            return Err(PrepareReconcileDispatchError::Incomplete {
                run_id,
                remaining_chunks,
            });
        }
        if total_chunks == 0 && status == RunStatus::Seeding {
            return Err(PrepareReconcileDispatchError::EmptyChunkLedger(run_id));
        }
    }
    Ok(())
}

#[derive(Debug, thiserror::Error)]
pub enum PrepareReconcileDispatchError {
    #[error(transparent)]
    Run(#[from] ReconcileRunError),
    #[error("reading the run's chunk ledger")]
    Chunks(#[from] ChunkStoreError),
    #[error("run {run_id:?} still has {remaining_chunks} unconfirmed chunks")]
    Incomplete {
        run_id: RunId,
        remaining_chunks: u64,
    },
    #[error(
        "seeding run {0:?} has no chunk rows, so dispatch cannot prove planning has completed; use --allow-incomplete to override"
    )]
    EmptyChunkLedger(RunId),
}

/// Highest acknowledged reconcile-control offset for every seed partition. A team-wide run may
/// enqueue several cohorts to one partition, so the maximum is the run's useful partition HWM.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ReconcileDispatchReceipt {
    offsets: BTreeMap<SeedPartition, i64>,
}

impl ReconcileDispatchReceipt {
    pub fn offsets(&self) -> impl ExactSizeIterator<Item = (SeedPartition, i64)> + '_ {
        self.offsets
            .iter()
            .map(|(partition, offset)| (*partition, *offset))
    }

    fn observe(&mut self, partition: SeedPartition, offset: i64) {
        self.offsets
            .entry(partition)
            .and_modify(|current| *current = (*current).max(offset))
            .or_insert(offset);
    }
}

pub async fn execute_reconcile_dispatch(
    prepared: PreparedReconcileDispatch,
    producer: &SeedTileProducer,
    max_inflight: NonZeroUsize,
    metadata_timeout: Duration,
) -> Result<ReconcileDispatchReceipt, ReconcileDispatchError> {
    let partitions = SeedPartition::all(COHORT_PARTITION_COUNT)?.collect::<Vec<_>>();
    let verify_producer = producer.clone();
    tokio::task::spawn_blocking(move || {
        verify_producer.verify_partition_count(COHORT_PARTITION_COUNT, metadata_timeout)
    })
    .await
    .map_err(ReconcileDispatchError::PartitionVerificationTask)??;

    let tiles = prepared.run.tiles().collect::<Vec<_>>();
    produce_reconcile_tiles(tiles, producer, &partitions, max_inflight).await
}

type ReconcileDelivery =
    Pin<Box<dyn Future<Output = Result<(i32, i64), KafkaError>> + Send + 'static>>;

trait ReconcileProducer {
    fn enqueue(
        &self,
        tile: &ReconcileTile,
        partition: SeedPartition,
    ) -> Result<ReconcileDelivery, EnqueueError>;
}

impl ReconcileProducer for SeedTileProducer {
    fn enqueue(
        &self,
        tile: &ReconcileTile,
        partition: SeedPartition,
    ) -> Result<ReconcileDelivery, EnqueueError> {
        let delivery = SeedTileProducer::enqueue_reconcile(self, tile, partition)?;
        Ok(Box::pin(async move {
            match delivery.await {
                Ok(Ok(coordinates)) => Ok(coordinates),
                Ok(Err((error, _))) => Err(error),
                Err(_) => Err(KafkaError::Canceled),
            }
        }))
    }
}

async fn produce_reconcile_tiles<P: ReconcileProducer>(
    tiles: impl IntoIterator<Item = ReconcileTile>,
    producer: &P,
    partitions: &[SeedPartition],
    max_inflight: NonZeroUsize,
) -> Result<ReconcileDispatchReceipt, ReconcileDispatchError> {
    let mut pending = VecDeque::new();
    let mut receipt = ReconcileDispatchReceipt::default();
    let mut failures = DeliveryFailures::default();
    let mut enqueue_error = None;

    'tiles: for tile in tiles {
        for partition in partitions.iter().copied() {
            loop {
                match producer.enqueue(&tile, partition) {
                    Ok(delivery) => {
                        pending.push_back(PendingDelivery {
                            partition,
                            delivery,
                        });
                        break;
                    }
                    Err(EnqueueError::QueueFull) if !pending.is_empty() => {
                        observe_next(&mut pending, &mut receipt, &mut failures).await;
                    }
                    Err(error) => {
                        enqueue_error = Some(error);
                        break 'tiles;
                    }
                }
            }

            if pending.len() >= max_inflight.get() {
                observe_next(&mut pending, &mut receipt, &mut failures).await;
            }
        }
    }

    while !pending.is_empty() {
        observe_next(&mut pending, &mut receipt, &mut failures).await;
    }

    if let Some(error) = enqueue_error {
        return Err(ReconcileDispatchError::Enqueue(error));
    }
    if let Some(error) = failures.into_error() {
        return Err(ReconcileDispatchError::Delivery(error));
    }
    Ok(receipt)
}

struct PendingDelivery {
    partition: SeedPartition,
    delivery: ReconcileDelivery,
}

async fn observe_next(
    pending: &mut VecDeque<PendingDelivery>,
    receipt: &mut ReconcileDispatchReceipt,
    failures: &mut DeliveryFailures,
) {
    let pending = pending
        .pop_front()
        .expect("observe_next is only called for a non-empty delivery queue");
    let expected_partition = i32::from(pending.partition.as_u16());
    match pending.delivery.await {
        Ok((actual_partition, offset)) if actual_partition == expected_partition && offset >= 0 => {
            receipt.observe(pending.partition, offset);
        }
        Ok((actual_partition, _)) if actual_partition != expected_partition => {
            failures.record(ReconcileDeliveryFailure::UnexpectedPartition {
                expected: pending.partition,
                actual: actual_partition,
            });
        }
        Ok((_, offset)) => {
            failures.record(ReconcileDeliveryFailure::NegativeOffset {
                partition: pending.partition,
                offset,
            });
        }
        Err(error) => failures.record(ReconcileDeliveryFailure::Kafka(error)),
    }
}

#[derive(Debug, Default)]
struct DeliveryFailures {
    count: usize,
    first: Option<ReconcileDeliveryFailure>,
}

impl DeliveryFailures {
    fn record(&mut self, failure: ReconcileDeliveryFailure) {
        self.count += 1;
        if self.first.is_none() {
            self.first = Some(failure);
        }
    }

    fn into_error(self) -> Option<ReconcileDeliveryFailures> {
        self.first.map(|first| ReconcileDeliveryFailures {
            count: self.count,
            first,
        })
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ReconcileDispatchError {
    #[error(transparent)]
    InvalidPartitionCount(#[from] SeedPartitionCountError),
    #[error("joining the seed-topic partition verification task")]
    PartitionVerificationTask(#[source] tokio::task::JoinError),
    #[error("verifying the seed-topic partition count")]
    TopicPartitionCount(#[from] PartitionCountError),
    #[error("enqueuing a reconcile control tile")]
    Enqueue(#[source] EnqueueError),
    #[error(transparent)]
    Delivery(#[from] ReconcileDeliveryFailures),
}

#[derive(Debug, thiserror::Error)]
#[error("{count} reconcile control tile deliveries failed; first failure: {first}")]
pub struct ReconcileDeliveryFailures {
    count: usize,
    #[source]
    first: ReconcileDeliveryFailure,
}

#[derive(Debug, thiserror::Error)]
enum ReconcileDeliveryFailure {
    #[error("Kafka rejected the delivery: {0}")]
    Kafka(#[source] KafkaError),
    #[error("partition {expected} was acknowledged as partition {actual}")]
    UnexpectedPartition {
        expected: SeedPartition,
        actual: i32,
    },
    #[error("partition {partition} was acknowledged with invalid offset {offset}")]
    NegativeOffset {
        partition: SeedPartition,
        offset: i64,
    },
}

#[cfg(test)]
mod tests {
    use std::collections::{HashMap, HashSet};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex};

    use cohort_core::filters::{CohortId, TeamId};
    use uuid::Uuid;

    use super::*;

    #[test]
    fn completion_requirement_fails_closed_for_unplanned_seeding_runs() {
        let run_id = RunId(Uuid::nil());
        assert!(validate_completion(
            run_id,
            RunStatus::Seeding,
            3,
            0,
            CompletionRequirement::Complete,
        )
        .is_ok());
        assert!(validate_completion(
            run_id,
            RunStatus::Reconciling,
            0,
            0,
            CompletionRequirement::Complete,
        )
        .is_ok());
        assert!(validate_completion(
            run_id,
            RunStatus::Seeding,
            0,
            0,
            CompletionRequirement::AllowIncomplete,
        )
        .is_ok());
        assert!(matches!(
            validate_completion(
                run_id,
                RunStatus::Seeding,
                3,
                2,
                CompletionRequirement::Complete,
            ),
            Err(PrepareReconcileDispatchError::Incomplete {
                remaining_chunks: 2,
                ..
            })
        ));
        assert!(matches!(
            validate_completion(
                run_id,
                RunStatus::Seeding,
                0,
                0,
                CompletionRequirement::Complete,
            ),
            Err(PrepareReconcileDispatchError::EmptyChunkLedger(id)) if id == run_id
        ));
    }

    #[tokio::test]
    async fn dispatch_covers_every_cohort_partition_and_reports_bounded_hwm() {
        let partitions = SeedPartition::all(64).unwrap().collect::<Vec<_>>();
        let producer = FakeProducer::new([]);
        let receipt = produce_reconcile_tiles(
            [tile(41), tile(42)],
            &producer,
            &partitions,
            NonZeroUsize::new(5).unwrap(),
        )
        .await
        .unwrap();

        let calls = producer.calls();
        assert_eq!(calls.len(), 128);
        assert_eq!(
            calls
                .iter()
                .map(|call| (call.cohort_id, call.partition))
                .collect::<HashSet<_>>()
                .len(),
            128,
        );
        assert_eq!(producer.deliveries.resolved.load(Ordering::SeqCst), 128);
        assert_eq!(producer.deliveries.current.load(Ordering::SeqCst), 0);
        assert_eq!(producer.deliveries.maximum.load(Ordering::SeqCst), 5);

        assert_eq!(
            receipt
                .offsets()
                .map(|(partition, offset)| (partition.as_u16(), offset))
                .collect::<Vec<_>>(),
            (0_u16..64)
                .map(|partition| (partition, i64::from(partition) + 1_000))
                .collect::<Vec<_>>(),
        );
    }

    #[tokio::test]
    async fn queue_full_drains_one_delivery_then_retries_the_same_target() {
        let partitions = SeedPartition::all(2).unwrap().collect::<Vec<_>>();
        let producer = FakeProducer::new([
            ScriptedOutcome::Ack,
            ScriptedOutcome::QueueFull,
            ScriptedOutcome::Ack,
        ]);

        let receipt = produce_reconcile_tiles(
            [tile(41)],
            &producer,
            &partitions,
            NonZeroUsize::new(10).unwrap(),
        )
        .await
        .unwrap();

        assert_eq!(producer.calls().len(), 3);
        assert_eq!(producer.deliveries.resolved.load(Ordering::SeqCst), 2);
        assert_eq!(receipt.offsets().len(), 2);
    }

    #[tokio::test]
    async fn nack_and_fatal_enqueue_drain_every_already_enqueued_delivery() {
        let partitions = SeedPartition::all(3).unwrap().collect::<Vec<_>>();
        let nack = FakeProducer::new([
            ScriptedOutcome::Nack,
            ScriptedOutcome::Ack,
            ScriptedOutcome::Ack,
        ]);
        let nack_error = produce_reconcile_tiles(
            [tile(41)],
            &nack,
            &partitions,
            NonZeroUsize::new(3).unwrap(),
        )
        .await
        .unwrap_err();
        assert!(matches!(
            nack_error,
            ReconcileDispatchError::Delivery(ReconcileDeliveryFailures { count: 1, .. })
        ));
        assert_eq!(nack.deliveries.resolved.load(Ordering::SeqCst), 3);

        let fatal = FakeProducer::new([ScriptedOutcome::Ack, ScriptedOutcome::Fatal]);
        let fatal_error = produce_reconcile_tiles(
            [tile(41)],
            &fatal,
            &partitions,
            NonZeroUsize::new(3).unwrap(),
        )
        .await
        .unwrap_err();
        assert!(matches!(fatal_error, ReconcileDispatchError::Enqueue(_)));
        assert_eq!(fatal.calls().len(), 2);
        assert_eq!(fatal.deliveries.resolved.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn invalid_delivery_coordinates_fail_the_dispatch() {
        let partition = SeedPartition::all(1).unwrap().collect::<Vec<_>>();
        for outcome in [
            ScriptedOutcome::UnexpectedPartition,
            ScriptedOutcome::NegativeOffset,
        ] {
            let producer = FakeProducer::new([outcome]);
            assert!(matches!(
                produce_reconcile_tiles([tile(41)], &producer, &partition, NonZeroUsize::MIN,)
                    .await,
                Err(ReconcileDispatchError::Delivery(
                    ReconcileDeliveryFailures { count: 1, .. }
                ))
            ));
            assert_eq!(producer.deliveries.resolved.load(Ordering::SeqCst), 1);
        }
    }

    fn tile(cohort_id: i32) -> ReconcileTile {
        ReconcileTile::new(
            TeamId(2),
            CohortId(cohort_id),
            crate::domain::BehavioralShapeHash::parse("behavioral-shape").unwrap(),
            RunId(Uuid::nil()),
        )
    }

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    enum ScriptedOutcome {
        Ack,
        QueueFull,
        Fatal,
        Nack,
        UnexpectedPartition,
        NegativeOffset,
    }

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    struct RecordedEnqueue {
        cohort_id: CohortId,
        partition: SeedPartition,
    }

    #[derive(Debug, Default)]
    struct DeliveryStats {
        current: AtomicUsize,
        maximum: AtomicUsize,
        resolved: AtomicUsize,
    }

    #[derive(Debug, Default)]
    struct FakeState {
        scripts: VecDeque<ScriptedOutcome>,
        calls: Vec<RecordedEnqueue>,
        next_offsets: HashMap<SeedPartition, i64>,
    }

    #[derive(Debug)]
    struct FakeProducer {
        state: Mutex<FakeState>,
        deliveries: Arc<DeliveryStats>,
    }

    impl FakeProducer {
        fn new(scripts: impl IntoIterator<Item = ScriptedOutcome>) -> Self {
            Self {
                state: Mutex::new(FakeState {
                    scripts: scripts.into_iter().collect(),
                    ..FakeState::default()
                }),
                deliveries: Arc::new(DeliveryStats::default()),
            }
        }

        fn calls(&self) -> Vec<RecordedEnqueue> {
            self.state.lock().unwrap().calls.clone()
        }

        fn delivery(&self, result: Result<(i32, i64), KafkaError>) -> ReconcileDelivery {
            let deliveries = Arc::clone(&self.deliveries);
            let current = deliveries.current.fetch_add(1, Ordering::SeqCst) + 1;
            deliveries.maximum.fetch_max(current, Ordering::SeqCst);
            Box::pin(async move {
                deliveries.current.fetch_sub(1, Ordering::SeqCst);
                deliveries.resolved.fetch_add(1, Ordering::SeqCst);
                result
            })
        }
    }

    impl ReconcileProducer for FakeProducer {
        fn enqueue(
            &self,
            tile: &ReconcileTile,
            partition: SeedPartition,
        ) -> Result<ReconcileDelivery, EnqueueError> {
            let mut state = self.state.lock().unwrap();
            state.calls.push(RecordedEnqueue {
                cohort_id: tile.cohort_id(),
                partition,
            });
            let outcome = state.scripts.pop_front().unwrap_or(ScriptedOutcome::Ack);
            match outcome {
                ScriptedOutcome::QueueFull => return Err(EnqueueError::QueueFull),
                ScriptedOutcome::Fatal => {
                    return Err(EnqueueError::Fatal(KafkaError::Canceled));
                }
                _ => {}
            }

            let next_offset = state
                .next_offsets
                .entry(partition)
                .or_insert_with(|| i64::from(partition.as_u16()));
            let offset = *next_offset;
            *next_offset += 1_000;
            drop(state);

            let expected_partition = i32::from(partition.as_u16());
            let result = match outcome {
                ScriptedOutcome::Ack => Ok((expected_partition, offset)),
                ScriptedOutcome::Nack => Err(KafkaError::Canceled),
                ScriptedOutcome::UnexpectedPartition => Ok((expected_partition + 1, offset)),
                ScriptedOutcome::NegativeOffset => Ok((expected_partition, -1)),
                ScriptedOutcome::QueueFull | ScriptedOutcome::Fatal => unreachable!(),
            };
            Ok(self.delivery(result))
        }
    }
}
