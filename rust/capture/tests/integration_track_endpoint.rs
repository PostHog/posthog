#[path = "common/integration_utils.rs"]
mod integration_utils;
use integration_utils::{
    base64_payload, execute_test, form_data_base64_payload, form_lz64_urlencoded_payload,
    form_urlencoded_payload, gzipped_payload, plain_json_payload, TestCase, BATCH_EVENTS_JSON,
    DEFAULT_TEST_TIME, SINGLE_EVENT_JSON,
};

use axum::http::{Method, StatusCode};
use capture::config::CaptureMode;

fn test_cases() -> Vec<TestCase> {
    let units = vec![
        // single event payload tests

        // plain JSON POST body
        TestCase::new(
            // test case title
            "track_post-simple-single-event-payload",
            // default fixed time for test Router & event handler
            DEFAULT_TEST_TIME,
            // capture-rs service mode
            CaptureMode::Events,
            // capture-rs target endpoint
            "/track",
            // JSON payload to use as input
            SINGLE_EVENT_JSON,
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
        // plain base64'd JSON payload in POST body
        TestCase::new(
            "track_post-base64-single-event-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            SINGLE_EVENT_JSON,
            Method::POST,
            Some("base64"),
            None,
            "application/json",
            StatusCode::OK,
            Box::new(base64_payload),
        ),
        // base64'd JSON payload w/o SDK encoding hint
        TestCase::new(
            "track_post-base64-no-hint-single-event-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            SINGLE_EVENT_JSON,
            Method::POST,
            None, // no compression hint; handling must auto-detect
            None,
            "text/plain",
            StatusCode::OK,
            Box::new(base64_payload),
        ),
        // GZIP'd JSON single event payload
        TestCase::new(
            "track_post-gzip-single-event-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            SINGLE_EVENT_JSON,
            Method::POST,
            Some("gzip"),
            None,
            "application/json",
            StatusCode::OK,
            Box::new(gzipped_payload),
        ),
        // GZIP'd single event JSON payload w/o SDK encoding hint
        TestCase::new(
            "track_post-gzip-no-hint-single-event-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            SINGLE_EVENT_JSON,
            Method::POST,
            None, // no compression hint; handling must auto-detect
            None,
            "text/plain",
            StatusCode::OK,
            Box::new(gzipped_payload),
        ),
        // single event JSON payload in POST form with "data" attribute base64 encoded
        TestCase::new(
            "track_post-form-data-base64-event-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            SINGLE_EVENT_JSON,
            Method::POST,
            None,
            None,
            "application/x-www-form-urlencoded",
            StatusCode::OK,
            Box::new(form_data_base64_payload),
        ),
        // single event JSON payload submitted as POST form
        TestCase::new(
            "track_post-form-urlencoded-event-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            SINGLE_EVENT_JSON,
            Method::POST,
            None,
            None,
            "application/x-www-form-urlencoded",
            StatusCode::OK,
            Box::new(form_urlencoded_payload),
        ),
        // single event JSON payload submitted as LZ64'd value in POST form
        TestCase::new(
            "track_post-form-lz64-urlencoded-event-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            SINGLE_EVENT_JSON,
            Method::POST,
            Some("lz64"),
            None,
            "application/x-www-form-urlencoded",
            StatusCode::OK,
            Box::new(form_lz64_urlencoded_payload),
        ),
        // batch payload test variants

        // plain JSON POST body
        TestCase::new(
            "track_post-simple-batch-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            BATCH_EVENTS_JSON,
            Method::POST,
            None,
            None,
            "application/json",
            StatusCode::OK,
            Box::new(plain_json_payload),
        ),
        // plain base64'd JSON payload in POST body
        TestCase::new(
            "track_post-base64-batch-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            BATCH_EVENTS_JSON,
            Method::POST,
            Some("base64"),
            None,
            "application/json",
            StatusCode::OK,
            Box::new(base64_payload),
        ),
        // base64'd JSON payload w/o SDK encoding hint
        TestCase::new(
            "track_post-base64-no-hint-batch-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            BATCH_EVENTS_JSON,
            Method::POST,
            None, // no compression hint; handling must auto-detect
            None,
            "text/plain",
            StatusCode::OK,
            Box::new(base64_payload),
        ),
        // GZIP'd JSON single event payload
        TestCase::new(
            "track_post-gzip-batch-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            BATCH_EVENTS_JSON,
            Method::POST,
            Some("gzip"),
            None,
            "application/json",
            StatusCode::OK,
            Box::new(gzipped_payload),
        ),
        // GZIP'd single event JSON payload w/o SDK encoding hint
        TestCase::new(
            "track_post-gzip-no-hint-batch-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            BATCH_EVENTS_JSON,
            Method::POST,
            None, // no compression hint; handling must auto-detect
            None,
            "text/plain",
            StatusCode::OK,
            Box::new(gzipped_payload),
        ),
        // batched events JSON payload submitted as POST form w/base64'd "data" attribute value
        TestCase::new(
            "track_post-form-data-base64-batch-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            BATCH_EVENTS_JSON,
            Method::POST,
            None,
            None,
            "application/x-www-form-urlencoded",
            StatusCode::OK,
            Box::new(form_data_base64_payload),
        ),
        // single event JSON payload submitted as POST form
        TestCase::new(
            "track_post-form-urlencoded-batch-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            BATCH_EVENTS_JSON,
            Method::POST,
            None,
            None,
            "application/x-www-form-urlencoded",
            StatusCode::OK,
            Box::new(form_urlencoded_payload),
        ),
        // single event JSON payload submitted as LZ64'd value in POST form
        TestCase::new(
            "track_post-form-lz64-urlencoded-batch-payload",
            DEFAULT_TEST_TIME,
            CaptureMode::Events,
            "/track",
            BATCH_EVENTS_JSON,
            Method::POST,
            Some("lz64"),
            None,
            "application/x-www-form-urlencoded",
            StatusCode::OK,
            Box::new(form_lz64_urlencoded_payload),
        ),
    ];

    units
}

#[tokio::test]
async fn test_track_endpoint() {
    for unit in test_cases() {
        execute_test(&unit).await;
    }
}
