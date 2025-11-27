"""
OTLP protobuf parser for OpenTelemetry traces.

Parses ExportTraceServiceRequest protobuf messages and extracts spans,
resource attributes, and instrumentation scope information.
"""

from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span


def parse_otlp_request(protobuf_data: bytes) -> list[dict[str, Any]]:
    """
    Parse OTLP ExportTraceServiceRequest from protobuf bytes.

    Returns a list of dicts, each containing:
    - span: parsed span dict
    - resource: dict of resource attributes for this span
    - scope: dict of instrumentation scope info for this span

    Each span carries its own resource/scope context to handle requests
    containing multiple resource_spans/scope_spans correctly.
    """
    request = ExportTraceServiceRequest()
    request.ParseFromString(protobuf_data)

    results = []

    # OTLP structure: resource_spans -> scope_spans -> spans
    for resource_spans in request.resource_spans:
        # Extract resource attributes (service.name, etc.)
        resource_attrs = {}
        if resource_spans.HasField("resource"):
            resource_attrs = parse_attributes(resource_spans.resource.attributes)

        # Iterate through scope spans
        for scope_spans in resource_spans.scope_spans:
            # Extract instrumentation scope
            scope_info = {}
            if scope_spans.HasField("scope"):
                scope_info = {
                    "name": scope_spans.scope.name,
                    "version": scope_spans.scope.version if scope_spans.scope.version else None,
                    "attributes": parse_attributes(scope_spans.scope.attributes)
                    if scope_spans.scope.attributes
                    else {},
                }

            # Parse each span with its resource/scope context
            for span in scope_spans.spans:
                parsed_span = parse_span(span)
                results.append(
                    {
                        "span": parsed_span,
                        "resource": resource_attrs,
                        "scope": scope_info,
                    }
                )

    return results


def parse_span(span: Span) -> dict[str, Any]:
    """
    Parse a single OTLP span into a dict.
    """
    return {
        "trace_id": span.trace_id.hex(),
        "span_id": span.span_id.hex(),
        "parent_span_id": span.parent_span_id.hex() if span.parent_span_id else None,
        "name": span.name,
        "kind": span.kind,
        "start_time_unix_nano": str(span.start_time_unix_nano),
        "end_time_unix_nano": str(span.end_time_unix_nano),
        "attributes": parse_attributes(span.attributes),
        "events": [parse_span_event(event) for event in span.events],
        "links": [parse_span_link(link) for link in span.links],
        "status": parse_span_status(span.status),
    }


def parse_span_event(event) -> dict[str, Any]:
    """
    Parse a span event.
    """
    return {
        "time_unix_nano": str(event.time_unix_nano),
        "name": event.name,
        "attributes": parse_attributes(event.attributes),
    }


def parse_span_link(link) -> dict[str, Any]:
    """
    Parse a span link.
    """
    return {
        "trace_id": link.trace_id.hex(),
        "span_id": link.span_id.hex(),
        "attributes": parse_attributes(link.attributes),
    }


def parse_span_status(status) -> dict[str, Any]:
    """
    Parse span status.
    """
    return {
        "code": status.code,
        "message": status.message if status.message else None,
    }


def parse_attributes(attributes: list[KeyValue]) -> dict[str, Any]:
    """
    Parse OpenTelemetry attributes (key-value pairs) into a dict.

    Handles different value types: string, int, double, bool, array, kvlist.
    """
    result = {}

    for kv in attributes:
        key = kv.key
        value = parse_any_value(kv.value)
        result[key] = value

    return result


def parse_any_value(value: AnyValue) -> Any:
    """
    Parse an AnyValue protobuf type into a Python value.

    AnyValue can be:
    - string_value
    - int_value
    - double_value
    - bool_value
    - array_value (list of AnyValue)
    - kvlist_value (dict of key-value pairs)
    - bytes_value
    """
    # Check which field is set
    which = value.WhichOneof("value")

    if which == "string_value":
        return value.string_value
    elif which == "int_value":
        return value.int_value
    elif which == "double_value":
        return value.double_value
    elif which == "bool_value":
        return value.bool_value
    elif which == "array_value":
        return [parse_any_value(item) for item in value.array_value.values]
    elif which == "kvlist_value":
        return parse_attributes(value.kvlist_value.values)
    elif which == "bytes_value":
        return value.bytes_value.hex()
    else:
        # Unknown or unset
        return None


def parse_baggage_header(baggage_header: str | None) -> dict[str, str]:
    """
    Parse OTel baggage from HTTP header.

    Baggage format: key1=value1,key2=value2,...

    Example: session_id=abc123,user_id=user_456
    """
    if not baggage_header:
        return {}

    baggage = {}

    # Split by comma
    items = baggage_header.split(",")

    for item in items:
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            baggage[key.strip()] = value.strip()

    return baggage
