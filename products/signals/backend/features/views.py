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

from products.signals.backend.features.queries import fetch_feature_report_ids
from products.signals.backend.features.serializers import (
    InboxFeatureCreatedSerializer,
    InboxFeatureCreateSerializer,
    InboxFeatureImplementationStartedSerializer,
    InboxFeaturePlanningFinishedSerializer,
    InboxFeaturePlanningNotReadySerializer,
    InboxFeatureReportSerializer,
)
from products.signals.backend.features.service import (
    FeaturePlanningNotReadyError,
    create_feature,
    finish_feature_planning,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact


class InboxFeatureViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The inbox Features tab's API surface.

    `create` starts a feature's interactive planning phase. `finish_planning` activates its owner
    scout and first implementation pass without ending the feature's lifecycle.
    """

    scope_object = "task"
    serializer_class = InboxFeatureReportSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    # Membership is resolved from planning task markers, so this avoids exposing an unscoped queryset
    # while still satisfying the mixin's model introspection.
    queryset = SignalReport.objects.none()

    @extend_schema(responses=InboxFeatureReportSerializer(many=True))
    def list(self, request: Request, *args, **kwargs) -> Response:
        # The planning task marker is created with the feature, so features remain discoverable
        # throughout planning without entering the signal grouping pipeline.
        marker_ids = fetch_feature_report_ids(self.team.id)

        reports: list[SignalReport] = []
        planning_report_ids: set[str] = set()
        if marker_ids:
            planning_finished_ids = {
                str(report_id)
                for report_id in SignalReportArtefact.objects.filter(
                    team_id=self.team.id,
                    report_id__in=marker_ids,
                    type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT,
                ).values_list("report_id", flat=True)
            }
            planning_report_ids = {report_id for report_id in marker_ids if report_id not in planning_finished_ids}
            ordered_ids = [
                *(report_id for report_id in marker_ids if report_id in planning_report_ids),
                *(report_id for report_id in marker_ids if report_id not in planning_report_ids),
            ]
            reports_by_id = {
                str(report.id): report
                for report in SignalReport.objects.filter(team=self.team, id__in=ordered_ids).exclude(
                    status=SignalReport.Status.DELETED
                )
            }
            reports = [reports_by_id[report_id] for report_id in ordered_ids if report_id in reports_by_id]

        page = self.paginate_queryset(reports)
        serializer_context = {**self.get_serializer_context(), "planning_report_ids": planning_report_ids}
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
