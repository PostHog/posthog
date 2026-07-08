use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use axum::extract::{Json, State};
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::Router;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;

use ingestion_consumer::dispatcher::Dispatcher;
use ingestion_consumer::types::{IngestBatchRequest, IngestBatchResponse, SerializedKafkaMessage};
use ingestion_consumer::worker_registry::{WorkerRegistry, WorkerRegistryConfig, WorkerState};

// ---- FakeWorker ----

#[derive(Clone)]
struct WorkerCtrl {
    is_healthy: Arc<AtomicBool>,
}

async fn ready_handler(State(ctrl): State<WorkerCtrl>) -> impl IntoResponse {
    if ctrl.is_healthy.load(Ordering::Relaxed) {
        axum::http::StatusCode::OK
    } else {
        axum::http::StatusCode::SERVICE_UNAVAILABLE
    }
}

async fn ingest_handler(
    State(_ctrl): State<WorkerCtrl>,
    Json(req): Json<IngestBatchRequest>,
) -> Json<IngestBatchResponse> {
    let accepted = req.messages.len() as u32;
    Json(IngestBatchResponse {
        batch_id: req.batch_id,
        status: "ok".to_string(),
        accepted,
        error: None,
    })
}

struct FakeWorker {
    pub url: String,
    is_healthy: Arc<AtomicBool>,
    handle: tokio::task::JoinHandle<()>,
}

impl FakeWorker {
    async fn start() -> Self {
        let is_healthy = Arc::new(AtomicBool::new(true));
        let ctrl = WorkerCtrl {
            is_healthy: Arc::clone(&is_healthy),
        };

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();

        let app = Router::new()
            .route("/_ready", get(ready_handler))
            .route("/ingest", post(ingest_handler))
            .with_state(ctrl);

        let handle = tokio::spawn(async move {
            axum::serve(listener, app)
                .await
                .expect("fake worker server error");
        });

        Self {
            url: format!("http://{addr}"),
            is_healthy,
            handle,
        }
    }

    fn set_healthy(&self, healthy: bool) {
        self.is_healthy.store(healthy, Ordering::Relaxed);
    }
}

impl Drop for FakeWorker {
    fn drop(&mut self) {
        self.handle.abort();
    }
}

// ---- helpers ----

fn fast_config() -> WorkerRegistryConfig {
    WorkerRegistryConfig {
        probe_interval: Duration::from_millis(15),
        dead_declaration: Duration::from_millis(40),
        passive_window: Duration::from_secs(60),
        passive_error_threshold: 0.01,
        passive_min_samples: 1000,
        degraded_hold: Duration::from_millis(30),
        min_state_duration: Duration::ZERO,
        probe_failure_threshold: 2,
        drain_timeout: Duration::from_secs(5),
    }
}

fn make_msg(token: &str, distinct_id: &str) -> SerializedKafkaMessage {
    let mut headers = HashMap::new();
    headers.insert("token".to_string(), token.to_string());
    headers.insert("distinct_id".to_string(), distinct_id.to_string());
    SerializedKafkaMessage {
        topic: "test".to_string(),
        partition: 0,
        offset: 0,
        timestamp: 0,
        key: None,
        value: None,
        headers,
    }
}

