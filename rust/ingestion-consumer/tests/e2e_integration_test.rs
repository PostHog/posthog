//! End-to-end integration tests for the ingestion consumer pipeline.
//!
//! Requires Kafka on localhost:9092 (available via docker-compose).
//! Each test creates a uniquely-named topic to avoid cross-test interference.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
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

use ingestion_consumer::consumer::{IngestionConsumer, IngestionConsumerOptions};
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
                    let arrived = Arc::clone(&arrived);
                    let gate = Arc::clone(&gate);
                    let delivery_log = delivery_log.clone();
                    move |AxumJson(req): AxumJson<IngestBatchRequest>| {
                        let recv = recv.clone();
                        let h = h.clone();
                        let ingest_ok = ingest_ok.clone();
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
            ingest_ok,
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
        }
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

    // A draining worker is alive, not failed: its /_ready still returns 200, and
    // the probe skips draining workers — it must never be declared dead.
    tokio::time::sleep(Duration::from_millis(400)).await;
    assert!(
        !harness.registry.is_dead(&drain_url),
        "a draining (but alive) worker must not be probed to death"
    );

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
