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

from products.outcomes.backend.criteria import AGGREGATIONS, CriteriaValidationError, parse_criteria
from products.outcomes.backend.models import Outcome, OutcomeLatch
from products.outcomes.backend.tasks import calculate_outcome

logger = structlog.get_logger(__name__)


@extend_schema_field(
    {
        "type": "object",
        "description": "A standard PostHog property filter (event property, person property, cohort, HogQL, ...), "
        "in the same shape the insights API accepts.",
        "additionalProperties": True,
    }
)
class PropertyFilterField(serializers.JSONField):
    pass


class OutcomeAtomSerializer(serializers.Serializer):
    event = serializers.CharField(max_length=400, help_text="Name of the event this condition aggregates.")
    properties = serializers.ListField(
        child=PropertyFilterField(),
        required=False,
        default=list,
        help_text="Property filters an event must match to count toward this condition.",
    )
    aggregation = serializers.ChoiceField(
        choices=list(AGGREGATIONS),
        default="count",
        help_text="Monotone aggregation over matching events: count of events, sum of a numeric property, "
        "or number of distinct values of a property.",
    )
    aggregation_property = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        max_length=400,
        help_text="Event property to sum or count distinct values of; required for sum and distinct, "
        "must be empty for count.",
    )
    threshold = serializers.FloatField(
        default=1,
        help_text="The condition is satisfied once the aggregation reaches at least this value. "
        "Must be a whole number of at least 1 for count and distinct, greater than 0 for sum.",
    )


class OutcomePathSerializer(serializers.Serializer):
    atoms = OutcomeAtomSerializer(
        many=True, help_text="Conditions combined within this path; all must be met unless min_matches is set."
    )
    min_matches = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        min_value=1,
        help_text="Satisfy the path when at least this many of its conditions are met (M-of-N). "
        "Leave empty to require all of them.",
    )


class OutcomeCriteriaSerializer(serializers.Serializer):
    paths = OutcomePathSerializer(
        many=True, help_text="Paths OR'd together: a person reaches the outcome by completing any one path."
    )


# "Outcome" is already taken in the OpenAPI schema by session summaries.
@extend_schema_serializer(component_name="OutcomeDefinition")
class OutcomeSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    criteria = OutcomeCriteriaSerializer(
        help_text="Monotone criteria: paths OR'd together, conditions AND'd within a path (optionally M-of-N)."
    )
    reached_count = serializers.SerializerMethodField(
        help_text="Number of persons who have reached this outcome so far."
    )

    class Meta:
        model = Outcome
        fields = [
            "id",
            "name",
            "description",
            "criteria",
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

    def validate_criteria(self, value: dict[str, Any]) -> dict[str, Any]:
        try:
            parse_criteria(value)
        except CriteriaValidationError as e:
            raise serializers.ValidationError(str(e))
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Criteria are immutable once facts exist: latched rows were computed against the
        # old definition and reached facts never un-reach. Archive-and-recreate instead.
        if self.instance is not None and "criteria" in attrs:
            if attrs["criteria"] != self.instance.criteria and self.instance.latches.exists():
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


@extend_schema_field(
    {
        "type": "object",
        "description": "Aggregate values only: the winning path index and, per condition, "
        "the attained value against its threshold at latch time.",
        "additionalProperties": True,
    }
)
class EvidenceField(serializers.JSONField):
    pass


class OutcomeLatchSerializer(serializers.ModelSerializer):
    evidence = EvidenceField(read_only=True)

    class Meta:
        model = OutcomeLatch
        fields = ["id", "person_id", "distinct_id", "reached_at", "evidence", "created_at"]
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