async fn wait_for_state(registry: &WorkerRegistry, worker: &str, expected: WorkerState) {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(3);
    loop {
        if registry.state(worker) == expected {
            return;
        }
        assert!(
            tokio::time::Instant::now() < deadline,
            "timed out waiting for worker {worker} to become {expected:?}"
        );
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
}

async fn wait_for_dead(registry: &WorkerRegistry, worker: &str) {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(3);
    loop {
        if registry.is_dead(worker) {
            return;
        }
        assert!(
            tokio::time::Instant::now() < deadline,
            "timed out waiting for worker {worker} to be declared dead"
        );
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
}

async fn wait_for_not_unhealthy(registry: &WorkerRegistry, worker: &str) {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(3);
    loop {
        if registry.state(worker) != WorkerState::Unhealthy {
            return;
        }
        assert!(
            tokio::time::Instant::now() < deadline,
            "timed out waiting for worker {worker} to leave Unhealthy"
        );
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
}

// ---- tests ----

/// Fresh keys must not be assigned to an Unhealthy worker, even though the
/// worker's server is still up (just returning 503 on /_ready).
#[tokio::test]
async fn test_new_keys_skip_unhealthy_worker() {
    let w0 = FakeWorker::start().await;
    let w1 = FakeWorker::start().await;

    let urls = vec![w0.url.clone(), w1.url.clone()];
    let registry = Arc::new(WorkerRegistry::new(&urls, fast_config()));
    let dispatcher = Dispatcher::new(Arc::clone(&registry));

    let token = CancellationToken::new();
    Arc::clone(&registry).start_probing(token.clone());

    w1.set_healthy(false);
    wait_for_state(&registry, &w1.url, WorkerState::Unhealthy).await;

    let keys: Vec<_> = (0..10)
        .map(|i| make_msg("t", &format!("user-{i}")))
        .collect();
    let sub_batches = dispatcher.assign("b", keys);

    assert!(
        sub_batches.iter().all(|b| b.worker.as_ref() == w0.url),
        "all assignments should go to w0; workers used: {:?}",
        sub_batches
            .iter()
            .map(|b| b.worker.to_string())
            .collect::<Vec<_>>()
    );

    token.cancel();
}

/// A key pinned to a worker while it was healthy must be re-routed to a
/// healthy worker after the original worker is declared dead.
#[tokio::test]
async fn test_pinned_key_rerouted_after_dead_declaration() {
    let w0 = FakeWorker::start().await;
    let w1 = FakeWorker::start().await;

    let urls = vec![w0.url.clone(), w1.url.clone()];
    let registry = Arc::new(WorkerRegistry::new(&urls, fast_config()));
    let dispatcher = Dispatcher::new(Arc::clone(&registry));

    let token = CancellationToken::new();
    Arc::clone(&registry).start_probing(token.clone());

    // Pin "t:user-1" to whichever worker gets it first. Hold the sub-batch
    // open (don't call on_sub_batch_resolved) so the pin stays alive.
    let b1 = dispatcher.assign("b", vec![make_msg("t", "user-1")]);
    assert_eq!(b1.len(), 1);
    let pinned_to = b1[0].worker.clone();
    let other = if pinned_to.as_ref() == w0.url {
        w1.url.clone()
    } else {
        w0.url.clone()
    };

    // Kill the pinned worker's health endpoint.
    if pinned_to.as_ref() == w0.url {
        w0.set_healthy(false);
    } else {
        w1.set_healthy(false);
    }

    // Wait for Unhealthy then dead declaration.
    wait_for_state(&registry, &pinned_to, WorkerState::Unhealthy).await;
    wait_for_dead(&registry, &pinned_to).await;

    // Resolve b1: with max_in_flight=1 the previous batch completes before the
    // next assigns, so the dead worker has no in-flight and its zero-ref pin is
    // evicted (an unresolved pin would instead defer to preserve order).
    dispatcher.on_sub_batch_resolved(&pinned_to, b1[0].messages.len(), &b1[0].routing_keys, false);

    // Next assign: the evicted pin means the key re-routes to the live worker.
    let b2 = dispatcher.assign("b", vec![make_msg("t", "user-1")]);
    assert_eq!(b2.len(), 1, "expected exactly one sub-batch");
    assert_eq!(
        b2[0].worker.as_ref(),
        other,
        "user-1 should reroute to the live worker after {pinned_to} is dead"
    );

    token.cancel();
}

/// When a dead worker's health endpoint starts returning 200 again, the probe
/// should drive it through Degraded and eventually back to Healthy, at which
/// point the dispatcher routes new keys to it again.
#[tokio::test]
async fn test_worker_recovery_detected_by_probe() {
    let w0 = FakeWorker::start().await;
    let w1 = FakeWorker::start().await;

    // w1 starts unhealthy so the probe detects it failing from the beginning.
    w1.set_healthy(false);

    let urls = vec![w0.url.clone(), w1.url.clone()];
    let registry = Arc::new(WorkerRegistry::new(&urls, fast_config()));
    let dispatcher = Dispatcher::new(Arc::clone(&registry));

    let token = CancellationToken::new();
    Arc::clone(&registry).start_probing(token.clone());

    wait_for_state(&registry, &w1.url, WorkerState::Unhealthy).await;

    // Recover w1.
    w1.set_healthy(true);

    // Wait until w1 leaves Unhealthy (Degraded or Healthy).
    wait_for_not_unhealthy(&registry, &w1.url).await;

    // Assign a large set of fresh keys. Both workers should get some, since w1
    // is now at least Degraded (Healthy | Degraded both receive assignments).
    let keys: Vec<_> = (0..40)
        .map(|i| make_msg("t", &format!("user-{i}")))
        .collect();
    let sub_batches = dispatcher.assign("b", keys);

    let workers_used: std::collections::HashSet<String> =
        sub_batches.iter().map(|b| b.worker.to_string()).collect();
    assert!(
        workers_used.contains(&w1.url),
        "w1 should receive new keys after recovery; workers used: {workers_used:?}"
    );

    token.cancel();
}

/// With 3 workers, one dying mid-flight:
/// - Keys pinned to the dead worker are evicted and re-routed to the survivors.
/// - Keys pinned to the two live workers are unaffected.
/// - No new keys reach the dead worker.
#[tokio::test]
async fn test_three_workers_one_dies_and_load_rebalances() {
    let w0 = FakeWorker::start().await;
    let w1 = FakeWorker::start().await;
    let w2 = FakeWorker::start().await;

    let urls = vec![w0.url.clone(), w1.url.clone(), w2.url.clone()];
    let registry = Arc::new(WorkerRegistry::new(&urls, fast_config()));
    let dispatcher = Dispatcher::new(Arc::clone(&registry));

    let token = CancellationToken::new();
    Arc::clone(&registry).start_probing(token.clone());

    // 3 distinct keys of equal size: bin-packing spreads exactly one key per
    // worker (provisional load increases by 1 for each pick, breaking all ties).
    let first = dispatcher.assign(
        "b",
        vec![
            make_msg("t", "key-a"),
            make_msg("t", "key-b"),
            make_msg("t", "key-c"),
        ],
    );
    assert_eq!(
        first.len(),
        3,
        "3 keys across 3 workers must yield 3 sub-batches"
    );
    let workers_covered: std::collections::HashSet<String> =
        first.iter().map(|b| b.worker.to_string()).collect();
    assert_eq!(workers_covered.len(), 3, "all 3 workers must receive a pin");

    // Remember which routing key was pinned to w1 — we'll re-assign it later
    // to verify it migrates to a live worker.
    let w1_key = first
        .iter()
        .find(|b| b.worker.as_ref() == w1.url)
        .unwrap()
        .routing_keys[0]
        .clone();

    // Kill w1 and wait for dead declaration (first batch stays open throughout).
    w1.set_healthy(false);
    wait_for_state(&registry, &w1.url, WorkerState::Unhealthy).await;
    wait_for_dead(&registry, &w1.url).await;

    // Fresh keys must only land on w0 or w2.
    let fresh = dispatcher.assign(
        "b",
        vec![
            make_msg("t", "new-1"),
            make_msg("t", "new-2"),
            make_msg("t", "new-3"),
        ],
    );
    assert!(
        fresh.iter().all(|b| b.worker.as_ref() != w1.url),
        "fresh keys must not route to dead w1; workers used: {:?}",
        fresh
            .iter()
            .map(|b| b.worker.to_string())
            .collect::<Vec<_>>()
    );

    // Resolve w1's in-flight sub-batch (max_in_flight=1: the prior batch
    // completes before the next assigns), evicting its now zero-ref pin.
    let w1_sub = first.iter().find(|b| b.worker.as_ref() == w1.url).unwrap();
    dispatcher.on_sub_batch_resolved(
        &w1_sub.worker,
        w1_sub.messages.len(),
        &w1_sub.routing_keys,
        false,
    );

    // The key that was pinned to w1 must re-route to w0 or w2 on its next assign.
    let (_, distinct_id) = w1_key.split_once(':').unwrap();
    let rerouted = dispatcher.assign("b", vec![make_msg("t", distinct_id)]);
    assert_eq!(
        rerouted.len(),
        1,
        "rerouted key must produce exactly one sub-batch"
    );
    assert_ne!(
        rerouted[0].worker.as_ref(),
        w1.url,
        "key previously pinned to w1 must reroute to a live worker, not w1"
    );

    token.cancel();
}

/// When every worker is Unhealthy, assign must return an empty vec — no
/// messages can be routed and nothing must be dropped silently.
#[tokio::test]
async fn test_all_workers_unhealthy_returns_empty() {
    let w0 = FakeWorker::start().await;
    let w1 = FakeWorker::start().await;

    w0.set_healthy(false);
    w1.set_healthy(false);

    let urls = vec![w0.url.clone(), w1.url.clone()];
    let registry = Arc::new(WorkerRegistry::new(&urls, fast_config()));
    let dispatcher = Dispatcher::new(Arc::clone(&registry));

    let token = CancellationToken::new();
    Arc::clone(&registry).start_probing(token.clone());

    wait_for_state(&registry, &w0.url, WorkerState::Unhealthy).await;
    wait_for_state(&registry, &w1.url, WorkerState::Unhealthy).await;

    let sub_batches = dispatcher.assign("b", vec![make_msg("t", "user-1")]);
    assert!(
        sub_batches.is_empty(),
        "expected empty assignment when all workers are unhealthy"
    );

    token.cancel();
}

/// Graceful drain end-to-end at the dispatcher level: a draining worker keeps
/// its in-flight pin (new messages defer rather than reroute or pile onto it),
/// the liveness probe does not evict it while draining, and once its in-flight
/// resolves it becomes reapable and the deferred key reroutes to a survivor.
#[tokio::test]
async fn test_draining_worker_defers_then_flushes_to_survivor() {
    let w0 = FakeWorker::start().await;
    let w1 = FakeWorker::start().await;

    let urls = vec![w0.url.clone(), w1.url.clone()];
    let registry = Arc::new(WorkerRegistry::new(&urls, fast_config()));
    let dispatcher = Dispatcher::new(Arc::clone(&registry));

    let token = CancellationToken::new();
    Arc::clone(&registry).start_probing(token.clone());

    // Pin user-1 to whichever worker gets it; hold the sub-batch open.
    let b1 = dispatcher.assign("batch-1", vec![make_msg("t", "user-1")]);
    let pinned = b1[0].worker.clone();
    let other = if pinned.as_ref() == w0.url {
        w1.url.clone()
    } else {
        w0.url.clone()
    };

    // Begin draining (as an EndpointSlice removal would).
    registry.start_draining(&pinned);

    // New messages for user-1 defer — not sent to the drainer, not yet rerouted.
    let b2 = dispatcher.assign("batch-2", vec![make_msg("t", "user-1")]);
    assert!(
        b2.is_empty(),
        "must defer while the pinned worker is draining"
    );
    assert!(dispatcher.has_deferred("batch-2"));

    // The drainer is still alive and healthy — the probe must not evict it while
    // it finishes in-flight work (its /_ready still returns 200 here).
    tokio::time::sleep(Duration::from_millis(120)).await;
    assert!(
        !registry.is_dead(&pinned),
        "drainer must not be probed to death"
    );
    assert!(
        registry.reapable_workers().is_empty(),
        "not reapable while in-flight remains"
    );

    // Resolve batch-1: the drainer finishes and becomes reapable.
    dispatcher.on_sub_batch_resolved(&pinned, b1[0].messages.len(), &b1[0].routing_keys, false);
    assert_eq!(registry.reapable_workers(), vec![pinned.clone()]);

    // Flushing batch-2 reroutes the deferred key onto the surviving worker.
    let flushed = dispatcher.flush_deferred("batch-2");
    assert_eq!(flushed.len(), 1);
    assert_eq!(flushed[0].worker.as_ref(), other);
    assert!(!dispatcher.has_deferred("batch-2"));

    token.cancel();
}
