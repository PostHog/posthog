import json
import logging

from asgiref.sync import async_to_sync
from rest_framework import serializers

from posthog.models import User
from posthog.temporal.common.client import sync_connect

from .models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalReportTask,
    SignalSourceConfig,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from .report_generation.resolve_reviewers import enrich_reviewer_dicts_with_org_members

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
            return self._get_session_analysis_status(obj.team_id)

        mapping = _DATA_IMPORT_SOURCE_MAP.get((obj.source_product, obj.source_type))
        if mapping is None:
            return None
        ext_source_type, schema_name = mapping
        return self._get_data_import_status(obj.team_id, ext_source_type, schema_name)

    def _get_session_analysis_status(self, team_id: int) -> str | None:
        """ "running" iff any `summarize-session` workflow for this team is currently executing."""
        query = f'PostHogTeamId = {team_id} AND WorkflowType = "summarize-session" AND ExecutionStatus = "Running"'

        try:
            temporal = sync_connect()

            async def has_running() -> bool:
                async for _ in temporal.list_workflows(query=query, page_size=1):
                    return True
                return False

            if async_to_sync(has_running)():
                return "running"
        except Exception as e:
            logger.warning("Failed to list session summarization workflows: %s", e)
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
        source_type = attrs.get("source_type", getattr(self.instance, "source_type", None))
        enabled = attrs.get("enabled", getattr(self.instance, "enabled", False))
        config = attrs.get("config", {})
        if source_product == SignalSourceConfig.SourceProduct.SESSION_REPLAY and config:
            recording_filters = config.get("recording_filters")
            if recording_filters is not None and not isinstance(recording_filters, dict):
                raise serializers.ValidationError({"config": "recording_filters must be a JSON object"})
        if enabled and source_type == SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER:
            get_team = self.context.get("get_team")
            team = get_team() if get_team else None
            if team is not None and not team.organization.is_ai_data_processing_approved:
                raise serializers.ValidationError(
                    {
                        "enabled": "AI data processing must be approved at the organization level to enable session analysis."
                    }
                )
        return attrs


class SignalTeamConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SignalTeamConfig
        fields = ["id", "default_autostart_priority", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class _UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "uuid", "first_name", "last_name", "email"]
        read_only_fields = fields


class SignalUserAutonomyConfigSerializer(serializers.ModelSerializer):
    user = _UserSerializer(read_only=True)

    class Meta:
        model = SignalUserAutonomyConfig
        fields = ["id", "user", "autostart_priority", "created_at", "updated_at"]
        read_only_fields = ["id", "user", "created_at", "updated_at"]


class SignalReportTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = SignalReportTask
        fields = ["id", "relationship", "task_id", "created_at"]
        read_only_fields = fields


class SignalUserAutonomyConfigCreateSerializer(serializers.Serializer):
    autostart_priority = serializers.ChoiceField(choices=AutonomyPriority.choices, required=False, allow_null=True)


class SignalReportSerializer(serializers.ModelSerializer):
    artefact_count = serializers.IntegerField(read_only=True)
    priority = serializers.SerializerMethodField(
        help_text="P0–P4 from the latest priority judgment artefact (when present).",
    )
    actionability = serializers.SerializerMethodField(
        help_text="Actionability choice from the latest actionability judgment artefact (when present).",
    )
    already_addressed = serializers.SerializerMethodField(
        help_text="Whether the issue appears already fixed, from the actionability judgment artefact.",
    )
    is_suggested_reviewer = serializers.BooleanField(read_only=True, default=False)
    source_products = serializers.SerializerMethodField(
        help_text="Distinct source products contributing signals to this report (from ClickHouse).",
    )
    implementation_pr_url = serializers.SerializerMethodField(
        help_text="PR URL from the latest implementation task run, if available.",
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
            "actionability",
            "already_addressed",
            "is_suggested_reviewer",
            "source_products",
            "implementation_pr_url",
        ]
        read_only_fields = fields

    def _get_actionability_artefact_data(self, obj: SignalReport) -> dict | None:
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
        return data if isinstance(data, dict) else None

    def get_priority(self, obj: SignalReport) -> str | None:
        prefetched = getattr(obj, "prefetched_priority_artefacts", None)
        if prefetched is not None:
            art = prefetched[0] if prefetched else None
        else:
            art = (
                obj.artefacts.filter(type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT)
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

    def get_actionability(self, obj: SignalReport) -> str | None:
        data = self._get_actionability_artefact_data(obj)
        if data is None:
            return None
        value = data.get("actionability")
        return value if isinstance(value, str) else None

    def get_already_addressed(self, obj: SignalReport) -> bool | None:
        data = self._get_actionability_artefact_data(obj)
        if data is None:
            return None
        value = data.get("already_addressed")
        return value if isinstance(value, bool) else None

    def get_source_products(self, obj: SignalReport) -> list[str]:
        source_products_map: dict[str, list[str]] | None = self.context.get("source_products_map")
        if source_products_map is not None:
            return source_products_map.get(str(obj.id), [])
        return []

    def get_implementation_pr_url(self, obj: SignalReport) -> str | None:
        implementation_pr_url_map: dict[str, str] | None = self.context.get("implementation_pr_url_map")
        if implementation_pr_url_map is not None:
            return implementation_pr_url_map.get(str(obj.id))
        value = getattr(obj, "implementation_pr_url", None)
        return value if isinstance(value, str) else None


class SignalReportArtefactSerializer(serializers.ModelSerializer):
    content = serializers.SerializerMethodField()

    class Meta:
        model = SignalReportArtefact
        fields = ["id", "type", "content", "created_at"]
        read_only_fields = fields

    def get_content(self, obj: SignalReportArtefact) -> dict | list:
        try:
            parsed = json.loads(obj.content)
        except (json.JSONDecodeError, ValueError):
            return {}

        # Enrich suggested_reviewers with fresh PostHog user info at read time
        if obj.type == SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS and isinstance(parsed, list):
            return enrich_reviewer_dicts_with_org_members(obj.team_id, parsed)

        return parsed
