from typing import cast

from django.db.models import Count

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission

from .models import SignalReport
from .serializers import SignalReportArtefactSerializer, SignalReportSerializer


@extend_schema(tags=["signal-reports"])
class SignalReportViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API for reading signal reports. Reports are auto-generated from video segment clustering.
    """

    serializer_class = SignalReportSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    scope_object = "task"  # Using task scope as signal_report doesn't have its own scope yet
    queryset = SignalReport.objects.all()
    posthog_feature_flag = {
        "tasks": [
            "list",
            "retrieve",
            "artefacts",
        ]
    }

    def safely_get_queryset(self, queryset):
        qs = (
            queryset.filter(
                team=self.team,
                status=SignalReport.Status.READY,
            )
            .annotate(artefact_count=Count("artefacts"))
            .order_by("-total_weight", "-updated_at")
        )

        return qs

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}

    @extend_schema(
        responses={
            200: OpenApiResponse(description="List of artefacts for the report"),
            404: OpenApiResponse(description="Report not found"),
        },
        summary="List report artefacts",
        description="Get list of artefacts for a signal report.",
    )
    @action(detail=True, methods=["get"], url_path="artefacts", required_scopes=["signal_report:read"])
    def artefacts(self, request, pk=None, **kwargs):
        report = cast(SignalReport, self.get_object())
        artefacts = report.artefacts.filter(type="video_segment").order_by("-created_at")
        serializer = SignalReportArtefactSerializer(artefacts, many=True)
        return Response(
            {
                "results": serializer.data,
                "count": len(serializer.data),
            }
        )
