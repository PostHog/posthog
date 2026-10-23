//! Requires Kafka on localhost:9092 (docker-compose).

mod common;

use std::collections::HashSet;
use std::num::{NonZeroU32, NonZeroU64, NonZeroUsize};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use axum::routing::get;
use axum::Router;
use futures::StreamExt;
use lifecycle::{ComponentOptions, Manager};
use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::client::DefaultClientContext;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{BaseConsumer, Consumer, StreamConsumer};
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::{BaseProducer, BaseRecord, FutureProducer, FutureRecord, Producer};
use rdkafka::util::Timeout;
use rdkafka::TopicPartitionList;
use rstest::rstest;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

use common_kafka_consumer::{TopicOffsetLedger, TopicPartition};
use ingestion_consumer::batcher::packer::PackTargets;
use ingestion_consumer::batcher::state_machine::RequestBudget;
use ingestion_consumer::batcher::worker_pool::WorkerPoolSource;
use ingestion_consumer::batcher::BatcherObserver;
use ingestion_consumer::charge_limit::ChargeLimit;
use ingestion_consumer::config::{CompletionGranularity, Polling};
use ingestion_consumer::consumer::{IngestionConsumer, IngestionConsumerOptions};
use ingestion_consumer::debug_recorder::{DebugEventKind, DebugRecorder};
use ingestion_consumer::discovery::reconcile_membership;
use ingestion_consumer::grpc_transport::{GrpcPort, GrpcTransport};
use ingestion_consumer::partition_budget::BudgetLimits;
use ingestion_consumer::rebalance::RebalanceContext;
use ingestion_consumer::routing::RoutingStrategy;
use ingestion_consumer::worker_registry::{
    WorkerId, WorkerRegistry, WorkerRegistryConfig, WorkerState,
};
use ingestion_worker_proto::ingestion::worker::v1::worker_ingest_server::{
    WorkerIngest as WorkerIngestService, WorkerIngestServer,
};
use ingestion_worker_proto::ingestion::worker::v1::{
    ingest_stream_request, ingest_stream_response, IngestStreamRequest, IngestStreamResponse,
    MessageRef, StreamReady, SubBatchAck, SubBatchStatus,
};

const UNBOUNDED_BYTES: u64 = 1 << 40;
const KAFKA_BROKERS: &str = "localhost:9092";
const BUDGET_ATTEMPTS: NonZeroU32 = NonZeroU32::new(3).expect("nonzero attempts");

async fn create_topic(name: &str, partitions: i32) {
    let admin: AdminClient<DefaultClientContext> = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .create()
        .expect("admin client");
    let topic = NewTopic::new(name, partitions, TopicReplication::Fixed(1));
    let opts = AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)));
    for result in admin.create_topics(&[topic], &opts).await.unwrap() {
        match result {
            Ok(_) | Err((_, rdkafka::types::RDKafkaErrorCode::TopicAlreadyExists)) => {}
            Err((name, err)) => panic!("failed to create topic {name}: {err:?}"),
        }
    }
    tokio::time::sleep(Duration::from_millis(300)).await;
}

fn make_producer() -> FutureProducer {
    ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()
        .expect("producer")
}

async fn produce(
    producer: &FutureProducer,
    topic: &str,
    partition: i32,
    token: &str,
    distinct_id: &str,
    seq: usize,
) {
    let value = format!(r#"{{"seq":{seq}}}"#);
    let key = format!("{token}:{distinct_id}");
    let headers = OwnedHeaders::new()
        .insert(Header {
            key: "token",
            value: Some(token),
        })
        .insert(Header {
            key: "distinct_id",
            value: Some(distinct_id),
        });

    producer
        .send(
            FutureRecord::to(topic)
                .key(&key)
                .payload(&value)
                .partition(partition)
                .headers(headers),
            Timeout::After(Duration::from_secs(5)),
        )
        .await
        .expect("produce failed");
}

async fn produce_in_one_transaction(
    topic: &str,
    partition: i32,
    token: &str,
    records: &[(&str, usize)],
) {
    let records = records
        .iter()
        .map(|&(distinct_id, seq)| (format!("{token}:{distinct_id}"), distinct_id, seq))
        .collect::<Vec<_>>();
    let records: Vec<(i32, &str, &str, usize)> = records
        .iter()
        .map(|(key, distinct_id, seq)| (partition, key.as_str(), *distinct_id, *seq))
        .collect();
    produce_keyed_in_one_transaction(topic, token, &records).await;
}

fn alternating_visitors(
    partition: i32,
    key: &str,
    first_seq: usize,
) -> [(i32, &str, &str, usize); 4] {
    [
        (partition, key, "visitor-a", first_seq),
        (partition, key, "visitor-b", first_seq + 1),
        (partition, key, "visitor-a", first_seq + 2),
        (partition, key, "visitor-b", first_seq + 3),
    ]
}

async fn produce_keyed_in_one_transaction(
    topic: &str,
    token: &str,
    records: &[(i32, &str, &str, usize)],
) {
    let topic = topic.to_string();
    let token = token.to_string();
    let records: Vec<(i32, String, String, usize)> = records
        .iter()
        .map(|&(partition, key, distinct_id, seq)| {
            (partition, key.to_string(), distinct_id.to_string(), seq)
        })
        .collect();
    // The transaction calls block, so keep them off the test's runtime thread,
    // which also serves the fake workers.
    tokio::task::spawn_blocking(move || {
        let producer: BaseProducer = ClientConfig::new()
            .set("bootstrap.servers", KAFKA_BROKERS)
            .set("message.timeout.ms", "5000")
            .set("transactional.id", format!("e2e-{}", Uuid::new_v4()))
            .create()
            .expect("producer");
        let timeout = Timeout::After(Duration::from_secs(10));
        producer
            .init_transactions(timeout)
            .expect("init transactions");
        producer.begin_transaction().expect("begin transaction");
        for (partition, key, distinct_id, seq) in &records {
            let value = format!(r#"{{"seq":{seq}}}"#);
            let headers = OwnedHeaders::new()
                .insert(Header {
                    key: "token",
                    value: Some(token.as_str()),
                })
                .insert(Header {
                    key: "distinct_id",
                    value: Some(distinct_id.as_str()),
                });
            producer
                .send(
                    BaseRecord::to(&topic)
                        .key(key.as_str())
                        .payload(&value)
                        .partition(*partition)
                        .headers(headers),
                )
                .map_err(|(err, _)| err)
                .expect("enqueue failed");
        }
        producer
            .commit_transaction(timeout)
            .expect("commit transaction");
    })
    .await
    .expect("transactional produce panicked");
}

async fn produce_raw(
    producer: &FutureProducer,
    topic: &str,
    partition: i32,
    key: &str,
    payload: &[u8],
    headers: Option<OwnedHeaders>,
) {
    let mut record = FutureRecord::to(topic)
        .key(key)
        .payload(payload)
        .partition(partition);
    if let Some(h) = headers {
        record = record.headers(h);
    }
    producer
        .send(record, Timeout::After(Duration::from_secs(5)))
        .await
        .expect("produce failed");
}

struct FakeWorker {
    pub url: String,
    pub received: Arc<Mutex<Vec<(String, usize)>>>,
    /// Message count of each recorded sub-batch, in arrival order.
    pub batch_sizes: Arc<Mutex<Vec<usize>>>,
    /// When false, /_ready fails and every send nacks.
    pub healthy: Arc<AtomicBool>,
    /// When false, the worker stays ready but nacks every send.
    pub ingest_ok: Arc<AtomicBool>,
    /// When set, the next sub-batch is recorded, then nacked, so its replay duplicates it.
    pub ack_lost_once: Arc<AtomicBool>,
    /// When true, every sub-batch is nacked unrecorded.
    pub reject_4xx: Arc<AtomicBool>,
    /// When set to `(distinct_id, frames)`, the next `frames` sub-batches with
    /// a soft budget that carry this distinct_id leave all of that id's
    /// messages unfinished. They are not recorded, and the ack is PARTIAL.
    pub leave_unfinished: Arc<Mutex<Option<(String, usize)>>>,
    /// (distinct_id, seq) pairs that arrived in a sub-batch marked as replay.
    pub replayed: Arc<Mutex<Vec<(String, usize)>>>,
    /// When true, replay sub-batches get no answer and stay in flight.
    pub hold_replays: Arc<AtomicBool>,
    /// When set, the next sub-batch is recorded in full but acked as one message fewer.
    pub underreport_once: Arc<AtomicBool>,
    arrived: Arc<AtomicUsize>,
    on_arrival: ArrivalHook,
    gate: Arc<tokio::sync::Mutex<()>>,
    _task: tokio::task::JoinHandle<()>,
}

/// Shared by all workers, so its mutex puts every accepted message in one total order.
type DeliveryLog = Arc<Mutex<Vec<(String, usize)>>>;

type ArrivalHook = Arc<Mutex<Option<Box<dyn Fn() + Send + Sync>>>>;

impl FakeWorker {
    async fn start() -> Self {
        Self::start_inner(None).await
    }

    async fn start_logged(delivery_log: DeliveryLog) -> Self {
        Self::start_inner(Some(delivery_log)).await
    }

    async fn start_inner(delivery_log: Option<DeliveryLog>) -> Self {
        let received: Arc<Mutex<Vec<(String, usize)>>> = Arc::new(Mutex::new(Vec::new()));
        let batch_sizes: Arc<Mutex<Vec<usize>>> = Arc::new(Mutex::new(Vec::new()));
        let healthy = Arc::new(AtomicBool::new(true));
        let ingest_ok = Arc::new(AtomicBool::new(true));
        let ack_lost_once = Arc::new(AtomicBool::new(false));
        let reject_4xx = Arc::new(AtomicBool::new(false));
        let underreport_once = Arc::new(AtomicBool::new(false));
        let leave_unfinished = Arc::new(Mutex::new(None));
        let replayed = Arc::new(Mutex::new(Vec::new()));
        let hold_replays = Arc::new(AtomicBool::new(false));
        let arrived = Arc::new(AtomicUsize::new(0));
        let on_arrival: ArrivalHook = Arc::new(Mutex::new(None));
        let gate = Arc::new(tokio::sync::Mutex::new(()));

        let app = Router::new().route(
            "/_ready",
            get({
                let h = Arc::clone(&healthy);
                move || {
                    let h = h.clone();
                    async move {
                        if h.load(Ordering::Relaxed) {
                            axum::http::StatusCode::OK
                        } else {
                            axum::http::StatusCode::SERVICE_UNAVAILABLE
                        }
                    }
                }
            }),
        );

        // gRPC listens on the HTTP port + 1, as `GrpcPort::OffsetFromHttp(1)` expects.
        let (listener, grpc_listener) = loop {
            let http = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let Some(grpc_port) = http.local_addr().unwrap().port().checked_add(1) else {
                continue;
            };
            match TcpListener::bind(("127.0.0.1", grpc_port)).await {
                Ok(grpc) => break (http, grpc),
                Err(_) => continue,
            }
        };
        let addr = listener.local_addr().unwrap();
        let url = format!("http://127.0.0.1:{}", addr.port());
        let task = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });

        let grpc_service = FakeWorkerGrpc {
            received: Arc::clone(&received),
            batch_sizes: Arc::clone(&batch_sizes),
            healthy: Arc::clone(&healthy),
            ingest_ok: Arc::clone(&ingest_ok),
            ack_lost_once: Arc::clone(&ack_lost_once),
            reject_4xx: Arc::clone(&reject_4xx),
            underreport_once: Arc::clone(&underreport_once),
            leave_unfinished: Arc::clone(&leave_unfinished),
            replayed: Arc::clone(&replayed),
            hold_replays: Arc::clone(&hold_replays),
            arrived: Arc::clone(&arrived),
            on_arrival: Arc::clone(&on_arrival),
            gate: Arc::clone(&gate),
            delivery_log,
        };
        tokio::spawn(async move {
            tonic::transport::Server::builder()
                .add_service(
                    WorkerIngestServer::new(grpc_service)
                        .accept_compressed(tonic::codec::CompressionEncoding::Gzip)
                        .send_compressed(tonic::codec::CompressionEncoding::Gzip),
                )
                .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(
                    grpc_listener,
                ))
                .await
                .unwrap();
        });

        Self {
            url,
            received,
            batch_sizes,
            healthy,
            ingest_ok,
            ack_lost_once,
            reject_4xx,
            underreport_once,
            leave_unfinished,
            replayed,
            hold_replays,
            arrived,
            on_arrival,
            gate,
            _task: task,
        }
    }

    fn count(&self) -> usize {
        self.received.lock().unwrap().len()
    }

    fn batch_sizes(&self) -> Vec<usize> {
        self.batch_sizes.lock().unwrap().clone()
    }

    /// Sub-batches that have reached this worker (including any held by the gate).
    fn arrived_count(&self) -> usize {
        self.arrived.load(Ordering::SeqCst)
    }

    /// Freeze this worker's ingest handling: sub-batches arrive but block until the
    /// returned guard is dropped. Acquire before producing so the batch is caught.
    async fn block(&self) -> tokio::sync::OwnedMutexGuard<()> {
        Arc::clone(&self.gate).lock_owned().await
    }

    /// Run `hook` as each sub-batch arrives, before the gate holds it.
    fn on_arrival(&self, hook: impl Fn() + Send + Sync + 'static) {
        *self.on_arrival.lock().unwrap() = Some(Box::new(hook));
    }

    fn seqs_for(&self, distinct_id: &str) -> Vec<usize> {
        self.received
            .lock()
            .unwrap()
            .iter()
            .filter(|(did, _)| did == distinct_id)
            .map(|(_, seq)| *seq)
            .collect()
    }
}

// A nack ends the stream, as the protocol requires.
struct FakeWorkerGrpc {
    received: Arc<Mutex<Vec<(String, usize)>>>,
    batch_sizes: Arc<Mutex<Vec<usize>>>,
    healthy: Arc<AtomicBool>,
    ingest_ok: Arc<AtomicBool>,
    ack_lost_once: Arc<AtomicBool>,
    reject_4xx: Arc<AtomicBool>,
    underreport_once: Arc<AtomicBool>,
    leave_unfinished: Arc<Mutex<Option<(String, usize)>>>,
    replayed: Arc<Mutex<Vec<(String, usize)>>>,
    hold_replays: Arc<AtomicBool>,
    arrived: Arc<AtomicUsize>,
    on_arrival: ArrivalHook,
    gate: Arc<tokio::sync::Mutex<()>>,
    delivery_log: Option<DeliveryLog>,
}

#[tonic::async_trait]
impl WorkerIngestService for FakeWorkerGrpc {
    type IngestStreamStream = tokio_stream::wrappers::UnboundedReceiverStream<
        Result<IngestStreamResponse, tonic::Status>,
    >;

