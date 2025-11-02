"""
Django REST API endpoint for LLM trace text representation.

This ViewSet provides a Django REST API for generating text representations of LLM events.
Uses pure Python formatters for all processing (no plugin-server dependency).

Architecture:
- Frontend: Calls this API with auth/permissions
- Django views: Call formatters directly
- Python backend: Imports formatters directly (no API call needed)

Endpoints:
- POST /api/llm_analytics/text_repr/ - Stringify single event
- POST /api/llm_analytics/text_repr/batch/ - Stringify multiple events
"""

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.llm_analytics.backend.text_repr.formatters import format_event_text_repr, format_trace_text_repr

logger = structlog.get_logger(__name__)


# Request/Response Serializers for OpenAPI documentation
class TextReprOptionsSerializer(serializers.Serializer):
    max_length = serializers.IntegerField(
        required=False,
        help_text="Maximum length of generated text (default: 50000)",
    )
    truncated = serializers.BooleanField(
        required=False,
        help_text="Use truncation for long content within events (default: true)",
    )
    truncate_buffer = serializers.IntegerField(
        required=False,
        help_text="Characters to show at start/end when truncating (default: 1000)",
    )
    include_markers = serializers.BooleanField(
        required=False,
        help_text="Use interactive markers for frontend vs plain text for backend/LLM (default: true)",
    )
    collapsed = serializers.BooleanField(
        required=False,
        help_text="Show summary vs full tree hierarchy for traces (default: false)",
    )
    include_metadata = serializers.BooleanField(
        required=False,
        help_text="Include metadata in response",
    )
    include_hierarchy = serializers.BooleanField(
        required=False,
        help_text="Include hierarchy information (for traces)",
    )
    max_depth = serializers.IntegerField(
        required=False,
        help_text="Maximum depth for hierarchical rendering",
    )


class TextReprRequestSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(
        choices=["$ai_generation", "$ai_span", "$ai_trace"],
        help_text="Type of LLM event to stringify",
    )
    data = serializers.JSONField(
        help_text="Event data to stringify. For traces, should include 'trace' and 'hierarchy' fields.",
    )
    options = TextReprOptionsSerializer(
        required=False,
        help_text="Optional configuration for text generation",
    )


class TextReprMetadataSerializer(serializers.Serializer):
    event_type = serializers.CharField(required=False)
    event_id = serializers.CharField(required=False)
    trace_id = serializers.CharField(required=False)
    rendering = serializers.CharField()
    char_count = serializers.IntegerField()
    truncated = serializers.BooleanField()
    error = serializers.CharField(required=False)


class TextReprResponseSerializer(serializers.Serializer):
    text = serializers.CharField(
        help_text="Generated text representation of the event",
    )
    metadata = TextReprMetadataSerializer(
        help_text="Metadata about the text representation",
    )


class BatchItemSerializer(serializers.Serializer):
    event_id = serializers.CharField(
        required=False,
        help_text="Optional event ID for tracking",
    )
    event_type = serializers.ChoiceField(
        choices=["$ai_generation", "$ai_span", "$ai_trace"],
        help_text="Type of LLM event to stringify",
    )
    data = serializers.JSONField(
        help_text="Event data to stringify",
    )


class BatchTextReprRequestSerializer(serializers.Serializer):
    items = serializers.ListField(
        child=BatchItemSerializer(),
        min_length=1,
        max_length=50,
        help_text="List of events to stringify (max 50)",
    )
    options = TextReprOptionsSerializer(
        required=False,
        help_text="Optional configuration applied to all items",
    )


class BatchTextReprResponseSerializer(serializers.Serializer):
    results = serializers.ListField(
        child=TextReprResponseSerializer(),
        help_text="List of text representations for each item",
    )


class LLMAnalyticsTextReprViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for LLM trace text representation.

    Provides endpoints for converting LLM trace events into human-readable text.
    Uses pure Python formatters for all processing.
    """

    scope_object = "llm_analytics"

    @extend_schema(
        request=TextReprRequestSerializer,
        responses={
            200: TextReprResponseSerializer,
            400: OpenApiTypes.OBJECT,
            500: OpenApiTypes.OBJECT,
            503: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                "Generation Example",
                description="Stringify an $ai_generation event",
                value={
                    "event_type": "$ai_generation",
                    "data": {
                        "id": "gen_123",
                        "properties": {
                            "$ai_input": [
                                {
                                    "role": "user",
                                    "content": "What is the capital of France?",
                                }
                            ],
                            "$ai_output_choices": [
                                {
                                    "message": {
                                        "role": "assistant",
                                        "content": "The capital of France is Paris.",
                                    }
                                }
                            ],
                        },
                    },
                    "options": {"max_length": 10000},
                },
                request_only=True,
            ),
            OpenApiExample(
                "Trace Example",
                description="Stringify a full trace with hierarchy",
                value={
                    "event_type": "$ai_trace",
                    "data": {
                        "trace": {
                            "trace_id": "trace_123",
                            "name": "ChatBot Interaction",
                        },
                        "hierarchy": [
                            {
                                "id": "gen_1",
                                "event": "$ai_generation",
                                "children": [],
                            }
                        ],
                    },
                },
                request_only=True,
            ),
            OpenApiExample(
                "Success Response",
                value={
                    "text": "INPUT:\n\n[1] USER\n\nWhat is the capital of France?\n\n...",
                    "metadata": {
                        "event_type": "$ai_generation",
                        "event_id": "gen_123",
                        "rendering": "detailed",
                        "char_count": 150,
                        "truncated": False,
                    },
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
        description="""
Generate a human-readable text representation of an LLM trace event.

This endpoint converts LLM analytics events ($ai_generation, $ai_span, or $ai_trace)
into formatted text representations suitable for display, logging, or analysis.

**Supported Event Types:**
- `$ai_generation`: Individual LLM API calls with input/output messages
- `$ai_span`: Logical spans with state transitions
- `$ai_trace`: Full traces with hierarchical structure

**Options:**
- `max_length`: Maximum character count (default: 50000)
- `truncated`: Enable middle-content truncation within events (default: true)
- `truncate_buffer`: Characters at start/end when truncating (default: 1000)
- `include_markers`: Use interactive markers vs plain text indicators (default: true)
  - Frontend: set true for `<<<TRUNCATED|base64|...>>>` markers
  - Backend/LLM: set false for `... (X chars truncated) ...` text
- `collapsed`: Show summary vs full trace tree (default: false)
- `include_hierarchy`: Include tree structure for traces (default: true)
- `max_depth`: Maximum depth for hierarchical rendering (default: unlimited)

**Use Cases:**
- Frontend display: `truncated: true, include_markers: true`
- Backend LLM context (summary): `truncated: true, include_markers: false, collapsed: true`
- Backend LLM context (full): `truncated: false`

