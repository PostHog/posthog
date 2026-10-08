use opentelemetry_proto::tonic::common::v1::{any_value, KeyValue};
use opentelemetry_proto::tonic::resource::v1::Resource;
use uuid::Uuid;

/// Span-level keys checked in order. AI SDK metadata and runtime context are
/// both per-call, so they can identify spans from multi-tenant processes.
const SPAN_DISTINCT_ID_KEYS: &[&str] = &[
    "ai.telemetry.metadata.posthog_distinct_id",
    "ai.settings.context.posthog_distinct_id",
    "posthog.distinct_id",
    "user.id",
];

/// Resource-level keys are the per-process fallback used when no per-span
/// override is set.
const RESOURCE_DISTINCT_ID_KEYS: &[&str] = &["posthog.distinct_id", "user.id"];

/// A session can span several traces, so its id takes priority over the trace id.
const SESSION_ID_KEYS: &[&str] = &[
    "$ai_session_id",
    "anthropic.session.id",
    "gen_ai.conversation.id",
];

/// Changing this value gives every session and trace without an explicit distinct_id a new one.
const DERIVED_DISTINCT_ID_NAMESPACE: Uuid = Uuid::from_u128(0x392e81d53d134a6fb541bdbf6c865e56);

fn get_string_attr<'a>(attrs: &'a [KeyValue], key: &str) -> Option<&'a str> {
    attrs
        .iter()
        .find(|attr| attr.key == key)
        .and_then(|attr| attr.value.as_ref())
        .and_then(|v| v.value.as_ref())
        .and_then(|v| match v {
            any_value::Value::StringValue(s) if !s.is_empty() => Some(s.as_str()),
            _ => None,
        })
}

/// Resolve the distinct_id for a single span, with span attributes taking
/// precedence over resource attributes. A single OTLP request can carry spans
/// for multiple users (typical in serverless / multi-tenant runtimes), so
/// distinct_id must be resolved per-span rather than per-request.
pub fn extract_distinct_id_for_span(
    span_attrs: &[KeyValue],
    resource: Option<&Resource>,
    fallback: &str,
) -> String {
    for key in SPAN_DISTINCT_ID_KEYS {
        if let Some(id) = get_string_attr(span_attrs, key) {
            return id.to_string();
        }
    }
    if let Some(resource) = resource {
        for key in RESOURCE_DISTINCT_ID_KEYS {
            if let Some(id) = get_string_attr(&resource.attributes, key) {
                return id.to_string();
            }
        }
    }
    fallback.to_string()
}

/// One stable UUID per OTLP request, used as the last-resort fallback when no
/// span or resource attribute identifies the user. Sharing a single UUID
/// across all anonymous spans in a batch keeps them grouped on a single
/// distinct_id rather than scattering them across one-shot UUIDs.
pub fn request_fallback_distinct_id() -> String {
    Uuid::new_v4().to_string()
}

/// Distinct id for a span that names no user. The spans of one trace can arrive in separate
/// requests, and a session produces several traces, so the id is derived from the session id or
/// the trace id to keep them on one anonymous person. `request_fallback` covers a span that has
/// neither a session id nor a valid trace id.
pub fn span_fallback_distinct_id(
    span_attrs: &[KeyValue],
    trace_id: &[u8],
    request_fallback: &str,
) -> String {
    for key in SESSION_ID_KEYS {
        if let Some(session_id) = get_string_attr(span_attrs, key) {
            return derived_distinct_id(&format!("session:{session_id}"));
        }
    }
    if trace_id.iter().any(|byte| *byte != 0) {
        return derived_distinct_id(&format!("trace:{}", hex::encode(trace_id)));
    }
    request_fallback.to_string()
}

