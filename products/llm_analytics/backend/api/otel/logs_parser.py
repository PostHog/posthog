"""
OTLP protobuf parser for OpenTelemetry logs.

Parses ExportLogsServiceRequest protobuf messages and extracts log records,
resource attributes, and instrumentation scope information.
"""

from typing import Any

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord

from .parser import parse_any_value, parse_attributes


def parse_otlp_logs_request(protobuf_data: bytes) -> list[dict[str, Any]]:
    """
    Parse OTLP ExportLogsServiceRequest from protobuf bytes.

    Returns a list of dicts, each containing:
    - log: parsed log record dict
    - resource: dict of resource attributes for this log
    - scope: dict of instrumentation scope info for this log

    Each log carries its own resource/scope context to handle requests
    containing multiple resource_logs/scope_logs correctly.
    """
    request = ExportLogsServiceRequest()
    request.ParseFromString(protobuf_data)

    results = []

    # OTLP structure: resource_logs -> scope_logs -> log_records
    for resource_logs in request.resource_logs:
        # Extract resource attributes (service.name, etc.)
        resource_attrs = {}
        if resource_logs.HasField("resource"):
            resource_attrs = parse_attributes(resource_logs.resource.attributes)

        # Iterate through scope logs
        for scope_logs in resource_logs.scope_logs:
            # Extract instrumentation scope
            scope_info = {}
            if scope_logs.HasField("scope"):
                scope_info = {
                    "name": scope_logs.scope.name,
                    "version": scope_logs.scope.version if scope_logs.scope.version else None,
                    "attributes": parse_attributes(scope_logs.scope.attributes) if scope_logs.scope.attributes else {},
                }

            # Parse each log record with its resource/scope context
            for log_record in scope_logs.log_records:
                parsed_log = parse_log_record(log_record)
                results.append(
                    {
                        "log": parsed_log,
                        "resource": resource_attrs,
                        "scope": scope_info,
                    }
                )

    return results


def parse_log_record(log_record: LogRecord) -> dict[str, Any]:
    """
    Parse a single OTLP log record into a dict.
    """
    return {
        "time_unix_nano": str(log_record.time_unix_nano),
        "observed_time_unix_nano": str(log_record.observed_time_unix_nano)
        if log_record.observed_time_unix_nano
        else None,
        "severity_number": log_record.severity_number,
        "severity_text": log_record.severity_text if log_record.severity_text else None,
        "body": parse_any_value(log_record.body) if log_record.HasField("body") else None,
        "attributes": parse_attributes(log_record.attributes),
        "trace_id": log_record.trace_id.hex() if log_record.trace_id else None,
        "span_id": log_record.span_id.hex() if log_record.span_id else None,
        "flags": log_record.flags if log_record.flags else None,
    }
