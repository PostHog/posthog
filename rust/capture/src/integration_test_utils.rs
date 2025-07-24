use std::fs::read;
use std::io::Write;
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use crate::{
    api::{CaptureError, CaptureResponse, CaptureResponseCode},
    config::CaptureMode,
    router::router,
    sinks::Event,
    time::TimeSource,
    v0_request::{DataType, ProcessedEvent},
};

use async_trait::async_trait;
use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestResponse;
use common_redis::MockRedisClient;
use flate2::write::GzEncoder;
use flate2::Compression;
use health::HealthRegistry;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, QUOTA_LIMITER_CACHE_KEY};
use limiters::token_dropper::TokenDropper;
use serde_json::{from_str, Number, Value};
use time::format_description::well_known::{Iso8601, Rfc3339};
use time::OffsetDateTime;

pub const DEFAULT_TEST_TIME: &str = "2025-07-01T11:00:00Z";

// we reuse the "raw" payload fixtures a lot, encoding/compressing them differently in different tests
pub const SINGLE_EVENT_JSON: &str = "single_event_payload.json";
pub const SINGLE_REPLAY_EVENT_JSON: &str = "single_replay_event_payload.json";
// the /engage/ endpoint is unique: this only accepts "unnamed" (no event.event attrib)
// events that are structured as "$identify" events
pub const SINGLE_ENGAGE_EVENT_JSON: &str = "single_engage_event_payload.json";
pub const BATCH_EVENTS_JSON: &str = "batch_events_payload.json";

pub struct FixedTime {
    pub time: String,
}

impl TimeSource for FixedTime {
    fn current_time(&self) -> String {
        self.time.to_string()
    }
}

#[derive(Clone, Default)]
pub struct MemorySink {
    events: Arc<Mutex<Vec<ProcessedEvent>>>,
}

