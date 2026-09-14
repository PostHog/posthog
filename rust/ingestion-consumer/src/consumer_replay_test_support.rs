use std::{sync::Arc, time::Duration};

use axum::{routing::get, Router};
use ingestion_worker_proto::ingestion::worker::v1::{
    ingest_stream_request, ingest_stream_response,
    worker_ingest_server::{WorkerIngest, WorkerIngestServer},
    IngestStreamRequest, IngestStreamResponse, StreamReady, SubBatch, SubBatchAck, SubBatchStatus,
};
use lifecycle::{ComponentOptions, Manager, MonitorGuard};
use rdkafka::{
    config::ClientConfig,
    consumer::{Consumer, StreamConsumer},
    mocking::MockCluster,
    producer::{DefaultProducerContext, FutureProducer, FutureRecord},
    Offset, TopicPartitionList,
};
use tokio::{net::TcpListener, sync::mpsc};
use tokio_stream::wrappers::{TcpListenerStream, UnboundedReceiverStream};
use tokio_util::sync::CancellationToken;
use tonic::{Request, Response, Status, Streaming};

use super::{AbortOnDrop, IngestionConsumer, IngestionConsumerOptions};
use crate::{
    dispatcher::Dispatcher,
    grpc_transport::{GrpcPort, GrpcTransport},
    order_sentinel::SentinelContext,
    routing::RoutingStrategy,
    scheduler::SchedulerKind,
    worker_registry::{WorkerRegistry, WorkerRegistryConfig},
};

const TOPIC: &str = "reassigned-poll";
const PARTITION: i32 = 0;
const GROUP: &str = "reassigned-poll-test";

/// Real consumer, batcher and transport; only the worker's ACK is controlled by the test.
/// Owns the broker and task guards so failed assertions also tear down the fixture.
pub(super) struct ReplayHarness {
    process: AbortOnDrop,
    shutdown: CancellationToken,
    kafka: Arc<StreamConsumer<SentinelContext>>,
    producer: FutureProducer,
    connections: mpsc::UnboundedReceiver<WorkerConnection>,
    _worker_server: AbortOnDrop,
    _ready_server: AbortOnDrop,
    _monitor: MonitorGuard,
    _cluster: MockCluster<'static, DefaultProducerContext>,
}

impl ReplayHarness {
    pub(super) async fn start_with_batch_size(batch_size: usize) -> Self {
        let cluster = MockCluster::new(1).unwrap();
        cluster.create_topic(TOPIC, 1, 1).unwrap();
        let (worker_url, ready_server) = start_ready_server().await;
        let (grpc_port, connections, worker_server) = start_worker_server().await;
        let transport = Arc::new(GrpcTransport::new(grpc_port, 1, Duration::from_secs(30)));
        let mut context = SentinelContext::detached();
        context.set_assignment_epoch(transport.assignment_epoch());
        let kafka: StreamConsumer<SentinelContext> = ClientConfig::new()
            .set("bootstrap.servers", cluster.bootstrap_servers())
            .set("group.id", GROUP)
            .set("auto.offset.reset", "earliest")
            .set("enable.auto.commit", "false")
            .set("enable.auto.offset.store", "false")
            .set("session.timeout.ms", "6000")
            .set("heartbeat.interval.ms", "1000")
            .create_with_context(context)
            .unwrap();
        kafka.subscribe(&[TOPIC]).unwrap();

        let worker_urls = vec![worker_url];
        let dispatcher = create_dispatcher(&worker_urls);
        let mut manager = Manager::builder(GROUP).with_trap_signals(false).build();
        let handle = manager.register("consumer", ComponentOptions::new());
        let shutdown = handle.shutdown_token();
        let monitor = manager.monitor_background();
        let consumer = IngestionConsumer::from_parts(
            kafka,
            dispatcher,
            transport,
            worker_urls,
            IngestionConsumerOptions {
                batch_size,
                batch_size_bytes: 0,
                // Leave collection open long enough to revoke and reassign through Kafka.
                batch_timeout: Duration::from_secs(60),
                max_in_flight_batches: 1,
                group_id: GROUP.to_string(),
                deferred_flush_timeout: Duration::from_secs(30),
                parked_retry_interval: Duration::from_millis(20),
                debug_recorder: None,
            },
            handle,
        );
        let kafka = Arc::clone(&consumer.consumer);
        let process = AbortOnDrop(tokio::spawn(consumer.process()));
        let producer = ClientConfig::new()
            .set("bootstrap.servers", cluster.bootstrap_servers())
            .create()
            .unwrap();
        Self {
            process,
            shutdown,
            kafka,
            producer,
            connections,
            _worker_server: worker_server,
            _ready_server: ready_server,
            _monitor: monitor,
            _cluster: cluster,
        }
    }

    pub(super) async fn publish_one_record(&self) {
        self.producer
            .send(
                FutureRecord::to(TOPIC)
                    .partition(PARTITION)
                    .key("key")
                    .payload("payload"),
                Duration::from_secs(5),
            )
            .await
            .unwrap();
    }

    pub(super) async fn wait_until_consumed(&self, offset: i64) {
        // Position is the next offset to read, not the broker's committed offset.
        wait_for("the first delivery to enter batch collection", || {
            self.kafka
                .position()
                .unwrap()
                .find_partition(TOPIC, PARTITION)
                .is_some_and(|p| p.offset() == Offset::Offset(offset + 1))
        })
        .await;
    }

