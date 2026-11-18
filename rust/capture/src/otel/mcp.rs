use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use opentelemetry_proto::tonic::trace::v1::span::SpanKind;
use opentelemetry_proto::tonic::trace::v1::status::StatusCode;
use opentelemetry_proto::tonic::trace::v1::Span;
use serde_json::{Map, Value};

use super::identity::get_string_attr;

#[derive(Debug, PartialEq, Eq)]
pub enum McpSpan {
    NotServer,
    Event(&'static str),
    Dropped,
}

/// `server/discover` replaces the `initialize` handshake from the 2026-07-28 protocol revision.
const METHOD_EVENTS: &[(&str, &str)] = &[
    ("initialize", "$mcp_initialize"),
    ("server/discover", "$mcp_initialize"),
    ("tools/list", "$mcp_tools_list"),
    ("tools/call", "$mcp_tool_call"),
    ("resources/list", "$mcp_resources_list"),
    ("resources/read", "$mcp_resource_read"),
    ("prompts/list", "$mcp_prompts_list"),
    ("prompts/get", "$mcp_prompt_get"),
];

pub fn classify(span: &Span) -> McpSpan {
    if span.kind != SpanKind::Server as i32 {
        return McpSpan::NotServer;
    }
    let Some(method) = get_string_attr(&span.attributes, "mcp.method.name") else {
        return McpSpan::NotServer;
    };
    METHOD_EVENTS
        .iter()
        .find(|(name, _)| *name == method)
        .map_or(McpSpan::Dropped, |(_, event)| McpSpan::Event(event))
}

/// Server spans for notifications are dropped on purpose, so a batch of them is not misconfigured.
pub fn has_server_span(request: &ExportTraceServiceRequest) -> bool {
    request
        .resource_spans
        .iter()
        .flat_map(|rs| &rs.scope_spans)
        .flat_map(|ss| &ss.spans)
        .any(|span| classify(span) != McpSpan::NotServer)
}

/// MCP events keep the raw span status: the `$ai_*` error properties carry LLM-specific
/// fallbacks, such as a placeholder message and an HTTP status.
pub fn apply_status_properties(span: &Span, properties: &mut Map<String, Value>) {
    let Some(status) = span.status.as_ref() else {
        return;
    };
    if status.code != StatusCode::Error as i32 {
        return;
    }
    properties.insert("$otel_status_code".to_string(), Value::from("error"));
    if !status.message.is_empty() {
        properties.insert(
            "$otel_status_message".to_string(),
            Value::from(status.message.clone()),
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use opentelemetry_proto::tonic::common::v1::{any_value, AnyValue, KeyValue};
    use opentelemetry_proto::tonic::trace::v1::Status;
    use rstest::rstest;

    fn span(kind: SpanKind, method: Option<&str>) -> Span {
        Span {
            kind: kind as i32,
            attributes: method
                .map(|method| KeyValue {
                    key: "mcp.method.name".to_string(),
                    value: Some(AnyValue {
                        value: Some(any_value::Value::StringValue(method.to_string())),
                    }),
                })
                .into_iter()
                .collect(),
            ..Default::default()
        }
    }

    #[rstest]
    #[case(SpanKind::Server, Some("tools/call"), McpSpan::Event("$mcp_tool_call"))]
    #[case(
        SpanKind::Server,
        Some("server/discover"),
        McpSpan::Event("$mcp_initialize")
    )]
    #[case(SpanKind::Server, Some("notifications/initialized"), McpSpan::Dropped)]
    #[case(SpanKind::Server, Some("ping"), McpSpan::Dropped)]
    #[case(SpanKind::Server, None, McpSpan::NotServer)]
    #[case(SpanKind::Client, Some("tools/call"), McpSpan::NotServer)]
    #[case(SpanKind::Internal, Some("tools/call"), McpSpan::NotServer)]
    fn classifies_by_kind_and_method(
        #[case] kind: SpanKind,
        #[case] method: Option<&str>,
        #[case] expected: McpSpan,
    ) {
        assert_eq!(classify(&span(kind, method)), expected);
    }

    #[rstest]
    #[case(StatusCode::Error, "Method not found", Some("Method not found"))]
    #[case(StatusCode::Error, "", None)]
    fn keeps_the_raw_error_status(
        #[case] code: StatusCode,
        #[case] message: &str,
        #[case] expected_message: Option<&str>,
    ) {
        let span = Span {
            status: Some(Status {
                code: code as i32,
                message: message.to_string(),
            }),
            ..Default::default()
        };
        let mut properties = Map::new();
        apply_status_properties(&span, &mut properties);
        assert_eq!(properties["$otel_status_code"], "error");
        assert_eq!(
            properties
                .get("$otel_status_message")
                .and_then(Value::as_str),
            expected_message
        );
    }

    #[test]
    fn ignores_a_status_that_is_not_an_error() {
        let span = Span {
            status: Some(Status {
                code: StatusCode::Ok as i32,
                message: String::new(),
            }),
            ..Default::default()
        };
        let mut properties = Map::new();
        apply_status_properties(&span, &mut properties);
        assert!(properties.is_empty());
    }
}