impl MemorySink {
    pub fn events(&self) -> Vec<ProcessedEvent> {
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
pub fn load_request_payload(title: &str, target: &str) -> Vec<u8> {
    let path = Path::new("tests/fixtures").join(target);
    let err_msg = format!("loading req event payload for case: {}", title);
    read(path).expect(&err_msg)
}

pub fn setup_capture_router(mode: CaptureMode, fixed_time: &str) -> (Router, MemorySink) {
    let quota_resource_mode = match mode {
        CaptureMode::Events => QuotaResource::Events,
        CaptureMode::Recordings => QuotaResource::Recordings,
    };
    let liveness = HealthRegistry::new("dummy");
    let sink = MemorySink::default();
    let timesource = FixedTime {
        time: fixed_time.to_string(),
    };
    let redis = Arc::new(MockRedisClient::new());
    let billing_limiter = RedisLimiter::new(
        Duration::from_secs(60 * 60 * 24 * 7),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        quota_resource_mode,
        ServiceName::Capture,
    )
    .expect("failed to create test billing limiter");

    // disable historical rerouting for this test,
    // since we use fixture files with old timestamps
    let enable_historical_rerouting = false;
    let historical_rerouting_threshold_days = 1_i64;
    let historical_tokens_keys = None;
    let is_mirror_deploy = false; // TODO: remove after migration to 100% capture-rs backend
    let verbose_sample_percent = 0.0_f32;

    (
        router(
            timesource,
            liveness.clone(),
            sink.clone(),
            redis,
            billing_limiter,
            TokenDropper::default(),
            false,
            mode,
            None,
            25 * 1024 * 1024,
            enable_historical_rerouting,
            historical_rerouting_threshold_days,
            historical_tokens_keys,
            is_mirror_deploy,
            verbose_sample_percent,
        ),
        sink,
    )
}

// utility to compress capture payloads for testing
pub fn gzip_compress(title: &str, data: Vec<u8>) -> Vec<u8> {
    let err_msg = format!("failed to GZIP payload in case: {}", title);
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());

    encoder.write_all(&data).expect(&err_msg);
    encoder.finish().expect(&err_msg)
}

pub fn lz64_compress(title: &str, data: Vec<u8>) -> String {
    let utf8_err_msg = format!("failed to convert raw_payload to UTF-8 in case: {}", title);
    let utf8_str = std::str::from_utf8(&data).expect(&utf8_err_msg);
    let utf16_bytes: Vec<u16> = utf8_str.encode_utf16().collect();
    lz_str::compress_to_base64(utf16_bytes)
}

// format the sent_at value when included in GET URL query params
pub fn iso8601_str_to_unix_millis(title: &str, ts_str: &str) -> i64 {
    let err_msg = format!(
        "failed to parse ISO8601 time into UNIX millis in case: {}",
        title
    );
    OffsetDateTime::parse(ts_str, &Iso8601::DEFAULT)
        .expect(&err_msg)
        .unix_timestamp()
        * 1000_i64
}

pub async fn validate_capture_response(title: &str, res: TestResponse) {
    assert_eq!(
        StatusCode::OK,
        res.status(),
        "test {}: non-2xx response: {}",
        title,
        res.text().await
    );

    let cap_resp_details = res.json().await;
    assert_eq!(
        Some(CaptureResponse {
            status: CaptureResponseCode::Ok,
            quota_limited: None,
        }),
        cap_resp_details,
        "test {}: non-OK CaptureResponse: {:?}",
        title,
        cap_resp_details,
    );
}

// utility to validate tests/fixtures/single_event_payload.json
pub fn validate_single_event_payload(title: &str, got_events: Vec<ProcessedEvent>) {
    let expected_event_count = 1;
    let expected_timestamp = OffsetDateTime::parse(DEFAULT_TEST_TIME, &Rfc3339).unwrap();

    assert_eq!(
        expected_event_count,
        got_events.len(),
        "event count: expected {}, got {}",
        expected_event_count,
        got_events.len(),
    );

    // should only be one event in this batch
    let got = got_events[0].to_owned();

    // introspect on extracted event parsing metadata
    let meta = &got.metadata;
    assert_eq!(
        DataType::AnalyticsMain,
        meta.data_type,
        "mismatched Kafka topic assignment in case: {}",
        title,
    );
    assert_eq!(None, meta.session_id, "wrong session_id in case: {}", title,);

    // introspect on extracted event attributes
    let event = &got.event;
    assert_eq!(
        "phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3", &event.token,
        "mismatched token in case: {}",
        title,
    );
    assert_eq!(
        "019833ae-4913-7179-b6bc-019570abb1c9", &event.distinct_id,
        "mismatched distinct_id in case: {}",
        title,
    );
    assert_eq!(
        DEFAULT_TEST_TIME, &event.now,
        "mismatched 'now' timestamp in case: {}",
        title,
    );
    assert_eq!(
        36_usize,
        event.uuid.to_string().len(),
        "invalid UUID in case: {}",
        title,
    );

    assert_eq!(
        Some(expected_timestamp),
        event.sent_at,
        "mismatched sent_at in case: {}",
        title,
    );
    assert!(
        !event.is_cookieless_mode,
        "mismatched cookieless flag in case: {}",
        title,
    );

    // introspect on event data to be processed by plugin-server
    let event_data_err_msg = format!("failed to hydrate test event.data in case: {}", title);
    let event: Value = from_str(&event.data).expect(&event_data_err_msg);

    assert_eq!(
        "$autocapture",
        event["event"].as_str().unwrap(),
        "mismatched event.event in case: {}",
        title,
    );
    assert_eq!(
        "2025-07-01T00:00:00Z",
        event["timestamp"].as_str().unwrap(),
        "mismatched event.timestamp in case: {}",
        title,
    );
    assert_eq!(
        "019833ae-4913-7179-b6bc-019570abb1c9", event["distinct_id"],
        "mismatched event.distinct_id in case: {}",
        title,
    );

    // introspect on extracted event.properties map
    let err_msg = format!("failed to extract event.properties in case: {}", title);
    let props = event["properties"].as_object().expect(&err_msg);

    assert_eq!(
        68_usize,
        props.len(),
        "mismatched event.properties length in case: {}",
        title,
    );
    assert_eq!(
        "web", props["$lib"],
        "mismatched event.properties.$lib in case: {}",
        title,
    );
    assert_eq!(
        "1.2.3", props["$lib_version"],
        "mismatched event.properties.$lib_version in case: {}",
        title,
    );
    assert_eq!(
        "https://posthog.example.com/testing", props["$current_url"],
        "mismatched event.properties.$current_url in case: {}",
        title,
    );
    assert_eq!(
        Some(&Number::from(138)),
        props["$browser_version"].as_number(),
        "mismatched event.properties.$browser_version in case: {}",
        title,
    );
    assert_eq!(
        Some(&Number::from(1157858)),
        props["$sdk_debug_current_session_duration"].as_number(),
        "mismatched event.properties.$sdk_debug_current_session_duration in case: {}",
        title,
    );
    assert_eq!(
        Some(false),
        props["$is_identified"].as_bool(),
        "mismatched event.properties.$is_identified in case: {}",
        title,
    );
    assert_eq!(
        Some(true),
        props["$console_log_recording_enabled_server_side"].as_bool(),
        "mismatched event.properties.$console_log_recording_enabled_server_side in case: {}",
        title,
    );
}

// utility to validate tests/fixtures/single_engage_event_payload.json
pub fn validate_single_engage_event_payload(title: &str, got_events: Vec<ProcessedEvent>) {
    let expected_event_count = 1;
    let expected_timestamp = OffsetDateTime::parse(DEFAULT_TEST_TIME, &Rfc3339).unwrap();

    assert_eq!(
        expected_event_count,
        got_events.len(),
        "event count: expected {}, got {}",
        expected_event_count,
        got_events.len(),
    );

    // should only be one event in this batch
    let got = got_events[0].to_owned();

    // introspect on extracted event parsing metadata
    let meta = &got.metadata;
    assert_eq!(
        DataType::AnalyticsMain,
        meta.data_type,
        "mismatched Kafka topic assignment in case: {}",
        title,
    );
    assert_eq!(None, meta.session_id, "wrong session_id in case: {}", title,);

    // introspect on extracted event attributes
    let event = &got.event;
    assert_eq!(
        "phc_VXRzc3poSG9GZm1JenRiZnJ6TTJFZGh4OWY2QXzx9f3", &event.token,
        "mismatched token in case: {}",
        title,
    );
    assert_eq!(
        "01983d85-e613-7067-a70e-21bb63f8b8ee", &event.distinct_id,
        "mismatched distinct_id in case: {}",
        title,
    );
    assert_eq!(
        DEFAULT_TEST_TIME, &event.now,
        "mismatched 'now' timestamp in case: {}",
        title,
    );
    assert_eq!(
        36_usize,
        event.uuid.to_string().len(),
        "invalid UUID in case: {}",
        title,
    );

    assert_eq!(
        Some(expected_timestamp),
        event.sent_at,
        "mismatched sent_at in case: {}",
        title,
    );
    assert!(
        !event.is_cookieless_mode,
        "mismatched cookieless flag in case: {}",
        title,
    );

    // introspect on event data to be processed by plugin-server
    let event_data_err_msg = format!("failed to hydrate test event.data in case: {}", title);
    let event: Value = from_str(&event.data).expect(&event_data_err_msg);

    // /engage/ events get post-processed into "$identify" events
    assert_eq!(
        "$identify",
        event["event"].as_str().unwrap(),
        "mismatched event.event in case: {}",
        title,
    );
    assert_eq!(
        "2025-07-01T11:00:00Z",
        event["timestamp"].as_str().unwrap(),
        "mismatched event.timestamp in case: {}",
        title,
    );
    assert_eq!(
        "01983d85-e613-7067-a70e-21bb63f8b8ee", event["distinct_id"],
        "mismatched event.distinct_id in case: {}",
        title,
    );

    // introspect on extracted event.properties map
    let err_msg = format!("failed to extract event.properties in case: {}", title);
    let props = event["properties"].as_object().expect(&err_msg);

    assert_eq!(
        1_usize,
        props.len(),
        "mismatched event.properties length in case: {}",
        title,
    );

    let err_msg = format!("failed to extract event.properties.$set in case: {}", title);
    let set_props = props["$set"].as_object().expect(&err_msg);
    assert_eq!(
        Some("bar"),
        set_props["foo"].as_str(),
        "mismatched event.properties.$set.foo in case: {}",
        title,
    );
    assert_eq!(
        Some(&Number::from(42)),
        set_props["baz"].as_number(),
        "mismatched event.properties.$set.baz in case: {}",
        title,
    );
}

// utility to validate tests/fixtures/single_replay_event_payload.json
pub fn validate_single_replay_event_payload(title: &str, got_events: Vec<ProcessedEvent>) {
    let expected_event_count = 1;
    let expected_timestamp = OffsetDateTime::parse(DEFAULT_TEST_TIME, &Rfc3339).unwrap();

    assert_eq!(
        expected_event_count,
        got_events.len(),
        "event count: expected {}, got {}",
        expected_event_count,
        got_events.len(),
    );

    // should only be one event in this batch
    let got = got_events[0].to_owned();

    // introspect on extracted event parsing metadata
    let meta = &got.metadata;
    assert_eq!(
        DataType::SnapshotMain,
        meta.data_type,
        "mismatched Kafka topic assignment in case: {}",
        title,
    );
    assert_eq!(
        Some("01983d9b-8639-78fa-ac26-b9e7bf716521".to_string()),
        meta.session_id,
        "wrong session_id in case: {}",
        title,
    );

    // introspect on extracted event attributes
    let event = &got.event;
    assert_eq!(
        "phc_VXRzc3poSG9GZm1JenRiZnJ6TTJFZGh4OWY2QXzx9f3", &event.token,
        "mismatched token in case: {}",
        title,
    );
    assert_eq!(
        "01983d90-510c-7970-a356-ecd2aa03cb22", &event.distinct_id,
        "mismatched distinct_id in case: {}",
        title,
    );

    assert_eq!(
        DEFAULT_TEST_TIME, &event.now,
        "mismatched 'now' timestamp in case: {}",
        title,
    );
    assert_eq!(
        36_usize,
        event.uuid.to_string().len(),
        "invalid UUID in case: {}",
        title,
    );

    assert_eq!(
        Some(expected_timestamp),
        event.sent_at,
        "mismatched sent_at in case: {}",
        title,
    );

    // introspect on event data to be processed by plugin-server
    let event_data_err_msg = format!("failed to hydrate test event.data in case: {}", title);
    let event: Value = from_str(&event.data).expect(&event_data_err_msg);

    assert_eq!(
        "$snapshot_items",
        event["event"].as_str().unwrap(),
        "mismatched event.event in case: {}",
        title,
    );
    assert_eq!(
        None,
        event["timestamp"].as_str(),
        "mismatched event.timestamp in case: {}",
        title,
    );

    // introspect on extracted event.properties map
    let err_msg = format!("failed to extract event.properties in case: {}", title);
    let props = event["properties"].as_object().expect(&err_msg);

    assert_eq!(
        6_usize,
        props.len(),
        "mismatched event.properties length in case: {}",
        title,
    );
    assert_eq!(
        "web", props["$lib"],
        "mismatched event.properties.$lib in case: {}",
        title,
    );
    assert_eq!(
        "01983d90-510c-7970-a356-ecd2aa03cb22", props["distinct_id"],
        "mismatched event.properties.distinct_id in case: {}",
        title,
    );
    assert_eq!(
        "01983d9b-8639-78fa-ac26-b9e7bf716521", props["$session_id"],
        "mismatched event.properties.$session_id in case: {}",
        title,
    );
    assert_eq!(
        "01983d90-31f6-78cf-86c8-b26d0bdaaff0", props["$window_id"],
        "mismatched event.properties.$window_id in case: {}",
        title,
    );

    // introspect on $snapshot_data elements from replay event.properties
    let err_msg = format!(
        "failed to extract event.properties.$snapshot_data in case: {}",
        title
    );
    let snap_items = props["$snapshot_items"].as_array().expect(&err_msg);
    assert_eq!(
        22_usize,
        snap_items.len(),
        "mismatched event.properties.$snapshot_items length in case: {}",
        title,
    );

    // introspect on first data element of $snapshot_items array
    let err_msg = format!(
        "failed to extract event.properties.$snapshot_items[0] in case: {}",
        title
    );
    let elem1 = snap_items[0].as_object().expect(&err_msg);
    assert_eq!(
        3_usize,
        elem1.len(),
        "mismatched event.properties.$snapshot_items[0] in case: {}",
        title,
    );
    assert!(
        elem1["data"].is_object(),
        "event.properties.$snapshot_items[0].data should be an object in case: {}",
        title,
    );
    assert!(
        elem1["timestamp"].is_i64(),
        "event.properties.$snapshot_items[0].timestamp should be a number in case: {}",
        title,
    );
    assert!(
        elem1["type"].is_number(),
        "event.properties.$snapshot_items[0].type should be a number in case: {}",
        title,
    );
}

// utility to validate tests/fixtures/batch_events_payload.json
pub fn validate_batch_events_payload(title: &str, got_events: Vec<ProcessedEvent>) {
    let expected_event_count = 2;
    let expected_timestamp = OffsetDateTime::parse(DEFAULT_TEST_TIME, &Rfc3339).unwrap();

    assert_eq!(
        expected_event_count,
        got_events.len(),
        "event count: expected {}, got {}",
        expected_event_count,
        got_events.len(),
    );

    // first event should be a $pageview
    let pageview = got_events[0].to_owned();

    // introspect on extracted event parsing metadata
    let meta = &pageview.metadata;
    assert_eq!(
        DataType::AnalyticsMain,
        meta.data_type,
        "mismatched Kafka topic assignment in case: {}",
        title,
    );
    assert_eq!(None, meta.session_id, "wrong session_id in case: {}", title,);

    // introspect on extracted event attributes
    let event = &pageview.event;
    assert_eq!(
        "phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3", &event.token,
        "mismatched token on $pageview in case: {}",
        title,
    );
    assert_eq!(
        "someone@example.com", &event.distinct_id,
        "mismatched distinct_id on $pageview in case: {}",
        title,
    );
    assert_eq!(
        DEFAULT_TEST_TIME, &event.now,
        "mismatched 'now' timestamp $pageview in case: {}",
        title,
    );
    assert_eq!(
        36_usize,
        event.uuid.to_string().len(),
        "invalid UUID on $pageview in case: {}",
        title,
    );

    assert_eq!(
        Some(expected_timestamp),
        event.sent_at,
        "mismatched sent_at on $pageview in case: {}",
        title,
    );
    assert!(
        !event.is_cookieless_mode,
        "mismatched cookieless flag on $pageview in case: {}",
        title,
    );

    // introspect on event data to be processed by plugin-server
    let event_data_err_msg = format!(
        "failed to hydrate test $pageview event.data in case: {}",
        title
    );
    let event: Value = from_str(&event.data).expect(&event_data_err_msg);

    assert_eq!(
        "$pageview",
        event["event"].as_str().unwrap(),
        "mismatched event.event on batch event 1 in case: {}",
        title,
    );
    assert_eq!(
        "2025-07-01T02:55:00Z",
        event["timestamp"].as_str().unwrap(),
        "mismatched event.timestamp on $pageview in case: {}",
        title,
    );
    assert_eq!(
        "someone@example.com", event["distinct_id"],
        "mismatched event.distinct_id on $pageview in case: {}",
        title,
    );

    // introspect on extracted event.properties map
    let err_msg = format!(
        "failed to extract event.properties on $pageview in case: {}",
        title
    );
    let props = event["properties"].as_object().expect(&err_msg);

    assert_eq!(
        64_usize,
        props.len(),
        "mismatched event.properties length on $pageview in case: {}",
        title,
    );
    assert_eq!(
        "web", props["$lib"],
        "mismatched event.properties.$lib on $pageview in case: {}",
        title,
    );
    assert_eq!(
        "1.2.3", props["$lib_version"],
        "mismatched event.properties.$lib_version on $pageview in case: {}",
        title,
    );
    assert_eq!(
        "https://posthog.example.com/testing", props["$current_url"],
        "mismatched event.properties.$current_url in case: {}",
        title,
    );
    assert_eq!(
        Some(&Number::from(138)),
        props["$browser_version"].as_number(),
        "mismatched event.properties.$browser_version in case: {}",
        title,
    );
    assert_eq!(
        Some(1753306906004_i64),
        props["$sdk_debug_session_start"].as_i64(),
        "mismatched event.properties.$sdk_debug_session_start on $pageview in case: {}",
        title,
    );
    assert_eq!(
        Some(true),
        props["$is_identified"].as_bool(),
        "mismatched event.properties.$is_identified on $pageview in case: {}",
        title,
    );
    assert_eq!(
        Some(1753306906.2_f64),
        props["$time"].as_f64(),
        "mismatched event.properties.$time on $pageview in case: {}",
        title,
    );

    // introspect on extracted event.properties.$set_once map
    let err_msg = format!(
        "failed to extract event.properties.$set_once on $pageview in case: {}",
        title
    );
    let set_once_props = event["properties"]["$set_once"]
        .as_object()
        .expect(&err_msg);

    assert_eq!(
        58_usize,
        set_once_props.len(),
        "mismatched event.properties.$set_once length on $pageview in case: {}",
        title,
    );

    // second event should be a $pageleave
    let pageleave = got_events[1].to_owned();

    // introspect on extracted event parsing metadata
    let meta = &pageleave.metadata;
    assert_eq!(
        DataType::AnalyticsMain,
        meta.data_type,
        "mismatched Kafka topic assignment in case: {}",
        title,
    );
    assert_eq!(
        None, meta.session_id,
        "mismatched session_id in case: {}",
        title,
    );

    // introspect on extracted event attributes
    let event = &pageleave.event;
    assert_eq!(
        "phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3", &event.token,
        "mismatched token on $pageleave in case: {}",
        title,
    );
    assert_eq!(
        "someone@example.com", &event.distinct_id,
        "mismatched distinct_id on $pageleave in case: {}",
        title,
    );
    assert_eq!(
        DEFAULT_TEST_TIME, &event.now,
        "mismatched 'now' timestamp $pageleave in case: {}",
        title,
    );
    assert_eq!(
        36_usize,
        event.uuid.to_string().len(),
        "invalid UUID on $pageleave in case: {}",
        title,
    );

    assert_eq!(
        Some(expected_timestamp),
        event.sent_at,
        "mismatched sent_at on $pageleave in case: {}",
        title,
    );
    assert!(
        !event.is_cookieless_mode,
        "mismatched cookieless flag on $pageleave in case: {}",
        title,
    );

    // introspect on event data to be processed by plugin-server
    let event_data_err_msg = format!(
        "failed to hydrate test $pageleave event.data in case: {}",
        title
    );
    let event: Value = from_str(&event.data).expect(&event_data_err_msg);

    assert_eq!(
        "$pageleave",
        event["event"].as_str().unwrap(),
        "mismatched event.event on batch event 2 in case: {}",
        title,
    );
    assert_eq!(
        "2025-07-01T03:00:00Z",
        event["timestamp"].as_str().unwrap(),
        "mismatched event.timestamp on $pageleave in case: {}",
        title,
    );
    assert_eq!(
        "someone@example.com", event["distinct_id"],
        "mismatched event.distinct_id on $pageleave in case: {}",
        title,
    );

    // introspect on extracted event.properties map
    let err_msg = format!(
        "failed to extract event.properties on $pageleave in case: {}",
        title
    );
    let props = event["properties"].as_object().expect(&err_msg);

    assert_eq!(
        72_usize,
        props.len(),
        "mismatched event.properties length on $pageleave in case: {}",
        title,
    );
    assert_eq!(
        "web", props["$lib"],
        "mismatched event.properties.$lib on $pageleave in case: {}",
        title,
    );
    assert_eq!(
        "1.2.3", props["$lib_version"],
        "mismatched event.properties.$lib_version on $pageleave in case: {}",
        title,
    );
    assert_eq!(
        "https://posthog.example.com/testing", props["$current_url"],
        "mismatched event.properties.$current_url in case: {}",
        title,
    );
    assert_eq!(
        Some(&Number::from(138)),
        props["$browser_version"].as_number(),
        "mismatched event.properties.$browser_version in case: {}",
        title,
    );
    assert_eq!(
        Some(1753305190397_i64),
        props["$sdk_debug_session_start"].as_i64(),
        "mismatched event.properties.$sdk_debug_session_start on $pageleave in case: {}",
        title,
    );
    assert_eq!(
        Some(true),
        props["$is_identified"].as_bool(),
        "mismatched event.properties.$is_identified on $pageleave in case: {}",
        title,
    );
    assert_eq!(
        Some(1753305291.695_f64),
        props["$time"].as_f64(),
        "mismatched event.properties.$time on $pageleave in case: {}",
        title,
    );
}
