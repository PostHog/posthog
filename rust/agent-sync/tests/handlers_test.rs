mod common;

use axum::http::StatusCode;
use futures::StreamExt;
use http_body_util::BodyExt;
use serde_json::json;
use std::time::Duration;
use uuid::Uuid;

use agent_sync::types::AgentEvent;
use common::{test_event, TestHarness};

#[tokio::test]
async fn test_get_logs_returns_events() {
    let run_id = Uuid::new_v4();
    let events = vec![
        test_event().run_id(run_id).sequence(1).build(),
        test_event().run_id(run_id).sequence(2).build(),
        test_event().run_id(run_id).sequence(3).build(),
    ];

    let harness = TestHarness::builder().with_events(events).build().await;

    let task_id = Uuid::new_v4();
    let response = harness
        .get(&format!(
            "/api/projects/1/tasks/{}/runs/{}/logs",
            task_id, run_id
        ))
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let events: Vec<AgentEvent> = TestHarness::body_json(response).await;
    assert_eq!(events.len(), 3);
    assert_eq!(events[0].sequence, 1);
    assert_eq!(events[1].sequence, 2);
    assert_eq!(events[2].sequence, 3);
    assert_eq!(events[0].run_id, run_id);
}

#[tokio::test]
async fn test_get_logs_respects_after_filter() {
    let run_id = Uuid::new_v4();
    let events = vec![
        test_event().run_id(run_id).sequence(1).build(),
        test_event().run_id(run_id).sequence(2).build(),
        test_event().run_id(run_id).sequence(3).build(),
    ];

    let harness = TestHarness::builder().with_events(events).build().await;

    let task_id = Uuid::new_v4();
    let response = harness
        .get(&format!(
            "/api/projects/1/tasks/{}/runs/{}/logs?after=1",
            task_id, run_id
        ))
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let events: Vec<AgentEvent> = TestHarness::body_json(response).await;
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].sequence, 2);
    assert_eq!(events[1].sequence, 3);
}

#[tokio::test]
async fn test_get_logs_respects_limit() {
    let run_id = Uuid::new_v4();
    let events = vec![
        test_event().run_id(run_id).sequence(1).build(),
        test_event().run_id(run_id).sequence(2).build(),
        test_event().run_id(run_id).sequence(3).build(),
    ];

    let harness = TestHarness::builder().with_events(events).build().await;

    let task_id = Uuid::new_v4();
    let response = harness
        .get(&format!(
            "/api/projects/1/tasks/{}/runs/{}/logs?limit=2",
            task_id, run_id
        ))
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let events: Vec<AgentEvent> = TestHarness::body_json(response).await;
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].sequence, 1);
    assert_eq!(events[1].sequence, 2);
}

#[tokio::test]
async fn test_get_logs_empty_run_returns_empty() {
    let harness = TestHarness::new().await;

    let task_id = Uuid::new_v4();
    let run_id = Uuid::new_v4();
    let response = harness
        .get(&format!(
            "/api/projects/1/tasks/{}/runs/{}/logs",
            task_id, run_id
        ))
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let events: Vec<AgentEvent> = TestHarness::body_json(response).await;
    assert!(events.is_empty());
}

