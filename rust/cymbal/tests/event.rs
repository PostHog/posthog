use std::{collections::HashMap, fs, sync::Arc};

use axum::{body::Body, http::Request};
use chrono::Utc;
use common_types::error_tracking::FrameId;
use cymbal::{
    error::UnhandledError,
    frames::Frame,
    symbol_store::saving::SymbolSetRecord,
    types::{
        event::AnyEvent, exception_properties::ExceptionProperties, Exception, ExceptionList,
        Stacktrace,
    },
};
use insta::assert_json_snapshot;
use mockall::predicate;
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
use reqwest::StatusCode;
use serde::{de::DeserializeOwned, Deserialize};
use serde_json::json;
use sqlx::PgPool;
use uuid::Uuid;

use crate::utils::MockS3Client;

mod utils;

const STORAGE_BUCKET: &str = "test-bucket";

// Test helper functions to build test data using cymbal types

fn make_event(exceptions: Vec<Exception>) -> AnyEvent {
    make_event_with_options(exceptions, None, Some(false))
}

fn make_event_with_options(
    exceptions: Vec<Exception>,
    fingerprint: Option<&str>,
    handled: Option<bool>,
) -> AnyEvent {
    let mut properties = json!({
        "$exception_list": exceptions,
        // Always set handled to avoid serialization issues with None -> null
        "$exception_handled": handled.unwrap_or(false),
    });

    if let Some(fp) = fingerprint {
        properties["$exception_fingerprint"] = json!(fp);
    }

    AnyEvent {
        uuid: Uuid::now_v7(),
        event: "$exception".to_string(),
        team_id: 1,
        timestamp: "2024-01-01T00:00:00Z".to_string(),
        properties,
        others: HashMap::new(),
    }
}

fn make_exception(exception_type: &str, message: &str) -> Exception {
    Exception {
        exception_id: None,
        exception_type: exception_type.to_string(),
        exception_message: message.to_string(),
        mechanism: None,
        module: None,
        thread_id: None,
        stack: None,
    }
}

fn make_exception_with_stack(exception_type: &str, message: &str, frames: Vec<Frame>) -> Exception {
    Exception {
        exception_id: None,
        exception_type: exception_type.to_string(),
        exception_message: message.to_string(),
        mechanism: None,
        module: None,
        thread_id: None,
        stack: Some(Stacktrace::Resolved { frames }),
    }
}

fn make_frame_js(name: &str) -> Frame {
    Frame {
        frame_id: FrameId::new(Uuid::now_v7().to_string(), 1, 0),
        mangled_name: name.to_string(),
        resolved_name: Some(name.to_string()),
        source: None,
        line: None,
        column: None,
        module: None,
        in_app: true,
        resolved: true,
        lang: "javascript".to_string(),
        resolve_failure: None,
        synthetic: false,
        suspicious: false,
        junk_drawer: None,
        code_variables: None,
        context: None,
        release: None,
    }
}

fn make_frame_ts(name: &str) -> Frame {
    Frame {
        frame_id: FrameId::new(Uuid::now_v7().to_string(), 1, 0),
        mangled_name: name.to_string(),
        resolved_name: Some(name.to_string()),
        source: None,
        line: None,
        column: None,
        module: None,
        in_app: true,
        resolved: true,
        lang: "typescript".to_string(),
        resolve_failure: None,
        synthetic: false,
        suspicious: false,
        junk_drawer: None,
        code_variables: None,
        context: None,
        release: None,
    }
}

fn frame_at(mut frame: Frame, source: &str, line: u32, column: u32) -> Frame {
    frame.source = Some(source.to_string());
    frame.line = Some(line);
    frame.column = Some(column);
    frame
}

// Response structs

#[derive(Deserialize)]
#[serde(untagged)]
enum ResponseItem {
    #[serde(rename_all = "PascalCase")]
    Ok { ok: AnyEvent },
    #[serde(rename_all = "PascalCase")]
    Err { err: serde_json::Value },
}

#[derive(Deserialize)]
struct SuccessResponse(Vec<ResponseItem>);

