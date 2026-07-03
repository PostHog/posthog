from django.shortcuts import get_object_or_404

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.plan_mode.queries import fetch_planning_marker_report_ids
from products.signals.backend.plan_mode.serializers import (
    InboxPlanCreatedSerializer,
    InboxPlanCreateSerializer,
    InboxPlanFinishedSerializer,
    InboxPlanImplementationStartedSerializer,
    InboxPlanNotReadySerializer,
    InboxPlanReportSerializer,
)
from products.signals.backend.plan_mode.service import PlanNotReadyError, create_plan, finish_plan


class InboxPlanViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The inbox Plan tab's surface — plan reports ("projects").

    List membership and ordering come from ClickHouse (the backing `inbox`/`plan` signals,
    most-recent-first); rows are enriched from Postgres. `create` starts the interactive planning
    conversation; `finish` finalizes a draft plan (user-driven defaults, backing signal, owner scout).
    """

    scope_object = "task"
    serializer_class = InboxPlanReportSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    # Membership is resolved from ClickHouse, so there is no model queryset to scope. Set to none() to
    # satisfy the mixin's model introspection without exposing an unscoped queryset.
    queryset = SignalReport.objects.none()

    @extend_schema(responses=InboxPlanReportSerializer(many=True))
    def list(self, request: Request, *args, **kwargs) -> Response:
        # Membership is the Postgres planning marker alone (exists from creation, so drafts are never
        # lost) — plans have no backing signal and live outside the grouping pipeline. Drafts lead,
        # then finished plans, each newest-first.
        marker_ids = fetch_planning_marker_report_ids(self.team.id)

        reports: list[SignalReport] = []
        draft_ids: set[str] = set()
        if marker_ids:
            finished_ids = {
                str(report_id)
                for report_id in SignalReportArtefact.objects.filter(
                    team_id=self.team.id,
                    report_id__in=marker_ids,
                    type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT,
                ).values_list("report_id", flat=True)
            }
            draft_ids = {report_id for report_id in marker_ids if report_id not in finished_ids}
            ordered_ids = [
                *(report_id for report_id in marker_ids if report_id in draft_ids),
                *(report_id for report_id in marker_ids if report_id not in draft_ids),
            ]
            reports_by_id = {
                str(report.id): report
                for report in SignalReport.objects.filter(team=self.team, id__in=ordered_ids).exclude(
                    status=SignalReport.Status.DELETED
                )
            }
            reports = [reports_by_id[report_id] for report_id in ordered_ids if report_id in reports_by_id]

        page = self.paginate_queryset(reports)
        serializer_context = {**self.get_serializer_context(), "draft_report_ids": draft_ids}
        if page is not None:
            serializer = InboxPlanReportSerializer(page, many=True, context=serializer_context)
            return self.get_paginated_response(serializer.data)

        serializer = InboxPlanReportSerializer(reports, many=True, context=serializer_context)
        return Response(serializer.data)

    @validated_request(
        request_serializer=InboxPlanCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=InboxPlanCreatedSerializer,
                description="Plan report created and planning conversation started.",
            ),
        },
        summary="Create a new plan",
        description=(
            "Create a draft plan report and start its interactive planning conversation with a cloud "
            "agent. The plan stays a draft until it is finalized via the finish endpoint."
        ),
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        created = create_plan(
            team=self.team,
            user=request.user,
            initial_description=request.validated_data["initial_description"],
        )
        response = InboxPlanCreatedSerializer(
            {"report_id": created.report_id, "task_id": created.task_id, "run_id": created.run_id}
        )
        return Response(response.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                response=InboxPlanImplementationStartedSerializer, description="Implementation pass started."
            ),
            400: OpenApiResponse(
                description="A pass is already in flight, or the plan lacks a repository / resolvable owner."
            ),
            404: OpenApiResponse(description="Plan report not found for this project."),
        },
        summary="Start an implementation pass",
        description=(
            "Manually start one implementation pass for the plan — the same in-flight-guarded path the "
            "owner scout and Finish plan use. Fails (400) while a previous pass is still running."
        ),
    )
    @action(detail=True, methods=["post"], url_path="start_implementation")
    def start_implementation(self, request: Request, *args, **kwargs) -> Response:
        from products.signals.backend.scout_harness.tools.report import (  # noqa: PLC0415 — avoid circular import via scout harness
            start_implementation_for_report,
        )
        from products.signals.backend.scout_report.persistence import (  # noqa: PLC0415 — avoid circular import via scout harness
            InvalidScoutReportError,
        )

        report = get_object_or_404(
            SignalReport.objects.filter(team=self.team).exclude(status=SignalReport.Status.DELETED),
            id=kwargs["pk"],
        )
        try:
            started = start_implementation_for_report(
                team=self.team, report_id=str(report.id), triggered_by=f"user:{request.user.id}"
            )
        except InvalidScoutReportError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            InboxPlanImplementationStartedSerializer(
                {
                    "task_id": started.task_id,
                    "task_run_id": started.task_run_id,
                    "repository": started.repository,
                }
            ).data
        )

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(response=InboxPlanFinishedSerializer, description="Plan finished."),
            400: OpenApiResponse(
                response=InboxPlanNotReadySerializer,
                description="The plan is missing required artefacts and cannot be finished yet.",
            ),
            404: OpenApiResponse(description="Plan report not found for this project."),
        },
        summary="Finish a plan",
        description=(
            "Finalize a draft plan: write the user-driven defaults (P1, safe, immediately actionable), "
            "create the plan's owner scout, and auto-start the first implementation pass (best-effort; "
            "the owner scout progresses the work on its schedule regardless). Requires title, summary, "
            "repository selection, owners, and priority to be in place. Idempotent — finishing again "
            "never starts a second pass."
        ),
    )
    @action(detail=True, methods=["post"], url_path="finish")
    def finish(self, request: Request, *args, **kwargs) -> Response:
        report = get_object_or_404(
            SignalReport.objects.filter(team=self.team).exclude(status=SignalReport.Status.DELETED),
            id=kwargs["pk"],
        )
        try:
            finished = finish_plan(team=self.team, user=request.user, report=report)
        except PlanNotReadyError as e:
            return Response({"missing": e.missing}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            InboxPlanFinishedSerializer(
                {
                    "finished": True,
                    "scout_skill_name": finished.scout_skill_name,
                    "implementation_task_id": finished.implementation_task_id,
                }
            ).data
        )
