#[path = "common/integration_utils.rs"]
mod integration_utils;

use async_trait::async_trait;
use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestClient;
use capture::api::CaptureError;
use capture::config::CaptureMode;
use capture::limiters::CaptureQuotaLimiter;
use capture::router::router;
use capture::sinks::Event;
use capture::time::TimeSource;
use capture::v0_request::ProcessedEvent;
use chrono::{DateTime, TimeZone, Utc};
use common_redis::MockRedisClient;
use futures::StreamExt;
use health::HealthRegistry;
use integration_utils::{DEFAULT_CONFIG, DEFAULT_TEST_TIME};
use limiters::token_dropper::TokenDropper;
use reqwest::multipart::{Form, Part};
use serde_json::{json, Value};
use std::io::Write;
use std::sync::Arc;
use std::time::Duration;

// Fixed time source for tests
struct FixedTime {
    pub time: DateTime<Utc>,
}

impl TimeSource for FixedTime {
    fn current_time(&self) -> DateTime<Utc> {
        self.time
    }
}

// Simple memory sink for tests
#[derive(Clone, Default)]
struct TestSink;

#[async_trait]
impl Event for TestSink {
    async fn send(&self, _event: ProcessedEvent) -> Result<(), CaptureError> {
        Ok(())
    }

    async fn send_batch(&self, _events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        Ok(())
    }
}

// Capturing sink for Kafka tests - stores events in memory
#[derive(Clone)]
struct CapturingSink {
    events: Arc<tokio::sync::Mutex<Vec<ProcessedEvent>>>,
}

impl CapturingSink {
    fn new() -> Self {
        Self {
            events: Arc::new(tokio::sync::Mutex::new(Vec::new())),
        }
    }

    async fn get_events(&self) -> Vec<ProcessedEvent> {
        self.events.lock().await.clone()
    }
}

#[async_trait]
impl Event for CapturingSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        self.events.lock().await.push(event);
        Ok(())
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.events.lock().await.extend(events);
        Ok(())
    }
}

// Helper to build multipart form and send request
async fn send_multipart_request(
    client: &TestClient,
    form: Form,
    auth_token: Option<&str>,
) -> axum_test_helper::TestResponse {
    // Get the boundary from the form
    let boundary = form.boundary().to_string();
    let content_type = format!("multipart/form-data; boundary={boundary}");

    // Use into_stream() to get the body bytes
    let mut stream = form.into_stream();
    let mut body = Vec::new();

    while let Some(chunk) = stream.next().await {
        body.extend_from_slice(&chunk.unwrap());
    }

    let mut request = client
        .post("/i/v0/ai")
        .header("Content-Type", content_type)
        .body(body);

    if let Some(token) = auth_token {
        request = request.header("Authorization", format!("Bearer {token}"));
    }

    request.send().await
}

/// Helper to create a basic AI event with properties in separate parts
fn create_ai_event_form(event_name: &str, distinct_id: &str, properties: Value) -> Form {
    use uuid::Uuid;

    let event_data = json!({
        "uuid": Uuid::now_v7().to_string(),
        "event": event_name,
        "distinct_id": distinct_id
    });

    Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
}

// Helper to setup test router
fn setup_ai_test_router() -> Router {
    let liveness = HealthRegistry::new("ai_endpoint_tests");
    let sink = TestSink;
    let timesource = FixedTime {
        time: DateTime::parse_from_rfc3339(DEFAULT_TEST_TIME)
            .expect("Invalid fixed time format")
            .with_timezone(&Utc),
    };
    let redis = Arc::new(MockRedisClient::new());

    let mut cfg = DEFAULT_CONFIG.clone();
    cfg.capture_mode = CaptureMode::Events;

    let quota_limiter =
        CaptureQuotaLimiter::new(&cfg, redis.clone(), Duration::from_secs(60 * 60 * 24 * 7));

    router(
        timesource,
        liveness,
        sink,
        redis,
        quota_limiter,
        TokenDropper::default(),
        false,
        CaptureMode::Events,
        None,
        25 * 1024 * 1024,
        false,
        1_i64,
        None,
        false,
        0.0_f32,
        26_214_400, // 25MB default for AI endpoint
    )
}

// ============================================================================
// PHASE 1: HTTP ENDPOINT
// ============================================================================

// ----------------------------------------------------------------------------
// Scenario 1.1: HTTP Method Validation
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_ai_endpoint_get_returns_405() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let response = test_client
        .get("/i/v0/ai")
        .header("Authorization", "Bearer test_token")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
}

#[tokio::test]
async fn test_ai_endpoint_put_returns_405() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let response = test_client
        .put("/i/v0/ai")
        .header("Authorization", "Bearer test_token")
        .body("test")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
}

#[tokio::test]
async fn test_ai_endpoint_delete_returns_405() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let response = test_client
        .delete("/i/v0/ai")
        .header("Authorization", "Bearer test_token")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
}

// ----------------------------------------------------------------------------
// Scenario 1.1: Authentication Validation
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_ai_endpoint_no_auth_returns_401() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let properties = json!({
        "$ai_model": "test"
    });

    let form = create_ai_event_form("$ai_generation", "test_user", properties);

    let response = send_multipart_request(&test_client, form, None).await;
    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
}