fn derived_distinct_id(name: &str) -> String {
    Uuid::new_v5(&DERIVED_DISTINCT_ID_NAMESPACE, name.as_bytes()).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use opentelemetry_proto::tonic::common::v1::AnyValue;

    fn make_kv(key: &str, value: any_value::Value) -> KeyValue {
        KeyValue {
            key: key.to_string(),
            value: Some(AnyValue { value: Some(value) }),
        }
    }

    fn string_kv(key: &str, value: &str) -> KeyValue {
        make_kv(key, any_value::Value::StringValue(value.to_string()))
    }

    fn resource_with(attrs: Vec<KeyValue>) -> Resource {
        Resource {
            attributes: attrs,
            dropped_attributes_count: 0,
        }
    }

    #[test]
    fn test_span_metadata_distinct_id_wins_over_resource() {
        let span_attrs = vec![string_kv(
            "ai.telemetry.metadata.posthog_distinct_id",
            "span-user",
        )];
        let resource = resource_with(vec![string_kv("posthog.distinct_id", "resource-user")]);
        assert_eq!(
            extract_distinct_id_for_span(&span_attrs, Some(&resource), "fallback"),
            "span-user"
        );
    }

    #[test]
    fn test_span_runtime_context_distinct_id_wins_over_resource() {
        let span_attrs = vec![string_kv(
            "ai.settings.context.posthog_distinct_id",
            "span-user",
        )];
        let resource = resource_with(vec![string_kv("posthog.distinct_id", "resource-user")]);
        assert_eq!(
            extract_distinct_id_for_span(&span_attrs, Some(&resource), "fallback"),
            "span-user"
        );
    }

    #[test]
    fn test_span_posthog_distinct_id_wins_over_user_id() {
        let span_attrs = vec![
            string_kv("user.id", "user-id-value"),
            string_kv("posthog.distinct_id", "posthog-id-value"),
        ];
        assert_eq!(
            extract_distinct_id_for_span(&span_attrs, None, "fallback"),
            "posthog-id-value"
        );
    }

    #[test]
    fn test_ai_telemetry_metadata_wins_over_posthog_distinct_id() {
        let span_attrs = vec![
            string_kv("posthog.distinct_id", "explicit"),
            string_kv("ai.telemetry.metadata.posthog_distinct_id", "metadata"),
        ];
        assert_eq!(
            extract_distinct_id_for_span(&span_attrs, None, "fallback"),
            "metadata"
        );
    }

    #[test]
    fn test_falls_back_to_resource_when_no_span_attrs() {
        let resource = resource_with(vec![string_kv("posthog.distinct_id", "resource-user")]);
        assert_eq!(
            extract_distinct_id_for_span(&[], Some(&resource), "fallback"),
            "resource-user"
        );
    }

    #[test]
    fn test_resource_user_id_used_when_no_posthog_id() {
        let resource = resource_with(vec![string_kv("user.id", "user-id-value")]);
        assert_eq!(
            extract_distinct_id_for_span(&[], Some(&resource), "fallback"),
            "user-id-value"
        );
    }

    #[test]
    fn test_resource_posthog_distinct_id_wins_over_user_id() {
        let resource = resource_with(vec![
            string_kv("user.id", "user-id-value"),
            string_kv("posthog.distinct_id", "posthog-id-value"),
        ]);
        assert_eq!(
            extract_distinct_id_for_span(&[], Some(&resource), "fallback"),
            "posthog-id-value"
        );
    }

    #[test]
    fn test_falls_back_when_no_attrs_present() {
        assert_eq!(
            extract_distinct_id_for_span(&[], None, "fallback-id"),
            "fallback-id"
        );
    }

    #[test]
    fn test_span_fallback_is_stable_per_trace_and_differs_across_traces() {
        let first = span_fallback_distinct_id(&[], &[1; 16], "request");
        assert_eq!(
            first,
            span_fallback_distinct_id(&[], &[1; 16], "other-request")
        );
        assert_ne!(first, span_fallback_distinct_id(&[], &[2; 16], "request"));
        assert_ne!(first, "request");
    }

    #[test]
    fn test_span_fallback_groups_the_traces_of_one_session() {
        for key in SESSION_ID_KEYS {
            let attrs = vec![string_kv(key, "session-1")];
            let first = span_fallback_distinct_id(&attrs, &[1; 16], "request");
            assert_eq!(
                first,
                span_fallback_distinct_id(&attrs, &[2; 16], "request")
            );
            assert_ne!(first, span_fallback_distinct_id(&[], &[1; 16], "request"));
        }
    }

    #[test]
    fn test_span_fallback_prefers_the_widest_session_grouping() {
        let all = vec![
            string_kv("gen_ai.conversation.id", "thread-1"),
            string_kv("anthropic.session.id", "session-1"),
            string_kv("$ai_session_id", "explicit-1"),
        ];
        let explicit_only = vec![string_kv("$ai_session_id", "explicit-1")];
        assert_eq!(
            span_fallback_distinct_id(&all, &[1; 16], "request"),
            span_fallback_distinct_id(&explicit_only, &[1; 16], "request")
        );

        let session_and_thread = vec![
            string_kv("gen_ai.conversation.id", "thread-1"),
            string_kv("anthropic.session.id", "session-1"),
        ];
        let session_only = vec![string_kv("anthropic.session.id", "session-1")];
        assert_eq!(
            span_fallback_distinct_id(&session_and_thread, &[1; 16], "request"),
            span_fallback_distinct_id(&session_only, &[1; 16], "request")
        );
    }

    #[test]
    fn test_span_fallback_uses_the_request_id_without_a_valid_trace_id() {
        assert_eq!(
            span_fallback_distinct_id(&[], &[0; 16], "request"),
            "request"
        );
        assert_eq!(span_fallback_distinct_id(&[], &[], "request"), "request");
    }

    #[test]
    fn test_empty_span_value_falls_through_to_resource() {
        let span_attrs = vec![string_kv("posthog.distinct_id", "")];
        let resource = resource_with(vec![string_kv("posthog.distinct_id", "resource-user")]);
        assert_eq!(
            extract_distinct_id_for_span(&span_attrs, Some(&resource), "fallback"),
            "resource-user"
        );
    }

    #[test]
    fn test_empty_resource_value_falls_through_to_fallback() {
        let resource = resource_with(vec![
            string_kv("posthog.distinct_id", ""),
            string_kv("user.id", ""),
        ]);
        assert_eq!(
            extract_distinct_id_for_span(&[], Some(&resource), "fallback-id"),
            "fallback-id"
        );
    }

    #[test]
    fn test_non_string_span_value_is_ignored() {
        let span_attrs = vec![make_kv(
            "ai.telemetry.metadata.posthog_distinct_id",
            any_value::Value::IntValue(42),
        )];
        assert_eq!(
            extract_distinct_id_for_span(&span_attrs, None, "fallback"),
            "fallback"
        );
    }

    #[test]
    fn test_request_fallback_distinct_id_is_uuid() {
        let id = request_fallback_distinct_id();
        assert!(Uuid::parse_str(&id).is_ok());
    }
}
