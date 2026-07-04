from typing import cast

from django.db.models import QuerySet
from django.utils import timezone

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.pulse.backend.api.brief import PULSE_FEATURE_FLAG
from products.pulse.backend.api.feedback import (
    FeedbackFieldsSerializerMixin,
    FeedbackVoteRequestSerializer,
    record_vote,
)
from products.pulse.backend.models import Opportunity


class ProposedExperimentTargetMetricSerializer(serializers.Serializer):
    insight_short_id = serializers.CharField(help_text="Short ID of the insight the experiment should move.")


class ProposedExperimentSerializer(serializers.Serializer):
    hypothesis = serializers.CharField(help_text="The testable hypothesis grounded in the opportunity's evidence.")
    flag_key_suggestion = serializers.CharField(help_text="Suggested feature flag key for the experiment.")
    target_metric = ProposedExperimentTargetMetricSerializer(
        allow_null=True,
        help_text=(
            "The goal metric the experiment should move, as an insight reference. Null when the proposal's "
            "metric did not validate against the opportunity's cited insight refs."
        ),
    )
    variant_sketch = serializers.CharField(help_text="Short sketch of the control and test variants.")


class OpportunitySerializer(FeedbackFieldsSerializerMixin, serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="User who created the opportunity.")
    evidence = serializers.ListField(
        child=serializers.DictField(),
        read_only=True,
        help_text="Evidence refs backing the opportunity: type, ref, and label per entry.",
    )
    proposed_experiment = ProposedExperimentSerializer(
        read_only=True,
        allow_null=True,
        help_text=(
            "Experiment proposed by goal-conditioned synthesis: hypothesis, flag key suggestion, target "
            "metric, and variant sketch. Only ever set on goal-relevant opportunities; null otherwise."
        ),
    )

    class Meta:
        model = Opportunity
        fields = [
            "id",
            "kind",
            "status",
            "title",
            "summary",
            "suggested_action",
            "evidence",
            "goal_relevant",
            "proposed_experiment",
            "first_seen_brief",
            "my_vote",
            "helpful_count",
            "not_helpful_count",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "kind": {
                "help_text": "What the opportunity asks for: build (product opportunity), fix (broken PostHog resource), or instrument (missing tracking)."
            },
            "status": {"help_text": "Lifecycle status: open, dismissed, acted, or resolved."},
            "title": {"help_text": "Short, actionable opportunity title."},
            "summary": {"help_text": "What was observed and why it matters."},
            "suggested_action": {"help_text": "The concrete next step suggested for the team."},
            "goal_relevant": {
                "help_text": "Whether this opportunity plausibly advances the focus goal of the brief it surfaced in."
            },
            "first_seen_brief": {"help_text": "The brief this opportunity first surfaced in, if any."},
        }


class OpportunityViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    serializer_class = OpportunitySerializer
    posthog_feature_flag = PULSE_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission]
    # Fail-closed manager raises if `.all()` runs at import; the real per-request
    # scoping happens in safely_get_queryset.
    queryset = Opportunity.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[Opportunity]) -> QuerySet[Opportunity]:
        scoped = Opportunity.objects.for_team(self.team_id).select_related("created_by").order_by("-created_at")
        if self.action == "list":
            scoped = self._apply_list_filters(scoped)
        return scoped

    def _apply_list_filters(self, queryset: QuerySet[Opportunity]) -> QuerySet[Opportunity]:
        for field, valid_values in (("status", Opportunity.Status.values), ("kind", Opportunity.Kind.values)):
            value = self.request.query_params.get(field)
            if value is None:
                continue
            if value not in valid_values:
                raise ValidationError({field: f"Must be one of: {', '.join(valid_values)}."})
            # nosemgrep: no-request-param-orm-filter -- field is a hardcoded loop key (status/kind); value is validated against the model's allowlist above
            queryset = queryset.filter(**{field: value})
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, enum=Opportunity.Status.values, description="Filter by lifecycle status."),
            OpenApiParameter("kind", str, enum=Opportunity.Kind.values, description="Filter by opportunity kind."),
        ]
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=None,
        responses={
            200: OpportunitySerializer,
            400: OpenApiResponse(description="The opportunity is not open, so it cannot be dismissed"),
        },
    )
    @action(methods=["POST"], detail=True)
    def dismiss(self, request: Request, **kwargs) -> Response:
        return self._transition(Opportunity.Status.OPEN, Opportunity.Status.DISMISSED, "opportunity_dismissed")

    @extend_schema(
        request=None,
        responses={
            200: OpportunitySerializer,
            400: OpenApiResponse(description="The opportunity is not open, so it cannot be marked as acted"),
        },
    )
    @action(methods=["POST"], detail=True)
    def acted(self, request: Request, **kwargs) -> Response:
        return self._transition(Opportunity.Status.OPEN, Opportunity.Status.ACTED, "opportunity_acted")

    @extend_schema(
        request=None,
        responses={
            200: OpportunitySerializer,
            400: OpenApiResponse(description="The opportunity is not dismissed, so it cannot be reopened"),
        },
    )
    @action(methods=["POST"], detail=True)
    def reopen(self, request: Request, **kwargs) -> Response:
        # Reopening only flips status back to OPEN. It does not resurrect suppressed briefs'
        # content: persist's dedup keys off the fingerprint's existence across ALL statuses,
        # so the row keeps suppressing re-creation whether open or dismissed.
        return self._transition(Opportunity.Status.DISMISSED, Opportunity.Status.OPEN, "opportunity_reopened")

    @extend_schema(
        request=FeedbackVoteRequestSerializer,
        responses={200: OpportunitySerializer},
    )
    @action(methods=["POST"], detail=True)
    def feedback(self, request: Request, **kwargs) -> Response:
        vote_serializer = FeedbackVoteRequestSerializer(data=request.data)
        vote_serializer.is_valid(raise_exception=True)
        helpful = vote_serializer.validated_data["helpful"]
        opportunity = self.get_object()
        user = cast(User, request.user)
        opportunity = record_vote(Opportunity, self.team_id, opportunity.pk, user.id, helpful)
        # The context props ARE the tuning signal — they let the feedback stream answer "which
        # opportunity shapes are helpful" without joining back to the rows.
        report_user_action(
            user,
            "opportunity_feedback",
            {
                "opportunity_id": str(opportunity.id),
                "helpful": helpful,
                "kind": opportunity.kind,
                "status": opportunity.status,
                "goal_relevant": opportunity.goal_relevant,
                "has_proposed_experiment": opportunity.proposed_experiment is not None,
            },
            team=self.team,
            request=request,
        )
        return Response(self.get_serializer(opportunity).data)

    def _transition(self, expected: Opportunity.Status, target: Opportunity.Status, event: str) -> Response:
        # Known v1 limitation: transitions don't sync the emitted SignalReport (and inbox triage
        # doesn't sync back) — the cross-product lifecycle is an open design question with the
        # signals owners.
        opportunity = self.get_object()
        # Conditional update so concurrent double-clicks are race-safe: the loser matches 0 rows
        # and 400s. auto_now doesn't fire on .update(), so updated_at is set explicitly.
        updated = (
            Opportunity.objects.for_team(self.team_id)
            .filter(pk=opportunity.pk, status=expected)
            .update(status=target, updated_at=timezone.now())
        )
        opportunity.refresh_from_db()
        if not updated:
            raise ValidationError(
                f"This opportunity is {opportunity.status}; it must be {expected} to become {target}."
            )
        report_user_action(
            self.request.user,
            event,
            {
                "opportunity_id": str(opportunity.id),
                "kind": opportunity.kind,
                "status": opportunity.status,
                "goal_relevant": opportunity.goal_relevant,
            },
            team=self.team,
            request=self.request,
        )
        return Response(self.get_serializer(opportunity).data)