#[tokio::test]
async fn test_get_logs_unauthorized_returns_401() {
    let harness = TestHarness::new().await;

    let task_id = Uuid::new_v4();
    let run_id = Uuid::new_v4();
    let response = harness
        .get_without_auth(&format!(
            "/api/projects/1/tasks/{}/runs/{}/logs",
            task_id, run_id
        ))
        .await;

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn test_get_logs_forbidden_returns_403() {
    let harness = TestHarness::builder().unauthorized().build().await;

    let task_id = Uuid::new_v4();
    let run_id = Uuid::new_v4();
    let response = harness
        .get(&format!(
            "/api/projects/1/tasks/{}/runs/{}/logs",
            task_id, run_id
        ))
        .await;

    assert_eq!(response.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn test_post_sync_publishes_event() {
    let harness = TestHarness::new().await;

    let task_id = Uuid::new_v4();
    let run_id = Uuid::new_v4();
    let message = json!({
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {"key": "value"}
    });

    let response = harness
        .post(
            &format!("/api/projects/1/tasks/{}/runs/{}/sync", task_id, run_id),
            message,
        )
        .await;

    assert_eq!(response.status(), StatusCode::ACCEPTED);

    let published = harness.published_events();
    assert_eq!(published.len(), 1);
    assert_eq!(published[0].run_id, run_id);
    assert_eq!(published[0].task_id, task_id);
    assert_eq!(published[0].entry_type, "session/update");
    assert_eq!(published[0].team_id, 1);
}

#[tokio::test]
async fn test_post_sync_with_different_methods() {
    let harness = TestHarness::new().await;

    let task_id = Uuid::new_v4();
    let run_id = Uuid::new_v4();

    let methods = ["result", "error", "heartbeat"];
    for method in methods {
        let message = json!({
            "jsonrpc": "2.0",
            "method": method,
            "params": {}
        });

        let response = harness
            .post(
                &format!("/api/projects/1/tasks/{}/runs/{}/sync", task_id, run_id),
                message,
            )
            .await;

        assert_eq!(response.status(), StatusCode::ACCEPTED);
    }

    let published = harness.published_events();
    assert_eq!(published.len(), 3);
    assert_eq!(published[0].entry_type, "result");
    assert_eq!(published[1].entry_type, "error");
    assert_eq!(published[2].entry_type, "heartbeat");
}

#[tokio::test]
async fn test_post_sync_forbidden_returns_403() {
    let harness = TestHarness::builder().unauthorized().build().await;

    let task_id = Uuid::new_v4();
    let run_id = Uuid::new_v4();
    let message = json!({"jsonrpc": "2.0", "method": "test"});

    let response = harness
        .post(
            &format!("/api/projects/1/tasks/{}/runs/{}/sync", task_id, run_id),
            message,
        )
        .await;

    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    assert!(harness.published_events().is_empty());
}

#[tokio::test]
async fn test_health_endpoints() {
    let harness = TestHarness::new().await;

    let response = harness.get_without_auth("/_liveness").await;
    assert_eq!(response.status(), StatusCode::OK);
}

#[tokio::test]
async fn test_get_sync_returns_sse_stream() {
    let run_id = Uuid::new_v4();
    let events = vec![
        test_event().run_id(run_id).sequence(1).build(),
        test_event().run_id(run_id).sequence(2).build(),
    ];

    let harness = TestHarness::builder().with_events(events).build().await;

    let task_id = Uuid::new_v4();
    let response = harness
        .get(&format!(
            "/api/projects/1/tasks/{}/runs/{}/sync",
            task_id, run_id
        ))
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let content_type = response.headers().get("content-type").unwrap();
    assert!(content_type.to_str().unwrap().contains("text/event-stream"));

    let mut collected = String::new();
    let mut body_stream = response.into_body().into_data_stream();

    let timeout_result = tokio::time::timeout(Duration::from_secs(2), async {
        while let Some(chunk) = body_stream.next().await {
            if let Ok(bytes) = chunk {
                collected.push_str(&String::from_utf8_lossy(&bytes));
                if collected.contains("id: 2") {
                    break;
                }
            }
        }
    })
    .await;

    assert!(timeout_result.is_ok(), "Timed out waiting for SSE events");
    assert!(collected.contains("id: 1"), "Should contain event 1");
    assert!(collected.contains("id: 2"), "Should contain event 2");
    assert!(collected.contains("data:"), "Should contain data field");
}

#[tokio::test]
async fn test_get_sync_respects_last_event_id() {
    let run_id = Uuid::new_v4();
    let events = vec![
        test_event().run_id(run_id).sequence(1).build(),
        test_event().run_id(run_id).sequence(2).build(),
        test_event().run_id(run_id).sequence(3).build(),
    ];

    let harness = TestHarness::builder().with_events(events).build().await;

    let task_id = Uuid::new_v4();
    let response = harness
        .get_with_header(
            &format!("/api/projects/1/tasks/{}/runs/{}/sync", task_id, run_id),
            "Last-Event-ID",
            "1",
        )
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let mut collected = String::new();
    let mut body_stream = response.into_body().into_data_stream();

    let timeout_result = tokio::time::timeout(Duration::from_secs(2), async {
        while let Some(chunk) = body_stream.next().await {
            if let Ok(bytes) = chunk {
                collected.push_str(&String::from_utf8_lossy(&bytes));
                if collected.contains("id: 3") {
                    break;
                }
            }
        }
    })
    .await;

    assert!(timeout_result.is_ok(), "Timed out waiting for SSE events");
    assert!(
        !collected.contains("id: 1\n"),
        "Should not contain event 1"
    );
    assert!(collected.contains("id: 2"), "Should contain event 2");
    assert!(collected.contains("id: 3"), "Should contain event 3");
}

#[tokio::test]
async fn test_get_sync_unauthorized_returns_401() {
    let harness = TestHarness::new().await;

    let task_id = Uuid::new_v4();
    let run_id = Uuid::new_v4();
    let response = harness
        .get_without_auth(&format!(
            "/api/projects/1/tasks/{}/runs/{}/sync",
            task_id, run_id
        ))
        .await;

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn test_get_sync_forbidden_returns_403() {
    let harness = TestHarness::builder().unauthorized().build().await;

    let task_id = Uuid::new_v4();
    let run_id = Uuid::new_v4();
    let response = harness
        .get(&format!(
            "/api/projects/1/tasks/{}/runs/{}/sync",
            task_id, run_id
        ))
        .await;

    assert_eq!(response.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn test_get_sync_receives_live_events() {
    let run_id = Uuid::new_v4();
    let harness = TestHarness::new().await;
    let harness_router = harness.router.clone();

    let event = test_event().run_id(run_id).sequence(42).build();

    tokio::spawn({
        let harness_router = harness_router.clone();
        let event = event.clone();
        async move {
            tokio::time::sleep(Duration::from_millis(50)).await;
            harness_router.route(event).await;
        }
    });

    let mut rx = harness_router.subscribe(&run_id.to_string());

    let timeout = tokio::time::timeout(Duration::from_secs(2), rx.recv()).await;
    assert!(timeout.is_ok(), "Should receive event within timeout");

    let received = timeout.unwrap().unwrap();
    assert_eq!(received.sequence, 42);
    assert_eq!(received.run_id, run_id);
}

#[tokio::test]
async fn test_get_sync_empty_run_returns_sse_content_type() {
    let harness = TestHarness::new().await;

    let task_id = Uuid::new_v4();
    let run_id = Uuid::new_v4();
    let response = harness
        .get(&format!(
            "/api/projects/1/tasks/{}/runs/{}/sync",
            task_id, run_id
        ))
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let content_type = response.headers().get("content-type").unwrap();
    assert!(content_type.to_str().unwrap().contains("text/event-stream"));
}