// ----------------------------------------------------------------------------
// Scenario 1.1: Content Type Validation
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_ai_endpoint_wrong_content_type_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let response = test_client
        .post("/i/v0/ai")
        .header("Content-Type", "application/json")
        .header(
            "Authorization",
            "Bearer phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3",
        )
        .json(&event_data)
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_ai_endpoint_empty_body_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let response = test_client
        .post("/i/v0/ai")
        .header("Content-Type", "multipart/form-data; boundary=test")
        .header(
            "Authorization",
            "Bearer phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3",
        )
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

// ----------------------------------------------------------------------------
// Scenario 1.2: Multipart Parsing
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_multipart_parsing_with_multiple_blobs() {
    use uuid::Uuid;

    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "uuid": Uuid::now_v7().to_string(),
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "test-multi-blob"
    });

    let input_blob = json!({"messages": [{"role": "user", "content": "Hello"}]});
    let output_blob = json!({"choices": [{"message": {"content": "Hi there"}}]});
    let metadata_blob = json!({"model_version": "1.0", "temperature": 0.7});

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_input",
            Part::bytes(serde_json::to_vec(&input_blob).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_output",
            Part::bytes(serde_json::to_vec(&output_blob).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_metadata",
            Part::bytes(serde_json::to_vec(&metadata_blob).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    let response_json: serde_json::Value = response.json::<serde_json::Value>().await;
    let accepted_parts = response_json["accepted_parts"].as_array().unwrap();
    assert_eq!(accepted_parts.len(), 5);
    assert_eq!(accepted_parts[0]["name"], "event");
    assert_eq!(accepted_parts[0]["length"].as_u64().unwrap(), 98); // UUID adds ~46 bytes
    assert_eq!(accepted_parts[1]["name"], "event.properties");
    assert_eq!(accepted_parts[1]["length"].as_u64().unwrap(), 31);
    assert_eq!(accepted_parts[2]["name"], "event.properties.$ai_input");
    assert_eq!(accepted_parts[2]["length"].as_u64().unwrap(), 48);
    assert_eq!(accepted_parts[3]["name"], "event.properties.$ai_output");
    assert_eq!(accepted_parts[3]["length"].as_u64().unwrap(), 48);
    assert_eq!(accepted_parts[4]["name"], "event.properties.$ai_metadata");
    assert_eq!(accepted_parts[4]["length"].as_u64().unwrap(), 41);
}

#[tokio::test]
async fn test_multipart_parsing_with_mixed_content_types() {
    use uuid::Uuid;

    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "uuid": Uuid::now_v7().to_string(),
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "test-mixed-types"
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_json_blob",
            Part::bytes(serde_json::to_vec(&json!({"type": "json"})).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_text_blob",
            Part::bytes(b"This is plain text content".to_vec())
                .mime_str("text/plain")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_binary_blob",
            Part::bytes(vec![0x00, 0x01, 0x02, 0x03, 0x04, 0x05])
                .mime_str("application/octet-stream")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    let response_json: serde_json::Value = response.json::<serde_json::Value>().await;
    let accepted_parts = response_json["accepted_parts"].as_array().unwrap();
    assert_eq!(accepted_parts.len(), 5);
    assert_eq!(accepted_parts[0]["length"].as_u64().unwrap(), 98); // UUID adds ~46 bytes
    assert_eq!(accepted_parts[1]["length"].as_u64().unwrap(), 32);
    assert_eq!(accepted_parts[2]["content-type"], "application/json");
    assert_eq!(accepted_parts[2]["length"].as_u64().unwrap(), 15);
    assert_eq!(accepted_parts[3]["content-type"], "text/plain");
    assert_eq!(accepted_parts[3]["length"].as_u64().unwrap(), 26);
    assert_eq!(
        accepted_parts[4]["content-type"],
        "application/octet-stream"
    );
    assert_eq!(accepted_parts[4]["length"].as_u64().unwrap(), 6);
}

#[tokio::test]
async fn test_multipart_parsing_with_large_blob() {
    use uuid::Uuid;

    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "uuid": Uuid::now_v7().to_string(),
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "test-large"
    });

    // Create a large JSON blob (100KB)
    let large_blob = json!({
        "messages": (0..100).map(|_| json!({"role": "user", "content": "x".repeat(1000)})).collect::<Vec<_>>()
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_large_input",
            Part::bytes(serde_json::to_vec(&large_blob).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    let response_json: serde_json::Value = response.json::<serde_json::Value>().await;
    let accepted_parts = response_json["accepted_parts"].as_array().unwrap();
    assert_eq!(accepted_parts.len(), 3);
    assert_eq!(accepted_parts[0]["length"].as_u64().unwrap(), 98); // UUID adds ~46 bytes
    assert_eq!(accepted_parts[1]["length"].as_u64().unwrap(), 26);
    assert_eq!(accepted_parts[2]["length"].as_u64().unwrap(), 102914);
}

#[tokio::test]
async fn test_multipart_parsing_with_empty_blob() {
    use uuid::Uuid;

    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "uuid": Uuid::now_v7().to_string(),
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "test-empty"
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_empty",
            Part::bytes(Vec::new())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;

    // Empty blobs should be rejected with 400 Bad Request
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

// ----------------------------------------------------------------------------
// Scenario 1.3: Boundary Validation
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_multipart_missing_boundary_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "properties": {
            "$ai_model": "test-missing-boundary"
        }
    });

    let form = Form::new().part(
        "event",
        Part::bytes(serde_json::to_vec(&event_data).unwrap())
            .file_name("event.json")
            .mime_str("application/json")
            .unwrap(),
    );

    // Use into_stream() to get the body bytes
    let mut stream = form.into_stream();
    let mut body = Vec::new();

    while let Some(chunk) = stream.next().await {
        body.extend_from_slice(&chunk.unwrap());
    }

    // Send with missing boundary parameter in Content-Type
    let response = test_client
        .post("/i/v0/ai")
        .header("Content-Type", "multipart/form-data")
        .header(
            "Authorization",
            "Bearer phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3",
        )
        .body(body)
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_multipart_corrupted_boundary_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "properties": {
            "$ai_model": "test-corrupted-boundary"
        }
    });

    // Manually construct a request with corrupted boundary
    let body = format!(
        "------WebKitFormBoundary1234567890abcdef\r\nContent-Disposition: form-data; name=\"event\"; filename=\"event.json\"\r\nContent-Type: application/json\r\n\r\n{}\r\n------WebKitFormBoundary1234567890abcdef--\r\n",
        serde_json::to_string(&event_data).unwrap()
    );

    let response = test_client
        .post("/i/v0/ai")
        .header(
            "Content-Type",
            "multipart/form-data; boundary=corrupted------WebKitFormBoundary1234567890abcdef",
        )
        .header(
            "Authorization",
            "Bearer phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3",
        )
        .body(body)
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

// ----------------------------------------------------------------------------
// Scenario 1.4: Event Processing Verification
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_multipart_event_not_first_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "properties": {
            "$ai_model": "test-event-not-first"
        }
    });

    // Create multipart data with blob part first, then event part
    let form = Form::new()
        .part(
            "event.properties.$ai_input",
            Part::bytes(
                serde_json::to_vec(&json!({"messages": [{"role": "user", "content": "test"}]}))
                    .unwrap(),
            )
            .file_name("input.json")
            .mime_str("application/json")
            .unwrap(),
        )
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .file_name("event.json")
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