impl SuccessResponse {
    fn take_properties(self) -> ExceptionProperties {
        let item = self.0.first().expect("Should have at least one event");
        match item {
            ResponseItem::Ok { ok: event } => serde_json::from_value(event.properties.clone())
                .expect("Should deserialize properties"),
            ResponseItem::Err { err: e } => {
                panic!("Expected Ok event, got Err: {:?}", e);
            }
        }
    }

    fn first_event(&self) -> &AnyEvent {
        let item = self.0.first().expect("Should have at least one event");
        match item {
            ResponseItem::Ok { ok: event } => event,
            ResponseItem::Err { err: e } => {
                panic!("Expected Ok event, got Err: {:?}", e);
            }
        }
    }

    fn first_error(&self) -> &serde_json::Value {
        let item = self.0.first().expect("Should have at least one event");
        match item {
            ResponseItem::Err { err: e } => e,
            ResponseItem::Ok { ok: _ } => {
                panic!("Expected Err event, got Ok");
            }
        }
    }
}

// Test helper

struct TestHarness {
    db: PgPool,
}

impl TestHarness {
    fn new(db: PgPool) -> Self {
        Self { db }
    }

    fn create_s3_mock() -> MockS3Client {
        let mut s3_client = MockS3Client::new();
        s3_client
            .expect_ping_bucket()
            .with(predicate::eq(STORAGE_BUCKET.to_string()))
            .returning(|_| Ok(()));
        s3_client
    }

    async fn post_events<T: DeserializeOwned>(&self, events: Vec<AnyEvent>) -> (StatusCode, T) {
        utils::get_response(
            self.db.clone(),
            STORAGE_BUCKET.to_string(),
            || {
                Request::builder()
                    .method("POST")
                    .header("content-type", "application/json")
                    .uri("/process")
                    .body(Body::from(serde_json::to_vec(&events).unwrap()))
                    .unwrap()
            },
            Arc::new(Self::create_s3_mock()),
        )
        .await
    }

    async fn post_event<T: DeserializeOwned>(&self, event: &AnyEvent) -> (StatusCode, T) {
        self.post_events(vec![event.clone()]).await
    }

    async fn post_raw_string(&self, json: &[u8]) -> (StatusCode, String) {
        utils::get_raw_response(
            self.db.clone(),
            STORAGE_BUCKET.to_string(),
            || {
                Request::builder()
                    .method("POST")
                    .header("content-type", "application/json")
                    .uri("/process")
                    .body(Body::from(json.to_vec()))
                    .unwrap()
            },
            Arc::new(Self::create_s3_mock()),
        )
        .await
    }

    async fn suppress_issue(&self, issue_id: Uuid) {
        sqlx::query("UPDATE posthog_errortrackingissue SET status = 'suppressed' WHERE id = $1")
            .bind(issue_id)
            .execute(&self.db)
            .await
            .expect("Should update issue status");
    }

    async fn get_issue_id(&self) -> Uuid {
        let row: (Uuid,) =
            sqlx::query_as("SELECT id FROM posthog_errortrackingissue WHERE team_id = 1")
                .fetch_one(&self.db)
                .await
                .expect("Issue should exist");
        row.0
    }

    async fn post_event_with_s3<T: DeserializeOwned>(
        &self,
        event: &AnyEvent,
        s3_client: Arc<MockS3Client>,
    ) -> (StatusCode, T) {
        utils::get_response(
            self.db.clone(),
            STORAGE_BUCKET.to_string(),
            || {
                Request::builder()
                    .method("POST")
                    .header("content-type", "application/json")
                    .uri("/process")
                    .body(Body::from(serde_json::to_vec(&vec![event]).unwrap()))
                    .unwrap()
            },
            s3_client,
        )
        .await
    }
}

// Helper to load static event files
fn load_static_event(filename: &str) -> AnyEvent {
    let path = format!("tests/static/events/{}.json", filename);
    let content = fs::read_to_string(&path).unwrap_or_else(|_| panic!("Failed to read {}", path));
    serde_json::from_str(&content).unwrap_or_else(|_| panic!("Failed to parse {}", path))
}