The response includes the formatted text and metadata about the rendering.
        """,
        tags=["LLM Analytics"],
    )
    def create(self, request: Request, **kwargs) -> Response:
        """
        Stringify a single LLM trace event.

        POST /api/llm_analytics/text_repr/
        """
        serializer = TextReprRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            event_type = serializer.validated_data["event_type"]
            data = serializer.validated_data["data"]
            options = serializer.validated_data.get("options", {})

            # Call Python formatters directly
            if event_type == "$ai_trace":
                # For traces, expect data to have trace and hierarchy
                text = format_trace_text_repr(
                    trace=data.get("trace", {}),
                    hierarchy=data.get("hierarchy", []),
                    options=options,
                )
            else:
                # For $ai_generation and $ai_span
                text = format_event_text_repr(event=data, options=options)

            # Build response with metadata
            result = {
                "text": text,
                "metadata": {
                    "event_type": event_type,
                    "event_id": data.get("id"),
                    "trace_id": data.get("properties", {}).get("$ai_trace_id") or data.get("trace_id"),
                    "rendering": "detailed",
                    "char_count": len(text),
                    "truncated": len(text) > options.get("max_length", 50000),
                },
            }

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception(
                "Unexpected error in text repr stringify",
                event_type=serializer.validated_data["event_type"],
                team_id=self.team_id,
            )
            return Response(
                {"error": "Internal server error", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        request=BatchTextReprRequestSerializer,
        responses={
            200: BatchTextReprResponseSerializer,
            400: OpenApiTypes.OBJECT,
            500: OpenApiTypes.OBJECT,
            503: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                "Batch Request",
                description="Stringify multiple events in one request (max 50)",
                value={
                    "items": [
                        {
                            "event_id": "gen_1",
                            "event_type": "$ai_generation",
                            "data": {"properties": {"$ai_input": "Hello"}},
                        },
                        {
                            "event_id": "span_1",
                            "event_type": "$ai_span",
                            "data": {"properties": {"$ai_input_state": "Processing"}},
                        },
                    ],
                    "options": {"max_length": 5000},
                },
                request_only=True,
            ),
            OpenApiExample(
                "Batch Response",
                value={
                    "results": [
                        {
                            "text": "INPUT:\n\n[User input]\n\nHello\n\n...",
                            "metadata": {
                                "event_type": "$ai_generation",
                                "event_id": "gen_1",
                                "rendering": "detailed",
                                "char_count": 50,
                                "truncated": False,
                            },
                        },
                        {
                            "text": "SPAN: Processing\n\n...",
                            "metadata": {
                                "event_type": "$ai_span",
                                "event_id": "span_1",
                                "rendering": "detailed",
                                "char_count": 30,
                                "truncated": False,
                            },
                        },
                    ]
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
        description="""
Generate text representations for multiple LLM trace events in a single request.

**Benefits:**
- Reduced HTTP overhead (one request for multiple events)
- Consistent options applied to all events
- Maintains order of input items

**Limits:**
- Maximum 50 items per batch
- Each item subject to same constraints as single stringify

Use this endpoint when you need to stringify multiple events efficiently,
such as when displaying a list of traces or processing events in bulk.
        """,
        tags=["LLM Analytics"],
    )
    @action(detail=False, methods=["post"], url_path="batch")
    def stringify_batch(self, request: Request) -> Response:
        """
        Stringify multiple LLM trace events in a batch.

        POST /api/llm_analytics/text_repr/batch/
        """
        serializer = BatchTextReprRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            items = serializer.validated_data["items"]
            options = serializer.validated_data.get("options", {})

            # Validate batch size
            if not items:
                return Response(
                    {"error": "items list cannot be empty"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if len(items) > 50:
                return Response(
                    {"error": "Maximum 50 items per batch"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Process each item
            results = []
            for item in items:
                try:
                    event_type = item["event_type"]
                    data = item["data"]

                    # Call Python formatters directly
                    if event_type == "$ai_trace":
                        text = format_trace_text_repr(
                            trace=data.get("trace", {}),
                            hierarchy=data.get("hierarchy", []),
                            options=options,
                        )
                    else:
                        text = format_event_text_repr(event=data, options=options)

                    # Build result with metadata
                    results.append(
                        {
                            "text": text,
                            "metadata": {
                                "event_type": event_type,
                                "event_id": item.get("event_id") or data.get("id"),
                                "trace_id": data.get("properties", {}).get("$ai_trace_id") or data.get("trace_id"),
                                "rendering": "detailed",
                                "char_count": len(text),
                                "truncated": len(text) > options.get("max_length", 50000),
                            },
                        }
                    )
                except Exception as e:
                    # Add error result for this item
                    logger.exception(
                        "Error stringifying item in batch",
                        item=item,
                        error=str(e),
                    )
                    results.append(
                        {
                            "text": "",
                            "metadata": {
                                "event_type": item.get("event_type"),
                                "event_id": item.get("event_id"),
                                "rendering": "error",
                                "char_count": 0,
                                "truncated": False,
                                "error": str(e),
                            },
                        }
                    )

            return Response({"results": results}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception(
                "Unexpected error in text repr batch stringify",
                item_count=len(serializer.validated_data.get("items", [])),
                team_id=self.team_id,
            )
            return Response(
                {"error": "Internal server error", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
