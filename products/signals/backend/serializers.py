import json
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, cast

from django.db.models import TextChoices

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers
from rest_framework.request import Request

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.models.integration import Integration, is_supported_external_issue_provider

from products.signals.backend import contracts
from products.signals.backend.billing import REFUND_INELIGIBILITY_REASONS, refund_ineligibility_reason
from products.signals.backend.contracts import DEFAULT_NOT_ACTIONABLE_KEY, STEERING_KEY, STEERING_MAX_LENGTH
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.warehouse_sources.backend.facade.models import ExternalDataSchema
from products.warehouse_sources.backend.facade.types import ExternalDataSchemaStatus

if TYPE_CHECKING:
    from products.signals.backend.implementation_pr import ImplementationPr
    from products.signals.backend.report_claims import ReportClaim

from .artefact_schemas import NON_WRITABLE_ARTEFACT_TYPES
from .daily_limit import reports_generated_today, team_day_start
from .models import (
    AutonomyPriority,
    SignalActorKind,
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportRefund,
    SignalReportTrackerIssue,
    SignalReportWorkState,
    SignalSourceConfig,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from .report_charts import CHART_SIZES, MAX_CHART_CAPTION_LENGTH, MAX_CHART_ID_LENGTH, MAX_CHART_TITLE_LENGTH
from .report_generation.resolve_reviewers import enrich_reviewer_dicts_with_org_members
from .report_metric_access import ReportMetricAccessPolicy
from .report_metric_refresh import MAX_REPORT_METRIC_REFRESH_REPORTS
from .report_metrics import (
    MAX_LIVE_METRIC_QUERY_POINTS,
    MAX_METRIC_CAPTION_LENGTH,
    MAX_METRIC_ID_LENGTH,
    MAX_METRIC_SERIES_POINTS,
    MAX_METRIC_TITLE_LENGTH,
    MAX_METRIC_UNIT_LENGTH,
    REPORT_METRIC_KINDS,
    REPORT_METRIC_ROLES,
    REPORT_METRIC_VALUE_FORMATS,
)
from .tracker_issues import TRACKER_TARGET_REQUIRED_FIELDS, issue_reference, validated_github_repository

DEFAULT_SESSION_ANALYSIS_SAMPLE_RATE = 0.1


@frozen
class _DataImportSchema:
    """The warehouse source type and schema name a signal source reads its sync status from."""

    source_type: str
    schema_name: str

    def matches(self, source_type: str, name: str) -> bool:
        # A repo-qualified schema reads as `<owner>/<repo>.<endpoint>`, a legacy one as the bare
        # endpoint name.
        return source_type == self.source_type and (name == self.schema_name or name.endswith(f".{self.schema_name}"))


# Maps (source_product, source_type) → the warehouse schema carrying that source's sync status
_DATA_IMPORT_SOURCE_MAP: dict[tuple[str, str], _DataImportSchema] = {
    (SignalSourceConfig.SourceProduct.GITHUB, SignalSourceConfig.SourceType.ISSUE): _DataImportSchema(
        source_type="Github", schema_name="issues"
    ),
    (SignalSourceConfig.SourceProduct.LINEAR, SignalSourceConfig.SourceType.ISSUE): _DataImportSchema(
        source_type="Linear", schema_name="issues"
    ),
    (SignalSourceConfig.SourceProduct.ZENDESK, SignalSourceConfig.SourceType.TICKET): _DataImportSchema(
        source_type="Zendesk", schema_name="tickets"
    ),
    (SignalSourceConfig.SourceProduct.PGANALYZE, SignalSourceConfig.SourceType.ISSUE): _DataImportSchema(
        source_type="PgAnalyze", schema_name="issues"
    ),
}

_DATA_IMPORT_EXTERNAL_SOURCE_TYPES = sorted({schema.source_type for schema in _DATA_IMPORT_SOURCE_MAP.values()})


def _read_data_import_statuses(team_id: int) -> dict[_DataImportSchema, set[str]]:
    """Every data-import schema on a team in one query, bucketed by `_DATA_IMPORT_SOURCE_MAP` value."""
    rows = (
        ExternalDataSchema.objects.filter(
            team_id=team_id,
            source__source_type__in=_DATA_IMPORT_EXTERNAL_SOURCE_TYPES,
        )
        .exclude(source__deleted=True)
        .values_list("source__source_type", "name", "status")
    )
    statuses: dict[_DataImportSchema, set[str]] = {}
    for row_source_type, row_name, row_status in rows:
        # `status` is nullable. A row without one matches none of the ranked states below.
        if row_status is None:
            continue
        for schema in _DATA_IMPORT_SOURCE_MAP.values():
            if schema.matches(row_source_type, row_name):
                statuses.setdefault(schema, set()).add(row_status)
    return statuses


_SOURCE_CONFIG_HELP_TEXT = (
    "Per-source settings as a JSON object. Keys read by the emission actionability gate on sources "
    "that define one (most data warehouse imports, and Conversations): "
    "`steering` (string, max 2000 characters) holds the team's preferences about this source's "
    "records in plain language: what matters, what to skip, what's out of scope. The emission "
    "actionability gate applies it when deciding which records become signals; rules apply from "
    "the next sync and nothing already emitted is retracted. "
    "`default_not_actionable` (boolean, default false) flips the gate's default: instead of "
    "keeping every record the steering rules don't exclude, only records that clearly match the "
    "team's preferences are kept. "
    "Other sources store these keys without reading them yet; future pipeline stages will consume "
    "the same steering text. "
    "Some sources read additional keys, for example `recording_filters` and `sample_rate` for "
    "session analysis."
)


# Declared as an open object WITHOUT typed `properties`: Orval turns properties into a
# key-stripping `zod.object`, which would silently drop source-specific keys (e.g. session
# replay's `recording_filters`) from MCP tool calls. The open shape generates a passthrough
# `zod.record`, and the steering keys are documented in the description instead.
@extend_schema_field({"type": "object", "additionalProperties": True, "description": _SOURCE_CONFIG_HELP_TEXT})
class _SourceConfigField(serializers.JSONField):
    """`config` blob typed as an open JSON object in the OpenAPI schema. Runtime behavior is
    plain JSONField; steering-key validation stays in the serializer's `validate`."""


class SignalSourceConfigSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField(
        help_text=(
            "Sync state of the warehouse import behind this source: `running`, `failed`, or "
            "`completed`. Null for a source that imports nothing from the warehouse, for an "
            "import that has never synced, and when the sync state could not be read."
        ),
    )
    config = _SourceConfigField(required=False, help_text=_SOURCE_CONFIG_HELP_TEXT)

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

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Absent key means "not read yet", a `None` value means the read failed.
        self._data_import_statuses_by_team: dict[int, dict[_DataImportSchema, set[str]] | None] = {}

    def get_status(self, obj: SignalSourceConfig) -> str | None:
        schema = _DATA_IMPORT_SOURCE_MAP.get((obj.source_product, obj.source_type))
        if schema is None:
            return None
        statuses_by_schema = self._data_import_statuses(obj.team_id)
        if statuses_by_schema is None:
            return None
        statuses = statuses_by_schema.get(schema, set())
        if ExternalDataSchemaStatus.RUNNING in statuses:
            return "running"
        # One failing repo outranks its siblings' success, so a broken repo is never hidden.
        if statuses & {
            ExternalDataSchemaStatus.FAILED,
            ExternalDataSchemaStatus.BILLING_LIMIT_REACHED,
            ExternalDataSchemaStatus.BILLING_LIMIT_TOO_LOW,
        }:
            return "failed"
        if ExternalDataSchemaStatus.COMPLETED in statuses:
            return "completed"
        return None

    def _data_import_statuses(self, team_id: int) -> dict[_DataImportSchema, set[str]] | None:
        """Sync statuses of every data-import source on a team, keyed as `_DATA_IMPORT_SOURCE_MAP` values.

        The inbox reads this list on load, and DRF reuses one child serializer across a list,
        so the first row that needs a status resolves every row's in one query. A `None` return
        means the warehouse read raised. Those rows then report no status, which keeps the
        response a 200 so a person can still configure their sources.
        """
        if team_id in self._data_import_statuses_by_team:
            return self._data_import_statuses_by_team[team_id]
        try:
            statuses = _read_data_import_statuses(team_id)
        except Exception as exc:
            capture_exception(exc)
            statuses = None
        self._data_import_statuses_by_team[team_id] = statuses
        return statuses

    def validate(self, attrs: dict) -> dict:
        source_product = attrs.get("source_product", getattr(self.instance, "source_product", None))
        source_type = attrs.get("source_type", getattr(self.instance, "source_type", None))
        enabled = attrs.get("enabled", getattr(self.instance, "enabled", False))
        config = attrs.get("config")
        # `is not None` rather than truthiness: falsy non-dict values ([], "", 0, false) must be
        # rejected, not silently persisted.
        if config is not None:
            if not isinstance(config, dict):
                raise serializers.ValidationError({"config": "config must be a JSON object"})
            # Presence-based checks so an explicit null is rejected like any other wrong type.
            if STEERING_KEY in config:
                steering = config[STEERING_KEY]
                if not isinstance(steering, str):
                    raise serializers.ValidationError({"config": "steering must be a string"})
                if len(steering) > STEERING_MAX_LENGTH:
                    raise serializers.ValidationError(
                        {"config": f"steering must be at most {STEERING_MAX_LENGTH} characters"}
                    )
            if DEFAULT_NOT_ACTIONABLE_KEY in config and not isinstance(config[DEFAULT_NOT_ACTIONABLE_KEY], bool):
                raise serializers.ValidationError({"config": "default_not_actionable must be a boolean"})
        if source_product == SignalSourceConfig.SourceProduct.SESSION_REPLAY and config:
            recording_filters = config.get("recording_filters")
            if recording_filters is not None and not isinstance(recording_filters, dict):
                raise serializers.ValidationError({"config": "recording_filters must be a JSON object"})
            sample_rate = config.get("sample_rate")
            if sample_rate is not None:
                # `isinstance(True, int)` is True in Python — reject bools explicitly.
                if isinstance(sample_rate, bool) or not isinstance(sample_rate, int | float):
                    raise serializers.ValidationError({"config": "sample_rate must be a number between 0 and 1"})
                if not (0 <= sample_rate <= 1):
                    raise serializers.ValidationError({"config": "sample_rate must be between 0 and 1"})
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

    def create(self, validated_data: dict) -> SignalSourceConfig:
        if (
            validated_data.get("source_product") == SignalSourceConfig.SourceProduct.SESSION_REPLAY
            and validated_data.get("source_type") == SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER
        ):
            config = dict(validated_data.get("config") or {})
            config.setdefault("sample_rate", DEFAULT_SESSION_ANALYSIS_SAMPLE_RATE)
            validated_data["config"] = config
        return super().create(validated_data)


# A team overrides the base branch for a handful of its repos; a map larger than this is abuse,
# not use. Bounding it caps the per-write activity-log row (which stores the full before/after map)
# and the request body a caller can push through this field.
MAX_AUTOSTART_BASE_BRANCH_ENTRIES = 500


class SignalTeamConfigSerializer(serializers.ModelSerializer):
    issue_tracking_integration = TeamScopedPrimaryKeyRelatedField(
        queryset=Integration.objects.all(),
        required=False,
        allow_null=True,
        help_text=(
            "Connected GitHub, GitLab, Linear, or Jira integration that self-driving opens a tracker "
            "issue in for each pull request it makes. Null turns tracker issues off, which is the "
            "default."
        ),
    )
    issue_tracking_config = serializers.DictField(
        child=serializers.CharField(max_length=255, allow_blank=True),
        required=False,
        help_text=(
            "Where in the tracker the issues land. Required keys depend on the integration kind: "
            "github -> {repository}; linear -> {team_id}; jira -> {project_key}; gitlab needs none, "
            "because its integration is already bound to one project. An optional 'label' is applied "
            "to created GitHub issues."
        ),
    )
    autostart_base_branches = serializers.DictField(
        child=serializers.CharField(max_length=255, allow_blank=True),
        required=False,
        help_text=(
            "Per-repository base branch overrides for auto-started inbox PRs, keyed by "
            "'organization/repository'. The branch is what the auto-PR targets; omit a repo "
            "(or send {}) to keep targeting the repo default branch."
        ),
    )
    max_reports_per_day = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        # Ceiling at the int4 column max so an out-of-range value returns 400, not a DB write error.
        max_value=2147483647,
        help_text=(
            "Daily cap on new reports surfacing to the inbox, counted per calendar day in the "
            "project's timezone. Once reached, signal ingestion, scout runs, and report research "
            "pause until local midnight. Null means unlimited."
        ),
    )
    default_open_pull_request_ready = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether self-driving pull requests open ready for review instead of draft, so the full CI "
            "matrix starts when the pull request is created. False by default. A reviewer's own "
            "github_open_pull_request_ready overrides this for reports that suggest them as reviewer."
        ),
    )
    reports_generated_today = serializers.SerializerMethodField(
        help_text=(
            "How many reports first became visible in the inbox during the current project-timezone "
            "day. This is the count the daily report limit compares against."
        )
    )
    daily_report_limit_reached = serializers.SerializerMethodField(
        help_text=(
            "Whether the team hit its daily report limit, pausing new report generation until "
            "local midnight. Always false when max_reports_per_day is null."
        )
    )

    # Memoized per serializer instance: both computed fields need the same count, and an
    # instance only ever renders the team's one singleton row.
    _reports_today: int | None = None

    def _reports_today_count(self, obj: SignalTeamConfig) -> int:
        if self._reports_today is None:
            self._reports_today = reports_generated_today(obj.team, day_start=team_day_start(obj.team))
        return self._reports_today

    @extend_schema_field(serializers.IntegerField(min_value=0))
    def get_reports_generated_today(self, obj: SignalTeamConfig) -> int:
        # No limit means the count is never shown, so skip the query — mirroring the sibling field
        # and daily_report_limit_gate, which both short-circuit unlimited teams.
        if obj.max_reports_per_day is None:
            return 0
        return self._reports_today_count(obj)

    @extend_schema_field(serializers.BooleanField())
    def get_daily_report_limit_reached(self, obj: SignalTeamConfig) -> bool:
        if obj.max_reports_per_day is None:
            return False
        return self._reports_today_count(obj) >= obj.max_reports_per_day

    class Meta:
        model = SignalTeamConfig
        fields = [
            "id",
            "autostart_enabled",
            "default_autostart_priority",
            "default_slack_notification_channel",
            "autostart_base_branches",
            "issue_tracking_integration",
            "issue_tracking_config",
            "max_reports_per_day",
            "default_open_pull_request_ready",
            "reports_generated_today",
            "daily_report_limit_reached",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "reports_generated_today", "daily_report_limit_reached", "created_at", "updated_at"]
        extra_kwargs = {
            "autostart_enabled": {
                "help_text": (
                    "Master switch for autonomous inbox PRs. Null (never set) leaves autostart on; set "
                    "false to opt out, so actionable reports still generate and notify but the team "
                    "never auto-starts an implementation task or opens a PR — reviewers open PRs manually."
                )
            },
            "default_slack_notification_channel": {
                "help_text": (
                    "Default Slack channel for this team's signal inbox notifications, in the same "
                    "`channel_id|#channel-name` shape PostHog uses elsewhere (only the channel id is required). "
                    "Null means no team-level default; per-user channels still apply."
                )
            },
        }

    def validate_issue_tracking_integration(self, value: Integration | None) -> Integration | None:
        if value is None:
            return None
        if not is_supported_external_issue_provider(value.kind):
            raise serializers.ValidationError(
                f"'{value.kind}' cannot track issues. Connect GitHub, GitLab, Linear, or Jira."
            )
        return value

    def validate(self, attrs: dict) -> dict:
        attrs = super().validate(attrs)
        # The target only makes sense against an integration, and the two can arrive in either the
        # same PATCH or separate ones, so fall back to what is already stored.
        integration = (
            attrs["issue_tracking_integration"]
            if "issue_tracking_integration" in attrs
            else getattr(self.instance, "issue_tracking_integration", None)
        )
        if integration is None:
            return attrs
        config = (
            attrs["issue_tracking_config"]
            if "issue_tracking_config" in attrs
            else getattr(self.instance, "issue_tracking_config", None) or {}
        )
        missing = [
            field
            for field in TRACKER_TARGET_REQUIRED_FIELDS.get(integration.kind, ())
            if not str(config.get(field) or "").strip()
        ]
        if missing:
            raise serializers.ValidationError(
                {"issue_tracking_config": f"Missing required fields for {integration.kind}: {', '.join(missing)}."}
            )
        # The repository reaches a GitHub path, so a name it cannot hold fails here rather than on
        # every run.
        if integration.kind == Integration.IntegrationKind.GITHUB:
            try:
                validated_github_repository(config["repository"])
            except serializers.ValidationError as error:
                raise serializers.ValidationError({"issue_tracking_config": error.detail})
        return attrs

    def validate_autostart_base_branches(self, value: dict) -> dict:
        if len(value) > MAX_AUTOSTART_BASE_BRANCH_ENTRIES:
            raise serializers.ValidationError(
                f"Too many repository overrides ({len(value)}); the maximum is {MAX_AUTOSTART_BASE_BRANCH_ENTRIES}."
            )
        cleaned: dict[str, str] = {}
        for repo, branch in value.items():
            repo_key = (repo or "").strip()
            # Bound the key too — the DictField child only caps the branch value, so an
            # oversized key would otherwise slip a large string into the stored map and its
            # activity-log copy.
            if len(repo_key) > 255:
                raise serializers.ValidationError("Repository keys must be at most 255 characters.")
            if repo_key.count("/") != 1 or any(not part for part in repo_key.split("/")):
                raise serializers.ValidationError(
                    f"Repository keys must be in 'organization/repository' form, got '{repo}'."
                )
            branch_value = (branch or "").strip()
            if branch_value:
                cleaned[repo_key.lower()] = branch_value
        return cleaned


