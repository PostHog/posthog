import json
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet

import structlog
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.permissions import AccessControlPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.temporal.llm_analytics.message_utils import extract_text_from_messages
from posthog.temporal.llm_analytics.run_evaluation import extract_event_io, run_hog_eval

from ..models.clustering_job import ClusteringJob
from ..models.evaluation_config import EvaluationConfig
from ..models.evaluation_configs import validate_evaluation_configs
from ..models.evaluation_reports import EvaluationReport
from ..models.evaluations import Evaluation
from ..models.model_configuration import LLMModelConfiguration
from ..models.provider_keys import LLMProvider, LLMProviderKey
from .metrics import llma_track_latency

logger = structlog.get_logger(__name__)


@extend_schema_field(
    {
        "oneOf": [
            {
                "type": "object",
                "title": "LLM judge config",
                "required": ["prompt"],
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Evaluation criteria for the LLM judge. Describe what makes a good vs bad response.",
                        "minLength": 1,
                    }
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "title": "Hog config",
                "required": ["source"],
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Hog source code. Must return true (pass), false (fail), or null for N/A.",
                        "minLength": 1,
                    }
                },
                "additionalProperties": False,
            },
        ]
    }
)
class _EvaluationConfigField(serializers.JSONField):
    pass


@extend_schema_field(
    {
        "type": "object",
        "properties": {
            "allows_na": {
                "type": "boolean",
                "description": "Whether the evaluation can return N/A for non-applicable generations.",
                "default": False,
            }
        },
        "additionalProperties": False,
    }
)
class _OutputConfigField(serializers.JSONField):
    pass


class ModelConfigurationSerializer(serializers.Serializer):
    """Nested serializer for model configuration."""

    provider = serializers.ChoiceField(choices=LLMProvider.choices)
    model = serializers.CharField(max_length=100)
    provider_key_id = serializers.UUIDField(required=False, allow_null=True)
    provider_key_name = serializers.SerializerMethodField(read_only=True)

    def get_provider_key_name(self, obj: LLMModelConfiguration) -> str | None:
        if obj.provider_key:
            return obj.provider_key.name
        return None

    def to_representation(self, instance: LLMModelConfiguration) -> dict[str, Any]:
        return {
            "provider": instance.provider,
            "model": instance.model,
            "provider_key_id": str(instance.provider_key_id) if instance.provider_key_id else None,
            "provider_key_name": instance.provider_key.name if instance.provider_key else None,
        }


class EvaluationSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    model_configuration = ModelConfigurationSerializer(required=False, allow_null=True)
    evaluation_config = _EvaluationConfigField(
        required=False,
        help_text="Configuration dict. For 'llm_judge': {prompt}. For 'hog': {source}.",
    )
    output_config = _OutputConfigField(
        required=False,
        help_text="Output config. For 'boolean' output_type: {allows_na} to permit N/A results.",
    )

    class Meta:
        model = Evaluation
        fields = [
            "id",
            "name",
            "description",
            "enabled",
            "status",
            "status_reason",
            "evaluation_type",
            "evaluation_config",
            "output_type",
            "output_config",
            "conditions",
            "model_configuration",
            "created_at",
            "updated_at",
            "created_by",
            "deleted",
        ]
        # status / status_reason are server-managed (coerced from enabled on user writes, set directly by
        # system transitions). Clients toggle `enabled`; the model's save() keeps the trio consistent.
        read_only_fields = ["id", "status", "status_reason", "created_at", "updated_at", "created_by"]
        extra_kwargs = {
            "name": {"help_text": "Name of the evaluation."},
            "description": {"help_text": "Optional description of what this evaluation checks."},
            "enabled": {"help_text": "Whether the evaluation runs automatically on new $ai_generation events."},
            "evaluation_type": {
                "help_text": "'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code."
            },
            "output_type": {"help_text": "Output format. Currently only 'boolean' is supported."},
            "conditions": {
                "help_text": "Optional trigger conditions to filter which events are evaluated. OR between condition sets, AND within each."
            },
            "deleted": {"help_text": "Set to true to soft-delete the evaluation."},
        }

    def validate(self, data):
        if "evaluation_config" in data and "output_config" in data:
            evaluation_type = data.get("evaluation_type")
            output_type = data.get("output_type")
            if evaluation_type and output_type:
                try:
                    data["evaluation_config"], data["output_config"] = validate_evaluation_configs(
                        evaluation_type, output_type, data["evaluation_config"], data["output_config"]
                    )
                except ValueError as e:
                    raise serializers.ValidationError({"config": str(e)})

        # Guard re-enable transitions: if the eval is currently disabled and the caller is flipping
        # `enabled=True`, make sure whatever caused the disabled state has actually been resolved.
        # Without this check, a caller (UI, API, MCP, agent) can flip enabled=True, see a 200, and
        # then watch the next Temporal run silently re-disable the eval for the same reason.
        if data.get("enabled") and self.instance and not self.instance.enabled:
            self._validate_re_enable(data)

        return data

    def _validate_re_enable(self, data: dict) -> None:
        has_byok = self._has_byok_key(data)
        status_reason = getattr(self.instance, "status_reason", None)

        # Trial limit: can only re-enable if they've attached a BYOK key (which bypasses trial quota).
        if status_reason == "trial_limit_reached" or not status_reason:
            team = self.context["get_team"]()
            config = EvaluationConfig.objects.filter(team=team).first()
            if config and config.trial_limit_reached and not has_byok:
                raise serializers.ValidationError(
                    {"enabled": "Trial evaluation limit reached. Add a provider API key to re-enable this evaluation."}
                )

        # Model-not-allowed: the eval's current model must now be on the trial allowlist, or they
        # must have attached a BYOK key (BYOK bypasses the allowlist entirely).
        if status_reason == "model_not_allowed" and not has_byok:
            from products.llm_analytics.backend.llm import TRIAL_MODEL_IDS

            model_config_data = data.get("model_configuration")
            if model_config_data is not None:
                model = model_config_data.get("model")
            elif self.instance and self.instance.model_configuration:
                model = self.instance.model_configuration.model
            else:
                model = None
            if model and model not in TRIAL_MODEL_IDS:
                raise serializers.ValidationError(
                    {
                        "enabled": (
                            f"Model '{model}' is not available on the trial plan. "
                            "Either choose a supported trial model or add a provider API key."
                        )
                    }
                )

        # Provider key deleted: the eval must now point at a real provider key.
        if status_reason == "provider_key_deleted" and not has_byok:
            raise serializers.ValidationError(
                {
                    "enabled": "The provider API key for this evaluation was deleted. Attach a provider API key before re-enabling."
                }
            )

    def _has_byok_key(self, data: dict) -> bool:
        """Check if the evaluation will have a BYOK key after this update."""
        model_config_data = data.get("model_configuration")
        if model_config_data is not None:
            return bool(model_config_data.get("provider_key_id"))
        if self.instance and self.instance.model_configuration:
            return self.instance.model_configuration.provider_key_id is not None
        return False

    def _create_or_update_model_configuration(
        self, model_config_data: dict[str, Any] | None, team_id: int
    ) -> LLMModelConfiguration | None:
        """Create or update an LLMModelConfiguration from serializer data."""
        if model_config_data is None:
            return None

        provider_key = None
        provider_key_id = model_config_data.get("provider_key_id")
        if provider_key_id:
            try:
                provider_key = LLMProviderKey.objects.get(id=provider_key_id, team_id=team_id)
            except LLMProviderKey.DoesNotExist:
                raise serializers.ValidationError(
                    {"model_configuration": {"provider_key_id": "Provider key not found"}}
                )

        model_config = LLMModelConfiguration(
            team_id=team_id,
            provider=model_config_data["provider"],
            model=model_config_data["model"],
            provider_key=provider_key,
        )
        model_config.full_clean()
        model_config.save()
        return model_config

    def create(self, validated_data):
        request = self.context["request"]
        team = self.context["get_team"]()
        validated_data["team"] = team
        validated_data["created_by"] = request.user

        model_config_data = validated_data.pop("model_configuration", None)
        if model_config_data:
            validated_data["model_configuration"] = self._create_or_update_model_configuration(
                model_config_data, team.id
            )

        return super().create(validated_data)

    def update(self, instance, validated_data):
        model_config_data = validated_data.pop("model_configuration", None)

        if model_config_data is not None:
            # Delete old model configuration if it exists
            if instance.model_configuration:
                old_config = instance.model_configuration
                instance.model_configuration = None
                old_config.delete()

            validated_data["model_configuration"] = self._create_or_update_model_configuration(
                model_config_data, instance.team_id
            )

        return super().update(instance, validated_data)


class EvaluationFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method="filter_search", help_text="Search in name or description")
    enabled = django_filters.BooleanFilter(help_text="Filter by enabled status")
    order_by = django_filters.OrderingFilter(
        fields=(
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
            ("name", "name"),
        ),
        field_labels={
            "created_at": "Created At",
            "updated_at": "Updated At",
            "name": "Name",
        },
    )

    class Meta:
        model = Evaluation
        fields = {
            "id": ["in"],
            "enabled": ["exact"],
        }

    def filter_search(self, queryset, name, value):
        if value:
            return queryset.filter(Q(name__icontains=value) | Q(description__icontains=value))
        return queryset


class EvaluationListSerializer(EvaluationSerializer):
    """Slim list serializer for MCP callers — drops heavy per-item fields to save tokens.

    Gated on the ``X-PostHog-Client: mcp`` header so the web UI keeps the full shape
    it relies on (see `EvaluationViewSet.get_serializer_class`).
    """

    class Meta(EvaluationSerializer.Meta):
        fields = [
            f
            for f in EvaluationSerializer.Meta.fields
            if f
            not in (
                "evaluation_config",
                "output_config",
                "conditions",
                "model_configuration",
                "created_by",
                "deleted",
            )
        ]
        read_only_fields = [f for f in EvaluationSerializer.Meta.read_only_fields if f != "created_by"]


class CreateEvaluationFromClusterRequestSerializer(serializers.Serializer):
    run_id = serializers.CharField(required=True, min_length=1)
    cluster_id = serializers.IntegerField(required=True)
    evaluation_goal = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    evaluation_prompt = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate(self, attrs):
        evaluation_prompt = attrs.get("evaluation_prompt")
        if evaluation_prompt is not None and not evaluation_prompt.strip():
            raise serializers.ValidationError({"evaluation_prompt": "Prompt cannot be empty."})
        return attrs


def _cluster_run_timestamp_bounds(run_id: str) -> tuple[str, str]:
    """Return UTC day bounds for a clustering run id.

    Run IDs are emitted as `<team_id>_<level>_<YYYYMMDD>_<HHMMSS>...`. Matching the frontend's
    day-bounded query keeps the lookup cheap while still tolerating older or malformed IDs.
    """
    parts = run_id.split("_")
    clickhouse_format = "%Y-%m-%d %H:%M:%S.%f"
    if len(parts) >= 4:
        try:
            parsed = datetime.strptime(f"{parts[2]}_{parts[3]}", "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
            start = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1) - timedelta(microseconds=1)
            return start.strftime(clickhouse_format), end.strftime(clickhouse_format)
        except ValueError:
            pass

    end = datetime.now(tz=UTC)
    start = end - timedelta(days=7)
    return start.strftime(clickhouse_format), end.strftime(clickhouse_format)


