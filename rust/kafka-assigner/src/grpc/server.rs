use std::sync::Arc;
use std::time::Duration;

use kafka_assigner_proto::kafka_assigner::v1 as proto;
use kafka_assigner_proto::kafka_assigner::v1::kafka_assigner_server::KafkaAssigner;
use tokio::sync::mpsc;
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status};

use crate::consumer_registry::{ConsumerConnection, ConsumerRegistry};
use crate::grpc::convert;
use crate::store::KafkaAssignerStore;
use crate::types::{AssignmentEvent, ConsumerStatus, RegisteredConsumer};

const STREAM_CHANNEL_SIZE: usize = 64;
const DEFAULT_LEASE_TTL: i64 = 30;
const DEFAULT_KEEPALIVE_INTERVAL: Duration = Duration::from_secs(10);

pub struct KafkaAssignerService {
    registry: Arc<ConsumerRegistry>,
    store: Arc<KafkaAssignerStore>,
}

impl KafkaAssignerService {
    pub fn new(store: Arc<KafkaAssignerStore>, registry: Arc<ConsumerRegistry>) -> Self {
        Self { registry, store }
    }
}

#[tonic::async_trait]
impl KafkaAssigner for KafkaAssignerService {
    type RegisterStream = ReceiverStream<Result<proto::AssignmentCommand, Status>>;

    async fn register(
        &self,
        request: Request<proto::RegisterRequest>,
    ) -> Result<Response<Self::RegisterStream>, Status> {
        let req = request.into_inner();
        let consumer_name = req.consumer_name;

        assignment_coordination::util::validate_identifier(&consumer_name)
            .map_err(|e| Status::invalid_argument(format!("invalid consumer_name: {e}")))?;

        // Grant an etcd lease for this consumer's registration.
        let lease_id = self
            .store
            .grant_lease(DEFAULT_LEASE_TTL)
            .await
            .map_err(|e| Status::internal(format!("failed to grant lease: {e}")))?;

        // Register the consumer in etcd (keyed to the lease).
        let now = assignment_coordination::util::now_seconds();
        let consumer = RegisteredConsumer {
            consumer_name: consumer_name.clone(),
            status: ConsumerStatus::Ready,
            registered_at: now,
        };
        self.store
            .register_consumer(&consumer, lease_id)
            .await
            .map_err(|e| Status::internal(format!("failed to register consumer: {e}")))?;

        // Create the channel that bridges the registry to the gRPC stream.
        let (event_tx, event_rx) = mpsc::channel::<AssignmentEvent>(STREAM_CHANNEL_SIZE);

        // If the consumer already owns partitions (e.g. reconnecting), send them
        // as the first message. New consumers get an empty set — skip the no-op.
        let assignments = self
            .store
            .list_assignments()
            .await
            .map_err(|e| Status::internal(format!("failed to list assignments: {e}")))?;
        let owned = convert::consumer_partitions(&consumer_name, &assignments);
        if !owned.is_empty() {
            let initial = AssignmentEvent::Assignment {
                assigned: owned,
                unassigned: vec![],
            };
            event_tx
                .send(initial)
                .await
                .map_err(|_| Status::internal("failed to send initial assignment"))?;
        }

        // Register in the local consumer registry.
        self.registry.register(ConsumerConnection {
            consumer_name: consumer_name.clone(),
            command_tx: event_tx,
            lease_id,
        });

        tracing::info!(consumer = %consumer_name, "consumer registered via gRPC");

        // Spawn a background task for lease keepalive and cleanup on disconnect.
        let store = Arc::clone(&self.store);
        let registry = Arc::clone(&self.registry);
        let name = consumer_name.clone();

        // Create a proto stream that converts AssignmentEvent -> proto::AssignmentCommand.
        let (proto_tx, proto_rx) =
            mpsc::channel::<Result<proto::AssignmentCommand, Status>>(STREAM_CHANNEL_SIZE);

        // Bridge: read domain events, convert to proto, forward to the gRPC stream.
        // When the event channel closes (consumer unregistered), this task exits,
        // which drops proto_tx, closing the gRPC stream.
        tokio::spawn({
            let proto_tx = proto_tx.clone();
            async move {
                let mut event_rx = event_rx;
                while let Some(event) = event_rx.recv().await {
                    let cmd = proto::AssignmentCommand::from(&event);
                    if proto_tx.send(Ok(cmd)).await.is_err() {
                        break;
                    }
                }
            }
        });

        // Keepalive + cleanup task. Keeps the etcd lease alive while the gRPC stream
        // is open. When the stream drops (proto_tx closed from consumer side), this
        // task detects it via the closed channel and cleans up.
        tokio::spawn(async move {
            let result =
                run_consumer_keepalive(&store, lease_id, DEFAULT_KEEPALIVE_INTERVAL, &proto_tx)
                    .await;

            if let Err(e) = &result {
                tracing::warn!(consumer = %name, error = %e, "consumer keepalive ended");
                // Notify the consumer that the stream is being closed so it
                // knows to reconnect rather than waiting for a timeout.
                drop(
                    proto_tx
                        .send(Err(Status::unavailable(format!("keepalive lost: {e}"))))
                        .await,
                );
            }

            // Cleanup: unregister from local registry and revoke the etcd lease.
            registry.unregister(&name);
            if let Err(e) = store.revoke_lease(lease_id).await {
                tracing::warn!(consumer = %name, error = %e, "failed to revoke lease on cleanup");
            }

            tracing::info!(consumer = %name, "consumer disconnected, cleaned up");
        });

        Ok(Response::new(ReceiverStream::new(proto_rx)))
    }