class _UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "uuid", "first_name", "last_name", "email"]
        read_only_fields = fields


class SignalReportPullRequestAttachedBySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        source="actor_kind",
        choices=SignalActorKind.choices,
        allow_null=True,
        help_text="Kind of actor who attached the PR. Null when legacy attribution is unknown.",
    )
    user = _UserSerializer(
        source="attached_by_user",
        allow_null=True,
        help_text="Authenticated principal who attached the PR, when recorded.",
    )
    agent = serializers.CharField(
        source="agent_name", allow_null=True, help_text="External agent client name, when recorded."
    )
    task_id = serializers.UUIDField(allow_null=True, help_text="Internal task that attached the PR, when recorded.")


class SignalReportPullRequestSerializer(serializers.Serializer):
    id = serializers.UUIDField(
        allow_null=True,
        help_text="PR selection ID. Task-output links use a deterministic ID until attached as an artefact.",
    )
    url = serializers.URLField(help_text="GitHub pull request URL.")
    state = serializers.ChoiceField(
        choices=SignalReportAssignment.PrState.choices, help_text="Latest known GitHub state."
    )
    merged = serializers.BooleanField(help_text="Whether this PR merged.")
    attached_by = serializers.SerializerMethodField(
        help_text="Who first attached this PR to the report, not necessarily its GitHub author. Task-output links identify the originating task."
    )
    claim_id = serializers.UUIDField(
        allow_null=True, help_text="Originating work claim. Null for legacy links without a recorded claim."
    )
    attached_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the first PR link was recorded. For backfilled links this is the import time; null for an unmigrated link.",
    )

    @extend_schema_field(SignalReportPullRequestAttachedBySerializer(allow_null=True))
    def get_attached_by(self, obj: "ImplementationPr") -> dict[str, object] | None:
        return (
            SignalReportPullRequestAttachedBySerializer(obj).data
            if obj.attached_at is not None or obj.actor_kind is not None
            else None
        )


