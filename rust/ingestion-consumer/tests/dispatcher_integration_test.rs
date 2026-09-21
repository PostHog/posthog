use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use common_kafka_consumer::Partition;

use axum::extract::State;
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;

use ingestion_consumer::batcher::Batcher;
use ingestion_consumer::dispatcher::Dispatcher;
use ingestion_consumer::grpc_transport::{GrpcPort, GrpcTransport};
use ingestion_consumer::types::{Accumulator, SerializedKafkaMessage};
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

fn make_msg(key: &str) -> SerializedKafkaMessage {
    SerializedKafkaMessage {
        topic: "test".to_string(),
        partition: 0,
        offset: 0,
        timestamp: 0,
        key: Some(key.to_string()),
        value: None,
        headers: HashMap::new(),
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

    let keys: Vec<_> = (0..10).map(|i| make_msg(&format!("t:user-{i}"))).collect();
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

/// A key served by a worker while it was healthy must be routed to a
/// healthy worker after the original worker is declared dead.
#[tokio::test]
async fn test_key_rerouted_after_dead_declaration() {
    let w0 = FakeWorker::start().await;
    let w1 = FakeWorker::start().await;

    let urls = vec![w0.url.clone(), w1.url.clone()];
    let registry = Arc::new(WorkerRegistry::new(&urls, fast_config()));
    let dispatcher = Dispatcher::new(Arc::clone(&registry));

    let token = CancellationToken::new();
    Arc::clone(&registry).start_probing(token.clone());

    // Route "t:user-1" to whichever worker gets it first. Hold the sub-batch
    // open (don't settle) so the key stays outstanding.
    let b1 = dispatcher.assign("b", vec![make_msg("t:user-1")]);
    assert_eq!(b1.len(), 1);
    let first_worker = b1[0].worker.clone();
    let other = if first_worker.as_ref() == w0.url {
        w1.url.clone()
    } else {
        w0.url.clone()
    };

    // Kill the first worker's health endpoint.
    if first_worker.as_ref() == w0.url {
        w0.set_healthy(false);
    } else {
        w1.set_healthy(false);
    }

    // Wait for Unhealthy then dead declaration.
    wait_for_state(&registry, &first_worker, WorkerState::Unhealthy).await;
    wait_for_dead(&registry, &first_worker).await;

    // Settle b1: with max_in_flight=1 the previous batch completes before the
    // next assigns, so the key is released (an outstanding key would instead
    // queue to preserve order).
    dispatcher.settle(
        &first_worker,
        b1[0].messages.len(),
        &b1[0].routing_keys,
        None,
    );

    // Next assign: the released key re-routes to the live worker.
    let b2 = dispatcher.assign("b", vec![make_msg("t:user-1")]);
    assert_eq!(b2.len(), 1, "expected exactly one sub-batch");
    assert_eq!(
        b2[0].worker.as_ref(),
        other,
        "user-1 should reroute to the live worker after {first_worker} is dead"
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
    let keys: Vec<_> = (0..40).map(|i| make_msg(&format!("t:user-{i}"))).collect();
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
/// - Keys on the dead worker re-route to the survivors once released.
/// - Keys on the two live workers are unaffected.
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
            make_msg("t:key-a"),
            make_msg("t:key-b"),
            make_msg("t:key-c"),
        ],
    );
    assert_eq!(
        first.len(),
        3,
        "3 keys across 3 workers must yield 3 sub-batches"
    );
    let workers_covered: std::collections::HashSet<String> =
        first.iter().map(|b| b.worker.to_string()).collect();
    assert_eq!(workers_covered.len(), 3, "all 3 workers must receive a key");

    // Remember which routing key went to w1 — we'll re-assign it later
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
            make_msg("t:new-1"),
            make_msg("t:new-2"),
            make_msg("t:new-3"),
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

    // Settle w1's in-flight sub-batch (max_in_flight=1: the prior batch
    // completes before the next assigns), releasing its key.
    let w1_sub = first.iter().find(|b| b.worker.as_ref() == w1.url).unwrap();
    dispatcher.settle(
        &w1_sub.worker,
        w1_sub.messages.len(),
        &w1_sub.routing_keys,
        None,
    );

    // The key that went to w1 must re-route to w0 or w2 on its next assign.
    let rerouted = dispatcher.assign("b", vec![make_msg(&w1_key)]);
    assert_eq!(
        rerouted.len(),
        1,
        "rerouted key must produce exactly one sub-batch"
    );
    assert_ne!(
        rerouted[0].worker.as_ref(),
        w1.url,
        "key previously on w1 must reroute to a live worker, not w1"
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

    let sub_batches = dispatcher.assign("b", vec![make_msg("t:user-1")]);
    assert!(
        sub_batches.is_empty(),
        "expected empty assignment when all workers are unhealthy"
    );

    token.cancel();
}

#[tokio::test(flavor = "current_thread")]
async fn purging_a_just_submitted_key_table_batch_is_not_fatal() {
    let registry = Arc::new(WorkerRegistry::new(&[], fast_config()));
    let dispatcher = Arc::new(Dispatcher::new(registry));
    let transport = Arc::new(GrpcTransport::new(
        GrpcPort::OffsetFromHttp(0),
        1,
        Duration::from_secs(30),
    ));
    let (batcher, mut outputs) = Batcher::new(
        Arc::clone(&dispatcher),
        transport,
        Duration::from_secs(10),
        Duration::from_millis(20),
    );

    let mut accumulator = Accumulator::default();
    accumulator.push(Partition(0), make_msg("a").into());
    batcher.submit(accumulator);
    // No await between submit and purge: run_scatter is queued but cannot run
    // until this current-thread task yields. The submission was accepted and
    // retained synchronously, then intentionally discarded by revocation.
    dispatcher.purge_revoked(&[("test".to_string(), 0)]);

    match tokio::time::timeout(Duration::from_millis(100), outputs.errors.recv()).await {
        Err(_) => {}
        Ok(Some(error)) => panic!("revoked work must not report a routing failure: {error}"),
        Ok(None) => panic!("batcher error channel closed unexpectedly"),
    }
}

#[tokio::test]
async fn dropping_an_idle_key_table_batcher_closes_its_outputs() {
    let registry = Arc::new(WorkerRegistry::new(&[], fast_config()));
    let dispatcher = Arc::new(Dispatcher::new(registry));
    let transport = Arc::new(GrpcTransport::new(
        GrpcPort::OffsetFromHttp(0),
        1,
        Duration::from_secs(30),
    ));
    let (batcher, mut outputs) = Batcher::new(
        dispatcher,
        transport,
        Duration::from_secs(10),
        Duration::from_millis(20),
    );

    drop(batcher);

    let completion = tokio::time::timeout(Duration::from_millis(100), outputs.completions.recv())
        .await
        .expect("dropping the batcher must not leave an idle retry task retaining its senders");
    assert!(
        completion.is_none(),
        "an idle dropped batcher cannot produce a completion"
    );
    assert!(
        outputs.errors.recv().await.is_none(),
        "all output senders close with the dropped batcher"
    );
}
