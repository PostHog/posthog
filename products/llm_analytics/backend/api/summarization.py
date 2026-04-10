"""
Django REST API endpoint for LLM trace and event summarization.

This ViewSet provides AI-powered summarization of LLM traces and events using
line-numbered text representations and LLM calls.

Endpoints:
- POST /api/projects/:id/llm_analytics/summarization/ - Summarize trace or event
- POST /api/projects/:id/llm_analytics/summarization/batch_check/ - Check cached summaries for multiple traces
"""

import time

from django.core.cache import cache

import orjson
import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import DateRange, IntervalType, TraceQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.hogql_queries.ai.trace_query_runner import TraceQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.permissions import AccessControlPermission
from posthog.rate_limit import (
    LLMAnalyticsSummarizationBurstThrottle,
    LLMAnalyticsSummarizationDailyThrottle,
    LLMAnalyticsSummarizationSustainedThrottle,
)

from products.llm_analytics.backend.api.metrics import llma_track_latency
from products.llm_analytics.backend.summarization.llm import summarize
from products.llm_analytics.backend.summarization.models import SummarizationMode
from products.llm_analytics.backend.summarization.utils import get_summary_cache_key
from products.llm_analytics.backend.text_repr.formatters import (
    FormatterOptions,
    format_event_text_repr,
    format_trace_text_repr,
    llm_trace_to_formatter_format,
)

logger = structlog.get_logger(__name__)


# Request/Response Serializers
class SummarizeRequestSerializer(serializers.Serializer):
    summarize_type = serializers.ChoiceField(
        choices=["trace", "event"],
        required=False,
        help_text="Type of entity to summarize. Inferred automatically when using trace_id or generation_id.",
    )
    mode = serializers.ChoiceField(
        choices=[m.value for m in SummarizationMode],
        default=SummarizationMode.MINIMAL.value,
        help_text="Summary detail level: 'minimal' for 3-5 points, 'detailed' for 5-10 points",
    )
    data = serializers.JSONField(  # type: ignore[assignment]
        required=False,
        help_text="Data to summarize. For traces: {trace, hierarchy}. For events: {event}. "
        "Not required when using trace_id or generation_id.",
    )
    force_refresh = serializers.BooleanField(
        default=False,
        required=False,
        help_text="Force regenerate summary, bypassing cache",
    )
    model = serializers.CharField(
        default=None,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="LLM model to use (defaults based on provider)",
    )
    # ID-based lookup fields (alternative to data)
    trace_id = serializers.CharField(
        required=False,
        help_text="Trace ID to summarize. The backend fetches the trace data automatically. "
        "Requires date_from for efficient lookup.",
    )
    generation_id = serializers.CharField(
        required=False,
        help_text="Generation event UUID to summarize. The backend fetches the event data automatically. "
        "Requires date_from for efficient lookup.",
    )
    date_from = serializers.CharField(
        required=False,
        default=None,
        allow_null=True,
        help_text="Start of date range for ID-based lookup (e.g. '-7d' or '2026-01-01'). Defaults to -30d.",
    )
    date_to = serializers.CharField(
        required=False,
        default=None,
        allow_null=True,
        help_text="End of date range for ID-based lookup. Defaults to now.",
    )

    def validate(self, attrs: dict) -> dict:
        has_data = "data" in attrs and attrs["data"] is not None
        has_trace_id = bool(attrs.get("trace_id"))
        has_generation_id = bool(attrs.get("generation_id"))
        has_id = has_trace_id or has_generation_id

        if has_data and has_id:
            raise serializers.ValidationError("Provide either 'data' or a trace_id/generation_id, not both.")
        if not has_data and not has_id:
            raise serializers.ValidationError("Provide either 'data' or a trace_id/generation_id.")
        if has_trace_id and has_generation_id:
            raise serializers.ValidationError("Provide either trace_id or generation_id, not both.")

        # When using IDs, override summarize_type to prevent mismatches
        if has_trace_id:
            attrs["summarize_type"] = "trace"
        elif has_generation_id:
            attrs["summarize_type"] = "event"

        # summarize_type is required when using data
        if has_data and not attrs.get("summarize_type"):
            raise serializers.ValidationError("summarize_type is required when using 'data'.")

        return attrs


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


