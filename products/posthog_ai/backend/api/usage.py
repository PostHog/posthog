"""Report PostHog AI credit usage to the surfaces that offer a `/usage` command.

A cloud agent and the Slack app answer the command from here rather than from a model call, so the
numbers match what the Max chat shows for the same team.
"""

from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.response import Response

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.rate_limit import AIUsageRateThrottle, ClickHouseSustainedRateThrottle

from products.posthog_ai.backend.services.usage.report import UsageReport, build_usage_report


class AIUsageQuerySerializer(serializers.Serializer):
    conversation_id = serializers.UUIDField(
        required=False,
        help_text=(
            "The conversation to report on, which is the `$ai_session_id` its generations carry: "
            "the Max conversation for a chat, the task for an agent run. Omitted, the report covers "
            "the team only."
        ),
    )
    conversation_started_at = serializers.DateTimeField(
        required=False,
        help_text=(
            "When the conversation started. Only a Max conversation can be looked up here, so a "
            "caller that knows its own start time passes it; without one the reported period bounds "
            "the search and a conversation older than the period is undercounted."
        ),
    )
    product = serializers.CharField(
        required=False,
        help_text=(
            "The `ai_product` of the calling surface, e.g. `slack_app` or `posthog_code`. Adds a row "
            "for what that product alone spent. A product with no credit counter is reported as null."
        ),
    )


class AIUsageProductSerializer(serializers.Serializer):
    # `label` is taken by DRF's own field attribute, so the wire name is `name`.
    name = serializers.CharField(help_text="What a person calls the product, e.g. `PostHog Desktop`.")
    credits = serializers.IntegerField(help_text="Credits the product spent over the reported period.")
    separate_bucket = serializers.BooleanField(
        help_text=(
            "True when the product bills against its own credit counter, so its credits are not part "
            "of the PostHog AI total in this response."
        )
    )


class AIUsageResponseSerializer(serializers.Serializer):
    conversation_credits = serializers.IntegerField(
        allow_null=True,
        help_text="Credits spent in the requested conversation. Null when no conversation was requested.",
    )
    period_credits = serializers.IntegerField(
        help_text="PostHog AI credits the team spent over the reported period, across every product."
    )
    free_tier_credits = serializers.IntegerField(help_text="The team's free tier limit in credits.")
    remaining_credits = serializers.IntegerField(
        help_text="Free tier credits left. Negative once the team is over the limit."
    )
    period_label = serializers.CharField(
        help_text=(
            "`Billing period`, or `Past 30 days` when billing has not told us the team's period. "
            "Every credit figure in the response covers this period."
        )
    )
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()
    conversation_start = serializers.DateTimeField(
        allow_null=True, help_text="When the conversation started, when that is known."
    )
    product = AIUsageProductSerializer(allow_null=True)
    message = serializers.CharField(
        help_text=(
            "The whole report as Markdown, so every surface renders one wording. Clients that lay "
            "the numbers out themselves read the fields above instead."
        )
    )


def serialize_usage_report(report: UsageReport) -> dict[str, Any]:
    return {
        "conversation_credits": report.conversation_credits,
        "period_credits": report.period_credits,
        "free_tier_credits": report.free_tier_credits,
        "remaining_credits": report.remaining_credits,
        "period_label": report.usage_period.label,
        "period_start": report.usage_period.start,
        "period_end": report.usage_period.end,
        "conversation_start": report.conversation_start,
        "product": (
            {
                "name": report.product.label,
                "credits": report.product.credits,
                "separate_bucket": report.product.separate_bucket,
            }
            if report.product
            else None
        ),
        "message": report.message,
    }


class _SingletonSchema(PostHogAutoSchema):
    """Prevents drf-spectacular from wrapping the ``list`` response in an array.

    The report is one object per project, not a collection, and the schema is what an MCP client
    reads to know the shape it will get.
    """

    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class AIUsageViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Read-only view of a team's PostHog AI credit usage."""

    schema = _SingletonSchema()
    scope_object = "project"
    required_scopes = ["project:read"]
    http_method_names = ["get", "head", "options"]
    # A cache miss costs up to three ClickHouse scans over the billing period, so this endpoint
    # carries its own per-project budget rather than the general ClickHouse burst rate.
    throttle_classes = [AIUsageRateThrottle, ClickHouseSustainedRateThrottle]

    @validated_request(
        query_serializer=AIUsageQuerySerializer,
        responses={200: OpenApiResponse(response=AIUsageResponseSerializer, description="PostHog AI usage")},
        summary="Get a team's PostHog AI usage",
        description=(
            "Return credits spent in one conversation, by the calling product, and across PostHog AI, "
            "for the team's current billing period."
        ),
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        query = request.validated_query_data
        report = build_usage_report(
            self.team,
            conversation_id=query.get("conversation_id"),
            conversation_started_at=query.get("conversation_started_at"),
            product=query.get("product"),
        )
        return Response(AIUsageResponseSerializer(serialize_usage_report(report)).data)