// ----------------------------------------------------------------------------
// Scenario 1.5: Basic Validation
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_invalid_event_name_not_ai_prefix_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "invalid_event_name",
        "distinct_id": "test_user",
        "properties": {
            "$ai_model": "test-invalid-name"
        }
    });

    let form = Form::new().part(
        "event",
        Part::bytes(serde_json::to_vec(&event_data).unwrap())
            .file_name("event.json")
            .mime_str("application/json")
            .unwrap(),
    );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_invalid_event_name_regular_event_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "$pageview",
        "distinct_id": "test_user",
        "properties": {
            "page": "/test"
        }
    });

    let form = Form::new().part(
        "event",
        Part::bytes(serde_json::to_vec(&event_data).unwrap())
            .file_name("event.json")
            .mime_str("application/json")
            .unwrap(),
    );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_invalid_event_name_custom_event_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "button_clicked",
        "distinct_id": "test_user",
        "properties": {
            "button": "submit"
        }
    });

    let form = Form::new().part(
        "event",
        Part::bytes(serde_json::to_vec(&event_data).unwrap())
            .file_name("event.json")
            .mime_str("application/json")
            .unwrap(),
    );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_all_allowed_ai_event_types_accepted() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let allowed_events = vec![
        "$ai_generation",
        "$ai_trace",
        "$ai_span",
        "$ai_embedding",
        "$ai_metric",
        "$ai_feedback",
    ];

    for event_name in allowed_events {
        let properties = json!({
            "$ai_model": "test-model"
        });

        let form = create_ai_event_form(event_name, "test_user", properties);

        let response = send_multipart_request(
            &test_client,
            form,
            Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
        )
        .await;
        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Event type {event_name} should be accepted"
        );
    }
}

#[tokio::test]
async fn test_invalid_ai_event_type_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let invalid_events = vec!["$ai_unknown", "$ai_custom", "$ai_"];

    for event_name in invalid_events {
        let properties = json!({
            "$ai_model": "test-model"
        });

        let form = create_ai_event_form(event_name, "test_user", properties);

        let response = send_multipart_request(
            &test_client,
            form,
            Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
        )
        .await;
        assert_eq!(
            response.status(),
            StatusCode::BAD_REQUEST,
            "Event type {event_name} should be rejected"
        );
    }
}

#[tokio::test]
async fn test_missing_required_ai_properties_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "properties": {
            "custom_property": "test_value"
        }
    });

    let form = Form::new().part(
        "event",
        Part::bytes(serde_json::to_vec(&event_data).unwrap())
            .file_name("event.json")
            .mime_str("application/json")
            .unwrap(),
    );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_empty_event_name_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "",
        "distinct_id": "test_user",
        "properties": {
            "$ai_model": "test-empty-name"
        }
    });

    let form = Form::new().part(
        "event",
        Part::bytes(serde_json::to_vec(&event_data).unwrap())
            .file_name("event.json")
            .mime_str("application/json")
            .unwrap(),
    );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_missing_distinct_id_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "$ai_generation",
        "properties": {
            "$ai_model": "test-missing-distinct-id"
        }
    });

    let form = Form::new().part(
        "event",
        Part::bytes(serde_json::to_vec(&event_data).unwrap())
            .file_name("event.json")
            .mime_str("application/json")
            .unwrap(),
    );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_ai_endpoint_returns_200_for_valid_request() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let properties = json!({
        "$ai_model": "test"
    });

    let form = create_ai_event_form("$ai_generation", "test_user", properties);

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    let response_json: serde_json::Value = response.json::<serde_json::Value>().await;
    assert!(response_json["accepted_parts"].is_array());
    let accepted_parts = response_json["accepted_parts"].as_array().unwrap();
    assert_eq!(accepted_parts.len(), 2);
    assert_eq!(accepted_parts[0]["name"], "event");
    assert_eq!(accepted_parts[0]["content-type"], "application/json");
    assert_eq!(accepted_parts[0]["length"].as_u64().unwrap(), 98); // UUID adds ~46 bytes
    assert_eq!(accepted_parts[1]["name"], "event.properties");
    assert_eq!(accepted_parts[1]["content-type"], "application/json");
    assert_eq!(accepted_parts[1]["length"].as_u64().unwrap(), 20);
}

