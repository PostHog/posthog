use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::extract::Json;
use axum::response::IntoResponse;
use axum::routing::post;
use axum::Router;
use tokio::net::TcpListener;
use tokio::time::sleep;

use ingestion_consumer::dispatcher::Dispatcher;
use ingestion_consumer::transport::{HttpTransport, TransportError};
use ingestion_consumer::types::{IngestBatchRequest, IngestBatchResponse, SerializedKafkaMessage};
use ingestion_consumer::worker_registry::{WorkerRegistry, WorkerRegistryConfig};

fn make_message(
    token: &str,
    distinct_id: &str,
    offset: i64,
    value: &str,
) -> SerializedKafkaMessage {
    let mut headers = HashMap::new();
    headers.insert("token".to_string(), token.to_string());
    headers.insert("distinct_id".to_string(), distinct_id.to_string());
    SerializedKafkaMessage {
        topic: "events_plugin_ingestion".to_string(),
        partition: 0,
        offset,
        timestamp: 1700000000000,
        key: Some(format!("{token}:{distinct_id}")),
        value: Some(value.to_string()),
        headers,
    }
}

/// Spin up a mock worker that records received batches and returns OK.
async fn start_mock_worker(
    received: Arc<Mutex<Vec<IngestBatchRequest>>>,
) -> (String, tokio::task::JoinHandle<()>) {
    let app = Router::new().route(
        "/ingest",
        post({
            let received = received.clone();
            move |Json(req): Json<IngestBatchRequest>| {
                let received = received.clone();
                async move {
                    let accepted = req.messages.len() as u32;
                    received.lock().unwrap().push(req);
                    Json(IngestBatchResponse {
                        batch_id: "test".to_string(),
                        status: "ok".to_string(),
                        accepted,
                        error: None,
                    })
                }
            }
        }),
    );

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let url = format!("http://127.0.0.1:{}", addr.port());

    let handle = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    (url, handle)
}

/// Spin up a mock worker that returns errors.
async fn start_failing_worker() -> (String, tokio::task::JoinHandle<()>) {
    let app = Router::new().route(
        "/ingest",
        post(|| async {
            (
                axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                "internal error",
            )
        }),
    );

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let url = format!("http://127.0.0.1:{}", addr.port());

    let handle = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    (url, handle)
}

/// Spin up a mock worker that always returns 503 (worker-busy contract violation).
async fn start_always_busy_worker() -> (String, tokio::task::JoinHandle<()>) {
    let app = Router::new().route(
        "/ingest",
        post(|Json(req): Json<IngestBatchRequest>| async move {
            (
                axum::http::StatusCode::SERVICE_UNAVAILABLE,
                axum::Json(IngestBatchResponse {
                    batch_id: req.batch_id,
                    status: "error".to_string(),
                    accepted: 0,
                    error: Some("at concurrent batch capacity (1)".to_string()),
                }),
            )
                .into_response()
        }),
    );

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let url = format!("http://127.0.0.1:{}", addr.port());

    let handle = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    (url, handle)
}

/// Spin up a mock worker that returns 503 for its first `busy_times` requests,
/// then 200 OK thereafter — simulating a worker that is momentarily at capacity.
async fn start_busy_then_ok_worker(busy_times: usize) -> (String, tokio::task::JoinHandle<()>) {
    let calls = Arc::new(AtomicUsize::new(0));
    let app = Router::new().route(
        "/ingest",
        post(move |Json(req): Json<IngestBatchRequest>| {
            let calls = calls.clone();
            async move {
                let n = calls.fetch_add(1, Ordering::SeqCst);
                if n < busy_times {
                    return (
                        axum::http::StatusCode::SERVICE_UNAVAILABLE,
                        axum::Json(IngestBatchResponse {
                            batch_id: req.batch_id,
                            status: "error".to_string(),
                            accepted: 0,
                            error: Some("at concurrent batch capacity (1)".to_string()),
                        }),
                    )
                        .into_response();
                }
                axum::Json(IngestBatchResponse {
                    batch_id: req.batch_id,
                    status: "ok".to_string(),
                    accepted: req.messages.len() as u32,
                    error: None,
                })
                .into_response()
            }
        }),
    );

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let url = format!("http://127.0.0.1:{}", addr.port());

    let handle = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    (url, handle)
}

