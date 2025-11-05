#![allow(dead_code)]
use std::fs::read;
use std::io::Write;
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use capture::{
    api::{CaptureError, CaptureResponse, CaptureResponseCode},
    config::CaptureMode,
    limiters::CaptureQuotaLimiter,
    router::router,
    sinks::Event,
    time::TimeSource,
    v0_request::{DataType, ProcessedEvent},
};
use chrono::{DateTime, Utc};

#[path = "./utils.rs"]
mod test_utils;
pub use test_utils::DEFAULT_CONFIG;

use async_trait::async_trait;
use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::{TestClient, TestResponse};
use base64::Engine;
use common_redis::MockRedisClient;
use flate2::write::GzEncoder;
use flate2::Compression;
use health::HealthRegistry;
use limiters::token_dropper::TokenDropper;
use serde_json::{from_str, Number, Value};
use time::format_description::well_known::{Iso8601, Rfc3339};
use time::OffsetDateTime;

pub const DEFAULT_TEST_TIME: &str = "2025-07-01T11:00:00Z";

// we reuse exemplar payload fixtures in the tests, focusing instead
// on all the ways a capture request and it's payload can be shaped:
pub const SINGLE_EVENT_JSON: &str = "single_event_payload.json";
pub const SINGLE_REPLAY_EVENT_JSON: &str = "single_replay_event_payload.json";
pub const BATCH_EVENTS_JSON: &str = "batch_events_payload.json";
// the /engage/ endpoint is unique: this only accepts "unnamed" (no event.event attrib)
// events that are structured as "$identify" events
pub const SINGLE_ENGAGE_EVENT_JSON: &str = "single_engage_event_payload.json";

pub type PayloadGen = Box<dyn Fn(&TestCase) -> Vec<u8>>;

#[derive(Debug)]
pub enum Method {
    Get,
    GetWithBody,
    Post,
}
pub struct TestCase {
    pub title: String,
    pub fixed_time: &'static str,
    pub mode: CaptureMode,
    pub base_path: &'static str,
    pub fixture: &'static str,
    pub method: Method,
    pub compression_hint: Option<&'static str>,
    pub lib_version_hint: Option<&'static str>,
    pub content_type: &'static str,
    pub expected_status: StatusCode,
    pub generate_payload: PayloadGen,
}

impl TestCase {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        title: String,
        fixed_time: &'static str,
        mode: CaptureMode,
        base_path: &'static str,
        fixture: &'static str,
        method: Method,
        compression_hint: Option<&'static str>,
        lib_version_hint: Option<&'static str>,
        content_type: &'static str,
        expected_status: StatusCode,
        generate_payload: PayloadGen,
    ) -> Self {
        TestCase {
            title,
            fixed_time,
            mode,
            base_path,
            fixture,
            method,
            compression_hint,
            lib_version_hint,
            content_type,
            expected_status,
            generate_payload,
        }
    }
}

//
// Test Runner
//

pub async fn execute_test(unit: &TestCase) {
    let payload = (unit.generate_payload)(unit);

    let (router, sink) = setup_capture_router(unit);
    let client = TestClient::new(router);

    let resp = match unit.method {
        Method::Post => post_request(unit, &client, payload).await,
        Method::Get => get_request(unit, &client, payload).await,
        Method::GetWithBody => get_with_body_request(unit, &client, payload).await,
    };

    match unit.expected_status {
        StatusCode::OK => validate_response_success(&unit.title, resp).await,
        _ => {
            expect_response_fail(&unit.title, resp).await;
            return; // no need to check the payload if the request failed!
        }
    };

    let got = sink.events();
    match unit.fixture {
        SINGLE_EVENT_JSON => validate_single_event_payload(&unit.title, got),
        SINGLE_REPLAY_EVENT_JSON => validate_single_replay_event_payload(&unit.title, got),
        SINGLE_ENGAGE_EVENT_JSON => validate_single_engage_event_payload(&unit.title, got),
        BATCH_EVENTS_JSON => validate_batch_events_payload(&unit.title, got),
        _ => panic!(
            "unsupported fixture type {} in TestCase: {}",
            unit.fixture, unit.title
        ),
    }
}