class SignalReportClaimSerializer(serializers.Serializer):
    claim_id = serializers.UUIDField(
        required=False, help_text="Active claim ID returned by an earlier call. Stale claims are rejected."
    )
    pull_requests = serializers.ListField(
        child=serializers.URLField(max_length=2048),
        required=False,
        max_length=50,
        help_text="GitHub PR URLs to add to this report's work. Additive and deduplicated; may span repositories.",
    )
    takeover = serializers.BooleanField(
        required=False, default=False, help_text="Explicitly end another actor's claim and take ownership."
    )
    pr_url = serializers.URLField(
        required=False,
        help_text="Compatibility alias for adding one PR. Prefer pull_requests for new callers.",
    )
    release = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Release ownership while preserving any attached pull request.",
    )

    def validate(self, attrs: dict) -> dict:
        if attrs.get("release") and ("pr_url" in attrs or attrs.get("pull_requests") or attrs.get("takeover")):
            raise serializers.ValidationError("Release cannot be combined with PR attachment or takeover.")
        if attrs.get("claim_id") and attrs.get("takeover"):
            raise serializers.ValidationError("A claim ID cannot be combined with takeover.")
        return attrs


class SignalReportAssigneeSerializer(serializers.Serializer):
    claim_id = serializers.UUIDField(allow_null=True, help_text="Identifier for the active work attempt.")
    kind = serializers.ChoiceField(choices=SignalActorKind.choices)
    user = _UserSerializer(allow_null=True)
    task_id = serializers.UUIDField(allow_null=True)
    agent = serializers.CharField(allow_null=True)
    claimed_at = serializers.DateTimeField(allow_null=True)


class SignalUserAutonomyConfigSerializer(serializers.ModelSerializer):
    user = _UserSerializer(read_only=True)
    slack_notification_integration_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="ID of the Slack Integration to deliver inbox-item notifications through, or null when notifications are disabled.",
    )

    class Meta:
        model = SignalUserAutonomyConfig
        fields = [
            "id",
            "user",
            "autostart_priority",
            "slack_notification_integration_id",
            "slack_notification_channel",
            "slack_notification_min_priority",
            "github_assign_on_pull_request",
            "github_open_pull_request_ready",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]
        extra_kwargs = {
            "slack_notification_channel": {
                "help_text": (
                    "Where the reviewer ping goes, in the same `id|name` shape PostHog uses elsewhere (only "
                    "the id is required): a channel (`C0123ABC456|#alerts`), or a workspace member "
                    "(`U0123ABC456|@sam`) who is sent a direct message. Null disables Slack notifications."
                )
            },
            "slack_notification_min_priority": {
                "help_text": (
                    "Minimum report priority that triggers a Slack notification. P0 is highest. "
                    "Null means notify on every priority. When set, reports without a priority judgment do not notify."
                )
            },
            "github_assign_on_pull_request": {
                "help_text": (
                    "Whether to add this user as a GitHub assignee on implementation pull requests for "
                    "reports that suggest them as reviewer. Off by default. Assignment is additive, so "
                    "turning it off never removes an assignee from a pull request that already has one."
                )
            },
            "github_open_pull_request_ready": {
                "help_text": (
                    "Whether implementation pull requests for reports that suggest this user as reviewer "
                    "open ready for review instead of draft, so the full CI matrix starts right away. "
                    "Null follows the project's default_open_pull_request_ready. Applies only when the "
                    "pull request is created; a pull request somebody converts back to draft stays draft."
                )
            },
        }


