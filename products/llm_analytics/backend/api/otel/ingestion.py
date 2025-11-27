"""
OpenTelemetry traces and logs ingestion API endpoints.

Accepts OTLP/HTTP (protobuf) format traces and logs and converts them to PostHog AI events.

Supports both OpenAI instrumentation versions:
- v1 (opentelemetry-instrumentation-openai): Sends everything as trace span attributes
- v2 (opentelemetry-instrumentation-openai-v2): Sends metadata as spans, message content as logs

Endpoints:
- POST /api/projects/:project_id/ai/otel/traces - Required for all instrumentation
- POST /api/projects/:project_id/ai/otel/logs - Required for v2 instrumentation with message content

Content-Type: application/x-protobuf
Authorization: Bearer <project_token>

Authentication uses project API token (phc_...), NOT personal API key.
Token can be provided via Authorization header or ?token= query parameter.
"""

import re
from typing import Any, Optional, Union

from django.http import HttpRequest

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import authentication, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.capture import capture_batch_internal
from posthog.models import Team

from .logs_parser import parse_otlp_logs_request
from .logs_transformer import (
    build_event_properties,
    calculate_timestamp,
    determine_event_type,
    extract_distinct_id,
    transform_log_to_ai_event,
)
from .parser import parse_baggage_header, parse_otlp_request
from .transformer import transform_span_to_ai_event

logger = structlog.get_logger(__name__)

# OpenTelemetry limits (aligned with plugin-server validation)
OTEL_LIMITS = {
    "MAX_SPANS_PER_REQUEST": 1000,
    "MAX_ATTRIBUTES_PER_SPAN": 128,
    "MAX_EVENTS_PER_SPAN": 128,
    "MAX_LINKS_PER_SPAN": 128,
    "MAX_ATTRIBUTE_VALUE_LENGTH": 100_000,  # 100KB
    "MAX_SPAN_NAME_LENGTH": 1024,
    "MAX_LOGS_PER_REQUEST": 1000,
    "MAX_ATTRIBUTES_PER_LOG": 128,
    "MAX_LOG_BODY_LENGTH": 100_000,  # 100KB
}


class ProjectTokenAuthentication(authentication.BaseAuthentication):
    """
    Authenticates using a project API token (phc_...).

    This is used for ingestion endpoints where a public project token is used
    instead of a personal API key. Supports token in:
    1. Authorization header: Bearer <token>
    2. Query parameter: ?token=<token>

    Similar to logs ingestion pattern.
    """

    keyword = "Bearer"

    @classmethod
    def find_token(
        cls,
        request: Union[HttpRequest, Request],
    ) -> Optional[str]:
        """Try to find project token in request and return it."""
        # Try Authorization header first
        if "HTTP_AUTHORIZATION" in request.META:
            authorization_match = re.match(rf"^{cls.keyword}\s+(\S.+)$", request.META["HTTP_AUTHORIZATION"])
            if authorization_match:
                token = authorization_match.group(1).strip()
                # Only accept project tokens (phc_...), not personal keys
                if token.startswith("phc_"):
                    return token
                return None

        # Try query parameter
        if "token" in request.GET:
            token = request.GET["token"]
            if token.startswith("phc_"):
                return token

        return None

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, Team]]:
        token = self.find_token(request)

        if not token:
            return None

        # Get the team from the project token
        team = Team.objects.get_team_from_cache_or_token(token)

        if team is None:
            raise AuthenticationFailed(detail="Invalid project token.")

        # Return team as the "user" for this authentication
        # The team itself acts as the authenticated entity
        return (team, token)

    @classmethod
    def authenticate_header(cls, request) -> str:
        return cls.keyword


