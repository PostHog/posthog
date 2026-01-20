"""
Django REST API endpoint for log explanation using AI.

This ViewSet provides AI-powered explanations of individual log entries.

Endpoints:
- POST /api/environments/:id/logs/explainLogWithAI/ - Explain a log entry using AI
"""

from pathlib import Path
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.template import Context, Engine

import structlog
from asgiref.sync import async_to_sync
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ConfigDict, Field
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import sync_execute
from posthog.rate_limit import (
    LLMAnalyticsSummarizationBurstThrottle,
    LLMAnalyticsSummarizationDailyThrottle,
    LLMAnalyticsSummarizationSustainedThrottle,
)

logger = structlog.get_logger(__name__)

EXPLAIN_TIMEOUT = 60


ConfidenceLevel = Literal["high", "medium", "low"]
ActionPriority = Literal["now", "soon", "later"]
SeverityAssessment = Literal["ok", "warning", "error", "critical"]
AttributeType = Literal["log", "resource"]


class ProbableCause(BaseModel):
    """A ranked hypothesis for why this log occurred."""

    model_config = ConfigDict(extra="forbid")

    hypothesis: str = Field(description="What likely caused this log entry")
    confidence: ConfidenceLevel = Field(description="Confidence level: 'high', 'medium', or 'low'")
    reasoning: str = Field(description="Brief reasoning for this hypothesis")


class ImmediateAction(BaseModel):
    """A prioritized action for the on-call engineer."""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(description="What to do")
    priority: ActionPriority = Field(description="Priority level: 'now', 'soon', or 'later'")
    why: str = Field(description="Why this action matters")