class SignalUserAutonomyConfigCreateSerializer(serializers.Serializer):
    autostart_priority = serializers.ChoiceField(choices=AutonomyPriority.choices, required=False, allow_null=True)
    slack_notification_integration_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text=(
            "Primary key of a Slack `Integration` row in one of the caller's teams. Pair with "
            "`slack_notification_channel` to enable notifications; pass null on either to disable them."
        ),
    )
    slack_notification_channel = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=255,
        help_text=(
            "`channel_id|#channel-name` target, the same convention used by Insight Alerts, or a "
            "`member_id|@display-name` target (`U0123ABC456|@sam`) to send the ping as a direct message. "
            "A member target is checked against the workspace on save."
        ),
    )
    slack_notification_direct_message = serializers.BooleanField(
        required=False,
        help_text=(
            "Set true to send the ping as a direct message from the PostHog app. The caller's own member id is "
            "resolved in the connected workspace and stored in `slack_notification_channel`, so nothing has to be "
            "picked. Rejected when the workspace has no eligible account for the caller, and cannot be combined "
            "with `slack_notification_channel`."
        ),
    )
    slack_notification_min_priority = serializers.ChoiceField(
        choices=AutonomyPriority.choices,
        required=False,
        allow_null=True,
        help_text=(
            "P0 is highest. Null = notify for every priority. When set, reports without a priority judgment do not notify."
        ),
    )
    github_assign_on_pull_request = serializers.BooleanField(
        required=False,
        help_text=(
            "Add this user as a GitHub assignee on implementation pull requests for reports that "
            "suggest them as reviewer. Off by default. Turning it off stops future assignment and "
            "never removes an existing assignee."
        ),
    )
    github_open_pull_request_ready = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text=(
            "Open implementation pull requests for reports that suggest this user as reviewer ready "
            "for review instead of draft, so the full CI matrix runs without anybody clicking Ready. "
            "Null follows the project default. A ready pull request runs the full matrix on every push."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        if attrs.get("slack_notification_direct_message") and attrs.get("slack_notification_channel"):
            raise serializers.ValidationError(
                "Set either `slack_notification_channel` or `slack_notification_direct_message`, not both."
            )
        return attrs


class SignalReportRefundSerializer(serializers.ModelSerializer):
    billing_synced = serializers.SerializerMethodField(
        help_text=(
            "Whether the billing service has acknowledged this refund. Always relevant for the "
            "credited path (the Stripe credit is issued asynchronously); excluded-path refunds "
            "need no billing sync and report false."
        ),
    )

    class Meta:
        model = SignalReportRefund
        fields = [
            "id",
            "reason",
            "note",
            "billing_path",
            "credits",
            "pr_url",
            "pr_run_created_at",
            "credit_amount_usd",
            "billing_synced",
            "created_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "reason": {"help_text": "Why the user refunded this PR (feeds the refund review)."},
            "note": {"help_text": "Optional free-form note captured with the refund."},
            "billing_path": {
                "help_text": (
                    "How the refund was executed, frozen at refund time: 'excluded' (same UTC day as "
                    "the billable PR run — the report never reaches billing) or 'credited' (billing "
                    "issues a Stripe customer-balance credit)."
                )
            },
            "credits": {"help_text": "Signals credits refunded (flat per-PR charge snapshot; 1 credit = $0.01)."},
            "pr_url": {"help_text": "The refunded implementation PR's GitHub URL, snapshotted at refund time."},
            "pr_run_created_at": {
                "help_text": "When the first billable PR run was created — the charge this reverses."
            },
            "credit_amount_usd": {
                "help_text": (
                    "USD amount the billing service credited (credited path only). Null until the sync "
                    "completes; '0.00' is a legitimate outcome (e.g. the PR was inside the free tier)."
                )
            },
            "created_at": {"help_text": "When the refund was created."},
        }

    def get_billing_synced(self, obj: SignalReportRefund) -> bool:
        return obj.billing_synced_at is not None


# The chart `query` is free-form JSON by design, and the generated schema has to keep it that way.
#
# This is load-bearing, not a style call. The MCP executor dispatches Zod's *parsed* output
# (`services/mcp/src/tools/exec.ts` — "Dispatch the parsed output so coerced values and defaults
# apply"), and a generated `zod.object({...})` strips keys it doesn't name. Declaring the node's
# shape — even just `kind` — would therefore drop `source` / `display` / `shortId` on the way through
# the tool and hand the backend a bare `{"kind": ...}`: valid per `ReportChart`, and a chart that
# renders nothing. `additionalProperties` doesn't save it either; it reaches the TypeScript type but
# not the Zod schema.
#
# So the field stays untyped in the schema (the `spec: zod.unknown()` precedent), and the contract
# lives in `help_text` where the scout reads it, enforced by `ReportChart` server-side.
@extend_schema_field(OpenApiTypes.ANY)
class ChartQueryField(serializers.JSONField):
    """The query node on a report chart. Typed for the schema pipeline so the generated MCP tool and
    frontend types describe a query node instead of an opaque `unknown`, while still carrying the
    node's per-kind fields through untouched."""


class ReportChartSerializer(serializers.Serializer):
    """One chart attached to a report — rendered in the inbox and referenceable from the summary."""

    chart_id = serializers.CharField(
        max_length=MAX_CHART_ID_LENGTH,
        help_text=(
            "Stable slug for this chart within the report (lowercase letters, numbers, underscores, "
            "hyphens; must start with a letter or number). Reference it from `summary` as a markdown "
            "link with a `chart:` target — `[Daily signups](chart:signups-drop)` — to place the chart "
            "at that point in the body. A chart you don't reference still renders, below the summary."
        ),
    )
    title = serializers.CharField(
        max_length=MAX_CHART_TITLE_LENGTH,
        help_text="Short heading shown above the chart.",
    )
    query = ChartQueryField(
        help_text=(
            "The query node to render. `kind` must be `InsightVizNode` (an ad-hoc product analytics "
            "chart), `DataVisualizationNode` (a SQL series — a `HogQLQuery` source plus a `display`), "
            "or `SavedInsightNode` (an existing insight by `shortId`). Pin the window to absolute "
            "dates where the node supports it, so the reader sees the data you wrote about rather "
            "than whatever a relative range resolves to when they open the report."
        ),
    )
    caption = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=MAX_CHART_CAPTION_LENGTH,
        help_text="Optional one-line note on what to look at in the chart.",
    )
    size = serializers.ChoiceField(
        choices=CHART_SIZES,
        required=False,
        allow_null=True,
        help_text=(
            "How much height the chart gets: `small` for a single number or a short series, `medium` "
            "for an ordinary graph, `large` when there are rows or a grid to read (retention, paths, "
            "a wide breakdown). Leave it out unless the default looks wrong — the inbox sizes a chart "
            "from its query, and two charts referenced from the same paragraph sit side by side."
        ),
    )


class _MetricFloatField(serializers.FloatField):
    """A metric value that refuses a JSON boolean.

    DRF's `FloatField` coerces `true`/`false` to 1.0/0.0 through `float(data)`, which would turn a
    malformed boolean snapshot into a real measurement at the API boundary. A metric value is never
    a boolean, so reject it before coercion; the schema pipeline still treats this as a plain number
    because it subclasses `FloatField`.
    """

    def to_internal_value(self, data: float | int | str) -> float:
        if isinstance(data, bool):
            self.fail("invalid")
        return super().to_internal_value(data)


class ReportMetricComparisonSerializer(serializers.Serializer):
    value = _MetricFloatField(help_text="Baseline or previous value, formatted like the current value.")
    label = serializers.CharField(  # type: ignore[assignment]  # field name intentionally shadows Field.label
        max_length=MAX_METRIC_UNIT_LENGTH,
        help_text="Short context for the comparison, such as `Previous period`.",
    )


_REPORT_METRIC_QUERY_HELP = (
    "Required when authoring: a live InsightVizNode wrapping one bounded TrendsQuery. Consumers "
    "derive a BoldNumber execution for the whole-window aggregate and an ActionsBar execution for "
    "longitudinal buckets. The query must produce exactly one output series and no more than "
    f"{MAX_LIVE_METRIC_QUERY_POINTS} estimated longitudinal points; one formula may combine up to "
    "ten event or action source series. An affected_users metric uses exactly one source with "
    "`math: dau`; never sum its per-bucket unique-user values. A response omits this on list or "
    "redacts it to null on detail when the viewer lacks access to the definition."
)


class ReportMetricSerializer(serializers.Serializer):
    """One impact measurement shown on a report."""

    metric_id = serializers.CharField(
        max_length=MAX_METRIC_ID_LENGTH,
        help_text=(
            "Stable slug for this metric within the report: lowercase letters, numbers, underscores, "
            "and hyphens, starting with a letter or number."
        ),
    )
    title = serializers.CharField(
        max_length=MAX_METRIC_TITLE_LENGTH,
        help_text="Short human-readable label for the measurement.",
    )
    kind = serializers.ChoiceField(
        choices=REPORT_METRIC_KINDS,
        help_text="What the value measures, independent of how it is formatted or drawn.",
    )
    role = serializers.ChoiceField(
        choices=REPORT_METRIC_ROLES,
        required=False,
        default="supporting",
        help_text="`primary` for the report's key observation, otherwise `supporting`.",
    )
    value = _MetricFloatField(
        allow_null=True,
        required=False,
        default=None,
        help_text=(
            "Latest saved snapshot, initially observed during authoring and replaced when a person "
            "opens the inbox or the report. Null means no snapshot is available to this viewer; it never means "
            "zero. The required live query remains the source of truth."
        ),
    )
    value_at = serializers.DateTimeField(
        allow_null=True,
        required=False,
        default=None,
        help_text="When the visible snapshot value was measured; null when value is null.",
    )
    series = serializers.ListField(
        child=_MetricFloatField(),
        allow_null=True,
        required=False,
        default=None,
        max_length=MAX_METRIC_SERIES_POINTS,
        help_text=(
            "Trailing per-bucket values of the live query, oldest first, saved with the value snapshot "
            f"so a list row can draw the trend without running the query; at most {MAX_METRIC_SERIES_POINTS} "
            "points. Null when no snapshot series is available to this viewer."
        ),
    )
    value_format = serializers.ChoiceField(
        choices=REPORT_METRIC_VALUE_FORMATS,
        required=False,
        default="number",
        help_text=(
            "How to format the numeric value; semantic meaning remains in kind. `percentage` uses "
            "percentage points, so 34 renders as 34%; `percentage_scaled` uses a 0–1 ratio, so "
            "0.34 renders as 34%. Sessions and occurrences use count; duration uses duration with "
            "an ms/s unit; revenue uses currency with an ISO currency unit."
        ),
    )
    unit = serializers.CharField(
        allow_null=True,
        required=False,
        default=None,
        max_length=MAX_METRIC_UNIT_LENGTH,
        help_text="Optional short suffix or currency code, such as `users`, `ms`, or `USD`.",
    )
    query = ChartQueryField(
        allow_null=True,
        required=False,
        default=None,
        help_text=_REPORT_METRIC_QUERY_HELP,
    )
    caption = serializers.CharField(
        allow_null=True,
        required=False,
        default=None,
        max_length=MAX_METRIC_CAPTION_LENGTH,
        help_text=(
            "Optional context the tile cannot show, such as a filter that narrows the count or a "
            "caveat on the data. Omit it rather than restate the title, unit, or window."
        ),
    )

    def to_representation(self, instance: Mapping[str, object]) -> dict[str, object]:
        representation = dict(super().to_representation(instance))
        policy = self._access_policy()

        if not policy.may_read_snapshot(instance):
            representation["value"] = None
            representation["value_at"] = None
            representation["series"] = None

        if "query" in representation and not policy.may_read_query(instance):
            representation["query"] = None

        return representation

    def _access_policy(self) -> ReportMetricAccessPolicy:
        context_key = "_report_metric_access_policy"
        cached = self.context.get(context_key)
        if isinstance(cached, ReportMetricAccessPolicy):
            return cached

        request = self.context.get("request")
        get_team = self.context.get("get_team")
        team = get_team() if callable(get_team) else None
        policy = ReportMetricAccessPolicy(
            request=request if isinstance(request, Request) else None,
            team=team if isinstance(team, Team) else None,
        )
        self.context[context_key] = policy
        return policy


