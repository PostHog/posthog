//! End-to-end integration tests for the ingestion consumer pipeline.
//!
//! Requires Kafka on localhost:9092 (available via docker-compose).
//! Each test creates a uniquely-named topic to avoid cross-test interference.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::extract::Json as AxumJson;
use axum::routing::{get, post};
use axum::Router;
use lifecycle::{ComponentOptions, Manager};
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::client::DefaultClientContext;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

use ingestion_consumer::consumer::IngestionConsumer;
use ingestion_consumer::dispatcher::Dispatcher;
use ingestion_consumer::transport::HttpTransport;
use ingestion_consumer::types::{IngestBatchRequest, IngestBatchResponse};
use ingestion_consumer::worker_registry::{WorkerRegistry, WorkerRegistryConfig};

const KAFKA_BROKERS: &str = "localhost:9092";

// ── Kafka helpers ──────────────────────────────────────────────────────────

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
    let key = format!("{token}:{distinct_id}:{seq}");
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

// ── Fake worker ────────────────────────────────────────────────────────────

struct FakeWorker {
    pub url: String,
    /// (distinct_id, seq) pairs in arrival order.
    pub received: Arc<Mutex<Vec<(String, usize)>>>,
    pub healthy: Arc<AtomicBool>,
    _task: tokio::task::JoinHandle<()>,
}

