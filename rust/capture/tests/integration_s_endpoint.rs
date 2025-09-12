#[path = "common/integration_utils.rs"]
mod integration_utils;
use integration_utils::{
    base64_payload, execute_test, form_data_base64_payload, form_lz64_urlencoded_payload,
    form_urlencoded_payload, gzipped_payload, lz64_payload, plain_json_payload, Method, TestCase,
    DEFAULT_TEST_TIME, SINGLE_REPLAY_EVENT_JSON,
};

use axum::http::StatusCode;
use capture::config::CaptureMode;

#[tokio::test]
async fn test_s_endpoint_get() {
    // GET request with payload in the "data" URL query param
    for unit in get_cases() {
        execute_test(&unit).await;
    }
}

#[tokio::test]
async fn test_s_endpoint_post() {
    // POST request with the payload in the body
    for unit in post_cases() {
        execute_test(&unit).await;
    }
}

#[tokio::test]
async fn test_s_endpoint_get_with_body() {
    // GET requests with a body payload are treated identically to POST requests
    let mut get_with_body_cases = post_cases();

    get_with_body_cases
        .iter_mut()
        .for_each(|tc: &mut TestCase| {
            tc.method = Method::GetWithBody;
            tc.title = tc.title.replace("post-", "get_with_body-");
        });
    for unit in get_with_body_cases {
        execute_test(&unit).await;
    }
}

fn post_cases() -> Vec<TestCase> {
    let units = vec![
        // single event payload tests

        // plain JSON POST body
        TestCase::new(
            // test case title
            "post-simple-single-event-payload".to_string(),
            // default fixed time for test Router & event handler
            DEFAULT_TEST_TIME,
            // capture-rs service mode
            CaptureMode::Recordings,
            // capture-rs target endpoint
            "/s",
            // JSON payload to use as input
            SINGLE_REPLAY_EVENT_JSON,
            // request submission type; one of POST or GET only for these integration tests
            Method::Post,
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
            "post-base64-single-event-payload".to_string(),
            DEFAULT_TEST_TIME,
            CaptureMode::Recordings,
            "/s",
            SINGLE_REPLAY_EVENT_JSON,
            Method::Post,
            Some("base64"),
            None,
            "application/json",
            StatusCode::OK,
            Box::new(base64_payload),
        ),
        // base64'd JSON payload w/o SDK encoding hint - NOT SUPPORTED by new capture atm
        TestCase::new(
            "post-base64-no-hint-single-event-payload".to_string(),
            DEFAULT_TEST_TIME,
            CaptureMode::Recordings,
            "/s",
            SINGLE_REPLAY_EVENT_JSON,
            Method::Post,
            None, // no compression hint; handling must auto-detect
            None,
            "text/plain",
            StatusCode::OK,
            Box::new(base64_payload),
        ),
        // GZIP'd JSON single event payload
        TestCase::new(
            "post-gzip-single-event-payload".to_string(),
            DEFAULT_TEST_TIME,
            CaptureMode::Recordings,
            "/s",
            SINGLE_REPLAY_EVENT_JSON,
            Method::Post,
            Some("gzip"),
            None,
            "application/json",
            StatusCode::OK,
            Box::new(gzipped_payload),
        ),
        // GZIP'd single event JSON payload w/o SDK encoding hint
        TestCase::new(
            "post-gzip-no-hint-single-event-payload".to_string(),
            DEFAULT_TEST_TIME,
            CaptureMode::Recordings,
            "/s",
            SINGLE_REPLAY_EVENT_JSON,
            Method::Post,
            None, // no compression hint; handling must auto-detect
            None,
            "text/plain",
            StatusCode::OK,
            Box::new(gzipped_payload),
        ),
        TestCase::new(
            "post-form-data-base64-event-payload".to_string(),
            DEFAULT_TEST_TIME,
            CaptureMode::Recordings,
            "/s",
            SINGLE_REPLAY_EVENT_JSON,
            Method::Post,
            None,
            None,
            "application/x-www-form-urlencoded",
            StatusCode::BAD_REQUEST,
            Box::new(form_data_base64_payload),
        ),
        // single event JSON payload submitted as POST form
        TestCase::new(
            "post-form-urlencoded-event-payload".to_string(),
            DEFAULT_TEST_TIME,
            CaptureMode::Recordings,
            "/s",
            SINGLE_REPLAY_EVENT_JSON,
            Method::Post,
            None,
            None,
            "application/x-www-form-urlencoded",
            StatusCode::OK,
            Box::new(form_urlencoded_payload),
        ),
        // single event JSON payload submitted as LZ64'd value in POST form
        // NOT SUPPORTED by new capture atm
        TestCase::new(
            "post-form-lz64-urlencoded-event-payload".to_string(),
            DEFAULT_TEST_TIME,
            CaptureMode::Recordings,
            "/s",
            SINGLE_REPLAY_EVENT_JSON,
            Method::Post,
            Some("lz64"),
            None,
            "application/x-www-form-urlencoded",
            StatusCode::OK,
            Box::new(form_lz64_urlencoded_payload),
        ),
    ];

    units
}

// NOT SUPPORTED by new capture atm
fn get_cases() -> Vec<TestCase> {
    let units = vec![
        // plain base64'd JSON payload in urlencoded "data" GET param
        TestCase::new(
            "get-base64-urlencoded-single-event-payload".to_string(),
            DEFAULT_TEST_TIME,
            CaptureMode::Recordings,
            "/s",
            SINGLE_REPLAY_EVENT_JSON,
            Method::Get,
            Some("base64"),
            None,
            "text/plain",
            StatusCode::OK,
            Box::new(base64_payload),
        ),
        // single event JSON payload submitted in urlencoded "data" GET param
        TestCase::new(
            "get-urlencoded-event-payload".to_string(),
            DEFAULT_TEST_TIME,
            CaptureMode::Recordings,
            "/s",
            SINGLE_REPLAY_EVENT_JSON,
            Method::Get,
            None,
            None,
            "text/plain",
            StatusCode::OK,
            Box::new(plain_json_payload),
        ),
        // single event JSON payload submitted as LZ64'd value in urlencoded "data" GET param
        TestCase::new(
            "get-lz64-urlencoded-event-payload".to_string(),
            DEFAULT_TEST_TIME,
            CaptureMode::Recordings,
            "/s",
            SINGLE_REPLAY_EVENT_JSON,
            Method::Get,
            Some("lz64"),
            None,
            "text/plain",
            StatusCode::OK,
            Box::new(lz64_payload),
        ),
    ];

    units
}