@extend_schema(
    description="""
    OpenTelemetry traces ingestion endpoint for LLM Analytics.

    Accepts OTLP/HTTP (protobuf) format traces following the OpenTelemetry Protocol specification.
    Converts OTel spans to PostHog AI events using PostHog-native and GenAI semantic conventions.

    Supported conventions:
    - PostHog native: posthog.ai.* attributes (highest priority)
    - GenAI semantic conventions: gen_ai.* attributes (fallback)

    Example OTel SDK configuration:
    ```python
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    exporter = OTLPSpanExporter(
        endpoint="https://app.posthog.com/api/projects/{project_id}/ai/otel/traces",
        headers={"Authorization": "Bearer phc_your_project_token"}
    )
    ```

    Authentication:
    - Use your project API token (starts with phc_...), NOT a personal API key
    - Token can be provided via Authorization header (Bearer token) or ?token= query parameter

    Rate limits and quotas apply as per normal PostHog event ingestion.
    """,
    request={"application/x-protobuf": bytes},
    responses={
        200: {"description": "Traces accepted for processing"},
        400: {"description": "Invalid OTLP format or validation errors"},
        401: {"description": "Authentication failed"},
        413: {"description": "Request too large (exceeds span/attribute limits)"},
    },
)
@api_view(["POST"])
@authentication_classes([ProjectTokenAuthentication])
@permission_classes([])
def otel_traces_endpoint(request: HttpRequest, project_id: int) -> Response:
    """
    Process OTLP trace export requests.

    This endpoint:
    1. Validates authentication and project access
    2. Parses OTLP protobuf payload
    3. Validates against size/span limits
    4. Transforms OTel spans to PostHog AI events
    5. Routes events to capture pipeline for ingestion
    """

    # Get authenticated team from request
    # ProjectTokenAuthentication returns (team, token) tuple
    if not hasattr(request, "user") or not isinstance(request.user, Team):
        return Response(
            {
                "error": "Invalid authentication. Use project token (phc_...) in Authorization header or ?token= parameter."
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    team = request.user

    # Verify the team ID matches the project_id in URL
    if team.id != project_id:
        return Response(
            {"error": "Project ID in URL does not match authenticated project token"},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Check content type
    content_type = request.content_type or ""
    if "protobuf" not in content_type and "octet-stream" not in content_type:
        return Response(
            {
                "error": f"Invalid content type: {content_type}. Expected application/x-protobuf or application/octet-stream"
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Get raw protobuf body
    protobuf_data = request.body

    if not protobuf_data:
        return Response(
            {"error": "Empty request body"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Parse baggage from headers (for session context)
        baggage_header = request.headers.get("baggage")
        baggage = parse_baggage_header(baggage_header) if baggage_header else {}

        # Parse OTLP protobuf
        parsed_request = parse_otlp_trace_request(protobuf_data)

        # Validate request
        validation_errors = validate_otlp_request(parsed_request)
        if validation_errors:
            logger.warning(
                "otel_traces_validation_failed",
                team_id=team.id,
                errors=validation_errors,
            )
            return Response(
                {"error": "Validation failed", "details": validation_errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Transform spans to AI events
        events = transform_spans_to_ai_events(parsed_request, baggage)

        # Route to capture pipeline
        capture_events(events, team)

        return Response(
            {
                "status": "success",
                "message": "Traces ingested successfully",
                "spans_received": len(parsed_request["spans"]),
                "events_created": len(events),
            },
            status=status.HTTP_200_OK,
        )

    except ValidationError as e:
        logger.warning(
            "otel_traces_validation_error",
            team_id=team.id,
            error=str(e),
        )
        return Response(
            {"error": str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        logger.error(
            "otel_traces_processing_error",
            team_id=team.id,
            error=str(e),
            exc_info=True,
        )
        return Response(
            {"error": "Internal server error processing traces"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def parse_otlp_trace_request(protobuf_data: bytes) -> dict[str, Any]:
    """
    Parse OTLP ExportTraceServiceRequest from protobuf bytes.

    Returns dict with:
    - spans: list of parsed span dicts
    - resource: dict of resource attributes
    - scope: dict of instrumentation scope info
    """
    return parse_otlp_request(protobuf_data)


def validate_otlp_request(parsed_request: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Validate OTLP request against limits.

    Returns list of validation errors (empty if valid).
    """
    errors = []
    spans = parsed_request.get("spans", [])

    # Check span count
    if len(spans) > OTEL_LIMITS["MAX_SPANS_PER_REQUEST"]:
        errors.append(
            {
                "field": "request.spans",
                "value": len(spans),
                "limit": OTEL_LIMITS["MAX_SPANS_PER_REQUEST"],
                "message": f"Request contains {len(spans)} spans, maximum is {OTEL_LIMITS['MAX_SPANS_PER_REQUEST']}. Configure batch size in your OTel SDK (e.g., OTEL_BSP_MAX_EXPORT_BATCH_SIZE).",
            }
        )

    # Validate each span
    for i, span in enumerate(spans):
        # Check span name length
        span_name = span.get("name", "")
        if len(span_name) > OTEL_LIMITS["MAX_SPAN_NAME_LENGTH"]:
            errors.append(
                {
                    "field": f"span[{i}].name",
                    "value": len(span_name),
                    "limit": OTEL_LIMITS["MAX_SPAN_NAME_LENGTH"],
                    "message": f"Span name exceeds {OTEL_LIMITS['MAX_SPAN_NAME_LENGTH']} characters.",
                }
            )

        # Check attribute count
        attributes = span.get("attributes", {})
        if len(attributes) > OTEL_LIMITS["MAX_ATTRIBUTES_PER_SPAN"]:
            errors.append(
                {
                    "field": f"span[{i}].attributes",
                    "value": len(attributes),
                    "limit": OTEL_LIMITS["MAX_ATTRIBUTES_PER_SPAN"],
                    "message": f"Span has {len(attributes)} attributes, maximum is {OTEL_LIMITS['MAX_ATTRIBUTES_PER_SPAN']}.",
                }
            )

        # Check attribute value sizes
        for key, value in attributes.items():
            if isinstance(value, str) and len(value) > OTEL_LIMITS["MAX_ATTRIBUTE_VALUE_LENGTH"]:
                errors.append(
                    {
                        "field": f"span[{i}].attributes.{key}",
                        "value": len(value),
                        "limit": OTEL_LIMITS["MAX_ATTRIBUTE_VALUE_LENGTH"],
                        "message": f"Attribute '{key}' exceeds {OTEL_LIMITS['MAX_ATTRIBUTE_VALUE_LENGTH']} bytes ({len(value)} bytes). Consider reducing payload size.",
                    }
                )

        # Check event count
        events = span.get("events", [])
        if len(events) > OTEL_LIMITS["MAX_EVENTS_PER_SPAN"]:
            errors.append(
                {
                    "field": f"span[{i}].events",
                    "value": len(events),
                    "limit": OTEL_LIMITS["MAX_EVENTS_PER_SPAN"],
                    "message": f"Span has {len(events)} events, maximum is {OTEL_LIMITS['MAX_EVENTS_PER_SPAN']}.",
                }
            )

        # Check link count
        links = span.get("links", [])
        if len(links) > OTEL_LIMITS["MAX_LINKS_PER_SPAN"]:
            errors.append(
                {
                    "field": f"span[{i}].links",
                    "value": len(links),
                    "limit": OTEL_LIMITS["MAX_LINKS_PER_SPAN"],
                    "message": f"Span has {len(links)} links, maximum is {OTEL_LIMITS['MAX_LINKS_PER_SPAN']}.",
                }
            )

    return errors


def transform_spans_to_ai_events(parsed_request: dict[str, Any], baggage: dict[str, str]) -> list[dict[str, Any]]:
    """
    Transform OTel spans to PostHog AI events.

    Uses waterfall pattern for attribute extraction:
    1. PostHog native (posthog.ai.*)
    2. GenAI semantic conventions (gen_ai.*)

    Note: Returns only events ready to send. Events that are first arrivals
    (cached, waiting for logs) are filtered out.
    """
    spans = parsed_request.get("spans", [])
    resource = parsed_request.get("resource", {})
    scope = parsed_request.get("scope", {})

    events = []
    for span in spans:
        event = transform_span_to_ai_event(span, resource, scope, baggage)
        if event is not None:  # Filter out first arrivals (cached, waiting for logs)
            events.append(event)

    return events


def capture_events(events: list[dict[str, Any]], team: Team) -> None:
    """
    Route transformed events to PostHog capture pipeline.

    Uses capture_batch_internal to submit events to capture-rs.
    Events are submitted concurrently for better performance.
    """
    if not events:
        return

    # Submit events to capture pipeline
    futures = capture_batch_internal(
        events=events,
        event_source="otel_traces_ingestion",
        token=team.api_token,
        process_person_profile=False,  # AI events don't need person processing
    )

    # Wait for all futures to complete and check for errors
    errors = []
    for i, future in enumerate(futures):
        try:
            response = future.result()
            if response.status_code not in (200, 201):
                errors.append(f"Event {i}: HTTP {response.status_code}")
        except Exception as e:
            errors.append(f"Event {i}: {str(e)}")

    if errors:
        logger.warning(
            "otel_traces_capture_errors",
            team_id=team.id,
            error_count=len(errors),
            errors=errors[:10],  # Log first 10 errors
        )


@extend_schema(
    description="""
    OpenTelemetry logs ingestion endpoint for LLM Analytics.

    Accepts OTLP/HTTP (protobuf) format logs following the OpenTelemetry Protocol specification.
    Converts OTel log records to PostHog AI events. Logs from GenAI instrumentation typically
    contain message content (prompts/completions) in the body field.

    Supported conventions:
    - GenAI semantic conventions: gen_ai.* attributes
    - Generic OTel log attributes

    Example OTel SDK configuration:
    ```python
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

    exporter = OTLPLogExporter(
        endpoint="https://app.posthog.com/api/projects/{project_id}/ai/otel/logs",
        headers={"Authorization": "Bearer phc_your_project_token"}
    )
    ```

    Authentication:
    - Use your project API token (starts with phc_...), NOT a personal API key
    - Token can be provided via Authorization header (Bearer token) or ?token= query parameter

    Rate limits and quotas apply as per normal PostHog event ingestion.
    """,
    request={"application/x-protobuf": bytes},
    responses={
        200: {"description": "Logs accepted for processing"},
        400: {"description": "Invalid OTLP format or validation errors"},
        401: {"description": "Authentication failed"},
        413: {"description": "Request too large (exceeds log/attribute limits)"},
    },
)
@api_view(["POST"])
@authentication_classes([ProjectTokenAuthentication])
@permission_classes([])
def otel_logs_endpoint(request: HttpRequest, project_id: int) -> Response:
    """
    Process OTLP logs export requests.

    This endpoint:
    1. Validates authentication and project access
    2. Parses OTLP protobuf payload
    3. Validates against size/log limits
    4. Transforms OTel log records to PostHog AI events
    5. Routes events to capture pipeline for ingestion
    """

    # Get authenticated team from request
    # ProjectTokenAuthentication returns (team, token) tuple
    if not hasattr(request, "user") or not isinstance(request.user, Team):
        return Response(
            {
                "error": "Invalid authentication. Use project token (phc_...) in Authorization header or ?token= parameter."
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    team = request.user

    # Verify the team ID matches the project_id in URL
    if team.id != project_id:
        return Response(
            {"error": "Project ID in URL does not match authenticated project token"},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Check content type
    content_type = request.content_type or ""
    if "protobuf" not in content_type and "octet-stream" not in content_type:
        return Response(
            {
                "error": f"Invalid content type: {content_type}. Expected application/x-protobuf or application/octet-stream"
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Get raw protobuf body
    protobuf_data = request.body

    if not protobuf_data:
        return Response(
            {"error": "Empty request body"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Parse OTLP protobuf
        parsed_request = parse_otlp_logs_request(protobuf_data)

        # Validate request
        validation_errors = validate_otlp_logs_request(parsed_request)
        if validation_errors:
            logger.warning(
                "otel_logs_validation_failed",
                team_id=team.id,
                errors=validation_errors,
            )
            return Response(
                {"error": "Validation failed", "details": validation_errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Transform logs to AI events (also caches properties for merging with traces)
        events = transform_logs_to_ai_events(parsed_request)

        # Route merged events to capture pipeline
        capture_events(events, team)

        return Response(
            {
                "status": "success",
                "message": "Logs ingested successfully",
                "logs_received": len(parsed_request["logs"]),
                "events_created": len(events),
            },
            status=status.HTTP_200_OK,
        )

    except ValidationError as e:
        logger.warning(
            "otel_logs_validation_error",
            team_id=team.id,
            error=str(e),
        )
        return Response(
            {"error": str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        logger.error(
            "otel_logs_processing_error",
            team_id=team.id,
            error=str(e),
            exc_info=True,
        )
        return Response(
            {"error": "Internal server error processing logs"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def validate_otlp_logs_request(parsed_request: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Validate OTLP logs request against limits.

    Returns list of validation errors (empty if valid).
    """
    errors = []
    logs = parsed_request.get("logs", [])

    # Check log count
    if len(logs) > OTEL_LIMITS["MAX_LOGS_PER_REQUEST"]:
        errors.append(
            {
                "field": "request.logs",
                "value": len(logs),
                "limit": OTEL_LIMITS["MAX_LOGS_PER_REQUEST"],
                "message": f"Request contains {len(logs)} logs, maximum is {OTEL_LIMITS['MAX_LOGS_PER_REQUEST']}. Configure batch size in your OTel SDK.",
            }
        )

    # Validate each log record
    for i, log_record in enumerate(logs):
        # Check attribute count
        attributes = log_record.get("attributes", {})
        if len(attributes) > OTEL_LIMITS["MAX_ATTRIBUTES_PER_LOG"]:
            errors.append(
                {
                    "field": f"log[{i}].attributes",
                    "value": len(attributes),
                    "limit": OTEL_LIMITS["MAX_ATTRIBUTES_PER_LOG"],
                    "message": f"Log has {len(attributes)} attributes, maximum is {OTEL_LIMITS['MAX_ATTRIBUTES_PER_LOG']}.",
                }
            )

        # Check body size
        body = log_record.get("body")
        if body and isinstance(body, str) and len(body) > OTEL_LIMITS["MAX_LOG_BODY_LENGTH"]:
            errors.append(
                {
                    "field": f"log[{i}].body",
                    "value": len(body),
                    "limit": OTEL_LIMITS["MAX_LOG_BODY_LENGTH"],
                    "message": f"Log body exceeds {OTEL_LIMITS['MAX_LOG_BODY_LENGTH']} bytes ({len(body)} bytes). Consider reducing payload size.",
                }
            )

        # Check attribute value sizes
        for key, value in attributes.items():
            if isinstance(value, str) and len(value) > OTEL_LIMITS["MAX_ATTRIBUTE_VALUE_LENGTH"]:
                errors.append(
                    {
                        "field": f"log[{i}].attributes.{key}",
                        "value": len(value),
                        "limit": OTEL_LIMITS["MAX_ATTRIBUTE_VALUE_LENGTH"],
                        "message": f"Attribute '{key}' exceeds {OTEL_LIMITS['MAX_ATTRIBUTE_VALUE_LENGTH']} bytes ({len(value)} bytes).",
                    }
                )

    return errors


def transform_logs_to_ai_events(parsed_request: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Transform OTel log records to PostHog AI events.

    CRITICAL: In v2 instrumentation, multiple log events (user message, assistant message, etc.)
    arrive in the SAME HTTP request. We must accumulate ALL logs for the same span BEFORE
    calling the event merger to avoid race conditions where the trace consumes partial logs.

    Note: Returns only events ready to send. Events that are first arrivals
    (cached, waiting for traces) are filtered out.
    """
    logs = parsed_request.get("logs", [])
    resource = parsed_request.get("resource", {})
    scope = parsed_request.get("scope", {})

    # Group logs by (trace_id, span_id) to accumulate them before merging
    from collections import defaultdict

    logs_by_span = defaultdict(list)

    for log_record in logs:
        trace_id = log_record.get("trace_id", "")
        span_id = log_record.get("span_id", "")

        if trace_id and span_id:
            logs_by_span[(trace_id, span_id)].append(log_record)
        else:
            # No trace/span ID - process individually
            logs_by_span[(None, None)].append(log_record)

    events = []

    # Process each span's logs together
    for (trace_id, span_id), span_logs in logs_by_span.items():
        if trace_id and span_id:
            # Accumulate properties from all logs for this span
            accumulated_props = {}
            for log_record in span_logs:
                props = build_event_properties(log_record, log_record.get("attributes", {}), resource, scope)
                # Merge properties with special handling for arrays
                for key, value in props.items():
                    if key in ("$ai_input", "$ai_output_choices"):
                        # Concatenate message arrays instead of overwriting
                        if key in accumulated_props and isinstance(accumulated_props[key], list):
                            accumulated_props[key] = accumulated_props[key] + value
                        else:
                            accumulated_props[key] = value
                    else:
                        # For non-array fields, later values override earlier ones
                        accumulated_props[key] = value

            # Now call event merger once with all accumulated properties
            from .event_merger import cache_and_merge_properties

            merged = cache_and_merge_properties(trace_id, span_id, accumulated_props, is_trace=False)

            if merged is not None:
                # Ready to send - create event
                event_type = determine_event_type(span_logs[0], span_logs[0].get("attributes", {}))
                timestamp = calculate_timestamp(span_logs[0])
                distinct_id = extract_distinct_id(resource, span_logs[0].get("attributes", {}))

                # Generate consistent UUID from trace_id + span_id
                import uuid

                namespace = uuid.UUID("00000000-0000-0000-0000-000000000000")
                event_uuid = str(uuid.uuid5(namespace, f"{trace_id}:{span_id}"))

                event = {
                    "event": event_type,
                    "distinct_id": distinct_id,
                    "timestamp": timestamp,
                    "properties": merged,
                    "uuid": event_uuid,
                }
                events.append(event)
        else:
            # No trace/span ID - process logs individually (shouldn't happen in normal v2)
            for log_record in span_logs:
                event = transform_log_to_ai_event(log_record, resource, scope)
                if event is not None:
                    events.append(event)

    return events
