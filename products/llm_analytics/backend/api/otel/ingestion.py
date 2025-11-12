"""
OpenTelemetry traces ingestion API endpoint.

Accepts OTLP/HTTP (protobuf) format traces and converts them to PostHog AI events.

Endpoint: POST /api/projects/:project_id/ai/otel/v1/traces
Content-Type: application/x-protobuf
Authorization: Bearer <api_key>
"""

from typing import Any

from django.http import HttpRequest

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models import Team

logger = structlog.get_logger(__name__)

# OpenTelemetry limits (aligned with plugin-server validation)
OTEL_LIMITS = {
    "MAX_SPANS_PER_REQUEST": 1000,
    "MAX_ATTRIBUTES_PER_SPAN": 128,
    "MAX_EVENTS_PER_SPAN": 128,
    "MAX_LINKS_PER_SPAN": 128,
    "MAX_ATTRIBUTE_VALUE_LENGTH": 100_000,  # 100KB
    "MAX_SPAN_NAME_LENGTH": 1024,
}


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
        endpoint="https://app.posthog.com/api/projects/{project_id}/ai/otel/v1/traces",
        headers={"Authorization": "Bearer phc_your_api_key"}
    )
    ```

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
@authentication_classes([PersonalAPIKeyAuthentication])
@permission_classes([IsAuthenticated])
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

    # Verify team access
    try:
        team = Team.objects.get(id=project_id, organization=request.user.current_organization)
    except Team.DoesNotExist:
        return Response(
            {"error": "Project not found or access denied"},
            status=status.HTTP_404_NOT_FOUND,
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

    logger.info(
        "otel_traces_received",
        team_id=team.id,
        content_length=len(protobuf_data),
        content_type=content_type,
    )

    try:
        # Parse OTLP protobuf (TODO: implement parser)
        # For now, return a placeholder response
        # parsed_request = parse_otlp_trace_request(protobuf_data)

        # Validate request
        # validation_errors = validate_otlp_request(parsed_request)
        # if validation_errors:
        #     return Response(
        #         {"errors": validation_errors},
        #         status=status.HTTP_400_BAD_REQUEST,
        #     )

        # Transform spans to AI events
        # events = transform_spans_to_ai_events(parsed_request, team)

        # Route to capture pipeline
        # capture_events(events, team)

        return Response(
            {
                "status": "success",
                "message": "Traces accepted for processing (stub implementation)",
                # "spans_received": len(parsed_request.spans),
                # "events_created": len(events),
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

    TODO: Implement using opentelemetry-proto package

    Returns dict with:
    - resource_spans: list of ResourceSpans
    - spans: flattened list of Span objects
    """
    raise NotImplementedError("OTLP protobuf parsing not yet implemented")


def validate_otlp_request(parsed_request: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Validate OTLP request against limits.

    Returns list of validation errors (empty if valid).
    """
    errors = []

    # TODO: Implement validation
    # - Check span count
    # - Check attribute counts
    # - Check attribute value sizes
    # - Check span name lengths

    return errors


def transform_spans_to_ai_events(parsed_request: dict[str, Any], team: Team) -> list[dict[str, Any]]:
    """
    Transform OTel spans to PostHog AI events.

    Uses waterfall pattern for attribute extraction:
    1. PostHog native (posthog.ai.*)
    2. GenAI semantic conventions (gen_ai.*)
    """
    # TODO: Implement transformation
    # - Extract attributes using conventions
    # - Determine event type ($ai_generation, $ai_span, etc.)
    # - Build event properties
    # - Calculate latency
    # - Handle baggage for session context

    raise NotImplementedError("Span transformation not yet implemented")


def capture_events(events: list[dict[str, Any]], team: Team) -> None:
    """
    Route transformed events to PostHog capture pipeline.

    TODO: Use capture_internal or direct Kafka ingestion
    """
    raise NotImplementedError("Event capture not yet implemented")