class ReportMetricWriteSerializer(ReportMetricSerializer):
    """Authoring shape: unlike a read response, the live query cannot be absent or redacted."""

    query = ChartQueryField(help_text=_REPORT_METRIC_QUERY_HELP)
    comparison = ReportMetricComparisonSerializer(
        allow_null=True,
        required=False,
        default=None,
        help_text="Legacy optional comparison. New report metrics must omit it.",
    )


class ReportMetricListSerializer(ReportMetricSerializer):
    """Snapshot-only metric shape for report lists.

    Omitting query definitions keeps the paginated inbox payload bounded.
    """

    query = None  # type: ignore[assignment]  # removes the inherited field from the list projection


class SignalReportSerializer(serializers.ModelSerializer):
    artefact_count = serializers.IntegerField(read_only=True)
    charts = ReportChartSerializer(
        many=True,
        read_only=True,
        help_text=(
            "Charts the report shows, in the order they were written. The summary places one with a "
            "`[label](chart:<chart_id>)` link; the rest render below it."
        ),
    )
    metrics = ReportMetricSerializer(
        many=True,
        read_only=True,
        help_text=(
            "Typed impact measurements in display order. At most one is primary. Live metric values "
            "and history come from their query; value/value_at are the latest saved fallback snapshots."
        ),
    )
    suggested_prompts = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text=(
            "Follow-up prompts the report's author suggests sending about it (questions to ask, or "
            "next-step actions to request), in the order they were written. The inbox offers them "
            "above the `Ask AI` box; clicking one fills the box with it."
        ),
    )
    refund_ineligibility_reason = serializers.SerializerMethodField(
        help_text=(
            "Why refunding this report's PR would be rejected right now, or null when a refund "
            "would be accepted (see the field's schema for the reason values)."
        ),
    )
    priority = serializers.SerializerMethodField(
        help_text="P0–P4 from the latest priority judgment artefact (when present).",
    )
    actionability = serializers.SerializerMethodField(
        help_text="Actionability choice from the latest actionability judgment artefact (when present).",
    )
    already_addressed = serializers.SerializerMethodField(
        help_text=(
            "Whether the issue is already being handled — fixed in recent changes, or with a fix in "
            "flight (an open PR, a recently active branch, an assigned / in-progress issue or agent "
            "task) — from the actionability judgment artefact."
        ),
    )
    dismissal_reason = serializers.SerializerMethodField(
        help_text="Reason code from the latest dismissal artefact, set when the report was suppressed (when present).",
    )
    dismissal_note = serializers.SerializerMethodField(
        help_text="Free-form note captured alongside the dismissal reason (when present).",
    )
    repo_slug = serializers.SerializerMethodField(
        help_text=(
            "`organization/repository` the report's work targets, from the latest repo-selection "
            "artefact (when present). Lets list cards show repository context without a per-card fetch."
        ),
    )
    is_suggested_reviewer = serializers.BooleanField(read_only=True, default=False)
    source_products = serializers.SerializerMethodField(
        help_text="Distinct source products contributing signals to this report (from ClickHouse).",
    )
    scout_name = serializers.SerializerMethodField(
        help_text="skill_name slug of the scout that authored this report, when scout-authored (from ClickHouse); null otherwise.",
    )
    implementation_pr_url = serializers.SerializerMethodField(
        help_text="Pull request attached to this report's claim, if available.",
    )
    pull_requests = serializers.SerializerMethodField(
        help_text="All distinct PRs linked to this report across work attempts."
    )
    implementation_pr_state = serializers.SerializerMethodField(
        help_text="Latest known pull request state: unknown, draft, open, closed, or merged.",
    )
    implementation_pr_merged = serializers.SerializerMethodField(
        help_text=(
            "Whether that implementation PR is merged, per the GitHub webhook. False when there is no "
            "PR or it hasn't merged. Report status doesn't imply this: a resolved report may have been "
            "resolved directly, without a merged PR."
        ),
    )
    tracker_issue_url = serializers.SerializerMethodField(
        help_text=(
            "Link to the issue self-driving opened in the team's tracker for this report's pull "
            "request. Null when the team tracks no issues, or the issue could not be opened."
        ),
    )
    tracker_issue_reference = serializers.SerializerMethodField(
        help_text=(
            "How that tracker issue reads in its provider, for example '#12' or 'ENG-123'. Null "
            "when there is no tracker issue."
        ),
    )
    tracker_issue_error = serializers.SerializerMethodField(
        help_text=(
            "Why the tracker issue could not be opened, for a team that wants one. Null when the "
            "issue exists or the team tracks no issues."
        ),
    )
    work_state = serializers.SerializerMethodField(
        help_text="Derived remediation state: unclaimed, working, in_review, or done.",
    )
    assignee = serializers.SerializerMethodField(
        help_text="Current user, internal task, or external agent claim owner. Null when unclaimed.",
    )
    refund = serializers.SerializerMethodField(
        help_text="The report's PR refund, when one exists. One refund per report, ever.",
    )
    channel_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text=(
            "The space (task channel) this report is assigned to, or null when unassigned. "
            "The general view lists every report regardless of this value."
        ),
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
            "charts",
            "metrics",
            "suggested_prompts",
            "priority",
            "actionability",
            "already_addressed",
            "dismissal_reason",
            "dismissal_note",
            "repo_slug",
            "is_suggested_reviewer",
            "source_products",
            "scout_name",
            "implementation_pr_url",
            "pull_requests",
            "implementation_pr_state",
            "implementation_pr_merged",
            "tracker_issue_url",
            "tracker_issue_reference",
            "tracker_issue_error",
            "work_state",
            "assignee",
            "refund",
            "refund_ineligibility_reason",
            "billing_exempt_reason",
            "channel_id",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "billing_exempt_reason": {
                "help_text": (
                    "Non-null when this report is system-marked never-billable (PostHog-system origin, "
                    "e.g. a health-check scout finding) — its implementation PRs are free and cannot be "
                    "refunded because nothing was charged."
                )
            },
        }

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

    def _get_dismissal_artefact_data(self, obj: SignalReport) -> dict | None:
        prefetched = getattr(obj, "prefetched_dismissal_artefacts", None)
        if prefetched is not None:
            art = prefetched[0] if prefetched else None
        else:
            art = obj.artefacts.filter(type=SignalReportArtefact.ArtefactType.DISMISSAL).order_by("-created_at").first()
        if art is None:
            return None
        try:
            data = json.loads(art.content)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def get_dismissal_reason(self, obj: SignalReport) -> str | None:
        data = self._get_dismissal_artefact_data(obj)
        if data is None:
            return None
        # Reason codes are owned by the client; pass through whatever was stored.
        value = data.get("reason")
        return value if isinstance(value, str) and value else None

    def get_dismissal_note(self, obj: SignalReport) -> str | None:
        data = self._get_dismissal_artefact_data(obj)
        if data is None:
            return None
        value = data.get("note")
        return value if isinstance(value, str) and value else None

    def _get_repo_selection_artefact_data(self, obj: SignalReport) -> dict | None:
        prefetched = getattr(obj, "prefetched_repo_selection_artefacts", None)
        if prefetched is not None:
            art = prefetched[0] if prefetched else None
        else:
            art = (
                obj.artefacts.filter(type=SignalReportArtefact.ArtefactType.REPO_SELECTION)
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

    def get_repo_slug(self, obj: SignalReport) -> str | None:
        data = self._get_repo_selection_artefact_data(obj)
        if data is None:
            return None
        value = data.get("repository")
        return value if isinstance(value, str) and value else None

    def get_source_products(self, obj: SignalReport) -> list[str]:
        source_products_map: dict[str, list[str]] | None = self.context.get("source_products_map")
        if source_products_map is not None:
            return source_products_map.get(str(obj.id), [])
        return []

    def get_scout_name(self, obj: SignalReport) -> str | None:
        scout_names_map: dict[str, str] | None = self.context.get("scout_names_map")
        if scout_names_map is not None:
            return scout_names_map.get(str(obj.id))
        return None

    def _get_pull_requests(self, obj: SignalReport) -> list["ImplementationPr"]:
        from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports

        by_report = self.context.get("pull_requests_map")
        if by_report is None:
            by_report = self.context.setdefault("resolved_pull_requests_map", {})
            report_id = str(obj.id)
            if report_id not in by_report:
                by_report[report_id] = fetch_implementation_prs_for_reports([report_id], team_id=obj.team_id).get(
                    report_id, []
                )
        return by_report.get(str(obj.id), [])

    def _get_primary_pull_request(self, obj: SignalReport) -> "ImplementationPr | None":
        from products.signals.backend.implementation_pr import primary_pull_request

        prs = self._get_pull_requests(obj)
        return primary_pull_request(prs) if prs else None

    def get_implementation_pr_url(self, obj: SignalReport) -> str | None:
        pr = self._get_primary_pull_request(obj)
        return pr.url if pr else None

    @extend_schema_field(serializers.ChoiceField(choices=SignalReportAssignment.PrState.choices, allow_null=True))
    def get_implementation_pr_state(self, obj: SignalReport) -> str | None:
        pr = self._get_primary_pull_request(obj)
        return pr.state if pr else None

    def get_implementation_pr_merged(self, obj: SignalReport) -> bool:
        pr = self._get_primary_pull_request(obj)
        return pr.merged if pr else False

    @extend_schema_field(SignalReportPullRequestSerializer(many=True))
    def get_pull_requests(self, obj: SignalReport) -> list[dict[str, object]]:
        return cast(
            list[dict[str, object]], SignalReportPullRequestSerializer(self._get_pull_requests(obj), many=True).data
        )

    @staticmethod
    def _get_tracker_issue(obj: SignalReport) -> SignalReportTrackerIssue | None:
        # Reverse OneToOne: RelatedObjectDoesNotExist subclasses AttributeError, so getattr
        # degrades to None for reports with no tracker issue. The viewset select_related()s it.
        return getattr(obj, "tracker_issue", None)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_tracker_issue_url(self, obj: SignalReport) -> str | None:
        tracker = self._get_tracker_issue(obj)
        if tracker is None or tracker.status != SignalReportTrackerIssue.Status.CREATED:
            return None
        return tracker.issue_url or None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_tracker_issue_reference(self, obj: SignalReport) -> str | None:
        tracker = self._get_tracker_issue(obj)
        if tracker is None or tracker.status != SignalReportTrackerIssue.Status.CREATED:
            return None
        return issue_reference(tracker)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_tracker_issue_error(self, obj: SignalReport) -> str | None:
        tracker = self._get_tracker_issue(obj)
        if tracker is None or tracker.status != SignalReportTrackerIssue.Status.FAILED:
            return None
        return tracker.failure_reason or "Could not open the tracker issue."

    @extend_schema_field(serializers.ChoiceField(choices=SignalReportWorkState.choices))
    def get_work_state(self, obj: SignalReport) -> str:
        if obj.status == SignalReport.Status.RESOLVED:
            return "done"
        if any(pr.state in {"open", "draft", "unknown"} for pr in self._get_pull_requests(obj)):
            return "in_review"
        assignment = self._get_assignment(obj)
        return "working" if assignment is not None and assignment.actor_kind else "unclaimed"

    @extend_schema_field(SignalReportAssigneeSerializer(allow_null=True))
    def get_assignee(self, obj: SignalReport) -> dict | None:
        assignment = self._get_assignment(obj)
        if assignment is None or not assignment.actor_kind:
            return None
        return {
            "claim_id": str(assignment.claim_id) if assignment.claim_id else None,
            "kind": assignment.actor_kind,
            "user": _UserSerializer(assignment.actor_user).data if assignment.actor_user else None,
            "task_id": str(assignment.actor_task_id) if assignment.actor_task_id else None,
            "agent": assignment.actor_agent,
            "claimed_at": assignment.claimed_at,
        }

    def _get_assignment(self, obj: SignalReport) -> "ReportClaim | None":
        from products.signals.backend.report_claims import get_active_claim

        claims = self.context.setdefault("claims_map", {})
        report_id = str(obj.id)
        if report_id not in claims:
            claims[report_id] = get_active_claim(team_id=obj.team_id, report_id=report_id)
        return claims[report_id]

    @extend_schema_field(SignalReportRefundSerializer(allow_null=True))
    def get_refund(self, obj: SignalReport) -> dict | None:
        # Reverse OneToOne: RelatedObjectDoesNotExist subclasses AttributeError, so getattr
        # degrades to None for unrefunded reports. The viewset select_related()s the relation.
        refund = getattr(obj, "refund", None)
        if refund is None:
            return None
        return SignalReportRefundSerializer(refund).data

    @extend_schema_field(
        serializers.ChoiceField(
            choices=list(REFUND_INELIGIBILITY_REASONS),
            allow_null=True,
            help_text=(
                "Why refunding this report's PR would be rejected right now, or null when a refund "
                "would be accepted. Shares the refund endpoint's eligibility decision, so the UI can "
                "disable the Refund action instead of offering a request that would 400. One of: "
                "already_refunded, billing_exempt, no_billable_pr, out_of_period."
            ),
        )
    )
    def get_refund_ineligibility_reason(self, obj: SignalReport) -> str | None:
        period = self.context.get("billing_period_bounds")
        # Degrades to null (eligible) outside the reports viewset, where neither the period
        # context nor the billable-moment annotation exists — the refund endpoint re-enforces.
        if period is None:
            return None
        billable_run_at_map: dict[str, datetime] | None = self.context.get("first_billable_pr_run_at_map")
        if billable_run_at_map is not None:
            billable_run_at = billable_run_at_map.get(str(obj.id))
        else:
            billable_run_at = getattr(obj, "first_billable_pr_run_at", None)
        return refund_ineligibility_reason(
            has_refund=getattr(obj, "refund", None) is not None,
            billing_exempt=bool(obj.billing_exempt_reason),
            billable_run_at=billable_run_at,
            period=period,
        )


# ── Report `signals` action ─────────────────────────────────────────────────────
#
class SignalReportListSerializer(SignalReportSerializer):
    metrics = ReportMetricListSerializer(
        many=True,
        read_only=True,
        help_text=(
            "Snapshot-only impact measurements for inbox rows. Live query definitions and authored "
            "comparisons are available from the report detail endpoint."
        ),
    )


class SignalReportMetricRefreshRequestSerializer(serializers.Serializer):
    report_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=MAX_REPORT_METRIC_REFRESH_REPORTS,
        help_text=(
            "Reports on screen, in display order. Each report's row metric is refreshed before any "
            f"report's supporting metrics. At most {MAX_REPORT_METRIC_REFRESH_REPORTS} ids per call."
        ),
    )


class SignalReportMetricSnapshotsSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Report id.")
    metrics = ReportMetricListSerializer(
        many=True,
        read_only=True,
        help_text="The report's metrics with their current snapshots, in display order.",
    )


class SignalReportMetricRefreshResponseSerializer(serializers.Serializer):
    reports = SignalReportMetricSnapshotsSerializer(
        many=True,
        read_only=True,
        help_text=(
            "One entry per requested report the caller can read whose status is ready or "
            "pending_input, in request order. A report in any other status has no entry. A metric "
            "whose snapshot was fresh, whose query failed, or whose budget ran out keeps its "
            "previous snapshot; merge by metric_id."
        ),
    )


# A signal's `extra` blob is one of the Pydantic `*SignalExtra` shapes from `contracts.py`. Those
# models are passed straight to `PolymorphicProxySerializer` — drf-spectacular's built-in
# `PydanticExtension` turns each into a named OpenAPI component (nested models included), so the
# frontend types flow through the standard OpenAPI/Orval pipeline without re-declaring the shapes.

# All `extra` payload shapes. They're discriminated at runtime by the (source_product, source_type)
# pair on the signal row, not by a field inside `extra`, so the OpenAPI union carries no discriminator.
SIGNAL_EXTRA_MODELS = list(contracts.SignalExtraBase.__subclasses__())


@extend_schema_field(
    PolymorphicProxySerializer(
        component_name="SignalExtra",
        # drf-spectacular's built-in PydanticExtension resolves the Pydantic models at schema-build
        # time; the stubs only know about DRF serializers, hence the cast.
        serializers=cast(list, SIGNAL_EXTRA_MODELS),
        resource_type_field_name=None,
    )
)
class SignalExtraField(serializers.JSONField):
    """Product-specific `extra` payload — one of the *SignalExtra shapes."""


# Mirrors of the clustering dataclasses in `temporal/types.py` (SpecificityMetadata,
# MatchedMetadata, NoMatchMetadata). Those are plain dataclasses, which spectacular's
# PydanticExtension can't consume directly, so the shape is declared here as DRF serializers.


class SpecificityMetadataSerializer(serializers.Serializer):
    pr_title = serializers.CharField(help_text="Title of the PR the specificity gate evaluated.")
    specific_enough = serializers.BooleanField(help_text="Whether the report passed the PR-specificity gate.")
    reason = serializers.CharField(help_text="The gate's reasoning.")


