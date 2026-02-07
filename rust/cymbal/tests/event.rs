use axum::{body::Body, http::Request};
use cymbal::{issue_resolution::IssueStatus, types::OutputErrProps};
use mockall::predicate;
use reqwest::StatusCode;
use serde::{de::DeserializeOwned, Deserialize, Serialize};

use sqlx::PgPool;
use std::sync::Arc;
use uuid::Uuid;

use crate::utils::MockS3Client;

mod utils;

const STORAGE_BUCKET: &str = "test-bucket";

// Test input structures

#[derive(Debug, Clone, Serialize)]
struct TestEventInput {
    uuid: Uuid,
    timestamp: String,
    team_id: i32,
    #[serde(rename = "$exception_list")]
    exception_list: Vec<TestException>,
    #[serde(
        rename = "$exception_fingerprint",
        skip_serializing_if = "Option::is_none"
    )]
    fingerprint: Option<String>,
    #[serde(rename = "$exception_handled", skip_serializing_if = "Option::is_none")]
    handled: Option<bool>,
}

#[derive(Debug, Clone, Serialize)]
struct TestException {
    #[serde(rename = "type")]
    exception_type: String,
    #[serde(rename = "value")]
    exception_message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    stacktrace: Option<TestStacktrace>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type", rename_all = "lowercase")]
enum TestStacktrace {
    Resolved { frames: Vec<TestFrame> },
}

#[derive(Debug, Clone, Serialize)]
struct TestFrame {
    raw_id: String,
    mangled_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    resolved_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    source: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    line: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    column: Option<u32>,
    in_app: bool,
    resolved: bool,
    lang: String,
}

impl TestEventInput {
    fn new(exceptions: Vec<TestException>) -> Self {
        Self {
            uuid: Uuid::now_v7(),
            timestamp: "2024-01-01T00:00:00Z".to_string(),
            team_id: 1,
            exception_list: exceptions,
            fingerprint: None,
            handled: None,
        }
    }

    fn with_fingerprint(mut self, fingerprint: &str) -> Self {
        self.fingerprint = Some(fingerprint.to_string());
        self
    }

    fn with_handled(mut self, handled: bool) -> Self {
        self.handled = Some(handled);
        self
    }
}

impl TestException {
    fn new(exception_type: &str, message: &str) -> Self {
        Self {
            exception_type: exception_type.to_string(),
            exception_message: message.to_string(),
            stacktrace: None,
        }
    }

    fn with_stack(mut self, frames: Vec<TestFrame>) -> Self {
        self.stacktrace = Some(TestStacktrace::Resolved { frames });
        self
    }
}

impl TestFrame {
    fn js(name: &str) -> Self {
        Self {
            raw_id: format!("{}/0", Uuid::now_v7()),
            mangled_name: name.to_string(),
            resolved_name: Some(name.to_string()),
            source: None,
            line: None,
            column: None,
            in_app: true,
            resolved: true,
            lang: "javascript".to_string(),
        }
    }

    fn ts(name: &str) -> Self {
        Self {
            raw_id: format!("{}/0", Uuid::now_v7()),
            mangled_name: name.to_string(),
            resolved_name: Some(name.to_string()),
            source: None,
            line: None,
            column: None,
            in_app: true,
            resolved: true,
            lang: "typescript".to_string(),
        }
    }

    fn at(mut self, source: &str, line: u32, column: u32) -> Self {
        self.source = Some(source.to_string());
        self.line = Some(line);
        self.column = Some(column);
        self
    }
}

// Response structs

#[derive(Deserialize)]
struct ErrorResponse {
    error: String,
}

#[derive(Debug, Deserialize)]
struct SuccessResponse {
    issue_id: Uuid,
    issue_status: IssueStatus,
    event: Option<OutputErrProps>,
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

    async fn post<T: DeserializeOwned>(&self, body: Vec<u8>) -> (StatusCode, T) {
        utils::get_response(
            self.db.clone(),
            STORAGE_BUCKET.to_string(),
            || {
                Request::builder()
                    .method("POST")
                    .header("content-type", "application/json")
                    .uri("/1/event/process")
                    .body(Body::from(body.clone()))
                    .unwrap()
            },
            Arc::new(Self::create_s3_mock()),
        )
        .await
    }

    async fn post_event<T: DeserializeOwned>(&self, input: &TestEventInput) -> (StatusCode, T) {
        self.post(serde_json::to_vec(input).unwrap()).await
    }

    async fn post_event_to_team<T: DeserializeOwned>(
        &self,
        input: &TestEventInput,
        path_team_id: i32,
    ) -> (StatusCode, T) {
        utils::get_response(
            self.db.clone(),
            STORAGE_BUCKET.to_string(),
            || {
                Request::builder()
                    .method("POST")
                    .header("content-type", "application/json")
                    .uri(format!("/{}/event/process", path_team_id))
                    .body(Body::from(serde_json::to_vec(input).unwrap()))
                    .unwrap()
            },
            Arc::new(Self::create_s3_mock()),
        )
        .await
    }

