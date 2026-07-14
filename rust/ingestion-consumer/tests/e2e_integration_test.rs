//! End-to-end integration tests for the ingestion consumer pipeline.
//!
//! Requires Kafka on localhost:9092 (available via docker-compose).
//! Each test creates a uniquely-named topic to avoid cross-test interference.

use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::extract::Json as AxumJson;
use axum::routing::{get, post};
use axum::Router;
use futures::StreamExt;
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

use ingestion_consumer::consumer::{IngestionConsumer, IngestionConsumerOptions};
use ingestion_consumer::discovery::reconcile_membership;
use ingestion_consumer::dispatcher::Dispatcher;
use ingestion_consumer::transport::HttpTransport;
use ingestion_consumer::types::{IngestBatchRequest, IngestBatchResponse, SerializedKafkaMessage};
use ingestion_consumer::worker_registry::{WorkerId, WorkerRegistry, WorkerRegistryConfig};

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

/// Produce a record with full control over payload bytes and optional headers —
/// for malformed-input scenarios (missing routing headers, non-UTF-8 bytes).
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

// ── Fake worker ────────────────────────────────────────────────────────────

struct FakeWorker {
    pub url: String,
    /// (distinct_id, seq) pairs in arrival order.
    pub received: Arc<Mutex<Vec<(String, usize)>>>,
    /// Gates /_ready (pool membership). When false the worker leaves the pool.
    pub healthy: Arc<AtomicBool>,
    /// Gates /ingest only. When false the worker stays ready (in the pool) but
    /// fails every send — a "flapping" worker, used to exercise the flush loop's
    /// re-defer path and its timeout bound.
    pub ingest_ok: Arc<AtomicBool>,
    /// When set, the next /ingest request is processed and recorded but answered
    /// with an error — a "lost ACK". Models the ambiguous outcome where the
    /// worker did the work but the consumer never learns it, so it replays.
    pub ack_lost_once: Arc<AtomicBool>,
    /// When true, every /ingest request is rejected with HTTP 400 without
    /// ingesting anything — a poison batch this worker will never accept.
    pub reject_4xx: Arc<AtomicBool>,
    /// When set, the next /ingest request is ingested in full but reports one
    /// message fewer than sent — a partial-acceptance contract violation.
    pub underreport_once: Arc<AtomicBool>,
    /// Number of /ingest requests that have reached the handler. Counted before
    /// the gate, so a test can observe a batch is in-flight even while held.
    arrived: Arc<AtomicUsize>,
    /// Held by the handler for the duration of each /ingest request. A test can
    /// acquire it via `block()` to freeze a request in flight (simulating a slow
    /// worker), then drop the guard to let it complete.
    gate: Arc<tokio::sync::Mutex<()>>,
    _task: tokio::task::JoinHandle<()>,
}

/// A receipt-ordered log of `(distinct_id, seq)` shared across all workers in a
/// run. The shared mutex gives every accepted message a slot in a single total
/// order, so a test can reconstruct global delivery order across reroutes and
/// assert per-distinct_id ordering, no loss, and no duplication.
type DeliveryLog = Arc<Mutex<Vec<(String, usize)>>>;

impl FakeWorker {
    async fn start() -> Self {
        Self::start_inner(None).await
    }

    /// Like `start`, but also appends every accepted message to a shared,
    /// cross-worker delivery log (for the churn/ordering suite).
    async fn start_logged(delivery_log: DeliveryLog) -> Self {
        Self::start_inner(Some(delivery_log)).await
    }