//
// Request generators
//

pub async fn get_request(unit: &TestCase, client: &TestClient, payload: Vec<u8>) -> TestResponse {
    let resolved_params = generate_get_path(unit, payload);
    let resolved_path = format!("{}/?{}", unit.base_path, resolved_params);

    let req = client
        .get(&resolved_path)
        .header("Content-Type", unit.content_type)
        .header("X-Forwarded-For", "127.0.0.1");

    req.send().await
}

pub async fn post_request(unit: &TestCase, client: &TestClient, payload: Vec<u8>) -> TestResponse {
    let resolved_path = generate_post_path(unit);

    let req = client
        .post(&resolved_path)
        .body(payload)
        .header("Content-Type", unit.content_type)
        .header("X-Forwarded-For", "127.0.0.1");

    req.send().await
}

pub async fn get_with_body_request(
    unit: &TestCase,
    client: &TestClient,
    payload: Vec<u8>,
) -> TestResponse {
    let resolved_path = generate_post_path(unit);

    let req = client
        .get(&resolved_path)
        .body(payload)
        .header("Content-Type", unit.content_type)
        .header("X-Forwarded-For", "127.0.0.1");

    req.send().await
}

//
// Payload generators
//

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

pub fn plain_json_payload(unit: &TestCase) -> Vec<u8> {
    load_request_payload(unit)
}

pub fn base64_payload(unit: &TestCase) -> Vec<u8> {
    let raw_payload = load_request_payload(unit);
    base64::engine::general_purpose::STANDARD
        .encode(raw_payload)
        .into()
}

pub fn gzipped_payload(unit: &TestCase) -> Vec<u8> {
    let raw_payload = load_request_payload(unit);
    gzip_compress(&unit.title, raw_payload)
}

pub fn lz64_payload(unit: &TestCase) -> Vec<u8> {
    let raw_payload = load_request_payload(unit);
    lz64_compress(&unit.title, raw_payload)
        .as_bytes()
        .to_owned()
}

pub fn form_urlencoded_payload(unit: &TestCase) -> Vec<u8> {
    let raw_payload = load_request_payload(unit);
    let err_msg = format!(
        "failed to serialize payload to urlencoded form in case: {}",
        unit.title
    );
    let utf8_payload = std::str::from_utf8(&raw_payload).expect(&err_msg);
    serde_urlencoded::to_string([("data", utf8_payload), ("ver", "1.2.3")])
        .expect(&err_msg)
        .into()
}

pub fn form_data_base64_payload(unit: &TestCase) -> Vec<u8> {
    let raw_payload = load_request_payload(unit);
    let err_msg = format!(
        "failed to serialize payload to urlencoded form in case: {}",
        unit.title
    );
    let base64_payload = base64::engine::general_purpose::STANDARD.encode(raw_payload);
    serde_urlencoded::to_string([("data", base64_payload.as_ref()), ("ver", "1.2.3")])
        .expect(&err_msg)
        .into()
}

pub fn form_lz64_urlencoded_payload(unit: &TestCase) -> Vec<u8> {
    let raw_payload = load_request_payload(unit);
    let lz64_payload = lz64_compress(&unit.title, raw_payload);
    let err_msg = format!(
        "failed to serialize LZ64 payload to urlencoded form in case: {}",
        unit.title
    );
    serde_urlencoded::to_string([("data", lz64_payload), ("ver", "1.2.3".to_string())])
        .expect(&err_msg)
        .into()
}

fn load_request_payload(unit: &TestCase) -> Vec<u8> {
    let path = Path::new("tests/fixtures").join(unit.fixture);
    let err_msg = format!("loading req event payload for case: {}", unit.title);
    read(path).expect(&err_msg)
}