    async fn ingest_stream(
        &self,
        request: tonic::Request<tonic::Streaming<IngestStreamRequest>>,
    ) -> Result<tonic::Response<Self::IngestStreamStream>, tonic::Status> {
        let mut inbound = request.into_inner();
        let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
        let received = Arc::clone(&self.received);
        let batch_sizes = Arc::clone(&self.batch_sizes);
        let healthy = Arc::clone(&self.healthy);
        let ingest_ok = Arc::clone(&self.ingest_ok);
        let ack_lost_once = Arc::clone(&self.ack_lost_once);
        let reject_4xx = Arc::clone(&self.reject_4xx);
        let underreport_once = Arc::clone(&self.underreport_once);
        let leave_unfinished = Arc::clone(&self.leave_unfinished);
        let replayed = Arc::clone(&self.replayed);
        let hold_replays = Arc::clone(&self.hold_replays);
        let arrived = Arc::clone(&self.arrived);
        let on_arrival = Arc::clone(&self.on_arrival);
        let gate = Arc::clone(&self.gate);
        let delivery_log = self.delivery_log.clone();

        tokio::spawn(async move {
            // Mirror the real worker: greet with `ready` so response headers
            // flush; the worker stream must ignore it.
            let _ = tx.send(Ok(IngestStreamResponse {
                msg: Some(ingest_stream_response::Msg::Ready(StreamReady {})),
            }));
            let nack = |tx: &tokio::sync::mpsc::UnboundedSender<
                Result<IngestStreamResponse, tonic::Status>,
            >,
                        seq: u64,
                        reason: &str| {
                let _ = tx.send(Ok(IngestStreamResponse {
                    msg: Some(ingest_stream_response::Msg::Ack(SubBatchAck {
                        seq,
                        status: SubBatchStatus::Failed as i32,
                        accepted: 0,
                        error: reason.to_string(),
                        unfinished: vec![],
                    })),
                }));
            };
            while let Ok(Some(frame)) = inbound.message().await {
                let Some(ingest_stream_request::Msg::SubBatch(sub_batch)) = frame.msg else {
                    continue;
                };
                arrived.fetch_add(1, Ordering::SeqCst);
                if let Some(hook) = on_arrival.lock().unwrap().as_ref() {
                    hook();
                }
                let _hold = gate.lock().await;
                if !healthy.load(Ordering::Relaxed) || !ingest_ok.load(Ordering::Relaxed) {
                    nack(&tx, sub_batch.seq, "worker unhealthy");
                    return;
                }
                if reject_4xx.load(Ordering::SeqCst) {
                    nack(&tx, sub_batch.seq, "poison batch");
                    return;
                }
                if sub_batch.replay && hold_replays.load(Ordering::SeqCst) {
                    continue;
                }
                let entries: Vec<(String, usize)> = sub_batch
                    .messages
                    .iter()
                    .map(|msg| {
                        let did = msg.headers.get("distinct_id").cloned().unwrap_or_default();
                        let seq = msg
                            .value
                            .as_deref()
                            .and_then(|v| serde_json::from_str::<serde_json::Value>(v).ok())
                            .and_then(|v| v["seq"].as_u64())
                            .unwrap_or(0) as usize;
                        (did, seq)
                    })
                    .collect();
                let unfinished_id = if sub_batch.soft_budget_ms > 0 {
                    leave_unfinished
                        .lock()
                        .unwrap()
                        .as_ref()
                        .map(|(id, _)| id.clone())
                } else {
                    None
                };
                let mut done = Vec::new();
                let mut unfinished = Vec::new();
                for (message, entry) in sub_batch.messages.iter().zip(entries) {
                    if unfinished_id.as_deref() == Some(entry.0.as_str()) {
                        unfinished.push(MessageRef {
                            partition: message.partition,
                            offset: message.offset,
                        });
                    } else {
                        done.push(entry);
                    }
                }
                if sub_batch.replay {
                    replayed.lock().unwrap().extend(done.iter().cloned());
                }
                received.lock().unwrap().extend(done.iter().cloned());
                batch_sizes.lock().unwrap().push(sub_batch.messages.len());
                if let Some(log) = &delivery_log {
                    log.lock().unwrap().extend(done.iter().cloned());
                }
                if !unfinished.is_empty() {
                    let mut frames_left = leave_unfinished.lock().unwrap();
                    let used_up = frames_left.as_mut().is_some_and(|(_, frames)| {
                        *frames -= 1;
                        *frames == 0
                    });
                    if used_up {
                        *frames_left = None;
                    }
                    drop(frames_left);
                    let _ = tx.send(Ok(IngestStreamResponse {
                        msg: Some(ingest_stream_response::Msg::Ack(SubBatchAck {
                            seq: sub_batch.seq,
                            status: SubBatchStatus::Partial as i32,
                            accepted: done.len() as u32,
                            error: String::new(),
                            unfinished,
                        })),
                    }));
                    continue;
                }
                if ack_lost_once.swap(false, Ordering::SeqCst) {
                    nack(&tx, sub_batch.seq, "ack lost");
                    return;
                }
                let accepted = sub_batch.messages.len() as u32;
                let reported = if underreport_once.swap(false, Ordering::SeqCst) {
                    accepted.saturating_sub(1)
                } else {
                    accepted
                };
                let _ = tx.send(Ok(IngestStreamResponse {
                    msg: Some(ingest_stream_response::Msg::Ack(SubBatchAck {
                        seq: sub_batch.seq,
                        status: SubBatchStatus::Ok as i32,
                        accepted: reported,
                        error: String::new(),
                        unfinished: vec![],
                    })),
                }));
            }
        });

        Ok(tonic::Response::new(
            tokio_stream::wrappers::UnboundedReceiverStream::new(rx),
        ))
    }
}

const COMMIT_INTERVAL: Duration = Duration::from_millis(500);

struct Harness {
    pub workers: Vec<FakeWorker>,
    pub registry: Arc<WorkerRegistry>,
    pub observer: BatcherObserver,
    pub delivery_log: DeliveryLog,
    pub shutdown: CancellationToken,
    task: Option<tokio::task::JoinHandle<()>>,
    _probe_token: CancellationToken,
    topic: String,
    group_id: String,
    pub ledger: Arc<TopicOffsetLedger>,
    debug_recorder: Arc<DebugRecorder>,
    max_in_flight: usize,
    deferred_flush_timeout: Duration,
    pack_targets: PackTargets,
    budget: Option<RequestBudget>,
    completion_granularity: CompletionGranularity,
    partition_budget: BudgetLimits,
    polling: Polling,
    in_flight_limit: ChargeLimit,
}

// Short session and heartbeat so group handovers finish quickly.
fn make_kafka_consumer(
    topic: &str,
    group_id: &str,
    instance_id: Option<&str>,
) -> StreamConsumer<RebalanceContext> {
    make_kafka_consumer_with_context(topic, group_id, instance_id, RebalanceContext::new())
}

fn make_kafka_consumer_with_context(
    topic: &str,
    group_id: &str,
    instance_id: Option<&str>,
    context: RebalanceContext,
) -> StreamConsumer<RebalanceContext> {
    let mut config = ClientConfig::new();
    config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", group_id)
        .set("auto.offset.reset", "earliest")
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .set("session.timeout.ms", "6000")
        .set("heartbeat.interval.ms", "1000")
        .set("socket.timeout.ms", "5000");
    if let Some(id) = instance_id {
        config.set("group.instance.id", id);
    }
    let kafka_consumer: StreamConsumer<RebalanceContext> =
        config.create_with_context(context).expect("kafka consumer");
    kafka_consumer.subscribe(&[topic]).expect("subscribe");
    kafka_consumer
}

/// Each FakeWorker serves gRPC on its HTTP port + 1; a 10 s ack timeout (production: 60 s) so a stalled request fences quickly.
fn test_transport() -> GrpcTransport {
    GrpcTransport::new(GrpcPort::OffsetFromHttp(1), Duration::from_secs(10))
}

/// Ticks every 100 ms, against 1 s in production.
fn spawn_reaper(
    registry: Arc<WorkerRegistry>,
    transport: Arc<GrpcTransport>,
    observer: BatcherObserver,
    token: CancellationToken,
) {
    tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = token.cancelled() => break,
                _ = tokio::time::sleep(Duration::from_millis(100)) => {}
            }
            for worker in registry.draining_workers() {
                if !observer.has_in_flight(&worker) {
                    registry.complete_drain(&worker);
                }
            }
            for worker in registry.reapable_workers() {
                registry.remove_worker(&worker);
                transport.remove_worker(&worker);
            }
        }
    });
}

impl Harness {
    async fn start(
        topic: &str,
        partitions: i32,
        worker_count: usize,
        max_in_flight: usize,
        deferred_flush_timeout: Duration,
        registry_config: WorkerRegistryConfig,
    ) -> Self {
        Self::start_inner(
            topic,
            partitions,
            worker_count,
            max_in_flight,
            deferred_flush_timeout,
            registry_config,
            0,
            ComponentOptions::new(),
            common::PRODUCTION_PACK_TARGETS,
            None,
            CompletionGranularity::Poll,
            COMMIT_INTERVAL,
            BudgetLimits::unset(),
            Polling::Capped,
            ChargeLimit::unset(),
        )
        .await
    }

