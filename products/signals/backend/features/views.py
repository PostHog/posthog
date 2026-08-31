from typing import cast

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
from posthog.models import User
from posthog.permissions import APIScopePermission

from products.signals.backend.features.queries import fetch_feature_report_ids, fetch_feature_stages
from products.signals.backend.features.serializers import (
    InboxFeatureCreatedSerializer,
    InboxFeatureCreateSerializer,
    InboxFeatureDiscoveryCreatedSerializer,
    InboxFeatureDiscoveryCreateSerializer,
    InboxFeatureDiscoveryRunSerializer,
    InboxFeatureErrorSerializer,
    InboxFeatureImplementationStartedSerializer,
    InboxFeaturePlanningFinishedSerializer,
    InboxFeaturePlanningNotReadySerializer,
    InboxFeatureReportSerializer,
)
from products.signals.backend.features.service import (
    FeatureDiscoveryStartError,
    FeaturePlanningNotReadyError,
    create_feature,
    finish_feature_planning,
    start_feature_discovery,
    start_feature_planning_session,
)
from products.signals.backend.models import FeatureDiscoveryRun, SignalReport


class InboxFeatureViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The inbox Features tab's API surface.

    `create` starts a feature's interactive planning phase. `finish_planning` activates its owner
    scout and first implementation pass without ending the feature's lifecycle.
    """

    scope_object = "task"
    serializer_class = InboxFeatureReportSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    # Membership comes from lifecycle artefacts, with task markers retained for legacy reports.
    # An empty queryset satisfies the mixin without exposing unscoped reports.
    queryset = SignalReport.objects.none()

    @extend_schema(responses=InboxFeatureReportSerializer(many=True))
    def list(self, request: Request, *args, **kwargs) -> Response:
        marker_ids = fetch_feature_report_ids(self.team.id)

        reports: list[SignalReport] = []
        feature_stages = fetch_feature_stages(self.team.id, marker_ids)
        if marker_ids:
            ordered_ids = [
                *(report_id for report_id in marker_ids if feature_stages[report_id].value == "staged"),
                *(report_id for report_id in marker_ids if feature_stages[report_id].value == "planning"),
                *(report_id for report_id in marker_ids if feature_stages[report_id].value == "managed"),
            ]
            reports_by_id = {
                str(report.id): report
                for report in SignalReport.objects.filter(team=self.team, id__in=ordered_ids).exclude(
                    status=SignalReport.Status.DELETED
                )
            }
            reports = [reports_by_id[report_id] for report_id in ordered_ids if report_id in reports_by_id]

        page = self.paginate_queryset(reports)
        serializer_context = {**self.get_serializer_context(), "feature_stages": feature_stages}
        if page is not None:
            serializer = InboxFeatureReportSerializer(page, many=True, context=serializer_context)
            return self.get_paginated_response(serializer.data)

        serializer = InboxFeatureReportSerializer(reports, many=True, context=serializer_context)
        return Response(serializer.data)

    @validated_request(
        request_serializer=InboxFeatureCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=InboxFeatureCreatedSerializer,
                description="Feature report created and planning conversation started.",
            ),
        },
        summary="Create a new feature",
        description=(
            "Create a feature report and start an interactive planning conversation with a cloud agent. "
            "The feature remains in planning until the finish planning endpoint is called."
        ),
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        created = create_feature(
            team=self.team,
            user=cast(User, request.user),
            initial_description=request.validated_data["initial_description"],
        )
        response = InboxFeatureCreatedSerializer(
            {"report_id": created.report_id, "task_id": created.task_id, "run_id": created.run_id}
        )
        return Response(response.data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=InboxFeatureDiscoveryCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=InboxFeatureDiscoveryCreatedSerializer,
                description="Feature discovery queued.",
            ),
            503: OpenApiResponse(
                response=InboxFeatureErrorSerializer,
                description="Feature discovery could not be started.",
            ),
        },
        summary="Discover features from a repository",
        description=(
            "Start a background agent that explores a repository and stages structured feature reports. "
            "An optional focus limits discovery to a specific product area."
        ),
    )
    @action(detail=False, methods=["post"], url_path="discover")
    def discover(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        try:
            created = start_feature_discovery(
                team=self.team,
                user=cast(User, request.user),
                repository=request.validated_data["repository"],
                focus=request.validated_data["focus"],
            )
        except FeatureDiscoveryStartError:
            return Response(
                InboxFeatureErrorSerializer(
                    {"detail": "Feature discovery could not start. Check the repository connection and try again."}
                ).data,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            InboxFeatureDiscoveryCreatedSerializer({"run_id": created.run_id}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        responses={200: InboxFeatureDiscoveryRunSerializer(many=True)},
        summary="List feature discovery runs",
        description="Return the 20 most recent discovery runs for this project.",
    )
    @action(detail=False, methods=["get"], url_path="discovery_runs", pagination_class=None)
    def discovery_runs(self, request: Request, *args, **kwargs) -> Response:
        runs = FeatureDiscoveryRun.objects.for_team(self.team.id).order_by("-created_at")[:20]
        return Response(InboxFeatureDiscoveryRunSerializer(runs, many=True).data)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                response=InboxFeatureImplementationStartedSerializer, description="Implementation pass started."
            ),
            400: OpenApiResponse(
                description="A pass is already in flight, or the feature lacks a repository or resolvable owner."
            ),
            404: OpenApiResponse(description="Feature report not found for this project."),
        },
        summary="Start an implementation pass",
        description=(
            "Manually start one implementation pass for the feature. This uses the same guarded path as "
            "the owner scout and finish planning action. It fails while a previous pass is still running."
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
            InboxFeatureImplementationStartedSerializer(
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
            200: OpenApiResponse(
                response=InboxFeaturePlanningFinishedSerializer, description="Feature planning finished."
            ),
            400: OpenApiResponse(
                response=InboxFeaturePlanningNotReadySerializer,
                description="The feature is missing details required to finish planning.",
            ),
            404: OpenApiResponse(description="Feature report not found for this project."),
        },
        summary="Finish planning a feature",
        description=(
            "Complete the feature's initial planning phase, activate its owner scout, and start the first "
            "implementation pass when possible. The feature remains active for ongoing monitoring and "
            "optimization. Requires title, summary, repository selection, owners, and priority. Calling "
            "this again never starts a second first pass."
        ),
    )
    @action(detail=True, methods=["post"], url_path="finish_planning")
    def finish_planning(self, request: Request, *args, **kwargs) -> Response:
        report = get_object_or_404(
            SignalReport.objects.filter(team=self.team).exclude(status=SignalReport.Status.DELETED),
            id=kwargs["pk"],
        )
        try:
            completion = finish_feature_planning(
                team=self.team,
                user=cast(User, request.user),
                report=report,
            )
        except FeaturePlanningNotReadyError as e:
            return Response({"missing": e.missing}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            InboxFeaturePlanningFinishedSerializer(
                {
                    "planning_finished": True,
                    "scout_skill_name": completion.scout_skill_name,
                    "implementation_task_id": completion.implementation_task_id,
                }
            ).data
        )

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                response=InboxFeatureCreatedSerializer,
                description="Feature planning conversation started.",
            ),
            404: OpenApiResponse(description="Feature report not found for this project."),
        },
        summary="Start a feature planning session",
        description=(
            "Start a fresh interactive planning conversation for a new, discovered, or managed feature. The agent "
            "receives the feature's lifecycle context, inspects its selected repository when available, asks about "
            "intended functionality, and updates the same report without changing its lifecycle."
        ),
    )
    @action(detail=True, methods=["post"], url_path="start_planning")
    def start_planning(self, request: Request, *args, **kwargs) -> Response:
        report = get_object_or_404(
            SignalReport.objects.filter(team=self.team).exclude(status=SignalReport.Status.DELETED),
            id=kwargs["pk"],
        )
        created = start_feature_planning_session(
            team=self.team,
            user=cast(User, request.user),
            report=report,
        )
        return Response(
            InboxFeatureCreatedSerializer(
                {
                    "report_id": created.report_id,
                    "task_id": created.task_id,
                    "run_id": created.run_id,
                }
            ).data
        )
