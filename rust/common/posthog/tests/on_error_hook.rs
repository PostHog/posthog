//! End-to-end coverage for the `on_error` hook wired in `common_posthog::init`:
//! a terminal capture failure must emit `posthog_sdk_delivery_failures_total`
//! with the right `service`/`surface`/`reason` labels.
//!
//! One test per binary: `init` builds a process-global PostHog client and the
//! DebuggingRecorder installs a process-global metrics recorder. The hook fires
//! on the SDK's background worker thread, so a thread-local recorder would miss
//! it — the recorder must be global.

mod support;

use httpmock::prelude::*;
use metrics_util::debugging::DebuggingRecorder;

#[tokio::test]
async fn init_hook_emits_delivery_failure_metric_on_terminal_reject() {
    let recorder = DebuggingRecorder::new();
    let snapshotter = recorder.snapshotter();
    recorder
        .install()
        .expect("no global recorder should be installed yet in this test binary");

    // 400 is a permanent reject: the SDK does not retry it, so the hook fires
    // after a single attempt and `flush` returns once that attempt is done.
    let server = MockServer::start_async().await;
    let mock = server
        .mock_async(|when, then| {
            when.method(POST);
            then.status(400).body("bad request");
        })
        .await;

    common_posthog::init("test-svc", Some("test-key"), &server.base_url())
        .await
        .expect("init should succeed when an api key is provided");

    posthog::capture(posthog::Event::new_anon("test_event"));
    posthog::flush().await;

    mock.assert_async().await;

    let (labels, count) = support::counter(&snapshotter, "posthog_sdk_delivery_failures_total")
        .expect("terminal capture reject must emit the delivery-failure metric");
    assert_eq!(count, 1, "one terminal failure => one increment");
    assert_eq!(
        labels,
        support::labels(&[
            ("service", "test-svc"),
            ("surface", "capture"),
            ("reason", "bad_request")
        ]),
        "HTTP 400 must classify as bad_request",
    );

    let (labels, count) =
        support::counter(&snapshotter, "posthog_sdk_capture_request_failures_total")
            .expect("a terminal request failure must emit the request-failure metric");
    assert_eq!(count, 1);
    assert_eq!(
        labels,
        support::labels(&[
            ("service", "test-svc"),
            ("status", "400"),
            ("error", "bad_request")
        ]),
    );
    assert!(
        support::counter(&snapshotter, "posthog_sdk_capture_unpersisted_events_total").is_none(),
        "a request failure carries no per-event results",
    );
}
