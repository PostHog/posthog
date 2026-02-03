use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use opentelemetry_proto::tonic::common::v1::any_value;
use opentelemetry_proto::tonic::resource::v1::Resource;
use uuid::Uuid;

const DISTINCT_ID_KEYS: &[&str] = &["posthog.distinct_id", "user.id"];

fn get_string_attr<'a>(resource: &'a Resource, key: &str) -> Option<&'a str> {
    resource
        .attributes
        .iter()
        .find(|attr| attr.key == key)
        .and_then(|attr| attr.value.as_ref())
        .and_then(|v| v.value.as_ref())
        .and_then(|v| match v {
            any_value::Value::StringValue(s) if !s.is_empty() => Some(s.as_str()),
            _ => None,
        })
}

pub fn extract_distinct_id(request: &ExportTraceServiceRequest) -> String {
    for rs in &request.resource_spans {
        if let Some(resource) = &rs.resource {
            for key in DISTINCT_ID_KEYS {
                if let Some(id) = get_string_attr(resource, key) {
                    return id.to_string();
                }
            }
        }
    }
    Uuid::new_v4().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use opentelemetry_proto::tonic::common::v1::{AnyValue, KeyValue};
    use opentelemetry_proto::tonic::trace::v1::ResourceSpans;

    fn make_kv(key: &str, value: any_value::Value) -> KeyValue {
        KeyValue {
            key: key.to_string(),
            value: Some(AnyValue {
                value: Some(value),
            }),
        }
    }

    #[test]
    fn test_posthog_distinct_id_found() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: Some(Resource {
                    attributes: vec![make_kv(
                        "posthog.distinct_id",
                        any_value::Value::StringValue("user-123".to_string()),
                    )],
                    dropped_attributes_count: 0,
                }),
                scope_spans: vec![],
                schema_url: String::new(),
            }],
        };
        assert_eq!(extract_distinct_id(&request), "user-123");
    }

    #[test]
    fn test_user_id_fallback() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: Some(Resource {
                    attributes: vec![make_kv(
                        "user.id",
                        any_value::Value::StringValue("user-456".to_string()),
                    )],
                    dropped_attributes_count: 0,
                }),
                scope_spans: vec![],
                schema_url: String::new(),
            }],
        };
        assert_eq!(extract_distinct_id(&request), "user-456");
    }

    #[test]
    fn test_uuid_fallback() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![],
        };
        let distinct_id = extract_distinct_id(&request);
        assert!(Uuid::parse_str(&distinct_id).is_ok());
    }

    #[test]
    fn test_empty_string_skipped() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: Some(Resource {
                    attributes: vec![
                        make_kv(
                            "posthog.distinct_id",
                            any_value::Value::StringValue(String::new()),
                        ),
                        make_kv(
                            "user.id",
                            any_value::Value::StringValue("fallback-user".to_string()),
                        ),
                    ],
                    dropped_attributes_count: 0,
                }),
                scope_spans: vec![],
                schema_url: String::new(),
            }],
        };
        assert_eq!(extract_distinct_id(&request), "fallback-user");
    }

    #[test]
    fn test_multiple_resource_spans_picks_first() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![
                ResourceSpans {
                    resource: Some(Resource {
                        attributes: vec![make_kv(
                            "posthog.distinct_id",
                            any_value::Value::StringValue("first".to_string()),
                        )],
                        dropped_attributes_count: 0,
                    }),
                    scope_spans: vec![],
                    schema_url: String::new(),
                },
                ResourceSpans {
                    resource: Some(Resource {
                        attributes: vec![make_kv(
                            "posthog.distinct_id",
                            any_value::Value::StringValue("second".to_string()),
                        )],
                        dropped_attributes_count: 0,
                    }),
                    scope_spans: vec![],
                    schema_url: String::new(),
                },
            ],
        };
        assert_eq!(extract_distinct_id(&request), "first");
    }
}