// ----------------------------------------------------------------------------
// Properties Handling Tests
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_properties_in_event_part_only() {
    use uuid::Uuid;

    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "uuid": Uuid::now_v7().to_string(),
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "properties": {
            "$ai_model": "embedded-model",
            "custom_field": "embedded-value"
        }
    });

    let form = Form::new().part(
        "event",
        Part::bytes(serde_json::to_vec(&event_data).unwrap())
            .mime_str("application/json")
            .unwrap(),
    );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    let response_json: serde_json::Value = response.json::<serde_json::Value>().await;
    let accepted_parts = response_json["accepted_parts"].as_array().unwrap();
    assert_eq!(accepted_parts.len(), 1);
    assert_eq!(accepted_parts[0]["name"], "event");
    assert_eq!(accepted_parts[0]["length"].as_u64().unwrap(), 174); // UUID adds ~46 bytes (128 + 46)
}

#[tokio::test]
async fn test_properties_in_separate_part_only() {
    use uuid::Uuid;

    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "uuid": Uuid::now_v7().to_string(),
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "separate-model",
        "custom_field": "separate-value"
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    let response_json: serde_json::Value = response.json::<serde_json::Value>().await;
    let accepted_parts = response_json["accepted_parts"].as_array().unwrap();
    assert_eq!(accepted_parts.len(), 2);
    assert_eq!(accepted_parts[0]["name"], "event");
    assert_eq!(accepted_parts[0]["length"].as_u64().unwrap(), 98); // UUID adds ~46 bytes
    assert_eq!(accepted_parts[1]["name"], "event.properties");
    assert_eq!(accepted_parts[1]["length"].as_u64().unwrap(), 62);
}

#[tokio::test]
async fn test_properties_both_embedded_and_separate_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "properties": {
            "$ai_model": "embedded-model",
            "custom_field": "embedded-value"
        }
    });

    let properties = json!({
        "$ai_model": "override-model",
        "custom_field": "override-value"
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

// ----------------------------------------------------------------------------
// Size Limit Tests
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_event_exceeds_32kb_returns_413() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    // Create event with large properties that exceed 32KB
    let large_value = "x".repeat(33 * 1024);
    let event_data = json!({
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "properties": {
            "$ai_model": "test",
            "large_field": large_value
        }
    });

    let form = Form::new().part(
        "event",
        Part::bytes(serde_json::to_vec(&event_data).unwrap())
            .mime_str("application/json")
            .unwrap(),
    );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::PAYLOAD_TOO_LARGE);
}

#[tokio::test]
async fn test_combined_event_properties_exceeds_960kb_returns_413() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    // Create event and properties that together exceed 960KB
    // 961KB to ensure we exceed the limit
    let large_value = "x".repeat(961 * 1024);
    let event_data = json!({
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "test",
        "large_field": large_value
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::PAYLOAD_TOO_LARGE);
}

#[tokio::test]
async fn test_sum_of_all_parts_exceeds_25mb_returns_413() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "test"
    });

    // Create a blob that, combined with event and properties, exceeds 25MB
    // Event ~52 bytes + properties ~24 bytes + blob ~25MB = exceeds limit
    let large_blob = vec![0u8; 25 * 1024 * 1024];

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_input",
            Part::bytes(large_blob)
                .mime_str("application/octet-stream")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::PAYLOAD_TOO_LARGE);
}

#[tokio::test]
async fn test_request_body_exceeds_110_percent_limit_returns_413() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let event_data = json!({
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "test"
    });

    // Create a blob that's just barely over 25MB
    // This will result in a request body that exceeds 27.5MB (110% limit)
    // once multipart overhead is added
    let large_blob = vec![0u8; (25 * 1024 * 1024) + (3 * 1024 * 1024)]; // 28MB

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_input",
            Part::bytes(large_blob)
                .mime_str("application/octet-stream")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;

    // Axum's DefaultBodyLimit returns 413 Payload Too Large when the body exceeds the limit
    assert_eq!(response.status(), StatusCode::PAYLOAD_TOO_LARGE);
}

// ----------------------------------------------------------------------------
// Content Type Validation Tests
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_blob_with_application_octet_stream_content_type() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let properties = json!({
        "$ai_model": "test"
    });

    let blob_data = vec![0u8, 1u8, 2u8, 3u8];

    let form = create_ai_event_form("$ai_generation", "test_user", properties).part(
        "event.properties.$ai_binary_data",
        Part::bytes(blob_data)
            .mime_str("application/octet-stream")
            .unwrap(),
    );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);
}

#[tokio::test]
async fn test_blob_with_application_json_content_type() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let properties = json!({
        "$ai_model": "test"
    });

    let blob_data = json!({"key": "value"}).to_string();

    let form = create_ai_event_form("$ai_generation", "test_user", properties).part(
        "event.properties.$ai_input",
        Part::bytes(blob_data.into_bytes())
            .mime_str("application/json")
            .unwrap(),
    );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);
}