fn generate_get_path(unit: &TestCase, payload: Vec<u8>) -> String {
    let err_msg = format!("payload is invalid UTF-8 in case: {}", unit.title);
    let data = std::str::from_utf8(&payload).expect(&err_msg);
    let unix_millis_sent_at = iso8601_str_to_unix_millis(&unit.title, unit.fixed_time).to_string();
    let mut params = vec![("data", data), ("_", &unix_millis_sent_at)];

    if let Some(c) = unit.compression_hint {
        params.push(("compression", c));
    }
    if let Some(v) = unit.lib_version_hint {
        params.push(("ver", v));
    }

    let err_msg = format!("failed to urlencode GET params in case: {}", unit.title);
    serde_urlencoded::to_string(params).expect(&err_msg)
}

fn generate_post_path(unit: &TestCase) -> String {
    let compression = unit
        .compression_hint
        .map(|c| format!("&compression={c}"))
        .unwrap_or("".to_string());
    let ver = unit
        .lib_version_hint
        .map(|v| format!("&ver={v}"))
        .unwrap_or("".to_string());
    let unix_millis_sent_at = iso8601_str_to_unix_millis(&unit.title, unit.fixed_time);

    format!(
        "{}/?_={unix_millis_sent_at}{compression}{ver}",
        unit.base_path,
    )
}

//
// Response validations
//

pub async fn validate_response_success(title: &str, res: TestResponse) {
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
        "test {title}: non-OK CaptureResponse: {cap_resp_details:?}",
    );
}

pub async fn expect_response_fail(title: &str, res: TestResponse) {
    assert_eq!(
        StatusCode::BAD_REQUEST,
        res.status(),
        "expected 4xx response status in case {} not received - got {} w/reason: {}",
        title,
        res.status(),
        res.text().await
    );
}

// utility to validate tests/fixtures/single_event_payload.json
pub fn validate_single_event_payload(title: &str, got_events: Vec<ProcessedEvent>) {
    let expected_event_count = 1;
    let expected_timestamp = OffsetDateTime::parse(DEFAULT_TEST_TIME, &Rfc3339).unwrap();

    assert_eq!(
        expected_event_count,
        got_events.len(),
        "mismatched event count in {}: expected {}, got {}",
        title,
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
        "mismatched Kafka topic assignment in case: {title}",
    );
    assert_eq!(None, meta.session_id, "wrong session_id in case: {title}",);

    // introspect on extracted event attributes
    let event = &got.event;
    assert_eq!(
        "phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3", &event.token,
        "mismatched token in case: {title}",
    );
    assert_eq!(
        "019833ae-4913-7179-b6bc-019570abb1c9", &event.distinct_id,
        "mismatched distinct_id in case: {title}",
    );
    assert_eq!(
        DEFAULT_TEST_TIME, &event.now,
        "mismatched 'now' timestamp in case: {title}",
    );
    assert_eq!(
        36_usize,
        event.uuid.to_string().len(),
        "invalid UUID in case: {title}",
    );

    assert_eq!(
        Some(expected_timestamp),
        event.sent_at,
        "mismatched sent_at in case: {title}",
    );
    assert!(
        !event.is_cookieless_mode,
        "mismatched cookieless flag in case: {title}",
    );

    // introspect on event data to be processed by plugin-server
    let event_data_err_msg = format!("failed to hydrate test event.data in case: {title}");
    let event: Value = from_str(&event.data).expect(&event_data_err_msg);

    assert_eq!(
        "$autocapture",
        event["event"].as_str().unwrap(),
        "mismatched event.event in case: {title}",
    );
    assert_eq!(
        "2025-07-01T00:00:00Z",
        event["timestamp"].as_str().unwrap(),
        "mismatched event.timestamp in case: {title}",
    );
    assert_eq!(
        "019833ae-4913-7179-b6bc-019570abb1c9", event["distinct_id"],
        "mismatched event.distinct_id in case: {title}",
    );

    // introspect on extracted event.properties map
    let err_msg = format!("failed to extract event.properties in case: {title}");
    let props = event["properties"].as_object().expect(&err_msg);

    assert_eq!(
        68_usize,
        props.len(),
        "mismatched event.properties length in case: {title}",
    );
    assert_eq!(
        "web", props["$lib"],
        "mismatched event.properties.$lib in case: {title}",
    );
    assert_eq!(
        "1.2.3", props["$lib_version"],
        "mismatched event.properties.$lib_version in case: {title}",
    );
    assert_eq!(
        "https://posthog.example.com/testing", props["$current_url"],
        "mismatched event.properties.$current_url in case: {title}",
    );
    assert_eq!(
        Some(&Number::from(138)),
        props["$browser_version"].as_number(),
        "mismatched event.properties.$browser_version in case: {title}",
    );
    assert_eq!(
        Some(&Number::from(1157858)),
        props["$sdk_debug_current_session_duration"].as_number(),
        "mismatched event.properties.$sdk_debug_current_session_duration in case: {title}",
    );
    assert_eq!(
        Some(false),
        props["$is_identified"].as_bool(),
        "mismatched event.properties.$is_identified in case: {title}",
    );
    assert_eq!(
        Some(true),
        props["$console_log_recording_enabled_server_side"].as_bool(),
        "mismatched event.properties.$console_log_recording_enabled_server_side in case: {title}",
    );
}