/// Spin up a mock worker that sleeps `delay` before responding ok. Records
/// the max number of overlapping in-flight requests it ever observed.
async fn start_slow_worker(
    delay: Duration,
    max_concurrent: Arc<AtomicUsize>,
) -> (String, tokio::task::JoinHandle<()>) {
    let in_flight = Arc::new(AtomicUsize::new(0));
    let app = Router::new().route(
        "/ingest",
        post({
            let in_flight = in_flight.clone();
            let max_concurrent = max_concurrent.clone();
            move |Json(req): Json<IngestBatchRequest>| {
                let in_flight = in_flight.clone();
                let max_concurrent = max_concurrent.clone();
                async move {
                    let now = in_flight.fetch_add(1, Ordering::SeqCst) + 1;
                    max_concurrent.fetch_max(now, Ordering::SeqCst);
                    sleep(delay).await;
                    in_flight.fetch_sub(1, Ordering::SeqCst);
                    Json(IngestBatchResponse {
                        batch_id: req.batch_id,
                        status: "ok".to_string(),
                        accepted: req.messages.len() as u32,
                        error: None,
                    })
                }
            }
        }),
    );

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let url = format!("http://127.0.0.1:{}", addr.port());

    let handle = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    (url, handle)
}

#[tokio::test]
async fn transport_sends_batch_and_receives_ack() {
    let received = Arc::new(Mutex::new(Vec::new()));
    let (url, _handle) = start_mock_worker(received.clone()).await;

    let urls = vec![url.clone()];
    let transport = HttpTransport::new(Duration::from_secs(5), 0, None, &urls, 1);

    let messages = vec![
        make_message("tok1", "user-a", 0, r#"{"event":"$pageview"}"#),
        make_message("tok1", "user-a", 1, r#"{"event":"$identify"}"#),
    ];

    let accepted = transport
        .send_batch(&url, "batch-1", messages)
        .await
        .unwrap();

    assert_eq!(accepted, 2);

    let batches = received.lock().unwrap();
    assert_eq!(batches.len(), 1);
    assert_eq!(batches[0].messages.len(), 2);
    assert_eq!(batches[0].messages[0].offset, 0);
    assert_eq!(batches[0].messages[1].offset, 1);

    // Verify headers survived the round-trip
    assert_eq!(batches[0].messages[0].headers.get("token").unwrap(), "tok1");
    assert_eq!(
        batches[0].messages[0].headers.get("distinct_id").unwrap(),
        "user-a"
    );
}

#[tokio::test]
async fn transport_retries_on_server_error() {
    let (url, _handle) = start_failing_worker().await;

    let urls = vec![url.clone()];
    let transport = HttpTransport::new(Duration::from_secs(1), 2, None, &urls, 1);

    let messages = vec![make_message("tok", "user", 0, "{}")];

    let result = transport.send_batch(&url, "batch-retry", messages).await;
    assert!(result.is_err());
}

#[tokio::test]
async fn transport_retries_on_worker_busy() {
    // 503 is transient backpressure (a shared worker can be momentarily full),
    // so the transport retries with the longer, jittered busy backoff rather
    // than failing fast. An always-busy worker exhausts retries and returns the
    // last WorkerBusy error — but only after backing off at least once.
    let (url, _handle) = start_always_busy_worker().await;

    let urls = vec![url.clone()];
    let transport = HttpTransport::new(Duration::from_secs(5), 1, None, &urls, 1);

    let messages = vec![make_message("tok", "user", 0, "{}")];

    let start = std::time::Instant::now();
    let err = transport
        .send_batch(&url, "batch-busy", messages)
        .await
        .unwrap_err();
    let elapsed = start.elapsed();

    assert!(
        matches!(err.error, TransportError::WorkerBusy(_)),
        "expected WorkerBusy, got {err:?}"
    );
    // One retry means one busy backoff (base 250ms + jitter), so the call must
    // take noticeably longer than the old fail-fast path (<200ms).
    assert!(
        elapsed >= Duration::from_millis(240),
        "expected a busy backoff before exhausting (≥240ms), got {elapsed:?}"
    );
}

#[tokio::test]
async fn transport_recovers_after_worker_busy() {
    // A worker that is busy once and then ready should succeed after a retry.
    let (url, _handle) = start_busy_then_ok_worker(1).await;

    let urls = vec![url.clone()];
    let transport = HttpTransport::new(Duration::from_secs(5), 3, None, &urls, 1);

    let messages = vec![make_message("tok", "user", 0, "{}")];

    let accepted = transport
        .send_batch(&url, "batch-recover", messages)
        .await
        .expect("should succeed after the worker stops being busy");
    assert_eq!(accepted, 1);
}

#[tokio::test]
async fn transport_fails_on_unreachable_worker() {
    let url = "http://127.0.0.1:1".to_string();
    let urls = vec![url.clone()];
    let transport = HttpTransport::new(Duration::from_secs(1), 0, None, &urls, 1);
    let messages = vec![make_message("tok", "user", 0, "{}")];

    let result = transport.send_batch(&url, "batch-fail", messages).await;
    assert!(result.is_err());
}

#[tokio::test]
async fn transport_lazily_creates_semaphore_for_unseeded_worker() {
    // Dynamic membership: a worker not seeded at construction (discovered at
    // runtime) gets a semaphore created on first send and is served normally.
    let received = Arc::new(Mutex::new(Vec::new()));
    let (url, _handle) = start_mock_worker(received.clone()).await;

    // Construct with an empty worker set — the target is "unknown" at build time.
    let transport = HttpTransport::new(Duration::from_secs(5), 0, None, &[], 1);

    let messages = vec![make_message("tok", "user", 0, "{}")];
    let accepted = transport
        .send_batch(&url, "batch-lazy", messages)
        .await
        .expect("send to an unseeded worker should succeed via lazy semaphore creation");

    assert_eq!(accepted, 1);
}

#[tokio::test]
async fn transport_serializes_concurrent_sends_to_same_worker() {
    // With concurrency=1 and a 500ms-slow worker, two parallel send_batch
    // calls must serialize: total elapsed ≈ 1s (not 500ms), and the worker
    // never sees more than 1 concurrent request.
    let max_concurrent = Arc::new(AtomicUsize::new(0));
    let (url, _h) = start_slow_worker(Duration::from_millis(500), max_concurrent.clone()).await;

    let urls = vec![url.clone()];
    let transport = Arc::new(HttpTransport::new(
        Duration::from_secs(5),
        0,
        None,
        &urls,
        1,
    ));

    let start = std::time::Instant::now();
    let mut handles = Vec::new();
    for i in 0..2 {
        let t = transport.clone();
        let u = url.clone();
        handles.push(tokio::spawn(async move {
            t.send_batch(
                &u,
                &format!("batch-{i}"),
                vec![make_message("tok", "u", 0, "{}")],
            )
            .await
            .unwrap()
        }));
    }
    for h in handles {
        h.await.unwrap();
    }
    let elapsed = start.elapsed();

    assert_eq!(
        max_concurrent.load(Ordering::SeqCst),
        1,
        "semaphore must serialize calls to the same worker"
    );
    assert!(
        elapsed >= Duration::from_millis(900),
        "expected ≥900ms for serialized 500ms calls, got {elapsed:?}"
    );
}

#[tokio::test]
async fn transport_parallelizes_across_different_workers() {
    // Semaphores are per-URL: two different workers must run in parallel.
    let max_a = Arc::new(AtomicUsize::new(0));
    let max_b = Arc::new(AtomicUsize::new(0));
    let (url_a, _h_a) = start_slow_worker(Duration::from_millis(500), max_a.clone()).await;
    let (url_b, _h_b) = start_slow_worker(Duration::from_millis(500), max_b.clone()).await;

    let urls = vec![url_a.clone(), url_b.clone()];
    let transport = Arc::new(HttpTransport::new(
        Duration::from_secs(5),
        0,
        None,
        &urls,
        1,
    ));

    let start = std::time::Instant::now();
    let t1 = {
        let t = transport.clone();
        let u = url_a.clone();
        tokio::spawn(async move {
            t.send_batch(&u, "batch-a", vec![make_message("tok", "u", 0, "{}")])
                .await
                .unwrap()
        })
    };
    let t2 = {
        let t = transport.clone();
        let u = url_b.clone();
        tokio::spawn(async move {
            t.send_batch(&u, "batch-b", vec![make_message("tok", "u", 0, "{}")])
                .await
                .unwrap()
        })
    };
    t1.await.unwrap();
    t2.await.unwrap();
    let elapsed = start.elapsed();

    // ≈ 500ms (parallel), well under 1s (which would mean serialized).
    assert!(
        elapsed < Duration::from_millis(900),
        "expected ≈500ms for parallel workers, got {elapsed:?}"
    );
}

#[tokio::test]
async fn dispatcher_and_transport_end_to_end() {
    // Start 2 mock workers
    let received_1 = Arc::new(Mutex::new(Vec::new()));
    let received_2 = Arc::new(Mutex::new(Vec::new()));
    let (url_1, _h1) = start_mock_worker(received_1.clone()).await;
    let (url_2, _h2) = start_mock_worker(received_2.clone()).await;

    let worker_urls = [url_1.clone(), url_2.clone()];
    let registry = Arc::new(WorkerRegistry::new(
        &worker_urls,
        WorkerRegistryConfig {
            probe_interval: Duration::from_secs(60),
            dead_declaration: Duration::from_secs(60),
            passive_window: Duration::from_secs(30),
            passive_error_threshold: 0.5,
            passive_min_samples: 1000,
            degraded_hold: Duration::from_secs(10),
            min_state_duration: Duration::ZERO,
            probe_failure_threshold: 2,
            drain_timeout: Duration::from_secs(5),
        },
    ));
    let dispatcher = Arc::new(Dispatcher::new(Arc::clone(&registry)));
    let transport = Arc::new(HttpTransport::new(
        Duration::from_secs(5),
        0,
        None,
        &worker_urls,
        1,
    ));

    // Create messages for multiple distinct_ids — user-1 appears twice
    let messages = vec![
        make_message("tok", "user-1", 0, r#"{"event":"a"}"#),
        make_message("tok", "user-2", 1, r#"{"event":"b"}"#),
        make_message("tok", "user-1", 2, r#"{"event":"c"}"#),
        make_message("tok", "user-3", 3, r#"{"event":"d"}"#),
    ];

    let sub_batches = dispatcher.assign("b", messages);

    // Scatter to workers
    let mut handles = Vec::new();
    for sub_batch in sub_batches {
        let t = transport.clone();
        let worker = sub_batch.worker.clone();
        let routing_keys = sub_batch.routing_keys.clone();
        let message_count = sub_batch.messages.len();
        let d = Arc::clone(&dispatcher);
        handles.push(tokio::spawn(async move {
            let result = t
                .send_batch(&worker, "batch-e2e", sub_batch.messages)
                .await
                .unwrap();
            d.on_sub_batch_resolved(&worker, message_count, &routing_keys, false);
            result
        }));
    }

    // Gather
    let mut total_accepted = 0u32;
    for h in handles {
        total_accepted += h.await.unwrap();
    }
    assert_eq!(total_accepted, 4);

    // user-1 messages (offsets 0 and 2) must have landed on the same worker
    let batches_1 = received_1.lock().unwrap();
    let batches_2 = received_2.lock().unwrap();

    let all_messages: Vec<&SerializedKafkaMessage> = batches_1
        .iter()
        .chain(batches_2.iter())
        .flat_map(|b| &b.messages)
        .collect();
    assert_eq!(all_messages.len(), 4);

    let user1_workers: Vec<usize> = all_messages
        .iter()
        .filter(|m| m.headers.get("distinct_id").map(|s| s.as_str()) == Some("user-1"))
        .map(|m| {
            if batches_1
                .iter()
                .any(|b| b.messages.iter().any(|bm| bm.offset == m.offset))
            {
                0
            } else {
                1
            }
        })
        .collect();
    assert!(
        user1_workers.iter().all(|&w| w == user1_workers[0]),
        "user-1 messages should all be on the same worker"
    );
}

#[tokio::test]
async fn wire_format_preserves_unicode_and_null_fields() {
    let received = Arc::new(Mutex::new(Vec::new()));
    let (url, _handle) = start_mock_worker(received.clone()).await;

    let urls = vec![url.clone()];
    let transport = HttpTransport::new(Duration::from_secs(5), 0, None, &urls, 1);

    let messages = vec![SerializedKafkaMessage {
        topic: "test".to_string(),
        partition: 0,
        offset: 42,
        timestamp: 0,
        key: None,
        value: Some(r#"{"name":"José 日本語 🎉"}"#.to_string()),
        headers: HashMap::new(),
    }];

    transport
        .send_batch(&url, "batch-unicode", messages)
        .await
        .unwrap();

    let batches = received.lock().unwrap();
    let msg = &batches[0].messages[0];
    assert!(msg.key.is_none());
    assert_eq!(msg.value.as_deref(), Some(r#"{"name":"José 日本語 🎉"}"#));
    assert!(msg.headers.is_empty());
}
