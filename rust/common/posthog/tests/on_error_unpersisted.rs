//! One test per binary: the client and the metrics recorder are process-global.

mod support;

use httpmock::prelude::*;
use metrics_util::debugging::DebuggingRecorder;
use uuid::Uuid;

#[tokio::test]
async fn init_hook_counts_events_dropped_inside_a_2xx() {
    let recorder = DebuggingRecorder::new();
    let snapshotter = recorder.snapshotter();
    recorder
        .install()
        .expect("no global recorder should be installed yet in this test binary");

    let uuid = Uuid::now_v7();
    // A `drop` is final, so the SDK does not retry and the hook fires after one attempt.
    let server = MockServer::start_async().await;
    let mock = server
        .mock_async(|when, then| {
            when.method(POST);
            then.status(200).body(
                serde_json::json!({
                    "results": { uuid.to_string(): { "result": "drop", "details": "invalid_options" } }
                })
                .to_string(),
            );
        })
        .await;

    common_posthog::init("test-svc", Some("test-key"), &server.base_url())
        .await
        .expect("init should succeed when an api key is provided");

    let mut event = posthog::Event::new("test_event", "user-1");
    event.set_uuid(uuid);
    posthog::capture(event);
    posthog::flush().await;

    mock.assert_async().await;

    let (labels, count) =
        support::counter(&snapshotter, "posthog_sdk_capture_unpersisted_events_total")
            .expect("an event dropped inside a 2xx must be counted");
    assert_eq!(count, 1);
    assert_eq!(
        labels,
        support::labels(&[
            ("service", "test-svc"),
            ("result", "drop"),
            ("class", "validation"),
            ("detail", "invalid_options"),
        ]),
    );
    assert!(support::counter(&snapshotter, "posthog_sdk_capture_request_failures_total").is_none());
}