def _parse_cluster_payload(raw_clusters: Any) -> list[dict[str, Any]]:
    if isinstance(raw_clusters, str):
        try:
            raw_clusters = json.loads(raw_clusters or "[]")
        except json.JSONDecodeError:
            return []

    if not isinstance(raw_clusters, list):
        return []

    return [cluster for cluster in raw_clusters if isinstance(cluster, dict)]


def _fetch_cluster_run_for_evaluation(team, run_id: str) -> dict[str, Any] | None:
    from posthog.hogql import ast
    from posthog.hogql.parser import parse_select
    from posthog.hogql.query import execute_hogql_query

    from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

    day_start, day_end = _cluster_run_timestamp_bounds(run_id)
    query = parse_select(
        """
        SELECT
            JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
            JSONExtractString(properties, '$ai_clustering_level') as level,
            JSONExtractString(properties, '$ai_clustering_job_id') as job_id,
            JSONExtractString(properties, '$ai_clustering_job_name') as job_name,
            JSONExtractString(properties, '$ai_window_start') as window_start,
            JSONExtractString(properties, '$ai_window_end') as window_end,
            JSONExtractRaw(properties, '$ai_clusters') as clusters
        FROM events
        WHERE event IN ('$ai_trace_clusters', '$ai_generation_clusters', '$ai_evaluation_clusters')
            AND timestamp >= {day_start}
            AND timestamp <= {day_end}
            AND JSONExtractString(properties, '$ai_clustering_run_id') = {run_id}
        ORDER BY timestamp DESC
        LIMIT 1
        """
    )

    tag_queries(product=Product.LLM_ANALYTICS, feature=Feature.QUERY)
    response = execute_hogql_query(
        query=query,
        placeholders={
            "day_start": ast.Constant(value=day_start),
            "day_end": ast.Constant(value=day_end),
            "run_id": ast.Constant(value=run_id),
        },
        team=team,
        limit_context=None,
    )

    if not response.results:
        return None

    row = response.results[0]
    return {
        "run_id": row[0],
        "level": row[1],
        "job_id": row[2] or None,
        "job_name": row[3] or None,
        "window_start": row[4],
        "window_end": row[5],
        "clusters": _parse_cluster_payload(row[6]),
    }


def _find_cluster_for_evaluation(cluster_run: dict[str, Any], cluster_id: int) -> dict[str, Any] | None:
    for cluster in cluster_run.get("clusters") or []:
        if cluster.get("cluster_id") == cluster_id:
            return cluster
    return None


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    if max_length <= 3:
        return value[:max_length]
    return value[: max_length - 3].rstrip() + "..."


def _cluster_title(cluster: dict[str, Any], cluster_id: int) -> str:
    title = cluster.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return f"Cluster {cluster_id}"


def _cluster_summary(cluster: dict[str, Any]) -> str:
    description = cluster.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return "No cluster summary was available."


def _default_cluster_evaluation_goal(cluster: dict[str, Any], cluster_id: int) -> str:
    return (
        f'Detect whether the generation or its trace context shows the "{_cluster_title(cluster, cluster_id)}" pattern.'
    )


def _build_cluster_evaluation_prompt(
    cluster: dict[str, Any], cluster_id: int, evaluation_goal: str | None = None
) -> str:
    goal = evaluation_goal.strip() if evaluation_goal else _default_cluster_evaluation_goal(cluster, cluster_id)
    return f"""You are judging whether an LLM generation shows a reusable pattern from an LLM Analytics cluster.

Evaluation goal:
{goal}

Cluster title:
{_cluster_title(cluster, cluster_id)}

Cluster summary:
{_cluster_summary(cluster)}

Use the generation input, output, metadata, and any available trace context to decide.

Return true when the generation clearly shows the evaluation goal.
Return false when the generation clearly does not show the evaluation goal.
Return N/A when there is not enough information to decide.

Focus on the evaluation goal, cluster title, and cluster summary only. Ignore source run counts, costs, latencies, token counts, and other metrics."""


