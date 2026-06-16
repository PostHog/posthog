use opentelemetry_proto::tonic::trace::v1::{span, status::StatusCode, Span};
use serde_json::{Map, Value};

use super::fan_out::attributes_to_map;

const HTTP_STATUS_KEYS: &[&str] = &[
    "$ai_http_status",
    "http.response.status_code",
    "http.status_code",
    "http.status",
    "status_code",
    "error.status_code",
    "exception.status_code",
];

fn http_status_from_value(value: &Value) -> Option<i64> {
    match value {
        Value::Number(n) => n.as_i64().filter(|status| (100..=599).contains(status)),
        Value::String(s) => s
            .parse::<i64>()
            .ok()
            .filter(|status| (100..=599).contains(status)),
        _ => None,
    }
}

fn http_status_from_attrs(attrs: &Map<String, Value>) -> Option<i64> {
    HTTP_STATUS_KEYS
        .iter()
        .find_map(|key| attrs.get(*key).and_then(http_status_from_value))
}

fn first_http_status_in_text(text: &str) -> Option<i64> {
    let mut digits = String::new();
    for ch in text.chars() {
        if ch.is_ascii_digit() {
            digits.push(ch);
            if digits.len() > 3 {
                digits.clear();
            }
            continue;
        }

        if digits.len() == 3 {
            if let Ok(status) = digits.parse::<i64>() {
                if (100..=599).contains(&status) {
                    return Some(status);
                }
            }
        }
        digits.clear();
    }

    if digits.len() == 3 {
        digits
            .parse::<i64>()
            .ok()
            .filter(|status| (100..=599).contains(status))
    } else {
        None
    }
}

fn http_status_from_text(text: &str) -> Option<i64> {
    let lower = text.to_ascii_lowercase();

    for marker in ["http", "status"] {
        let mut offset = 0;
        while let Some(index) = lower[offset..].find(marker) {
            let window_start = offset + index + marker.len();
            let window: String = text[window_start..].chars().take(40).collect();
            if let Some(status) = first_http_status_in_text(&window) {
                return Some(status);
            }
            offset = window_start;
        }
    }

    None
}

fn http_status_from_error_attrs(attrs: &Map<String, Value>) -> Option<i64> {
    ["exception.message", "error.message"]
        .iter()
        .find_map(|key| {
            attrs
                .get(*key)
                .and_then(Value::as_str)
                .and_then(http_status_from_text)
        })
}

fn latest_exception_event(span: &Span) -> Option<&span::Event> {
    span.events.iter().rev().find(|event| {
        event.name == "exception"
            || event
                .attributes
                .iter()
                .any(|kv| kv.key == "exception.message" || kv.key == "exception.type")
    })
}

fn error_message_from_exception(event: &span::Event) -> Option<String> {
    let attrs = attributes_to_map(&event.attributes);
    let message = attrs.get("exception.message").and_then(Value::as_str);
    let error_type = attrs.get("exception.type").and_then(Value::as_str);

    match (error_type, message) {
        (Some(error_type), Some(message)) if !error_type.is_empty() && !message.is_empty() => {
            Some(format!("{error_type}: {message}"))
        }
        (_, Some(message)) if !message.is_empty() => Some(message.to_string()),
        (Some(error_type), _) if !error_type.is_empty() => Some(error_type.to_string()),
        _ => None,
    }
}

