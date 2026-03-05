use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use anyhow::Result;
use kafka_assigner_proto::kafka_assigner::v1 as proto;
use rdkafka::consumer::Consumer;
use rdkafka::consumer::StreamConsumer;
use rdkafka::TopicPartitionList;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

use super::client::AssignerGrpcClient;
use crate::kafka::batch_consumer::BatchConsumerProcessor;
use crate::kafka::offset_tracker::OffsetTracker;
use crate::kafka::partition_router::{shutdown_workers, PartitionRouter};
use crate::kafka::types::Partition;
use crate::metrics_const::{PARTITION_STORE_FALLBACK_EMPTY, REBALANCE_PARTITION_STATE_CHANGE};
use crate::store_manager::StoreManager;

/// Handles commands from the kafka-assigner and translates them into
/// store management and partition routing operations.
///
/// Warming (checkpoint download) is spawned externally by the consumer;
/// the handler only tracks cancellation tokens and handles completion.
pub struct AssignerCommandHandler<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    store_manager: Arc<StoreManager>,
    offset_tracker: Arc<OffsetTracker>,
    router: Arc<PartitionRouter<T, P>>,
    grpc_client: AssignerGrpcClient,

    /// Partitions we currently own and process.
    assigned_partitions: HashSet<Partition>,

    /// Partitions currently warming (checkpoint download in progress).
    warming_partitions: HashMap<Partition, CancellationToken>,
}