#[tokio::test]
async fn test_blob_with_text_plain_content_type() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let properties = json!({
        "$ai_model": "test"
    });

    let blob_data = "This is plain text data";

    let form = create_ai_event_form("$ai_generation", "test_user", properties).part(
        "event.properties.$ai_output",
        Part::bytes(blob_data.as_bytes().to_vec())
            .mime_str("text/plain")
            .unwrap(),
    );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);
}

#[tokio::test]
async fn test_blob_with_invalid_content_type_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let properties = json!({
        "$ai_model": "test"
    });

    let blob_data = vec![0u8, 1u8, 2u8, 3u8];

    let form = create_ai_event_form("$ai_generation", "test_user", properties).part(
        "event.properties.$ai_data",
        Part::bytes(blob_data).mime_str("application/xml").unwrap(),
    );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_blob_without_content_type_returns_400() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let properties = json!({
        "$ai_model": "test"
    });

    let blob_data = vec![0u8, 1u8, 2u8, 3u8];

    // Create a part without Content-Type (reqwest doesn't set it if we don't call mime_str)
    let form = create_ai_event_form("$ai_generation", "test_user", properties)
        .part("event.properties.$ai_data", Part::bytes(blob_data));

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

// ----------------------------------------------------------------------------
// Compression Tests
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_gzip_compressed_request() {
    let router = setup_ai_test_router();
    let test_client = TestClient::new(router);

    let properties = json!({
        "$ai_model": "test-gzip"
    });

    let form = create_ai_event_form("$ai_generation", "test_user", properties);

    // Get the multipart body
    let boundary = form.boundary().to_string();
    let content_type = format!("multipart/form-data; boundary={boundary}");

    let mut stream = form.into_stream();
    let mut body = Vec::new();

    while let Some(chunk) = stream.next().await {
        body.extend_from_slice(&chunk.unwrap());
    }

    // Compress the body with gzip
    let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    encoder.write_all(&body).unwrap();
    let compressed_body = encoder.finish().unwrap();

    // Send compressed request
    let response = test_client
        .post("/i/v0/ai")
        .header("Content-Type", content_type)
        .header("Content-Encoding", "gzip")
        .header(
            "Authorization",
            "Bearer phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3",
        )
        .body(compressed_body)
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    // Verify response (lengths should match uncompressed data)
    let response_json: serde_json::Value = response.json::<serde_json::Value>().await;
    let accepted_parts = response_json["accepted_parts"].as_array().unwrap();
    assert_eq!(accepted_parts.len(), 2);
    assert_eq!(accepted_parts[0]["name"], "event");
    assert_eq!(accepted_parts[0]["length"].as_u64().unwrap(), 98); // UUID adds ~46 bytes
    assert_eq!(accepted_parts[1]["name"], "event.properties");
    assert_eq!(accepted_parts[1]["length"].as_u64().unwrap(), 25);
}

// ----------------------------------------------------------------------------
// Scenario 1.6: Kafka Publishing and S3 Placeholders
// ----------------------------------------------------------------------------

// Helper to setup test router with CapturingSink
fn setup_ai_test_router_with_capturing_sink() -> (Router, CapturingSink) {
    let liveness = HealthRegistry::new("ai_endpoint_tests");
    let sink = CapturingSink::new();
    let sink_clone = sink.clone();
    let timesource = FixedTime {
        time: DateTime::parse_from_rfc3339(DEFAULT_TEST_TIME)
            .expect("Invalid fixed time format")
            .with_timezone(&Utc),
    };
    let redis = Arc::new(MockRedisClient::new());

    let mut cfg = DEFAULT_CONFIG.clone();
    cfg.capture_mode = CaptureMode::Events;

    let quota_limiter =
        CaptureQuotaLimiter::new(&cfg, redis.clone(), Duration::from_secs(60 * 60 * 24 * 7));

    let router = router(
        timesource,
        liveness,
        sink,
        redis,
        quota_limiter,
        TokenDropper::default(),
        false,
        CaptureMode::Events,
        None,
        25 * 1024 * 1024,
        false,
        1_i64,
        None,
        false,
        0.0_f32,
        26_214_400, // 25MB default for AI endpoint
    );

    (router, sink_clone)
}