class KeyField(BaseModel):
    """An important field from the log that deserves attention."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="The field name/path")
    value: str = Field(description="The field value")
    significance: str = Field(description="Why this field is important")
    attribute_type: AttributeType = Field(
        description="Where this field lives: 'log' for attributes, 'resource' for resource_attributes"
    )


class LogExplanationResponse(BaseModel):
    """Structured response from LLM log explanation - designed for 2AM on-call debugging."""

    model_config = ConfigDict(extra="forbid")

    # Quick glance section
    headline: str = Field(description="5-10 word summary of what happened")
    severity_assessment: SeverityAssessment = Field(
        description="Assessment of severity: 'ok', 'warning', 'error', or 'critical'"
    )
    impact_summary: str = Field(description="Brief statement of what/who is affected")

    # Root cause analysis
    probable_causes: list[ProbableCause] = Field(
        description="Ranked list of 1-3 hypotheses for why this occurred, highest confidence first"
    )

    # Immediate actions
    immediate_actions: list[ImmediateAction] = Field(
        description="Prioritized list of 1-5 actions to take, 'now' items first"
    )

    # Technical breakdown
    technical_explanation: str = Field(
        description="Detailed technical analysis for engineers who want to understand deeply"
    )
    key_fields: list[KeyField] = Field(
        description="Important fields from the log that deserve attention (trace_id, error codes, etc.)"
    )


class ExplainRequestSerializer(serializers.Serializer):
    uuid = serializers.CharField(help_text="UUID of the log entry to explain")
    timestamp = serializers.DateTimeField(help_text="Timestamp of the log entry (used for efficient lookup)")
    force_refresh = serializers.BooleanField(
        default=False,
        required=False,
        help_text="Force regenerate explanation, bypassing cache",
    )


class ProbableCauseSerializer(serializers.Serializer):
    hypothesis = serializers.CharField()
    confidence = serializers.CharField()
    reasoning = serializers.CharField()


class ImmediateActionSerializer(serializers.Serializer):
    action = serializers.CharField()
    priority = serializers.CharField()
    why = serializers.CharField()


class KeyFieldSerializer(serializers.Serializer):
    field = serializers.CharField()
    value = serializers.CharField()
    significance = serializers.CharField()
    attribute_type = serializers.CharField()


class ExplainResponseSerializer(serializers.Serializer):
    headline = serializers.CharField()
    severity_assessment = serializers.CharField()
    impact_summary = serializers.CharField()
    probable_causes = ProbableCauseSerializer(many=True)
    immediate_actions = ImmediateActionSerializer(many=True)
    technical_explanation = serializers.CharField()
    key_fields = KeyFieldSerializer(many=True)


def load_prompt_template(template_name: str, context: dict) -> str:
    """Load and render a Django template file for prompts."""
    templates_dir = Path(__file__).parent / "prompts"
    engine = Engine(dirs=[str(templates_dir)])
    template = engine.get_template(template_name)
    return template.render(Context(context, autoescape=False))


def fetch_log_by_uuid(team_id: int, uuid: str, timestamp: str) -> dict | None:
    """Fetch a single log entry from ClickHouse by UUID.

    The timestamp parameter is required for efficient lookup - it allows ClickHouse
    to use the primary key index instead of scanning all data for the team.
    """
    query = """
        SELECT
            uuid,
            timestamp,
            body,
            mapFilter((k, v) -> not(has(resource_attributes, k)), attributes),
            severity_text,
            service_name,
            resource_attributes,
            hex(trace_id) as trace_id,
            hex(span_id) as span_id,
            event_name
        FROM logs
        WHERE team_id = %(team_id)s
          AND uuid = %(uuid)s
          AND timestamp >= %(timestamp)s - INTERVAL 1 SECOND
          AND timestamp <= %(timestamp)s + INTERVAL 1 SECOND
        LIMIT 1
    """
    results = sync_execute(query, {"team_id": team_id, "uuid": uuid, "timestamp": timestamp})
    if not results:
        return None

    row = results[0]
    return {
        "uuid": row[0],
        "timestamp": row[1].replace(tzinfo=ZoneInfo("UTC")) if row[1] else None,
        "body": row[2],
        "attributes": row[3],  # filtered_attributes from query
        "severity_text": row[4],
        "service_name": row[5],
        "resource_attributes": row[6],
        "trace_id": row[7],
        "span_id": row[8],
        "event_name": row[9],
    }


async def explain_log_with_openai(log_data: dict, team_id: int) -> LogExplanationResponse:
    """Generate explanation using OpenAI API with structured outputs."""
    system_prompt = load_prompt_template("explain_system.djt", {})
    user_prompt = load_prompt_template("explain_user.djt", log_data)

    client = AsyncOpenAI(timeout=EXPLAIN_TIMEOUT)

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = await client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            response_format=cast(
                Any,
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "log_explanation_response",
                        "strict": True,
                        "schema": LogExplanationResponse.model_json_schema(),
                    },
                },
            ),
        )

        content = response.choices[0].message.content
        if not content:
            raise exceptions.ValidationError("OpenAI returned empty response")
        return LogExplanationResponse.model_validate_json(content)
    except exceptions.ValidationError:
        raise
    except Exception as e:
        logger.exception("OpenAI API call failed for log explanation", error=str(e), team_id=team_id)
        raise exceptions.APIException("Failed to generate log explanation")


class LogExplainViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for AI-powered log explanation.

    Fetches a log by UUID and generates an AI explanation.
    """

    scope_object = "logs"
    serializer_class = ExplainRequestSerializer

    def get_throttles(self):
        """Apply rate limiting to prevent abuse of explain endpoint."""
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
                "AI data processing must be approved by your organization before using log explanation"
            )

    def _get_cache_key(self, uuid: str, timestamp: str) -> str:
        """Generate cache key for log explanation results."""
        return f"log_explain:v1:{self.team_id}:{uuid}:{timestamp}"

    def create(self, request: Request, **kwargs) -> Response:
        """
        Explain a log entry using AI.

        POST /api/environments/:id/logs/explainLogWithAI/
        """
        self._validate_feature_access(request)

        serializer = ExplainRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        uuid = serializer.validated_data["uuid"]
        timestamp = serializer.validated_data["timestamp"].isoformat()
        force_refresh = serializer.validated_data.get("force_refresh", False)

        try:
            cache_key = self._get_cache_key(uuid, timestamp)
            if not force_refresh:
                cached_result = cache.get(cache_key)
                if cached_result is not None:
                    logger.info(
                        "Returning cached log explanation",
                        uuid=uuid,
                        team_id=self.team_id,
                    )
                    return Response(cached_result, status=status.HTTP_200_OK)

            log_data = fetch_log_by_uuid(self.team_id, uuid, timestamp)
            if not log_data:
                return Response({"error": "Log not found"}, status=status.HTTP_404_NOT_FOUND)

            explanation = async_to_sync(explain_log_with_openai)(log_data, self.team_id)
            result = explanation.model_dump()

            cache.set(cache_key, result, timeout=3600)
            logger.info(
                "Generated and cached log explanation",
                uuid=uuid,
                team_id=self.team_id,
                force_refresh=force_refresh,
            )

            return Response(result, status=status.HTTP_200_OK)

        except exceptions.ValidationError:
            raise
        except exceptions.APIException:
            raise
        except Exception as e:
            logger.exception(
                "Failed to generate log explanation",
                uuid=uuid,
                team_id=self.team_id,
                error=str(e),
            )
            return Response(
                {
                    "error": "Failed to generate explanation",
                    "detail": "An error occurred while generating the explanation",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
