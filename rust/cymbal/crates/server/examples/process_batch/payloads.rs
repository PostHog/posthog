use cymbal_api::cymbal::v1::{BatchContext, ExceptionEvent, ProcessingOptions};

pub fn batch_context(batch_id: &str) -> BatchContext {
    BatchContext {
        batch_id: batch_id.to_string(),
        metadata: Default::default(),
    }
}

pub fn input_event(event_id: impl Into<String>, properties_json: Vec<u8>) -> ExceptionEvent {
    input_event_with_team(event_id, default_team_id(), properties_json)
}

pub fn default_team_id() -> i64 {
    std::env::var("CYMBAL_EXAMPLE_TEAM_ID")
        .ok()
        .and_then(|value| value.parse::<i64>().ok())
        .unwrap_or(2)
}

pub fn input_event_with_team(
    event_id: impl Into<String>,
    team_id: i64,
    properties_json: Vec<u8>,
) -> ExceptionEvent {
    let event_id = event_id.into();
    ExceptionEvent {
        distinct_id: format!("distinct-{event_id}"),
        event_id,
        team_id,
        timestamp: None,
        properties_json,
    }
}

pub fn sample_exception_properties(message: &str) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "event": "$exception",
        "$exception_message": message,
        "$exception_type": "Error",
        "$exception_list": [{
            "type": "Error",
            "value": message,
            "stacktrace": {
                "frames": [{
                    "filename": "app.js",
                    "function": "runSmokeTest",
                    "lineno": 10,
                    "colno": 5,
                }]
            }
        }]
    }))
    .expect("static smoke-test exception payload should serialize")
}

pub fn exception_without_stacktrace_properties(message: &str) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "event": "$exception",
        "$exception_message": message,
        "$exception_type": "StacklessError",
        "$exception_list": [{
            "type": "StacklessError",
            "value": message,
        }]
    }))
    .expect("static stackless exception payload should serialize")
}

pub fn multi_frame_exception_properties(message: &str) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "event": "$exception",
        "$exception_message": message,
        "$exception_type": "TypeError",
        "$exception_list": [{
            "type": "TypeError",
            "value": message,
            "stacktrace": {
                "frames": [
                    {
                        "filename": "vendor.js",
                        "function": "dispatch",
                        "lineno": 42,
                        "colno": 2,
                        "in_app": false,
                    },
                    {
                        "filename": "checkout.js",
                        "function": "submitOrder",
                        "lineno": 101,
                        "colno": 9,
                        "in_app": true,
                    },
                    {
                        "filename": "cart.js",
                        "function": "calculateTotal",
                        "lineno": 88,
                        "colno": 13,
                        "in_app": true,
                    }
                ]
            }
        }]
    }))
    .expect("static multi-frame exception payload should serialize")
}

pub fn empty_exception_list_properties(message: &str) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "event": "$exception",
        "$exception_message": message,
        "$exception_type": "EmptyExceptionList",
        "$exception_list": [],
    }))
    .expect("static empty exception-list payload should serialize")
}

pub fn manual_fingerprint_exception_properties(message: &str, fingerprint: &str) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "event": "$exception",
        "$exception_message": message,
        "$exception_type": "Error",
        "$exception_fingerprint": fingerprint,
        "$exception_list": [{
            "type": "Error",
            "value": message,
            "stacktrace": {
                "frames": [{
                    "filename": "manual.js",
                    "function": "runManualFingerprintExample",
                    "lineno": 20,
                    "colno": 7,
                }]
            }
        }]
    }))
    .expect("static manual fingerprint exception payload should serialize")
}

pub fn plain_event_properties(message: &str) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "event": "plain_event",
        "message": message,
        "feature": "cymbal-example",
    }))
    .expect("static plain event payload should serialize")
}

pub fn invalid_exception_list_properties(message: &str) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "event": "$exception",
        "$exception_message": message,
        "$exception_type": "Error",
        "$exception_list": "not-a-list",
    }))
    .expect("static invalid exception-list payload should serialize")
}

pub fn invalid_json_properties() -> Vec<u8> {
    br#"{"event":"$exception","$exception_message":"invalid json""#.to_vec()
}

pub fn default_processing_options() -> ProcessingOptions {
    ProcessingOptions {
        skip_alerting: false,
        emit_internal_events: true,
        emit_signals: true,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sample_payloads_cover_json_and_non_json_inputs() {
        assert!(
            serde_json::from_slice::<serde_json::Value>(&sample_exception_properties("boom"))
                .is_ok()
        );
        assert!(serde_json::from_slice::<serde_json::Value>(
            &manual_fingerprint_exception_properties("boom", "manual")
        )
        .is_ok());
        assert!(serde_json::from_slice::<serde_json::Value>(
            &exception_without_stacktrace_properties("stackless")
        )
        .is_ok());
        assert!(
            serde_json::from_slice::<serde_json::Value>(&multi_frame_exception_properties(
                "frames"
            ))
            .is_ok()
        );
        assert!(
            serde_json::from_slice::<serde_json::Value>(&empty_exception_list_properties("empty"))
                .is_ok()
        );
        assert!(
            serde_json::from_slice::<serde_json::Value>(&plain_event_properties("plain")).is_ok()
        );
        assert!(
            serde_json::from_slice::<serde_json::Value>(&invalid_exception_list_properties("bad"))
                .is_ok()
        );
        assert!(serde_json::from_slice::<serde_json::Value>(&invalid_json_properties()).is_err());
    }

    #[test]
    fn payload_variants_exercise_distinct_pipeline_paths() {
        let manual: serde_json::Value = serde_json::from_slice(
            &manual_fingerprint_exception_properties("manual", "manual-fingerprint"),
        )
        .unwrap();
        let empty: serde_json::Value =
            serde_json::from_slice(&empty_exception_list_properties("empty")).unwrap();
        let multiframe: serde_json::Value =
            serde_json::from_slice(&multi_frame_exception_properties("frames")).unwrap();
        let stackless: serde_json::Value =
            serde_json::from_slice(&exception_without_stacktrace_properties("stackless")).unwrap();

        assert_eq!(
            manual
                .pointer("/$exception_fingerprint")
                .and_then(serde_json::Value::as_str),
            Some("manual-fingerprint")
        );
        assert_eq!(
            empty
                .pointer("/$exception_list")
                .and_then(serde_json::Value::as_array)
                .unwrap()
                .len(),
            0
        );
        assert_eq!(
            multiframe
                .pointer("/$exception_list/0/stacktrace/frames")
                .and_then(serde_json::Value::as_array)
                .unwrap()
                .len(),
            3
        );
        assert!(stackless.pointer("/$exception_list/0/stacktrace").is_none());
    }
}
