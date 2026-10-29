//! The surfacing features hold to ingestion's `SessionFeatureRecorder`: the vector holds fixture blocks and what the
//! TypeScript computes for each, and its own test there pins the TypeScript to it.

// One `json!` object per field of `FeatureEndResult`.
#![recursion_limit = "256"]

use replay_core_v4::inspect::features::{BlockFeatures, PATH_TOKENS};
use replay_core_v4::inspect::session::{BlockInspection, SessionInspector};
use replay_core_v4::scan::message::{read_message, Message};
use serde_json::{json, Map, Value};

const VECTOR: &str = include_str!(
    "../../../../nodejs/src/ingestion/pipelines/sessionreplay/sessions/session-feature-recorder-vector.json"
);

fn capture_message(window_id: &Value, events: &Value) -> Message {
    let inner = json!({"event": "$snapshot_items", "properties": {
        "$session_id": "session",
        "$window_id": window_id,
        "$snapshot_source": "web",
        "$snapshot_items": events,
    }});
    read_message(
        json!({"distinct_id": "d", "data": inner.to_string()})
            .to_string()
            .into_bytes(),
    )
    .unwrap()
}

/// The block's values as `FeatureEndResult` names them, with each visited URL as the md5 that ingestion stores.
fn as_typescript(features: &BlockFeatures) -> Value {
    let mut visited_urls: Vec<String> = features
        .visited_urls
        .iter()
        .map(|url| format!("{:x}", md5::compute(url)))
        .collect();
    visited_urls.sort_unstable();
    let path_token_counts: Map<String, Value> = PATH_TOKENS
        .iter()
        .zip(features.path_token_counts)
        .map(|((token, _), count)| ((*token).to_owned(), json!(count)))
        .collect();
    json!({
        "eventCount": features.event_count,
        "mousePositionCount": features.mouse_position_count,
        "mouseSumX": features.mouse_sum_x,
        "mouseSumXSquared": features.mouse_sum_x_squared,
        "mouseSumY": features.mouse_sum_y,
        "mouseSumYSquared": features.mouse_sum_y_squared,
        "mouseDistanceTraveled": features.mouse_distance_traveled,
        "mouseDirectionChangeCount": features.mouse_direction_change_count,
        "mouseVelocitySum": features.mouse_velocity_sum,
        "mouseVelocitySumOfSquares": features.mouse_velocity_sum_of_squares,
        "mouseVelocityCount": features.mouse_velocity_count,
        "scrollEventCount": features.scroll_event_count,
        "totalScrollMagnitude": features.total_scroll_magnitude,
        "scrollDirectionReversalCount": features.scroll_direction_reversal_count,
        "rapidScrollReversalCount": features.rapid_scroll_reversal_count,
        "scrollToTopCount": features.scroll_to_top_count,
        "clickCount": features.click_count,
        "keypressCount": features.keypress_count,
        "mouseActivityCount": features.mouse_activity_count,
        "rageClickCount": features.rage_click_count,
        "deadClickCount": features.dead_click_count,
        "backspaceCount": features.backspace_count,
        "interActionGapCount": features.inter_action_gap_count,
        "interActionGapSumMs": features.inter_action_gap_sum_ms,
        "interActionGapSumOfSquaresMs": features.inter_action_gap_sum_of_squares_ms,
        "maxIdleGapMs": features.max_idle_gap_ms,
        "longIdleGapCount": features.long_idle_gap_count,
        "quickBackCount": features.quick_back_count,
        "pageVisitCount": features.page_visit_count,
        "visitedUrls": visited_urls,
        "pathTokenCounts": path_token_counts,
        "consoleErrorCount": features.console_error_count,
        "consoleErrorAfterClickCount": features.console_error_after_click_count,
        "consoleWarnCount": features.console_warn_count,
        "networkRequestCount": features.network_request_count,
        "networkFailedRequestCount": features.network_failed_request_count,
        "network4xxCount": features.network_4xx_count,
        "network5xxCount": features.network_5xx_count,
        "networkRequestDurationSum": features.network_request_duration_sum,
        "networkRequestDurationSumOfSquares": features.network_request_duration_sum_of_squares,
        "networkRequestDurationCount": features.network_request_duration_count,
        "mutationCount": features.mutation_count,
        "viewportResizeCount": features.viewport_resize_count,
        "touchEventCount": features.touch_event_count,
        "maxScrollY": features.max_scroll_y,
        "clickTargetIds": features.click_target_ids,
        "formFieldIds": features.form_field_ids,
        "textSelectionCount": features.text_selection_count,
        "selectionCopyCount": features.selection_copy_count,
    })
}

/// Every number as an `f64`, so that JavaScript's `12` and Rust's `12.0` compare equal and floats compare exactly.
fn numbers_as_f64(value: Value) -> Value {
    match value {
        Value::Number(number) => json!(number.as_f64().unwrap()),
        Value::Array(items) => Value::Array(items.into_iter().map(numbers_as_f64).collect()),
        Value::Object(fields) => Value::Object(
            fields
                .into_iter()
                .map(|(key, value)| (key, numbers_as_f64(value)))
                .collect(),
        ),
        other => other,
    }
}

#[test]
fn computes_what_ingestions_feature_recorder_computes_for_each_block() {
    let vector: Value = serde_json::from_str(VECTOR).unwrap();
    let cases = vector["cases"].as_array().unwrap();
    assert!(!cases.is_empty());
    for case in cases {
        let mut session = SessionInspector::default();
        for (index, block) in case["blocks"].as_array().unwrap().iter().enumerate() {
            let mut inspection = BlockInspection::default();
            for message in block["messages"].as_array().unwrap() {
                let message = capture_message(&message["window_id"], &message["events"]);
                session.observe_message(&mut inspection, &message);
            }
            let features = inspection.finish().features;
            assert_eq!(
                numbers_as_f64(as_typescript(&features)),
                numbers_as_f64(block["expected"].clone()),
                "{}, block {index}",
                case["name"]
            );
        }
    }
}
