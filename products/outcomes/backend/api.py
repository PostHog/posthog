from typing import Any

from django.db.models import Count, QuerySet

import structlog
from drf_spectacular.utils import extend_schema, extend_schema_field, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.outcomes.backend.models import OUTCOME_REACHED_EVENT, Outcome, OutcomeLatch
from products.outcomes.backend.tasks import calculate_outcome

logger = structlog.get_logger(__name__)


# "Outcome" is already taken in the OpenAPI schema by session summaries' LLM output.
@extend_schema_serializer(component_name="OutcomeDefinition")
class OutcomeSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    reached_count = serializers.SerializerMethodField(
        help_text="Number of persons who have reached this outcome so far."
    )

    class Meta:
        model = Outcome
        fields = [
            "id",
            "name",
            "description",
            "target_event",
            "threshold",
            "reached_count",
            "last_calculated_at",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = ["id", "reached_count", "last_calculated_at", "created_at", "updated_at", "created_by"]

    @extend_schema_field(serializers.IntegerField())
    def get_reached_count(self, outcome: Outcome) -> int:
        annotated = getattr(outcome, "reached_count", None)
        if annotated is not None:
            return annotated
        return outcome.latches.count()

    def validate_target_event(self, value: str) -> str:
        if value == OUTCOME_REACHED_EVENT:
            raise serializers.ValidationError(
                f"Outcomes cannot be defined over {OUTCOME_REACHED_EVENT} — that would create an evaluation loop."
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Criteria are immutable once facts exist: latched rows were computed against the
        # old definition and reached facts never un-reach. Archive-and-recreate instead.
        if self.instance is not None:
            criteria_changed = any(
                field in attrs and attrs[field] != getattr(self.instance, field)
                for field in ("target_event", "threshold")
            )
            if criteria_changed and self.instance.latches.exists():
                raise serializers.ValidationError(
                    "This outcome already has reached facts, so its criteria can no longer change. "
                    "Create a new outcome instead."
                )
        return attrs

    def create(self, validated_data: dict[str, Any]) -> Outcome:
        team = self.context["get_team"]()
        outcome = Outcome.objects.create(
            team=team,
            created_by=self.context["request"].user,
            **validated_data,
        )
        logger.info("outcome_created", outcome_id=str(outcome.id), team_id=team.id)
        return outcome


class OutcomeLatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = OutcomeLatch
        fields = ["id", "person_id", "distinct_id", "reached_at", "event_count", "created_at"]
        read_only_fields = fields


class OutcomeViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Create, read, update, and delete outcome definitions, and inspect who reached them."""

    scope_object = "INTERNAL"
    # `.unscoped()` avoids the fail-closed manager raising at import (no team context yet);
    # `safely_get_queryset` re-scopes every real query to the team.
    queryset = Outcome.objects.unscoped()
    serializer_class = OutcomeSerializer
    permission_classes = [IsAuthenticated]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return (
            queryset.filter(team_id=self.team_id)
            .annotate(reached_count=Count("latches"))
            .select_related("created_by")
            .order_by("-created_at")
        )

    @extend_schema(
        responses={200: OutcomeLatchSerializer(many=True)},
        description="The most recent persons who reached this outcome (up to 100).",
    )
    @action(methods=["GET"], detail=True, pagination_class=None)
    def reached(self, request: Request, **kwargs: Any) -> Response:
        outcome = self.get_object()
        latches = outcome.latches.order_by("-reached_at")[:100]
        return Response(OutcomeLatchSerializer(latches, many=True).data)

    @extend_schema(
        request=None,
        responses={202: OutcomeSerializer},
        description="Enqueue an immediate recalculation of this outcome instead of waiting for the periodic run.",
    )
    @action(methods=["POST"], detail=True)
    def calculate(self, request: Request, **kwargs: Any) -> Response:
        outcome = self.get_object()
        calculate_outcome.delay(outcome_id=str(outcome.id), team_id=outcome.team_id)
        return Response(self.get_serializer(outcome).data, status=status.HTTP_202_ACCEPTED)
