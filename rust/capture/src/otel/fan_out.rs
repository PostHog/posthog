use chrono::{DateTime, TimeZone, Utc};
use common_types::HasEventName;
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use opentelemetry_proto::tonic::common::v1::{any_value, KeyValue};
use serde_json::Value;

use super::identity::extract_distinct_id_for_span;
use super::providers;

pub struct SpanEvent {
    pub event_name: String,
    pub distinct_id: String,
    pub properties: Value,
    pub timestamp: Option<DateTime<Utc>>,
}

impl HasEventName for SpanEvent {
    fn event_name(&self) -> &str {
        &self.event_name
    }

    fn has_property(&self, key: &str) -> bool {
        self.properties
            .as_object()
            .map(|m| m.contains_key(key))
            .unwrap_or(false)
    }
}

impl HasEventName for &SpanEvent {
    fn event_name(&self) -> &str {
        &self.event_name
    }

    fn has_property(&self, key: &str) -> bool {
        self.properties
            .as_object()
            .map(|m| m.contains_key(key))
            .unwrap_or(false)
    }
}

fn any_value_to_json(value: &any_value::Value) -> Value {
    match value {
        any_value::Value::StringValue(s) => Value::String(s.clone()),
        any_value::Value::BoolValue(b) => Value::Bool(*b),
        any_value::Value::IntValue(i) => Value::Number((*i).into()),
        any_value::Value::DoubleValue(d) => serde_json::Number::from_f64(*d)
            .map(Value::Number)
            .unwrap_or(Value::Null),
        any_value::Value::BytesValue(bytes) => Value::String(hex::encode(bytes)),
        any_value::Value::ArrayValue(arr) => Value::Array(
            arr.values
                .iter()
                .filter_map(|v| v.value.as_ref().map(any_value_to_json))
                .collect(),
        ),
        any_value::Value::KvlistValue(kvlist) => Value::Object(attributes_to_map(&kvlist.values)),
    }
}

fn attributes_to_map(attrs: &[KeyValue]) -> serde_json::Map<String, Value> {
    attrs
        .iter()
        .filter_map(|kv| {
            kv.value
                .as_ref()
                .and_then(|v| v.value.as_ref())
                .map(|v| (kv.key.clone(), any_value_to_json(v)))
        })
        .collect()
}

/// OTel SDK auto-detected resource attribute prefixes that are noise for AI
/// events. User-set resource attributes (e.g. `user.id`, `posthog.ai.debug`)
/// pass through since they don't match these prefixes.
const NOISY_RESOURCE_PREFIXES: &[&str] = &["host.", "process.", "os.", "telemetry."];

fn filter_resource_attributes(attrs: &[KeyValue]) -> serde_json::Map<String, Value> {
    attrs
        .iter()
        .filter_map(|kv| {
            if NOISY_RESOURCE_PREFIXES
                .iter()
                .any(|prefix| kv.key.starts_with(prefix))
            {
                return None;
            }
            kv.value
                .as_ref()
                .and_then(|v| v.value.as_ref())
                .map(|v| (kv.key.clone(), any_value_to_json(v)))
        })
        .collect()
}

fn apply_geoip_default(properties: &mut serde_json::Map<String, Value>) {
    let alias = properties.remove("posthog.geoip_disable");
    if properties.contains_key("$geoip_disable") {
        return;
    }
    properties.insert(
        "$geoip_disable".to_string(),
        alias.unwrap_or(Value::Bool(true)),
    );
}

fn nanos_to_datetime(nanos: u64) -> Option<DateTime<Utc>> {
    if nanos == 0 {
        return None;
    }
    let secs = (nanos / 1_000_000_000) as i64;
    let nsecs = (nanos % 1_000_000_000) as u32;
    Utc.timestamp_opt(secs, nsecs).single()
}

