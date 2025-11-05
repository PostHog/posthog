"""
Django REST API endpoint for LLM trace text representation.

This ViewSet provides a Django REST API for generating text representations of LLM events.
Uses pure Python formatters for all processing (no plugin-server dependency).

Architecture:
- Frontend: Calls this API with auth/permissions for single events
- Python backend: Imports formatters directly (no API call needed)

Endpoint:
- POST /api/llm_analytics/text_repr/ - Stringify single event
"""

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.rate_limit import LLMAnalyticsTextReprBurstThrottle, LLMAnalyticsTextReprSustainedThrottle

from products.llm_analytics.backend.text_repr.formatters import format_event_text_repr, format_trace_text_repr

logger = structlog.get_logger(__name__)


# Request/Response Serializers for OpenAPI documentation
class TextReprOptionsSerializer(serializers.Serializer):
    max_length = serializers.IntegerField(
        required=False,
        help_text="Maximum length of generated text (default: 4000000)",
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
    tools_collapse_threshold = serializers.IntegerField(
        required=False,
        help_text="Number of tools before collapsing the list (default: 5)",
    )
    include_line_numbers = serializers.BooleanField(
        required=False,
        help_text="Prefix each line with line number (default: false)",
    )


class TextReprRequestSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(
        choices=["$ai_generation", "$ai_span", "$ai_embedding", "$ai_trace"],
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


class LLMAnalyticsTextReprViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for LLM trace text representation.

    Provides endpoints for converting LLM trace events into human-readable text.
    Uses pure Python formatters for all processing.
    """

    scope_object = "llm_analytics"

    def get_throttles(self):
        """Apply rate limiting to prevent abuse of text formatting endpoint."""
        return [LLMAnalyticsTextReprBurstThrottle(), LLMAnalyticsTextReprSustainedThrottle()]

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

This endpoint converts LLM analytics events ($ai_generation, $ai_span, $ai_embedding, or $ai_trace)
into formatted text representations suitable for display, logging, or analysis.

**Supported Event Types:**
- `$ai_generation`: Individual LLM API calls with input/output messages
- `$ai_span`: Logical spans with state transitions
- `$ai_embedding`: Embedding generation events (text input → vector)
- `$ai_trace`: Full traces with hierarchical structure

**Options:**
- `max_length`: Maximum character count (default: 4000000)
- `truncated`: Enable middle-content truncation within events (default: true)
- `truncate_buffer`: Characters at start/end when truncating (default: 1000)
- `include_markers`: Use interactive markers vs plain text indicators (default: true)
  - Frontend: set true for `<<<TRUNCATED|base64|...>>>` markers
  - Backend/LLM: set false for `... (X chars truncated) ...` text
- `collapsed`: Show summary vs full trace tree (default: false)
- `include_hierarchy`: Include tree structure for traces (default: true)
- `max_depth`: Maximum depth for hierarchical rendering (default: unlimited)
- `tools_collapse_threshold`: Number of tools before auto-collapsing list (default: 5)
  - Tool lists >5 items show `<<<TOOLS_EXPANDABLE|...>>>` marker for frontend
  - Or `[+] AVAILABLE TOOLS: N` for backend when `include_markers: false`
- `include_line_numbers`: Prefix each line with line number like L001:, L010: (default: false)

**Use Cases:**
- Frontend display: `truncated: true, include_markers: true, include_line_numbers: true`
- Backend LLM context (summary): `truncated: true, include_markers: false, collapsed: true`
- Backend LLM context (full): `truncated: false`

The response includes the formatted text and metadata about the rendering.
        """,
        tags=["LLM Analytics"],
    )
    @monitor(feature=None, endpoint="llm_analytics_text_repr", method="POST")
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

            # Validate input data structure
            if event_type == "$ai_trace":
                if not data.get("trace") or not isinstance(data.get("hierarchy"), list):
                    raise ValidationError("Trace events require 'trace' object and 'hierarchy' array in data field")
            elif "properties" not in data:
                raise ValidationError(f"{event_type} events require 'properties' object in data field")

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

            # Apply max_length cap if output exceeds limit
            max_len = options.get("max_length", 4000000)
            original_length = len(text)
            truncated_by_max_length = original_length > max_len

            if truncated_by_max_length:
                truncation_msg = f"\n\n... [Output truncated at {max_len:,} characters. Original length: {original_length:,} characters]"
                # Reserve space for truncation message
                text = text[: max_len - len(truncation_msg)] + truncation_msg

            # Build response with metadata
            # Extract trace_id - different location for traces vs events
            if event_type == "$ai_trace":
                trace_id = data.get("trace", {}).get("properties", {}).get("$ai_trace_id")
            else:
                trace_id = data.get("properties", {}).get("$ai_trace_id") or data.get("trace_id")

            result = {
                "text": text,
                "metadata": {
                    "event_type": event_type,
                    "event_id": data.get("id"),
                    "trace_id": trace_id,
                    "rendering": "detailed",
                    "char_count": len(text),
                    "truncated": truncated_by_max_length,
                },
            }

            return Response(result, status=status.HTTP_200_OK)

        except ValidationError:
            # Re-raise validation errors to be handled by DRF
            raise
        except ValueError as e:
            # Handle specific formatting/parsing errors
            logger.warning(
                "Invalid data format in text repr request",
                event_type=serializer.validated_data.get("event_type"),
                team_id=self.team_id,
                error=str(e),
            )
            return Response(
                {"error": "Invalid data format", "detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            # Unexpected errors
            logger.exception(
                "Unexpected error in text repr generation",
                event_type=serializer.validated_data.get("event_type"),
                team_id=self.team_id,
            )
            return Response(
                {"error": "Internal server error", "detail": "Failed to generate text representation"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
