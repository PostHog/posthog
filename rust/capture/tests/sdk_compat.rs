use assert_json_diff::assert_json_matches_no_panic;
use async_trait::async_trait;
use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestClient;

use capture::{
    api::{CaptureError, CaptureResponse, CaptureResponseCode},
    config::CaptureMode,
    router::router,
    sinks::Event,
    time::TimeSource,
    v0_request::{Compression, DataType, ProcessedEvent, ProcessingContext},
};

//use chrono::Utc;
use common_redis::MockRedisClient;
use health::HealthRegistry;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, QUOTA_LIMITER_CACHE_KEY};
use limiters::token_dropper::TokenDropper;
use serde::Deserialize;
use serde_json::{from_slice, from_str, json, Value};
use time::format_description::well_known::{Iso8601, Rfc3339};
use time::OffsetDateTime;

use std::fs::{read, File};
use std::path::Path;
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
    now: Option<OffsetDateTime>,
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
// This payload can optionally be base64 or urlencoded. It can
// be the value of the "data" element of a POST form or the direct
// content of the request body. This structure can, in turn, be
// GZIP or LZ64 compressed.
//
// in this case, we load a generic JSON event payload for each test,
// and let that test case additionally compress/encode the data
// according to the behavior we're exercising.
fn load_request_payload(target_path: &Path) -> Vec<u8> {
    let err_msg = format!("loading test payload: {:?}", target_path);
    read(target_path).expect(&err_msg)
}

fn load_metadata(target_path: &Path) -> TestMetadata {
    let read_err_msg = format!("loading test meta payload: {:?}", target_path);
    let buf = read(target_path).expect(&read_err_msg);
    let parse_err_msg = format!("parsing test meta payload: {:?}", target_path);
    from_slice::<TestMetadata>(&buf).expect(&parse_err_msg)
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
    .expect("failed to create test billing limiter");

    // disable historical rerouting for this test,
    // since we use fixture files with old timestamps
    let enable_historical_rerouting = false;
    let historical_rerouting_threshold_days = 1_i64;
    let historical_tokens_keys = None;
    let is_mirror_deploy = false; // TODO: remove after migration to 100% capture-rs backend
    let base64_detect_percent = 0.0_f32;

    router(
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
