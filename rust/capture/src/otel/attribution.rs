//! SDK attribution for OTLP requests, for ingestion warnings.
//!
//! Lives here rather than in `ingestion_warnings` because it destructures OTLP
//! types; see that module's doc for the projection-vs-emit-helper split.

use common_ingestion_warnings::WarningRequestContext;
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use opentelemetry_proto::tonic::common::v1::any_value;

use crate::ingestion_warnings::{unknown_if_missing, within_bound};

/// The OTLP analogue of `$lib`/`$lib_version`: semantic-convention resource
/// attributes every OTEL SDK sets about itself.
///
/// `fan_out` strips the whole `telemetry.` prefix from event properties as
/// auto-detected noise, which is right for properties and irrelevant here —
/// these are read off the raw request, and only ever to say which exporter
/// produced a bad payload.
const SDK_NAME_ATTR: &str = "telemetry.sdk.name";
const SDK_VERSION_ATTR: &str = "telemetry.sdk.version";

/// Warning attribution for an OTLP request.
///
/// `request` is `None` when the body never parsed, which is exactly when a
/// warning is most likely: attribution then falls back to unknown, since the
/// SDK identity lives inside the payload we couldn't read.
pub(super) fn otel_request_context(
    token: &str,
    path: &str,
    request: Option<&ExportTraceServiceRequest>,
) -> WarningRequestContext {
    let (lib, lib_version) = request.map(sdk_attribution).unwrap_or_default();
    WarningRequestContext {
        token: token.to_string(),
        lib: unknown_if_missing(lib.as_deref()),
        lib_version: unknown_if_missing(lib_version.as_deref()),
        path: path.to_string(),
    }
}

/// Read the SDK name and version off the first resource that declares either.
///
/// A single export can carry several resources, but attribution only needs to
/// name the exporter, and one process is one SDK. Non-string values are ignored
/// rather than rendered: the semantic convention defines both as strings, so a
/// number here is a broken exporter, not a value worth displaying.
fn sdk_attribution(request: &ExportTraceServiceRequest) -> (Option<String>, Option<String>) {
    for resource_spans in &request.resource_spans {
        let Some(resource) = resource_spans.resource.as_ref() else {
            continue;
        };

        let mut name = None;
        let mut version = None;
        for kv in &resource.attributes {
            let Some(any_value::Value::StringValue(value)) =
                kv.value.as_ref().and_then(|v| v.value.as_ref())
            else {
                continue;
            };
            match kv.key.as_str() {
                SDK_NAME_ATTR => name = within_bound(value.clone()),
                SDK_VERSION_ATTR => version = within_bound(value.clone()),
                _ => {}
            }
        }

        if name.is_some() || version.is_some() {
            return (name, version);
        }
    }
    (None, None)
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_ingestion_warnings::UNKNOWN_ATTRIBUTION;
    use opentelemetry_proto::tonic::common::v1::{AnyValue, KeyValue};
    use opentelemetry_proto::tonic::resource::v1::Resource;
    use opentelemetry_proto::tonic::trace::v1::ResourceSpans;

    use crate::ingestion_warnings::MAX_SDK_ATTRIBUTION_LEN;

    fn string_attr(key: &str, value: &str) -> KeyValue {
        KeyValue {
            key: key.to_string(),
            value: Some(AnyValue {
                value: Some(any_value::Value::StringValue(value.to_string())),
            }),
        }
    }

    fn int_attr(key: &str, value: i64) -> KeyValue {
        KeyValue {
            key: key.to_string(),
            value: Some(AnyValue {
                value: Some(any_value::Value::IntValue(value)),
            }),
        }
    }

    fn request_with(resources: Vec<Option<Vec<KeyValue>>>) -> ExportTraceServiceRequest {
        ExportTraceServiceRequest {
            resource_spans: resources
                .into_iter()
                .map(|attributes| ResourceSpans {
                    resource: attributes.map(|attributes| Resource {
                        attributes,
                        ..Default::default()
                    }),
                    ..Default::default()
                })
                .collect(),
        }
    }

    // Every case here is a payload an exporter can actually send, so each must
    // produce a stampable context rather than a missing key.
    #[test]
    fn sdk_attribution_falls_back_to_unknown_when_unusable() {
        let over_bound = "w".repeat(MAX_SDK_ATTRIBUTION_LEN + 1);
        let cases = [
            (
                "unparsed body",
                None,
                UNKNOWN_ATTRIBUTION,
                UNKNOWN_ATTRIBUTION,
            ),
            (
                "no resource",
                Some(request_with(vec![None])),
                UNKNOWN_ATTRIBUTION,
                UNKNOWN_ATTRIBUTION,
            ),
            (
                "no telemetry attrs",
                Some(request_with(vec![Some(vec![string_attr(
                    "service.name",
                    "checkout",
                )])])),
                UNKNOWN_ATTRIBUTION,
                UNKNOWN_ATTRIBUTION,
            ),
            (
                "name without version",
                Some(request_with(vec![Some(vec![string_attr(
                    SDK_NAME_ATTR,
                    "opentelemetry",
                )])])),
                "opentelemetry",
                UNKNOWN_ATTRIBUTION,
            ),
            (
                "non-string name",
                Some(request_with(vec![Some(vec![
                    int_attr(SDK_NAME_ATTR, 42),
                    string_attr(SDK_VERSION_ATTR, "1.2.3"),
                ])])),
                UNKNOWN_ATTRIBUTION,
                "1.2.3",
            ),
            (
                "oversized name",
                Some(request_with(vec![Some(vec![
                    string_attr(SDK_NAME_ATTR, &over_bound),
                    string_attr(SDK_VERSION_ATTR, "1.2.3"),
                ])])),
                UNKNOWN_ATTRIBUTION,
                "1.2.3",
            ),
            (
                "first resource without attrs is skipped",
                Some(request_with(vec![
                    Some(vec![string_attr("service.name", "checkout")]),
                    Some(vec![
                        string_attr(SDK_NAME_ATTR, "opentelemetry-js"),
                        string_attr(SDK_VERSION_ATTR, "2.0.0"),
                    ]),
                ])),
                "opentelemetry-js",
                "2.0.0",
            ),
        ];

        for (label, request, expected_lib, expected_version) in cases {
            let ctx = otel_request_context("tok", "/i/v0/ai/otel", request.as_ref());
            assert_eq!(ctx.token, "tok", "{label}: token");
            assert_eq!(ctx.path, "/i/v0/ai/otel", "{label}: path");
            assert_eq!(ctx.lib, expected_lib, "{label}: lib");
            assert_eq!(ctx.lib_version, expected_version, "{label}: libVersion");
        }
    }
}
