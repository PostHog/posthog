use opentelemetry_proto::tonic::collector::logs::v1::ExportLogsServiceRequest;
use opentelemetry_proto::tonic::logs::v1::LogRecord;
use prost::Message;
use serde_json::{Map, Value};
use uuid::Uuid;

use super::fan_out::{
    any_value_to_json, apply_geoip_default, attributes_to_map, filter_resource_attributes,
    nanos_to_datetime, SpanEvent,
};
use super::identity::extract_distinct_id_for_span;

pub const EVALUATION_EVENT_NAME: &str = "gen_ai.evaluation.result";

const EVALUATION_NAME: &str = "gen_ai.evaluation.name";
const SCORE_VALUE: &str = "gen_ai.evaluation.score.value";
const SCORE_LABEL: &str = "gen_ai.evaluation.score.label";
const EXPLANATION: &str = "gen_ai.evaluation.explanation";

pub fn count_records(request: &ExportLogsServiceRequest) -> usize {
    request
        .resource_logs
        .iter()
        .flat_map(|resource_logs| &resource_logs.scope_logs)
        .map(|scope_logs| scope_logs.log_records.len())
        .sum()
}

pub fn expand_into_events(
    request: &ExportLogsServiceRequest,
    request_fallback_distinct_id: &str,
) -> Vec<SpanEvent> {
    let mut events =
        Vec::with_capacity(count_records(request).min(super::MAX_AI_EVENTS_PER_REQUEST));

    for resource_logs in &request.resource_logs {
        let resource_attributes = resource_logs
            .resource
            .as_ref()
            .map(|resource| filter_resource_attributes(&resource.attributes))
            .unwrap_or_default();

        for scope_logs in &resource_logs.scope_logs {
            for record in &scope_logs.log_records {
                let Some(event) = evaluation_event(
                    record,
                    &resource_attributes,
                    resource_logs.resource.as_ref(),
                    request_fallback_distinct_id,
                ) else {
                    continue;
                };
                events.push(event);
            }
        }
    }

    events
}

fn evaluation_event(
    record: &LogRecord,
    resource_attributes: &Map<String, Value>,
    resource: Option<&opentelemetry_proto::tonic::resource::v1::Resource>,
    request_fallback_distinct_id: &str,
) -> Option<SpanEvent> {
    if record.event_name != EVALUATION_EVENT_NAME {
        return None;
    }

    let attributes = attributes_to_map(&record.attributes);
    let evaluation_name = attributes
        .get(EVALUATION_NAME)?
        .as_str()?
        .trim()
        .to_string();
    if evaluation_name.is_empty() {
        return None;
    }

    let score_label = attributes
        .get(SCORE_LABEL)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|label| !label.is_empty())
        .map(str::to_string);
    let score_value = attributes.get(SCORE_VALUE).and_then(Value::as_f64);
    if score_label.is_none() && score_value.is_none() {
        return None;
    }

    let distinct_id =
        extract_distinct_id_for_span(&record.attributes, resource, request_fallback_distinct_id);
    let mut properties = resource_attributes.clone();
    properties.extend(attributes);
    apply_geoip_default(&mut properties);

    properties.insert(
        "$ai_evaluation_id".to_string(),
        Value::String(evaluation_id(record).to_string()),
    );
    properties.insert(
        "$ai_evaluation_name".to_string(),
        Value::String(evaluation_name),
    );
    properties.insert(
        "$ai_evaluation_runtime".to_string(),
        Value::String("otel".to_string()),
    );
    properties.insert(
        "$ai_ingestion_source".to_string(),
        Value::String("otel".to_string()),
    );

    if record.trace_id.len() == 16 {
        properties.insert(
            "$ai_trace_id".to_string(),
            Value::String(hex::encode(&record.trace_id)),
        );
    }
    if record.span_id.len() == 8 {
        properties.insert(
            "$ai_target_span_id".to_string(),
            Value::String(hex::encode(&record.span_id)),
        );
    }
    if let Some(label) = score_label.as_deref() {
        properties.insert(
            "$ai_evaluation_score_label".to_string(),
            Value::String(label.to_string()),
        );
        properties.insert(
            "$ai_evaluation_result".to_string(),
            Value::String(label.to_string()),
        );
        properties.insert(
            "$ai_evaluation_result_type".to_string(),
            Value::String("label".to_string()),
        );
    }
    if let Some(value) = score_value {
        if let Some(number) = serde_json::Number::from_f64(value) {
            properties.insert(
                "$ai_evaluation_score_value".to_string(),
                Value::Number(number.clone()),
            );
            if score_label.is_none() {
                properties.insert("$ai_evaluation_result".to_string(), Value::Number(number));
                properties.insert(
                    "$ai_evaluation_result_type".to_string(),
                    Value::String("number".to_string()),
                );
            }
        }
    }
    if let Some(explanation) = properties.get(EXPLANATION).and_then(Value::as_str) {
        properties.insert(
            "$ai_evaluation_reasoning".to_string(),
            Value::String(explanation.to_string()),
        );
    }
    if let Some(body) = record.body.as_ref().and_then(|body| body.value.as_ref()) {
        properties.insert("$otel_log_body".to_string(), any_value_to_json(body));
    }

    let timestamp_nanos = if record.time_unix_nano != 0 {
        record.time_unix_nano
    } else {
        record.observed_time_unix_nano
    };

    Some(SpanEvent {
        event_name: "$ai_evaluation".to_string(),
        distinct_id,
        properties: Value::Object(properties),
        timestamp: nanos_to_datetime(timestamp_nanos),
    })
}