    async fn post_raw_string(&self, json: &[u8]) -> (StatusCode, String) {
        utils::get_raw_response(
            self.db.clone(),
            STORAGE_BUCKET.to_string(),
            || {
                Request::builder()
                    .method("POST")
                    .header("content-type", "application/json")
                    .uri("/1/event/process")
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
}

// Tests

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn invalid_request_returns_400(db: PgPool) {
    let harness = TestHarness::new(db);

    let (status, body) = harness.post_raw_string(b"{}").await;

    assert!(status.is_client_error());
    assert!(
        body.contains("missing field"),
        "Expected 'missing field' error, got: {}",
        body
    );
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn empty_exception_list_returns_400(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = TestEventInput::new(vec![]);

    let (status, body): (_, ErrorResponse) = harness.post_event(&input).await;

    assert!(status.is_client_error());
    assert_eq!(body.error, "Exception list cannot be empty");
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn team_id_mismatch_returns_400(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = TestEventInput::new(vec![TestException::new("Error", "test error")]);

    // Post to team 2 in URL but team_id 1 in payload
    let (status, body): (_, ErrorResponse) = harness.post_event_to_team(&input, 2).await;

    assert!(status.is_client_error());
    assert!(body.error.contains("Team ID mismatch"));
    assert!(body.error.contains("path team_id 2"));
    assert!(body.error.contains("payload team_id 1"));
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn creates_issue_with_fingerprint(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = TestEventInput::new(vec![TestException::new("Error", "test error message")
        .with_stack(vec![TestFrame::js("handleClick").at("src/app.js", 42, 10)])]);

    let (status, body): (_, SuccessResponse) = harness.post_event(&input).await;

    assert!(status.is_success(), "Expected success, got {:?}", status);
    let event = body.event.expect("Should have an event");
    assert!(!event.fingerprint.is_empty());
    assert_eq!(event.types, vec!["Error"]);
    assert_eq!(event.values, vec!["test error message"]);
    assert_eq!(harness.get_issue_id().await, body.issue_id);
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn uses_client_fingerprint_override(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = TestEventInput::new(vec![TestException::new(
        "TypeError",
        "cannot read property",
    )])
    .with_fingerprint("custom-fingerprint");

    let (status, body): (_, SuccessResponse) = harness.post_event(&input).await;

    assert!(status.is_success());
    assert_eq!(
        body.event.expect("Should have an event").fingerprint,
        "custom-fingerprint"
    );
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn same_fingerprint_returns_same_issue(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = TestEventInput::new(vec![TestException::new("Error", "test error")
        .with_stack(vec![TestFrame::js("foo").at("src/test.js", 10, 5)])]);

    let (_, body1): (_, SuccessResponse) = harness.post_event(&input).await;
    let (_, body2): (_, SuccessResponse) = harness.post_event(&input).await;
    let event1 = body1.event.expect("Should have an event");
    let event2 = body2.event.expect("Should have an event");
    assert_eq!(event1.fingerprint, event2.fingerprint);
    assert_eq!(body1.issue_id, body2.issue_id);
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn suppressed_issue_returns_suppressed_response(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = TestEventInput::new(vec![TestException::new("SuppressedError", "will suppress")]);

    let (_, created): (_, SuccessResponse) = harness.post_event(&input).await;
    harness.suppress_issue(created.issue_id).await;

    let (status, body): (_, SuccessResponse) = harness.post_event(&input).await;

    assert!(status.is_success());
    assert_eq!(body.issue_status, IssueStatus::Suppressed);
    assert_eq!(body.issue_id, created.issue_id);
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn extracts_metadata_from_exceptions(db: PgPool) {
    let harness = TestHarness::new(db);
    let input = TestEventInput::new(vec![TestException::new(
        "TypeError",
        "Cannot read property 'foo' of undefined",
    )
    .with_stack(vec![
        TestFrame::ts("handleClick").at("src/components/Button.tsx", 42, 10),
        TestFrame::ts("onClick").at("src/App.tsx", 100, 5),
    ])])
    .with_handled(true);

    let (status, body): (_, SuccessResponse) = harness.post_event(&input).await;

    assert!(status.is_success());
    let event = body.event.expect("Should have an event");
    assert_eq!(event.types, vec!["TypeError"]);
    assert_eq!(
        event.values,
        vec!["Cannot read property 'foo' of undefined"]
    );
    assert!(event.handled);
    assert!(event
        .sources
        .contains(&"src/components/Button.tsx".to_string()));
    assert!(event.sources.contains(&"src/App.tsx".to_string()));
    assert!(event.functions.contains(&"handleClick".to_string()));
    assert!(event.functions.contains(&"onClick".to_string()));
}