// utility to validate tests/fixtures/single_engage_event_payload.json
pub fn validate_single_engage_event_payload(title: &str, got_events: Vec<ProcessedEvent>) {
    let expected_event_count = 1;
    let expected_timestamp = OffsetDateTime::parse(DEFAULT_TEST_TIME, &Rfc3339).unwrap();

    assert_eq!(
        expected_event_count,
        got_events.len(),
        "event count: expected {expected_event_count}, got {}",
        got_events.len(),
    );

    // should only be one event in this batch
    let got = got_events[0].to_owned();

    // introspect on extracted event parsing metadata
    let meta = &got.metadata;
    assert_eq!(
        DataType::AnalyticsMain,
        meta.data_type,
        "mismatched Kafka topic assignment in case: {title}",
    );
    assert_eq!(None, meta.session_id, "wrong session_id in case: {title}",);

    // introspect on extracted event attributes
    let event = &got.event;
    assert_eq!(
        "phc_VXRzc3poSG9GZm1JenRiZnJ6TTJFZGh4OWY2QXzx9f3", &event.token,
        "mismatched token in case: {title}",
    );
    assert_eq!(
        "known_user@example.com", &event.distinct_id,
        "mismatched distinct_id in case: {title}",
    );
    assert_eq!(
        DEFAULT_TEST_TIME, &event.now,
        "mismatched 'now' timestamp in case: {title}",
    );
    assert_eq!(
        36_usize,
        event.uuid.to_string().len(),
        "invalid UUID in case: {title}",
    );

    assert_eq!(
        Some(expected_timestamp),
        event.sent_at,
        "mismatched sent_at in case: {title}",
    );
    assert!(
        !event.is_cookieless_mode,
        "mismatched cookieless flag in case: {title}",
    );

    // introspect on event data to be processed by plugin-server
    let event_data_err_msg = format!("failed to hydrate test event.data in case: {title}");
    let event: Value = from_str(&event.data).expect(&event_data_err_msg);

    // /engage/ events get post-processed into "$identify" events
    assert_eq!(
        "$identify",
        event["event"].as_str().unwrap(),
        "mismatched event.event in case: {title}",
    );
    assert_eq!(
        "2025-07-01T11:00:00Z",
        event["timestamp"].as_str().unwrap(),
        "mismatched event.timestamp in case: {title}",
    );
    assert_eq!(
        "known_user@example.com", event["distinct_id"],
        "mismatched event.distinct_id in case: {title}",
    );

    // introspect on extracted event.properties map
    let err_msg = format!("failed to extract event.properties in case: {title}");
    let props = event["properties"].as_object().expect(&err_msg);

    assert_eq!(
        2_usize,
        props.len(),
        "mismatched event.properties length in case: {title}",
    );

    assert_eq!(
        Some("01983d85-e613-7067-a70e-21bb63f8b8ee"),
        props["$anon_distinct_id"].as_str(),
        "mismatched event.properties.$anon_distinct_id in case: {title}",
    );

    let err_msg = format!("failed to extract event.properties.$set in case: {title}");
    let set_props = props["$set"].as_object().expect(&err_msg);
    assert_eq!(
        Some("bar"),
        set_props["foo"].as_str(),
        "mismatched event.properties.$set.foo in case: {title}",
    );
    assert_eq!(
        Some(&Number::from(42)),
        set_props["baz"].as_number(),
        "mismatched event.properties.$set.baz in case: {title}",
    );
}

