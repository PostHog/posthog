#[path = "common/integration_utils.rs"]
mod integration_utils;

use std::io::Write;
use std::sync::{Arc, Mutex};

use axum_test_helper::TestClient;
use capture::config::CaptureMode;
use integration_utils::build_router_for_mode;
use rstest::rstest;
use serde_json::json;
use tracing_subscriber::filter::LevelFilter;
use tracing_subscriber::fmt::format::FmtSpan;
use tracing_subscriber::fmt::MakeWriter;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::Layer;

const COOKIE_VALUE: &str = "session=cookie-value-not-for-logs";
const USER_AGENT: &str = "request-logging-test-agent/1.0";

#[derive(Clone, Default)]
struct LogBuffer(Arc<Mutex<Vec<u8>>>);

impl LogBuffer {
    fn contents(&self) -> String {
        String::from_utf8(self.0.lock().unwrap().clone()).unwrap()
    }
}

impl Write for LogBuffer {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

impl<'a> MakeWriter<'a> for LogBuffer {
    type Writer = LogBuffer;

    fn make_writer(&'a self) -> Self::Writer {
        self.clone()
    }
}

// Mirrors the production JSON log layer in main.rs, and also emits span close
// events so every field recorded on a span shows up in the output.
fn json_log_layer(buffer: LogBuffer) -> impl tracing::Subscriber {
    tracing_subscriber::registry().with(
        tracing_subscriber::fmt::layer()
            .json()
            .flatten_event(true)
            .with_span_list(true)
            .with_current_span(true)
            .with_span_events(FmtSpan::CLOSE)
            .with_writer(buffer)
            .with_filter(LevelFilter::INFO),
    )
}

#[rstest]
#[case::analytics_event(
    CaptureMode::Events,
    "/e/",
    "application/json",
    json!({"token": "phc_request_logging", "event": "$pageview", "distinct_id": "user-1"}).to_string(),
    "handle_event_payload"
)]
#[case::recording(
    CaptureMode::Recordings,
    "/s/",
    "application/json",
    json!({
        "token": "phc_request_logging",
        "event": "$snapshot_items",
        "distinct_id": "user-1",
        "properties": {"$session_id": "session-1", "$window_id": "window-1", "$snapshot_items": []}
    }).to_string(),
    "handle_recording_payload"
)]
#[case::otel_traces(
    CaptureMode::Ai,
    "/i/v0/ai/otel",
    "application/x-protobuf",
    String::new(),
    "otel_handler"
)]
#[tokio::test]
async fn test_request_logs_omit_headers_outside_allowlist(
    #[case] mode: CaptureMode,
    #[case] path: &str,
    #[case] content_type: &str,
    #[case] body: String,
    #[case] expected_span: &str,
) {
    let buffer = LogBuffer::default();
    let _guard = tracing::subscriber::set_default(json_log_layer(buffer.clone()));

    let client = TestClient::new(build_router_for_mode(mode));
    client
        .post(path)
        .header("Content-Type", content_type)
        .header("User-Agent", USER_AGENT)
        .header("Cookie", COOKIE_VALUE)
        .header("Authorization", "Bearer phc_request_logging")
        .header("X-Forwarded-For", "127.0.0.1")
        .header("X-CAPTURE-DEBUG", "1")
        .body(body)
        .send()
        .await;

    let logs = buffer.contents();
    assert!(
        logs.contains(expected_span),
        "expected the {expected_span} span in the logs, got: {logs}"
    );
    assert!(
        !logs.contains("cookie-value-not-for-logs"),
        "cookie header value found in logs: {logs}"
    );
    assert!(
        !logs.contains("Bearer phc_request_logging"),
        "authorization header value found in logs: {logs}"
    );
}

#[tokio::test]
async fn test_debug_request_logs_keep_allowlisted_headers() {
    let buffer = LogBuffer::default();
    let _guard = tracing::subscriber::set_default(json_log_layer(buffer.clone()));

    let client = TestClient::new(build_router_for_mode(CaptureMode::Events));
    client
        .post("/e/")
        .header("Content-Type", "application/json")
        .header("User-Agent", USER_AGENT)
        .header("Cookie", COOKIE_VALUE)
        .header("X-Forwarded-For", "127.0.0.1")
        .header("X-CAPTURE-DEBUG", "1")
        .body(
            json!({"token": "phc_request_logging", "event": "$pageview", "distinct_id": "user-1"})
                .to_string(),
        )
        .send()
        .await;

    let logs = buffer.contents();
    let entering = logs
        .lines()
        .find(|line| line.contains("CHATTY: entering handle_event_payload"))
        .unwrap_or_else(|| panic!("expected a debug request log line, got: {logs}"));
    assert!(entering.contains(USER_AGENT), "{entering}");
    assert!(
        !entering.contains("cookie-value-not-for-logs"),
        "{entering}"
    );
}
