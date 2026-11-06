from typing import Any, cast

from django.http import Http404

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Team, User
from posthog.permissions import APIScopePermission
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.signals.backend.facade import goal_scouts as api
from products.signals.backend.presentation.goal_scout_serializers import (
    GoalScoutActivitySerializer,
    GoalScoutActSerializer,
    GoalScoutBuildSerializer,
    GoalScoutDetailSerializer,
    GoalScoutEntrySerializer,
    GoalScoutGuardrailOptionSerializer,
    GoalScoutGuardrailRequestSerializer,
    GoalScoutIdeaSerializer,
    GoalScoutLabelsRequestSerializer,
    GoalScoutLabelsSerializer,
    GoalScoutMeasureRequestSerializer,
    GoalScoutMeasureSearchSerializer,
    GoalScoutMetricPreviewQuerySerializer,
    GoalScoutMetricSerializer,
    GoalScoutWriteSerializer,
)
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission

WRITE_FIELDS = {
    "statement": "belief",
    "budget_cents": "budget_cents",
    "target": "target",
    "goal_insight": "insight_short_id",
    "goal_description": "goal_description",
    "goal_metric": "metric_name",
    "unit": "unit",
    "direction": "direction",
    "secondary_metrics": "guardrails",
    "repositories": "repositories",
    "title": "name",
    "area": "area",
}
AI_THROTTLES = [AIBurstRateThrottle, AISustainedRateThrottle]


class SignalScoutGoalViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    pagination_class = None
    lookup_field = "id"
    lookup_value_regex = "[0-9a-f-]{36}"

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not api.goal_scouts_enabled(self.canonical_team):
            raise PermissionDenied("Goal scouts are not enabled for this project.")

    def handle_exception(self, exc: Exception) -> Response:
        return super().handle_exception(Http404("Goal not found.") if isinstance(exc, api.GoalNotFound) else exc)

    @property
    def canonical_team(self) -> Team:
        return self.team.parent_team if self.team.parent_team_id and self.team.parent_team else self.team

    @property
    def acting_user(self) -> User:
        return cast(User, self.request.user)

    @validated_request(responses={200: OpenApiResponse(response=GoalScoutEntrySerializer(many=True))})
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        return Response(GoalScoutEntrySerializer(api.list_goals(self.canonical_team, self.acting_user), many=True).data)

    @validated_request(
        request_serializer=GoalScoutWriteSerializer,
        responses={201: OpenApiResponse(response=GoalScoutDetailSerializer)},
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        data = request.validated_data
        created = api.create_goal(
            self.canonical_team,
            self.acting_user,
            api.GoalInput(
                name=data["title"],
                belief=data["statement"],
                area=data.get("area", ""),
                repositories=data["repositories"],
                insight_short_id=data.get("goal_insight") or "",
                goal_description=(data.get("goal_description") or "").strip(),
                metric_name=data["goal_metric"],
                unit=data.get("unit", ""),
                direction=data.get("direction") or "increase",
                guardrails=[dict(item) for item in data.get("secondary_metrics") or []],
                target=data.get("target"),
                budget_cents=data["budget_cents"],
                ideas=data.get("ideas") or [],
            ),
        )
        return Response(GoalScoutDetailSerializer(created).data, status=201)

    @validated_request(responses={200: OpenApiResponse(response=GoalScoutDetailSerializer)})
    def retrieve(self, request: ValidatedRequest, id: str, **kwargs: Any) -> Response:
        return Response(GoalScoutDetailSerializer(api.goal_detail(self.canonical_team, self.acting_user, id)).data)

    @extend_schema(request=GoalScoutWriteSerializer, responses={200: GoalScoutDetailSerializer})
    def partial_update(self, request: Request, id: str, **kwargs: Any) -> Response:
        serializer = GoalScoutWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = {WRITE_FIELDS[key]: value for key, value in serializer.validated_data.items() if key in WRITE_FIELDS}
        if "guardrails" in changes:
            changes["guardrails"] = [dict(item) for item in changes["guardrails"]]
        if "insight_short_id" in changes:
            changes["insight_short_id"] = changes["insight_short_id"] or None
        updated = api.update_goal(self.canonical_team, self.acting_user, id, changes)
        return Response(GoalScoutDetailSerializer(updated).data)

    @validated_request(responses={200: OpenApiResponse(response=GoalScoutDetailSerializer)})
    @action(detail=True, methods=["post"])
    def close(self, request: ValidatedRequest, id: str, **kwargs: Any) -> Response:
        return Response(GoalScoutDetailSerializer(api.close_goal(self.canonical_team, self.acting_user, id)).data)

    @validated_request(
        request_serializer=GoalScoutIdeaSerializer,
        responses={200: OpenApiResponse(response=GoalScoutDetailSerializer)},
    )
    @action(detail=True, methods=["post"])
    def ideas(self, request: ValidatedRequest, id: str, **kwargs: Any) -> Response:
        updated = api.add_owner_idea(self.canonical_team, self.acting_user, id, request.validated_data["title"])
        return Response(GoalScoutDetailSerializer(updated).data)

    @validated_request(
        request_serializer=GoalScoutBuildSerializer,
        responses={200: OpenApiResponse(response=GoalScoutDetailSerializer)},
    )
    @action(detail=True, methods=["post"])
    def build(self, request: ValidatedRequest, id: str, **kwargs: Any) -> Response:
        updated = api.build_idea(
            self.canonical_team,
            self.acting_user,
            id,
            request.validated_data["work_id"],
            dict(request.validated_data.get("plan") or {}),
        )
        return Response(GoalScoutDetailSerializer(updated).data)

    @validated_request(
        request_serializer=GoalScoutActSerializer,
        responses={200: OpenApiResponse(response=GoalScoutDetailSerializer)},
    )
    @action(detail=True, methods=["post"])
    def act(self, request: ValidatedRequest, id: str, **kwargs: Any) -> Response:
        updated = api.act_on_work(
            self.canonical_team,
            self.acting_user,
            id,
            request.validated_data["work_id"],
            request.validated_data["action"],
        )
        return Response(GoalScoutDetailSerializer(updated).data)

    @validated_request(responses={200: OpenApiResponse(response=GoalScoutActivitySerializer(many=True))})
    @action(detail=True, methods=["get"])
    def activity(self, request: ValidatedRequest, id: str, **kwargs: Any) -> Response:
        entries = api.goal_activity(self.canonical_team, self.acting_user, id)
        return Response(GoalScoutActivitySerializer(entries, many=True).data)

    @validated_request(
        query_serializer=GoalScoutMetricPreviewQuerySerializer,
        responses={200: OpenApiResponse(response=GoalScoutMetricSerializer)},
    )
    @action(detail=False, methods=["get"], url_path="metric_preview")
    def metric_preview(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        preview = api.metric_preview(self.canonical_team, self.acting_user, request.validated_query_data["insight"])
        return Response(GoalScoutMetricSerializer(preview).data)

    @validated_request(
        request_serializer=GoalScoutMeasureRequestSerializer,
        responses={200: OpenApiResponse(response=GoalScoutMeasureSearchSerializer)},
    )
    @action(detail=False, methods=["post"], throttle_classes=AI_THROTTLES)
    def measures(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        search = api.measure_options(self.canonical_team, self.acting_user, request.validated_data["goal"])
        return Response(GoalScoutMeasureSearchSerializer(search).data)

    @validated_request(
        request_serializer=GoalScoutGuardrailRequestSerializer,
        responses={200: OpenApiResponse(response=GoalScoutGuardrailOptionSerializer(many=True))},
    )
    @action(detail=False, methods=["post"], throttle_classes=AI_THROTTLES)
    def guardrails(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        options = api.guardrail_options(
            self.canonical_team, self.acting_user, request.validated_data["goal"], request.validated_data["measure"]
        )
        return Response(GoalScoutGuardrailOptionSerializer(options, many=True).data)

    @validated_request(
        request_serializer=GoalScoutLabelsRequestSerializer,
        responses={200: OpenApiResponse(response=GoalScoutLabelsSerializer)},
    )
    @action(detail=False, methods=["post"], throttle_classes=AI_THROTTLES)
    def labels(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        labels = api.belief_labels(self.canonical_team, request.validated_data["belief"])
        return Response(GoalScoutLabelsSerializer(labels).data)