// utility to validate tests/fixtures/single_replay_event_payload.json
pub fn validate_single_replay_event_payload(title: &str, got_events: Vec<ProcessedEvent>) {
    let expected_event_count = 1;
    let expected_timestamp = OffsetDateTime::parse(DEFAULT_TEST_TIME, &Rfc3339).unwrap();

    assert_eq!(
        expected_event_count,
        got_events.len(),
        "event count: expected {expected_event_count}, got {}",
        got_events.len(),
    );

    // should only be one event in this batch
    let got = got_events[0].to_owned();

    // introspect on extracted event parsing metadata
    let meta = &got.metadata;
    assert_eq!(
        DataType::SnapshotMain,
        meta.data_type,
        "mismatched Kafka topic assignment in case: {title}",
    );
    assert_eq!(
        Some("01983d9b-8639-78fa-ac26-b9e7bf716521".to_string()),
        meta.session_id,
        "wrong session_id in case: {title}",
    );

    // introspect on extracted event attributes
    let event = &got.event;
    assert_eq!(
        "phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3", &event.token,
        "mismatched token in case: {title}",
    );
    assert_eq!(
        "01983d90-510c-7970-a356-ecd2aa03cb22", &event.distinct_id,
        "mismatched distinct_id in case: {title}",
    );

    assert_eq!(
        DEFAULT_TEST_TIME, &event.now,
        "mismatched 'now' timestamp in case: {title}",
    );
    assert_eq!(
        36_usize,
        event.uuid.to_string().len(),
        "invalid UUID in case: {title}",
    );

    assert_eq!(
        Some(expected_timestamp),
        event.sent_at,
        "mismatched sent_at in case: {title}",
    );

    // introspect on event data to be processed by plugin-server
    let event_data_err_msg = format!("failed to hydrate test event.data in case: {title}");
    let event: Value = from_str(&event.data).expect(&event_data_err_msg);

    assert_eq!(
        "$snapshot_items",
        event["event"].as_str().unwrap(),
        "mismatched event.event in case: {title}",
    );
    assert_eq!(
        None,
        event["timestamp"].as_str(),
        "mismatched event.timestamp in case: {title}",
    );

    // introspect on extracted event.properties map
    let err_msg = format!("failed to extract event.properties in case: {title}");
    let props = event["properties"].as_object().expect(&err_msg);

    assert_eq!(
        6_usize,
        props.len(),
        "mismatched event.properties length in case: {title}",
    );
    assert_eq!(
        "web", props["$lib"],
        "mismatched event.properties.$lib in case: {title}",
    );
    assert_eq!(
        "01983d90-510c-7970-a356-ecd2aa03cb22", props["distinct_id"],
        "mismatched event.properties.distinct_id in case: {title}",
    );
    assert_eq!(
        "01983d9b-8639-78fa-ac26-b9e7bf716521", props["$session_id"],
        "mismatched event.properties.$session_id in case: {title}",
    );
    assert_eq!(
        "01983d90-31f6-78cf-86c8-b26d0bdaaff0", props["$window_id"],
        "mismatched event.properties.$window_id in case: {title}",
    );

    // introspect on $snapshot_data elements from replay event.properties
    let err_msg = format!("failed to extract event.properties.$snapshot_data in case: {title}");
    let snap_items = props["$snapshot_items"].as_array().expect(&err_msg);
    assert_eq!(
        22_usize,
        snap_items.len(),
        "mismatched event.properties.$snapshot_items length in case: {title}",
    );

    // introspect on first data element of $snapshot_items array
    let err_msg = format!("failed to extract event.properties.$snapshot_items[0] in case: {title}");
    let elem1 = snap_items[0].as_object().expect(&err_msg);
    assert_eq!(
        3_usize,
        elem1.len(),
        "mismatched event.properties.$snapshot_items[0] in case: {title}",
    );
    assert!(
        elem1["data"].is_object(),
        "event.properties.$snapshot_items[0].data should be an object in case: {title}",
    );
    assert!(
        elem1["timestamp"].is_i64(),
        "event.properties.$snapshot_items[0].timestamp should be a number in case: {title}",
    );
    assert!(
        elem1["type"].is_number(),
        "event.properties.$snapshot_items[0].type should be a number in case: {title}",
    );
}