impl<T, P> AssignerCommandHandler<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    pub fn new(
        store_manager: Arc<StoreManager>,
        offset_tracker: Arc<OffsetTracker>,
        router: Arc<PartitionRouter<T, P>>,
        grpc_client: AssignerGrpcClient,
    ) -> Self {
        Self {
            store_manager,
            offset_tracker,
            router,
            grpc_client,
            assigned_partitions: HashSet::new(),
            warming_partitions: HashMap::new(),
        }
    }

    /// Handle an AssignmentUpdate command from the assigner.
    ///
    /// For newly assigned partitions: create stores, create workers, update Kafka assignment.
    /// For unassigned partitions: shutdown workers, clean up stores, update Kafka assignment.
    pub async fn handle_assignment(
        &mut self,
        update: proto::AssignmentUpdate,
        consumer: &StreamConsumer,
    ) -> Result<()> {
        let assigned: Vec<Partition> = update.assigned.iter().map(proto_to_partition).collect();
        let unassigned: Vec<Partition> = update.unassigned.iter().map(proto_to_partition).collect();

        if !assigned.is_empty() {
            info!(
                count = assigned.len(),
                partitions = ?assigned,
                "Received partition assignments"
            );
        }
        if !unassigned.is_empty() {
            info!(
                count = unassigned.len(),
                partitions = ?unassigned,
                "Received partition unassignments"
            );
        }

        for partition in &unassigned {
            metrics::counter!(
                REBALANCE_PARTITION_STATE_CHANGE,
                "topic" => partition.topic().to_string(),
                "partition" => partition.partition_number().to_string(),
                "op" => "revoke",
                "assignment_mode" => "kafka_assigner",
            )
            .increment(1);
            self.remove_partition(partition).await;
        }

        for partition in &assigned {
            metrics::counter!(
                REBALANCE_PARTITION_STATE_CHANGE,
                "topic" => partition.topic().to_string(),
                "partition" => partition.partition_number().to_string(),
                "op" => "assign",
                "assignment_mode" => "kafka_assigner",
            )
            .increment(1);
            self.add_partition(partition).await;
        }

        self.sync_kafka_assignment(consumer)?;

        Ok(())
    }

    /// Begin warming a partition. Returns a cancellation token that can be
    /// used to abort the warming if a Release arrives before it completes.
    ///
    /// The caller is responsible for spawning the actual checkpoint import
    /// task and calling `finish_warm` when it completes.
    pub fn start_warm(&mut self, partition: &Partition) -> CancellationToken {
        let cancel_token = CancellationToken::new();
        self.warming_partitions
            .insert(partition.clone(), cancel_token.clone());
        cancel_token
    }

    /// Check if a partition is currently warming.
    pub fn is_warming(&self, partition: &Partition) -> bool {
        self.warming_partitions.contains_key(partition)
    }

    /// Complete the warming phase for a partition.
    ///
    /// On success: signals PartitionReady to the assigner.
    /// On failure: creates a fallback empty store, then signals PartitionReady.
    pub async fn finish_warm(
        &mut self,
        partition: &Partition,
        import_result: Result<()>,
    ) -> Result<()> {
        self.warming_partitions.remove(partition);

        match import_result {
            Ok(()) => {
                info!(
                    topic = partition.topic(),
                    partition = partition.partition_number(),
                    "Partition warmed successfully, signaling ready"
                );
            }
            Err(e) => {
                warn!(
                    topic = partition.topic(),
                    partition = partition.partition_number(),
                    error = ?e,
                    "Checkpoint import failed during warm, creating fallback empty store"
                );
                match self
                    .store_manager
                    .get_or_create_for_rebalance(partition.topic(), partition.partition_number())
                    .await
                {
                    Ok(_) => {
                        metrics::counter!(
                            PARTITION_STORE_FALLBACK_EMPTY,
                            "reason" => "import_failed",
                            "assignment_mode" => "kafka_assigner",
                        )
                        .increment(1);
                    }
                    Err(store_err) => {
                        error!(
                            topic = partition.topic(),
                            partition = partition.partition_number(),
                            error = ?store_err,
                            "Failed to create fallback store"
                        );
                    }
                }
            }
        }

        self.grpc_client.partition_ready(partition).await?;
        Ok(())
    }

    /// Handle a ReleasePartition command: cancel warming, stop processing, drain, clean up,
    /// update Kafka assignment, and signal released to the assigner.
    pub async fn handle_release(
        &mut self,
        release: proto::ReleasePartition,
        consumer: &StreamConsumer,
    ) -> Result<()> {
        let proto_partition = release
            .partition
            .as_ref()
            .expect("ReleasePartition must have a partition");
        let partition = proto_to_partition(proto_partition);

        info!(
            topic = partition.topic(),
            partition = partition.partition_number(),
            new_owner = release.new_owner.as_str(),
            "Releasing partition"
        );

        metrics::counter!(
            REBALANCE_PARTITION_STATE_CHANGE,
            "topic" => partition.topic().to_string(),
            "partition" => partition.partition_number().to_string(),
            "op" => "release",
            "assignment_mode" => "kafka_assigner",
        )
        .increment(1);

        // Cancel any in-progress warming for this partition
        if let Some(token) = self.warming_partitions.remove(&partition) {
            token.cancel();
        }

        self.remove_partition(&partition).await;
        self.sync_kafka_assignment(consumer)?;

        self.grpc_client.partition_released(&partition).await?;

        Ok(())
    }

    /// Add a partition to the set of actively processed partitions.
    async fn add_partition(&mut self, partition: &Partition) {
        if self.assigned_partitions.contains(partition) {
            return;
        }

        // Ensure a store exists (may have been created during warm phase)
        if self
            .store_manager
            .get(partition.topic(), partition.partition_number())
            .is_none()
        {
            if let Err(e) = self
                .store_manager
                .get_or_create_for_rebalance(partition.topic(), partition.partition_number())
                .await
            {
                error!(
                    topic = partition.topic(),
                    partition = partition.partition_number(),
                    error = ?e,
                    "Failed to create store for assigned partition"
                );
            }
        }

        self.router.add_partition(partition.clone());
        self.assigned_partitions.insert(partition.clone());

        info!(
            topic = partition.topic(),
            partition = partition.partition_number(),
            total_assigned = self.assigned_partitions.len(),
            "Added partition to active set"
        );
    }

    /// Remove a partition from the set of actively processed partitions.
    async fn remove_partition(&mut self, partition: &Partition) {
        if !self.assigned_partitions.remove(partition) {
            return;
        }

        let workers = self
            .router
            .remove_partitions(std::slice::from_ref(partition));
        shutdown_workers(workers).await;

        // TODO: flush tracked offset for this partition to Kafka before clearing,
        // otherwise we lose uncommitted progress and reprocess on next assignment.
        self.offset_tracker.clear_partition(partition);

        self.store_manager
            .unregister_store(partition.topic(), partition.partition_number());

        // Clean up RocksDB directory for this partition
        if let Err(e) = self
            .store_manager
            .cleanup_store_files(partition.topic(), partition.partition_number())
        {
            warn!(
                topic = partition.topic(),
                partition = partition.partition_number(),
                error = ?e,
                "Failed to clean up store files, orphan cleaner will handle it"
            );
        }

        info!(
            topic = partition.topic(),
            partition = partition.partition_number(),
            total_assigned = self.assigned_partitions.len(),
            "Removed partition from active set"
        );
    }

    /// Sync the Kafka consumer's manual partition assignment with our current set.
    pub(super) fn sync_kafka_assignment(&self, consumer: &StreamConsumer) -> Result<()> {
        let mut tpl = TopicPartitionList::new();
        for partition in &self.assigned_partitions {
            tpl.add_partition(partition.topic(), partition.partition_number());
        }

        consumer
            .assign(&tpl)
            .map_err(|e| anyhow::anyhow!("Failed to assign partitions to Kafka consumer: {e}"))?;

        info!(
            partition_count = self.assigned_partitions.len(),
            "Synced Kafka consumer assignment"
        );

        Ok(())
    }
}

pub(super) fn proto_to_partition(tp: &proto::TopicPartition) -> Partition {
    Partition::new(tp.topic.clone(), tp.partition as i32)
}
