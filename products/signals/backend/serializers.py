import json
import logging

from asgiref.sync import async_to_sync
from rest_framework import serializers
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.ai.video_segment_clustering.constants import clustering_workflow_id
from posthog.temporal.common.client import sync_connect

from .models import SignalReport, SignalReportArtefact, SignalSourceConfig

logger = logging.getLogger(__name__)


class SignalSourceConfigSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()

    class Meta:
        model = SignalSourceConfig
        fields = [
            "id",
            "source_product",
            "source_type",
            "enabled",
            "config",
            "created_at",
            "updated_at",
            "status",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "status"]

    def get_status(self, obj: SignalSourceConfig) -> str | None:
        if obj.source_type != SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER:
            return None
        workflow_id = clustering_workflow_id(obj.team_id, obj.id)
        try:
            client = sync_connect()
            handle = client.get_workflow_handle(workflow_id)
            desc = async_to_sync(handle.describe)()
            status = desc.status
            if status == WorkflowExecutionStatus.RUNNING:
                return "running"
            if status == WorkflowExecutionStatus.COMPLETED:
                return "completed"
            if status in (
                WorkflowExecutionStatus.FAILED,
                WorkflowExecutionStatus.TERMINATED,
                WorkflowExecutionStatus.CANCELED,
                WorkflowExecutionStatus.TIMED_OUT,
            ):
                return "failed"
            return None
        except RPCError as e:
            if e.status == RPCStatusCode.NOT_FOUND:
                return None
            logger.warning("Failed to fetch clustering workflow status: %s", e)
            return None

    def validate(self, attrs: dict) -> dict:
        source_product = attrs.get("source_product", getattr(self.instance, "source_product", None))
        config = attrs.get("config", {})
        if source_product == SignalSourceConfig.SourceProduct.SESSION_REPLAY and config:
            recording_filters = config.get("recording_filters")
            if recording_filters is not None and not isinstance(recording_filters, dict):
                raise serializers.ValidationError({"config": "recording_filters must be a JSON object"})
        return attrs


class SignalReportSerializer(serializers.ModelSerializer):
    artefact_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = SignalReport
        fields = [
            "id",
            "title",
            "summary",
            "status",
            "total_weight",  # Used for priority scoring
            "signal_count",  # Used for occurrence count
            "signals_at_run",  # Snooze threshold: re-promote when signal_count >= this value
            "created_at",
            "updated_at",
            "artefact_count",
        ]
        read_only_fields = fields


class SignalReportArtefactSerializer(serializers.ModelSerializer):
    content = serializers.SerializerMethodField()

    class Meta:
        model = SignalReportArtefact
        fields = ["id", "type", "content", "created_at"]
        read_only_fields = fields

    def get_content(self, obj: SignalReportArtefact) -> dict:
        try:
            return json.loads(obj.content)
        except (json.JSONDecodeError, ValueError):
            return {}
