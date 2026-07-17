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

fn is_word_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_'
}

fn has_marker_boundaries(text: &str, index: usize, marker: &str) -> bool {
    let bytes = text.as_bytes();
    let before = index == 0 || !is_word_byte(bytes[index - 1]);
    let after_index = index + marker.len();
    let after = after_index >= bytes.len() || !is_word_byte(bytes[after_index]);
    before && after
}

fn strip_word_prefix<'a>(text: &'a str, prefix: &str) -> Option<&'a str> {
    let trimmed = text.trim_start();
    let lower = trimmed.to_ascii_lowercase();
    if lower.starts_with(prefix) && has_marker_boundaries(&lower, 0, prefix) {
        return Some(&trimmed[prefix.len()..]);
    }
    None
}

fn http_status_at_start(text: &str) -> Option<i64> {
    let trimmed = text.trim_start();
    let bytes = trimmed.as_bytes();
    if bytes.len() < 3 || !bytes[..3].iter().all(u8::is_ascii_digit) {
        return None;
    }
    if let Some(next) = bytes.get(3) {
        if is_word_byte(*next) {
            return None;
        }
    }

    trimmed[..3]
        .parse::<i64>()
        .ok()
        .filter(|status| (100..=599).contains(status))
}

fn http_status_after_separator(text: &str, allow_bare_number: bool) -> Option<i64> {
    let trimmed = text.trim_start();
    if trimmed.starts_with("://") {
        return None;
    }

    if let Some(separator) = trimmed.chars().next().filter(|ch| matches!(ch, ':' | '=')) {
        return http_status_at_start(&trimmed[separator.len_utf8()..]);
    }

    allow_bare_number.then(|| http_status_at_start(trimmed))?
}

fn http_status_after_status_marker(text: &str) -> Option<i64> {
    if let Some(after_code) = strip_word_prefix(text, "code") {
        return http_status_after_separator(after_code, true);
    }
    http_status_after_separator(text, false)
}

fn http_status_after_http_marker(text: &str) -> Option<i64> {
    if let Some(after_status) = strip_word_prefix(text, "status") {
        return http_status_after_status_marker(after_status);
    }
    http_status_after_separator(text, true)
}

fn find_status_after_marker(
    text: &str,
    lower: &str,
    marker: &str,
    parser: fn(&str) -> Option<i64>,
) -> Option<i64> {
    let mut offset = 0;
    while let Some(index) = lower[offset..].find(marker) {
        let absolute_index = offset + index;
        let marker_end = absolute_index + marker.len();
        if has_marker_boundaries(lower, absolute_index, marker) {
            if let Some(status) = parser(&text[marker_end..]) {
                return Some(status);
            }
        }
        offset = marker_end;
    }
    None
}

fn http_status_from_text(text: &str) -> Option<i64> {
    let lower = text.to_ascii_lowercase();

    find_status_after_marker(text, &lower, "status_code", |text| {
        http_status_after_separator(text, true)
    })
    .or_else(|| {
        find_status_after_marker(text, &lower, "status code", |text| {
            http_status_after_separator(text, true)
        })
    })
    .or_else(|| find_status_after_marker(text, &lower, "status", http_status_after_status_marker))
    .or_else(|| find_status_after_marker(text, &lower, "http", http_status_after_http_marker))
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
    fn test_error_status_ignores_ambiguous_numbers_in_error_message() {
        let mut span = make_span(vec![]);
        span.status = Some(Status {
            code: StatusCode::Error as i32,
            message: "status of 200 records is unknown".to_string(),
        });
        span.events = vec![span::Event {
            name: "exception".to_string(),
            attributes: vec![make_kv(
                "exception.message",
                any_value::Value::StringValue(
                    "request to https://example.com/items/404 failed".to_string(),
                ),
            )],
            ..Default::default()
        }];
        let mut properties = Map::new();

        apply_error_status_properties(&span, &mut properties);

        assert_eq!(properties["$ai_is_error"], Value::Bool(true));
        assert_eq!(properties["$ai_http_status"], Value::Number(500.into()));
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