/// Convert OTLP spans into [`SpanEvent`]s. `request_fallback_distinct_id` is
/// used only when neither the span nor its enclosing resource carries a
/// distinct_id attribute — see [`extract_distinct_id_for_span`] for the full
/// precedence list.
pub fn expand_into_events(
    request: &ExportTraceServiceRequest,
    request_fallback_distinct_id: &str,
) -> Vec<SpanEvent> {
    let total_spans: usize = request
        .resource_spans
        .iter()
        .flat_map(|rs| &rs.scope_spans)
        .map(|ss| ss.spans.len())
        .sum();
    let mut events = Vec::with_capacity(total_spans.min(super::MAX_SPANS_PER_REQUEST));

    for rs in &request.resource_spans {
        let resource_attrs = rs
            .resource
            .as_ref()
            .map(|r| filter_resource_attributes(&r.attributes))
            .unwrap_or_default();

        for ss in &rs.scope_spans {
            for span in &ss.spans {
                let Some(provider) = providers::get_provider_raw(&span.attributes) else {
                    continue;
                };

                let distinct_id = extract_distinct_id_for_span(
                    &span.attributes,
                    rs.resource.as_ref(),
                    request_fallback_distinct_id,
                );
                let span_attrs = attributes_to_map(&span.attributes);
                let event_name = (provider.classify)(&span_attrs);

                let mut properties = resource_attrs.clone();
                properties.extend(span_attrs);

                apply_geoip_default(&mut properties);

                properties.insert(
                    "$ai_trace_id".to_string(),
                    Value::String(hex::encode(&span.trace_id)),
                );
                properties.insert(
                    "$ai_span_id".to_string(),
                    Value::String(hex::encode(&span.span_id)),
                );
                if !span.parent_span_id.is_empty() {
                    properties.insert(
                        "$ai_parent_id".to_string(),
                        Value::String(hex::encode(&span.parent_span_id)),
                    );
                }
                properties.insert(
                    "$ai_ingestion_source".to_string(),
                    Value::String("otel".to_string()),
                );

                if !span.name.is_empty() {
                    properties.insert(
                        "$otel_span_name".to_string(),
                        Value::String(span.name.clone()),
                    );
                }
                properties.insert(
                    "$otel_start_time_unix_nano".to_string(),
                    Value::String(span.start_time_unix_nano.to_string()),
                );
                properties.insert(
                    "$otel_end_time_unix_nano".to_string(),
                    Value::String(span.end_time_unix_nano.to_string()),
                );

                let timestamp = nanos_to_datetime(span.start_time_unix_nano);

                events.push(SpanEvent {
                    event_name: event_name.to_string(),
                    distinct_id,
                    properties: Value::Object(properties),
                    timestamp,
                });
            }
        }
    }

    events
}

#[cfg(test)]
mod tests {
    use super::*;
    use opentelemetry_proto::tonic::common::v1::AnyValue;
    use opentelemetry_proto::tonic::resource::v1::Resource;
    use opentelemetry_proto::tonic::trace::v1::{ResourceSpans, ScopeSpans, Span};
    use rstest::rstest;

    fn make_kv(key: &str, value: any_value::Value) -> KeyValue {
        KeyValue {
            key: key.to_string(),
            value: Some(AnyValue { value: Some(value) }),
        }
    }

    fn make_span(
        trace_id: Vec<u8>,
        span_id: Vec<u8>,
        parent_span_id: Vec<u8>,
        start_time_nanos: u64,
        end_time_nanos: u64,
        name: &str,
        attributes: Vec<KeyValue>,
    ) -> Span {
        Span {
            trace_id,
            span_id,
            parent_span_id,
            start_time_unix_nano: start_time_nanos,
            end_time_unix_nano: end_time_nanos,
            name: name.to_string(),
            attributes,
            ..Default::default()
        }
    }

    #[test]
    fn test_any_value_to_json() {
        for (input, expected) in [
            (
                any_value::Value::StringValue("hello".to_string()),
                Value::String("hello".to_string()),
            ),
            (any_value::Value::BoolValue(true), Value::Bool(true)),
            (any_value::Value::IntValue(42), Value::Number(42.into())),
            (
                any_value::Value::BytesValue(vec![0xAB, 0xCD]),
                Value::String("abcd".to_string()),
            ),
        ] {
            assert_eq!(any_value_to_json(&input), expected);
        }

        let v = any_value_to_json(&any_value::Value::DoubleValue(1.23));
        assert!(v.is_number());
    }