    /// One worker; every request carries a 500 ms soft budget.
    async fn start_budgeted(topic: &str, partitions: i32) -> Self {
        Self::start_inner(
            topic,
            partitions,
            1,
            // A poll can end after one message, so later polls must reach the
            // packer while the first waits for its run. Every poll under a
            // held request also stays in flight, and a full cap stops polling.
            512,
            Duration::from_secs(60),
            fast_registry_config(),
            0,
            ComponentOptions::new(),
            // A request waits for four events per partition, which one
            // `alternating_visitors` call per partition fills.
            PackTargets {
                events: NonZeroUsize::new(4 * partitions as usize),
                bytes: None,
                latency_budget: Duration::from_secs(5),
            },
            Some(RequestBudget {
                soft_budget: Duration::from_millis(500),
                attempts: BUDGET_ATTEMPTS,
            }),
            CompletionGranularity::Poll,
            COMMIT_INTERVAL,
            BudgetLimits::unset(),
            Polling::Capped,
            ChargeLimit::unset(),
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    async fn start_with_pack_targets(
        topic: &str,
        partitions: i32,
        worker_count: usize,
        max_in_flight: usize,
        deferred_flush_timeout: Duration,
        registry_config: WorkerRegistryConfig,
        pack_targets: PackTargets,
    ) -> Self {
        Self::start_inner(
            topic,
            partitions,
            worker_count,
            max_in_flight,
            deferred_flush_timeout,
            registry_config,
            0,
            ComponentOptions::new(),
            pack_targets,
            None,
            CompletionGranularity::Poll,
            COMMIT_INTERVAL,
            BudgetLimits::unset(),
            Polling::Capped,
            ChargeLimit::unset(),
        )
        .await
    }

    async fn start_with_liveness(
        topic: &str,
        worker_count: usize,
        deferred_flush_timeout: Duration,
        liveness_deadline: Duration,
        stall_threshold: u32,
    ) -> Self {
        Self::start_inner(
            topic,
            1,
            worker_count,
            1,
            deferred_flush_timeout,
            fast_registry_config(),
            0,
            ComponentOptions::new()
                .with_liveness_deadline(liveness_deadline)
                .with_stall_threshold(stall_threshold),
            common::ONE_MESSAGE_PER_REQUEST,
            None,
            CompletionGranularity::Poll,
            COMMIT_INTERVAL,
            BudgetLimits::unset(),
            Polling::Capped,
            ChargeLimit::unset(),
        )
        .await
    }

    async fn start_polling(
        topic: &str,
        partitions: i32,
        worker_count: usize,
        max_in_flight: usize,
        batch_size_bytes: usize,
        polling: Polling,
    ) -> Self {
        let (granularity, partition_budget, in_flight_limit) = match polling {
            Polling::Capped => (
                CompletionGranularity::Poll,
                BudgetLimits::unset(),
                ChargeLimit::unset(),
            ),
            Polling::Continuous => (
                CompletionGranularity::Group,
                BudgetLimits::new(
                    NonZeroU64::new(10_000),
                    NonZeroU64::new(UNBOUNDED_BYTES),
                    0.8,
                )
                .expect("a valid budget"),
                ChargeLimit::new(NonZeroU64::new(100_000), NonZeroU64::new(UNBOUNDED_BYTES)),
            ),
        };
        Self::start_inner(
            topic,
            partitions,
            worker_count,
            max_in_flight,
            Duration::from_secs(60),
            fast_registry_config(),
            batch_size_bytes,
            ComponentOptions::new(),
            common::PRODUCTION_PACK_TARGETS,
            None,
            granularity,
            COMMIT_INTERVAL,
            partition_budget,
            polling,
            in_flight_limit,
        )
        .await
    }

    async fn start_byte_capped(topic: &str, batch_size_bytes: usize, polling: Polling) -> Self {
        Self::start_polling(topic, 1, 1, 1, batch_size_bytes, polling).await
    }

    async fn start_group_granularity(
        pack_targets: PackTargets,
        topic: &str,
        partitions: i32,
        worker_count: usize,
        max_in_flight: usize,
    ) -> Self {
        Self::start_group_granularity_committing_every(
            pack_targets,
            topic,
            partitions,
            worker_count,
            max_in_flight,
            COMMIT_INTERVAL,
        )
        .await
    }

    async fn start_group_granularity_committing_every(
        pack_targets: PackTargets,
        topic: &str,
        partitions: i32,
        worker_count: usize,
        max_in_flight: usize,
        commit_interval: Duration,
    ) -> Self {
        Self::start_inner(
            topic,
            partitions,
            worker_count,
            max_in_flight,
            Duration::from_secs(60),
            fast_registry_config(),
            0,
            ComponentOptions::new(),
            pack_targets,
            None,
            CompletionGranularity::Group,
            commit_interval,
            BudgetLimits::unset(),
            Polling::Capped,
            ChargeLimit::unset(),
        )
        .await
    }

    async fn start_with_partition_budget(
        pack_targets: PackTargets,
        topic: &str,
        partitions: i32,
        worker_count: usize,
        partition_budget: BudgetLimits,
        polling: Polling,
    ) -> Self {
        let (max_in_flight, in_flight_limit) = match polling {
            Polling::Capped => (8, ChargeLimit::unset()),
            // One poll slot: the continuous loop must not wait on any poll.
            Polling::Continuous => (
                1,
                ChargeLimit::new(NonZeroU64::new(1_000), NonZeroU64::new(UNBOUNDED_BYTES)),
            ),
        };
        Self::start_inner(
            topic,
            partitions,
            worker_count,
            max_in_flight,
            Duration::from_secs(60),
            fast_registry_config(),
            0,
            ComponentOptions::new(),
            pack_targets,
            None,
            CompletionGranularity::Group,
            COMMIT_INTERVAL,
            partition_budget,
            polling,
            in_flight_limit,
        )
        .await
    }

    async fn start_continuous(
        pack_targets: PackTargets,
        topic: &str,
        partitions: i32,
        worker_count: usize,
        partition_budget: BudgetLimits,
        in_flight_limit: ChargeLimit,
    ) -> Self {
        Self::start_inner(
            topic,
            partitions,
            worker_count,
            1,
            Duration::from_secs(60),
            fast_registry_config(),
            0,
            ComponentOptions::new(),
            pack_targets,
            None,
            CompletionGranularity::Group,
            COMMIT_INTERVAL,
            partition_budget,
            Polling::Continuous,
            in_flight_limit,
        )
        .await
    }

    async fn start_with_partition_budget_committing_every(
        pack_targets: PackTargets,
        topic: &str,
        partitions: i32,
        worker_count: usize,
        partition_budget: BudgetLimits,
        commit_interval: Duration,
    ) -> Self {
        Self::start_inner(
            topic,
            partitions,
            worker_count,
            8,
            Duration::from_secs(60),
            fast_registry_config(),
            0,
            ComponentOptions::new(),
            pack_targets,
            None,
            CompletionGranularity::Group,
            commit_interval,
            partition_budget,
            Polling::Capped,
            ChargeLimit::unset(),
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    async fn start_inner(
        topic: &str,
        partitions: i32,
        worker_count: usize,
        max_in_flight: usize,
        deferred_flush_timeout: Duration,
        registry_config: WorkerRegistryConfig,
        batch_size_bytes: usize,
        component_options: ComponentOptions,
        pack_targets: PackTargets,
        budget: Option<RequestBudget>,
        completion_granularity: CompletionGranularity,
        commit_interval: Duration,
        partition_budget: BudgetLimits,
        polling: Polling,
        in_flight_limit: ChargeLimit,
    ) -> Self {
        create_topic(topic, partitions).await;

        let delivery_log: DeliveryLog = Arc::new(Mutex::new(Vec::new()));
        let mut workers = Vec::new();
        for _ in 0..worker_count {
            workers.push(FakeWorker::start_logged(Arc::clone(&delivery_log)).await);
        }
        let worker_urls: Vec<String> = workers.iter().map(|w| w.url.clone()).collect();

        let registry = Arc::new(WorkerRegistry::new(&worker_urls, registry_config));
        let probe_token = CancellationToken::new();
        Arc::clone(&registry).start_probing(probe_token.clone());

        let pool_source = WorkerPoolSource::new(Arc::clone(&registry), RoutingStrategy::default());
        let registry_for_test = Arc::clone(&registry);
        let transport = Arc::new(test_transport());

        let mut manager = Manager::builder("e2e-test")
            .with_trap_signals(false)
            .with_health_poll_interval(Duration::from_millis(100))
            .build();
        let handle = manager.register("consumer", component_options);
        let shutdown = handle.shutdown_token();
        let _monitor = manager.monitor_background();

        let group_id = format!("e2e-{}", Uuid::new_v4());
        let ledger = Arc::new(TopicOffsetLedger::new());
        let debug_recorder = DebugRecorder::new(10_000, Duration::from_secs(3600));
        let kafka_consumer =
            make_kafka_consumer_with_context(topic, &group_id, None, RebalanceContext::new());

        let (batcher, outputs) = common::batcher(
            pool_source,
            Arc::clone(&transport),
            deferred_flush_timeout,
            Duration::from_millis(200),
            pack_targets,
            budget,
        );
        let consumer = IngestionConsumer::from_parts(
            kafka_consumer,
            batcher,
            outputs,
            Arc::clone(&transport),
            worker_urls,
            IngestionConsumerOptions {
                batch_size: 50,
                batch_size_bytes,
                batch_timeout: Duration::from_millis(100),
                max_in_flight_batches: max_in_flight,
                group_id: "e2e-test".to_string(),
                debug_recorder: Some(Arc::clone(&debug_recorder)),
                completion_granularity,
                commit_interval,
                ledger: Arc::clone(&ledger),
                partition_budget,
                polling,
                in_flight_limit,
            },
            handle,
        );
        let observer = consumer.batcher_observer();
        spawn_reaper(
            Arc::clone(&registry),
            transport,
            observer.clone(),
            probe_token.clone(),
        );

        let task = tokio::spawn(async move { consumer.process().await });

        // Give the consumer time to connect and enter the poll loop.
        tokio::time::sleep(Duration::from_millis(300)).await;

        Self {
            workers,
            registry: registry_for_test,
            observer,
            delivery_log,
            shutdown,
            task: Some(task),
            _probe_token: probe_token,
            topic: topic.to_string(),
            group_id,
            ledger,
            debug_recorder,
            max_in_flight,
            deferred_flush_timeout,
            pack_targets,
            budget,
            completion_granularity,
            partition_budget,
            polling,
            in_flight_limit,
        }
    }

    /// Message count of each poll the consumer dispatched, before the packer merges any.
    fn poll_sizes(&self) -> Vec<usize> {
        self.debug_recorder
            .backlog()
            .into_iter()
            .filter_map(|event| match event.kind {
                DebugEventKind::BatchDispatched { messages, .. } => Some(messages),
                _ => None,
            })
            .collect()
    }

    /// Abort the consumer task: no shutdown, no drain, no final commit.
    fn crash_consumer(&mut self) {
        if let Some(task) = self.task.take() {
            task.abort();
        }
    }

    /// Model a pod restart: a new consumer stack in the same group, against the same workers.
    async fn restart_consumer(&mut self, registry_config: WorkerRegistryConfig) {
        let worker_urls: Vec<String> = self.workers.iter().map(|w| w.url.clone()).collect();

        let registry = Arc::new(WorkerRegistry::new(&worker_urls, registry_config));
        Arc::clone(&registry).start_probing(self._probe_token.clone());
        let pool_source = WorkerPoolSource::new(Arc::clone(&registry), RoutingStrategy::default());
        let transport = Arc::new(test_transport());

        let mut manager = Manager::builder("e2e-test-restarted")
            .with_trap_signals(false)
            .build();
        let handle = manager.register("consumer", ComponentOptions::new());
        self.shutdown = handle.shutdown_token();

        self.ledger = Arc::new(TopicOffsetLedger::new());
        let kafka_consumer = make_kafka_consumer_with_context(
            &self.topic,
            &self.group_id,
            None,
            RebalanceContext::new(),
        );
        let (batcher, outputs) = common::batcher(
            pool_source,
            Arc::clone(&transport),
            self.deferred_flush_timeout,
            Duration::from_millis(200),
            self.pack_targets,
            self.budget,
        );
        let consumer = IngestionConsumer::from_parts(
            kafka_consumer,
            batcher,
            outputs,
            Arc::clone(&transport),
            worker_urls,
            IngestionConsumerOptions {
                batch_size: 50,
                batch_size_bytes: 0,
                batch_timeout: Duration::from_millis(100),
                max_in_flight_batches: self.max_in_flight,
                group_id: "e2e-test".to_string(),
                debug_recorder: None,
                completion_granularity: self.completion_granularity,
                commit_interval: COMMIT_INTERVAL,
                ledger: Arc::clone(&self.ledger),
                partition_budget: self.partition_budget,
                polling: self.polling,
                in_flight_limit: self.in_flight_limit,
            },
            handle,
        );
        self.observer = consumer.batcher_observer();
        spawn_reaper(
            Arc::clone(&registry),
            transport,
            self.observer.clone(),
            self._probe_token.clone(),
        );

        self.registry = registry;
        self.task = Some(tokio::spawn(async move { consumer.process().await }));

        // Give the restarted consumer time to rejoin the group and start polling.
        tokio::time::sleep(Duration::from_millis(300)).await;
    }

    async fn wait_for_consumer_exit(&mut self, timeout: Duration) -> bool {
        let Some(task) = self.task.take() else {
            return true;
        };
        tokio::time::timeout(timeout, task).await.is_ok()
    }

    fn committed_offset(&self, partition: i32) -> Option<i64> {
        broker_committed_offset(&self.group_id, &self.topic, partition)
    }

    async fn wait_for(&self, total: usize, timeout: Duration) {
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            let got: usize = self.workers.iter().map(|w| w.count()).sum();
            if got >= total {
                return;
            }
            assert!(
                tokio::time::Instant::now() < deadline,
                "timed out waiting for {total} messages (got {got})"
            );
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    }

    async fn stop(mut self) {
        self.shutdown.cancel();
        if let Some(task) = self.task.take() {
            let _ = tokio::time::timeout(Duration::from_secs(3), task).await;
        }
    }

    /// A second consumer in the same group, over the same workers, as a second pod.
    async fn join_second_consumer(&self) -> SecondConsumer {
        let worker_urls: Vec<String> = self.workers.iter().map(|w| w.url.clone()).collect();
        let registry = Arc::new(WorkerRegistry::new(&worker_urls, fast_registry_config()));
        let probe = CancellationToken::new();
        Arc::clone(&registry).start_probing(probe.clone());
        let pool_source = WorkerPoolSource::new(Arc::clone(&registry), RoutingStrategy::default());
        let transport = Arc::new(test_transport());
        let mut manager = Manager::builder("e2e-c2").with_trap_signals(false).build();
        let handle = manager.register("consumer", ComponentOptions::new());
        let shutdown = handle.shutdown_token();
        let (batcher, outputs) = common::batcher(
            pool_source,
            Arc::clone(&transport),
            self.deferred_flush_timeout,
            Duration::from_millis(200),
            self.pack_targets,
            self.budget,
        );
        let consumer = IngestionConsumer::from_parts(
            make_kafka_consumer(&self.topic, &self.group_id, None),
            batcher,
            outputs,
            transport,
            worker_urls,
            IngestionConsumerOptions {
                batch_size: 50,
                batch_size_bytes: 0,
                batch_timeout: Duration::from_millis(100),
                max_in_flight_batches: self.max_in_flight,
                group_id: "e2e-test".to_string(),
                debug_recorder: None,
                completion_granularity: self.completion_granularity,
                commit_interval: COMMIT_INTERVAL,
                ledger: Arc::new(TopicOffsetLedger::new()),
                partition_budget: self.partition_budget,
                polling: self.polling,
                in_flight_limit: self.in_flight_limit,
            },
            handle,
        );
        let task = tokio::spawn(async move { consumer.process().await });
        SecondConsumer {
            shutdown,
            probe,
            task,
            _manager: manager,
        }
    }
}

struct SecondConsumer {
    shutdown: CancellationToken,
    probe: CancellationToken,
    task: tokio::task::JoinHandle<()>,
    _manager: Manager,
}

impl SecondConsumer {
    async fn stop(self) {
        self.shutdown.cancel();
        let _ = tokio::time::timeout(Duration::from_secs(5), self.task).await;
        self.probe.cancel();
    }
}

fn fast_registry_config() -> WorkerRegistryConfig {
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
    }
}

fn broker_committed_offset(group_id: &str, topic: &str, partition: i32) -> Option<i64> {
    let probe: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", group_id)
        .create()
        .expect("committed-offset probe");
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition(topic, partition);
    let committed = probe
        .committed_offsets(tpl, Duration::from_secs(2))
        .expect("fetch committed offsets");
    match committed.elements()[0].offset() {
        rdkafka::Offset::Offset(offset) => Some(offset),
        _ => None,
    }
}

async fn wait_until(timeout: Duration, msg: &str, mut cond: impl FnMut() -> bool) {
    let deadline = tokio::time::Instant::now() + timeout;
    while !cond() {
        assert!(
            tokio::time::Instant::now() < deadline,
            "timed out waiting for: {msg}"
        );
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

fn sole_arrived_worker(harness: &Harness) -> usize {
    let arrived: Vec<usize> = harness
        .workers
        .iter()
        .enumerate()
        .filter(|(_, w)| w.arrived_count() > 0)
        .map(|(i, _)| i)
        .collect();
    assert_eq!(
        arrived.len(),
        1,
        "expected exactly one worker to have a batch in flight, got {arrived:?}"
    );
    arrived[0]
}

#[rstest]
#[case::production_targets(common::PRODUCTION_PACK_TARGETS)]
#[case::one_message_per_request(common::ONE_MESSAGE_PER_REQUEST)]
#[tokio::test]
async fn messages_per_distinct_id_arrive_in_order(#[case] pack_targets: PackTargets) {
    let topic = format!("e2e-ordering-{}", Uuid::new_v4());
    let harness = Harness::start_with_pack_targets(
        &topic,
        3,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
        pack_targets,
    )
    .await;

    let producer = make_producer();
    for seq in 0..8usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
        produce(&producer, &topic, 2, "tok", "user-3", seq).await;
    }

    harness.wait_for(24, Duration::from_secs(15)).await;

    let total: usize = harness.workers.iter().map(|w| w.count()).sum();
    assert_eq!(total, 24, "expected 24 messages total, got {total}");

    // A key can move between workers across requests, so order holds per worker.
    for worker in &harness.workers {
        for user in ["user-1", "user-2", "user-3"] {
            let seqs = worker.seqs_for(user);
            assert!(
                seqs.windows(2).all(|w| w[0] < w[1]),
                "{user} arrived out of order on a worker: {seqs:?}"
            );
        }
    }

    harness.stop().await;
}

#[tokio::test]
async fn a_partial_ack_redelivers_only_the_unfinished_messages() {
    let topic = format!("e2e-partial-{}", Uuid::new_v4());
    let harness = Harness::start_budgeted(&topic, 1).await;
    *harness.workers[0].leave_unfinished.lock().unwrap() = Some(("visitor-a".to_string(), 1));

    produce_keyed_in_one_transaction(
        &topic,
        "tok",
        &alternating_visitors(0, "tok:203.0.113.7", 0),
    )
    .await;
    // A commit means every resend settled, so a late duplicate is in the log.
    wait_until(Duration::from_secs(15), "the offsets commit", || {
        harness
            .committed_offset(0)
            .is_some_and(|offset| offset >= 4)
    })
    .await;

    let worker = &harness.workers[0];
    assert_eq!(
        worker.batch_sizes()[0],
        4,
        "all four messages ride one request: sizes {:?}",
        worker.batch_sizes()
    );
    assert_eq!(worker.seqs_for("visitor-a"), vec![0, 2]);
    assert_eq!(worker.seqs_for("visitor-b"), vec![1, 3]);
    assert_eq!(
        *worker.replayed.lock().unwrap(),
        vec![("visitor-a".to_string(), 0), ("visitor-a".to_string(), 2)],
        "only the unfinished messages are redelivered, marked as replay"
    );

    harness.stop().await;
}

#[tokio::test]
async fn a_crash_before_a_partial_acks_resend_loses_nothing() {
    let topic = format!("e2e-partial-crash-{}", Uuid::new_v4());
    let mut harness = Harness::start_budgeted(&topic, 1).await;
    *harness.workers[0].leave_unfinished.lock().unwrap() = Some(("visitor-a".to_string(), 1));
    // The resend never settles, so it is still in flight at the crash.
    harness.workers[0]
        .hold_replays
        .store(true, Ordering::SeqCst);

    produce_keyed_in_one_transaction(
        &topic,
        "tok",
        &alternating_visitors(0, "tok:203.0.113.7", 0),
    )
    .await;
    wait_until(
        Duration::from_secs(15),
        "the resend to reach the worker",
        || harness.workers[0].arrived_count() >= 2,
    )
    .await;
    assert!(
        harness.workers[0].seqs_for("visitor-a").is_empty(),
        "visitor A's messages are unfinished"
    );

    // Commits are async: wait so a wrong commit lands before the crash.
    tokio::time::sleep(Duration::from_millis(500)).await;
    assert_eq!(
        harness.committed_offset(0),
        None,
        "nothing commits while an unfinished message waits for its resend"
    );

    harness.crash_consumer();
    harness.restart_consumer(fast_registry_config()).await;

    wait_until(
        Duration::from_secs(30),
        "the offsets to commit after the restart",
        || {
            harness
                .committed_offset(0)
                .is_some_and(|offset| offset >= 4)
        },
    )
    .await;
    assert_eq!(
        harness.workers[0].seqs_for("visitor-a"),
        vec![0, 2],
        "the restarted consumer delivers the unfinished messages"
    );

    harness.stop().await;
}

#[tokio::test]
async fn a_partial_ack_after_a_revoke_resends_nothing() {
    let topic = format!("e2e-partial-revoke-{}", Uuid::new_v4());
    let harness = Harness::start_budgeted(&topic, 2).await;
    *harness.workers[0].leave_unfinished.lock().unwrap() = Some(("visitor-a".to_string(), 1));
    let partitions = [
        TopicPartition::new(topic.clone(), 0),
        TopicPartition::new(topic.clone(), 1),
    ];
    let records: Vec<_> = alternating_visitors(0, "tok:203.0.113.7", 0)
        .into_iter()
        .chain(alternating_visitors(1, "tok:203.0.113.8", 10))
        .collect();

    // A trickle keeps the consumer polling, so it takes part in the rebalance.
    let producer = make_producer();
    producer
        .client()
        .fetch_metadata(Some(&topic), Duration::from_secs(5))
        .expect("trickle producer metadata");

    // Hold the first request; the trickle's requests queue behind it (one un-acked per worker).
    let gate = harness.workers[0].block().await;
    produce_keyed_in_one_transaction(&topic, "tok", &records).await;
    let trickling = Arc::new(AtomicBool::new(true));
    let trickle = tokio::spawn({
        let trickling = Arc::clone(&trickling);
        let topic = topic.clone();
        async move {
            let mut seq = 1000usize;
            while trickling.load(Ordering::SeqCst) {
                produce(&producer, &topic, 0, "tok", "trickle", seq).await;
                seq += 1;
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
        }
    });
    wait_until(
        Duration::from_secs(15),
        "a request to reach the worker",
        || harness.workers[0].arrived_count() > 0,
    )
    .await;
    let generations: Vec<u64> = partitions
        .iter()
        .map(|partition| harness.ledger.generation(partition))
        .collect();

    let second = harness.join_second_consumer().await;

    // Wait under the 10 s ack timeout, after which the held request returns as a replay.
    wait_until(
        Duration::from_secs(8),
        "the rebalance to revoke both partitions",
        || {
            partitions
                .iter()
                .zip(&generations)
                .all(|(partition, before)| harness.ledger.generation(partition) > *before)
        },
    )
    .await;
    trickling.store(false, Ordering::SeqCst);
    trickle.await.expect("trickle task");
    drop(gate);

    wait_until(
        Duration::from_secs(30),
        "every message to be delivered",
        || {
            let delivered: HashSet<(String, usize)> = harness
                .delivery_log
                .lock()
                .unwrap()
                .iter()
                .cloned()
                .collect();
            records
                .iter()
                .all(|(_, _, visitor, seq)| delivered.contains(&(visitor.to_string(), *seq)))
        },
    )
    .await;
    // The old owner may not have settled the partial ack yet; wait for it.
    wait_until(
        Duration::from_secs(15),
        "the old owner to settle the partial ack",
        || harness.observer.total_in_flight() == 0,
    )
    .await;
    assert!(
        harness.workers[0]
            .leave_unfinished
            .lock()
            .unwrap()
            .is_none(),
        "the held request was acked as partial"
    );
    assert_eq!(
        *harness.workers[0].replayed.lock().unwrap(),
        Vec::<(String, usize)>::new(),
        "the old owner resends nothing for a revoked partition"
    );

    second.stop().await;
    harness.stop().await;
}

#[tokio::test]
async fn a_message_that_never_fits_the_budget_lands_without_one() {
    let topic = format!("e2e-partial-escalate-{}", Uuid::new_v4());
    let harness = Harness::start_budgeted(&topic, 1).await;
    *harness.workers[0].leave_unfinished.lock().unwrap() =
        Some(("visitor-a".to_string(), usize::MAX));

    produce_keyed_in_one_transaction(
        &topic,
        "tok",
        &alternating_visitors(0, "tok:203.0.113.7", 0),
    )
    .await;
    wait_until(Duration::from_secs(15), "the offsets commit", || {
        harness
            .committed_offset(0)
            .is_some_and(|offset| offset >= 4)
    })
    .await;

    let worker = &harness.workers[0];
    assert_eq!(worker.seqs_for("visitor-a"), vec![0, 2]);
    assert_eq!(worker.seqs_for("visitor-b"), vec![1, 3]);
    assert_eq!(
        worker.batch_sizes(),
        vec![4, 2, 2],
        "visitor A goes out once more with a budget, then once without"
    );

    harness.stop().await;
}

#[rstest]
#[case::capped(Polling::Capped)]
#[case::continuous(Polling::Continuous)]
#[tokio::test]
async fn byte_bound_caps_batches_below_the_count_bound(#[case] polling: Polling) {
    let topic = format!("e2e-bytecap-{}", Uuid::new_v4());
    let harness = Harness::start_byte_capped(&topic, 4096, polling).await;

    let producer = make_producer();
    let payload = vec![b'x'; 2048];
    for seq in 0..12usize {
        produce_raw(
            &producer,
            &topic,
            0,
            &format!("tok:user-1:{seq}"),
            &payload,
            None,
        )
        .await;
    }

    harness.wait_for(12, Duration::from_secs(20)).await;

    let sizes = harness.poll_sizes();
    assert_eq!(
        sizes.iter().sum::<usize>(),
        12,
        "every message must still be polled, got polls {sizes:?}"
    );
    // A batch timeout only shrinks polls, so producer timing cannot break this.
    assert!(
        sizes.iter().all(|&n| n <= 2),
        "no poll may exceed the byte bound by more than one message, got {sizes:?}"
    );

    harness.stop().await;
}

#[rstest]
#[case::capped(Polling::Capped)]
#[case::continuous(Polling::Continuous)]
#[tokio::test]
async fn message_larger_than_byte_bound_is_still_delivered(#[case] polling: Polling) {
    let topic = format!("e2e-bytecap-oversize-{}", Uuid::new_v4());
    let harness = Harness::start_byte_capped(&topic, 4096, polling).await;

    let producer = make_producer();
    produce_raw(
        &producer,
        &topic,
        0,
        "tok:user-1:0",
        &vec![b'x'; 16384],
        None,
    )
    .await;

    harness.wait_for(1, Duration::from_secs(20)).await;

    assert_eq!(
        harness.workers[0].batch_sizes(),
        vec![1],
        "the oversized message must arrive as a batch of one"
    );

    harness.stop().await;
}

#[tokio::test]
async fn failing_worker_triggers_rerouting() {
    let topic = format!("e2e-failover-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        2,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;

    let producer = make_producer();

    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    harness.wait_for(8, Duration::from_secs(10)).await;

    let dead_idx = if !harness.workers[0].seqs_for("user-1").is_empty() {
        0
    } else {
        1
    };
    let live_idx = 1 - dead_idx;

    harness.workers[dead_idx]
        .healthy
        .store(false, Ordering::Relaxed);

    tokio::time::sleep(Duration::from_millis(600)).await;

    for seq in 4..8usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    harness.wait_for(12, Duration::from_secs(10)).await;

    let live_seqs = harness.workers[live_idx].seqs_for("user-1");
    let batch2_seqs: Vec<usize> = live_seqs.iter().copied().filter(|&s| s >= 4).collect();
    assert_eq!(
        batch2_seqs,
        vec![4, 5, 6, 7],
        "batch-2 messages for user-1 missing or out-of-order on live worker: {live_seqs:?}"
    );

    harness.stop().await;
}

#[tokio::test]
async fn failed_sends_degrade_passive_health() {
    let topic = format!("e2e-passive-fault-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        1,
        1,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    harness.workers[0].ingest_ok.store(false, Ordering::SeqCst);
    produce(&producer, &topic, 0, "tok", "user-1", 0).await;

    let worker = harness.workers[0].url.clone();
    wait_until(
        Duration::from_secs(10),
        "failed sends to degrade the worker",
        || harness.registry.state(&worker) != WorkerState::Healthy,
    )
    .await;

    harness.workers[0].ingest_ok.store(true, Ordering::SeqCst);
    harness.stop().await;
}

#[tokio::test]
async fn draining_worker_takes_no_new_work_and_reroutes_in_order() {
    let topic = format!("e2e-drain-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        2,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;

    let producer = make_producer();

    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    harness.wait_for(8, Duration::from_secs(10)).await;

    let drain_idx = if !harness.workers[0].seqs_for("user-1").is_empty() {
        0
    } else {
        1
    };
    let live_idx = 1 - drain_idx;
    let drain_url = harness.workers[drain_idx].url.clone();
    harness.registry.start_draining(&drain_url);

    wait_until(Duration::from_secs(2), "idle drainer to be reaped", || {
        !harness
            .registry
            .workers()
            .iter()
            .any(|w| w.as_ref() == drain_url)
    })
    .await;

    for seq in 4..8usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    harness.wait_for(12, Duration::from_secs(10)).await;

    let mut all_user1: Vec<usize> = harness
        .workers
        .iter()
        .flat_map(|w| w.seqs_for("user-1"))
        .collect();
    all_user1.sort_unstable();
    assert_eq!(
        all_user1,
        (0..8).collect::<Vec<_>>(),
        "user-1 messages were lost or duplicated: {all_user1:?}"
    );

    let drained_seqs = harness.workers[drain_idx].seqs_for("user-1");
    assert!(
        drained_seqs.iter().all(|&s| s < 4),
        "draining worker received new work: {drained_seqs:?}"
    );

    let live_batch2: Vec<usize> = harness.workers[live_idx]
        .seqs_for("user-1")
        .into_iter()
        .filter(|&s| s >= 4)
        .collect();
    assert_eq!(
        live_batch2,
        vec![4, 5, 6, 7],
        "batch-2 messages misrouted or out of order on the live worker: {live_batch2:?}"
    );

    harness.stop().await;
}

/// Whether `url` is currently routable (healthy or degraded) per the registry.
fn in_pool(harness: &Harness, url: &str) -> bool {
    harness
        .registry
        .healthy_workers()
        .iter()
        .any(|w| w.as_ref() == url)
}

#[tokio::test]
async fn send_failure_mid_flight_replays_to_survivor_in_order() {
    let topic = format!("e2e-replay-single-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        1,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    // Freeze both workers so whichever gets the batch holds it in flight.
    let mut guards: Vec<Option<tokio::sync::OwnedMutexGuard<()>>> = Vec::new();
    for w in &harness.workers {
        guards.push(Some(w.block().await));
    }

    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    wait_until(Duration::from_secs(10), "batch to reach a worker", || {
        harness.workers.iter().any(|w| w.arrived_count() > 0)
    })
    .await;
    let failed = sole_arrived_worker(&harness);
    let survivor = 1 - failed;

    harness.workers[failed]
        .healthy
        .store(false, Ordering::SeqCst);
    guards[survivor] = None;
    guards[failed] = None;

    harness.wait_for(4, Duration::from_secs(10)).await;

    assert_eq!(
        harness.workers[failed].count(),
        0,
        "the failed worker recorded nothing (it only returned errors)"
    );
    assert_eq!(
        harness.workers[survivor].seqs_for("user-1"),
        vec![0, 1, 2, 3],
        "user-1 must replay to the survivor in Kafka order"
    );

    harness.stop().await;
}

#[tokio::test]
async fn partial_send_failure_replays_only_the_failed_subbatch() {
    let topic = format!("e2e-replay-partial-{}", Uuid::new_v4());
    let one_key_of_four_per_request = PackTargets {
        events: NonZeroUsize::new(4),
        bytes: None,
        latency_budget: Duration::ZERO,
    };
    let harness = Harness::start_with_pack_targets(
        &topic,
        1,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
        one_key_of_four_per_request,
    )
    .await;

    let mut guards: Vec<Option<tokio::sync::OwnedMutexGuard<()>>> = Vec::new();
    for w in &harness.workers {
        guards.push(Some(w.block().await));
    }

    // One poll must carry both keys; at max_in_flight=1 a one-key poll would block the second.
    let records: Vec<(&str, usize)> = (0..4usize)
        .flat_map(|seq| [("user-1", seq), ("user-2", seq)])
        .collect();
    produce_in_one_transaction(&topic, 0, "tok", &records).await;
    wait_until(
        Duration::from_secs(10),
        "both workers to receive a sub-batch",
        || harness.workers.iter().all(|w| w.arrived_count() > 0),
    )
    .await;

    harness.workers[0].healthy.store(false, Ordering::SeqCst);
    guards[1] = None;
    guards[0] = None;

    harness.wait_for(8, Duration::from_secs(15)).await;

    assert_eq!(
        harness.workers[0].count(),
        0,
        "failed worker recorded nothing"
    );
    assert_eq!(
        harness.workers[1].seqs_for("user-1"),
        vec![0, 1, 2, 3],
        "user-1 fully on the survivor in order"
    );
    assert_eq!(
        harness.workers[1].seqs_for("user-2"),
        vec![0, 1, 2, 3],
        "user-2 (the originally-successful sub-batch) intact, not duplicated"
    );

    harness.stop().await;
}

#[tokio::test]
async fn deferred_flush_retries_until_a_worker_recovers() {
    let topic = format!("e2e-replay-wait-{}", Uuid::new_v4());
    let liveness_deadline = Duration::from_millis(1500);
    let harness =
        Harness::start_with_liveness(&topic, 2, Duration::from_secs(60), liveness_deadline, 2)
            .await;
    let producer = make_producer();

    // Take worker 1 out of the pool so the batch routes to worker 0.
    harness.workers[1].healthy.store(false, Ordering::SeqCst);
    wait_until(
        Duration::from_secs(10),
        "worker 1 to leave the pool",
        || !in_pool(&harness, &harness.workers[1].url),
    )
    .await;

    let guard0 = harness.workers[0].block().await;
    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    wait_until(Duration::from_secs(10), "batch to reach worker 0", || {
        harness.workers[0].arrived_count() > 0
    })
    .await;

    // Fail worker 0 too: now there is nowhere to replay.
    harness.workers[0].healthy.store(false, Ordering::SeqCst);
    drop(guard0);

    // Only the oldest poll is stashed, so read its count rather than assert 4.
    wait_until(
        Duration::from_secs(10),
        "worker 0 to leave the pool",
        || !in_pool(&harness, &harness.workers[0].url),
    )
    .await;
    wait_until(
        Duration::from_secs(10),
        "the failed send to be deferred",
        || harness.observer.pending_messages() > 0,
    )
    .await;

    let held = harness.observer.pending_messages();
    tokio::time::sleep(liveness_deadline * 4).await;
    assert_eq!(
        harness.observer.pending_messages(),
        held,
        "deferred work must be held steady while no worker is available"
    );
    assert!(
        !harness.shutdown.is_cancelled(),
        "waiting for a worker must keep the liveness heartbeat going"
    );

    // Worker 1 rejoins blocked, so the flush waits on it past the liveness deadline.
    let guard1 = harness.workers[1].block().await;
    harness.workers[1].healthy.store(true, Ordering::SeqCst);
    wait_until(Duration::from_secs(10), "replay to reach worker 1", || {
        harness.workers[1].arrived_count() > 0
    })
    .await;
    tokio::time::sleep(liveness_deadline * 4).await;
    assert!(
        !harness.shutdown.is_cancelled(),
        "waiting on a slow worker must keep the liveness heartbeat going"
    );

    drop(guard1);
    harness.wait_for(4, Duration::from_secs(15)).await;

    assert_eq!(
        harness.workers[1].seqs_for("user-1"),
        vec![0, 1, 2, 3],
        "deferred user-1 must flush to the recovered worker in order"
    );
    assert_eq!(
        harness.workers[0].count(),
        0,
        "failed worker recorded nothing"
    );

    harness.stop().await;
}

#[tokio::test]
async fn no_worker_exit_comes_from_the_flush_timeout_not_a_liveness_stall() {
    let topic = format!("e2e-flush-timeout-liveness-{}", Uuid::new_v4());
    let flush_timeout = Duration::from_secs(4);
    let liveness_deadline = Duration::from_millis(1500);
    let mut harness =
        Harness::start_with_liveness(&topic, 2, flush_timeout, liveness_deadline, 2).await;
    let producer = make_producer();

    harness.workers[1].healthy.store(false, Ordering::SeqCst);
    wait_until(
        Duration::from_secs(10),
        "worker 1 to leave the pool",
        || !in_pool(&harness, &harness.workers[1].url),
    )
    .await;

    let guard0 = harness.workers[0].block().await;
    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    wait_until(Duration::from_secs(10), "batch to reach worker 0", || {
        harness.workers[0].arrived_count() > 0
    })
    .await;

    harness.workers[0].healthy.store(false, Ordering::SeqCst);
    drop(guard0);
    wait_until(
        Duration::from_secs(10),
        "the failed send to be deferred",
        || harness.observer.pending_messages() > 0,
    )
    .await;
    let deferred_at = tokio::time::Instant::now();

    assert!(
        harness
            .wait_for_consumer_exit(Duration::from_secs(20))
            .await,
        "consumer must fail the batch once nothing lands for a full flush timeout"
    );
    let waited = deferred_at.elapsed();
    assert!(
        waited >= flush_timeout * 3 / 4,
        "consumer exited after {waited:?}: a liveness stall, not the {flush_timeout:?} flush timeout"
    );
    assert_eq!(
        harness.workers.iter().map(|w| w.count()).sum::<usize>(),
        0,
        "nothing should be delivered"
    );
}

#[tokio::test]
async fn slow_deferred_drain_with_progress_outlasts_the_flush_timeout() {
    let topic = format!("e2e-slow-drain-{}", Uuid::new_v4());
    let flush_timeout = Duration::from_secs(3);
    let liveness_deadline = Duration::from_millis(1500);
    let harness =
        Harness::start_with_liveness(&topic, 3, flush_timeout, liveness_deadline, 2).await;
    let producer = make_producer();

    // Workers 1 and 2 out, so both keys route to worker 0 together.
    for i in [1, 2] {
        harness.workers[i].healthy.store(false, Ordering::SeqCst);
    }
    wait_until(
        Duration::from_secs(10),
        "workers 1 and 2 to leave the pool",
        || {
            !in_pool(&harness, &harness.workers[1].url)
                && !in_pool(&harness, &harness.workers[2].url)
        },
    )
    .await;

    let guard0 = harness.workers[0].block().await;
    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 0, "tok", "user-2", seq).await;
    }
    wait_until(Duration::from_secs(10), "batch to reach worker 0", || {
        harness.workers[0].arrived_count() > 0
    })
    .await;

    // Rejoin workers 1 and 2 before worker 0 fails, so the flush spreads the keys over them.
    let mut guard1 = Some(harness.workers[1].block().await);
    let guard2 = harness.workers[2].block().await;
    for i in [1, 2] {
        harness.workers[i].healthy.store(true, Ordering::SeqCst);
    }
    wait_until(
        Duration::from_secs(10),
        "workers 1 and 2 to rejoin the pool",
        || in_pool(&harness, &harness.workers[1].url) && in_pool(&harness, &harness.workers[2].url),
    )
    .await;
    harness.workers[0].healthy.store(false, Ordering::SeqCst);
    drop(guard0);
    wait_until(
        Duration::from_secs(10),
        "the flush to reach both workers",
        || harness.workers[1].arrived_count() > 0 && harness.workers[2].arrived_count() > 0,
    )
    .await;
    let flush_started = tokio::time::Instant::now();

    // Worker 2 fails its key now, so that key re-defers into a later round.
    harness.workers[2].ingest_ok.store(false, Ordering::SeqCst);
    drop(guard2);
    wait_until(Duration::from_secs(10), "worker 2 to answer", || {
        harness.workers[2].arrived_count() == 1 && harness.observer.pending_messages() > 0
    })
    .await;
    let guard2 = harness.workers[2].block().await;
    harness.workers[2].ingest_ok.store(true, Ordering::SeqCst);

    // Worker 1 lands its key only after the original flush deadline has passed.
    tokio::time::sleep(flush_timeout + Duration::from_millis(200)).await;
    assert!(
        !harness.shutdown.is_cancelled(),
        "a slow in-flight send must not trip the liveness stall"
    );
    guard1.take();
    wait_until(
        Duration::from_secs(10),
        "the retried key to reach worker 2",
        || harness.workers[2].arrived_count() == 2,
    )
    .await;

    // The second round waits past the liveness deadline again before landing.
    tokio::time::sleep(liveness_deadline * 3).await;
    assert!(
        !harness.shutdown.is_cancelled(),
        "the second flush round must keep the heartbeat going"
    );
    drop(guard2);
    harness.wait_for(8, Duration::from_secs(15)).await;

    assert!(
        flush_started.elapsed() > flush_timeout,
        "the drain must have outlasted the flush timeout for this test to mean anything"
    );
    assert!(
        !harness.shutdown.is_cancelled(),
        "the consumer must still be running"
    );
    let log = harness.delivery_log.lock().unwrap().clone();
    for user in ["user-1", "user-2"] {
        let seqs: Vec<usize> = log
            .iter()
            .filter(|(did, _)| did == user)
            .map(|(_, seq)| *seq)
            .collect();
        assert_eq!(
            seqs,
            vec![0, 1, 2, 3],
            "{user} must land exactly once, in order; log: {log:?}"
        );
    }
    assert_eq!(
        harness.workers[0].count(),
        0,
        "failed worker recorded nothing"
    );

    harness.stop().await;
}

#[rstest]
#[case::production_targets(common::PRODUCTION_PACK_TARGETS)]
#[case::one_message_per_request(common::ONE_MESSAGE_PER_REQUEST)]
#[tokio::test]
async fn multi_key_send_failure_replays_every_key_in_order(#[case] pack_targets: PackTargets) {
    let topic = format!("e2e-replay-multikey-{}", Uuid::new_v4());
    let harness = Harness::start_with_pack_targets(
        &topic,
        3,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
        pack_targets,
    )
    .await;
    let producer = make_producer();

    // Worker 1 out so all three keys land on worker 0.
    harness.workers[1].healthy.store(false, Ordering::SeqCst);
    wait_until(
        Duration::from_secs(10),
        "worker 1 to leave the pool",
        || !in_pool(&harness, &harness.workers[1].url),
    )
    .await;

    let guard0 = harness.workers[0].block().await;
    for seq in 0..3usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
        produce(&producer, &topic, 2, "tok", "user-3", seq).await;
    }
    wait_until(Duration::from_secs(10), "batch to reach worker 0", || {
        harness.workers[0].arrived_count() > 0
    })
    .await;

    harness.workers[0].healthy.store(false, Ordering::SeqCst);
    harness.workers[1].healthy.store(true, Ordering::SeqCst);
    wait_until(
        Duration::from_secs(10),
        "worker 1 to rejoin the pool",
        || in_pool(&harness, &harness.workers[1].url),
    )
    .await;
    drop(guard0);

    harness.wait_for(9, Duration::from_secs(15)).await;

    assert_eq!(
        harness.workers[0].count(),
        0,
        "failed worker recorded nothing"
    );
    for user in ["user-1", "user-2", "user-3"] {
        assert_eq!(
            harness.workers[1].seqs_for(user),
            vec![0, 1, 2],
            "{user} must replay to the recovered worker in order"
        );
    }

    harness.stop().await;
}

#[tokio::test]
async fn flush_target_failure_re_defers_then_replays_in_order() {
    let topic = format!("e2e-replay-cascade-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        1,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    let mut guards: Vec<Option<tokio::sync::OwnedMutexGuard<()>>> = Vec::new();
    for w in &harness.workers {
        guards.push(Some(w.block().await));
    }

    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    wait_until(Duration::from_secs(10), "batch to reach a worker", || {
        harness.workers.iter().any(|w| w.arrived_count() > 0)
    })
    .await;
    let first = sole_arrived_worker(&harness);
    let second = 1 - first;

    // Fail the first send; the replay goes to the other, blocked worker.
    harness.workers[first]
        .healthy
        .store(false, Ordering::SeqCst);
    guards[first] = None;
    wait_until(
        Duration::from_secs(10),
        "the replay to reach the second worker",
        || harness.workers[second].arrived_count() > 0,
    )
    .await;

    // Fail the replay too → it must be re-deferred, not lost.
    harness.workers[second]
        .healthy
        .store(false, Ordering::SeqCst);
    guards[second] = None;
    wait_until(
        Duration::from_secs(10),
        "both workers to leave the pool",
        || {
            !in_pool(&harness, &harness.workers[first].url)
                && !in_pool(&harness, &harness.workers[second].url)
        },
    )
    .await;
    // The failed replay can wait in reconnect backoff before it reaches the stash.
    wait_until(
        Duration::from_secs(10),
        "re-deferred work to be held after the replay target also fails",
        || harness.observer.pending_messages() > 0,
    )
    .await;

    harness.workers[second]
        .healthy
        .store(true, Ordering::SeqCst);
    harness.wait_for(4, Duration::from_secs(15)).await;

    assert_eq!(
        harness.workers[first].count(),
        0,
        "the worker that only ever failed recorded nothing"
    );
    assert_eq!(
        harness.workers[second].seqs_for("user-1"),
        vec![0, 1, 2, 3],
        "user-1 replays to the recovered worker in order despite the cascade"
    );

    harness.stop().await;
}

#[tokio::test]
async fn full_pool_drain_holds_fresh_keys_until_a_worker_returns() {
    let topic = format!("e2e-full-drain-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        1,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    // The whole pool drains before any message arrives.
    for w in &harness.workers {
        harness.registry.start_draining(&w.url);
    }

    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }

    // Let the consumer collect and process the batch while nothing is routable.
    tokio::time::sleep(Duration::from_millis(800)).await;
    assert_eq!(
        harness.workers.iter().map(|w| w.count()).sum::<usize>(),
        0,
        "nothing can be delivered while the whole pool is drained"
    );

    harness
        .registry
        .add_worker(WorkerId::from(harness.workers[0].url.as_str()));
    harness.wait_for(4, Duration::from_secs(10)).await;
    assert_eq!(
        harness.workers[0].seqs_for("user-1"),
        vec![0, 1, 2, 3],
        "held messages must deliver in order once a worker returns"
    );

    harness.stop().await;
}

#[tokio::test]
async fn forced_reap_at_drain_timeout_reroutes_deferred_work() {
    let topic = format!("e2e-forced-reap-{}", Uuid::new_v4());
    let registry_config = WorkerRegistryConfig {
        drain_timeout: Duration::from_millis(400),
        ..fast_registry_config()
    };
    let harness = Harness::start(&topic, 1, 2, 2, Duration::from_secs(60), registry_config).await;
    let producer = make_producer();

    let mut guards: Vec<Option<tokio::sync::OwnedMutexGuard<()>>> = Vec::new();
    for w in &harness.workers {
        guards.push(Some(w.block().await));
    }

    // Batch 1 (seq 0–3) reaches its worker and is held in flight there.
    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    wait_until(Duration::from_secs(10), "batch to reach a worker", || {
        harness.workers.iter().any(|w| w.arrived_count() > 0)
    })
    .await;
    let pinned = sole_arrived_worker(&harness);
    let survivor = 1 - pinned;
    let pinned_url = harness.workers[pinned].url.clone();

    // The pinned worker leaves the pool while its batch is still in flight.
    harness.registry.start_draining(&pinned_url);

    // Batch 2 (seq 4–7) arrives while batch 1 is held → defers behind the drainer.
    for seq in 4..8usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    wait_until(Duration::from_secs(10), "batch 2 to defer", || {
        harness.observer.pending_messages() > 0
    })
    .await;

    wait_until(
        Duration::from_secs(10),
        "the drainer to be force-reaped",
        || {
            !harness
                .registry
                .workers()
                .iter()
                .any(|w| w.as_ref() == pinned_url)
        },
    )
    .await;

    // Release all: batch 1 completes on the reaped worker, batch 2 flushes to the survivor.
    guards.clear();
    harness.wait_for(8, Duration::from_secs(15)).await;

    let reaped = harness.workers[pinned].seqs_for("user-1");
    let rerouted = harness.workers[survivor].seqs_for("user-1");
    assert!(
        !reaped.is_empty(),
        "the reaped worker keeps its in-flight batch"
    );
    assert!(
        rerouted.ends_with(&[4, 5, 6, 7]),
        "batch 2 arrived after the drain started, so it re-routes: {rerouted:?}"
    );
    assert_eq!(
        [reaped.clone(), rerouted.clone()].concat(),
        (0..8).collect::<Vec<_>>(),
        "deferred messages re-route to the survivor in order: {reaped:?} then {rerouted:?}"
    );

    harness.stop().await;
}

#[tokio::test]
async fn consumer_crash_before_commit_redelivers_without_loss() {
    let topic = format!("e2e-restart-{}", Uuid::new_v4());
    let mut harness = Harness::start(
        &topic,
        1,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    // Hold both workers so the first batch never acks or commits.
    let mut guards: Vec<Option<tokio::sync::OwnedMutexGuard<()>>> = Vec::new();
    for w in &harness.workers {
        guards.push(Some(w.block().await));
    }

    for seq in 0..6usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    wait_until(Duration::from_secs(10), "batch to reach a worker", || {
        harness.workers.iter().any(|w| w.arrived_count() > 0)
    })
    .await;

    // The worker may record the first delivery after the crash: duplicates allowed, loss not.
    harness.crash_consumer();
    guards.clear();

    harness.restart_consumer(fast_registry_config()).await;

    wait_until(
        Duration::from_secs(30),
        "every message to be redelivered after the crash",
        || {
            let delivered: HashSet<usize> = harness
                .workers
                .iter()
                .flat_map(|w| w.seqs_for("user-1"))
                .collect();
            (0..6).all(|seq| delivered.contains(&seq))
        },
    )
    .await;

    harness.stop().await;
}

async fn assert_commits_track_the_ledger_frontier(mut harness: Harness) {
    let topic = harness.topic.clone();
    let producer = make_producer();

    for seq in 0..10usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    harness.wait_for(10, Duration::from_secs(15)).await;
    wait_until(
        Duration::from_secs(10),
        "the committed offset to reach the frontier",
        || harness.committed_offset(0) == Some(10),
    )
    .await;

    harness.crash_consumer();
    harness.restart_consumer(fast_registry_config()).await;
    for seq in 10..15usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    harness.wait_for(15, Duration::from_secs(15)).await;
    wait_until(
        Duration::from_secs(10),
        "the committed offset to reach the new frontier",
        || harness.committed_offset(0) == Some(15),
    )
    .await;

    let total: usize = harness.workers.iter().map(|w| w.count()).sum();
    assert_eq!(
        total, 15,
        "a committed frontier behind the accepted work would redeliver here"
    );

    harness.stop().await;
}

#[tokio::test]
async fn the_committed_offset_is_the_ledger_frontier() {
    let topic = format!("e2e-ledger-commit-{}", Uuid::new_v4());
    assert_commits_track_the_ledger_frontier(
        Harness::start(
            &topic,
            1,
            1,
            1,
            Duration::from_secs(60),
            fast_registry_config(),
        )
        .await,
    )
    .await;
}

#[tokio::test]
async fn group_granularity_commits_the_ledger_frontier() {
    let topic = format!("e2e-group-commit-{}", Uuid::new_v4());
    assert_commits_track_the_ledger_frontier(
        Harness::start_group_granularity(common::PRODUCTION_PACK_TARGETS, &topic, 1, 1, 1).await,
    )
    .await;
}

#[tokio::test]
async fn group_granularity_keeps_a_held_frontier_uncommitted_until_the_stop_commits_it() {
    let metrics = metrics();
    let topic = format!("e2e-group-stop-commit-{}", Uuid::new_v4());
    let harness = Harness::start_group_granularity_committing_every(
        common::PRODUCTION_PACK_TARGETS,
        &topic,
        1,
        1,
        1,
        Duration::from_secs(3600),
    )
    .await;
    let p0 = TopicPartition::new(&topic, 0);
    let producer = make_producer();

    produce(&producer, &topic, 0, "tok", "user-a", 0).await;
    wait_until(
        Duration::from_secs(10),
        "the first frontier to commit",
        || harness.committed_offset(0) == Some(1),
    )
    .await;

    for seq in 1..10usize {
        produce(&producer, &topic, 0, "tok", "user-a", seq).await;
    }
    wait_until(Duration::from_secs(10), "every message to settle", || {
        harness.workers[0].count() == 10 && harness.ledger.held(&p0).offsets == 0
    })
    .await;
    assert_eq!(
        harness.committed_offset(0),
        Some(1),
        "the interval holds the later frontier"
    );
    assert_eq!(
        uncommitted_offsets(metrics, &topic, 0),
        Some(9.0),
        "the held frontier is still uncommitted"
    );

    let group_id = harness.group_id.clone();
    harness.stop().await;

    wait_until(Duration::from_secs(10), "the stop to commit", || {
        broker_committed_offset(&group_id, &topic, 0) == Some(10)
    })
    .await;
    assert_eq!(uncommitted_offsets(metrics, &topic, 0), Some(0.0));
}

// One recorder per test binary; each test reads only its own topic's series.
fn metrics() -> &'static Snapshotter {
    static SNAPSHOTTER: OnceLock<Snapshotter> = OnceLock::new();
    SNAPSHOTTER.get_or_init(|| {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        metrics::set_global_recorder(recorder).expect("no other recorder in the e2e binary");
        snapshotter
    })
}

fn uncommitted_offsets(metrics: &Snapshotter, topic: &str, partition: i32) -> Option<f64> {
    let partition = partition.to_string();
    metrics
        .snapshot()
        .into_vec()
        .into_iter()
        .find_map(|(key, _, _, value)| {
            let key = key.key();
            let labeled = |name: &str, expected: &str| {
                key.labels()
                    .any(|label| label.key() == name && label.value() == expected)
            };
            if key.name() != "kafka_consumer_ledger_uncommitted_offsets"
                || !labeled("topic", topic)
                || !labeled("partition", &partition)
            {
                return None;
            }
            match value {
                DebugValue::Gauge(value) => Some(value.into_inner()),
                _ => None,
            }
        })
}

const STALL_KEYS: [(i32, &str); 2] = [(0, "user-a"), (1, "user-b")];

async fn stall_two_partitions_on_two_workers(
    harness: &Harness,
    topic: &str,
) -> Vec<Option<tokio::sync::OwnedMutexGuard<()>>> {
    let mut guards = Vec::new();
    for worker in &harness.workers {
        guards.push(Some(worker.block().await));
    }

    let producer = make_producer();
    let mut sends = Vec::new();
    for seq in 0..5usize {
        for (partition, key) in STALL_KEYS {
            sends.push(produce(&producer, topic, partition, "tok", key, seq));
        }
    }
    futures::future::join_all(sends).await;

    wait_until(
        Duration::from_secs(10),
        "both workers to hold a sub-batch",
        || harness.workers.iter().all(|w| w.arrived_count() > 0),
    )
    .await;

    guards
}

fn accepted_partition(harness: &Harness, idx: usize) -> i32 {
    let worker = &harness.workers[idx];
    assert_eq!(
        worker.count(),
        5,
        "each worker must hold exactly one key's messages"
    );
    STALL_KEYS
        .iter()
        .find(|(_, key)| !worker.seqs_for(key).is_empty())
        .map(|(partition, _)| *partition)
        .expect("the released worker accepted neither key")
}

#[tokio::test]
async fn group_granularity_commits_a_partition_while_another_stalls() {
    let topic = format!("e2e-group-stall-{}", Uuid::new_v4());
    // One message per request, or the packer puts both keys on one worker.
    let harness =
        Harness::start_group_granularity(common::ONE_MESSAGE_PER_REQUEST, &topic, 2, 2, 2).await;
    let mut guards = stall_two_partitions_on_two_workers(&harness, &topic).await;

    guards[0] = None;
    wait_until(
        Duration::from_secs(10),
        "the released worker to accept its key",
        || harness.workers[0].count() == 5,
    )
    .await;
    let released = accepted_partition(&harness, 0);
    let stalled = 1 - released;

    wait_until(
        Duration::from_secs(10),
        "the released partition to commit",
        || harness.committed_offset(released) == Some(5),
    )
    .await;
    assert_eq!(
        harness.committed_offset(stalled),
        None,
        "the stalled send must hold its own partition back"
    );

    guards[1] = None;
    wait_until(
        Duration::from_secs(10),
        "the stalled partition to commit once released",
        || harness.committed_offset(stalled) == Some(5),
    )
    .await;

    harness.stop().await;
}

#[rstest]
#[case::capped(Polling::Capped)]
#[case::continuous(Polling::Continuous)]
#[tokio::test]
async fn a_partition_at_its_budget_pauses_until_a_commit_frees_it(#[case] polling: Polling) {
    let topic = format!("e2e-partition-budget-{}", Uuid::new_v4());
    let budget = BudgetLimits::new(NonZeroU64::new(5), NonZeroU64::new(UNBOUNDED_BYTES), 0.5)
        .expect("a valid budget");
    let harness = Harness::start_with_partition_budget(
        common::PRODUCTION_PACK_TARGETS,
        &topic,
        1,
        1,
        budget,
        polling,
    )
    .await;
    let p0 = TopicPartition::new(&topic, 0);
    let guard = harness.workers[0].block().await;
    let producer = make_producer();

    for seq in 0..5usize {
        produce(&producer, &topic, 0, "tok", "user-a", seq).await;
    }
    wait_until(Duration::from_secs(10), "the budget to fill", || {
        harness.ledger.held(&p0).offsets == 5
    })
    .await;

    for seq in 5..20usize {
        produce(&producer, &topic, 0, "tok", "user-a", seq).await;
    }
    tokio::time::sleep(Duration::from_secs(1)).await;
    assert_eq!(
        harness.ledger.held(&p0).offsets,
        5,
        "a paused partition fetches nothing more"
    );

    drop(guard);
    wait_until(
        Duration::from_secs(10),
        "the partition to resume and drain",
        || harness.committed_offset(0) == Some(20),
    )
    .await;

    harness.stop().await;
}

#[rstest]
#[case::capped(Polling::Capped)]
#[case::continuous(Polling::Continuous)]
#[tokio::test]
async fn a_partition_at_its_budget_does_not_pause_another(#[case] polling: Polling) {
    let topic = format!("e2e-partition-budget-two-{}", Uuid::new_v4());
    let budget = BudgetLimits::new(NonZeroU64::new(5), NonZeroU64::new(UNBOUNDED_BYTES), 0.5)
        .expect("a valid budget");
    // One message per request, or the packer puts both keys on one worker.
    let harness = Harness::start_with_partition_budget(
        common::ONE_MESSAGE_PER_REQUEST,
        &topic,
        2,
        2,
        budget,
        polling,
    )
    .await;
    let mut guards = stall_two_partitions_on_two_workers(&harness, &topic).await;

    guards[0] = None;
    wait_until(
        Duration::from_secs(10),
        "the released worker to accept its key",
        || harness.workers[0].count() == 5,
    )
    .await;
    let released = accepted_partition(&harness, 0);
    let stalled = 1 - released;
    let stalled_partition = TopicPartition::new(&topic, stalled);

    let producer = make_producer();
    for seq in 5..10usize {
        for (partition, key) in STALL_KEYS {
            produce(&producer, &topic, partition, "tok", key, seq).await;
        }
    }
    wait_until(
        Duration::from_secs(10),
        "the released partition to resume and drain",
        || harness.committed_offset(released) == Some(10),
    )
    .await;
    assert_eq!(
        harness.ledger.held(&stalled_partition).offsets,
        5,
        "the partition at its budget fetches nothing more"
    );
    assert_eq!(harness.committed_offset(stalled), None);

    guards[1] = None;
    wait_until(
        Duration::from_secs(10),
        "the stalled partition to resume and drain",
        || harness.committed_offset(stalled) == Some(10),
    )
    .await;

    harness.stop().await;
}

#[tokio::test]
async fn continuous_polling_commits_the_ledger_frontier() {
    let topic = format!("e2e-continuous-commit-{}", Uuid::new_v4());
    assert_commits_track_the_ledger_frontier(
        Harness::start_continuous(
            common::PRODUCTION_PACK_TARGETS,
            &topic,
            1,
            1,
            BudgetLimits::new(
                NonZeroU64::new(1_000),
                NonZeroU64::new(UNBOUNDED_BYTES),
                0.8,
            )
            .expect("a valid budget"),
            ChargeLimit::new(NonZeroU64::new(1_000), NonZeroU64::new(UNBOUNDED_BYTES)),
        )
        .await,
    )
    .await;
}

#[tokio::test]
async fn the_in_flight_limit_stops_reading_until_a_commit_frees_room() {
    let topic = format!("e2e-in-flight-limit-{}", Uuid::new_v4());
    let harness = Harness::start_continuous(
        common::PRODUCTION_PACK_TARGETS,
        &topic,
        1,
        1,
        BudgetLimits::new(
            NonZeroU64::new(1_000),
            NonZeroU64::new(UNBOUNDED_BYTES),
            0.8,
        )
        .expect("a valid budget"),
        ChargeLimit::new(NonZeroU64::new(5), NonZeroU64::new(UNBOUNDED_BYTES)),
    )
    .await;
    let p0 = TopicPartition::new(&topic, 0);
    let guard = harness.workers[0].block().await;
    let backlog: Vec<(&str, usize)> = (0..120).map(|seq| ("user-a", seq)).collect();

    produce_in_one_transaction(&topic, 0, "tok", &backlog).await;
    wait_until(
        Duration::from_secs(10),
        "the in-flight limit to fill",
        || harness.ledger.held(&p0).offsets >= 5,
    )
    .await;
    tokio::time::sleep(Duration::from_secs(1)).await;
    assert_eq!(
        harness.ledger.held(&p0).offsets,
        50,
        "a ready backlog stops one poll of the batch size past the limit"
    );

    drop(guard);
    wait_until(
        Duration::from_secs(10),
        "reading to resume and drain",
        || harness.workers[0].count() == 120,
    )
    .await;

    harness.stop().await;
}

/// On this single-threaded runtime the batcher runs only when the consumer
/// loop yields. A ready backlog keeps `recv` ready on every turn, so the first
/// request must reach the worker before the loop has charged the whole backlog.
#[tokio::test]
async fn a_ready_backlog_does_not_keep_the_batcher_from_running() {
    const BACKLOG: usize = 2_000;
    let topic = format!("e2e-continuous-backlog-{}", Uuid::new_v4());
    let harness = Harness::start_continuous(
        common::PRODUCTION_PACK_TARGETS,
        &topic,
        1,
        1,
        BudgetLimits::new(
            NonZeroU64::new(100_000),
            NonZeroU64::new(UNBOUNDED_BYTES),
            0.8,
        )
        .expect("a valid budget"),
        ChargeLimit::new(NonZeroU64::new(100_000), NonZeroU64::new(UNBOUNDED_BYTES)),
    )
    .await;
    let p0 = TopicPartition::new(&topic, 0);
    let held_at_arrival: Arc<Mutex<Vec<usize>>> = Arc::new(Mutex::new(Vec::new()));
    {
        let ledger = Arc::clone(&harness.ledger);
        let p0 = p0.clone();
        let held_at_arrival = Arc::clone(&held_at_arrival);
        harness.workers[0].on_arrival(move || {
            held_at_arrival
                .lock()
                .unwrap()
                .push(ledger.held(&p0).offsets);
        });
    }
    let guard = harness.workers[0].block().await;
    let backlog: Vec<(&str, usize)> = (0..BACKLOG).map(|seq| ("user-a", seq)).collect();

    produce_in_one_transaction(&topic, 0, "tok", &backlog).await;
    wait_until(
        Duration::from_secs(10),
        "the first request to reach the worker",
        || harness.workers[0].arrived_count() >= 1,
    )
    .await;
    let held = held_at_arrival.lock().unwrap()[0];
    assert!(
        held < BACKLOG / 2,
        "the loop charged {held} of {BACKLOG} offsets before the first request reached the worker"
    );

    drop(guard);
    wait_until(Duration::from_secs(10), "the backlog to drain", || {
        harness.workers[0].count() == BACKLOG
    })
    .await;

    harness.stop().await;
}

#[tokio::test]
async fn a_partition_paused_at_its_budget_fetches_again_after_a_rebalance_returns_it() {
    let topic = format!("e2e-partition-budget-rebalance-{}", Uuid::new_v4());
    let budget = BudgetLimits::new(NonZeroU64::new(5), NonZeroU64::new(UNBOUNDED_BYTES), 0.5)
        .expect("a valid budget");
    let harness = Harness::start_with_partition_budget_committing_every(
        common::PRODUCTION_PACK_TARGETS,
        &topic,
        1,
        1,
        budget,
        Duration::from_secs(20),
    )
    .await;
    let p0 = TopicPartition::new(&topic, 0);
    let producer = make_producer();

    produce(&producer, &topic, 0, "tok", "user-a", 0).await;
    wait_until(
        Duration::from_secs(10),
        "the first frontier to commit",
        || harness.committed_offset(0) == Some(1),
    )
    .await;
    for seq in 1..6usize {
        produce(&producer, &topic, 0, "tok", "user-a", seq).await;
    }
    wait_until(
        Duration::from_secs(10),
        "the interval to hold the budget's worth of settled offsets",
        || harness.workers[0].count() == 6 && harness.ledger.held(&p0).offsets == 0,
    )
    .await;

    let generation_before = harness.ledger.generation(&p0);
    let second = harness.join_second_consumer().await;
    wait_until(
        Duration::from_secs(15),
        "the rebalance to revoke the partition",
        || harness.ledger.generation(&p0) > generation_before,
    )
    .await;
    assert_eq!(
        harness.committed_offset(0),
        Some(1),
        "the partition must still be at its budget when it is revoked"
    );
    second.stop().await;

    for seq in 6..10usize {
        produce(&producer, &topic, 0, "tok", "user-a", seq).await;
    }
    wait_until(
        Duration::from_secs(40),
        "the returned partition to fetch again",
        || {
            let delivered: HashSet<usize> = harness
                .workers
                .iter()
                .flat_map(|w| w.seqs_for("user-a"))
                .collect();
            (6..10).all(|seq| delivered.contains(&seq))
        },
    )
    .await;

    harness.stop().await;
}

#[tokio::test]
async fn lost_ack_after_processing_replays_without_loss() {
    let topic = format!("e2e-lost-ack-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        1,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    // Arm both workers: the batch can land on either.
    for w in &harness.workers {
        w.ack_lost_once.store(true, Ordering::SeqCst);
    }

    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }

    wait_until(
        Duration::from_secs(15),
        "every message delivered and the lost ACK replayed",
        || {
            let log = harness.delivery_log.lock().unwrap();
            let distinct: HashSet<usize> = log.iter().map(|(_, seq)| *seq).collect();
            distinct.len() == 4 && log.len() > 4
        },
    )
    .await;

    let log = harness.delivery_log.lock().unwrap().clone();
    let seqs: Vec<usize> = log
        .iter()
        .filter(|(did, _)| did.as_str() == "user-1")
        .map(|(_, s)| *s)
        .collect();
    assert!(
        seqs.len() > 4,
        "the lost ACK must force a replay (duplicates expected): {seqs:?}"
    );
    let mut seen = HashSet::new();
    let first_deliveries: Vec<usize> = seqs.iter().copied().filter(|s| seen.insert(*s)).collect();
    assert_eq!(
        first_deliveries,
        vec![0, 1, 2, 3],
        "no loss, and first deliveries in Kafka order: {seqs:?}"
    );

    harness.stop().await;
}

#[tokio::test]
async fn poison_batch_fails_safely_without_committing() {
    let topic = format!("e2e-poison-{}", Uuid::new_v4());
    let mut harness = Harness::start(
        &topic,
        1,
        2,
        1,
        Duration::from_secs(2),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    for w in &harness.workers {
        w.reject_4xx.store(true, Ordering::SeqCst);
    }

    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }

    assert!(
        harness
            .wait_for_consumer_exit(Duration::from_secs(20))
            .await,
        "the consumer must fail the poison batch within the flush timeout"
    );
    assert_eq!(
        harness.workers.iter().map(|w| w.count()).sum::<usize>(),
        0,
        "a rejected poison batch must not be partially ingested"
    );
}

#[tokio::test]
async fn partial_acceptance_fails_the_batch_without_commit() {
    let topic = format!("e2e-partial-accept-{}", Uuid::new_v4());
    let mut harness = Harness::start(
        &topic,
        1,
        2,
        1,
        Duration::from_secs(2),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    for w in &harness.workers {
        w.underreport_once.store(true, Ordering::SeqCst);
    }

    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }

    assert!(
        harness
            .wait_for_consumer_exit(Duration::from_secs(20))
            .await,
        "an under-acknowledged batch must fail the consumer, not commit"
    );
    assert_eq!(
        harness.committed_offset(0),
        None,
        "nothing is committed over an under-acknowledged batch"
    );
}

#[tokio::test]
async fn drainer_crash_mid_drain_replays_to_survivor_in_order() {
    let topic = format!("e2e-drain-crash-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        1,
        2,
        2,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    let mut guards: Vec<Option<tokio::sync::OwnedMutexGuard<()>>> = Vec::new();
    for w in &harness.workers {
        guards.push(Some(w.block().await));
    }

    // Batch 1 (seq 0–3) is held in flight on its worker.
    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    wait_until(Duration::from_secs(10), "batch to reach a worker", || {
        harness.workers.iter().any(|w| w.arrived_count() > 0)
    })
    .await;
    let drainer = sole_arrived_worker(&harness);
    let survivor = 1 - drainer;

    // The worker begins draining; batch 2 (seq 4–7) defers behind it.
    harness
        .registry
        .start_draining(&harness.workers[drainer].url);
    for seq in 4..8usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    wait_until(Duration::from_secs(10), "batch 2 to defer", || {
        harness.observer.pending_messages() > 0
    })
    .await;

    // The drainer crashes mid-drain: its held request fails instead of finishing.
    harness.workers[drainer]
        .healthy
        .store(false, Ordering::SeqCst);
    guards.clear();

    harness.wait_for(8, Duration::from_secs(15)).await;
    assert_eq!(
        harness.workers[drainer].count(),
        0,
        "the crashed drainer ingested nothing"
    );
    assert_eq!(
        harness.workers[survivor].seqs_for("user-1"),
        (0..8).collect::<Vec<_>>(),
        "all work replays to the survivor in order"
    );

    harness.stop().await;
}

#[rstest]
#[case::production_targets(common::PRODUCTION_PACK_TARGETS)]
#[case::one_message_per_request(common::ONE_MESSAGE_PER_REQUEST)]
#[tokio::test]
async fn full_pool_send_failure_with_multiple_keys_recovers_in_order(
    #[case] pack_targets: PackTargets,
) {
    let topic = format!("e2e-pool-loss-{}", Uuid::new_v4());
    let harness = Harness::start_with_pack_targets(
        &topic,
        2,
        2,
        3,
        Duration::from_secs(60),
        fast_registry_config(),
        pack_targets,
    )
    .await;
    let producer = make_producer();

    let mut guards: Vec<Option<tokio::sync::OwnedMutexGuard<()>>> = Vec::new();
    for w in &harness.workers {
        guards.push(Some(w.block().await));
    }

    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    // One message per request puts each key on its own worker; production targets pack both.
    let split = pack_targets == common::ONE_MESSAGE_PER_REQUEST;
    wait_until(Duration::from_secs(10), "work to be in flight", || {
        if split {
            harness.workers.iter().all(|w| w.arrived_count() > 0)
        } else {
            harness.workers.iter().any(|w| w.arrived_count() > 0)
        }
    })
    .await;

    for w in &harness.workers {
        w.healthy.store(false, Ordering::SeqCst);
    }
    guards.clear();
    wait_until(
        Duration::from_secs(10),
        "all failed work to be stashed",
        || harness.observer.pending_messages() == 8,
    )
    .await;

    harness.workers[1].healthy.store(true, Ordering::SeqCst);
    harness.wait_for(8, Duration::from_secs(15)).await;

    assert_eq!(
        harness.workers[0].count(),
        0,
        "the still-dead worker recorded nothing"
    );
    for user in ["user-1", "user-2"] {
        assert_eq!(
            harness.workers[1].seqs_for(user),
            (0..4).collect::<Vec<_>>(),
            "{user} must drain to the recovered worker in order"
        );
    }

    harness.stop().await;
}

#[tokio::test]
async fn headerless_messages_survive_send_failure_replay() {
    let topic = format!("e2e-headerless-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        1,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    // Take worker 1 out so the batch lands on worker 0 as one sub-batch.
    harness.workers[1].healthy.store(false, Ordering::SeqCst);
    wait_until(
        Duration::from_secs(10),
        "worker 1 to leave the pool",
        || !in_pool(&harness, &harness.workers[1].url),
    )
    .await;

    let guard0 = harness.workers[0].block().await;
    for seq in 0..3usize {
        produce_raw(
            &producer,
            &topic,
            0,
            &format!("k{seq}"),
            format!(r#"{{"seq":{seq}}}"#).as_bytes(),
            None,
        )
        .await;
    }
    wait_until(Duration::from_secs(10), "batch to reach worker 0", || {
        harness.workers[0].arrived_count() > 0
    })
    .await;

    harness.workers[0].healthy.store(false, Ordering::SeqCst);
    harness.workers[1].healthy.store(true, Ordering::SeqCst);
    wait_until(
        Duration::from_secs(10),
        "worker 1 to rejoin the pool",
        || in_pool(&harness, &harness.workers[1].url),
    )
    .await;
    drop(guard0);

    harness.wait_for(3, Duration::from_secs(15)).await;
    assert_eq!(
        harness.workers[0].count(),
        0,
        "failed worker recorded nothing"
    );
    // Headerless messages have an empty distinct_id and distinct keys, so order is free.
    let mut seqs = harness.workers[1].seqs_for("");
    seqs.sort_unstable();
    assert_eq!(
        seqs,
        vec![0, 1, 2],
        "headerless messages must replay exactly once"
    );

    harness.stop().await;
}

#[tokio::test]
async fn non_utf8_payload_is_delivered_not_lost() {
    let topic = format!("e2e-non-utf8-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        1,
        1,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    let headers = OwnedHeaders::new()
        .insert(Header {
            key: "token",
            value: Some("tok"),
        })
        .insert(Header {
            key: "distinct_id",
            value: Some("user-1"),
        });
    produce_raw(
        &producer,
        &topic,
        0,
        "k",
        &[0xF0, 0x28, 0x8C, 0x28],
        Some(headers),
    )
    .await;

    harness.wait_for(1, Duration::from_secs(10)).await;
    assert_eq!(
        harness.workers[0].seqs_for("user-1"),
        vec![0],
        "the event must arrive (with its body nulled) rather than be dropped"
    );

    harness.stop().await;
}

#[tokio::test]
async fn fleet_redeploy_migrates_work_to_new_workers_without_loss() {
    let topic = format!("e2e-redeploy-{}", Uuid::new_v4());
    let mut harness = Harness::start(
        &topic,
        2,
        2,
        2,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    // Steady traffic on two keys lands on the old fleet.
    for seq in 0..10usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    harness.wait_for(20, Duration::from_secs(15)).await;

    // The fleet is replaced wholesale.
    let new_a = FakeWorker::start_logged(Arc::clone(&harness.delivery_log)).await;
    let new_b = FakeWorker::start_logged(Arc::clone(&harness.delivery_log)).await;
    let desired: HashSet<WorkerId> = [new_a.url.as_str(), new_b.url.as_str()]
        .into_iter()
        .map(WorkerId::from)
        .collect();
    reconcile_membership(&harness.registry, &desired);
    let old_count = harness.workers.len();
    harness.workers.push(new_a);
    harness.workers.push(new_b);

    // Traffic continues through the switchover.
    for seq in 10..20usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    harness.wait_for(40, Duration::from_secs(20)).await;

    wait_until(Duration::from_secs(5), "old workers to be reaped", || {
        harness.registry.worker_count() == 2
    })
    .await;

    let log = harness.delivery_log.lock().unwrap().clone();
    assert_eq!(log.len(), 40, "exactly-once across the redeploy");
    for user in ["user-1", "user-2"] {
        let seqs: Vec<usize> = log
            .iter()
            .filter(|(d, _)| d.as_str() == user)
            .map(|(_, s)| *s)
            .collect();
        assert_eq!(
            seqs,
            (0..20).collect::<Vec<_>>(),
            "{user} must stay in order across the redeploy: {seqs:?}"
        );
    }
    let new_fleet_received: usize = harness.workers[old_count..].iter().map(|w| w.count()).sum();
    assert!(
        new_fleet_received > 0,
        "the new fleet must take over the traffic"
    );

    harness.stop().await;
}

#[rstest]
#[case::capped(Polling::Capped)]
#[case::continuous(Polling::Continuous)]
#[tokio::test]
async fn second_consumer_joining_the_group_preserves_all_messages(#[case] polling: Polling) {
    let topic = format!("e2e-two-consumers-{}", Uuid::new_v4());
    let harness = Harness::start_polling(&topic, 2, 2, 1, 0, polling).await;
    let producer = make_producer();

    // Hold an uncommitted batch while the first consumer owns both partitions.
    let mut guards: Vec<Option<tokio::sync::OwnedMutexGuard<()>>> = Vec::new();
    for w in &harness.workers {
        guards.push(Some(w.block().await));
    }
    for seq in 0..5usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    wait_until(Duration::from_secs(10), "work to reach a worker", || {
        harness.workers.iter().any(|w| w.arrived_count() > 0)
    })
    .await;

    let second = harness.join_second_consumer().await;

    // Release the batch so the first consumer polls again and the rebalance completes.
    guards.clear();
    tokio::time::sleep(Duration::from_secs(2)).await;
    for seq in 5..10usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }

    wait_until(
        Duration::from_secs(30),
        "every message to be delivered at least once across the rebalance",
        || {
            ["user-1", "user-2"].iter().all(|user| {
                let delivered: HashSet<usize> = harness
                    .workers
                    .iter()
                    .flat_map(|w| w.seqs_for(user))
                    .collect();
                (0..10).all(|s| delivered.contains(&s))
            })
        },
    )
    .await;

    second.stop().await;
    harness.stop().await;
}

#[rstest]
#[case::capped(Polling::Capped)]
#[case::continuous(Polling::Continuous)]
#[tokio::test]
async fn partition_lost_and_regained_keeps_the_consumer_alive(#[case] polling: Polling) {
    let topic = format!("e2e-regain-{}", Uuid::new_v4());
    // 128 in-flight polls keep the consumer polling under held batches.
    let harness = Harness::start_polling(&topic, 2, 2, 128, 0, polling).await;
    let producer = make_producer();
    let partitions = [
        TopicPartition::new(topic.clone(), 0),
        TopicPartition::new(topic.clone(), 1),
    ];

    // Hold the first batch in flight while the group changes underneath it.
    let mut guards: Vec<Option<tokio::sync::OwnedMutexGuard<()>>> = Vec::new();
    for w in &harness.workers {
        guards.push(Some(w.block().await));
    }
    for seq in 0..5usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    wait_until(Duration::from_secs(10), "work to reach a worker", || {
        harness.workers.iter().any(|w| w.arrived_count() > 0)
    })
    .await;
    let generations_before: Vec<u64> = partitions
        .iter()
        .map(|partition| harness.ledger.generation(partition))
        .collect();

    // A second consumer joins and takes a partition away.
    let second = harness.join_second_consumer().await;

    // A trickle keeps the consumer polling until the rebalance reaches its ledger.
    let rebalanced = || {
        partitions
            .iter()
            .zip(&generations_before)
            .any(|(partition, before)| harness.ledger.generation(partition) > *before)
    };
    let deadline = tokio::time::Instant::now() + Duration::from_secs(10);
    let mut trickle_seq = 1000usize;
    while !rebalanced() {
        assert!(
            tokio::time::Instant::now() < deadline,
            "timed out waiting for the rebalance to reach the first consumer's ledger"
        );
        produce(&producer, &topic, 0, "tok", "user-1", trickle_seq).await;
        trickle_seq += 1;
        tokio::time::sleep(Duration::from_millis(20)).await;
    }

    // The released offsets carry replaced generations, so they settle as stale.
    guards.clear();
    for seq in 5..10usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    wait_until(
        Duration::from_secs(30),
        "every message to be delivered across the join",
        || {
            ["user-1", "user-2"].iter().all(|user| {
                let delivered: HashSet<usize> = harness
                    .workers
                    .iter()
                    .flat_map(|w| w.seqs_for(user))
                    .collect();
                (0..10).all(|s| delivered.contains(&s))
            })
        },
    )
    .await;

    // The partition returns under a new generation.
    second.stop().await;

    for seq in 10..15usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    wait_until(
        Duration::from_secs(30),
        "the returned partition to consume under its new assignment",
        || {
            ["user-1", "user-2"].iter().all(|user| {
                let delivered: HashSet<usize> = harness
                    .workers
                    .iter()
                    .flat_map(|w| w.seqs_for(user))
                    .collect();
                (10..15).all(|s| delivered.contains(&s))
            })
        },
    )
    .await;

    harness.stop().await;
}

#[tokio::test]
async fn fenced_static_member_exits_on_fatal_error() {
    let topic = format!("e2e-fenced-{}", Uuid::new_v4());
    create_topic(&topic, 1).await;

    let worker = FakeWorker::start().await;
    let urls = vec![worker.url.clone()];
    let registry = Arc::new(WorkerRegistry::new(&urls, fast_registry_config()));
    let probe = CancellationToken::new();
    Arc::clone(&registry).start_probing(probe.clone());
    let pool_source = WorkerPoolSource::new(Arc::clone(&registry), RoutingStrategy::default());
    let transport = Arc::new(test_transport());
    let mut manager = Manager::builder("e2e-fenced")
        .with_trap_signals(false)
        .build();
    let handle = manager.register("consumer", ComponentOptions::new());
    let group = format!("e2e-{}", Uuid::new_v4());
    let (batcher, outputs) = common::batcher(
        pool_source,
        Arc::clone(&transport),
        Duration::from_secs(60),
        Duration::from_millis(200),
        common::PRODUCTION_PACK_TARGETS,
        None,
    );
    let consumer = IngestionConsumer::from_parts(
        make_kafka_consumer(&topic, &group, Some("pod-1")),
        batcher,
        outputs,
        transport,
        urls,
        IngestionConsumerOptions {
            batch_size: 50,
            batch_size_bytes: 0,
            batch_timeout: Duration::from_millis(100),
            max_in_flight_batches: 1,
            group_id: "e2e-test".to_string(),
            debug_recorder: None,
            completion_granularity: CompletionGranularity::Poll,
            commit_interval: Duration::ZERO,
            ledger: Arc::new(TopicOffsetLedger::new()),
            partition_budget: BudgetLimits::unset(),
            polling: Polling::Capped,
            in_flight_limit: ChargeLimit::unset(),
        },
        handle,
    );
    let task = tokio::spawn(async move { consumer.process().await });

    // Prove the first instance is consuming before it gets fenced.
    let producer = make_producer();
    produce(&producer, &topic, 0, "tok", "user-1", 0).await;
    wait_until(Duration::from_secs(10), "first instance to consume", || {
        worker.count() >= 1
    })
    .await;

    // The usurper joins with the SAME instance id; polling drives the join.
    let usurper = make_kafka_consumer(&topic, &group, Some("pod-1"));
    let usurper_task = tokio::spawn(async move {
        let mut stream = usurper.stream();
        // Errors are items too; read until the timeout so the usurper joins.
        let _ = tokio::time::timeout(Duration::from_secs(30), async {
            while stream.next().await.is_some() {}
        })
        .await;
    });

    let exited = tokio::time::timeout(Duration::from_secs(30), task)
        .await
        .is_ok();
    assert!(
        exited,
        "the fenced instance must exit with a fatal error, not keep polling a dead client"
    );

    usurper_task.abort();
    probe.cancel();
}

#[derive(Clone, Copy, Debug)]
enum Churn {
    Drain,
    Fail,
    Mixed,
}

async fn sleep_or_cancel(token: &CancellationToken, ms: u64) -> bool {
    tokio::select! {
        _ = token.cancelled() => true,
        _ = tokio::time::sleep(Duration::from_millis(ms)) => false,
    }
}

/// Churn one worker at a time until cancelled, then restore all.
fn spawn_churn(
    harness: &Harness,
    churn: Churn,
    token: CancellationToken,
) -> tokio::task::JoinHandle<()> {
    let registry = Arc::clone(&harness.registry);
    let controls: Vec<(String, Arc<AtomicBool>)> = harness
        .workers
        .iter()
        .map(|w| (w.url.clone(), Arc::clone(&w.ingest_ok)))
        .collect();
    tokio::spawn(async move {
        let mut i = 0usize;
        while !token.is_cancelled() {
            let (url, ingest_ok) = &controls[i % controls.len()];
            let drain = match churn {
                Churn::Drain => true,
                Churn::Fail => false,
                Churn::Mixed => i.is_multiple_of(2),
            };
            if drain {
                registry.start_draining(url);
                if sleep_or_cancel(&token, 120).await {
                    break;
                }
                registry.add_worker(WorkerId::from(url.as_str()));
            } else {
                ingest_ok.store(false, Ordering::SeqCst);
                if sleep_or_cancel(&token, 120).await {
                    break;
                }
                ingest_ok.store(true, Ordering::SeqCst);
            }
            // A gap with everyone healthy so the backlog can drain.
            if sleep_or_cancel(&token, 80).await {
                break;
            }
            i += 1;
        }
        for (url, ingest_ok) in &controls {
            ingest_ok.store(true, Ordering::SeqCst);
            registry.add_worker(WorkerId::from(url.as_str()));
        }
    })
}

async fn run_churn_suite(churn: Churn, max_in_flight: usize, strict_order: bool) {
    let topic = format!("e2e-churn-{churn:?}-mif{max_in_flight}-{}", Uuid::new_v4());
    let dids = 8usize;
    let per_did = 60usize;
    let total = dids * per_did;
    let partitions = 4i32;

    let harness = Harness::start(
        &topic,
        partitions,
        4,
        max_in_flight,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    let churn_token = CancellationToken::new();
    let churn_handle = spawn_churn(&harness, churn, churn_token.clone());

    // Interleave distinct_ids so each Kafka batch mixes many keys.
    for seq in 0..per_did {
        for d in 0..dids {
            produce(
                &producer,
                &topic,
                (d as i32) % partitions,
                "tok",
                &format!("user-{d}"),
                seq,
            )
            .await;
        }
    }

    harness.wait_for(total, Duration::from_secs(90)).await;

    // Quiesce churn so the final assertions see a settled log.
    churn_token.cancel();
    let _ = churn_handle.await;

    let log = harness.delivery_log.lock().unwrap().clone();
    assert_eq!(
        log.len(),
        total,
        "exactly-once: expected {total} deliveries, got {}",
        log.len()
    );

    let expected: Vec<usize> = (0..per_did).collect();
    for d in 0..dids {
        let did = format!("user-{d}");
        let seqs: Vec<usize> = log
            .iter()
            .filter(|(id, _)| *id == did)
            .map(|(_, s)| *s)
            .collect();
        let mut sorted = seqs.clone();
        sorted.sort_unstable();
        assert_eq!(
            sorted, expected,
            "{did}: messages lost or duplicated under {churn:?} churn: {seqs:?}"
        );
        if strict_order {
            assert_eq!(
                seqs, expected,
                "{did}: messages delivered out of order under {churn:?} churn: {seqs:?}"
            );
        }
    }

    // Leaked bookkeeping would skew placement or strand messages.
    wait_until(
        Duration::from_secs(10),
        "batcher pending/in-flight to drain to zero after churn",
        || harness.observer.pending_messages() == 0 && harness.observer.total_in_flight() == 0,
    )
    .await;

    harness.stop().await;
}

#[tokio::test]
async fn churn_drain_preserves_order_at_max_in_flight_2() {
    run_churn_suite(Churn::Drain, 2, true).await;
}

#[tokio::test]
async fn churn_drain_preserves_order_at_max_in_flight_3() {
    run_churn_suite(Churn::Drain, 3, true).await;
}

#[tokio::test]
async fn churn_send_failures_are_exactly_once_at_max_in_flight_3() {
    run_churn_suite(Churn::Fail, 3, false).await;
}

#[tokio::test]
async fn churn_mixed_drain_and_failures_are_exactly_once_at_max_in_flight_3() {
    run_churn_suite(Churn::Mixed, 3, false).await;
}

#[tokio::test]
async fn flapping_worker_does_not_pin_batch_past_flush_timeout() {
    let topic = format!("e2e-flap-{}", Uuid::new_v4());
    // Short flush timeout so the bound is observable quickly; concurrency > 1.
    let mut harness = Harness::start(
        &topic,
        1,
        2,
        2,
        Duration::from_secs(2),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    let mut guards: Vec<Option<tokio::sync::OwnedMutexGuard<()>>> = Vec::new();
    for w in &harness.workers {
        guards.push(Some(w.block().await));
    }

    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    wait_until(Duration::from_secs(10), "batch to reach a worker", || {
        harness.workers.iter().any(|w| w.arrived_count() > 0)
    })
    .await;
    let target = sole_arrived_worker(&harness);
    let other = 1 - target;

    // target stays ready but nacks; other leaves the pool, so the flush has nowhere else to go.
    harness.workers[target]
        .ingest_ok
        .store(false, Ordering::SeqCst);
    harness.workers[other]
        .healthy
        .store(false, Ordering::SeqCst);
    guards[other] = None;
    guards[target] = None;

    assert!(
        harness
            .wait_for_consumer_exit(Duration::from_secs(20))
            .await,
        "consumer must fail the batch within the flush timeout, not spin forever"
    );
    assert_eq!(
        harness.workers.iter().map(|w| w.count()).sum::<usize>(),
        0,
        "nothing should be delivered (target only errors; other is down)"
    );
}

#[tokio::test]
async fn nacking_worker_fences_worker_stream_and_reroutes_in_order() {
    let topic = format!("e2e-fence-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        2,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;

    let producer = make_producer();

    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    harness.wait_for(8, Duration::from_secs(10)).await;

    // Take down user-1's worker: it nacks and leaves the pool.
    let dead_idx = if !harness.workers[0].seqs_for("user-1").is_empty() {
        0
    } else {
        1
    };
    let live_idx = 1 - dead_idx;
    harness.workers[dead_idx]
        .healthy
        .store(false, Ordering::Relaxed);
    tokio::time::sleep(Duration::from_millis(600)).await;

    for seq in 4..8usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    harness.wait_for(12, Duration::from_secs(15)).await;

    let live_seqs = harness.workers[live_idx].seqs_for("user-1");
    let batch2_seqs: Vec<usize> = live_seqs.iter().copied().filter(|&s| s >= 4).collect();
    assert_eq!(
        batch2_seqs,
        vec![4, 5, 6, 7],
        "post-fence messages for user-1 missing or out-of-order on the live worker: {live_seqs:?}"
    );

    harness.stop().await;
}

#[tokio::test]
async fn same_key_across_partitions_completes_and_commits() {
    let topic = format!("e2e-cross-partition-key-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        2,
        1,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    for seq in 0..3usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    for seq in 3..6usize {
        produce(&producer, &topic, 1, "tok", "user-1", seq).await;
    }
    harness.wait_for(6, Duration::from_secs(15)).await;

    for seq in 6..9usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    for seq in 9..12usize {
        produce(&producer, &topic, 1, "tok", "user-1", seq).await;
    }
    harness.wait_for(12, Duration::from_secs(15)).await;

    let seqs = harness.workers[0].seqs_for("user-1");
    let mut sorted = seqs.clone();
    sorted.sort_unstable();
    assert_eq!(
        sorted,
        (0..12).collect::<Vec<_>>(),
        "every message must land exactly once; got {seqs:?}"
    );
    let partition_0: Vec<usize> = seqs
        .iter()
        .copied()
        .filter(|s| *s < 3 || (6..9).contains(s))
        .collect();
    let partition_1: Vec<usize> = seqs
        .iter()
        .copied()
        .filter(|s| (3..6).contains(s) || *s >= 9)
        .collect();
    assert_eq!(
        partition_0,
        vec![0, 1, 2, 6, 7, 8],
        "partition 0 must keep offset order"
    );
    assert_eq!(
        partition_1,
        vec![3, 4, 5, 9, 10, 11],
        "partition 1 must keep offset order"
    );

    harness.stop().await;
}