#[tokio::test]
async fn test_ai_event_published_to_kafka() {
    let (router, sink) = setup_ai_test_router_with_capturing_sink();
    let test_client = TestClient::new(router);

    let event_uuid = "550e8400-e29b-41d4-a716-446655440000";
    let event_data = json!({
        "uuid": event_uuid,
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "gpt-4"
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    // Verify event was published to Kafka
    let events = sink.get_events().await;
    assert_eq!(
        events.len(),
        1,
        "Expected exactly one event to be published"
    );

    let event = &events[0];

    // Verify event UUID
    let event_json: serde_json::Value = serde_json::from_str(&event.event.data).unwrap();
    assert_eq!(event_json["uuid"], event_uuid);
    assert_eq!(event_json["event"], "$ai_generation");
    assert_eq!(event_json["distinct_id"], "test_user");

    // Verify properties
    let props = event_json["properties"].as_object().unwrap();
    assert_eq!(props["$ai_model"], "gpt-4");
}

#[tokio::test]
async fn test_ai_event_with_blobs_published_with_s3_placeholders() {
    let (router, sink) = setup_ai_test_router_with_capturing_sink();
    let test_client = TestClient::new(router);

    let event_uuid = "650e8400-e29b-41d4-a716-446655440001";
    let event_data = json!({
        "uuid": event_uuid,
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "gpt-4"
    });

    let input_blob = json!({"messages": [{"role": "user", "content": "Hello"}]});
    let output_blob = json!({"choices": [{"message": {"content": "Hi there"}}]});

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_input",
            Part::bytes(serde_json::to_vec(&input_blob).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_output",
            Part::bytes(serde_json::to_vec(&output_blob).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    // Verify event was published to Kafka
    let events = sink.get_events().await;
    assert_eq!(
        events.len(),
        1,
        "Expected exactly one event to be published"
    );

    let event = &events[0];
    let event_json: serde_json::Value = serde_json::from_str(&event.event.data).unwrap();

    // Verify properties contain S3 placeholder URLs
    let props = event_json["properties"].as_object().unwrap();

    // Both blobs should have S3 placeholder URLs
    let input_url = props["$ai_input"].as_str().unwrap();
    let output_url = props["$ai_output"].as_str().unwrap();

    // Verify S3 URLs point to same file with different ranges
    assert!(input_url.starts_with("s3://PLACEHOLDER/TEAM_ID/"));
    assert!(output_url.starts_with("s3://PLACEHOLDER/TEAM_ID/"));

    // Extract UUIDs from both URLs (should be the same)
    // URL format: s3://PLACEHOLDER/TEAM_ID/{uuid}?range=...
    let input_uuid = input_url
        .split('/')
        .nth(4)
        .unwrap()
        .split('?')
        .next()
        .unwrap();
    let output_uuid = output_url
        .split('/')
        .nth(4)
        .unwrap()
        .split('?')
        .next()
        .unwrap();
    assert_eq!(
        input_uuid, output_uuid,
        "Both blobs should point to same file"
    );
    assert_eq!(input_uuid, event_uuid, "UUID should match event UUID");

    // Verify ranges are sequential
    assert!(
        input_url.contains("range="),
        "Input URL should have range parameter"
    );
    assert!(
        output_url.contains("range="),
        "Output URL should have range parameter"
    );

    // Extract range values
    let input_range = input_url.split("range=").nth(1).unwrap();
    let output_range = output_url.split("range=").nth(1).unwrap();

    // Input blob JSON is 48 bytes, so should be range=0-47
    assert_eq!(input_range, "0-47", "First blob should start at 0");

    // Output blob JSON is 48 bytes, so should be range=48-95 (starts where input ends)
    assert_eq!(
        output_range, "48-95",
        "Second blob should start where first ends"
    );
}

#[tokio::test]
async fn test_ai_event_with_multiple_blobs_sequential_ranges() {
    let (router, sink) = setup_ai_test_router_with_capturing_sink();
    let test_client = TestClient::new(router);

    let event_uuid = "750e8400-e29b-41d4-a716-446655440002";
    let event_data = json!({
        "uuid": event_uuid,
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "claude-3"
    });

    // Create blobs of different sizes
    let blob1 = "A".repeat(100); // 100 bytes
    let blob2 = "B".repeat(200); // 200 bytes
    let blob3 = "C".repeat(150); // 150 bytes

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_blob1",
            Part::bytes(blob1.into_bytes())
                .mime_str("text/plain")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_blob2",
            Part::bytes(blob2.into_bytes())
                .mime_str("text/plain")
                .unwrap(),
        )
        .part(
            "event.properties.$ai_blob3",
            Part::bytes(blob3.into_bytes())
                .mime_str("text/plain")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    // Verify event was published to Kafka
    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let event = &events[0];
    let event_json: serde_json::Value = serde_json::from_str(&event.event.data).unwrap();
    let props = event_json["properties"].as_object().unwrap();

    // Extract all URLs
    let url1 = props["$ai_blob1"].as_str().unwrap();
    let url2 = props["$ai_blob2"].as_str().unwrap();
    let url3 = props["$ai_blob3"].as_str().unwrap();

    // Verify all point to same file
    // URL format: s3://PLACEHOLDER/TEAM_ID/{uuid}?range=...
    let uuid1 = url1.split('/').nth(4).unwrap().split('?').next().unwrap();
    let uuid2 = url2.split('/').nth(4).unwrap().split('?').next().unwrap();
    let uuid3 = url3.split('/').nth(4).unwrap().split('?').next().unwrap();
    assert_eq!(uuid1, uuid2);
    assert_eq!(uuid2, uuid3);
    assert_eq!(uuid1, event_uuid);

    // Extract ranges
    let range1 = url1.split("range=").nth(1).unwrap();
    let range2 = url2.split("range=").nth(1).unwrap();
    let range3 = url3.split("range=").nth(1).unwrap();

    // Verify sequential ranges (inclusive on both ends)
    assert_eq!(range1, "0-99", "First blob: 100 bytes, range 0-99");
    assert_eq!(
        range2, "100-299",
        "Second blob: 200 bytes, starts at 100, range 100-299"
    );
    assert_eq!(
        range3, "300-449",
        "Third blob: 150 bytes, starts at 300, range 300-449"
    );
}

#[tokio::test]
async fn test_ai_event_metadata_preserved_in_kafka() {
    let (router, sink) = setup_ai_test_router_with_capturing_sink();
    let test_client = TestClient::new(router);

    let event_uuid = "850e8400-e29b-41d4-a716-446655440003";
    let distinct_id = "user_12345";
    let event_data = json!({
        "uuid": event_uuid,
        "event": "$ai_trace",
        "distinct_id": distinct_id,
        "timestamp": "2024-01-15T10:30:00Z"
    });

    let properties = json!({
        "$ai_model": "gpt-4-turbo",
        "$ai_trace_id": "trace_abc123",
        "custom_metadata": "test_value"
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    // Verify event metadata
    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let event = &events[0];
    let event_json: serde_json::Value = serde_json::from_str(&event.event.data).unwrap();

    // Verify all metadata is preserved
    assert_eq!(event_json["uuid"], event_uuid);
    assert_eq!(event_json["event"], "$ai_trace");
    assert_eq!(event_json["distinct_id"], distinct_id);
    assert_eq!(event_json["timestamp"], "2024-01-15T10:30:00Z");

    let props = event_json["properties"].as_object().unwrap();
    assert_eq!(props["$ai_model"], "gpt-4-turbo");
    assert_eq!(props["$ai_trace_id"], "trace_abc123");
    assert_eq!(props["custom_metadata"], "test_value");
}

// ----------------------------------------------------------------------------
// Timestamp and $ignore_sent_at Tests
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_ai_event_with_ignore_sent_at_true() {
    let (router, sink) = setup_ai_test_router_with_capturing_sink();
    let test_client = TestClient::new(router);

    let event_uuid = "950e8400-e29b-41d4-a716-446655440004";
    let event_timestamp = "2024-01-15T10:00:00Z";
    let sent_at = "2024-01-15T10:05:00Z"; // 5 minutes later

    let event_data = json!({
        "uuid": event_uuid,
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "timestamp": event_timestamp,
        "sent_at": sent_at
    });

    let properties = json!({
        "$ai_model": "gpt-4",
        "$ignore_sent_at": true  // Should ignore clock skew correction
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    // Verify timestamp was not adjusted (sent_at was ignored)
    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let event = &events[0];
    let computed_timestamp = event.metadata.computed_timestamp.unwrap();

    // Should use the event timestamp directly without clock skew correction
    let expected = DateTime::parse_from_rfc3339(event_timestamp)
        .unwrap()
        .with_timezone(&chrono::Utc);
    assert_eq!(
        computed_timestamp, expected,
        "With $ignore_sent_at=true, timestamp should match event timestamp exactly"
    );
}

#[tokio::test]
async fn test_ai_event_with_ignore_sent_at_false() {
    let (router, sink) = setup_ai_test_router_with_capturing_sink();
    let test_client = TestClient::new(router);

    let event_uuid = "a50e8400-e29b-41d4-a716-446655440005";
    let event_timestamp = "2024-01-01T11:59:55Z";
    let sent_at = "2024-01-01T12:00:05Z"; // 10 seconds later

    let event_data = json!({
        "uuid": event_uuid,
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "timestamp": event_timestamp,
        "sent_at": sent_at
    });

    let properties = json!({
        "$ai_model": "gpt-4",
        "$ignore_sent_at": false  // Should apply clock skew correction
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    // Verify timestamp was adjusted using clock skew correction
    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let event = &events[0];
    let computed_timestamp = event.metadata.computed_timestamp.unwrap();

    // With clock skew correction:
    // computed = now + (timestamp - sent_at)
    // now = DEFAULT_TEST_TIME (2025-07-01T11:00:00Z)
    // timestamp - sent_at = 11:59:55 - 12:00:05 = -10 seconds
    // computed = 2025-07-01T11:00:00Z - 10s = 2025-07-01T10:59:50Z
    let expected = chrono::Utc
        .with_ymd_and_hms(2025, 7, 1, 10, 59, 50)
        .unwrap();

    assert_eq!(
        computed_timestamp, expected,
        "With $ignore_sent_at=false, clock skew correction should be applied"
    );
}

#[tokio::test]
async fn test_ai_event_without_ignore_sent_at_defaults_to_false() {
    let (router, sink) = setup_ai_test_router_with_capturing_sink();
    let test_client = TestClient::new(router);

    let event_uuid = "b50e8400-e29b-41d4-a716-446655440006";
    let event_timestamp = "2024-01-01T11:59:55Z";
    let sent_at = "2024-01-01T12:00:05Z"; // 10 seconds later

    let event_data = json!({
        "uuid": event_uuid,
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "timestamp": event_timestamp,
        "sent_at": sent_at
    });

    let properties = json!({
        "$ai_model": "gpt-4"
        // No $ignore_sent_at property - should default to false
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    // Verify timestamp was adjusted (default behavior is to apply clock skew correction)
    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let event = &events[0];
    let computed_timestamp = event.metadata.computed_timestamp.unwrap();

    // Should apply clock skew correction by default
    let expected = chrono::Utc
        .with_ymd_and_hms(2025, 7, 1, 10, 59, 50)
        .unwrap();

    assert_eq!(
        computed_timestamp, expected,
        "Without $ignore_sent_at property, clock skew correction should be applied (default behavior)"
    );
}

// ----------------------------------------------------------------------------
// IP Address Extraction and Redaction Tests
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_ai_event_ip_defaults_to_localhost_in_tests() {
    let (router, sink) = setup_ai_test_router_with_capturing_sink();
    let test_client = TestClient::new(router);

    let event_uuid = "c50e8400-e29b-41d4-a716-446655440007";
    let event_data = json!({
        "uuid": event_uuid,
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "gpt-4"
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    // Verify IP address defaults to 127.0.0.1 in test environment
    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let event = &events[0];
    assert_eq!(
        event.event.ip, "127.0.0.1",
        "IP address should default to 127.0.0.1 when ConnectInfo is not available"
    );
}

#[tokio::test]
async fn test_ai_event_ip_redacted_for_internal_events() {
    let (router, sink) = setup_ai_test_router_with_capturing_sink();
    let test_client = TestClient::new(router);

    let event_uuid = "d50e8400-e29b-41d4-a716-446655440008";
    let event_data = json!({
        "uuid": event_uuid,
        "event": "$ai_generation",
        "distinct_id": "test_user"
    });

    let properties = json!({
        "$ai_model": "gpt-4",
        "capture_internal": true  // Mark as internal event - IP should be redacted
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    // Verify IP address is redacted to 127.0.0.1 for internal events
    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let event = &events[0];
    assert_eq!(
        event.event.ip, "127.0.0.1",
        "IP address should be redacted to 127.0.0.1 for events with capture_internal property"
    );

    // Verify the capture_internal property is preserved
    let event_json: serde_json::Value = serde_json::from_str(&event.event.data).unwrap();
    let props = event_json["properties"].as_object().unwrap();
    assert_eq!(props["capture_internal"], true);
}

// ----------------------------------------------------------------------------
// Timestamp Conversion Tests
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_ai_event_with_invalid_sent_at_skips_clock_skew_correction() {
    let (router, sink) = setup_ai_test_router_with_capturing_sink();
    let test_client = TestClient::new(router);

    let event_uuid = "e50e8400-e29b-41d4-a716-446655440009";
    let event_timestamp = "2024-01-01T11:59:55Z";

    let event_data = json!({
        "uuid": event_uuid,
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "timestamp": event_timestamp,
        "sent_at": "invalid-timestamp-format"  // Invalid sent_at that can't be parsed
    });

    let properties = json!({
        "$ai_model": "gpt-4"
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    // Verify timestamp was not adjusted (sent_at was invalid, so treated as missing)
    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let event = &events[0];
    let computed_timestamp = event.metadata.computed_timestamp.unwrap();

    // Should use the event timestamp directly without clock skew correction
    // (same behavior as if sent_at was missing)
    let expected = DateTime::parse_from_rfc3339(event_timestamp)
        .unwrap()
        .with_timezone(&chrono::Utc);
    assert_eq!(
        computed_timestamp, expected,
        "With invalid sent_at, timestamp should match event timestamp exactly (no clock skew correction)"
    );
}

#[tokio::test]
async fn test_ai_event_without_sent_at_uses_event_timestamp() {
    let (router, sink) = setup_ai_test_router_with_capturing_sink();
    let test_client = TestClient::new(router);

    let event_uuid = "f50e8400-e29b-41d4-a716-446655440010";
    let event_timestamp = "2024-01-01T11:59:55Z";

    let event_data = json!({
        "uuid": event_uuid,
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "timestamp": event_timestamp
        // No sent_at field
    });

    let properties = json!({
        "$ai_model": "gpt-4"
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    // Verify timestamp uses event timestamp without clock skew correction
    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let event = &events[0];
    let computed_timestamp = event.metadata.computed_timestamp.unwrap();

    // Should use the event timestamp directly
    let expected = DateTime::parse_from_rfc3339(event_timestamp)
        .unwrap()
        .with_timezone(&chrono::Utc);
    assert_eq!(
        computed_timestamp, expected,
        "Without sent_at, timestamp should match event timestamp exactly"
    );
}

#[tokio::test]
async fn test_ai_event_with_valid_sent_at_applies_clock_skew_correction() {
    let (router, sink) = setup_ai_test_router_with_capturing_sink();
    let test_client = TestClient::new(router);

    let event_uuid = "050e8400-e29b-41d4-a716-446655440011";
    let event_timestamp = "2024-01-01T11:59:55Z";
    let sent_at = "2024-01-01T12:00:05Z"; // 10 seconds later

    let event_data = json!({
        "uuid": event_uuid,
        "event": "$ai_generation",
        "distinct_id": "test_user",
        "timestamp": event_timestamp,
        "sent_at": sent_at  // Valid sent_at
    });

    let properties = json!({
        "$ai_model": "gpt-4"
    });

    let form = Form::new()
        .part(
            "event",
            Part::bytes(serde_json::to_vec(&event_data).unwrap())
                .mime_str("application/json")
                .unwrap(),
        )
        .part(
            "event.properties",
            Part::bytes(serde_json::to_vec(&properties).unwrap())
                .mime_str("application/json")
                .unwrap(),
        );

    let response = send_multipart_request(
        &test_client,
        form,
        Some("phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    // Verify timestamp was adjusted using clock skew correction
    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let event = &events[0];
    let computed_timestamp = event.metadata.computed_timestamp.unwrap();

    // With clock skew correction:
    // computed = now + (timestamp - sent_at)
    // now = DEFAULT_TEST_TIME (2025-07-01T11:00:00Z)
    // timestamp - sent_at = 11:59:55 - 12:00:05 = -10 seconds
    // computed = 2025-07-01T11:00:00Z - 10s = 2025-07-01T10:59:50Z
    let expected = chrono::Utc
        .with_ymd_and_hms(2025, 7, 1, 10, 59, 50)
        .unwrap();

    assert_eq!(
        computed_timestamp, expected,
        "With valid sent_at, clock skew correction should be applied"
    );
}
