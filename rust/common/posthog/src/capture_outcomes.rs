//! Metric labels for capture outcomes, from fixed lists so label cardinality stays bounded.

use posthog::{CaptureErrorResponse, Error, EventResult, EventStatus};

const DETAIL_CLASSES: &[(&str, &str)] = &[
    ("events_over_quota", "quota"),
    ("exceptions_over_quota", "quota"),
    ("llm_events_over_quota", "quota"),
    ("survey_responses_over_quota", "quota"),
    ("over_quota", "quota"),
    ("not_persisted", "retry"),
    ("ai_byte_rate_limited", "rate_limit"),
    ("rejected", "server"),
    ("event_restriction_drop", "restriction"),
    ("non_historical_import_drop", "restriction"),
    ("missing_event_name", "validation"),
    ("event_name_too_long", "validation"),
    ("missing_distinct_id", "validation"),
    ("distinct_id_too_large", "validation"),
    ("invalid_event_timestamp", "validation"),
    ("malformed_event_properties", "validation"),
    ("invalid_options", "validation"),
    ("dropped_performance_event", "validation"),
    ("duplicate_event_uuid", "validation"),
    ("ai_event_too_big", "validation"),
    ("misrouted_event", "validation"),
    ("event_too_big", "validation"),
    ("serialization_failed", "validation"),
    ("gateway_props_unparseable", "validation"),
    ("person_processing_disabled", "warning"),
];

