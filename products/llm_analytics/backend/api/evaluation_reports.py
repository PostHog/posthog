"""API endpoints for evaluation report configuration and report run history."""

import datetime as dt
from typing import Any

from django.conf import settings
from django.db.models import QuerySet

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.integration import Integration
from posthog.permissions import AccessControlPermission

from products.llm_analytics.backend.api.metrics import llma_track_latency
from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun
from products.workflows.backend.utils.rrule_utils import validate_rrule

logger = structlog.get_logger(__name__)


class EvaluationReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationReport
        fields = [
            "id",
            "evaluation",
            "frequency",
            "rrule",
            "starts_at",
            "timezone_name",
            "next_delivery_date",
            "delivery_targets",
            "max_sample_size",
            "enabled",
            "deleted",
            "last_delivered_at",
            "report_prompt_guidance",
            "trigger_threshold",
            "cooldown_minutes",
            "daily_run_cap",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "next_delivery_date", "last_delivered_at", "created_by", "created_at"]

    def validate_evaluation(self, value):
        # Prevent creating a report in team A that references team B's evaluation:
        # the FK queryset is unscoped, so a user with access to multiple teams could
        # otherwise cross tenant boundaries by passing a foreign evaluation id.
        team = self.context["get_team"]()
        if value.team_id != team.id:
            raise serializers.ValidationError("Evaluation does not belong to this team.")
        return value

    def validate_rrule(self, value: str) -> str:
        # Allow empty for count-triggered reports; cross-field validation enforces required-when-scheduled.
        if not value:
            return value
        try:
            validate_rrule(value)
        except ValueError as exc:
            logger.warning("Invalid rrule provided for evaluation report", exc_info=True)
            raise serializers.ValidationError("Invalid recurrence rule.") from exc
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # On create without an explicit frequency, fall through to the model default so
        # trigger_threshold / cooldown_minutes bounds still get enforced against every_n.
        frequency = attrs.get("frequency") or (
            self.instance.frequency if self.instance else EvaluationReport.Frequency.EVERY_N
        )
        if frequency == EvaluationReport.Frequency.EVERY_N:
            threshold = (
                attrs.get("trigger_threshold")
                if "trigger_threshold" in attrs
                else (self.instance.trigger_threshold if self.instance else None)
            )
            if threshold is None:
                raise serializers.ValidationError({"trigger_threshold": "Required when frequency is 'every_n'."})
            if threshold < EvaluationReport.TRIGGER_THRESHOLD_MIN:
                raise serializers.ValidationError(
                    {"trigger_threshold": f"Minimum is {EvaluationReport.TRIGGER_THRESHOLD_MIN}."}
                )
            if threshold > EvaluationReport.TRIGGER_THRESHOLD_MAX:
                raise serializers.ValidationError(
                    {"trigger_threshold": f"Maximum is {EvaluationReport.TRIGGER_THRESHOLD_MAX}."}
                )
            cooldown = (
                attrs.get("cooldown_minutes")
                if "cooldown_minutes" in attrs
                else (self.instance.cooldown_minutes if self.instance else EvaluationReport.COOLDOWN_MINUTES_DEFAULT)
            )
            if cooldown < EvaluationReport.COOLDOWN_MINUTES_MIN:
                raise serializers.ValidationError(
                    {"cooldown_minutes": f"Minimum is {EvaluationReport.COOLDOWN_MINUTES_MIN} minutes."}
                )
        elif frequency == EvaluationReport.Frequency.SCHEDULED:
            rrule_str = attrs.get("rrule") if "rrule" in attrs else (self.instance.rrule if self.instance else "")
            if not rrule_str:
                raise serializers.ValidationError({"rrule": "Required when frequency is 'scheduled'."})
            starts_at = (
                attrs.get("starts_at") if "starts_at" in attrs else (self.instance.starts_at if self.instance else None)
            )
            if starts_at is None:
                raise serializers.ValidationError({"starts_at": "Required when frequency is 'scheduled'."})
        return attrs

    def validate_delivery_targets(self, value: list) -> list:
        if not isinstance(value, list):
            raise serializers.ValidationError("Delivery targets must be a list.")
        team = self.context["get_team"]()
        slack_ids_to_verify: set[int] = set()
        for target in value:
            if not isinstance(target, dict):
                raise serializers.ValidationError("Each delivery target must be an object.")
            target_type = target.get("type")
            if target_type not in ("email", "slack"):
                raise serializers.ValidationError(f"Invalid delivery target type: {target_type}")
            if target_type == "email" and not target.get("value"):
                raise serializers.ValidationError("Email delivery target must include a 'value' field.")
            if target_type == "slack":
                integration_id = target.get("integration_id")
                channel = target.get("channel")
                if not integration_id or not channel:
                    raise serializers.ValidationError(
                        "Slack delivery target must include 'integration_id' and 'channel'."
                    )
                try:
                    slack_ids_to_verify.add(int(integration_id))
                except (TypeError, ValueError):
                    raise serializers.ValidationError("Slack integration_id must be an integer.")
        if slack_ids_to_verify:
            # Enforce tenant + kind boundary: only integrations that belong to this team AND
            # are Slack integrations are valid. Prevents cross-team reuse of integration ids
            # and rejects non-Slack kinds that happen to share an id.
            owned = set(
                Integration.objects.filter(
                    team_id=team.id, kind=Integration.IntegrationKind.SLACK, id__in=slack_ids_to_verify
                ).values_list("id", flat=True)
            )
            missing = slack_ids_to_verify - owned
            if missing:
                raise serializers.ValidationError(f"Slack integration(s) not found for this team: {sorted(missing)}.")
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


class EvaluationReportViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    """CRUD for evaluation report configurations + report run history."""

    scope_object = "llm_analytics"
    permission_classes = [AccessControlPermission]
    serializer_class = EvaluationReportSerializer
    queryset = EvaluationReport.objects.all()

    def safely_get_queryset(self, queryset: QuerySet[EvaluationReport]) -> QuerySet[EvaluationReport]:
        queryset = queryset.filter(team_id=self.team_id).order_by("-created_at")
        if self.action not in ("update", "partial_update"):
            queryset = queryset.filter(deleted=False)

        evaluation_id = self.request.query_params.get("evaluation")
        if evaluation_id:
            queryset = queryset.filter(evaluation_id=evaluation_id)

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

    def perform_create(self, serializer):
        instance = serializer.save()
        report_user_action(
            self.request.user,
            "llma evaluation report created",
            {
                "evaluation_report_id": str(instance.id),
                "evaluation_id": str(instance.evaluation_id),
                "frequency": instance.frequency,
                "has_rrule": bool(instance.rrule),
                "timezone_name": instance.timezone_name,
                "delivery_target_count": len(instance.delivery_targets or []),
                "delivery_target_types": sorted(
                    {t.get("type") for t in (instance.delivery_targets or []) if t.get("type")}
                ),
                "trigger_threshold": instance.trigger_threshold,
                "enabled": instance.enabled,
                "has_prompt_guidance": bool(instance.report_prompt_guidance),
            },
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer):
        tracked_fields = [
            "frequency",
            "rrule",
            "starts_at",
            "timezone_name",
            "delivery_targets",
            "max_sample_size",
            "enabled",
            "deleted",
            "report_prompt_guidance",
            "trigger_threshold",
            "cooldown_minutes",
            "daily_run_cap",
        ]
        is_deletion = serializer.validated_data.get("deleted") is True and not serializer.instance.deleted

        changed_fields: list[str] = []
        for field in tracked_fields:
            if (
                field in serializer.validated_data
                and getattr(serializer.instance, field) != serializer.validated_data[field]
            ):
                changed_fields.append(field)

        instance = serializer.save()

        if is_deletion:
            report_user_action(
                self.request.user,
                "llma evaluation report deleted",
                {
                    "evaluation_report_id": str(instance.id),
                    "evaluation_id": str(instance.evaluation_id),
                    "was_enabled": serializer.instance.enabled,
                },
                team=self.team,
                request=self.request,
            )
        elif changed_fields:
            event_properties: dict[str, Any] = {
                "evaluation_report_id": str(instance.id),
                "evaluation_id": str(instance.evaluation_id),
                "changed_fields": changed_fields,
            }
            if "enabled" in changed_fields:
                event_properties["enabled_new_value"] = instance.enabled
            report_user_action(
                self.request.user,
                "llma evaluation report updated",
                event_properties,
                team=self.team,
                request=self.request,
            )

    @extend_schema(responses=EvaluationReportRunSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="runs")
    @llma_track_latency("llma_evaluation_report_runs_list")
    def runs(self, request: Request, **kwargs) -> Response:
        """List report runs (history) for this report."""
        report = self.get_object()
        queryset = EvaluationReportRun.objects.filter(report=report).order_by("-created_at")
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = EvaluationReportRunSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = EvaluationReportRunSerializer(queryset, many=True)
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
        except ImportError:
            # The eval_reports Temporal module ships in a later PR in this stack; if we're on a
            # build where it hasn't landed yet, surface a 503 instead of a confusing 500.
            logger.exception("eval_reports Temporal module not available", report_id=str(report.id))
            return Response(
                {"error": "Report generation is not yet available on this deployment."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Stable workflow ID windowed to the minute: if a user smashes the button, Temporal
        # rejects the duplicate start (WorkflowAlreadyStarted) and we treat that as success.
        workflow_id = f"eval-report-manual-{report.id}-{dt.datetime.now(tz=dt.UTC).strftime('%Y%m%dT%H%M')}"
        try:
            client = sync_connect()
            # mypy can't resolve Temporal's start_workflow overloads for string-named workflows.
            async_to_sync(client.start_workflow)(  # type: ignore[misc]
                GENERATE_EVAL_REPORT_WORKFLOW_NAME,  # type: ignore[arg-type]
                GenerateAndDeliverEvalReportWorkflowInput(report_id=str(report.id), manual=True),  # type: ignore[arg-type]
                id=workflow_id,
                task_queue=settings.LLMA_TASK_QUEUE,
            )
        except Exception as exc:
            # Temporal's WorkflowAlreadyStarted is a subclass of RPCError / Exception depending
            # on SDK version; match by name to stay version-tolerant.
            if type(exc).__name__ == "WorkflowAlreadyStartedError":
                logger.info(
                    "Duplicate evaluation report generation request coalesced",
                    report_id=str(report.id),
                    workflow_id=workflow_id,
                )
                return Response(status=status.HTTP_202_ACCEPTED)
            logger.exception("Failed to trigger evaluation report generation", report_id=str(report.id))
            return Response(
                {"error": "Failed to trigger report generation"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(status=status.HTTP_202_ACCEPTED)