    async fn partition_ready(
        &self,
        request: Request<proto::PartitionReadyRequest>,
    ) -> Result<Response<proto::PartitionReadyResponse>, Status> {
        let req = request.into_inner();
        let tp = convert::topic_partition_from_ready(&req)
            .ok_or_else(|| Status::invalid_argument("partition is required"))?;

        assignment_coordination::util::validate_identifier(&req.consumer_name)
            .map_err(|e| Status::invalid_argument(format!("invalid consumer_name: {e}")))?;
        assignment_coordination::util::validate_identifier(&tp.topic)
            .map_err(|e| Status::invalid_argument(format!("invalid topic: {e}")))?;

        // Write handoff phase to Ready in etcd. The leader's watch_handoffs_loop
        // will see this and call complete_handoff.
        let mut handoff = self
            .store
            .get_handoff(&tp)
            .await
            .map_err(|e| Status::internal(format!("failed to get handoff: {e}")))?
            .ok_or_else(|| {
                Status::not_found(format!("no handoff for {}/{}", tp.topic, tp.partition))
            })?;

        handoff.phase = crate::types::HandoffPhase::Ready;
        self.store
            .put_handoff(&handoff)
            .await
            .map_err(|e| Status::internal(format!("failed to update handoff: {e}")))?;

        tracing::info!(
            consumer = %req.consumer_name,
            topic = %tp.topic,
            partition = tp.partition,
            "partition ready signaled via gRPC"
        );

        Ok(Response::new(proto::PartitionReadyResponse {}))
    }

    async fn partition_released(
        &self,
        request: Request<proto::PartitionReleasedRequest>,
    ) -> Result<Response<proto::PartitionReleasedResponse>, Status> {
        let req = request.into_inner();
        let tp = convert::topic_partition_from_released(&req)
            .ok_or_else(|| Status::invalid_argument("partition is required"))?;

        assignment_coordination::util::validate_identifier(&req.consumer_name)
            .map_err(|e| Status::invalid_argument(format!("invalid consumer_name: {e}")))?;
        assignment_coordination::util::validate_identifier(&tp.topic)
            .map_err(|e| Status::invalid_argument(format!("invalid topic: {e}")))?;

        // Delete the handoff from etcd. This signals to the leader that the
        // old consumer has released and the handoff is fully complete.
        self.store
            .delete_handoff(&tp)
            .await
            .map_err(|e| Status::internal(format!("failed to delete handoff: {e}")))?;

        tracing::info!(
            consumer = %req.consumer_name,
            topic = %tp.topic,
            partition = tp.partition,
            "partition released signaled via gRPC"
        );

        Ok(Response::new(proto::PartitionReleasedResponse {}))
    }
}

/// Keep the etcd lease alive while the gRPC stream is still open.
///
/// The `proto_tx` sender is used to detect when the consumer disconnects:
/// if the consumer drops the stream, the receiver side closes, and
/// `proto_tx.is_closed()` becomes true.
async fn run_consumer_keepalive(
    store: &KafkaAssignerStore,
    lease_id: i64,
    interval: Duration,
    proto_tx: &mpsc::Sender<Result<proto::AssignmentCommand, Status>>,
) -> crate::error::Result<()> {
    let (mut keeper, mut stream) = store.keep_alive(lease_id).await?;

    loop {
        tokio::select! {
            _ = proto_tx.closed() => {
                // Consumer disconnected — the gRPC stream was dropped.
                return Ok(());
            }
            _ = tokio::time::sleep(interval) => {
                keeper.keep_alive().await?;
                if stream.message().await?.is_none() {
                    return Err(crate::error::Error::leadership_lost());
                }
            }
        }
    }
}
