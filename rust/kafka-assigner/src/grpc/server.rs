use std::future::Future;
use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;
use kafka_assigner_proto::kafka_assigner::v1 as proto;
use kafka_assigner_proto::kafka_assigner::v1::kafka_assigner_server::KafkaAssigner;
use tokio::sync::{mpsc, Mutex};
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
    /// Per-topic lock to serialize concurrent `ensure_topic_config` calls,
    /// avoiding duplicate Kafka metadata fetches for the same new topic.
    topic_init_locks: DashMap<String, Arc<Mutex<()>>>,
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
            topic_init_locks: DashMap::new(),
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
        let store = &self.store;
        let kafka_config = &self.kafka_config;

        run_once_per_key(
            topic,
            &self.topic_init_locks,
            || async {
                store
                    .get_topic_config(topic)
                    .await
                    .map(|opt| opt.is_some())
                    .map_err(|e| Status::internal(format!("failed to check topic config: {e}")))
            },
            || async {
                tracing::info!(topic, "topic config not found in etcd, fetching from Kafka");

                let kc = kafka_config.clone();
                let topic_owned = topic.to_string();

                let partition_count = tokio::task::spawn_blocking(move || {
                    crate::kafka_admin::fetch_partition_count(
                        &kc.hosts,
                        kc.tls,
                        &topic_owned,
                        kc.metadata_timeout,
                    )
                })
                .await
                .map_err(|e| Status::internal(format!("metadata fetch task panicked: {e}")))?
                .map_err(|e| Status::internal(format!("failed to fetch partition count: {e}")))?;

                let config = TopicConfig {
                    topic: topic.to_string(),
                    partition_count,
                };

                store
                    .set_topic_config(&config)
                    .await
                    .map_err(|e| Status::internal(format!("failed to store topic config: {e}")))?;

                tracing::info!(topic, partition_count, "stored topic config in etcd");
                Ok(())
            },
        )
        .await
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

/// Double-checked locking: run `init_fn` at most once per key.
///
/// `is_initialized` is called first without a lock (fast path). If it returns
/// false, a per-key mutex is acquired and `is_initialized` is re-checked. Only
/// if still false, `init_fn` runs.
async fn run_once_per_key<C, CF, I, IF, E>(
    key: &str,
    locks: &DashMap<String, Arc<Mutex<()>>>,
    is_initialized: C,
    init_fn: I,
) -> Result<(), E>
where
    C: Fn() -> CF,
    CF: Future<Output = Result<bool, E>>,
    I: FnOnce() -> IF,
    IF: Future<Output = Result<(), E>>,
{
    if is_initialized().await? {
        return Ok(());
    }

    let lock = locks
        .entry(key.to_string())
        .or_insert_with(|| Arc::new(Mutex::new(())))
        .clone();
    let _guard = lock.lock().await;

    if is_initialized().await? {
        return Ok(());
    }

    init_fn().await
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

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};

    use super::*;

    #[tokio::test]
    async fn run_once_skips_init_when_already_initialized() {
        let locks = DashMap::new();
        let init_count = AtomicU32::new(0);

        run_once_per_key(
            "topic-a",
            &locks,
            || async { Ok::<_, String>(true) },
            || async {
                init_count.fetch_add(1, Ordering::SeqCst);
                Ok(())
            },
        )
        .await
        .unwrap();

        assert_eq!(init_count.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn run_once_calls_init_when_not_initialized() {
        let locks = DashMap::new();
        let init_count = AtomicU32::new(0);

        run_once_per_key(
            "topic-a",
            &locks,
            || async { Ok::<_, String>(false) },
            || async {
                init_count.fetch_add(1, Ordering::SeqCst);
                Ok(())
            },
        )
        .await
        .unwrap();

        assert_eq!(init_count.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn run_once_concurrent_callers_only_init_once() {
        let locks = Arc::new(DashMap::new());
        let init_count = Arc::new(AtomicU32::new(0));
        let initialized = Arc::new(AtomicBool::new(false));

        let mut handles = Vec::new();
        for _ in 0..10 {
            let locks = Arc::clone(&locks);
            let count = Arc::clone(&init_count);
            let flag = Arc::clone(&initialized);
            handles.push(tokio::spawn(async move {
                run_once_per_key(
                    "topic-a",
                    &locks,
                    || {
                        let flag = Arc::clone(&flag);
                        async move { Ok::<_, String>(flag.load(Ordering::SeqCst)) }
                    },
                    || {
                        let count = Arc::clone(&count);
                        let flag = Arc::clone(&flag);
                        async move {
                            count.fetch_add(1, Ordering::SeqCst);
                            // Simulate slow work so other callers queue up on the lock.
                            tokio::time::sleep(Duration::from_millis(50)).await;
                            flag.store(true, Ordering::SeqCst);
                            Ok(())
                        }
                    },
                )
                .await
            }));
        }

        for handle in handles {
            handle.await.unwrap().unwrap();
        }

        assert_eq!(init_count.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn run_once_different_keys_init_independently() {
        let locks = Arc::new(DashMap::new());
        let count_a = Arc::new(AtomicU32::new(0));
        let count_b = Arc::new(AtomicU32::new(0));

        let locks_a = Arc::clone(&locks);
        let ca = Arc::clone(&count_a);
        let handle_a = tokio::spawn(async move {
            run_once_per_key(
                "topic-a",
                &locks_a,
                || async { Ok::<_, String>(false) },
                || async {
                    ca.fetch_add(1, Ordering::SeqCst);
                    Ok(())
                },
            )
            .await
        });

        let locks_b = Arc::clone(&locks);
        let cb = Arc::clone(&count_b);
        let handle_b = tokio::spawn(async move {
            run_once_per_key(
                "topic-b",
                &locks_b,
                || async { Ok::<_, String>(false) },
                || async {
                    cb.fetch_add(1, Ordering::SeqCst);
                    Ok(())
                },
            )
            .await
        });

        handle_a.await.unwrap().unwrap();
        handle_b.await.unwrap().unwrap();

        assert_eq!(count_a.load(Ordering::SeqCst), 1);
        assert_eq!(count_b.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn run_once_propagates_check_error() {
        let locks = DashMap::new();

        let result = run_once_per_key(
            "topic-a",
            &locks,
            || async { Err::<bool, _>("check failed") },
            || async { Ok(()) },
        )
        .await;

        assert_eq!(result.unwrap_err(), "check failed");
    }

    #[tokio::test]
    async fn run_once_propagates_init_error() {
        let locks = DashMap::new();

        let result = run_once_per_key(
            "topic-a",
            &locks,
            || async { Ok::<_, String>(false) },
            || async { Err("init failed".to_string()) },
        )
        .await;

        assert_eq!(result.unwrap_err(), "init failed");
    }
}