fn evaluation_id(record: &LogRecord) -> Uuid {
    Uuid::new_v5(&Uuid::NAMESPACE_URL, &record.encode_to_vec())
}

#[cfg(test)]
mod tests {
    use opentelemetry_proto::tonic::collector::logs::v1::ExportLogsServiceRequest;
    use opentelemetry_proto::tonic::common::v1::{any_value, AnyValue, KeyValue};
    use opentelemetry_proto::tonic::logs::v1::{LogRecord, ResourceLogs, ScopeLogs};
    use opentelemetry_proto::tonic::resource::v1::Resource;

    use super::*;

    fn string_attribute(key: &str, value: &str) -> KeyValue {
        KeyValue {
            key: key.to_string(),
            value: Some(AnyValue {
                value: Some(any_value::Value::StringValue(value.to_string())),
            }),
        }
    }

    fn double_attribute(key: &str, value: f64) -> KeyValue {
        KeyValue {
            key: key.to_string(),
            value: Some(AnyValue {
                value: Some(any_value::Value::DoubleValue(value)),
            }),
        }
    }

    fn request(record: LogRecord) -> ExportLogsServiceRequest {
        ExportLogsServiceRequest {
            resource_logs: vec![ResourceLogs {
                resource: Some(Resource {
                    attributes: vec![string_attribute("posthog.distinct_id", "user-1")],
                    dropped_attributes_count: 0,
                }),
                scope_logs: vec![ScopeLogs {
                    scope: None,
                    log_records: vec![record],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            }],
        }
    }

    fn evaluation_record() -> LogRecord {
        LogRecord {
            time_unix_nano: 1_704_067_200_000_000_000,
            trace_id: vec![1; 16],
            span_id: vec![2; 8],
            event_name: EVALUATION_EVENT_NAME.to_string(),
            attributes: vec![
                string_attribute(EVALUATION_NAME, "correctness"),
                double_attribute(SCORE_VALUE, 0.9),
                string_attribute(SCORE_LABEL, "pass"),
                string_attribute(EXPLANATION, "grounded in context"),
            ],
            ..Default::default()
        }
    }

    #[test]
    fn maps_evaluation_result_event() {
        let events = expand_into_events(&request(evaluation_record()), "fallback");

        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_name, "$ai_evaluation");
        assert_eq!(events[0].distinct_id, "user-1");
        assert_eq!(events[0].properties["$ai_evaluation_name"], "correctness");
        assert_eq!(events[0].properties["$ai_evaluation_score_label"], "pass");
        assert_eq!(events[0].properties["$ai_evaluation_score_value"], 0.9);
        assert_eq!(events[0].properties["$ai_evaluation_runtime"], "otel");
        assert_eq!(events[0].properties["$ai_trace_id"], hex::encode([1; 16]));
        assert_eq!(
            events[0].properties["$ai_target_span_id"],
            hex::encode([2; 8])
        );
        assert_eq!(
            events[0].properties["$ai_evaluation_reasoning"],
            "grounded in context"
        );
    }

    #[test]
    fn evaluation_id_is_stable_for_replays() {
        let request = request(evaluation_record());

        let first = expand_into_events(&request, "fallback");
        let second = expand_into_events(&request, "fallback");

        assert_eq!(
            first[0].properties["$ai_evaluation_id"],
            second[0].properties["$ai_evaluation_id"]
        );
    }

    #[test]
    fn ignores_non_evaluation_records() {
        let record = LogRecord {
            event_name: "exception".to_string(),
            ..evaluation_record()
        };

        assert!(expand_into_events(&request(record), "fallback").is_empty());
    }

    #[test]
    fn ignores_evaluations_without_scores() {
        let record = LogRecord {
            attributes: vec![string_attribute(EVALUATION_NAME, "correctness")],
            ..evaluation_record()
        };

        assert!(expand_into_events(&request(record), "fallback").is_empty());
    }

    #[test]
    fn ignores_blank_score_labels_without_numeric_scores() {
        let record = LogRecord {
            attributes: vec![
                string_attribute(EVALUATION_NAME, "correctness"),
                string_attribute(SCORE_LABEL, "  "),
            ],
            ..evaluation_record()
        };

        assert!(expand_into_events(&request(record), "fallback").is_empty());
    }

    #[test]
    fn ignores_non_string_explanations() {
        let record = LogRecord {
            attributes: vec![
                string_attribute(EVALUATION_NAME, "correctness"),
                double_attribute(SCORE_VALUE, 0.9),
                double_attribute(EXPLANATION, 1.0),
            ],
            ..evaluation_record()
        };

        let events = expand_into_events(&request(record), "fallback");

        assert!(events[0]
            .properties
            .get("$ai_evaluation_reasoning")
            .is_none());
    }
}