    async fn start_inner(delivery_log: Option<DeliveryLog>) -> Self {
        let received: Arc<Mutex<Vec<(String, usize)>>> = Arc::new(Mutex::new(Vec::new()));
        let healthy = Arc::new(AtomicBool::new(true));
        let ingest_ok = Arc::new(AtomicBool::new(true));
        let ack_lost_once = Arc::new(AtomicBool::new(false));
        let reject_4xx = Arc::new(AtomicBool::new(false));
        let underreport_once = Arc::new(AtomicBool::new(false));
        let arrived = Arc::new(AtomicUsize::new(0));
        let gate = Arc::new(tokio::sync::Mutex::new(()));

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
                    let ingest_ok = Arc::clone(&ingest_ok);
                    let ack_lost_once = Arc::clone(&ack_lost_once);
                    let reject_4xx = Arc::clone(&reject_4xx);
                    let underreport_once = Arc::clone(&underreport_once);
                    let arrived = Arc::clone(&arrived);
                    let gate = Arc::clone(&gate);
                    let delivery_log = delivery_log.clone();
                    move |AxumJson(req): AxumJson<IngestBatchRequest>| {
                        let recv = recv.clone();
                        let h = h.clone();
                        let ingest_ok = ingest_ok.clone();
                        let ack_lost_once = ack_lost_once.clone();
                        let reject_4xx = reject_4xx.clone();
                        let underreport_once = underreport_once.clone();
                        let arrived = arrived.clone();
                        let gate = gate.clone();
                        let delivery_log = delivery_log.clone();
                        async move {
                            arrived.fetch_add(1, Ordering::SeqCst);
                            // Block here while a test holds the gate (slow worker).
                            let _hold = gate.lock().await;
                            // Health is checked after the gate so a test can flip a
                            // held request to a failure before releasing it. A
                            // worker that is ready but has ingest_ok=false fails
                            // sends while staying in the pool (a flapping worker).
                            if !h.load(Ordering::Relaxed) || !ingest_ok.load(Ordering::Relaxed) {
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
                            // A poison batch: permanently rejected with a client
                            // error, nothing ingested.
                            if reject_4xx.load(Ordering::SeqCst) {
                                return (
                                    axum::http::StatusCode::BAD_REQUEST,
                                    AxumJson(IngestBatchResponse {
                                        batch_id: req.batch_id,
                                        status: "error".to_string(),
                                        accepted: 0,
                                        error: Some("poison batch".to_string()),
                                    }),
                                );
                            }
                            let accepted = req.messages.len() as u32;
                            let entries: Vec<(String, usize)> = req
                                .messages
                                .iter()
                                .map(|msg| {
                                    let did =
                                        msg.headers.get("distinct_id").cloned().unwrap_or_default();
                                    let seq = msg
                                        .value
                                        .as_deref()
                                        .and_then(|v| {
                                            serde_json::from_str::<serde_json::Value>(v).ok()
                                        })
                                        .and_then(|v| v["seq"].as_u64())
                                        .unwrap_or(0)
                                        as usize;
                                    (did, seq)
                                })
                                .collect();
                            recv.lock().unwrap().extend(entries.iter().cloned());
                            // Record the whole batch as one contiguous slot in the
                            // shared total order (it was accepted as a unit).
                            if let Some(log) = &delivery_log {
                                log.lock().unwrap().extend(entries);
                            }
                            // The work is done and recorded, but the ACK is lost:
                            // answer with an error so the consumer must replay.
                            if ack_lost_once.swap(false, Ordering::SeqCst) {
                                return (
                                    axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                                    AxumJson(IngestBatchResponse {
                                        batch_id: req.batch_id,
                                        status: "error".to_string(),
                                        accepted: 0,
                                        error: Some("ack lost".to_string()),
                                    }),
                                );
                            }
                            // Partial acceptance: everything was ingested, but the
                            // response claims one message fewer than sent.
                            let reported = if underreport_once.swap(false, Ordering::SeqCst) {
                                accepted.saturating_sub(1)
                            } else {
                                accepted
                            };
                            (
                                axum::http::StatusCode::OK,
                                AxumJson(IngestBatchResponse {
                                    batch_id: req.batch_id,
                                    status: "ok".to_string(),
                                    accepted: reported,
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
            ingest_ok,
            ack_lost_once,
            reject_4xx,
            underreport_once,
            arrived,
            gate,
            _task: task,
        }
    }

    fn count(&self) -> usize {
        self.received.lock().unwrap().len()
    }

    /// /ingest requests that have reached this worker (including any held by the gate).
    fn arrived_count(&self) -> usize {
        self.arrived.load(Ordering::SeqCst)
    }

    /// Freeze this worker's /ingest handling: requests arrive but block until the
    /// returned guard is dropped. Acquire before producing so the batch is caught.
    async fn block(&self) -> tokio::sync::OwnedMutexGuard<()> {
        Arc::clone(&self.gate).lock_owned().await
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
    pub registry: Arc<WorkerRegistry>,
    pub dispatcher: Arc<Dispatcher>,
    /// Cross-worker, receipt-ordered log of every accepted message.
    pub delivery_log: DeliveryLog,
    pub shutdown: CancellationToken,
    task: Option<tokio::task::JoinHandle<()>>,
    _probe_token: CancellationToken,
    topic: String,
    /// Consumer group id, kept so `restart_consumer` rejoins the same group.
    group_id: String,
    max_in_flight: usize,
    deferred_flush_timeout: Duration,
}

/// Build a Kafka consumer subscribed to `topic` in `group_id`, configured like
/// the production batch consumer (no auto commit/store, earliest reset). The
/// short session timeout makes group handovers observable quickly in tests.
/// `instance_id` opts into static membership (`group.instance.id`).
fn make_kafka_consumer(topic: &str, group_id: &str, instance_id: Option<&str>) -> StreamConsumer {
    let mut config = ClientConfig::new();
    config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", group_id)
        .set("auto.offset.reset", "earliest")
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .set("session.timeout.ms", "6000")
        .set("socket.timeout.ms", "5000");
    if let Some(id) = instance_id {
        config.set("group.instance.id", id);
    }
    let kafka_consumer: StreamConsumer = config.create().expect("kafka consumer");
    kafka_consumer.subscribe(&[topic]).expect("subscribe");
    kafka_consumer
}

/// Reap drained workers exactly as `main.rs` does in production: complete the
/// drain of an idle drainer, then remove reaped workers from the registry and
/// transport. Runs until `token` is cancelled. (A faster tick than production's
/// 1s keeps test scenarios responsive.)
fn spawn_reaper(
    registry: Arc<WorkerRegistry>,
    transport: Arc<HttpTransport>,
    dispatcher: Arc<Dispatcher>,
    token: CancellationToken,
) {
    tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = token.cancelled() => break,
                _ = tokio::time::sleep(Duration::from_millis(100)) => {}
            }
            for worker in registry.draining_workers() {
                if !dispatcher.has_in_flight(&worker) {
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

        let dispatcher = Arc::new(Dispatcher::new(Arc::clone(&registry)));
        let registry_for_test = Arc::clone(&registry);
        let dispatcher_for_test = Arc::clone(&dispatcher);
        let transport = Arc::new(HttpTransport::new(
            Duration::from_secs(5),
            0, // no retries — errors surface immediately for health tracking
            None,
            &worker_urls,
            1,
        ));
        spawn_reaper(
            Arc::clone(&registry),
            Arc::clone(&transport),
            Arc::clone(&dispatcher),
            probe_token.clone(),
        );

        let mut manager = Manager::builder("e2e-test")
            .with_trap_signals(false)
            .build();
        let handle = manager.register("consumer", ComponentOptions::new());
        let shutdown = handle.shutdown_token();

        let group_id = format!("e2e-{}", Uuid::new_v4());
        let kafka_consumer = make_kafka_consumer(topic, &group_id, None);

        let consumer = IngestionConsumer::from_parts(
            kafka_consumer,
            dispatcher,
            transport,
            worker_urls,
            IngestionConsumerOptions {
                batch_size: 50,
                batch_timeout: Duration::from_millis(100),
                max_in_flight_batches: max_in_flight,
                group_id: "e2e-test".to_string(),
                deferred_flush_timeout,
            },
            handle,
        );

        let task = tokio::spawn(async move { consumer.process().await });

        // Give the consumer time to connect and enter the poll loop.
        tokio::time::sleep(Duration::from_millis(300)).await;

        Self {
            workers,
            registry: registry_for_test,
            dispatcher: dispatcher_for_test,
            delivery_log,
            shutdown,
            task: Some(task),
            _probe_token: probe_token,
            topic: topic.to_string(),
            group_id,
            max_in_flight,
            deferred_flush_timeout,
        }
    }

    /// Simulate a crash: abort the consumer task in place — no shutdown signal,
    /// no draining, no offset commit — as an OOM-kill would.
    fn crash_consumer(&mut self) {
        if let Some(task) = self.task.take() {
            task.abort();
        }
    }

    /// Start a fresh consumer stack — a new Kafka client in the same consumer
    /// group, plus new registry/dispatcher/transport — against the same topic
    /// and workers, modeling a pod restart. Only the FakeWorkers survive,
    /// mirroring production where worker pods outlive a consumer pod.
    async fn restart_consumer(&mut self, registry_config: WorkerRegistryConfig) {
        let worker_urls: Vec<String> = self.workers.iter().map(|w| w.url.clone()).collect();

        let registry = Arc::new(WorkerRegistry::new(&worker_urls, registry_config));
        Arc::clone(&registry).start_probing(self._probe_token.clone());
        let dispatcher = Arc::new(Dispatcher::new(Arc::clone(&registry)));
        let transport = Arc::new(HttpTransport::new(
            Duration::from_secs(5),
            0,
            None,
            &worker_urls,
            1,
        ));
        spawn_reaper(
            Arc::clone(&registry),
            Arc::clone(&transport),
            Arc::clone(&dispatcher),
            self._probe_token.clone(),
        );

        let mut manager = Manager::builder("e2e-test-restarted")
            .with_trap_signals(false)
            .build();
        let handle = manager.register("consumer", ComponentOptions::new());
        self.shutdown = handle.shutdown_token();

        let kafka_consumer = make_kafka_consumer(&self.topic, &self.group_id, None);
        let consumer = IngestionConsumer::from_parts(
            kafka_consumer,
            Arc::clone(&dispatcher),
            transport,
            worker_urls,
            IngestionConsumerOptions {
                batch_size: 50,
                batch_timeout: Duration::from_millis(100),
                max_in_flight_batches: self.max_in_flight,
                group_id: "e2e-test".to_string(),
                deferred_flush_timeout: self.deferred_flush_timeout,
            },
            handle,
        );

        self.registry = registry;
        self.dispatcher = dispatcher;
        self.task = Some(tokio::spawn(async move { consumer.process().await }));

        // Give the restarted consumer time to rejoin the group and start polling.
        tokio::time::sleep(Duration::from_millis(300)).await;
    }

    /// Wait for the consumer's process loop to exit on its own (e.g. after it
    /// fails a batch), up to `timeout`. Returns true if it exited within the bound.
    async fn wait_for_consumer_exit(&mut self, timeout: Duration) -> bool {
        let Some(task) = self.task.take() else {
            return true;
        };
        tokio::time::timeout(timeout, task).await.is_ok()
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

/// Poll `cond` until it returns true or the timeout elapses (panics on timeout).
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

/// Index of the single worker that has received an /ingest request so far.
/// Panics if zero or more than one have — callers rely on a unique pin.
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
    let harness = Harness::start(
        &topic,
        3,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;

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

/// Graceful drain end-to-end: a worker that begins draining receives no new
/// work, keeps the messages it already has (no reprocessing, no loss), and
/// subsequent messages for the same distinct_id reroute in order to a surviving
/// worker. The drainer stays alive throughout (it is not failed), so the probe
/// must not declare it dead.
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

    // Batch 1: 4 messages each for user-1 (partition 0) and user-2 (partition 1).
    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    harness.wait_for(8, Duration::from_secs(10)).await;

    // Identify which worker owns user-1 and begin draining it.
    let drain_idx = if !harness.workers[0].seqs_for("user-1").is_empty() {
        0
    } else {
        1
    };
    let live_idx = 1 - drain_idx;
    let drain_url = harness.workers[drain_idx].url.clone();
    harness.registry.start_draining(&drain_url);

    // With the reaper running (as in production), an idle drainer is promptly
    // reaped — cleanly removed from the pool once its in-flight hits zero —
    // rather than lingering or being probed to death mid-drain.
    wait_until(Duration::from_secs(2), "idle drainer to be reaped", || {
        !harness
            .registry
            .workers()
            .iter()
            .any(|w| w.as_ref() == drain_url)
    })
    .await;

    // Batch 2: 4 more messages for user-1. The drainer takes no new work, so
    // these must route to the live worker, in order.
    for seq in 4..8usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }
    harness.wait_for(12, Duration::from_secs(10)).await;

    // No reprocessing / no loss: each user-1 seq 0..8 is delivered exactly once.
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

    // The draining worker received no new work after draining began.
    let drained_seqs = harness.workers[drain_idx].seqs_for("user-1");
    assert!(
        drained_seqs.iter().all(|&s| s < 4),
        "draining worker received new work: {drained_seqs:?}"
    );

    // Batch-2 messages all landed on the live worker, in ascending order.
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

// ── Failure-triggered defer + flush at the consumer level ────────────────────
//
// These drive the consumer's defer→stash→flush loop end-to-end through real
// Kafka. A "blocking" worker holds a batch in flight so a test can flip it to a
// failure before it responds; the failed send then exercises `defer_failed` and
// the `complete_oldest_batch` flush loop. (The drain-triggered defer needs a
// drain signal injected between two overlapping batch assigns, which isn't
// reachable from a black-box test; that path is covered by the dispatcher unit
// and dispatcher_integration tests, which drive `assign`/`flush_deferred`
// directly.)

/// Whether `url` is currently routable (healthy or degraded) per the registry.
fn in_pool(harness: &Harness, url: &str) -> bool {
    harness
        .registry
        .healthy_workers()
        .iter()
        .any(|w| w.as_ref() == url)
}

/// Whether `url` is routable per a bare registry (no Harness).
fn registry_has(registry: &WorkerRegistry, url: &str) -> bool {
    registry.healthy_workers().iter().any(|w| w.as_ref() == url)
}

/// Build a dispatcher-level message for a distinct_id carrying `seq` in its body,
/// so a FakeWorker records it the same way it records produced Kafka records.
fn worker_msg(distinct_id: &str, seq: usize) -> SerializedKafkaMessage {
    let mut headers = HashMap::new();
    headers.insert("token".to_string(), "tok".to_string());
    headers.insert("distinct_id".to_string(), distinct_id.to_string());
    SerializedKafkaMessage {
        topic: "t".to_string(),
        partition: 0,
        offset: seq as i64,
        timestamp: 0,
        key: None,
        value: Some(format!(r#"{{"seq":{seq}}}"#)),
        headers,
    }
}

/// A send that fails mid-flight is deferred and replayed, in order, to the
/// surviving worker — no loss, no duplication, no reordering.
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

    // Turn the held request into a failure, then release everything.
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

/// In a batch split across two workers, only the failed sub-batch is deferred
/// and replayed; the successful one is not re-sent. Everything ends up on the
/// survivor, in order, with the failed worker having recorded nothing.
#[tokio::test]
async fn partial_send_failure_replays_only_the_failed_subbatch() {
    let topic = format!("e2e-replay-partial-{}", Uuid::new_v4());
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

    let mut guards: Vec<Option<tokio::sync::OwnedMutexGuard<()>>> = Vec::new();
    for w in &harness.workers {
        guards.push(Some(w.block().await));
    }

    // Two equal-size keys on two partitions → bin-packed one per worker: one
    // batch, two sub-batches, one per worker.
    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    wait_until(
        Duration::from_secs(10),
        "both workers to receive a sub-batch",
        || harness.workers.iter().all(|w| w.arrived_count() > 0),
    )
    .await;

    // Fail worker 0's sub-batch only. Whatever key it held replays to worker 1,
    // so worker 1 ends with both keys and worker 0 with nothing.
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

/// When a send fails and there is no healthy worker to replay to, the deferred
/// work is held (not lost, not dropped) and the flush loop retries until a
/// worker returns, then drains in order.
#[tokio::test]
async fn deferred_flush_retries_until_a_worker_recovers() {
    let topic = format!("e2e-replay-wait-{}", Uuid::new_v4());
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

    // Wait until worker 0 has also left the pool. The failed send is now
    // deferred with nowhere to go. (At max_in_flight=1 the consumer is parked in
    // the flush loop for the oldest batch and stops consuming, so only that
    // batch's messages are stashed — Kafka polling may have split the produced
    // records across batches; the exact count doesn't matter.)
    wait_until(
        Duration::from_secs(10),
        "worker 0 to leave the pool",
        || !in_pool(&harness, &harness.workers[0].url),
    )
    .await;
    wait_until(
        Duration::from_secs(10),
        "the failed send to be deferred",
        || harness.dispatcher.stashed_messages() > 0,
    )
    .await;

    // The deferred work is held steady — the flush loop is backing off, not
    // dropping anything — for as long as no worker is available.
    let held = harness.dispatcher.stashed_messages();
    tokio::time::sleep(Duration::from_millis(400)).await;
    assert_eq!(
        harness.dispatcher.stashed_messages(),
        held,
        "deferred work must be held steady while no worker is available"
    );

    // Recover worker 1 → the flush loop drains the stash to it, then the consumer
    // resumes and delivers the rest. All of user-1 lands on worker 1, in order.
    harness.workers[1].healthy.store(true, Ordering::SeqCst);
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

/// A failed multi-key sub-batch replays every key, each in its own Kafka order,
/// once a worker is available.
#[tokio::test]
async fn multi_key_send_failure_replays_every_key_in_order() {
    let topic = format!("e2e-replay-multikey-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        3,
        2,
        1,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    // Worker 1 out so all three keys land on worker 0 as one sub-batch.
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

    // Fail worker 0 and bring worker 1 back as the replay target.
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

/// A replay whose target also fails is re-deferred and retried until it lands —
/// cascading failures during flush never lose or reorder the deferred work.
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

    // Fail the initial send → the batch defers and the flush re-routes to the
    // other worker, whose request we are holding via its gate.
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
    assert!(
        harness.dispatcher.stashed_messages() > 0,
        "re-deferred work must be held after the replay target also fails"
    );

    // Recover the second worker → the replay finally lands, in order.
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

/// Drain-triggered defer through the dispatcher + real HTTP transport — the path
/// the consumer drives. The Kafka poll loop can't inject a drain between two
/// overlapping batch assigns deterministically (it assigns available batches
/// back-to-back and parks in `complete_oldest_batch` the moment data dries up),
/// so this models the consumer's exact sequence — assign, drain, assign (defer),
/// resolve, flush — and delivers over real HTTP, asserting the deferred key lands
/// on the survivor in order.
#[tokio::test]
async fn drain_defer_flush_delivers_to_survivor_over_http() {
    let w0 = FakeWorker::start().await;
    let w1 = FakeWorker::start().await;
    let urls = vec![w0.url.clone(), w1.url.clone()];
    let workers = [w0, w1];

    let registry = Arc::new(WorkerRegistry::new(&urls, fast_registry_config()));
    let probe_token = CancellationToken::new();
    Arc::clone(&registry).start_probing(probe_token.clone());
    let dispatcher = Dispatcher::new(Arc::clone(&registry));
    let transport = HttpTransport::new(Duration::from_secs(5), 0, None, &urls, 1);

    // batch-1: user-1 pins to a worker. Send it for real but DON'T resolve, so it
    // is genuinely in flight on that worker.
    let b1 = dispatcher.assign("batch-1", vec![worker_msg("user-1", 0)]);
    assert_eq!(b1.len(), 1);
    let pinned_url = b1[0].worker.to_string();
    let pinned_idx = workers.iter().position(|w| w.url == pinned_url).unwrap();
    let survivor_idx = 1 - pinned_idx;
    transport
        .send_batch(&pinned_url, "batch-1", b1[0].messages.clone())
        .await
        .expect("batch-1 send");

    // Drain the pinned worker. The next batch for the key must defer (its worker
    // is draining and still has in-flight work — rerouting now would reorder it).
    registry.start_draining(&pinned_url);
    let b2 = dispatcher.assign("batch-2", vec![worker_msg("user-1", 1)]);
    assert!(b2.is_empty(), "must defer while the pinned worker drains");
    assert!(dispatcher.has_deferred("batch-2"));

    // Resolve batch-1 (the drainer finishes its in-flight), then flush batch-2:
    // it re-routes to the survivor.
    dispatcher.on_sub_batch_resolved(
        &b1[0].worker,
        b1[0].messages.len(),
        &b1[0].routing_keys,
        false,
    );
    let f2 = dispatcher.flush_deferred("batch-2");
    assert_eq!(f2.len(), 1);
    assert_eq!(
        f2[0].worker.to_string(),
        workers[survivor_idx].url,
        "deferred group flushes to the survivor, not the drainer"
    );
    transport
        .send_batch(f2[0].worker.as_ref(), "batch-2", f2[0].messages.clone())
        .await
        .expect("batch-2 flush send");

    // The drainer kept its in-flight seq 0; the deferred seq 1 landed on the
    // survivor — delivered over real HTTP, in order, with nothing lost.
    assert_eq!(workers[pinned_idx].seqs_for("user-1"), vec![0]);
    assert_eq!(workers[survivor_idx].seqs_for("user-1"), vec![1]);
    assert!(
        registry_has(&registry, &workers[survivor_idx].url),
        "survivor stayed routable throughout"
    );

    probe_token.cancel();
}

// ── Pool-wide outages, forced reap, crash restart, ambiguous ACKs ────────────

/// A transient full-pool drain — every worker leaving at once, as during a
/// deploy overlap — must not fail the batch: fresh keys that can't route
/// anywhere are held and delivered once a worker returns, instead of being
/// dropped (which fails the batch and restarts the process).
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

    // One worker returns — the held messages must deliver to it, in order.
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

/// A worker that leaves the pool but never finishes its in-flight work is
/// force-reaped at the drain timeout — removed from the registry and transport
/// while its request is still live. The reap must not break the in-flight
/// resolve, and the key's deferred messages must re-route to a survivor in
/// order once the held batch completes.
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
        harness.dispatcher.stashed_messages() > 0
    })
    .await;

    // The drain timeout passes with the batch still held → the reaper force-
    // removes the worker while its request is live.
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

    // Release everything: batch 1 completes on the (already removed) worker,
    // then batch 2 flushes to the survivor.
    guards.clear();
    harness.wait_for(8, Duration::from_secs(15)).await;

    assert_eq!(
        harness.workers[pinned].seqs_for("user-1"),
        vec![0, 1, 2, 3],
        "the reaped worker keeps exactly its in-flight batch"
    );
    assert_eq!(
        harness.workers[survivor].seqs_for("user-1"),
        vec![4, 5, 6, 7],
        "deferred messages re-route to the survivor in order"
    );

    harness.stop().await;
}

/// A consumer crash after a batch reached a worker but before its offsets were
/// committed must not lose anything: the restarted consumer resumes from the
/// last commit and redelivers. Duplicates are allowed (at-least-once); loss is
/// not.
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

    // Hold both workers so the first batch is in flight but never ACKs — its
    // offsets are never committed.
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

    // Crash the consumer mid-flight, then release the held requests. Whether
    // the worker ends up recording that first delivery is exactly the ambiguity
    // a restart must tolerate: duplicates allowed, loss not.
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

/// A worker that processes a batch but whose ACK is lost is indistinguishable
/// from a failed send, so the consumer replays the batch: duplicates are the
/// accepted cost of at-least-once, loss never is, and the replay lands behind
/// the original delivery.
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

    // Arm both workers (the batch could land on either): the first /ingest each
    // receives is processed and recorded, but answered with an error.
    for w in &harness.workers {
        w.ack_lost_once.store(true, Ordering::SeqCst);
    }

    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
    }

    // Original delivery (recorded, ACK lost) + replay → 8 recorded entries.
    harness.wait_for(8, Duration::from_secs(15)).await;

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

// ── Poison batches and contract violations ───────────────────────────────────

/// A batch every worker permanently rejects with a 4xx must fail the consumer
/// within the flush timeout — failing safe (nothing ingested, nothing
/// committed, redelivered after restart) rather than spinning forever. Until a
/// DLQ path exists, a poison batch crash-loops the process by design; this
/// pins the "safe" half of that trade-off.
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

/// A worker that ingests a batch but reports fewer accepted messages than were
/// sent violates the transport contract. The consumer must treat the batch as
/// incomplete and fail it — never commit offsets over an under-acknowledged
/// batch, which would silently lose the unaccounted messages.
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
        harness.workers.iter().map(|w| w.count()).sum::<usize>(),
        4,
        "the worker did ingest the batch — redelivery after restart may duplicate, never lose"
    );
}

// ── Drain edge cases and malformed input ─────────────────────────────────────

/// A drainer that crashes mid-drain (its in-flight send fails instead of
/// finishing) must not wedge the drain: both its failed in-flight batch and
/// the work deferred behind it replay to the survivor, in order.
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
        harness.dispatcher.stashed_messages() > 0
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

/// The whole pool failing at once with multiple keys in flight, at
/// max_in_flight > 1: everything is stashed while nothing is routable, then
/// drains to the first recovered worker with per-key order intact.
#[tokio::test]
async fn full_pool_send_failure_with_multiple_keys_recovers_in_order() {
    let topic = format!("e2e-pool-loss-{}", Uuid::new_v4());
    let harness = Harness::start(
        &topic,
        2,
        2,
        3,
        Duration::from_secs(60),
        fast_registry_config(),
    )
    .await;
    let producer = make_producer();

    let mut guards: Vec<Option<tokio::sync::OwnedMutexGuard<()>>> = Vec::new();
    for w in &harness.workers {
        guards.push(Some(w.block().await));
    }

    // Two equal keys on two partitions bin-pack one per worker.
    for seq in 0..4usize {
        produce(&producer, &topic, 0, "tok", "user-1", seq).await;
        produce(&producer, &topic, 1, "tok", "user-2", seq).await;
    }
    wait_until(
        Duration::from_secs(10),
        "both workers to hold a sub-batch",
        || harness.workers.iter().all(|w| w.arrived_count() > 0),
    )
    .await;

    // The whole pool fails at once with work in flight — everything must be
    // stashed, not lost, while nothing is routable.
    for w in &harness.workers {
        w.healthy.store(false, Ordering::SeqCst);
    }
    guards.clear();
    wait_until(
        Duration::from_secs(10),
        "all failed work to be stashed",
        || harness.dispatcher.stashed_messages() == 8,
    )
    .await;

    // One worker recovers → everything drains to it, per-key order intact.
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

/// Messages without token/distinct_id headers route under synthetic
/// per-message keys; a send failure must replay them exactly once, like any
/// other message.
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

    // Fail worker 0 and recover worker 1 as the replay target.
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
    // Headerless messages record under an empty distinct_id; all three must
    // replay exactly once (order across distinct synthetic keys is undefined).
    let mut seqs = harness.workers[1].seqs_for("");
    seqs.sort_unstable();
    assert_eq!(
        seqs,
        vec![0, 1, 2],
        "headerless messages must replay exactly once"
    );

    harness.stop().await;
}

/// A non-UTF-8 payload cannot round-trip the string wire format — its body is
/// nulled in transit today (a known content-loss gap) — but the event itself
/// must still route via its headers and reach a worker, not be dropped.
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
    // 0xF0 0x28 0x8C 0x28 is invalid UTF-8.
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

// ── Fleet redeploy and consumer-group membership ─────────────────────────────

/// A full fleet replacement, reconciled exactly as EndpointSlice discovery
/// does: the desired set flips to brand-new workers, the old ones drain and
/// are reaped, and traffic keeps flowing — exactly once, in per-key order.
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

    // The old fleet is drained and reaped out of the pool entirely.
    wait_until(Duration::from_secs(5), "old workers to be reaped", || {
        harness.registry.worker_count() == 2
    })
    .await;

    // Exactly once, in per-key order, across the redeploy.
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

/// A second consumer joining the same group rebalances partitions away from
/// the first while it holds an uncommitted in-flight batch. Redelivery of that
/// batch on the new owner may duplicate (at-least-once) — but nothing may be
/// lost across the handover.
#[tokio::test]
async fn second_consumer_joining_the_group_preserves_all_messages() {
    let topic = format!("e2e-two-consumers-{}", Uuid::new_v4());
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

    // The first consumer owns both partitions and has an uncommitted batch
    // held in flight.
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

    // A second consumer joins the same group with its own routing stack but
    // the same worker pool.
    let worker_urls: Vec<String> = harness.workers.iter().map(|w| w.url.clone()).collect();
    let registry2 = Arc::new(WorkerRegistry::new(&worker_urls, fast_registry_config()));
    let probe2 = CancellationToken::new();
    Arc::clone(&registry2).start_probing(probe2.clone());
    let dispatcher2 = Arc::new(Dispatcher::new(Arc::clone(&registry2)));
    let transport2 = Arc::new(HttpTransport::new(
        Duration::from_secs(5),
        0,
        None,
        &worker_urls,
        1,
    ));
    let mut manager2 = Manager::builder("e2e-c2").with_trap_signals(false).build();
    let handle2 = manager2.register("consumer", ComponentOptions::new());
    let shutdown2 = handle2.shutdown_token();
    let consumer2 = IngestionConsumer::from_parts(
        make_kafka_consumer(&topic, &harness.group_id, None),
        dispatcher2,
        transport2,
        worker_urls,
        IngestionConsumerOptions {
            batch_size: 50,
            batch_timeout: Duration::from_millis(100),
            max_in_flight_batches: 1,
            group_id: "e2e-test".to_string(),
            deferred_flush_timeout: Duration::from_secs(60),
        },
        handle2,
    );
    let task2 = tokio::spawn(async move { consumer2.process().await });

    // Release the held batch so the first consumer resumes polling and the
    // rebalance can complete, then keep traffic flowing on both partitions.
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

    shutdown2.cancel();
    let _ = tokio::time::timeout(Duration::from_secs(3), task2).await;
    probe2.cancel();
    harness.stop().await;
}

/// A same-name pod restart racing its old instance: a second member joins with
/// the same `group.instance.id`, so the broker fences the first. The fenced
/// instance's client is permanently dead — the consumer must exit (so the pod
/// restarts) rather than keep polling it while reporting healthy.
#[tokio::test]
async fn fenced_static_member_exits_on_fatal_error() {
    let topic = format!("e2e-fenced-{}", Uuid::new_v4());
    create_topic(&topic, 1).await;

    let worker = FakeWorker::start().await;
    let urls = vec![worker.url.clone()];
    let registry = Arc::new(WorkerRegistry::new(&urls, fast_registry_config()));
    let probe = CancellationToken::new();
    Arc::clone(&registry).start_probing(probe.clone());
    let dispatcher = Arc::new(Dispatcher::new(Arc::clone(&registry)));
    let transport = Arc::new(HttpTransport::new(
        Duration::from_secs(5),
        0,
        None,
        &urls,
        1,
    ));
    let mut manager = Manager::builder("e2e-fenced")
        .with_trap_signals(false)
        .build();
    let handle = manager.register("consumer", ComponentOptions::new());
    let group = format!("e2e-{}", Uuid::new_v4());
    let consumer = IngestionConsumer::from_parts(
        make_kafka_consumer(&topic, &group, Some("pod-1")),
        dispatcher,
        transport,
        urls,
        IngestionConsumerOptions {
            batch_size: 50,
            batch_timeout: Duration::from_millis(100),
            max_in_flight_batches: 1,
            group_id: "e2e-test".to_string(),
            deferred_flush_timeout: Duration::from_secs(60),
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
        let _ = tokio::time::timeout(Duration::from_secs(30), stream.next()).await;
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

// ── max_in_flight > 1 churn / invariant suite ────────────────────────────────
//
// At max_in_flight > 1 the consumer processes batches concurrently, so exact
// scenarios can't be scripted deterministically. These tests instead run a high
// volume across many distinct_ids while aggressively churning the worker pool,
// and assert the correctness INVARIANTS on the cross-worker delivery log:
//   - exactly-once: every produced (distinct_id, seq) is delivered once — no
//     loss, no duplication;
//   - ordering: under graceful drain, each distinct_id's messages are delivered
//     in Kafka order despite rerouting (a regression of the deferred-replay
//     ordering shows up here as an out-of-order seq).
//
// Drain churn (the graceful-drain feature) preserves order, so it is asserted
// strictly. Send-failure churn falls back to at-least-once replay, which can
// interleave a failed-then-replayed message with a later same-key success on a
// flapping worker; those variants assert exactly-once but not strict order.

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

/// Continuously churn the worker pool until cancelled, affecting one worker at a
/// time so the pool always keeps a healthy majority (progress is always
/// possible). Drain = leave/rejoin the pool (EndpointSlice-style); Fail = stay
/// ready but error sends (a crash mid-send). Restores all workers on exit.
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

    // Once everything is delivered and churn has quiesced, the dispatcher's
    // bookkeeping must drain back to zero. A leak in any of these permanently
    // skews routing (stale pins / phantom load) or strands messages (stash).
    wait_until(
        Duration::from_secs(10),
        "dispatcher pins/in-flight/stash to drain to zero after churn",
        || {
            harness.dispatcher.stashed_messages() == 0
                && harness.dispatcher.pin_count() == 0
                && harness.dispatcher.total_in_flight() == 0
        },
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

/// A flapping worker — ready (in the pool) but failing every send — must not pin
/// a batch's offsets forever. The flush loop enforces its deadline on the
/// re-defer path too, so the consumer fails the batch within the configured
/// flush timeout instead of spinning. Runs at max_in_flight > 1.
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

    // `target` flaps: stays ready (in the pool) but fails every send. `other` is
    // taken out of the pool so the flush can't escape — the flush loop keeps
    // re-routing to the flapping target and re-deferring on the scatter path.
    harness.workers[target]
        .ingest_ok
        .store(false, Ordering::SeqCst);
    harness.workers[other]
        .healthy
        .store(false, Ordering::SeqCst);
    guards[other] = None;
    guards[target] = None;

    // The consumer must fail the batch within ~the flush timeout, not spin
    // forever on the re-defer path.
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
