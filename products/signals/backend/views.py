import uuid
from typing import cast

from django.conf import settings
from django.db.models import Count

from asgiref.sync import async_to_sync
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission

from products.signals.backend.api import emit_signal
from products.signals.backend.models import SignalReport
from products.signals.backend.serializers import SignalReportArtefactSerializer, SignalReportSerializer


class EmitSignalSerializer(serializers.Serializer):
    source_product = serializers.CharField(max_length=100)
    source_type = serializers.CharField(max_length=100)
    description = serializers.CharField()
    weight = serializers.FloatField(default=0.5, min_value=0.0, max_value=1.0)
    extra = serializers.DictField(required=False, default=dict)


# Simple debug view, to make testing out the flow easier. Disabled in production.
class SignalViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    @action(methods=["POST"], detail=False)
    def emit(self, request: Request, *args, **kwargs):
        if not settings.DEBUG:
            raise NotFound()

        serializer = EmitSignalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        async_to_sync(emit_signal)(
            team=self.team,
            source_product=data["source_product"],
            source_type=data["source_type"],
            source_id=str(uuid.uuid4()),
            description=data["description"],
            weight=data["weight"],
            extra=data["extra"],
        )

        return Response({"status": "ok"}, status=status.HTTP_202_ACCEPTED)


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