    pub(super) async fn revoke_partition(&self) {
        self.kafka.unsubscribe();
        wait_for("the Kafka assignment to be revoked", || {
            self.kafka.assignment().unwrap().count() == 0
        })
        .await;
    }

    pub(super) fn reassign_partition(&self) {
        self.kafka.subscribe(&[TOPIC]).unwrap();
    }

    pub(super) async fn expect_worker_batch(&mut self, offsets: &[i64]) -> WorkerBatch {
        let mut worker = tokio::time::timeout(Duration::from_secs(15), self.connections.recv())
            .await
            .expect("reassigned poll reaches the worker")
            .expect("worker connection channel stays open");
        let batch = tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                let request = worker.requests.message().await.unwrap().unwrap();
                if let Some(ingest_stream_request::Msg::SubBatch(batch)) = request.msg {
                    break batch;
                }
            }
        })
        .await
        .expect("worker receives the collected batch");
        assert_eq!(
            batch
                .messages
                .iter()
                .map(|message| message.offset)
                .collect::<Vec<_>>(),
            offsets,
            "the original delivery and its replay must share the poll"
        );
        WorkerBatch { batch, worker }
    }

    pub(super) async fn expect_committed_offset(&self, next_offset: i64) {
        wait_for("the accepted replay to be committed to Kafka", || {
            let mut partitions = TopicPartitionList::new();
            partitions.add_partition(TOPIC, PARTITION);
            self.kafka
                .committed_offsets(partitions, Duration::from_secs(2))
                .unwrap()
                .find_partition(TOPIC, PARTITION)
                .unwrap()
                .offset()
                == Offset::Offset(next_offset)
        })
        .await;
    }

    pub(super) async fn shutdown(mut self) {
        self.shutdown.cancel();
        tokio::time::timeout(Duration::from_secs(5), &mut self.process.0)
            .await
            .expect("consumer drains and stops")
            .unwrap();
    }
}

pub(super) struct WorkerBatch {
    batch: SubBatch,
    // Keep the request stream alive until the consumer has processed the ACK.
    worker: WorkerConnection,
}

impl WorkerBatch {
    pub(super) fn accept_all(&self) {
        self.worker
            .responses
            .send(Ok(IngestStreamResponse {
                msg: Some(ingest_stream_response::Msg::Ack(SubBatchAck {
                    seq: self.batch.seq,
                    status: SubBatchStatus::Ok as i32,
                    accepted: self.batch.messages.len().try_into().unwrap(),
                    error: String::new(),
                })),
            }))
            .unwrap();
    }
}

async fn wait_for(description: &str, mut ready: impl FnMut() -> bool) {
    tokio::time::timeout(Duration::from_secs(15), async {
        while !ready() {
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .unwrap_or_else(|_| panic!("timed out waiting for {description}"));
}

fn create_dispatcher(worker_urls: &[String]) -> Arc<Dispatcher> {
    Arc::new(Dispatcher::with_scheduler(
        Arc::new(WorkerRegistry::new(
            worker_urls,
            WorkerRegistryConfig {
                probe_interval: Duration::from_millis(50),
                dead_declaration: Duration::from_millis(200),
                passive_window: Duration::from_secs(30),
                passive_error_threshold: 0.5,
                passive_min_samples: 1,
                degraded_hold: Duration::from_millis(100),
                min_state_duration: Duration::ZERO,
                probe_failure_threshold: 2,
                drain_timeout: Duration::from_secs(5),
            },
        )),
        RoutingStrategy::default(),
        SchedulerKind::KeyTable,
    ))
}

async fn start_ready_server() -> (String, AbortOnDrop) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let server = AbortOnDrop(tokio::spawn(async move {
        axum::serve(
            listener,
            Router::new().route("/_ready", get(|| async { axum::http::StatusCode::OK })),
        )
        .await
        .unwrap();
    }));
    (url, server)
}

async fn start_worker_server() -> (
    GrpcPort,
    mpsc::UnboundedReceiver<WorkerConnection>,
    AbortOnDrop,
) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = GrpcPort::Fixed(listener.local_addr().unwrap().port());
    let (connections, incoming) = mpsc::unbounded_channel();
    let server = AbortOnDrop(tokio::spawn(async move {
        tonic::transport::Server::builder()
            .add_service(
                WorkerIngestServer::new(Worker(connections))
                    .accept_compressed(tonic::codec::CompressionEncoding::Gzip)
                    .send_compressed(tonic::codec::CompressionEncoding::Gzip),
            )
            .serve_with_incoming(TcpListenerStream::new(listener))
            .await
            .unwrap();
    }));
    (port, incoming, server)
}

struct WorkerConnection {
    requests: Streaming<IngestStreamRequest>,
    responses: mpsc::UnboundedSender<Result<IngestStreamResponse, Status>>,
}

struct Worker(mpsc::UnboundedSender<WorkerConnection>);

#[tonic::async_trait]
impl WorkerIngest for Worker {
    type IngestStreamStream = UnboundedReceiverStream<Result<IngestStreamResponse, Status>>;

    async fn ingest_stream(
        &self,
        request: Request<Streaming<IngestStreamRequest>>,
    ) -> Result<Response<Self::IngestStreamStream>, Status> {
        let (responses, rx) = mpsc::unbounded_channel();
        responses
            .send(Ok(IngestStreamResponse {
                msg: Some(ingest_stream_response::Msg::Ready(StreamReady {})),
            }))
            .unwrap();
        self.0
            .send(WorkerConnection {
                requests: request.into_inner(),
                responses,
            })
            .unwrap();
        Ok(Response::new(UnboundedReceiverStream::new(rx)))
    }
}