def _build_cluster_evaluation_description(
    cluster_run: dict[str, Any], cluster: dict[str, Any], cluster_id: int, evaluation_goal: str | None = None
) -> str:
    title = _cluster_title(cluster, cluster_id)
    parts = [
        f'Disabled draft evaluation generated from LLM Analytics cluster "{title}".',
        f"Source run: {cluster_run.get('run_id')}",
        f"Cluster id: {cluster_id}",
    ]

    if cluster_run.get("window_start") and cluster_run.get("window_end"):
        parts.append(f"Window: {cluster_run['window_start']} to {cluster_run['window_end']}")

    if evaluation_goal:
        parts.append(f"Evaluation goal:\n{evaluation_goal}")

    summary = _cluster_summary(cluster)
    if summary:
        parts.append(f"Cluster summary:\n{summary}")

    return _truncate("\n\n".join(parts), 500)


def _clustering_job_filters(team_id: int, job_id: str | None) -> list[dict[str, Any]]:
    if not job_id:
        return []

    try:
        job = ClusteringJob.objects.get(id=job_id, team_id=team_id)
    except (ClusteringJob.DoesNotExist, ValidationError, ValueError):
        return []

    return job.event_filters if isinstance(job.event_filters, list) else []


class TestHogRequestSerializer(serializers.Serializer):
    source = serializers.CharField(
        required=True,
        min_length=1,
        help_text="Hog source code to test. Must return a boolean (true = pass, false = fail) or null for N/A.",
    )  # type: ignore[assignment]
    sample_count = serializers.IntegerField(
        required=False,
        default=5,
        min_value=1,
        max_value=10,
        help_text="Number of recent $ai_generation events to test against (1–10, default 5).",
    )
    allows_na = serializers.BooleanField(
        required=False, default=False, help_text="Whether the evaluation can return N/A for non-applicable generations."
    )
    conditions = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text="Optional trigger conditions to filter which events are sampled.",
    )


class TestHogResultItemSerializer(serializers.Serializer):
    event_uuid = serializers.CharField(help_text="UUID of the $ai_generation event.")
    trace_id = serializers.CharField(allow_null=True, required=False, help_text="Trace ID if available.")
    input_preview = serializers.CharField(help_text="First 200 chars of the generation input.")
    output_preview = serializers.CharField(help_text="First 200 chars of the generation output.")
    result = serializers.BooleanField(allow_null=True, help_text="True = pass, False = fail, null = N/A or error.")
    reasoning = serializers.CharField(allow_null=True, help_text="Hog evaluation reasoning string, if any.")
    error = serializers.CharField(allow_null=True, help_text="Error message if the Hog code raised an exception.")


class TestHogResponseSerializer(serializers.Serializer):
    results = TestHogResultItemSerializer(many=True)
    message = serializers.CharField(
        required=False, help_text="Optional message, e.g. when no recent events were found."
    )


