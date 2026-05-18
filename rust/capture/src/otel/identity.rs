use opentelemetry_proto::tonic::common::v1::{any_value, KeyValue};
use opentelemetry_proto::tonic::resource::v1::Resource;
use uuid::Uuid;

/// Span-level keys checked in order. The Vercel AI SDK serializes
/// `experimental_telemetry.metadata.posthog_distinct_id` as
/// `ai.telemetry.metadata.posthog_distinct_id`, which is the canonical
/// per-call way to attribute an event to a user.
const SPAN_DISTINCT_ID_KEYS: &[&str] = &[
    "ai.telemetry.metadata.posthog_distinct_id",
    "posthog.distinct_id",
    "user.id",
];

/// Resource-level keys are the per-process fallback used when no per-span
/// override is set.
const RESOURCE_DISTINCT_ID_KEYS: &[&str] = &["posthog.distinct_id", "user.id"];

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
