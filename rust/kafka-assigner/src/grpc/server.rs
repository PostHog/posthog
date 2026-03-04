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
use crate::types::{AssignmentEvent, ConsumerStatus, RegisteredConsumer, TopicConfig};

/// Kafka connection settings for admin metadata lookups.
#[derive(Clone)]
pub struct KafkaConfig {
    pub hosts: String,
    pub tls: bool,
    pub metadata_timeout: Duration,
}

pub struct KafkaAssignerService {
    registry: Arc<ConsumerRegistry>,
    store: Arc<KafkaAssignerStore>,
    kafka_config: KafkaConfig,
    stream_channel_size: usize,
    consumer_lease_ttl: i64,
    consumer_keepalive_interval: Duration,
}

impl KafkaAssignerService {
    pub fn new(store: Arc<KafkaAssignerStore>, registry: Arc<ConsumerRegistry>) -> Self {
        let kafka_config = KafkaConfig {
            hosts: "localhost:9092".to_string(),
            tls: false,
            metadata_timeout: Duration::from_secs(15),
        };
        Self::with_config(
            store,
            registry,
            kafka_config,
            64,
            30,
            Duration::from_secs(10),
        )
    }

    pub fn from_config(
        store: Arc<KafkaAssignerStore>,
        registry: Arc<ConsumerRegistry>,
        config: &crate::config::Config,
    ) -> Self {
        let kafka_config = KafkaConfig {
            hosts: config.kafka_hosts.clone(),
            tls: config.kafka_tls,
            metadata_timeout: config.kafka_metadata_timeout(),
        };
        Self::with_config(
            store,
            registry,
            kafka_config,
            config.stream_channel_size,
            config.consumer_lease_ttl_secs,
            config.consumer_keepalive_interval(),
        )
    }

    fn with_config(
        store: Arc<KafkaAssignerStore>,
        registry: Arc<ConsumerRegistry>,
        kafka_config: KafkaConfig,
        stream_channel_size: usize,
        consumer_lease_ttl: i64,
        consumer_keepalive_interval: Duration,
    ) -> Self {
        Self {
            registry,
            store,
            kafka_config,
            stream_channel_size,
            consumer_lease_ttl,
            consumer_keepalive_interval,
        }
    }

    /// Ensure a `TopicConfig` exists in etcd for the given topic.
    ///
    /// If one already exists, this is a no-op. Otherwise, fetch the partition
    /// count from Kafka broker metadata and store the config in etcd.
    async fn ensure_topic_config(&self, topic: &str) -> Result<(), Status> {
        let existing = self
            .store
            .get_topic_config(topic)
            .await
            .map_err(|e| Status::internal(format!("failed to check topic config: {e}")))?;

        if existing.is_some() {
            return Ok(());
        }

        tracing::info!(topic, "topic config not found in etcd, fetching from Kafka");

        let kafka_config = self.kafka_config.clone();
        let topic_owned = topic.to_string();

        let partition_count = tokio::task::spawn_blocking(move || {
            crate::kafka_admin::fetch_partition_count(
                &kafka_config.hosts,
                kafka_config.tls,
                &topic_owned,
                kafka_config.metadata_timeout,
            )
        })
        .await
        .map_err(|e| Status::internal(format!("metadata fetch task panicked: {e}")))?
        .map_err(|e| Status::internal(format!("failed to fetch partition count: {e}")))?;

        let config = TopicConfig {
            topic: topic.to_string(),
            partition_count,
        };

        self.store
            .set_topic_config(&config)
            .await
            .map_err(|e| Status::internal(format!("failed to store topic config: {e}")))?;

        tracing::info!(topic, partition_count, "stored topic config in etcd");

        Ok(())
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
        let topic = req.topic;

        assignment_coordination::util::validate_identifier(&consumer_name)
            .map_err(|e| Status::invalid_argument(format!("invalid consumer_name: {e}")))?;

        if !topic.is_empty() {
            assignment_coordination::util::validate_identifier(&topic)
                .map_err(|e| Status::invalid_argument(format!("invalid topic: {e}")))?;
            self.ensure_topic_config(&topic).await?;
        }

        // Grant an etcd lease for this consumer's registration.
        let lease_id = self
            .store
            .grant_lease(self.consumer_lease_ttl)
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
        let (event_tx, event_rx) = mpsc::channel::<AssignmentEvent>(self.stream_channel_size);

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
        let keepalive_interval = self.consumer_keepalive_interval;

        // Create a proto stream that converts AssignmentEvent -> proto::AssignmentCommand.
        let (proto_tx, proto_rx) =
            mpsc::channel::<Result<proto::AssignmentCommand, Status>>(self.stream_channel_size);

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
                run_consumer_keepalive(&store, lease_id, keepalive_interval, &proto_tx).await;

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
