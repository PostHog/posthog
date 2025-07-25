use axum::http::StatusCode;
use axum_test_helper::TestClient;
use base64::Engine;

use capture::config::CaptureMode;
use capture::integration_test_utils::{
    gzip_compress, iso8601_str_to_unix_millis, load_request_payload, lz64_compress,
    setup_capture_router, validate_capture_response, validate_single_event_payload,
    DEFAULT_TEST_TIME, SINGLE_EVENT_JSON,
};

#[tokio::test]
async fn simple_batch_events_payload() {
    let title = "simple-batch-events-payload";
    let raw_payload = load_request_payload(title, SINGLE_EVENT_JSON);

    let (router, sink) = setup_capture_router(CaptureMode::Events, DEFAULT_TEST_TIME);
    let client = TestClient::new(router);

    let unix_millis_sent_at = iso8601_str_to_unix_millis(title, DEFAULT_TEST_TIME);
    let req_path = format!("/i/v0/e/?_={}", unix_millis_sent_at);
    let req = client
        .post(&req_path)
        .body(raw_payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1");
    let res = req.send().await;

    validate_capture_response(title, res).await;

    // extract the processed events from the in-mem sink and validate contents
    let got = sink.events();
    validate_single_event_payload(title, got);
}

#[tokio::test]
async fn base64_batch_events_payload() {
    let title = "base64-batch-events-payload";
    let raw_payload = load_request_payload(title, SINGLE_EVENT_JSON);
    let base64_payload = base64::engine::general_purpose::STANDARD.encode(raw_payload);

    let (router, _sink) = setup_capture_router(CaptureMode::Events, DEFAULT_TEST_TIME);
    let client = TestClient::new(router);

    let unix_millis_sent_at = iso8601_str_to_unix_millis(title, DEFAULT_TEST_TIME);
    let req_path = format!("/i/v0/e/?_={}&compression=base64", unix_millis_sent_at);
    let req = client
        .post(&req_path)
        .body(base64_payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1");
    let res = req.send().await;

    // we expect this to fail while /batch/, /s/, and /i/v0/e/
    // are processed by handle_common
    assert_eq!(
        StatusCode::BAD_REQUEST,
        res.status(),
        "test {}: non-4xx response: {}",
        title,
        res.text().await
    );

    //validate_capture_response(title, res).await;

    // extract the processed events from the in-mem sink and validate contents
    //let got = sink.events();
    //validate_batch_events_payload(title, got);
}

#[tokio::test]
async fn gzipped_batch_events_payload() {
    let title = "gzipped-batch-events-payload";
    let raw_payload = load_request_payload(title, SINGLE_EVENT_JSON);
    let gzipped_payload = gzip_compress(title, raw_payload);

    let (router, sink) = setup_capture_router(CaptureMode::Events, DEFAULT_TEST_TIME);
    let client = TestClient::new(router);

    let unix_millis_sent_at = iso8601_str_to_unix_millis(title, DEFAULT_TEST_TIME);
    let req_path = format!("/i/v0/e/?_={}&compression=gzip", unix_millis_sent_at);
    let req = client
        .post(&req_path)
        .body(gzipped_payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1");
    let res = req.send().await;

    validate_capture_response(title, res).await;

    // extract the processed events from the in-mem sink and validate contents
    let got = sink.events();
    validate_single_event_payload(title, got);
}

#[tokio::test]
async fn gzipped_no_hint_batch_events_payload() {
    let title = "gzipped-no-hint-batch-events-payload";
    let raw_payload = load_request_payload(title, SINGLE_EVENT_JSON);
    let gzipped_payload = gzip_compress(title, raw_payload);

    let (router, sink) = setup_capture_router(CaptureMode::Events, DEFAULT_TEST_TIME);
    let client = TestClient::new(router);

    // note: without a "compression" GET query param or POST form, we must auto-detect GZIP compression
    let unix_millis_sent_at = iso8601_str_to_unix_millis(title, DEFAULT_TEST_TIME);
    let req_path = format!("/i/v0/e/?_={}", unix_millis_sent_at);
    let req = client
        .post(&req_path)
        .body(gzipped_payload)
        .header("Content-Type", "text/plain")
        .header("X-Forwarded-For", "127.0.0.1");
    let res = req.send().await;

    validate_capture_response(title, res).await;

    // extract the processed events from the in-mem sink and validate contents
    let got = sink.events();
    validate_single_event_payload(title, got);
}

#[tokio::test]
async fn post_form_base64_urlencoded_batch_events_payload() {
    let title = "post-form-urlencoded-batch-events-payload";
    let raw_payload = load_request_payload(title, SINGLE_EVENT_JSON);
    let err_msg = format!(
        "failed to serialize payload to base64 + urlencoded form in case: {}",
        title
    );
    // the "new" capture endpoints like /batch/ expect base64 encoded form payloads only
    let base64_payload = base64::engine::general_purpose::STANDARD.encode(raw_payload);
    let form_payload =
        serde_urlencoded::to_string([("data", base64_payload.as_str()), ("ver", "1.2.3")])
            .expect(&err_msg);

    let (router, sink) = setup_capture_router(CaptureMode::Events, DEFAULT_TEST_TIME);
    let client = TestClient::new(router);

    let unix_millis_sent_at = iso8601_str_to_unix_millis(title, DEFAULT_TEST_TIME);
    let req_path = format!("/i/v0/e/?_={}", unix_millis_sent_at);
    let req = client
        .post(&req_path)
        .body(form_payload)
        .header("Content-Type", "application/x-www-form-urlencoded")
        .header("X-Forwarded-For", "127.0.0.1");
    let res = req.send().await;

    validate_capture_response(title, res).await;

    // extract the processed events from the in-mem sink and validate contents
    let got = sink.events();
    validate_single_event_payload(title, got);
}

#[tokio::test]
async fn post_form_lz64_batch_events_payload() {
    let title = "post-form-lz64-batch-events-payload";
    let raw_payload = load_request_payload(title, SINGLE_EVENT_JSON);
    let lz64_payload = lz64_compress(title, raw_payload);
    let err_msg = format!(
        "failed to serialize LZ64 payload to urlencoded form in case: {}",
        title
    );
    let form_payload =
        serde_urlencoded::to_string([("data", lz64_payload), ("ver", "1.2.3".to_string())])
            .expect(&err_msg);

    let (router, _sink) = setup_capture_router(CaptureMode::Events, DEFAULT_TEST_TIME);
    let client = TestClient::new(router);

    let unix_millis_sent_at = iso8601_str_to_unix_millis(title, DEFAULT_TEST_TIME);
    let req_path = format!("/i/v0/e/?_={}&compression=lz64", unix_millis_sent_at);
    let req = client
        .post(&req_path)
        .body(form_payload)
        .header("Content-Type", "application/x-www-form-urlencoded")
        .header("X-Forwarded-For", "127.0.0.1");
    let res = req.send().await;

    // we expect this to fail while /batch/, /s/, and /i/v0/e/
    // are processed by handle_common, w/o LZ64 support
    assert_eq!(
        StatusCode::BAD_REQUEST,
        res.status(),
        "test {}: non-4xx response: {}",
        title,
        res.text().await
    );

    //validate_capture_response(title, res).await;

    // extract the processed events from the in-mem sink and validate contents
    //let got = sink.events();
    //validate_batch_events_payload(title, got);
}