// utility to validate tests/fixtures/batch_events_payload.json
pub fn validate_batch_events_payload(title: &str, got_events: Vec<ProcessedEvent>) {
    let expected_event_count = 2;
    let expected_timestamp = OffsetDateTime::parse(DEFAULT_TEST_TIME, &Rfc3339).unwrap();

    assert_eq!(
        expected_event_count,
        got_events.len(),
        "event count: expected {expected_event_count}, got {}",
        got_events.len(),
    );

    // first event should be a $pageview
    let pageview = got_events[0].to_owned();

    // introspect on extracted event parsing metadata
    let meta = &pageview.metadata;
    assert_eq!(
        DataType::AnalyticsMain,
        meta.data_type,
        "mismatched Kafka topic assignment in case: {title}",
    );
    assert_eq!(None, meta.session_id, "wrong session_id in case: {title}",);

    // introspect on extracted event attributes
    let event = &pageview.event;
    assert_eq!(
        "phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3", &event.token,
        "mismatched token on $pageview in case: {title}",
    );
    assert_eq!(
        "someone@example.com", &event.distinct_id,
        "mismatched distinct_id on $pageview in case: {title}",
    );
    assert_eq!(
        DEFAULT_TEST_TIME, &event.now,
        "mismatched 'now' timestamp $pageview in case: {title}",
    );
    assert_eq!(
        36_usize,
        event.uuid.to_string().len(),
        "invalid UUID on $pageview in case: {title}",
    );

    assert_eq!(
        Some(expected_timestamp),
        event.sent_at,
        "mismatched sent_at on $pageview in case: {title}",
    );
    assert!(
        !event.is_cookieless_mode,
        "mismatched cookieless flag on $pageview in case: {title}",
    );

    // introspect on event data to be processed by plugin-server
    let event_data_err_msg =
        format!("failed to hydrate test $pageview event.data in case: {title}");
    let event: Value = from_str(&event.data).expect(&event_data_err_msg);

    assert_eq!(
        "$pageview",
        event["event"].as_str().unwrap(),
        "mismatched event.event on batch event 1 in case: {title}",
    );
    assert_eq!(
        "2025-07-01T02:55:00Z",
        event["timestamp"].as_str().unwrap(),
        "mismatched event.timestamp on $pageview in case: {title}",
    );
    assert_eq!(
        "someone@example.com", event["distinct_id"],
        "mismatched event.distinct_id on $pageview in case: {title}",
    );

    // introspect on extracted event.properties map
    let err_msg = format!("failed to extract event.properties on $pageview in case: {title}");
    let props = event["properties"].as_object().expect(&err_msg);

    assert_eq!(
        64_usize,
        props.len(),
        "mismatched event.properties length on $pageview in case: {title}",
    );
    assert_eq!(
        "web", props["$lib"],
        "mismatched event.properties.$lib on $pageview in case: {title}",
    );
    assert_eq!(
        "1.2.3", props["$lib_version"],
        "mismatched event.properties.$lib_version on $pageview in case: {title}",
    );
    assert_eq!(
        "https://posthog.example.com/testing", props["$current_url"],
        "mismatched event.properties.$current_url in case: {title}",
    );
    assert_eq!(
        Some(&Number::from(138)),
        props["$browser_version"].as_number(),
        "mismatched event.properties.$browser_version in case: {title}",
    );
    assert_eq!(
        Some(1753306906004_i64),
        props["$sdk_debug_session_start"].as_i64(),
        "mismatched event.properties.$sdk_debug_session_start on $pageview in case: {title}",
    );
    assert_eq!(
        Some(true),
        props["$is_identified"].as_bool(),
        "mismatched event.properties.$is_identified on $pageview in case: {title}",
    );
    assert_eq!(
        Some(1753306906.2_f64),
        props["$time"].as_f64(),
        "mismatched event.properties.$time on $pageview in case: {title}",
    );

    // introspect on extracted event.properties.$set_once map
    let err_msg =
        format!("failed to extract event.properties.$set_once on $pageview in case: {title}");
    let set_once_props = event["properties"]["$set_once"]
        .as_object()
        .expect(&err_msg);

    assert_eq!(
        58_usize,
        set_once_props.len(),
        "mismatched event.properties.$set_once length on $pageview in case: {title}",
    );

    // second event should be a $pageleave
    let pageleave = got_events[1].to_owned();

    // introspect on extracted event parsing metadata
    let meta = &pageleave.metadata;
    assert_eq!(
        DataType::AnalyticsMain,
        meta.data_type,
        "mismatched Kafka topic assignment in case: {title}",
    );
    assert_eq!(
        None, meta.session_id,
        "mismatched session_id in case: {title}",
    );

    // introspect on extracted event attributes
    let event = &pageleave.event;
    assert_eq!(
        "phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3", &event.token,
        "mismatched token on $pageleave in case: {title}",
    );
    assert_eq!(
        "someone@example.com", &event.distinct_id,
        "mismatched distinct_id on $pageleave in case: {title}",
    );
    assert_eq!(
        DEFAULT_TEST_TIME, &event.now,
        "mismatched 'now' timestamp $pageleave in case: {title}",
    );
    assert_eq!(
        36_usize,
        event.uuid.to_string().len(),
        "invalid UUID on $pageleave in case: {title}",
    );

    assert_eq!(
        Some(expected_timestamp),
        event.sent_at,
        "mismatched sent_at on $pageleave in case: {title}",
    );
    assert!(
        !event.is_cookieless_mode,
        "mismatched cookieless flag on $pageleave in case: {title}",
    );

    // introspect on event data to be processed by plugin-server
    let event_data_err_msg =
        format!("failed to hydrate test $pageleave event.data in case: {title}");
    let event: Value = from_str(&event.data).expect(&event_data_err_msg);

    assert_eq!(
        "$pageleave",
        event["event"].as_str().unwrap(),
        "mismatched event.event on batch event 2 in case: {title}",
    );
    assert_eq!(
        "2025-07-01T03:00:00Z",
        event["timestamp"].as_str().unwrap(),
        "mismatched event.timestamp on $pageleave in case: {title}",
    );
    assert_eq!(
        "someone@example.com", event["distinct_id"],
        "mismatched event.distinct_id on $pageleave in case: {title}",
    );

    // introspect on extracted event.properties map
    let err_msg = format!("failed to extract event.properties on $pageleave in case: {title}");
    let props = event["properties"].as_object().expect(&err_msg);

    assert_eq!(
        72_usize,
        props.len(),
        "mismatched event.properties length on $pageleave in case: {title}",
    );
    assert_eq!(
        "web", props["$lib"],
        "mismatched event.properties.$lib on $pageleave in case: {title}",
    );
    assert_eq!(
        "1.2.3", props["$lib_version"],
        "mismatched event.properties.$lib_version on $pageleave in case: {title}",
    );
    assert_eq!(
        "https://posthog.example.com/testing", props["$current_url"],
        "mismatched event.properties.$current_url in case: {title}",
    );
    assert_eq!(
        Some(&Number::from(138)),
        props["$browser_version"].as_number(),
        "mismatched event.properties.$browser_version in case: {title}",
    );
    assert_eq!(
        Some(1753305190397_i64),
        props["$sdk_debug_session_start"].as_i64(),
        "mismatched event.properties.$sdk_debug_session_start on $pageleave in case: {title}",
    );
    assert_eq!(
        Some(true),
        props["$is_identified"].as_bool(),
        "mismatched event.properties.$is_identified on $pageleave in case: {title}",
    );
    assert_eq!(
        Some(1753305291.695_f64),
        props["$time"].as_f64(),
        "mismatched event.properties.$time on $pageleave in case: {title}",
    );
}

