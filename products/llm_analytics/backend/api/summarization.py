"""
Django REST API endpoint for LLM trace and event summarization.

This ViewSet provides AI-powered summarization of LLM traces and events using
line-numbered text representations and LLM calls.

Endpoint:
- POST /api/projects/:id/llm_analytics/summarize/ - Summarize trace or event
"""

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle

from products.llm_analytics.backend.summarization.constants import SUMMARIZATION_FEATURE_FLAG
from products.llm_analytics.backend.summarization.event import summarize_event
from products.llm_analytics.backend.summarization.trace import summarize_trace
from products.llm_analytics.backend.text_repr.formatters import format_event_text_repr, format_trace_text_repr

logger = structlog.get_logger(__name__)


# Request/Response Serializers
class SummarizeRequestSerializer(serializers.Serializer):
    summarize_type = serializers.ChoiceField(
        choices=["trace", "event"],
        help_text="Type of entity to summarize",
    )
    mode = serializers.ChoiceField(
        choices=["minimal", "detailed"],
        default="detailed",
        help_text="Summary detail level: 'minimal' for 3-5 points, 'detailed' for 5-10 points",
    )
    data = serializers.JSONField(
        help_text="Data to summarize. For traces: {trace, hierarchy}. For events: {event}.",
    )


class SummarizeResponseSerializer(serializers.Serializer):
    summary = serializers.CharField(
        help_text="AI-generated summary with line references",
    )
    text_repr = serializers.CharField(
        help_text="Line-numbered text representation that the summary references",
    )
    metadata = serializers.JSONField(
        required=False,
        help_text="Metadata about the summarization",
    )


class LLMAnalyticsSummarizationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for LLM trace and event summarization.

    Provides AI-powered summarization using line-numbered text representations.
    """

    scope_object = "llm_analytics"

    def get_throttles(self):
        """Apply rate limiting to prevent abuse of summarization endpoint."""
        return [ClickHouseBurstRateThrottle(), ClickHouseSustainedRateThrottle()]

    def _validate_feature_access(self, request: Request) -> None:
        """Validate that the user has access to the summarization feature."""
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        # In development/debug mode, allow access by default
        from django.conf import settings

        if settings.DEBUG:
            return

        # Check feature flag at team level in production
        if not posthoganalytics.feature_enabled(
            SUMMARIZATION_FEATURE_FLAG,
            str(self.team.uuid),
            groups={"team": str(self.team.uuid)},
        ):
            raise exceptions.PermissionDenied("LLM trace summarization is not enabled for this team")

    @extend_schema(
        request=SummarizeRequestSerializer,
        responses={
            200: SummarizeResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            500: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                "Trace Summarization",
                description="Summarize a full trace with hierarchy",
                value={
                    "summarize_type": "trace",
                    "data": {
                        "trace": {
                            "id": "trace_123",
                            "properties": {
                                "$ai_span_name": "ChatBot Interaction",
                            },
                        },
                        "hierarchy": [
                            {
                                "event": {
                                    "id": "gen_1",
                                    "event": "$ai_generation",
                                    "properties": {
                                        "$ai_input": [{"role": "user", "content": "Hello"}],
                                        "$ai_output_choices": [
                                            {"message": {"role": "assistant", "content": "Hi there!"}}
                                        ],
                                    },
                                },
                                "children": [],
                            }
                        ],
                    },
                },
                request_only=True,
            ),
            OpenApiExample(
                "Event Summarization",
                description="Summarize a single generation event",
                value={
                    "summarize_type": "event",
                    "data": {
                        "event": {
                            "id": "gen_456",
                            "event": "$ai_generation",
                            "properties": {
                                "$ai_input": [{"role": "user", "content": "Explain Python"}],
                                "$ai_output_choices": [{"message": {"role": "assistant", "content": "Python is..."}}],
                            },
                        }
                    },
                },
                request_only=True,
            ),
            OpenApiExample(
                "Success Response",
                value={
                    "summary": "## Summary\n- User initiated conversation with greeting [L5-8]\n- Assistant responded with friendly message [L12-15]\n\n## Interesting Notes\n- Standard greeting pattern with no errors",
                    "metadata": {
                        "text_repr_length": 450,
                        "model": "gpt-4.1",
                    },
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
        description="""
Generate an AI-powered summary of an LLM trace or event.

This endpoint analyzes the provided trace/event, generates a line-numbered text
representation, and uses an LLM to create a concise summary with line references.

**Summary Format:**
- 5-10 bullet points covering main flow and key decisions
- "Interesting Notes" section for failures, successes, or unusual patterns
- Line references in [L45] or [L45-52] format pointing to relevant sections

**Feature Flag:**
- Requires `ai-llm-trace-summary` feature flag enabled at team level

**Use Cases:**
- Quick understanding of complex traces
- Identifying key events and patterns
- Debugging with AI-assisted analysis
- Documentation and reporting

The response includes the summary text and optional metadata.
        """,
        tags=["LLM Analytics"],
    )
    @monitor(feature=None, endpoint="llm_analytics_summarize", method="POST")
    def create(self, request: Request, **kwargs) -> Response:
        """
        Summarize a trace or event.

        POST /api/projects/:id/llm_analytics/summarize/
        """
        # Validate feature access
        self._validate_feature_access(request)

        # Validate request
        serializer = SummarizeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            summarize_type = serializer.validated_data["summarize_type"]
            mode = serializer.validated_data.get("mode", "detailed")
            data = serializer.validated_data["data"]

            # Generate line-numbered text representation
            options = {
                "include_line_numbers": True,
                "truncated": False,  # Full content for LLM
                "include_markers": False,  # Plain text for LLM
                "collapsed": False,  # Full hierarchy
            }

            if summarize_type == "trace":
                # Validate trace data
                if not data.get("trace") or not isinstance(data.get("hierarchy"), list):
                    raise exceptions.ValidationError("Trace summarization requires 'trace' and 'hierarchy' fields")

                trace = data["trace"]
                hierarchy = data["hierarchy"]

                # Generate text representation
                text_repr = format_trace_text_repr(trace=trace, hierarchy=hierarchy, options=options)

                # Call summarization with mode
                summary = async_to_sync(summarize_trace)(
                    trace=trace,
                    hierarchy=hierarchy,
                    text_repr=text_repr,
                    mode=mode,
                )

            elif summarize_type == "event":
                # Validate event data
                if not data.get("event"):
                    raise exceptions.ValidationError("Event summarization requires 'event' field")

                event = data["event"]

                # Generate text representation
                text_repr = format_event_text_repr(event=event, options=options)

                # Call summarization with mode
                summary = async_to_sync(summarize_event)(
                    event=event,
                    text_repr=text_repr,
                    mode=mode,
                )

            else:
                raise exceptions.ValidationError(f"Invalid summarize_type: {summarize_type}")

            # Build response
            result = {
                "summary": summary,
                "text_repr": text_repr,  # Include line-numbered text for navigation
                "metadata": {
                    "text_repr_length": len(text_repr),
                    "summarize_type": summarize_type,
                },
            }

            return Response(result, status=status.HTTP_200_OK)

        except exceptions.ValidationError:
            # Re-raise validation errors
            raise
        except Exception as e:
            # Log and return error
            logger.exception(
                "Failed to generate summary",
                summarize_type=serializer.validated_data.get("summarize_type"),
                team_id=self.team_id,
                error=str(e),
            )
            return Response(
                {"error": "Failed to generate summary", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
