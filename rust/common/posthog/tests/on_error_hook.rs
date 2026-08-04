//! End-to-end coverage for the `on_error` hook wired in `common_posthog::init`:
//! a terminal capture failure must emit `posthog_sdk_delivery_failures_total`
//! with the right `service`/`surface`/`reason` labels.
//!
//! One test per binary: `init` builds a process-global PostHog client and the
//! DebuggingRecorder installs a process-global metrics recorder. The hook fires
//! on the SDK's background worker thread, so a thread-local recorder would miss
//! it — the recorder must be global.

use std::collections::HashMap;

use httpmock::prelude::*;
use metrics_util::debugging::{DebugValue, DebuggingRecorder};

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

    posthog_rs::capture(posthog_rs::Event::new_anon("test_event"));
    posthog_rs::flush().await;

    mock.assert_async().await;

    let hit = snapshotter
        .snapshot()
        .into_vec()
        .into_iter()
        .find_map(|(key, _, _, value)| {
            if key.key().name() != "posthog_sdk_delivery_failures_total" {
                return None;
            }
            let labels: HashMap<String, String> = key
                .key()
                .labels()
                .map(|l| (l.key().to_string(), l.value().to_string()))
                .collect();
            match value {
                DebugValue::Counter(c) => Some((labels, c)),
                _ => None,
            }
        });

    let (labels, count) =
        hit.expect("terminal capture reject must emit the delivery-failure metric");
    assert_eq!(count, 1, "one terminal failure => one increment");
    assert_eq!(labels.get("service").map(String::as_str), Some("test-svc"));
    assert_eq!(labels.get("surface").map(String::as_str), Some("capture"));
    assert_eq!(
        labels.get("reason").map(String::as_str),
        Some("bad_request"),
        "HTTP 400 must classify as bad_request",
    );
}