impl FakeWorker {
    async fn start() -> Self {
        let received: Arc<Mutex<Vec<(String, usize)>>> = Arc::new(Mutex::new(Vec::new()));
        let healthy = Arc::new(AtomicBool::new(true));

        let app = Router::new()
            .route(
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
            )
            .route(
                "/ingest",
                post({
                    let recv = Arc::clone(&received);
                    let h = Arc::clone(&healthy);
                    move |AxumJson(req): AxumJson<IngestBatchRequest>| {
                        let recv = recv.clone();
                        let h = h.clone();
                        async move {
                            if !h.load(Ordering::Relaxed) {
                                return (
                                    axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                                    AxumJson(IngestBatchResponse {
                                        batch_id: req.batch_id,
                                        status: "error".to_string(),
                                        accepted: 0,
                                        error: Some("worker unhealthy".to_string()),
                                    }),
                                );
                            }
                            let accepted = req.messages.len() as u32;
                            let mut g = recv.lock().unwrap();
                            for msg in &req.messages {
                                let did =
                                    msg.headers.get("distinct_id").cloned().unwrap_or_default();
                                let seq = msg
                                    .value
                                    .as_deref()
                                    .and_then(|v| serde_json::from_str::<serde_json::Value>(v).ok())
                                    .and_then(|v| v["seq"].as_u64())
                                    .unwrap_or(0)
                                    as usize;
                                g.push((did, seq));
                            }
                            (
                                axum::http::StatusCode::OK,
                                AxumJson(IngestBatchResponse {
                                    batch_id: req.batch_id,
                                    status: "ok".to_string(),
                                    accepted,
                                    error: None,
                                }),
                            )
                        }
                    }
                }),
            );

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let url = format!("http://127.0.0.1:{}", addr.port());
        let task = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });

        Self {
            url,
            received,
            healthy,
            _task: task,
        }
    }

    fn count(&self) -> usize {
        self.received.lock().unwrap().len()
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

// ── Test harness ───────────────────────────────────────────────────────────

struct Harness {
    pub workers: Vec<FakeWorker>,
    pub shutdown: CancellationToken,
    _task: tokio::task::JoinHandle<()>,
    _probe_token: CancellationToken,
}

impl Harness {
    async fn start(
        topic: &str,
        partitions: i32,
        worker_count: usize,
        registry_config: WorkerRegistryConfig,
    ) -> Self {
        create_topic(topic, partitions).await;

        let mut workers = Vec::new();
        for _ in 0..worker_count {
            workers.push(FakeWorker::start().await);
        }
        let worker_urls: Vec<String> = workers.iter().map(|w| w.url.clone()).collect();

        let registry = Arc::new(WorkerRegistry::new(&worker_urls, registry_config));
        let probe_token = CancellationToken::new();
        Arc::clone(&registry).start_probing(probe_token.clone());

        let dispatcher = Arc::new(Dispatcher::new(Arc::clone(&registry)));
        let transport = Arc::new(HttpTransport::new(
            Duration::from_secs(5),
            0, // no retries — errors surface immediately for health tracking
            None,
            &worker_urls,
            1,
        ));

        let mut manager = Manager::builder("e2e-test")
            .with_trap_signals(false)
            .build();
        let handle = manager.register("consumer", ComponentOptions::new());
        let shutdown = handle.shutdown_token();

        let kafka_consumer: StreamConsumer = ClientConfig::new()
            .set("bootstrap.servers", KAFKA_BROKERS)
            .set("group.id", format!("e2e-{}", Uuid::new_v4()))
            .set("auto.offset.reset", "earliest")
            .set("enable.auto.commit", "false")
            .set("enable.auto.offset.store", "false")
            .set("socket.timeout.ms", "5000")
            .create()
            .expect("kafka consumer");
        kafka_consumer.subscribe(&[topic]).expect("subscribe");

        let consumer = IngestionConsumer::from_parts(
            kafka_consumer,
            dispatcher,
            transport,
            worker_urls,
            50,
            Duration::from_millis(100),
            handle,
        );

        let task = tokio::spawn(async move { consumer.process().await });

        // Give the consumer time to connect and enter the poll loop.
        tokio::time::sleep(Duration::from_millis(300)).await;

        Self {
            workers,
            shutdown,
            _task: task,
            _probe_token: probe_token,
        }
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

    async fn stop(self) {
        self.shutdown.cancel();
        let _ = tokio::time::timeout(Duration::from_secs(3), self._task).await;
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
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

/// Kafka partition order is preserved per distinct_id on each worker.
///
/// With concurrent_batches=1 (sequential processing), pins are evicted after
/// each batch resolves, so the same distinct_id can be assigned to different
/// workers across batches. The guarantee is narrower: wherever a distinct_id's
/// messages land, they arrive in Kafka sequence order on that worker.
///
/// Cross-batch stickiness (all distinct_id events always to the same pod) is
/// the responsibility of the concurrent-batches layer: when concurrent_batches>1,
/// the Dispatcher's ref-counted pins keep the assignment alive across overlapping
/// in-flight batches. That invariant is tested in the concurrent-batches suite.
#[tokio::test]
async fn messages_per_distinct_id_arrive_in_order() {
    let topic = format!("e2e-ordering-{}", Uuid::new_v4());
    let harness = Harness::start(&topic, 3, 2, fast_registry_config()).await;

    let producer = make_producer();
    for seq in 0..8usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
        produce(&producer, &topic, 2, "tok", "user-3", seq).await;
    }

    harness.wait_for(24, Duration::from_secs(15)).await;

    // All messages must arrive.
    let total: usize = harness.workers.iter().map(|w| w.count()).sum();
    assert_eq!(total, 24, "expected 24 messages total, got {total}");

    // On whichever worker(s) a distinct_id's messages land, they must be in
    // ascending sequence order — no reordering within a single worker's delivery.
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

/// When a worker becomes unhealthy, its sticky pins are dropped and subsequent
/// messages for the same distinct_id are rerouted to a healthy worker.
#[tokio::test]
async fn failing_worker_triggers_rerouting() {
    let topic = format!("e2e-failover-{}", Uuid::new_v4());
    let harness = Harness::start(&topic, 2, 2, fast_registry_config()).await;

    let producer = make_producer();

    // Batch 1: 4 messages for user-1 (partition 0) and user-2 (partition 1).
    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    harness.wait_for(8, Duration::from_secs(10)).await;

    // Identify which worker owns user-1 and take it down.
    let dead_idx = if !harness.workers[0].seqs_for("user-1").is_empty() {
        0
    } else {
        1
    };
    let live_idx = 1 - dead_idx;

    harness.workers[dead_idx]
        .healthy
        .store(false, Ordering::Relaxed);

    // Wait for probe failures → Unhealthy → dead declaration.
    // probe_interval*probe_failure_threshold + dead_declaration ≈ 300ms; use 600ms to be safe.
    tokio::time::sleep(Duration::from_millis(600)).await;

    // Batch 2: 4 more messages for user-1. The pin was dropped; should route to the live worker.
    for seq in 4..8usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    harness.wait_for(12, Duration::from_secs(10)).await;

    // Batch-2 messages (seq 4–7) must all be on the live worker and in order.
    let live_seqs = harness.workers[live_idx].seqs_for("user-1");
    let batch2_seqs: Vec<usize> = live_seqs.iter().copied().filter(|&s| s >= 4).collect();
    assert_eq!(
        batch2_seqs,
        vec![4, 5, 6, 7],
        "batch-2 messages for user-1 missing or out-of-order on live worker: {live_seqs:?}"
    );

    harness.stop().await;
}
