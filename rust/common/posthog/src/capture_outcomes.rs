//! Bounded metric labels for capture outcomes: the per-event results in a 2xx
//! body and the terminal request errors. Every value comes from a fixed list,
//! so capture adding a new detail or error code cannot grow label cardinality.

use posthog::{CaptureErrorResponse, Error, EventResult, EventStatus};

const QUOTA_DETAILS: &[&str] = &[
    "events_over_quota",
    "exceptions_over_quota",
    "llm_events_over_quota",
    "survey_responses_over_quota",
    "over_quota",
];
const RETRY_DETAILS: &[&str] = &["not_persisted", "ai_byte_rate_limited"];
const RESTRICTION_DETAILS: &[&str] = &["event_restriction_drop", "non_historical_import_drop"];
const VALIDATION_DETAILS: &[&str] = &[
    "missing_event_name",
    "event_name_too_long",
    "missing_distinct_id",
    "distinct_id_too_large",
    "invalid_event_timestamp",
    "malformed_event_properties",
    "invalid_options",
    "dropped_performance_event",
    "duplicate_event_uuid",
    "ai_event_too_big",
    "misrouted_event",
];
const WARNING_DETAILS: &[&str] = &["person_processing_disabled"];

/// Request-level error codes capture v1 returns in its error body (`error`).
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

/// The labels for one per-event result from a 2xx response.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventOutcome {
    /// `ok`, `warning`, `drop`, `retry` or `unknown`.
    pub result: &'static str,
    /// `none`, `quota`, `retry`, `restriction`, `validation`, `warning` or `other`.
    pub class: &'static str,
    /// The capture detail, `none` when absent, or `other` when not in the known list.
    pub detail: &'static str,
}

impl EventOutcome {
    /// An event the SDK submitted that the response did not mention.
    pub const UNACCOUNTED: EventOutcome = EventOutcome {
        result: "unaccounted",
        class: "other",
        detail: "none",
    };

    /// A later copy of a uuid that capture dropped in favor of the first copy.
    pub const DUPLICATE_COPY: EventOutcome = EventOutcome {
        result: "drop",
        class: "validation",
        detail: "duplicate_event_uuid",
    };
}

/// The labels for one terminal request failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RequestOutcome {
    /// The HTTP status as a string, or `transport`, `timeout` or `serialization`.
    pub status: String,
    /// The capture error code from the response body, or a class when there is none.
    pub error: &'static str,
}

pub fn event_outcome(result: &EventResult) -> EventOutcome {
    let detail = result.details.as_deref();
    let known = detail.and_then(known_detail);
    let class = match known {
        Some(d) if QUOTA_DETAILS.contains(&d) => "quota",
        Some(d) if RETRY_DETAILS.contains(&d) => "retry",
        Some(d) if RESTRICTION_DETAILS.contains(&d) => "restriction",
        Some(d) if VALIDATION_DETAILS.contains(&d) => "validation",
        Some(_) => "warning",
        None if detail.is_some() => "other",
        None => "none",
    };
    EventOutcome {
        result: status_label(&result.result),
        class,
        detail: match (detail, known) {
            (None, _) => "none",
            (Some(_), Some(d)) => d,
            (Some(_), None) => "other",
        },
    }
}

pub fn request_outcome(err: &Error) -> RequestOutcome {
    let (status, error): (String, &'static str) = match err {
        Error::BillingLimitExceeded(body) => (
            "402".into(),
            body_error(body).unwrap_or("billing_limit_exceeded"),
        ),
        Error::Unauthorized => ("401".into(), "unauthorized"),
        Error::RateLimit => ("429".into(), "rate_limited"),
        Error::BadRequest(body) => {
            let code = body_error(body);
            let status = if code == Some("payload_too_large") {
                "413"
            } else {
                "400"
            };
            (status.into(), code.unwrap_or("bad_request"))
        }
        Error::ServerError { status, message } => (
            status.to_string(),
            body_error(message).unwrap_or("server_error"),
        ),
        Error::Connection(message) => connection_outcome(message),
        Error::Serialization(_) => ("serialization".into(), "serialization"),
        _ => ("other".into(), "other"),
    };
    RequestOutcome { status, error }
}

fn status_label(status: &EventStatus) -> &'static str {
    match status {
        EventStatus::Ok => "ok",
        EventStatus::Warning => "warning",
        EventStatus::Drop => "drop",
        EventStatus::Retry => "retry",
        _ => "unknown",
    }
}

fn known_detail(detail: &str) -> Option<&'static str> {
    [
        QUOTA_DETAILS,
        RETRY_DETAILS,
        RESTRICTION_DETAILS,
        VALIDATION_DETAILS,
        WARNING_DETAILS,
    ]
    .iter()
    .flat_map(|list| list.iter())
    .find(|known| **known == detail)
    .copied()
}

fn body_error(body: &str) -> Option<&'static str> {
    let parsed: CaptureErrorResponse = serde_json::from_str(body).ok()?;
    REQUEST_ERRORS
        .iter()
        .find(|known| **known == parsed.error)
        .copied()
}

/// The SDK reports a non-mapped HTTP status as `Unexpected HTTP status <code>: <body>`
/// and a transport failure with reqwest's message, which says "timed out" on a timeout.
fn connection_outcome(message: &str) -> (String, &'static str) {
    if let Some(rest) = message.strip_prefix("Unexpected HTTP status ") {
        let code: String = rest.chars().take_while(char::is_ascii_digit).collect();
        if code.len() == 3 {
            let error = rest
                .split_once(": ")
                .and_then(|(_, body)| body_error(body))
                .unwrap_or("unexpected_status");
            return (code, error);
        }
    }
    if message.contains("timed out") {
        return ("timeout".into(), "timeout");
    }
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
                Error::Connection("error sending request: operation timed out".into()),
                "timeout",
                "timeout",
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