//
// Utilities
//

struct FixedTime {
    pub time: DateTime<Utc>,
}

impl TimeSource for FixedTime {
    fn current_time(&self) -> DateTime<Utc> {
        self.time
    }
}

#[derive(Clone, Default)]
struct MemorySink {
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

fn setup_capture_router(unit: &TestCase) -> (Router, MemorySink) {
    let liveness = HealthRegistry::new("integration_tests");
    let sink = MemorySink::default();
    let timesource = FixedTime {
        time: DateTime::parse_from_rfc3339(unit.fixed_time)
            .expect("Invalid fixed time format in test case")
            .with_timezone(&Utc),
    };
    let redis = Arc::new(MockRedisClient::new());

    let mut cfg = DEFAULT_CONFIG.clone();
    cfg.capture_mode = unit.mode.clone();

    let quota_limiter =
        CaptureQuotaLimiter::new(&cfg, redis.clone(), Duration::from_secs(60 * 60 * 24 * 7));

    // simple defaults - payload validation isn't the focus of these tests
    let enable_historical_rerouting = false;
    let historical_rerouting_threshold_days = 1_i64;
    let is_mirror_deploy = false; // TODO: remove after migration to 100% capture-rs backend
    let verbose_sample_percent = 0.0_f32;

    (
        router(
            timesource,
            liveness.clone(),
            sink.clone(),
            redis,
            quota_limiter,
            TokenDropper::default(),
            false,
            unit.mode.clone(),
            None,
            25 * 1024 * 1024,
            enable_historical_rerouting,
            historical_rerouting_threshold_days,
            is_mirror_deploy,
            verbose_sample_percent,
            26_214_400, // 25MB default for AI endpoint
        ),
        sink,
    )
}

// utility to compress capture payloads for testing
fn gzip_compress(title: &str, data: Vec<u8>) -> Vec<u8> {
    let err_msg = format!("failed to GZIP payload in case: {title}");
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());

    encoder.write_all(&data).expect(&err_msg);
    encoder.finish().expect(&err_msg)
}

fn lz64_compress(title: &str, data: Vec<u8>) -> String {
    let utf8_err_msg = format!("failed to convert raw_payload to UTF-8 in case: {title}");
    let utf8_str = std::str::from_utf8(&data).expect(&utf8_err_msg);
    let utf16_bytes: Vec<u16> = utf8_str.encode_utf16().collect();

    lz_str::compress_to_base64(utf16_bytes)
}

// format the sent_at value when included in GET URL query params
fn iso8601_str_to_unix_millis(title: &str, ts_str: &str) -> i64 {
    let err_msg = format!("failed to parse ISO8601 time into UNIX millis in case: {title}");
    OffsetDateTime::parse(ts_str, &Iso8601::DEFAULT)
        .expect(&err_msg)
        .unix_timestamp()
        * 1000_i64
}
