use axum_test_helper::TestClient;

use capture::config::CaptureMode;
use capture::integration_test_utils::{
    gzip_compress, iso8601_str_to_unix_millis, load_request_payload, lz64_compress,
    setup_capture_router, validate_batch_events_payload, validate_capture_response,
    BATCH_EVENTS_JSON, DEFAULT_TEST_TIME,
};

#[tokio::test]
async fn simple_batch_events_payload() {
    let title = "simple-batch-events-payload";
    let raw_payload = load_request_payload(title, BATCH_EVENTS_JSON);

    let (router, sink) = setup_capture_router(CaptureMode::Events, DEFAULT_TEST_TIME);
    let client = TestClient::new(router);

    let unix_millis_sent_at = iso8601_str_to_unix_millis(title, DEFAULT_TEST_TIME);
    let req_path = format!("/batch/?_={}", unix_millis_sent_at);
    let req = client
        .post(&req_path)
        .body(raw_payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1");
    let res = req.send().await;

    validate_capture_response(title, res).await;

    // extract the processed events from the in-mem sink and validate contents
    let got = sink.events();
    validate_batch_events_payload(title, got);
}