class MatchedMetadataSerializer(serializers.Serializer):
    parent_signal_id = serializers.CharField(help_text="Signal already in the report that this one matched.")
    match_query = serializers.CharField(help_text="Query used to find the parent signal.")
    reason = serializers.CharField(help_text="Why the signals were judged to describe the same issue.")
    specificity = SpecificityMetadataSerializer(
        required=False, allow_null=True, help_text="PR-specificity gate result, when the gate ran."
    )


class NoMatchMetadataSerializer(serializers.Serializer):
    reason = serializers.CharField(help_text="Why no existing report matched.")
    rejected_signal_ids = serializers.ListField(
        child=serializers.CharField(), help_text="Candidate signals that were considered and rejected."
    )
    specificity_rejection = SpecificityMetadataSerializer(
        required=False, allow_null=True, help_text="PR-specificity gate result that caused a rejection, when present."
    )


@extend_schema_field(
    PolymorphicProxySerializer(
        component_name="SignalMatchMetadata",
        serializers=[MatchedMetadataSerializer, NoMatchMetadataSerializer],
        resource_type_field_name=None,
    )
)
class SignalMatchMetadataField(serializers.JSONField):
    """Why the signal matched (or didn't) into its report cluster."""


class SignalNodeSerializer(serializers.Serializer):
    signal_id = serializers.CharField(help_text="ClickHouse document id of the signal.")
    content = serializers.CharField(help_text="The signal's human-readable description.")
    source_product = serializers.ChoiceField(
        choices=[(p.value, p.value) for p in SignalSourceProduct],
        help_text="Product that emitted the signal.",
    )
    source_type = serializers.ChoiceField(
        choices=[(t.value, t.value) for t in SignalSourceType],
        help_text="Signal type within the source product.",
    )
    source_id = serializers.CharField(help_text="Emitter-scoped id of the underlying object (issue, ticket, ...).")
    weight = serializers.FloatField(help_text="Signal weight in [0, 1]; drives report ranking.")
    timestamp = serializers.DateTimeField(help_text="Emission timestamp.")
    extra = SignalExtraField(help_text="Product-specific payload; shape depends on (source_product, source_type).")
    match_metadata = SignalMatchMetadataField(
        required=False,
        allow_null=True,
        help_text="Clustering match/no-match metadata, when present.",
    )


class ReportSignalsResponseSerializer(serializers.Serializer):
    """Response body for GET /api/projects/:id/signals/reports/:id/signals/."""

    report = SignalReportSerializer(help_text="The report these signals were clustered into.")
    signals = SignalNodeSerializer(many=True, help_text="All signals contributing to the report.")


class SignalReportArtefactSerializer(serializers.ModelSerializer):
    claim_id = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="Work claim that produced this artefact."
    )
    pull_request_id = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="Shared PR record linked by this artefact."
    )
    content = serializers.SerializerMethodField()
    created_by = _UserSerializer(
        read_only=True,
        allow_null=True,
        help_text=(
            "Authenticated user principal for user or external agent writes. Null for internal task and system writes."
        ),
    )
    task_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="Internal task the artefact is attributed to. Null for user, external agent, and system writes.",
    )
    actor_kind = serializers.SerializerMethodField(
        help_text="Actor kind. Legacy rows without attribution are returned as system.",
    )
    actor_agent = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="MCP client name when an external agent produced the artefact.",
    )

    class Meta:
        model = SignalReportArtefact
        fields = [
            "claim_id",
            "pull_request_id",
            "id",
            "type",
            "content",
            "created_at",
            "updated_at",
            "actor_kind",
            "actor_agent",
            "created_by",
            "task_id",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ChoiceField(choices=SignalActorKind.choices))
    def get_actor_kind(self, obj: SignalReportArtefact) -> str:
        return obj.actor_kind or SignalActorKind.SYSTEM

    def get_content(self, obj: SignalReportArtefact) -> dict | list:
        try:
            parsed = json.loads(obj.content)
        except (json.JSONDecodeError, ValueError):
            return {}

        # Enrich suggested_reviewers with fresh PostHog user info at read time
        if obj.type == SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS and isinstance(parsed, list):
            reviewer_login_map = cast(
                Mapping[str, User] | None,
                self.context.get("signals_github_login_to_user_map"),
            )
            reviewer_uuid_map = cast(
                Mapping[str, User] | None,
                self.context.get("signals_reviewer_user_uuid_map"),
            )
            return enrich_reviewer_dicts_with_org_members(
                obj.team_id,
                parsed,
                login_to_user=reviewer_login_map,
                uuid_to_user=reviewer_uuid_map,
            )

        return parsed


class SuggestedReviewerEntryWriteSerializer(serializers.Serializer):
    """Single entry in a PUT body for a `suggested_reviewers` artefact.

    Each entry must identify a reviewer by at least one of `github_login` or `user_uuid`. A
    `user_uuid` only has to name an org member on this team — a member with no linked GitHub
    account is stored by uuid and routes like any other reviewer.
    """

    github_login = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=200,
        help_text="GitHub login (case-insensitive). Stored lowercased.",
    )
    user_uuid = serializers.UUIDField(
        required=False,
        help_text=(
            "PostHog user UUID. Must be an org member on this team; a linked GitHub account is not "
            "required. If supplied together with `github_login`, the user's own identity wins."
        ),
    )
    github_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text="Optional human-readable display name. Not backfilled from GitHub by the server.",
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=500,
        help_text=(
            "Optional short evidence for why this reviewer was chosen. Omitted entries keep the "
            "prior reason for reviewers already on the report."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        if not attrs.get("github_login") and not attrs.get("user_uuid"):
            raise serializers.ValidationError("Each entry must include `github_login` or `user_uuid` (or both).")
        return attrs


class SignalReportArtefactWriteSerializer(serializers.Serializer):
    """PUT body for replacing a `suggested_reviewers` artefact's content.

    Only `suggested_reviewers` artefacts may be modified via this endpoint;
    the viewset enforces the type check before validation runs.
    """

    MAX_ENTRIES = 10

    content = SuggestedReviewerEntryWriteSerializer(
        many=True,
        allow_empty=True,
        help_text=(
            f"Full replacement list of reviewers. Empty list clears the artefact. At most {MAX_ENTRIES} entries."
        ),
    )

    def validate_content(self, value: list[dict]) -> list[dict]:
        if len(value) > self.MAX_ENTRIES:
            raise serializers.ValidationError(f"At most {self.MAX_ENTRIES} reviewers may be supplied.")
        return value


# Writable types only — `video_segment` (and any other NON_WRITABLE type) is read-only and rejected
# by the write API, so it must not be advertised as an option here.
_WRITABLE_ARTEFACT_TYPES = sorted(set(SignalReportArtefact.ArtefactType.values) - NON_WRITABLE_ARTEFACT_TYPES)

_ARTEFACT_TYPES_HELP = (
    "The artefact type. One of: "
    + ", ".join(_WRITABLE_ARTEFACT_TYPES)
    + ". Log types accumulate; status types (safety_judgment, actionability_judgment, "
    "priority_judgment, repo_selection, suggested_reviewers, channel_assignment) are latest-wins — appending a new "
    "version supersedes the previous one as the report's canonical status."
)


def _validate_artefact_content_is_container(value: object) -> dict | list:
    if not isinstance(value, dict | list):
        raise serializers.ValidationError("content must be a JSON object or array.")
    return value


class SignalReportArtefactLogCreateSerializer(serializers.Serializer):
    """Body for appending an artefact to a report.

    Everything is append-only: log artefacts accumulate, status artefacts supersede the previous
    version (latest-wins). The `content` shape depends on `artefact_type` and is validated
    against the type's schema (see `products/signals/backend/artefact_schemas.py`).
    """

    # Plain CharField (not ChoiceField) on purpose: the value is validated against
    # `ArtefactType.values` in the view, and avoiding a `choices=` enum keeps this off the
    # collision-prone enum-name path in the generated OpenAPI types.
    claim_id = serializers.UUIDField(
        required=False, help_text="Active claim to attribute this work to. Must belong to the caller and report."
    )
    artefact_type = serializers.CharField(help_text=_ARTEFACT_TYPES_HELP)
    content = serializers.JSONField(
        help_text="The artefact payload as a JSON object or array; shape depends on artefact_type "
        "and is validated against its schema.",
    )

    def validate_content(self, value: object) -> dict | list:
        # Shape-only here: the view is the schema boundary — it parses the payload into the
        # type's content model (after normalizing task_run defaults) and 400s on a mismatch.
        return _validate_artefact_content_is_container(value)


class SignalReportArtefactLogUpdateSerializer(serializers.Serializer):
    """Body for replacing the content of an existing artefact (addressed by id).

    Per-type schema validation happens in the view, which knows the artefact's type.
    """

    content = serializers.JSONField(
        help_text="The new artefact payload as a JSON object or array, matching the artefact type's schema."
    )

    def validate_content(self, value: object) -> dict | list:
        return _validate_artefact_content_is_container(value)


class SignalReportArtefactWriteResponseSerializer(serializers.Serializer):
    """Response shape for the log-artefact create/update endpoints — echoes the stored row."""

    id = serializers.UUIDField(read_only=True, help_text="The artefact's unique id.")
    claim_id = serializers.UUIDField(read_only=True, allow_null=True, help_text="Claim that produced this artefact.")
    report_id = serializers.UUIDField(read_only=True, help_text="The id of the report this artefact belongs to.")
    # Plain CharField (no `choices=`) to keep the model's full ArtefactType enum out of the
    # generated OpenAPI schema; the value is simply echoed back.
    type = serializers.CharField(read_only=True, help_text="The artefact type.")
    content = serializers.JSONField(read_only=True, help_text="The artefact payload, parsed from storage.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the artefact was created.")
    updated_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the artefact was last written — set on creation and refreshed on each edit. "
        "Null only for rows created before this field existed.",
    )
    task_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="Task the artefact is attributed to, when an agent produced it. Null for user writes.",
    )