// Helper to load sourcemap from static files
fn get_sourcemap(chunk_id: &str) -> Result<Option<Vec<u8>>, UnhandledError> {
    let Ok(minified_source) = fs::read_to_string(format!("tests/static/sourcemaps/{chunk_id}.js"))
    else {
        return Ok(None);
    };

    let Ok(sourcemap) = fs::read_to_string(format!("tests/static/sourcemaps/{chunk_id}.js.map"))
    else {
        return Ok(None);
    };

    let symbol_data = write_symbol_data(SourceAndMap {
        minified_source,
        sourcemap,
    })
    .map_err(|e| UnhandledError::Other(e.to_string()))?;

    Ok(Some(symbol_data))
}

// Helper to insert symbol set records in the database
async fn insert_symbol_set_record(db: &PgPool, team_id: i32, chunk_id: &str) {
    let mut record = SymbolSetRecord {
        id: Uuid::now_v7(),
        team_id,
        set_ref: chunk_id.to_string(),
        storage_ptr: Some(chunk_id.to_string()),
        failure_reason: None,
        created_at: Utc::now(),
        content_hash: Some("fake-hash".to_string()),
        last_used: Some(Utc::now()),
    };
    record.save(db).await.expect("Failed to insert record");
}

// Helper to extract exception list from response
fn extract_exception_list(response: &SuccessResponse) -> ExceptionList {
    let event = response.first_event();
    let props: ExceptionProperties =
        serde_json::from_value(event.properties.clone()).expect("Should deserialize properties");
    props.exception_list
}