const REQUEST_ERRORS: &[&str] = &[
    "missing_required_headers",
    "invalid_header_value",
    "invalid_query_param",
    "missing_query_params",
    "request_decoding_error",
    "request_parsing_error",
    "empty_body",
    "empty_batch",
    "invalid_batch",
    "missing_event_name",
    "event_name_too_long",
    "missing_distinct_id",
    "distinct_id_too_large",
    "missing_event_uuid",
    "invalid_event_uuid",
    "invalid_event_timestamp",
    "malformed_event_properties",
    "dropped_performance_event",
    "request_timeout",
    "body_read_timeout",
    "missing_authorization",
    "invalid_api_token",
    "payload_too_large",
    "unsupported_content_type",
    "unsupported_encoding",
    "billing_limit_exceeded",
    "internal_error",
    "service_unavailable",
    "gateway_timeout",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventOutcome {
    pub result: &'static str,
    pub class: &'static str,
    pub detail: &'static str,
}

impl EventOutcome {
    pub const UNACCOUNTED: EventOutcome = EventOutcome {
        result: "unaccounted",
        class: "other",
        detail: "none",
    };

    pub const DUPLICATE_COPY: EventOutcome = EventOutcome {
        result: "drop",
        class: "validation",
        detail: "duplicate_event_uuid",
    };
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RequestOutcome {
    pub status: String,
    pub error: &'static str,
}

pub fn event_outcome(result: &EventResult) -> EventOutcome {
    let label = match result.result {
        EventStatus::Ok => "ok",
        EventStatus::Warning => "warning",
        EventStatus::Drop => "drop",
        EventStatus::Retry => "retry",
        _ => "unknown",
    };
    let (detail, class) = match result.details.as_deref() {
        None => ("none", "none"),
        Some(detail) => DETAIL_CLASSES
            .iter()
            .find(|(known, _)| *known == detail)
            .copied()
            .unwrap_or(("other", "other")),
    };
    EventOutcome {
        result: label,
        class,
        detail,
    }
}

pub fn request_outcome(err: &Error) -> RequestOutcome {
    let (status, error) = match err {
        Error::BillingLimitExceeded(body) => {
            ("402".into(), body_error(body, "billing_limit_exceeded"))
        }
        Error::Unauthorized => ("401".into(), "unauthorized"),
        Error::RateLimit => ("429".into(), "rate_limited"),
        Error::BadRequest(body) => match body_error(body, "bad_request") {
            "payload_too_large" => ("413".into(), "payload_too_large"),
            code => ("400".into(), code),
        },
        Error::ServerError { status, message } => {
            (status.to_string(), body_error(message, "server_error"))
        }
        Error::Connection(message) => connection_outcome(message),
        Error::Serialization(_) => ("serialization".into(), "serialization"),
        _ => ("other".into(), "other"),
    };
    RequestOutcome { status, error }
}

fn body_error(body: &str, fallback: &'static str) -> &'static str {
    serde_json::from_str::<CaptureErrorResponse>(body)
        .ok()
        .and_then(|parsed| REQUEST_ERRORS.iter().find(|known| **known == parsed.error))
        .copied()
        .unwrap_or(fallback)
}

// The SDK reports an unmapped status as `Unexpected HTTP status <code>: <body>`.
fn connection_outcome(message: &str) -> (String, &'static str) {
    if let Some(rest) = message.strip_prefix("Unexpected HTTP status ") {
        if let Some((code, body)) = rest.split_once(": ") {
            if code.len() == 3 && code.bytes().all(|b| b.is_ascii_digit()) {
                return (code.to_string(), body_error(body, "unexpected_status"));
            }
        }
    }
    // Timeouts land here too: the SDK keeps only reqwest's top-level message, which omits the cause.
    ("transport".into(), "transport")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn result(status: EventStatus, details: Option<&str>) -> EventResult {
        serde_json::from_value(serde_json::json!({
            "result": match status {
                EventStatus::Ok => "ok",
                EventStatus::Warning => "warning",
                EventStatus::Drop => "drop",
                EventStatus::Retry => "retry",
                _ => "something_new",
            },
            "details": details,
        }))
        .unwrap()
    }

    #[test]
    fn event_outcome_classifies_every_known_detail() {
        let cases = [
            (EventStatus::Ok, None, ("ok", "none", "none")),
            (
                EventStatus::Warning,
                Some("person_processing_disabled"),
                ("warning", "warning", "person_processing_disabled"),
            ),
            (
                EventStatus::Drop,
                Some("events_over_quota"),
                ("drop", "quota", "events_over_quota"),
            ),
            (
                EventStatus::Drop,
                Some("llm_events_over_quota"),
                ("drop", "quota", "llm_events_over_quota"),
            ),
            (
                EventStatus::Retry,
                Some("not_persisted"),
                ("retry", "retry", "not_persisted"),
            ),
            (
                EventStatus::Drop,
                Some("event_restriction_drop"),
                ("drop", "restriction", "event_restriction_drop"),
            ),
            (
                EventStatus::Drop,
                Some("invalid_options"),
                ("drop", "validation", "invalid_options"),
            ),
            (
                EventStatus::Drop,
                Some("distinct_id_too_large"),
                ("drop", "validation", "distinct_id_too_large"),
            ),
            (
                EventStatus::Drop,
                Some("ai_byte_rate_limited"),
                ("drop", "rate_limit", "ai_byte_rate_limited"),
            ),
            (
                EventStatus::Drop,
                Some("rejected"),
                ("drop", "server", "rejected"),
            ),
            (
                EventStatus::Drop,
                Some("event_too_big"),
                ("drop", "validation", "event_too_big"),
            ),
            (
                EventStatus::Drop,
                Some("serialization_failed"),
                ("drop", "validation", "serialization_failed"),
            ),
            (
                EventStatus::Drop,
                Some("gateway_props_unparseable"),
                ("drop", "validation", "gateway_props_unparseable"),
            ),
            (
                EventStatus::Drop,
                Some("a_detail_capture_adds_later"),
                ("drop", "other", "other"),
            ),
        ];
        for (status, details, (result_label, class, detail)) in cases {
            assert_eq!(
                event_outcome(&result(status, details)),
                EventOutcome {
                    result: result_label,
                    class,
                    detail
                },
                "{details:?}"
            );
        }
    }

    #[test]
    fn event_outcome_labels_an_unknown_result_without_growing_labels() {
        let outcome = event_outcome(&result(EventStatus::Unknown, Some("whatever")));
        assert_eq!(
            outcome,
            EventOutcome {
                result: "unknown",
                class: "other",
                detail: "other"
            }
        );
    }

    #[test]
    fn request_outcome_maps_each_error_to_status_and_code() {
        let cases: Vec<(Error, &str, &str)> = vec![
            (
                Error::BillingLimitExceeded(r#"{"error":"billing_limit_exceeded"}"#.into()),
                "402",
                "billing_limit_exceeded",
            ),
            (
                Error::BillingLimitExceeded("not json".into()),
                "402",
                "billing_limit_exceeded",
            ),
            (Error::Unauthorized, "401", "unauthorized"),
            (Error::RateLimit, "429", "rate_limited"),
            (
                Error::BadRequest(r#"{"error":"payload_too_large"}"#.into()),
                "413",
                "payload_too_large",
            ),
            (
                Error::BadRequest(r#"{"error":"invalid_batch"}"#.into()),
                "400",
                "invalid_batch",
            ),
            (
                Error::BadRequest(r#"{"error":"brand_new_code"}"#.into()),
                "400",
                "bad_request",
            ),
            (
                Error::ServerError {
                    status: 503,
                    message: r#"{"error":"service_unavailable"}"#.into(),
                },
                "503",
                "service_unavailable",
            ),
            (
                Error::ServerError {
                    status: 500,
                    message: "oops".into(),
                },
                "500",
                "server_error",
            ),
            (
                Error::Connection(r#"Unexpected HTTP status 404: {"error":"x"}"#.into()),
                "404",
                "unexpected_status",
            ),
            (
                Error::Connection(
                    "error sending request for url (http://127.0.0.1:1/i/v1/analytics/events)"
                        .into(),
                ),
                "transport",
                "transport",
            ),
            (
                Error::Connection("connection refused".into()),
                "transport",
                "transport",
            ),
            (
                Error::Serialization("bad".into()),
                "serialization",
                "serialization",
            ),
        ];
        for (err, status, error) in cases {
            let got = request_outcome(&err);
            assert_eq!((got.status.as_str(), got.error), (status, error), "{err:?}");
        }
    }
}