class CommitDiffResponseSerializer(serializers.Serializer):
    """Response for the `commit` artefact diff endpoint — the commit's branch rendered against the
    repository default branch."""

    diff = serializers.CharField(
        read_only=True,
        help_text="Unified diff (patch) text of the branch against the repository default branch, "
        "from the GitHub compare API.",
    )
    truncated = serializers.BooleanField(
        read_only=True,
        help_text="True when the diff was too large to return in full and has been truncated.",
    )


class PullRequestCheckSerializer(serializers.Serializer):
    """One CI check on a pull request's head commit — a GitHub Actions check run or a legacy commit
    status, normalized to a common shape."""

    name = serializers.CharField(read_only=True, help_text="Check run name or status context.")
    status = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Lifecycle state: 'queued', 'in_progress', or 'completed'.",
    )
    conclusion = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Outcome once completed: 'success', 'failure', 'neutral', 'cancelled', 'skipped', "
        "'timed_out', or 'action_required'. Null while still running.",
    )
    url = serializers.CharField(
        read_only=True, allow_null=True, help_text="Link to the check run / status detail on GitHub."
    )


class PullRequestChecksResponseSerializer(serializers.Serializer):
    """Response for the PR checks endpoint — the CI status of a report's implementation PR."""

    checks = PullRequestCheckSerializer(many=True, read_only=True)


class PullRequestCiStatus(TextChoices):
    """Coarse rollup of a pull request's checks, as mapped from GitHub's status check rollup."""

    PASSING = "passing", "Passing"
    FAILING = "failing", "Failing"
    PENDING = "pending", "Pending"
    NONE = "none", "No checks"


class PullRequestCiStatusSerializer(serializers.Serializer):
    """The CI rollup of one report's implementation pull request."""

    report_id = serializers.UUIDField(
        read_only=True, help_text="Report whose implementation pull request this status describes."
    )
    ci_status = serializers.ChoiceField(
        read_only=True,
        choices=PullRequestCiStatus.choices,
        help_text="Rollup of the pull request's checks on its head commit: 'passing' (nothing failed), "
        "'failing', 'pending' (checks are still running), or 'none' (the head commit has no checks).",
    )


class PullRequestCiStatusesResponseSerializer(serializers.Serializer):
    """Response for the batch PR CI status endpoint, for painting CI state onto a list of reports."""

    statuses = PullRequestCiStatusSerializer(
        many=True,
        read_only=True,
        help_text="One entry per requested report whose CI state resolved. Reports without an open "
        "implementation pull request, and reports GitHub could not answer for, are left out.",
    )


class PullRequestCommentReactionSerializer(serializers.Serializer):
    """One emoji reaction on a review comment, with the reactor so the viewer's own can be toggled."""

    id = serializers.CharField(read_only=True, help_text="GitHub reaction id (needed to remove it).")
    content = serializers.CharField(
        read_only=True,
        help_text="Reaction key: '+1', '-1', 'laugh', 'hooray', 'confused', 'heart', 'rocket', or 'eyes'.",
    )
    user_login = serializers.CharField(
        read_only=True, allow_null=True, help_text="GitHub login of the user who added the reaction."
    )


class PullRequestCommentSerializer(serializers.Serializer):
    """One comment on a pull request — a conversation comment or an inline review comment."""

    id = serializers.CharField(read_only=True, help_text="GitHub comment id.")
    author = serializers.CharField(read_only=True, allow_null=True, help_text="Comment author's GitHub login.")
    author_avatar_url = serializers.CharField(read_only=True, allow_null=True, help_text="Author's GitHub avatar URL.")
    body = serializers.CharField(read_only=True, allow_blank=True, help_text="Comment body (GitHub-flavored markdown).")
    created_at = serializers.CharField(read_only=True, allow_null=True, help_text="ISO 8601 creation timestamp.")
    url = serializers.CharField(read_only=True, allow_null=True, help_text="Link to the comment on GitHub.")
    comment_type = serializers.ChoiceField(
        read_only=True,
        choices=["conversation", "review"],
        help_text="'conversation' for a PR discussion comment, 'review' for an inline code-review comment.",
    )
    path = serializers.CharField(
        read_only=True, allow_null=True, help_text="File path the review comment is anchored to (review comments only)."
    )
    line = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="Line in the diff the review comment is anchored to — the end line for multi-line comments "
        "(review comments only; null when the comment is outdated relative to the PR head).",
    )
    start_line = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="First line of a multi-line review comment's range (review comments only).",
    )
    side = serializers.ChoiceField(
        read_only=True,
        allow_null=True,
        choices=["LEFT", "RIGHT"],
        help_text="Diff side the review comment is anchored to: 'LEFT' = deletions, 'RIGHT' = additions "
        "(review comments only).",
    )
    diff_hunk = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Diff hunk excerpt the review comment applies to (review comments only).",
    )
    in_reply_to_id = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Id of the thread root comment this one replies to; null for thread roots and conversation comments.",
    )
    commit_id = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="SHA of the commit the review comment was made against (review comments only).",
    )
    reactions = PullRequestCommentReactionSerializer(
        many=True,
        read_only=True,
        help_text="Emoji reactions on this review comment, one entry per reactor.",
    )


class PullRequestCommentsResponseSerializer(serializers.Serializer):
    """Response for the PR comments endpoint — conversation and review comments merged chronologically."""

    comments = PullRequestCommentSerializer(many=True, read_only=True)


class PullRequestReviewCommentCreateSerializer(serializers.Serializer):
    """Request body for posting an inline PR review comment as the requesting user.

    Two shapes: a reply to an existing thread (only `body` + `in_reply_to`), or a new
    thread on a diff line (`body` + `path` + `line`, optionally `side`)."""

    body = serializers.CharField(help_text="Comment body (GitHub-flavored markdown).", max_length=65536)
    # Numeric-only: this id is interpolated into the GitHub reply URL, so an unconstrained string could
    # smuggle path segments (e.g. `../../issues/1/comments`) and retarget the request.
    in_reply_to = serializers.RegexField(
        r"^[0-9]+$",
        required=False,
        allow_null=True,
        help_text="Numeric id of the thread root comment to reply to. When set, path/line/side are ignored.",
    )
    path = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="File path to anchor a new comment thread to (required when starting a new thread).",
    )
    line = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="Diff line to anchor a new comment thread to (required when starting a new thread).",
    )
    side = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=["LEFT", "RIGHT"],
        help_text="Diff side of the anchor line: 'LEFT' = deletions, 'RIGHT' = additions. Defaults to 'RIGHT'.",
    )

    def validate(self, attrs: dict) -> dict:
        if not attrs.get("in_reply_to") and not (attrs.get("path") and attrs.get("line")):
            raise serializers.ValidationError("Provide either in_reply_to (reply) or path + line (new thread).")
        return attrs


class PullRequestReviewCommentCreateResponseSerializer(serializers.Serializer):
    """Response after posting a review comment — the created comment in the normalized PR-comment shape."""

    comment = PullRequestCommentSerializer(read_only=True)


class PullRequestReviewCommentUpdateSerializer(serializers.Serializer):
    """Request body for editing a review comment's markdown body."""

    body = serializers.CharField(help_text="New comment body (GitHub-flavored markdown).", max_length=65536)


_REACTION_CONTENTS = ["+1", "-1", "laugh", "hooray", "confused", "heart", "rocket", "eyes"]


class PullRequestReviewCommentReactionCreateSerializer(serializers.Serializer):
    """Request body for adding an emoji reaction to a review comment."""

    content = serializers.ChoiceField(
        choices=_REACTION_CONTENTS,
        help_text="Reaction to add: one of '+1', '-1', 'laugh', 'hooray', 'confused', 'heart', 'rocket', 'eyes'.",
    )


class PullRequestReviewCommentReactionCreateResponseSerializer(serializers.Serializer):
    """Response after adding a reaction — the created reaction, so the frontend can track its id."""

    reaction = PullRequestCommentReactionSerializer(read_only=True)