class BatchCheckRequestSerializer(serializers.Serializer):
    trace_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="List of trace IDs to check for cached summaries",
        max_length=100,
    )
    mode = serializers.ChoiceField(
        choices=[m.value for m in SummarizationMode],
        default=SummarizationMode.MINIMAL.value,
        help_text="Summary detail level to check for",
    )
    model = serializers.CharField(
        default=None,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="LLM model used for cached summaries",
    )


class CachedSummarySerializer(serializers.Serializer):
    trace_id = serializers.CharField()
    title = serializers.CharField()
    cached = serializers.BooleanField(default=True)


class BatchCheckResponseSerializer(serializers.Serializer):
    summaries = CachedSummarySerializer(many=True)


class LLMAnalyticsSummarizationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for LLM trace and event summarization.

    Provides AI-powered summarization using line-numbered text representations.
    """

    scope_object = "llm_analytics"
    permission_classes = [AccessControlPermission]

    def get_throttles(self):
        """Apply rate limiting to prevent abuse of summarization endpoint."""
        return [
            LLMAnalyticsSummarizationBurstThrottle(),
            LLMAnalyticsSummarizationSustainedThrottle(),
            LLMAnalyticsSummarizationDailyThrottle(),
        ]

    def _validate_feature_access(self, request: Request) -> None:
        """Validate that the user is authenticated and AI data processing is approved."""
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        if not self.organization.is_ai_data_processing_approved:
            raise exceptions.PermissionDenied(
                "AI data processing must be approved by your organization before using summarization"
            )

    def _get_cache_key(
        self,
        summarize_type: str,
        entity_id: str,
        mode: str,
        model: str | None = None,
    ) -> str:
        """Generate cache key for summary results.

        Args:
            summarize_type: 'trace' or 'event'
            entity_id: Unique identifier for the entity being summarized
            mode: Summary detail level ('minimal' or 'detailed')
            model: LLM model
        """
        return get_summary_cache_key(self.team_id, summarize_type, entity_id, mode, model)

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

    def _fetch_trace_data(self, trace_id: str, date_from: str | None, date_to: str | None) -> tuple[str, dict]:
        """Fetch trace by ID and return (entity_id, entity_data) for summarization."""
        date_range = DateRange(
            date_from=date_from or "-30d",
            date_to=date_to,
        )
        runner = TraceQueryRunner(
            team=self.team,
            query=TraceQuery(traceId=trace_id, dateRange=date_range),
        )
        response = runner.calculate()

        if not response.results:
            raise exceptions.NotFound(f"Trace '{trace_id}' not found in the given date range.")

        trace_obj = response.results[0]
        trace_dict, hierarchy = llm_trace_to_formatter_format(trace_obj)
        return trace_id, {"trace": trace_dict, "hierarchy": hierarchy}

    def _fetch_generation_data(
        self, generation_id: str, date_from: str | None, date_to: str | None
    ) -> tuple[str, dict]:
        """Fetch a single generation event by UUID and return (entity_id, entity_data) for summarization."""
        from datetime import datetime

        qdr = QueryDateRange(
            DateRange(date_from=date_from or "-30d", date_to=date_to),
            self.team,
            IntervalType.DAY,
            datetime.now(),
        )

        result = execute_hogql_query(
            query=parse_select(
                """
                SELECT uuid, event, timestamp, properties
                FROM events
                WHERE event = '$ai_generation'
                  AND uuid = {generation_uuid}
                  AND timestamp >= {date_from}
                  AND timestamp <= {date_to}
                LIMIT 1
                """,
            ),
            placeholders={
                "generation_uuid": ast.Constant(value=generation_id),
                "date_from": ast.Constant(value=qdr.date_from().isoformat()),
                "date_to": ast.Constant(value=qdr.date_to().isoformat()),
            },
            team=self.team,
        )

        if not result.results:
            raise exceptions.NotFound(f"Generation '{generation_id}' not found in the given date range.")

        row = result.results[0]
        props = row[3]
        if isinstance(props, str):
            props = orjson.loads(props)

        event_data = {
            "id": str(row[0]),
            "event": row[1],
            "timestamp": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
            "properties": props,
        }
        return generation_id, {"event": event_data}

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
            text, _ = format_trace_text_repr(
                trace=entity_data["trace"],
                hierarchy=entity_data["hierarchy"],
                options=options,
            )
            return text
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

**Two ways to use this endpoint:**

1. **By ID (recommended):** Pass `trace_id` or `generation_id` with an optional `date_from`/`date_to`.
   The backend fetches the data automatically. `summarize_type` is inferred.
2. **By data:** Pass the full trace/event data blob in `data` with `summarize_type`.
   This is how the frontend uses it.

**Summary Format:**
- Title (concise, max 10 words)
- Mermaid flow diagram showing the main flow
- 3-10 summary bullets with line references
- "Interesting Notes" section for failures, successes, or unusual patterns
- Line references in [L45] or [L45-52] format pointing to relevant sections

The response includes the structured summary, the text representation, and metadata.
        """,
        tags=["LLM Analytics"],
    )
    @llma_track_latency("llma_summarize")
    @monitor(feature=None, endpoint="llma_summarize", method="POST")
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
            force_refresh = serializer.validated_data["force_refresh"]
            model = serializer.validated_data.get("model")
            # Treat empty string as None for model
            if model == "":
                model = None

            trace_id = serializer.validated_data.get("trace_id")
            generation_id = serializer.validated_data.get("generation_id")
            date_from = serializer.validated_data.get("date_from")
            date_to = serializer.validated_data.get("date_to")

            if trace_id:
                entity_id, entity_data = self._fetch_trace_data(trace_id, date_from, date_to)
            elif generation_id:
                entity_id, entity_data = self._fetch_generation_data(generation_id, date_from, date_to)
            else:
                data = serializer.validated_data["data"]
                entity_id, entity_data = self._extract_entity_id(summarize_type, data)

            cache_key = self._get_cache_key(summarize_type, entity_id, mode, model)
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

            start_time = time.time()
            user_distinct_id = getattr(request.user, "distinct_id", None)
            summary = summarize(
                text_repr=text_repr,
                team_id=self.team_id,
                mode=mode,
                model=model,
                user_id=user_distinct_id,
            )

            duration_seconds = time.time() - start_time

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

            # Track user action
            report_user_action(
                self.request.user,
                "llma summarization generated",
                {
                    "summarize_type": summarize_type,
                    "entity_id": entity_id,
                    "mode": mode,
                    "text_repr_length": len(text_repr),
                    "force_refresh": force_refresh,
                    "duration_seconds": duration_seconds,
                },
                team=self.team,
                request=self.request,
            )

            return Response(result, status=status.HTTP_200_OK)

        except exceptions.APIException:
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

    @extend_schema(
        request=BatchCheckRequestSerializer,
        responses={
            200: BatchCheckResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
        },
        description="""
Check which traces have cached summaries available.

This endpoint allows batch checking of multiple trace IDs to see which ones
have cached summaries. Returns only the traces that have cached summaries
with their titles.

**Use Cases:**
- Load cached summaries on session view load
- Avoid unnecessary LLM calls for already-summarized traces
- Display summary previews without generating new summaries
        """,
        tags=["LLM Analytics"],
    )
    @action(detail=False, methods=["post"], url_path="batch_check")
    @llma_track_latency("llma_summarize_batch_check")
    @monitor(feature=None, endpoint="llma_summarize_batch_check", method="POST")
    def batch_check(self, request: Request, **kwargs) -> Response:
        """
        Check which traces have cached summaries.

        POST /api/projects/:id/llm_analytics/summarization/batch_check/
        """
        self._validate_feature_access(request)

        serializer = BatchCheckRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        trace_ids = serializer.validated_data["trace_ids"]
        mode = serializer.validated_data["mode"]
        model = serializer.validated_data.get("model")
        # Treat empty string as None for model
        if model == "":
            model = None

        summaries = []
        for trace_id in trace_ids:
            cache_key = self._get_cache_key("trace", trace_id, mode, model)
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                summary_data = cached_result.get("summary", {})
                title = summary_data.get("title", "Untitled trace")
                summaries.append(
                    {
                        "trace_id": trace_id,
                        "title": title,
                        "cached": True,
                    }
                )

        logger.info(
            "Batch checked summaries",
            trace_count=len(trace_ids),
            cached_count=len(summaries),
            mode=mode,
            team_id=self.team_id,
        )

        return Response({"summaries": summaries}, status=status.HTTP_200_OK)
