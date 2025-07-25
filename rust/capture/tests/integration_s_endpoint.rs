#[path = "common/integration_utils.rs"]
mod integration_utils;
use integration_utils::{
    base64_payload, execute_test, form_data_base64_payload, form_lz64_urlencoded_payload,
    form_urlencoded_payload, gzipped_payload, plain_json_payload, TestCase, DEFAULT_TEST_TIME,
    SINGLE_REPLAY_EVENT_JSON,
};

use axum::http::{Method, StatusCode};
use capture::config::CaptureMode;

#[allow(warnings)]
fn test_cases() -> Vec<Box<TestCase>> {
    let units = vec![
        // single event payload tests

        // plain JSON POST body
        TestCase::new(
            // test case title
            "s_post-simple-single-event-payload",
            // default fixed time for test Router & event handler
            DEFAULT_TEST_TIME,
            // capture-rs service mode
            CaptureMode::Recordings,
            // capture-rs target endpoint
            "/s",
            // JSON payload to use as input
            SINGLE_REPLAY_EVENT_JSON,
            // request submission type; one of POST or GET only for these integration tests
            Method::POST,
            // compression "hint" (as supplied by some SDKs)
            None,
            // $lib_version "hint" (as supplied by some SDKs outside of event props)
            None,
            // request Content-Type
            "application/json",
            // determine how to eval the response - do we expect to succeed or fail this call?
            StatusCode::OK,
            // type of pre-processing and formatting to apply to payload
            Box::new(plain_json_payload),
        ),
        // plain base64'd JSON payload in POST body - NOT SUPPORTED in new capture atm
        TestCase::new(
            // test case title
            "s_post-base64-single-event-payload",
            // default fixed time for test Router & event handler
            DEFAULT_TEST_TIME,
            // capture-rs service mode
            CaptureMode::Recordings,
            // capture-rs target endpoint
            "/s",
            // JSON payload to use as input
            SINGLE_REPLAY_EVENT_JSON,
            // request submission type; one of POST or GET only for these integration tests
            Method::POST,
            // compression "hint" (as supplied by some SDKs)
            Some("base64"),
            // $lib_version "hint" (as supplied by some SDKs outside of event props)
            None,
            // request Content-Type
            "application/json",
            // determine how to eval the response - do we expect to succeed or fail this call?
            StatusCode::BAD_REQUEST,
            // type of pre-processing and formatting to apply to payload
            Box::new(base64_payload),
        ),
        // base64'd JSON payload w/o SDK encoding hint - NOT SUPPORTED by new capture atm
        TestCase::new(
            // test case title
            "s_post-base64-no-hint-single-event-payload",
            // default fixed time for test Router & event handler
            DEFAULT_TEST_TIME,
            // capture-rs service mode
            CaptureMode::Recordings,
            // capture-rs target endpoint
            "/s",
            // JSON payload to use as input
            SINGLE_REPLAY_EVENT_JSON,
            // request submission type; one of POST or GET only for these integration tests
            Method::POST,
            // compression "hint" (as supplied by some SDKs)
            None, // no compression hint; handling must auto-detect
            // $lib_version "hint" (as supplied by some SDKs outside of event props)
            None,
            // request Content-Type
            "text/plain",
            // determine how to eval the response - do we expect to succeed or fail this call?
            StatusCode::BAD_REQUEST,
            // type of pre-processing and formatting to apply to payload
            Box::new(base64_payload),
        ),
        // GZIP'd JSON single event payload
        TestCase::new(
            // test case title
            "s_post-gzip-single-event-payload",
            // default fixed time for test Router & event handler
            DEFAULT_TEST_TIME,
            // capture-rs service mode
            CaptureMode::Recordings,
            // capture-rs target endpoint
            "/s",
            // JSON payload to use as input
            SINGLE_REPLAY_EVENT_JSON,
            // request submission type; one of POST or GET only for these integration tests
            Method::POST,
            // compression "hint" (as supplied by some SDKs)
            Some("gzip"),
            // $lib_version "hint" (as supplied by some SDKs outside of event props)
            None,
            // request Content-Type
            "application/json",
            // determine how to eval the response - do we expect to succeed or fail this call?
            StatusCode::OK,
            // type of pre-processing and formatting to apply to payload
            Box::new(gzipped_payload),
        ),
        // GZIP'd single event JSON payload w/o SDK encoding hint
        TestCase::new(
            // test case title
            "s_post-gzip-no-hint-single-event-payload",
            // default fixed time for test Router & event handler
            DEFAULT_TEST_TIME,
            // capture-rs service mode
            CaptureMode::Recordings,
            // capture-rs target endpoint
            "/s",
            // JSON payload to use as input
            SINGLE_REPLAY_EVENT_JSON,
            // request submission type; one of POST or GET only for these integration tests
            Method::POST,
            // compression "hint" (as supplied by some SDKs)
            None, // no compression hint; handling must auto-detect
            // $lib_version "hint" (as supplied by some SDKs outside of event props)
            None,
            // request Content-Type
            "text/plain",
            // determine how to eval the response - do we expect to succeed or fail this call?
            StatusCode::OK,
            // type of pre-processing and formatting to apply to payload
            Box::new(gzipped_payload),
        ),
        TestCase::new(
            // test case title
            "s_post-form-data-base64-event-payload",
            // default fixed time for test Router & event handler
            DEFAULT_TEST_TIME,
            // capture-rs service mode
            CaptureMode::Recordings,
            // capture-rs target endpoint
            "/s",
            // JSON payload to use as input
            SINGLE_REPLAY_EVENT_JSON,
            // request submission type; one of POST or GET only for these integration tests
            Method::POST,
            // compression "hint" (as supplied by some SDKs)
            None,
            // $lib_version "hint" (as supplied by some SDKs outside of event props)
            None,
            // request Content-Type
            "application/x-www-form-urlencoded",
            // determine how to eval the response - do we expect to succeed or fail this call?
            StatusCode::OK,
            // type of pre-processing and formatting to apply to payload
            Box::new(form_data_base64_payload),
        ),
        // single event JSON payload submitted as POST form
        TestCase::new(
            // test case title
            "s_post-form-urlencoded-event-payload",
            // default fixed time for test Router & event handler
            DEFAULT_TEST_TIME,
            // capture-rs service mode
            CaptureMode::Recordings,
            // capture-rs target endpoint
            "/s",
            // JSON payload to use as input
            SINGLE_REPLAY_EVENT_JSON,
            // request submission type; one of POST or GET only for these integration tests
            Method::POST,
            // compression "hint" (as supplied by some SDKs)
            None,
            // $lib_version "hint" (as supplied by some SDKs outside of event props)
            None,
            // request Content-Type
            "application/x-www-form-urlencoded",
            // determine how to eval the response - do we expect to succeed or fail this call?
            StatusCode::BAD_REQUEST,
            // type of pre-processing and formatting to apply to payload
            Box::new(form_urlencoded_payload),
        ),
        // single event JSON payload submitted as LZ64'd value in POST form
        // NOT SUPPORTED by new capture atm
        TestCase::new(
            // test case title
            "s_post-form-lz64-urlencoded-event-payload",
            // default fixed time for test Router & event handler
            DEFAULT_TEST_TIME,
            // capture-rs service mode
            CaptureMode::Recordings,
            // capture-rs target endpoint
            "/s",
            // JSON payload to use as input
            SINGLE_REPLAY_EVENT_JSON,
            // request submission type; one of POST or GET only for these integration tests
            Method::POST,
            // compression "hint" (as supplied by some SDKs)
            Some("lz64"),
            // $lib_version "hint" (as supplied by some SDKs outside of event props)
            None,
            // request Content-Type
            "application/x-www-form-urlencoded",
            // determine how to eval the response - do we expect to succeed or fail this call?
            StatusCode::BAD_REQUEST,
            // type of pre-processing and formatting to apply to payload
            Box::new(form_lz64_urlencoded_payload),
        ),
    ];

    units
}

#[tokio::test]
async fn test_s_endpoint() {
    for unit in test_cases() {
        execute_test(unit).await;
    }
}
