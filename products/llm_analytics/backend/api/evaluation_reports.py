"""API endpoints for evaluation report configuration and report run history."""

import datetime as dt

from django.db.models import QuerySet

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import AccessControlPermission

from products.llm_analytics.backend.api.metrics import llma_track_latency
from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun

logger = structlog.get_logger(__name__)


class EvaluationReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationReport
        fields = [
            "id",
            "evaluation",
            "frequency",
            "byweekday",
            "start_date",
            "next_delivery_date",
            "delivery_targets",
            "max_sample_size",
            "enabled",
            "deleted",
            "last_delivered_at",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "next_delivery_date", "last_delivered_at", "created_by", "created_at"]

    def validate_delivery_targets(self, value: list) -> list:
        if not isinstance(value, list) or len(value) == 0:
            raise serializers.ValidationError("At least one delivery target is required.")
        for target in value:
            if not isinstance(target, dict):
                raise serializers.ValidationError("Each delivery target must be an object.")
            target_type = target.get("type")
            if target_type not in ("email", "slack"):
                raise serializers.ValidationError(f"Invalid delivery target type: {target_type}")
            if target_type == "email" and not target.get("value"):
                raise serializers.ValidationError("Email delivery target must include a 'value' field.")
            if target_type == "slack" and (not target.get("integration_id") or not target.get("channel")):
                raise serializers.ValidationError("Slack delivery target must include 'integration_id' and 'channel'.")
        return value

    def create(self, validated_data):
        request = self.context["request"]
        team = self.context["get_team"]()
        validated_data["team"] = team
        validated_data["created_by"] = request.user
        return super().create(validated_data)


class EvaluationReportRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationReportRun
        fields = [
            "id",
            "report",
            "content",
            "metadata",
            "period_start",
            "period_end",
            "delivery_status",
            "delivery_errors",
            "created_at",
        ]
        read_only_fields = fields


class EvaluationReportViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """CRUD for evaluation report configurations + report run history."""

    scope_object = "llm_analytics"
    permission_classes = [AccessControlPermission]
    serializer_class = EvaluationReportSerializer
    queryset = EvaluationReport.objects.all()

    def safely_get_queryset(self, queryset: QuerySet[EvaluationReport]) -> QuerySet[EvaluationReport]:
        queryset = queryset.filter(team_id=self.team_id).order_by("-created_at")
        if self.action not in ("update", "partial_update"):
            queryset = queryset.filter(deleted=False)
        return queryset

    @llma_track_latency("llma_evaluation_reports_list")
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_evaluation_reports_create")
    def create(self, request: Request, *args, **kwargs) -> Response:
        return super().create(request, *args, **kwargs)

    @llma_track_latency("llma_evaluation_reports_retrieve")
    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        return super().retrieve(request, *args, **kwargs)

    @llma_track_latency("llma_evaluation_reports_update")
    def update(self, request: Request, *args, **kwargs) -> Response:
        return super().update(request, *args, **kwargs)

    @llma_track_latency("llma_evaluation_reports_partial_update")
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        return super().partial_update(request, *args, **kwargs)

    def perform_destroy(self, instance):
        instance.deleted = True
        instance.save(update_fields=["deleted"])

    @action(detail=True, methods=["get"], url_path="runs")
    @llma_track_latency("llma_evaluation_report_runs_list")
    def runs(self, request: Request, **kwargs) -> Response:
        """List report runs (history) for this report."""
        report = self.get_object()
        runs = EvaluationReportRun.objects.filter(report=report).order_by("-created_at")[:50]
        serializer = EvaluationReportRunSerializer(runs, many=True)
        return Response(serializer.data)

    @extend_schema(request=None, responses={202: None})
    @action(detail=True, methods=["post"], url_path="generate")
    @llma_track_latency("llma_evaluation_report_generate")
    def generate(self, request: Request, **kwargs) -> Response:
        """Trigger immediate report generation."""
        report = self.get_object()

        try:
            from posthog.temporal.common.client import sync_connect
            from posthog.temporal.llm_analytics.eval_reports.constants import GENERATE_EVAL_REPORT_WORKFLOW_NAME
            from posthog.temporal.llm_analytics.eval_reports.types import GenerateAndDeliverEvalReportWorkflowInput

            temporal_client = sync_connect()
            temporal_client.start_workflow(
                GENERATE_EVAL_REPORT_WORKFLOW_NAME,
                GenerateAndDeliverEvalReportWorkflowInput(report_id=str(report.id)),
                id=f"eval-report-manual-{report.id}-{dt.datetime.now(tz=dt.UTC).timestamp():.0f}",
                task_queue="general-purpose",
            )
        except Exception:
            logger.exception("Failed to trigger evaluation report generation", report_id=str(report.id))
            return Response(
                {"error": "Failed to trigger report generation"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(status=status.HTTP_202_ACCEPTED)
