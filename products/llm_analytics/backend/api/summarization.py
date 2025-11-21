"""
Django REST API endpoint for LLM trace and event summarization.

This ViewSet provides AI-powered summarization of LLM traces and events using
line-numbered text representations and LLM calls.

Endpoint:
- POST /api/projects/:id/llm_analytics/summarize/ - Summarize trace or event
"""

from django.conf import settings
from django.core.cache import cache

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
from products.llm_analytics.backend.summarization.llm import summarize
from products.llm_analytics.backend.text_repr.formatters import (
    FormatterOptions,
    format_event_text_repr,
    format_trace_text_repr,
)

logger = structlog.get_logger(__name__)


# Request/Response Serializers
class SummarizeRequestSerializer(serializers.Serializer):
    summarize_type = serializers.ChoiceField(
        choices=["trace", "event"],
        help_text="Type of entity to summarize",
    )
    mode = serializers.ChoiceField(
        choices=["minimal", "detailed"],
        default="minimal",
        help_text="Summary detail level: 'minimal' for 3-5 points, 'detailed' for 5-10 points",
    )
    data = serializers.JSONField(  # type: ignore[assignment]
        help_text="Data to summarize. For traces: {trace, hierarchy}. For events: {event}.",
    )
    force_refresh = serializers.BooleanField(
        default=False,
        required=False,
        help_text="Force regenerate summary, bypassing cache",
    )


class SummaryBulletSerializer(serializers.Serializer):
    text = serializers.CharField()
    line_refs = serializers.CharField()


class InterestingNoteSerializer(serializers.Serializer):
    text = serializers.CharField()
    line_refs = serializers.CharField()  # Can be empty string if no line refs


class StructuredSummarySerializer(serializers.Serializer):
    title = serializers.CharField(help_text="Concise title (no longer than 10 words) summarizing the trace/event")
    flow_diagram = serializers.CharField(help_text="Mermaid flowchart code showing the main flow")
    summary_bullets = SummaryBulletSerializer(many=True, help_text="Main summary bullets")
    interesting_notes = InterestingNoteSerializer(
        many=True, help_text="Interesting notes (0-2 for minimal, more for detailed)"
    )


