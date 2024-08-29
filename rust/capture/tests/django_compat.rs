use assert_json_diff::assert_json_matches_no_panic;
use async_trait::async_trait;
use axum::http::StatusCode;
use axum_test_helper::TestClient;
use base64::engine::general_purpose;
use base64::Engine;
use capture::api::{CaptureError, CaptureResponse, CaptureResponseCode, DataType, ProcessedEvent};
use capture::config::CaptureMode;
use capture::limiters::billing::BillingLimiter;
use capture::redis::MockRedisClient;
use capture::router::router;
use capture::sinks::Event;
use capture::time::TimeSource;
use health::HealthRegistry;
use serde::Deserialize;
use serde_json::{json, Value};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::sync::{Arc, Mutex};
use time::format_description::well_known::{Iso8601, Rfc3339};
use time::{Duration, OffsetDateTime};

#[derive(Debug, Deserialize)]
struct RequestDump {
    path: String,
    method: String,
    content_encoding: String,
    content_type: String,
    ip: String,
    now: String,
    body: String,
    output: Vec<Value>,
    #[serde(default)] // default = false
    historical_migration: bool,
}

static REQUESTS_DUMP_FILE_NAME: &str = "tests/requests_dump.jsonl";

#[derive(Clone)]
pub struct FixedTime {
    pub time: String,
}

impl TimeSource for FixedTime {
    fn current_time(&self) -> String {
        self.time.to_string()
    }
}

#[derive(Clone, Default)]
struct MemorySink {
    events: Arc<Mutex<Vec<ProcessedEvent>>>,
}

impl MemorySink {
    fn len(&self) -> usize {
        self.events.lock().unwrap().len()
    }

    fn events(&self) -> Vec<ProcessedEvent> {
        self.events.lock().unwrap().clone()
    }
}

#[async_trait]
impl Event for MemorySink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        self.events.lock().unwrap().push(event);
        Ok(())
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.events.lock().unwrap().extend_from_slice(&events);
        Ok(())
    }
}

#[tokio::test]
async fn it_matches_django_capture_behaviour() -> anyhow::Result<()> {
    let file = File::open(REQUESTS_DUMP_FILE_NAME)?;
    let reader = BufReader::new(file);
    let liveness = HealthRegistry::new("dummy");

    let mut mismatches = 0;

    for (line_number, line_contents) in reader.lines().enumerate() {
        let line_contents = line_contents?;
        if line_contents.starts_with('#') {
            // Skip comment lines
            continue;
        }
        let case: RequestDump = serde_json::from_str(&line_contents)?;
        let raw_body = general_purpose::STANDARD.decode(&case.body)?;
        assert_eq!(
            case.method, "POST",
            "update code to handle method {}",
            case.method
        );

        let sink = MemorySink::default();
        let timesource = FixedTime { time: case.now };

        let redis = Arc::new(MockRedisClient::new());
        let billing = BillingLimiter::new(Duration::weeks(1), redis.clone(), None)
            .expect("failed to create billing limiter");

        let app = router(
            timesource,
            liveness.clone(),
            sink.clone(),
            redis,
            billing,
            false,
            CaptureMode::Events,
            None,
        );

        let client = TestClient::new(app);
        let mut req = client.post(&case.path).body(raw_body);
        if !case.content_encoding.is_empty() {
            req = req.header("Content-encoding", case.content_encoding);
        }
        if !case.content_type.is_empty() {
            req = req.header("Content-type", case.content_type);
        }
        if !case.ip.is_empty() {
            req = req.header("X-Forwarded-For", case.ip);
        }

        let res = req.send().await;
        assert_eq!(
            res.status(),
            StatusCode::OK,
            "line {} rejected: {}",
            line_number,
            res.text().await
        );
        assert_eq!(
            Some(CaptureResponse {
                status: CaptureResponseCode::Ok,
                quota_limited: None,
            }),
            res.json().await
        );
        assert_eq!(
            sink.len(),
            case.output.len(),
            "event count mismatch on line {}",
            line_number
        );

        for (event_number, (message, expected)) in
            sink.events().iter().zip(case.output.iter()).enumerate()
        {
            // Ensure the data type matches
            if case.historical_migration {
                assert_eq!(DataType::AnalyticsHistorical, message.data_type);
            } else {
                assert_eq!(DataType::AnalyticsMain, message.data_type);
            }

            // Normalizing the expected event to align with known django->rust inconsistencies
            let mut expected = expected.clone();
            if let Some(value) = expected.get_mut("sent_at") {
                // Default ISO format is different between python and rust, both are valid
                // Parse and re-print the value before comparison
                let raw_value = value.as_str().expect("sent_at field is not a string");
                if raw_value.is_empty() {
                    *value = Value::Null
                } else {
                    let sent_at =
                        OffsetDateTime::parse(value.as_str().expect("empty"), &Iso8601::DEFAULT)
                            .expect("failed to parse expected sent_at");
                    *value = Value::String(sent_at.format(&Rfc3339)?)
                }
            }
            if let Some(expected_data) = expected.get_mut("data") {
                // Data is a serialized JSON map. Unmarshall both and compare them,
                // instead of expecting the serialized bytes to be equal
                let mut expected_props: Value =
                    serde_json::from_str(expected_data.as_str().expect("not str"))?;
                if let Some(object) = expected_props.as_object_mut() {
                    // toplevel fields added by posthog-node that plugin-server will ignore anyway
                    object.remove("type");
                    object.remove("library");
                    object.remove("library_version");
                }

                let found_props: Value = serde_json::from_str(&message.data)?;
                let match_config =
                    assert_json_diff::Config::new(assert_json_diff::CompareMode::Strict);
                if let Err(e) =
                    assert_json_matches_no_panic(&expected_props, &found_props, match_config)
                {
                    println!(
                        "data field mismatch at line {}, event {}: {}",
                        line_number, event_number, e
                    );
                    mismatches += 1;
                } else {
                    *expected_data = json!(&message.data)
                }
            }

            if let Some(object) = expected.as_object_mut() {
                // site_url is unused in the pipeline now, let's drop it
                object.remove("site_url");

                // Remove sent_at field if empty: Rust will skip marshalling it
                if let Some(None) = object.get("sent_at").map(|v| v.as_str()) {
                    object.remove("sent_at");
                }
            }

            let match_config = assert_json_diff::Config::new(assert_json_diff::CompareMode::Strict);
            if let Err(e) =
                assert_json_matches_no_panic(&json!(expected), &json!(message), match_config)
            {
                println!(
                    "record mismatch at line {}, event {}: {}",
                    line_number + 1,
                    event_number,
                    e
                );
                mismatches += 1;
            }
        }
    }
    assert_eq!(0, mismatches, "some events didn't match");
    Ok(())
}
