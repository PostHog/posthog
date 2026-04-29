use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::extract::Json;
use axum::routing::post;
use axum::Router;
use tokio::net::TcpListener;

use ingestion_consumer::router::MessageRouter;
use ingestion_consumer::transport::HttpTransport;
use ingestion_consumer::types::{IngestBatchRequest, IngestBatchResponse, SerializedKafkaMessage};

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

#[tokio::test]
async fn transport_sends_batch_and_receives_ack() {
    let received = Arc::new(Mutex::new(Vec::new()));
    let (url, _handle) = start_mock_worker(received.clone()).await;

    let transport = HttpTransport::new(Duration::from_secs(5), 0, None);

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

    let transport = HttpTransport::new(Duration::from_secs(1), 2, None);

    let messages = vec![make_message("tok", "user", 0, "{}")];

    let result = transport.send_batch(&url, "batch-retry", messages).await;
    assert!(result.is_err());
}

#[tokio::test]
async fn transport_fails_on_unreachable_worker() {
    let transport = HttpTransport::new(Duration::from_secs(1), 0, None);
    let messages = vec![make_message("tok", "user", 0, "{}")];

    let result = transport
        .send_batch("http://127.0.0.1:1", "batch-fail", messages)
        .await;
    assert!(result.is_err());
}

#[tokio::test]
async fn router_and_transport_end_to_end() {
    // Start 2 mock workers
    let received_1 = Arc::new(Mutex::new(Vec::new()));
    let received_2 = Arc::new(Mutex::new(Vec::new()));
    let (url_1, _h1) = start_mock_worker(received_1.clone()).await;
    let (url_2, _h2) = start_mock_worker(received_2.clone()).await;

    let worker_urls = [url_1.clone(), url_2.clone()];
    let router = MessageRouter::new(worker_urls.len());
    let transport = Arc::new(HttpTransport::new(Duration::from_secs(5), 0, None));

    // Create messages for multiple distinct_ids
    let messages = vec![
        make_message("tok", "user-1", 0, r#"{"event":"a"}"#),
        make_message("tok", "user-2", 1, r#"{"event":"b"}"#),
        make_message("tok", "user-1", 2, r#"{"event":"c"}"#),
        make_message("tok", "user-3", 3, r#"{"event":"d"}"#),
    ];

    // Route
    let groups = router.route_batch(messages);

    // Scatter to workers
    let mut handles = Vec::new();
    for (worker_idx, sub_batch) in groups {
        let t = transport.clone();
        let url = worker_urls[worker_idx].clone();
        handles.push(tokio::spawn(async move {
            t.send_batch(&url, "batch-e2e", sub_batch).await.unwrap()
        }));
    }

    // Gather
    let mut total_accepted = 0u32;
    for h in handles {
        total_accepted += h.await.unwrap();
    }

    assert_eq!(total_accepted, 4);

    // Verify all messages for the same distinct_id landed on the same worker
    let batches_1 = received_1.lock().unwrap();
    let batches_2 = received_2.lock().unwrap();

    let all_messages: Vec<&SerializedKafkaMessage> = batches_1
        .iter()
        .chain(batches_2.iter())
        .flat_map(|b| &b.messages)
        .collect();
    assert_eq!(all_messages.len(), 4);

    // user-1 messages (offsets 0, 2) must be on the same worker
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

    let transport = HttpTransport::new(Duration::from_secs(5), 0, None);

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
