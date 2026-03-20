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

# Maps (source_product, source_type) → (ExternalDataSourceType value, schema name)
_DATA_IMPORT_SOURCE_MAP: dict[tuple[str, str], tuple[str, str]] = {
    (SignalSourceConfig.SourceProduct.GITHUB, SignalSourceConfig.SourceType.ISSUE): ("Github", "issues"),
    (SignalSourceConfig.SourceProduct.LINEAR, SignalSourceConfig.SourceType.ISSUE): ("Linear", "issues"),
    (SignalSourceConfig.SourceProduct.ZENDESK, SignalSourceConfig.SourceType.TICKET): ("Zendesk", "tickets"),
}


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
        if obj.source_type == SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER:
            return self._get_clustering_status(obj)

        mapping = _DATA_IMPORT_SOURCE_MAP.get((obj.source_product, obj.source_type))
        if mapping is None:
            return None
        ext_source_type, schema_name = mapping
        return self._get_data_import_status(obj.team_id, ext_source_type, schema_name)

    def _get_clustering_status(self, obj: SignalSourceConfig) -> str | None:
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

    def _get_data_import_status(self, team_id: int, ext_source_type: str, schema_name: str) -> str | None:
        from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

        schema = (
            ExternalDataSchema.objects.filter(
                team_id=team_id,
                source__source_type=ext_source_type,
                name=schema_name,
            )
            .exclude(source__deleted=True)
            .first()
        )
        if schema is None:
            return None
        if schema.status == ExternalDataSchema.Status.RUNNING:
            return "running"
        if schema.status == ExternalDataSchema.Status.COMPLETED:
            return "completed"
        if schema.status in (
            ExternalDataSchema.Status.FAILED,
            ExternalDataSchema.Status.BILLING_LIMIT_REACHED,
            ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW,
        ):
            return "failed"
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
    priority = serializers.SerializerMethodField(
        help_text="P0–P4 from the latest actionability judgment artefact (when present).",
    )

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
            "priority",
        ]
        read_only_fields = fields

    def get_priority(self, obj: SignalReport) -> str | None:
        prefetched = getattr(obj, "prefetched_actionability_artefacts", None)
        if prefetched is not None:
            art = prefetched[0] if prefetched else None
        else:
            art = (
                obj.artefacts.filter(type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT)
                .order_by("-created_at")
                .first()
            )
        if art is None:
            return None
        try:
            data = json.loads(art.content)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        p = data.get("priority")
        return p if isinstance(p, str) else None


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