// Tests

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn invalid_request_returns_400(db: PgPool) {
    let harness = TestHarness::new(db);

    let (status, body) = harness.post_raw_string(b"{}").await;

    assert!(status.is_client_error());
    assert!(
        body.contains("invalid type") || body.contains("expected"),
        "Expected deserialization error, got: {}",
        body
    );
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn empty_exception_list_returns_event_with_error(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = make_event(vec![]);

    let (status, body): (_, SuccessResponse) = harness.post_event(&input).await;

    // Empty exception list returns success with error embedded in the event
    assert!(status.is_success());
    assert_eq!(body.0.len(), 1);
    let event = body.first_event();
    let errors: Vec<String> =
        serde_json::from_value(event.properties.get("$cymbal_errors").unwrap().clone()).unwrap();
    assert!(errors.iter().any(|e| e.contains("Empty exception list")));
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn creates_issue_with_fingerprint(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = make_event(vec![make_exception_with_stack(
        "Error",
        "test error message",
        vec![frame_at(make_frame_js("handleClick"), "src/app.js", 42, 10)],
    )]);

    let (status, body): (_, SuccessResponse) = harness.post_event(&input).await;

    assert!(status.is_success(), "Expected success, got {:?}", status);
    let event: ExceptionProperties = body.take_properties();
    assert!(event.fingerprint.is_some());
    assert_eq!(event.exception_types.unwrap(), vec!["Error".to_string()]);
    assert_eq!(
        event.exception_messages.unwrap(),
        vec!["test error message".to_string()]
    );
    assert_eq!(harness.get_issue_id().await, event.issue_id.unwrap());
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn uses_client_fingerprint_override(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = make_event_with_options(
        vec![make_exception("TypeError", "cannot read property")],
        Some("custom-fingerprint"),
        None,
    );

    let (status, body): (_, SuccessResponse) = harness.post_event(&input).await;

    let event = body.take_properties();
    assert!(status.is_success());
    assert_eq!(event.fingerprint.unwrap(), "custom-fingerprint".to_string());
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn same_fingerprint_returns_same_issue(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = make_event(vec![make_exception_with_stack(
        "Error",
        "test error",
        vec![frame_at(make_frame_js("foo"), "src/test.js", 10, 5)],
    )]);

    let (_, body1): (_, SuccessResponse) = harness.post_event(&input).await;
    let (_, body2): (_, SuccessResponse) = harness.post_event(&input).await;
    let event1 = body1.take_properties();
    let event2 = body2.take_properties();

    assert_eq!(event1.fingerprint, event2.fingerprint);
    assert_eq!(event1.issue_id, event2.issue_id);
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn suppressed_issue_returns_suppressed_response(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = make_event(vec![make_exception("SuppressedError", "will suppress")]);

    let (_, created): (_, SuccessResponse) = harness.post_event(&input).await;
    let body = created.take_properties();
    let issue_id = body.issue_id.unwrap();
    harness.suppress_issue(issue_id).await;

    let (status, body): (_, SuccessResponse) = harness.post_event(&input).await;

    assert!(status.is_success());
    // exception should be returned as suppressed error
    assert_eq!(body.0.len(), 1);
    let err = body.first_error();
    assert!(err.to_string().contains("Suppressed"));
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn extracts_metadata_from_exceptions(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = make_event_with_options(
        vec![make_exception_with_stack(
            "TypeError",
            "Cannot read property 'foo' of undefined",
            vec![
                frame_at(
                    make_frame_ts("handleClick"),
                    "src/components/Button.tsx",
                    42,
                    10,
                ),
                frame_at(make_frame_ts("onClick"), "src/App.tsx", 100, 5),
            ],
        )],
        None,
        Some(true),
    );

    let (status, body): (_, SuccessResponse) = harness.post_event(&input).await;

    assert!(status.is_success());
    let event = body.take_properties();

    assert_eq!(event.exception_types.unwrap(), vec!["TypeError"]);
    assert_eq!(
        event.exception_messages.unwrap(),
        vec!["Cannot read property 'foo' of undefined"]
    );
    assert!(event.exception_handled.unwrap());
    assert!(event
        .exception_sources
        .clone()
        .unwrap()
        .contains(&"src/components/Button.tsx".to_string()));
    assert!(event
        .exception_sources
        .clone()
        .unwrap()
        .contains(&"src/App.tsx".to_string()));
    assert!(event
        .exception_functions
        .clone()
        .unwrap()
        .contains(&"handleClick".to_string()));
    assert!(event
        .exception_functions
        .clone()
        .unwrap()
        .contains(&"onClick".to_string()));
}

// Frame resolution tests

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn resolves_javascript_raw_frames(db: PgPool) {
    let harness = TestHarness::new(db);
    let event = load_static_event("javascript");

    let (status, body): (_, SuccessResponse) = harness.post_event(&event).await;

    assert!(status.is_success());
    let exception_list = extract_exception_list(&body);
    assert_json_snapshot!(exception_list.0, {
        "[].id" => "REDACTED",
    });
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn resolves_python_raw_frames(db: PgPool) {
    let harness = TestHarness::new(db);
    let event = load_static_event("python");

    let (status, body): (_, SuccessResponse) = harness.post_event(&event).await;

    assert!(status.is_success());
    let exception_list = extract_exception_list(&body);
    assert_json_snapshot!(exception_list.0, {
        "[].id" => "REDACTED",
    });
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn resolves_javascript_with_sourcemaps(db: PgPool) {
    let harness = TestHarness::new(db.clone());
    let event = load_static_event("javascript_chunk_id");

    // Set up symbol set record in database
    insert_symbol_set_record(&db, 1, "1234").await;

    // Set up S3 mock to return sourcemap
    let mut s3_client = MockS3Client::new();
    s3_client
        .expect_ping_bucket()
        .with(predicate::eq(STORAGE_BUCKET.to_string()))
        .returning(|_| Ok(()));
    s3_client
        .expect_get()
        .with(
            predicate::eq(STORAGE_BUCKET.to_string()),
            predicate::eq("1234"),
        )
        .returning(|_, chunk_id| get_sourcemap(chunk_id));

    let (status, body): (_, SuccessResponse) = harness
        .post_event_with_s3(&event, Arc::new(s3_client))
        .await;

    assert!(status.is_success());
    let exception_list = extract_exception_list(&body);
    assert_json_snapshot!(exception_list.0, {
        "[].id" => "REDACTED",
    });
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn handles_missing_sourcemap(db: PgPool) {
    let harness = TestHarness::new(db);
    let event = load_static_event("javascript_chunk_id_2");

    // No sourcemap record in database, so resolution will fail gracefully
    let (status, body): (_, SuccessResponse) = harness.post_event(&event).await;

    assert!(status.is_success());
    let exception_list = extract_exception_list(&body);
    assert_json_snapshot!(exception_list.0, {
        "[].id" => "REDACTED",
    });
}