pub fn apply_error_status_properties(span: &Span, properties: &mut Map<String, Value>) {
    let Some(status) = span.status.as_ref() else {
        return;
    };

    if StatusCode::try_from(status.code) != Ok(StatusCode::Error) {
        return;
    }

    properties.insert("$ai_is_error".to_string(), Value::Bool(true));

    if !properties.contains_key("$ai_error") {
        let error = latest_exception_event(span)
            .and_then(error_message_from_exception)
            .or_else(|| (!status.message.is_empty()).then(|| status.message.clone()))
            .unwrap_or_else(|| "OpenTelemetry span status error".to_string());
        properties.insert("$ai_error".to_string(), Value::String(error));
    }

    if !properties.contains_key("$ai_http_status") {
        let event_status = latest_exception_event(span)
            .map(|event| attributes_to_map(&event.attributes))
            .and_then(|attrs| {
                http_status_from_attrs(&attrs).or_else(|| http_status_from_error_attrs(&attrs))
            });
        let http_status = event_status
            .or_else(|| http_status_from_attrs(properties))
            .or_else(|| http_status_from_text(&status.message))
            .unwrap_or(500);
        properties.insert(
            "$ai_http_status".to_string(),
            Value::Number(http_status.into()),
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use opentelemetry_proto::tonic::common::v1::{any_value, AnyValue, KeyValue};
    use opentelemetry_proto::tonic::trace::v1::Status;

    fn make_kv(key: &str, value: any_value::Value) -> KeyValue {
        KeyValue {
            key: key.to_string(),
            value: Some(AnyValue { value: Some(value) }),
        }
    }

    fn make_span(attributes: Vec<KeyValue>) -> Span {
        Span {
            attributes,
            ..Default::default()
        }
    }

    #[test]
    fn test_error_status_maps_exception_event() {
        let mut span = make_span(vec![make_kv(
            "http.response.status_code",
            any_value::Value::IntValue(429),
        )]);
        span.status = Some(Status {
            code: StatusCode::Error as i32,
            message: "rate limited".to_string(),
        });
        span.events = vec![span::Event {
            name: "exception".to_string(),
            attributes: vec![
                make_kv(
                    "exception.type",
                    any_value::Value::StringValue("RateLimitError".to_string()),
                ),
                make_kv(
                    "exception.message",
                    any_value::Value::StringValue("Too many requests".to_string()),
                ),
            ],
            ..Default::default()
        }];
        let mut properties = attributes_to_map(&span.attributes);

        apply_error_status_properties(&span, &mut properties);

        assert_eq!(properties["$ai_is_error"], Value::Bool(true));
        assert_eq!(
            properties["$ai_error"],
            Value::String("RateLimitError: Too many requests".to_string())
        );
        assert_eq!(properties["$ai_http_status"], Value::Number(429.into()));
    }

    #[test]
    fn test_error_status_falls_back_to_status_message_and_500() {
        let mut span = make_span(vec![]);
        span.status = Some(Status {
            code: StatusCode::Error as i32,
            message: "provider failed".to_string(),
        });
        let mut properties = Map::new();

        apply_error_status_properties(&span, &mut properties);

        assert_eq!(properties["$ai_is_error"], Value::Bool(true));
        assert_eq!(
            properties["$ai_error"],
            Value::String("provider failed".to_string())
        );
        assert_eq!(properties["$ai_http_status"], Value::Number(500.into()));
    }

    #[test]
    fn test_error_status_recovers_http_status_from_error_message() {
        let mut span = make_span(vec![]);
        span.status = Some(Status {
            code: StatusCode::Error as i32,
            message: "Status code: 429".to_string(),
        });
        span.events = vec![span::Event {
            name: "exception".to_string(),
            attributes: vec![make_kv(
                "exception.message",
                any_value::Value::StringValue("Provider failed with HTTP 429".to_string()),
            )],
            ..Default::default()
        }];
        let mut properties = Map::new();

        apply_error_status_properties(&span, &mut properties);

        assert_eq!(properties["$ai_is_error"], Value::Bool(true));
        assert_eq!(properties["$ai_http_status"], Value::Number(429.into()));
    }

    #[test]
    fn test_ok_status_does_not_mark_error() {
        let mut span = make_span(vec![]);
        span.status = Some(Status {
            code: StatusCode::Ok as i32,
            message: String::new(),
        });
        span.events = vec![span::Event {
            name: "exception".to_string(),
            attributes: vec![make_kv(
                "exception.message",
                any_value::Value::StringValue("not a span failure".to_string()),
            )],
            ..Default::default()
        }];
        let mut properties = Map::new();

        apply_error_status_properties(&span, &mut properties);

        assert!(!properties.contains_key("$ai_is_error"));
        assert!(!properties.contains_key("$ai_error"));
        assert!(!properties.contains_key("$ai_http_status"));
    }

    #[test]
    fn test_error_status_preserves_explicit_error_attributes() {
        let mut span = make_span(vec![]);
        span.status = Some(Status {
            code: StatusCode::Error as i32,
            message: "provider failed".to_string(),
        });
        let mut properties = Map::from_iter([
            ("$ai_error".to_string(), Value::String("custom".to_string())),
            ("$ai_is_error".to_string(), Value::Bool(false)),
            ("$ai_http_status".to_string(), Value::Number(418.into())),
        ]);

        apply_error_status_properties(&span, &mut properties);

        assert_eq!(properties["$ai_is_error"], Value::Bool(true));
        assert_eq!(properties["$ai_error"], Value::String("custom".to_string()));
        assert_eq!(properties["$ai_http_status"], Value::Number(418.into()));
    }
}