@extend_schema(tags=["llm_analytics"])
class EvaluationViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "evaluation"
    permission_classes = [IsAuthenticated, AccessControlPermission]
    serializer_class = EvaluationSerializer
    queryset = Evaluation.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = EvaluationFilter

    @staticmethod
    def _is_mcp_request(request: Request) -> bool:
        return request.META.get("HTTP_X_POSTHOG_CLIENT") == "mcp"

    def _wants_slim_list(self) -> bool:
        return self.action == "list" and self._is_mcp_request(self.request)

    def get_serializer_class(self):
        if self._wants_slim_list():
            return EvaluationListSerializer
        return super().get_serializer_class()

    def safely_get_queryset(self, queryset: QuerySet[Evaluation]) -> QuerySet[Evaluation]:
        queryset = queryset.filter(team_id=self.team_id).order_by("-created_at")
        if not self._wants_slim_list():
            queryset = queryset.select_related("created_by", "model_configuration", "model_configuration__provider_key")
        if not self.action.endswith("update"):
            queryset = queryset.filter(deleted=False)
        return queryset

    @staticmethod
    def _get_config_length(instance) -> int:
        """Get the relevant config content length for tracking."""
        if instance.evaluation_config and isinstance(instance.evaluation_config, dict):
            if instance.evaluation_type == "hog":
                source = instance.evaluation_config.get("source", "")
                return len(source) if isinstance(source, str) else 0
            else:
                prompt = instance.evaluation_config.get("prompt", "")
                return len(prompt) if isinstance(prompt, str) else 0
        return 0

    def perform_create(self, serializer):
        with transaction.atomic():
            instance = serializer.save()

            # Auto-create a default report config so reports are generated from the start.
            # Defaults to count-triggered (frequency=every_n), so rrule/starts_at stay empty
            # and users add email/Slack delivery targets later if they want notifications.
            EvaluationReport.objects.create(
                team=self.team,
                evaluation=instance,
            )

        # Calculate properties for tracking
        conditions = instance.conditions or []
        condition_count = len(conditions)
        has_rollout_percentage = any(condition.get("rollout_percentage", 100) < 100 for condition in conditions)

        config_length = self._get_config_length(instance)

        # Track evaluation created
        report_user_action(
            self.request.user,
            "llma evaluation created",
            {
                "evaluation_id": str(instance.id),
                "evaluation_name": instance.name,
                "evaluation_type": instance.evaluation_type,
                "output_type": instance.output_type,
                "has_description": bool(instance.description),
                "enabled": instance.enabled,
                "condition_count": condition_count,
                "has_rollout_percentage": has_rollout_percentage,
                "config_length": config_length,
            },
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer):
        # Check if this is a deletion (soft delete)
        is_deletion = serializer.validated_data.get("deleted") is True and not serializer.instance.deleted

        # Capture old enabled state before save (for deletion tracking)
        old_enabled_value = serializer.instance.enabled

        # Track changes before update
        changed_fields: list[str] = []
        enabled_changed = False
        enabled_new_value = None
        condition_count_changed = False
        condition_count_new = 0
        config_content_changed = False

        for field in [
            "name",
            "description",
            "enabled",
            "evaluation_type",
            "output_type",
            "evaluation_config",
            "output_config",
            "conditions",
            "deleted",
        ]:
            if field in serializer.validated_data:
                old_value = getattr(serializer.instance, field)
                new_value = serializer.validated_data[field]
                if old_value != new_value:
                    changed_fields.append(field)

                    if field == "enabled":
                        enabled_changed = True
                        enabled_new_value = new_value
                    elif field == "conditions":
                        condition_count_changed = True
                        condition_count_new = len(new_value) if new_value else 0
                    elif field == "evaluation_config":
                        eval_type = serializer.validated_data.get(
                            "evaluation_type", serializer.instance.evaluation_type
                        )
                        config_key = "source" if eval_type == "hog" else "prompt"
                        old_content = old_value.get(config_key, "") if isinstance(old_value, dict) else ""
                        new_content = new_value.get(config_key, "") if isinstance(new_value, dict) else ""
                        if old_content != new_content:
                            config_content_changed = True

        instance = serializer.save()

        # Track appropriate event
        if is_deletion:
            report_user_action(
                self.request.user,
                "llma evaluation deleted",
                {
                    "evaluation_id": str(instance.id),
                    "evaluation_name": instance.name,
                    "was_enabled": old_enabled_value,
                },
                team=self.team,
                request=self.request,
            )
        elif changed_fields:
            event_properties: dict[str, Any] = {
                "evaluation_id": str(instance.id),
                "changed_fields": changed_fields,
            }

            if enabled_changed:
                event_properties["enabled_changed"] = True
                event_properties["enabled_new_value"] = enabled_new_value
            if condition_count_changed:
                event_properties["condition_count_changed"] = True
                event_properties["condition_count_new"] = condition_count_new
            if config_content_changed:
                event_properties["config_content_changed"] = True

            report_user_action(
                self.request.user,
                "llma evaluation updated",
                event_properties,
                team=self.team,
                request=self.request,
            )

    @llma_track_latency("llma_evaluations_list")
    @monitor(feature=None, endpoint="llma_evaluations_list", method="GET")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_evaluations_retrieve")
    @monitor(feature=None, endpoint="llma_evaluations_retrieve", method="GET")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @llma_track_latency("llma_evaluations_create")
    @monitor(feature=None, endpoint="llma_evaluations_create", method="POST")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(request=CreateEvaluationFromClusterRequestSerializer, responses=EvaluationSerializer)
    @action(detail=False, methods=["post"], url_path="create_from_cluster", required_scopes=["evaluation:write"])
    @llma_track_latency("llma_evaluations_create_from_cluster")
    @monitor(feature=None, endpoint="llma_evaluations_create_from_cluster", method="POST")
    def create_from_cluster(self, request: Request, **kwargs) -> Response:
        """Create a disabled LLM-judge evaluation draft from a cluster card summary."""
        request_serializer = CreateEvaluationFromClusterRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        run_id = request_serializer.validated_data["run_id"]
        cluster_id = request_serializer.validated_data["cluster_id"]
        cluster_run = _fetch_cluster_run_for_evaluation(self.team, run_id)
        if not cluster_run:
            return Response({"detail": "Clustering run not found."}, status=status.HTTP_404_NOT_FOUND)

        cluster = _find_cluster_for_evaluation(cluster_run, cluster_id)
        if not cluster:
            return Response({"detail": "Cluster not found in clustering run."}, status=status.HTTP_404_NOT_FOUND)

        title = _cluster_title(cluster, cluster_id)
        evaluation_goal = (request_serializer.validated_data.get("evaluation_goal") or "").strip()
        evaluation_prompt = (request_serializer.validated_data.get("evaluation_prompt") or "").strip()
        if not evaluation_prompt:
            evaluation_prompt = _build_cluster_evaluation_prompt(cluster, cluster_id, evaluation_goal or None)
        event_filters = _clustering_job_filters(self.team_id, cluster_run.get("job_id"))
        payload = {
            "name": _truncate(f"Cluster: {title}", 400),
            "description": _build_cluster_evaluation_description(
                cluster_run, cluster, cluster_id, evaluation_goal or None
            ),
            "enabled": False,
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": evaluation_prompt},
            "output_type": "boolean",
            "output_config": {"allows_na": True},
            "conditions": [{"id": f"cluster-{cluster_id}", "rollout_percentage": 100, "properties": event_filters}],
        }

        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        instance = serializer.instance
        report_user_action(
            request.user,
            "llma evaluation created from cluster",
            {
                "evaluation_id": str(instance.id),
                "evaluation_name": instance.name,
                "cluster_id": cluster_id,
                "cluster_title": title,
                "clustering_run_id": run_id,
                "clustering_level": cluster_run.get("level"),
                "clustering_job_id": cluster_run.get("job_id"),
                "condition_property_count": len(event_filters),
                "has_evaluation_goal": bool(evaluation_goal),
                "has_prompt_override": bool(request_serializer.validated_data.get("evaluation_prompt")),
            },
            team=self.team,
            request=self.request,
        )

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @llma_track_latency("llma_evaluations_update")
    @monitor(feature=None, endpoint="llma_evaluations_update", method="PUT")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @llma_track_latency("llma_evaluations_partial_update")
    @monitor(feature=None, endpoint="llma_evaluations_partial_update", method="PATCH")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(request=TestHogRequestSerializer, responses=TestHogResponseSerializer)
    @action(detail=False, methods=["post"], url_path="test_hog", required_scopes=["evaluation:read"])
    def test_hog(self, request: Request, **kwargs) -> Response:
        """Test Hog evaluation code against sample events without saving."""
        serializer = TestHogRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)

        source = serializer.validated_data["source"]
        sample_count = serializer.validated_data["sample_count"]
        allows_na = serializer.validated_data["allows_na"]
        conditions = serializer.validated_data.get("conditions", [])

        from posthog.hogql import ast
        from posthog.hogql.property import property_to_expr
        from posthog.hogql.query import execute_hogql_query

        from posthog.cdp.validation import compile_hog
        from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
        from posthog.models.team import Team

        try:
            bytecode = compile_hog(source, "destination")
        except serializers.ValidationError as e:
            return Response({"error": f"Compilation error: {e.detail}"}, status=400)
        except Exception:
            logger.exception("Unexpected error compiling Hog source")
            return Response({"error": "Compilation failed due to an unexpected error"}, status=400)

        team = Team.objects.get(id=self.team_id)

        # Build WHERE clause from trigger conditions (OR between condition sets, AND within each)
        where_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=["$ai_generation"]),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Sub,
                    left=ast.Call(name="now", args=[]),
                    right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=7)]),
                ),
            ),
        ]

        # Apply property filters from conditions
        condition_exprs: list[ast.Expr] = []
        for condition in conditions:
            props = condition.get("properties", [])
            if props:
                expr = property_to_expr(props, team)
                condition_exprs.append(expr)

        if condition_exprs:
            if len(condition_exprs) == 1:
                where_exprs.append(condition_exprs[0])
            else:
                where_exprs.append(ast.Or(exprs=condition_exprs))

        query = ast.SelectQuery(
            select=[
                ast.Field(chain=["uuid"]),
                ast.Field(chain=["event"]),
                ast.Field(chain=["properties"]),
                ast.Field(chain=["distinct_id"]),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=where_exprs),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
            limit=ast.Constant(value=sample_count),
        )

        tag_queries(product=Product.LLM_ANALYTICS, feature=Feature.QUERY)
        response = execute_hogql_query(query=query, team=team, limit_context=None)

        if not response.results:
            report_user_action(
                request.user,
                "llma evaluation hog code tested",
                {
                    "sample_count": sample_count,
                    "allows_na": allows_na,
                    "condition_count": len(conditions),
                    "result_count": 0,
                    "pass_count": 0,
                    "fail_count": 0,
                    "error_count": 0,
                    "na_count": 0,
                    "no_events": True,
                },
                team=self.team,
                request=self.request,
            )
            return Response({"results": [], "message": "No recent AI events found in the last 7 days"})

        results = []
        for row in response.results:
            event_uuid = str(row[0])
            event_type = row[1]
            properties = row[2]
            distinct_id = row[3]

            if isinstance(properties, str):
                properties = json.loads(properties)

            event_data = {
                "uuid": event_uuid,
                "event": event_type,
                "properties": properties,
                "distinct_id": distinct_id or "",
            }

            result = run_hog_eval(bytecode, event_data, allows_na=allows_na)

            input_raw, output_raw = extract_event_io(event_type, properties)
            input_preview = extract_text_from_messages(input_raw)[:200]
            output_preview = extract_text_from_messages(output_raw)[:200]

            results.append(
                {
                    "event_uuid": event_uuid,
                    "trace_id": properties.get("$ai_trace_id"),
                    "input_preview": input_preview,
                    "output_preview": output_preview,
                    "result": result["verdict"],
                    "reasoning": result["reasoning"],
                    "error": result["error"],
                }
            )

        report_user_action(
            request.user,
            "llma evaluation hog code tested",
            {
                "sample_count": sample_count,
                "allows_na": allows_na,
                "condition_count": len(conditions),
                "result_count": len(results),
                "pass_count": sum(1 for r in results if r["result"] is True),
                "fail_count": sum(1 for r in results if r["result"] is False),
                "error_count": sum(1 for r in results if r["error"]),
                "na_count": sum(1 for r in results if r["result"] is None and not r["error"]),
            },
            team=self.team,
            request=self.request,
        )

        return Response({"results": results})
