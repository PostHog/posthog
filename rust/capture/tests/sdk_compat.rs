use assert_json_diff::assert_json_matches_no_panic;
use async_trait::async_trait;
use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestClient;

use capture::api::{CaptureError, CaptureResponse, CaptureResponseCode};
use capture::config::CaptureMode;
use capture::router::router;
use capture::sinks::Event;
use capture::time::TimeSource;
use capture::v0_request::{DataType, Compression, ProcessingContext, ProcessedEvent};

//use chrono::Utc;
use common_redis::MockRedisClient;
use health::HealthRegistry;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, QUOTA_LIMITER_CACHE_KEY};
use limiters::token_dropper::TokenDropper;
use serde::Deserialize;
use serde_json::{from_str, from_slice, json, Value};
use time::OffsetDateTime;
use time::format_description::well_known::{Iso8601, Rfc3339};

use std::fs::{read, File};
use std::path::Path;
use std::io::Result;
use std::sync::{Arc, Mutex};
use std::time::Duration;

#[derive(Debug, Deserialize)]
struct RequestDump {
    title: String,
    path: String,
    method: String,
    content_encoding: String,
    content_type: String,
    ip: String,
    now: String,
    body: String,
    output: Vec<serde_json::Value>,
    #[serde(default)] // default = false
    historical_migration: bool,
}

#[derive(Debug, Deserialize)]
struct TestMetadata {
    title: String,
    path: String,
    method: String,
    content_encoding: Option<String>,
    content_type: Option<String>,
    ip: Option<String>,
    lib_version: Option<String>,
    sent_at: Option<OffsetDateTime>,
    compression: Compression,
    historical_migration: bool,
}

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

// A well-formed payload is UTF-8 JSON:
// - A single event object
// - A batch object including a list of events and top-level metadata fields
//
// This payload can be base64 or urlencoded. It can be the value of the "data" element
// of a form or the direct content of the request body. This structure can, in turn, be
// GZIP or LZ64 compressed.
//
fn load_request_payload(base_path: &Path) -> Result<Vec<u8>> {
    // TODO(eli): consider loading this UNENCRYPTED and for each test case, wrapping/compressing as needed for the test at hand?
    let resolved_path = base_path.join("payload.bin");
    read(resolved_path).expect("loading encoded payload")
}

fn load_metadata(base_path: &Path) -> io::Result<ProcessingContext> {
    let resolved_path = base_path.join("metadata.json");
    let buf = read(resolved_path).expect("loading encoded payload");
    serde_json::from_slice::<TestMetadata>(buf)
}

fn setup_capture_router(fixed_time: String) -> Router {
    let liveness = HealthRegistry::new("dummy");
    let sink = MemorySink::default();
    let timesource = FixedTime { time: fixed_time };

    let redis = Arc::new(MockRedisClient::new());
    let billing_limiter = RedisLimiter::new(
        Duration::from_secs(60 * 60 * 24 * 7),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::Events,
        ServiceName::Capture,
    )
    .expect("failed to create billing limiter");

    // disable historical rerouting for this test,
    // since we use fixture files with old timestamps
    let enable_historical_rerouting = false;
    let historical_rerouting_threshold_days = 1_i64;
    let historical_tokens_keys = None;
    let is_mirror_deploy = false; // TODO: remove after migration to 100% capture-rs backend
    let base64_detect_percent = 0.0_f32;

    return router(
        timesource,
        liveness.clone(),
        sink.clone(),
        redis,
        billing_limiter,
        TokenDropper::default(),
        false,
        CaptureMode::Events,
        None,
        25 * 1024 * 1024,
        enable_historical_rerouting,
        historical_rerouting_threshold_days,
        historical_tokens_keys,
        is_mirror_deploy,
        base64_detect_percent,
    )
}