    #[test]
    fn test_attributes_to_map() {
        let attrs = vec![
            make_kv("key1", any_value::Value::StringValue("val1".to_string())),
            make_kv("key2", any_value::Value::IntValue(42)),
        ];
        let map = attributes_to_map(&attrs);
        assert_eq!(map.get("key1"), Some(&Value::String("val1".to_string())));
        assert_eq!(map.get("key2"), Some(&Value::Number(42.into())));
    }

    #[test]
    fn test_attributes_to_map_skips_missing_values() {
        let attrs = vec![KeyValue {
            key: "empty".to_string(),
            value: None,
        }];
        let map = attributes_to_map(&attrs);
        assert!(map.is_empty());
    }

    #[test]
    fn test_nanos_to_datetime_valid() {
        let dt = nanos_to_datetime(1_704_067_200_000_000_000).unwrap();
        assert_eq!(dt.to_rfc3339(), "2024-01-01T00:00:00+00:00");
    }

    #[test]
    fn test_nanos_to_datetime_zero() {
        assert!(nanos_to_datetime(0).is_none());
    }

    #[test]
    fn test_expand_single_span() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: Some(Resource {
                    attributes: vec![make_kv(
                        "service.name",
                        any_value::Value::StringValue("test-svc".to_string()),
                    )],
                    dropped_attributes_count: 0,
                }),
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![make_span(
                        vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16],
                        vec![1, 2, 3, 4, 5, 6, 7, 8],
                        vec![],
                        1_704_067_200_000_000_000,
                        1_704_067_201_500_000_000,
                        "chat gpt-4",
                        vec![make_kv(
                            "gen_ai.operation.name",
                            any_value::Value::StringValue("chat".to_string()),
                        )],
                    )],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            }],
        };

        let events = expand_into_events(&request, "user-1");
        assert_eq!(events.len(), 1);

        let event = &events[0];
        assert_eq!(event.event_name, "$ai_generation");
        assert_eq!(event.distinct_id, "user-1");

        let props = event.properties.as_object().unwrap();
        assert_eq!(props["$ai_trace_id"], "0102030405060708090a0b0c0d0e0f10");
        assert_eq!(props["$ai_span_id"], "0102030405060708");
        assert_eq!(props["$ai_ingestion_source"], "otel");
        assert_eq!(props["service.name"], "test-svc");
        assert_eq!(props["$otel_span_name"], "chat gpt-4");
        assert_eq!(props["$otel_start_time_unix_nano"], "1704067200000000000");
        assert_eq!(props["$otel_end_time_unix_nano"], "1704067201500000000");
        assert!(event.timestamp.is_some());
    }

    #[test]
    fn test_expand_skips_irrelevant_spans() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: Some(Resource {
                    attributes: vec![],
                    dropped_attributes_count: 0,
                }),
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![make_span(
                        vec![1; 16],
                        vec![2; 8],
                        vec![],
                        1_704_067_200_000_000_000,
                        1_704_067_201_000_000_000,
                        "http POST https://us.i.posthog.com/e",
                        vec![make_kv(
                            "http.request.method",
                            any_value::Value::StringValue("POST".to_string()),
                        )],
                    )],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            }],
        };

        let events = expand_into_events(&request, "user-1");
        assert!(events.is_empty());
    }

    #[test]
    fn test_noisy_resource_attrs_are_filtered() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: Some(Resource {
                    attributes: vec![
                        make_kv(
                            "service.name",
                            any_value::Value::StringValue("my-svc".to_string()),
                        ),
                        make_kv(
                            "host.name",
                            any_value::Value::StringValue("my-host".to_string()),
                        ),
                        make_kv("process.pid", any_value::Value::IntValue(1234)),
                        make_kv(
                            "user.id",
                            any_value::Value::StringValue("user-123".to_string()),
                        ),
                        make_kv(
                            "posthog.ai.debug",
                            any_value::Value::StringValue("true".to_string()),
                        ),
                    ],
                    dropped_attributes_count: 0,
                }),
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![make_span(
                        vec![0; 16],
                        vec![0; 8],
                        vec![],
                        0,
                        0,
                        "",
                        vec![make_kv(
                            "gen_ai.request.model",
                            any_value::Value::StringValue("gpt-4".to_string()),
                        )],
                    )],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            }],
        };

        let events = expand_into_events(&request, "user");
        let props = events[0].properties.as_object().unwrap();
        assert_eq!(props["service.name"], "my-svc");
        assert!(!props.contains_key("host.name"));
        assert!(!props.contains_key("process.pid"));
        assert_eq!(props["user.id"], "user-123");
        assert_eq!(props["posthog.ai.debug"], "true");
    }

    #[test]
    fn test_parent_span_id_included_when_present() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: None,
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![make_span(
                        vec![0; 16],
                        vec![0; 8],
                        vec![1, 2, 3, 4, 5, 6, 7, 8],
                        0,
                        0,
                        "",
                        vec![make_kv(
                            "gen_ai.request.model",
                            any_value::Value::StringValue("gpt-4".to_string()),
                        )],
                    )],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            }],
        };

        let events = expand_into_events(&request, "user");
        let props = events[0].properties.as_object().unwrap();
        assert_eq!(props["$ai_parent_id"], "0102030405060708");
    }

    #[test]
    fn test_parent_span_id_excluded_when_empty() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: None,
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![make_span(
                        vec![0; 16],
                        vec![0; 8],
                        vec![],
                        0,
                        0,
                        "",
                        vec![make_kv(
                            "gen_ai.request.model",
                            any_value::Value::StringValue("gpt-4".to_string()),
                        )],
                    )],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            }],
        };

        let events = expand_into_events(&request, "user");
        let props = events[0].properties.as_object().unwrap();
        assert!(!props.contains_key("$ai_parent_id"));
    }

    #[test]
    fn test_empty_request() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![],
        };
        let events = expand_into_events(&request, "user");
        assert!(events.is_empty());
    }

    #[test]
    fn test_span_attribute_distinct_id_overrides_resource_and_fallback() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: Some(Resource {
                    attributes: vec![make_kv(
                        "posthog.distinct_id",
                        any_value::Value::StringValue("resource-user".to_string()),
                    )],
                    dropped_attributes_count: 0,
                }),
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![make_span(
                        vec![0; 16],
                        vec![0; 8],
                        vec![],
                        0,
                        0,
                        "",
                        vec![
                            make_kv(
                                "ai.telemetry.metadata.posthog_distinct_id",
                                any_value::Value::StringValue("span-user".to_string()),
                            ),
                            make_kv(
                                "gen_ai.request.model",
                                any_value::Value::StringValue("gpt-4".to_string()),
                            ),
                        ],
                    )],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            }],
        };
        let events = expand_into_events(&request, "fallback");
        assert_eq!(events[0].distinct_id, "span-user");
    }

    #[test]
    fn test_mixed_users_in_one_batch_get_independent_distinct_ids() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: None,
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![
                        make_span(
                            vec![0; 16],
                            vec![1; 8],
                            vec![],
                            0,
                            0,
                            "",
                            vec![
                                make_kv(
                                    "ai.telemetry.metadata.posthog_distinct_id",
                                    any_value::Value::StringValue("user-a".to_string()),
                                ),
                                make_kv(
                                    "gen_ai.request.model",
                                    any_value::Value::StringValue("gpt-4".to_string()),
                                ),
                            ],
                        ),
                        make_span(
                            vec![0; 16],
                            vec![2; 8],
                            vec![],
                            0,
                            0,
                            "",
                            vec![
                                make_kv(
                                    "ai.telemetry.metadata.posthog_distinct_id",
                                    any_value::Value::StringValue("user-b".to_string()),
                                ),
                                make_kv(
                                    "gen_ai.request.model",
                                    any_value::Value::StringValue("gpt-4".to_string()),
                                ),
                            ],
                        ),
                    ],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            }],
        };
        let events = expand_into_events(&request, "fallback");
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].distinct_id, "user-a");
        assert_eq!(events[1].distinct_id, "user-b");
    }

    #[test]
    fn test_falls_back_to_resource_when_span_has_no_id() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: Some(Resource {
                    attributes: vec![make_kv(
                        "posthog.distinct_id",
                        any_value::Value::StringValue("resource-user".to_string()),
                    )],
                    dropped_attributes_count: 0,
                }),
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![make_span(
                        vec![0; 16],
                        vec![0; 8],
                        vec![],
                        0,
                        0,
                        "",
                        vec![make_kv(
                            "gen_ai.request.model",
                            any_value::Value::StringValue("gpt-4".to_string()),
                        )],
                    )],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            }],
        };
        let events = expand_into_events(&request, "fallback");
        assert_eq!(events[0].distinct_id, "resource-user");
    }

    #[test]
    fn test_falls_back_to_request_fallback_when_no_attrs() {
        let request = ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: None,
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![make_span(
                        vec![0; 16],
                        vec![0; 8],
                        vec![],
                        0,
                        0,
                        "",
                        vec![make_kv(
                            "gen_ai.request.model",
                            any_value::Value::StringValue("gpt-4".to_string()),
                        )],
                    )],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            }],
        };
        let events = expand_into_events(&request, "fallback-id");
        assert_eq!(events[0].distinct_id, "fallback-id");
    }

    fn make_minimal_request(
        extra_resource_attrs: Vec<KeyValue>,
        extra_span_attrs: Vec<KeyValue>,
    ) -> ExportTraceServiceRequest {
        let mut span_attrs = vec![make_kv(
            "gen_ai.request.model",
            any_value::Value::StringValue("gpt-4".to_string()),
        )];
        span_attrs.extend(extra_span_attrs);

        ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: Some(Resource {
                    attributes: extra_resource_attrs,
                    dropped_attributes_count: 0,
                }),
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![make_span(
                        vec![0; 16],
                        vec![0; 8],
                        vec![],
                        0,
                        0,
                        "",
                        span_attrs,
                    )],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            }],
        }
    }

    #[rstest]
    // Default: no attributes set; $geoip_disable defaults to true.
    #[case::default_disabled(vec![], vec![], true)]
    // Canonical $geoip_disable on span wins.
    #[case::canonical_opt_in(vec![], vec![("$geoip_disable", false)], false)]
    // posthog.geoip_disable alias on resource is copied into $geoip_disable.
    #[case::alias_opt_in(vec![("posthog.geoip_disable", false)], vec![], false)]
    // Both set: canonical wins, alias is consumed (not duplicated).
    #[case::canonical_wins_over_alias(
        vec![("posthog.geoip_disable", false)],
        vec![("$geoip_disable", true)],
        true
    )]
    fn test_geoip_default_behavior(
        #[case] resource_attrs: Vec<(&str, bool)>,
        #[case] span_attrs: Vec<(&str, bool)>,
        #[case] expected_geoip_disable: bool,
    ) {
        let to_kv = |(k, v): &(&str, bool)| make_kv(k, any_value::Value::BoolValue(*v));
        let request = make_minimal_request(
            resource_attrs.iter().map(to_kv).collect(),
            span_attrs.iter().map(to_kv).collect(),
        );
        let events = expand_into_events(&request, "user");
        let props = events[0].properties.as_object().unwrap();
        assert_eq!(props["$geoip_disable"], Value::Bool(expected_geoip_disable));
        // Alias must always be consumed so it doesn't leak as a duplicate property.
        assert!(!props.contains_key("posthog.geoip_disable"));
    }
}