class SummarizeResponseSerializer(serializers.Serializer):
    summary = StructuredSummarySerializer(
        help_text="Structured AI-generated summary with flow, bullets, and optional notes",
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

    scope_object = "llm_analytics"  # type: ignore[assignment]

    def get_throttles(self):
        """Apply rate limiting to prevent abuse of summarization endpoint."""
        return [ClickHouseBurstRateThrottle(), ClickHouseSustainedRateThrottle()]

    def _validate_feature_access(self, request: Request) -> None:
        """Validate that the user has access to the summarization feature."""
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        if settings.DEBUG:
            return

        # Check feature flag using user's distinct_id to match against person-based cohorts
        if not posthoganalytics.feature_enabled(
            SUMMARIZATION_FEATURE_FLAG,
            str(request.user.distinct_id),
        ):
            raise exceptions.PermissionDenied("LLM trace summarization is not enabled for this user")

    def _get_cache_key(self, summarize_type: str, entity_id: str, mode: str) -> str:
        """Generate cache key for summary results.

        Args:
            summarize_type: 'trace' or 'event'
            entity_id: Unique identifier for the entity being summarized
            mode: Summary detail level ('minimal' or 'detailed')
        """
        return f"llm_summary:{self.team_id}:{summarize_type}:{entity_id}:{mode}"

    def _extract_entity_id(self, summarize_type: str, data: dict) -> tuple[str, dict]:
        """Extract entity ID and validated entity data based on summarize type.

        Args:
            summarize_type: 'trace' or 'event'
            data: Request data containing trace/event information

        Returns:
            Tuple of (entity_id, entity_data) where entity_data is trace or event dict

        Raises:
            ValidationError: If required fields are missing or invalid
        """
        if summarize_type == "trace":
            if not data.get("trace") or not isinstance(data.get("hierarchy"), list):
                raise exceptions.ValidationError("Trace summarization requires 'trace' and 'hierarchy' fields")
            trace = data["trace"]
            entity_id = trace.get("properties", {}).get("$ai_trace_id") or trace.get("id")
            if not entity_id:
                raise exceptions.ValidationError("Trace must have either '$ai_trace_id' or 'id'")
            return entity_id, {"trace": trace, "hierarchy": data["hierarchy"]}
        elif summarize_type == "event":
            if not data.get("event"):
                raise exceptions.ValidationError("Event summarization requires 'event' field")
            event = data["event"]
            entity_id = event.get("id")
            if not entity_id:
                raise exceptions.ValidationError("Event must have an 'id' field")
            return entity_id, {"event": event}
        else:
            raise exceptions.ValidationError(f"Invalid summarize_type: {summarize_type}")

    def _generate_text_repr(self, summarize_type: str, entity_data: dict) -> str:
        """Generate line-numbered text representation for summarization.

        Args:
            summarize_type: 'trace' or 'event'
            entity_data: Dict containing trace/event data

        Returns:
            Line-numbered text representation
        """
        options: FormatterOptions = {
            "include_line_numbers": True,
            "truncated": False,
            "include_markers": False,
            "collapsed": False,
        }

        if summarize_type == "trace":
            return format_trace_text_repr(
                trace=entity_data["trace"],
                hierarchy=entity_data["hierarchy"],
                options=options,
            )
        else:  # event
            return format_event_text_repr(event=entity_data["event"], options=options)

    def _build_summary_response(self, summary, text_repr: str, summarize_type: str) -> dict:
        """Build the API response dict from summary and text representation.

        Args:
            summary: Pydantic summary model from LLM
            text_repr: Line-numbered text representation
            summarize_type: 'trace' or 'event'

        Returns:
            Response dict with summary, text_repr, and metadata
        """
        return {
            "summary": summary.model_dump(),
            "text_repr": text_repr,
            "metadata": {
                "text_repr_length": len(text_repr),
                "summarize_type": summarize_type,
            },
        }

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
- Requires `llm-analytics-summarization` feature flag enabled at team level

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
        self._validate_feature_access(request)

        serializer = SummarizeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            summarize_type = serializer.validated_data["summarize_type"]
            mode = serializer.validated_data["mode"]
            data = serializer.validated_data["data"]
            force_refresh = serializer.validated_data["force_refresh"]

            entity_id, entity_data = self._extract_entity_id(summarize_type, data)

            cache_key = self._get_cache_key(summarize_type, entity_id, mode)
            if not force_refresh:
                cached_result = cache.get(cache_key)
                if cached_result is not None:
                    logger.info(
                        "Returning cached summary",
                        summarize_type=summarize_type,
                        entity_id=entity_id,
                        mode=mode,
                        team_id=self.team_id,
                    )
                    return Response(cached_result, status=status.HTTP_200_OK)

            text_repr = self._generate_text_repr(summarize_type, entity_data)

            summary = async_to_sync(summarize)(
                text_repr=text_repr,
                team_id=self.team_id,
                trace_id=entity_id,
                mode=mode,
            )

            result = self._build_summary_response(summary, text_repr, summarize_type)

            cache.set(cache_key, result, timeout=3600)
            logger.info(
                "Generated and cached new summary",
                summarize_type=summarize_type,
                entity_id=entity_id,
                mode=mode,
                team_id=self.team_id,
                force_refresh=force_refresh,
            )

            return Response(result, status=status.HTTP_200_OK)

        except exceptions.ValidationError:
            raise
        except Exception as e:
            logger.exception(
                "Failed to generate summary",
                summarize_type=serializer.validated_data.get("summarize_type"),
                team_id=self.team_id,
                error=str(e),
            )
            return Response(
                {"error": "Failed to generate summary", "detail": "An error occurred while generating the summary"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
