use std::sync::Arc;
use std::time::Duration;

use httpmock::prelude::*;
use serde_json::json;

#[derive(Debug)]
struct TestError;

impl std::fmt::Display for TestError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("handled telemetry test")
    }
}

impl std::error::Error for TestError {}

fn is_internal_panic_exception(req: &HttpMockRequest) -> bool {
    let Some(body) = req.body.as_deref() else {
        return false;
    };
    let Ok(body) = serde_json::from_slice::<serde_json::Value>(body) else {
        return false;
    };

    body.pointer("/batch/0/event").and_then(|v| v.as_str()) == Some("$exception")
        && body
            .pointer("/batch/0/properties/$exception_list/0/type")
            .and_then(|v| v.as_str())
            == Some("Panic")
        && body
            .pointer("/batch/0/properties/$exception_list/0/value")
            .and_then(|v| v.as_str())
            == Some("panic telemetry test")
        && body
            .pointer("/batch/0/properties/$exception_level")
            .and_then(|v| v.as_str())
            == Some("fatal")
        && body
            .pointer("/batch/0/properties/service")
            .and_then(|v| v.as_str())
            == Some("panic-test")
}

fn is_internal_handled_exception(req: &HttpMockRequest) -> bool {
    let Some(body) = req.body.as_deref() else {
        return false;
    };
    let Ok(body) = serde_json::from_slice::<serde_json::Value>(body) else {
        return false;
    };

    body.pointer("/batch/0/event").and_then(|v| v.as_str()) == Some("$exception")
        && body
            .pointer("/batch/0/properties/$exception_list/0/type")
            .and_then(|v| v.as_str())
            .is_some_and(|value| value.ends_with("TestError"))
        && body
            .pointer("/batch/0/properties/$exception_list/0/value")
            .and_then(|v| v.as_str())
            == Some("handled telemetry test")
        && body
            .pointer("/batch/0/properties/service")
            .and_then(|v| v.as_str())
            == Some("panic-test")
        && body
            .pointer("/batch/0/properties/request_id")
            .and_then(|v| v.as_str())
            == Some("req-1")
}

#[tokio::test]
async fn init_enables_panic_capture() {
    let posthog = MockServer::start_async().await;
    let capture = posthog
        .mock_async(|when, then| {
            when.method(POST)
                .path("/i/v1/analytics/events")
                .matches(is_internal_panic_exception);
            then.status(200).body("{\"results\":{}}");
        })
        .await;
    let handled_capture = posthog
        .mock_async(|when, then| {
            when.method(POST)
                .path("/i/v1/analytics/events")
                .matches(is_internal_handled_exception);
            then.status(200).body("{\"results\":{}}");
        })
        .await;
    std::panic::set_hook(Box::new(|_| {}));
    common_posthog::init("panic-test", Some("test-api-key"), &posthog.base_url())
        .await
        .expect("posthog init");

    common_posthog::capture_exception(Arc::new(TestError), [("request_id", json!("req-1"))]);
    posthog_rs::flush().await;
    for _ in 0..100 {
        if handled_capture.hits_async().await > 0 {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    handled_capture.assert_async().await;

    let panic = std::panic::catch_unwind(|| {
        panic!("panic telemetry test");
    });
    assert!(panic.is_err());
    drop(std::panic::take_hook());

    for _ in 0..100 {
        if capture.hits_async().await > 0 {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    capture.assert_async().await;
}
