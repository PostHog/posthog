import json
import uuid
import dataclasses
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from django.db.models import Prefetch, TextChoices
from django.utils import timezone

import structlog
from drf_spectacular.extensions import OpenApiSerializerExtension
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework.request import Request

from posthog.api.fields import RepeatedOrCommaSeparatedListField
from posthog.auth import is_mcp_request
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.integrations import IntegrationKind, IntegrationRecord
from posthog.integrations.fields import IntegrationReferenceField
from posthog.models import Team, User
from posthog.models.integration import SUPPORTED_EXTERNAL_ISSUE_PROVIDERS

from products.signals.backend import contracts
from products.signals.backend.agent_instructions import AGENT_STEERING_MAX_LENGTH, STEERING_FIELDS
from products.signals.backend.anomaly_scores.config import covers_team, parse_config, read_payload
from products.signals.backend.billing import REFUND_INELIGIBILITY_REASONS, refund_ineligibility_reason
from products.signals.backend.contracts import (
    DEFAULT_NOT_ACTIONABLE_KEY,
    SCOPE_CONFIG_KEYS,
    STEERING_KEY,
    STEERING_MAX_LENGTH,
    scope_ids_problem,
)
from products.signals.backend.enums import (
    ReportTaskActionKind,
    ReviewerEditAction,
    ReviewerRemovalReason,
    ReviewerSelectionOutcome,
    SignalSourceProduct,
    SignalSourceType,
    SuggestedSourceProduct,
)
from products.signals.backend.report_check_monitoring_timing import MonitoringCheckTiming, MonitoringCheckTimingState
from products.signals.backend.report_checks import (
    CHECK_CONFIG_SCHEMAS,
    DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN,
    DEFAULT_FIRST_RUN_AFTER,
    MAX_CHECK_HORIZON,
    MAX_CHECK_INTERVAL_MINUTES,
    MAX_CHECK_RATIONALE_LENGTH,
    MAX_CHECK_RUNS,
    MAX_CHECK_TITLE_LENGTH,
    MIN_CHECK_INTERVAL_MINUTES,
    CheckConfigValidationError,
    MetricThresholdConfig,
    parse_check_config,
)
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.reviewer_rules import ReviewerRules
from products.signals.backend.scout_harness.tools.report import is_self_improvement_title
from products.warehouse_sources.backend.facade.models import ExternalDataSchema
from products.warehouse_sources.backend.facade.types import ExternalDataSchemaStatus

if TYPE_CHECKING:
    from drf_spectacular.openapi import AutoSchema
    from drf_spectacular.utils import Direction

    from products.signals.backend.implementation_pr import ImplementationPr
    from products.signals.backend.personal_ranking.serve import ServedRanking
    from products.signals.backend.report_claims import ReportClaim
    from products.signals.backend.report_plan import ReportPlan, ReportPlanStep

from .artefact_schemas import NON_WRITABLE_ARTEFACT_TYPES, ActionabilityChoice, SourceSuggestion, priority_from_judgment
from .briefing_reports import SUMMARY_LEAD_LIMIT, summary_lead
from .daily_limit import reports_generated_today, team_day_start
from .implementation_repositories import (
    MAX_IMPLEMENTATION_REPOSITORIES,
    InvalidImplementationRepository,
    normalize_implementation_repositories,
    repositories_missing_from_installations,
)
from .models import (
    GITHUB_LABEL_NAME_MAX_LENGTH,
    MAX_SCOUT_REPORT_NOTES,
    AutonomyPriority,
    SignalActorKind,
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportCheck,
    SignalReportPullRequest,
    SignalReportRefund,
    SignalReportSuppressionSource,
    SignalReportTrackerIssue,
    SignalReportWorkState,
    SignalSourceConfig,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from .pull_request_label import DEFAULT_PULL_REQUEST_LABEL
from .ranking.inbox_sort import inbox_merge_key
from .ranking.public_outcomes import RankingOutcome
from .ranking.report_predictions import ReportPredictions, read_report_predictions
from .ranking.staleness import EDIT_ARTEFACT_TYPES
from .report_charts import CHART_SIZES, MAX_CHART_CAPTION_LENGTH, MAX_CHART_ID_LENGTH, MAX_CHART_TITLE_LENGTH
from .report_generation.resolve_reviewers import enrich_reviewer_dicts_with_org_members, trusted_manual_reviewer_adders
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

logger = structlog.get_logger(__name__)

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
    "session analysis. "
    "The Linear issue source (`source_product=linear`, `source_type=issue`) reads "
    "`linear_team_ids` (list of Linear team id strings, max 100): the warehouse still syncs the "
    "whole Linear workspace, but only issues from those teams become signals. Omit the key or "
    "pass an empty list to use every team. Get the ids from the Linear integration's teams endpoint."
)


# Declared as an open object WITHOUT typed `properties`: Orval turns properties into a
# key-stripping `zod.object`, which would silently drop source-specific keys (e.g. session
# replay's `recording_filters`) from MCP tool calls. The open shape generates a passthrough
# `zod.record`, and the steering keys are documented in the description instead.
@extend_schema_field({"type": "object", "additionalProperties": True, "description": _SOURCE_CONFIG_HELP_TEXT})
class _SourceConfigField(serializers.JSONField):
    """`config` blob typed as an open JSON object in the OpenAPI schema. Runtime behavior is
    plain JSONField; steering-key validation stays in the serializer's `validate`."""


# The three states get_status maps the warehouse import's status down to. Declared so the generated
# client narrows to them rather than to a bare string, which is what the frontend already does by
# hand. `status` is too generic a field name for drf-spectacular to name a set on its own, so the
# name comes from ENUM_NAME_OVERRIDES.
SIGNAL_SOURCE_CONFIG_STATUSES = ["running", "completed", "failed"]


class SignalSourceConfigSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField(
        help_text=(
            "Sync state of the warehouse import behind this source: `running`, `failed`, or "
            "`completed`. Null for a source that imports nothing from the warehouse, for an "
            "import that has never synced, and when the sync state could not be read."
        ),
    )
    config = _SourceConfigField(required=False, help_text=_SOURCE_CONFIG_HELP_TEXT)
    config_set = _SourceConfigField(
        required=False,
        write_only=True,
        help_text="Top-level config keys to set atomically on update. Unspecified keys are preserved. Cannot be combined with config.",
    )
    config_remove = serializers.ListField(
        child=serializers.CharField(trim_whitespace=False, allow_blank=False),
        required=False,
        write_only=True,
        help_text="Top-level config keys to remove atomically on update. Missing keys are ignored. Cannot overlap config_set or be combined with config.",
    )

    class Meta:
        model = SignalSourceConfig
        fields = [
            "id",
            "source_product",
            "source_type",
            "enabled",
            "config",
            "config_set",
            "config_remove",
            "created_at",
            "updated_at",
            "status",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "status"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Absent key means "not read yet", a `None` value means the read failed.
        self._data_import_statuses_by_team: dict[int, dict[_DataImportSchema, set[str]] | None] = {}

    @extend_schema_field(serializers.ChoiceField(choices=SIGNAL_SOURCE_CONFIG_STATUSES, allow_null=True))
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
        if "config_set" in attrs or "config_remove" in attrs:
            if self.instance is None:
                raise serializers.ValidationError("config_set and config_remove are only supported on update.")
            if "config" in attrs:
                raise serializers.ValidationError("Use either config or config_set/config_remove.")
            config_set = attrs.pop("config_set", {})
            config_remove = attrs.pop("config_remove", [])
            if not isinstance(config_set, dict):
                raise serializers.ValidationError({"config_set": "config_set must be a JSON object"})
            if set(config_set).intersection(config_remove):
                raise serializers.ValidationError("A config key cannot be both set and removed.")
            merged_config = {**self.instance.config, **config_set}
            for key in config_remove:
                merged_config.pop(key, None)
            attrs["config"] = merged_config
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
            scope_key = SCOPE_CONFIG_KEYS.get((source_product, source_type)) if source_product and source_type else None
            if scope_key is not None and scope_key in config:
                problem = scope_ids_problem(config[scope_key])
                if problem is not None:
                    raise serializers.ValidationError({"config": f"{scope_key} {problem}"})
                # Stored stripped: emission matches these ids exactly, so a pasted id with a
                # stray space would select a scope and then read nothing.
                config[scope_key] = [scope_id.strip() for scope_id in config[scope_key]]
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


_AUTOSTART_BASE_BRANCHES_HELP = (
    "Per-repository base branch overrides for auto-started inbox PRs, keyed by "
    "'organization/repository'. The branch is what the auto-PR targets; omit a repo "
    "(or send {}) to keep targeting the repo default branch."
)

# The validator below bounds the key count, the key shape and the key length. A DictField publishes
# only the value constraint, so the key rules are declared here to keep the schema and the validator
# saying the same thing.
_AUTOSTART_BASE_BRANCHES_SCHEMA = {
    "type": "object",
    "description": _AUTOSTART_BASE_BRANCHES_HELP,
    "maxProperties": MAX_AUTOSTART_BASE_BRANCH_ENTRIES,
    "propertyNames": {"pattern": "^[^/]+/[^/]+$", "maxLength": 255},
    "additionalProperties": {"type": "string", "maxLength": 255},
}


@extend_schema_field(_AUTOSTART_BASE_BRANCHES_SCHEMA)
class _AutostartBaseBranchesField(serializers.DictField):
    pass


# many=False: the read action is named `list` for routing, but the config is a per-project
# singleton. Without this drf-spectacular types the response as a paginated list.
@extend_schema_serializer(many=False)
class SignalTeamConfigSerializer(serializers.ModelSerializer):
    scout_instructions = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=AGENT_STEERING_MAX_LENGTH,
        help_text="Project-level instructions added to every scout run, alongside project instructions and the scout's own brief. Blank uses project instructions only.",
    )
    research_instructions = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=AGENT_STEERING_MAX_LENGTH,
        help_text="Project-level instructions for the dedicated signal report research stage. Other agent roles do not receive them. Blank uses project instructions only.",
    )
    implementation_instructions = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=AGENT_STEERING_MAX_LENGTH,
        help_text="Project-level instructions for agents implementing signal reports. Other agent roles do not receive them. Blank uses project instructions only.",
    )
    issue_tracking_integration = IntegrationReferenceField(
        kinds=sorted(SUPPORTED_EXTERNAL_ISSUE_PROVIDERS),
        required=False,
        allow_null=True,
        help_text=(
            "Connected GitHub, GitLab, Linear, or Jira integration that self-driving opens a tracker "
            "issue in for each pull request it makes. Null turns tracker issues off, which is the "
            "default."
        ),
    )
    default_slack_notification_integration = IntegrationReferenceField(
        kinds=["slack"],
        auth_types="any",
        source="default_slack_notification_integration_id",
        required=False,
        allow_null=True,
        help_text=(
            "Connected Slack integration that owns `default_slack_notification_channel`. Send it together "
            "with the channel. A channel saved without it is routed through the team's oldest Slack "
            "integration, and clearing the channel clears this too."
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
    autostart_base_branches = _AutostartBaseBranchesField(
        child=serializers.CharField(max_length=255, allow_blank=True),
        required=False,
        help_text=_AUTOSTART_BASE_BRANCHES_HELP,
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
    github_issue_writeback_enabled = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether self-driving comments back on a GitHub issue that raised a report, linking to "
            "the report so everybody watching the issue knows it is being researched. The comment is "
            "public on the issue thread and carries a link only, never report content. False by "
            "default. Needs a GitHub integration that can reach the issue's repository."
        ),
    )
    pull_request_label_enabled = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether self-driving adds a label to every pull request it opens, so GitHub search, "
            "saved searches, and notification rules can separate them from other automation on the "
            "repository. False by default. Needs a GitHub integration that can reach the repository."
        ),
    )
    pull_request_label = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=GITHUB_LABEL_NAME_MAX_LENGTH,
        help_text=(
            f"The label name self-driving applies, at most {GITHUB_LABEL_NAME_MAX_LENGTH} characters. "
            f"Null or blank means '{DEFAULT_PULL_REQUEST_LABEL}'. The label is created in the repository "
            "when it does not exist yet. Only used while pull_request_label_enabled is true."
        ),
    )
    implementation_repositories = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        max_length=MAX_IMPLEMENTATION_REPOSITORIES,
        help_text=(
            "Extra GitHub repositories, as 'organization/repository', that self-driving implementation "
            "tasks can read and write within the connected GitHub App's permissions, for example an "
            "assets repository for PR screenshots. A task gets only the entries with the same owner as "
            "its selected repository. They are not cloned, and the PR still targets the selected "
            "repository. Each new entry must be reachable through one of the project's GitHub "
            "installations. Changes apply to tasks started afterwards. Empty by default."
        ),
    )
    anomaly_scoring_enabled = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether anomaly scoring scores this project's active trends insights every hour and writes "
            "the results as $anomaly_score events, which are not billed. True by default. Set false to "
            "stop new scores; events written before stay. Turning it on does not enroll a project that "
            "anomaly_scoring_available reports as not covered."
        ),
    )
    anomaly_scoring_available = serializers.SerializerMethodField(
        help_text=(
            "Whether anomaly scoring covers this project, so anomaly_scoring_enabled has an effect. "
            "PostHog decides which projects anomaly scoring covers."
        )
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

    def to_representation(self, instance: SignalTeamConfig) -> dict[str, object]:
        representation = dict(super().to_representation(instance))
        for field in STEERING_FIELDS.values():
            representation[field] = representation[field] or ""
        return representation

    def validate_implementation_repositories(self, value: list[str]) -> list[str]:
        try:
            repositories = normalize_implementation_repositories(value)
        except InvalidImplementationRepository as error:
            raise serializers.ValidationError(str(error))
        # Entries already stored passed this check when they were added, so removing one never
        # waits on GitHub.
        stored = set(getattr(self.instance, "implementation_repositories", None) or [])
        added = [repository for repository in repositories if repository not in stored]
        team_id = self.instance.team_id if self.instance is not None else self.context["get_team"]().id
        missing = repositories_missing_from_installations(team_id, added)
        if missing:
            raise serializers.ValidationError(
                f"The project's GitHub connection can't reach {', '.join(missing)}. "
                "Give the PostHog GitHub App access to it in your GitHub installation settings, then try again."
            )
        return repositories

    def validate_pull_request_label(self, value: str | None) -> str | None:
        # One stored shape for "use the default", so a team that clears the box does not get a
        # label GitHub would refuse.
        return (value or "").strip() or None

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
    def get_anomaly_scoring_available(self, obj: SignalTeamConfig) -> bool:
        return covers_team(parse_config(read_payload()), obj.team)

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
            "default_slack_notification_integration",
            "autostart_base_branches",
            "scout_instructions",
            "research_instructions",
            "implementation_instructions",
            "issue_tracking_integration",
            "issue_tracking_config",
            "max_reports_per_day",
            "default_open_pull_request_ready",
            "github_issue_writeback_enabled",
            "pull_request_label_enabled",
            "pull_request_label",
            "implementation_repositories",
            "anomaly_scoring_enabled",
            "anomaly_scoring_available",
            "reports_generated_today",
            "daily_report_limit_reached",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "anomaly_scoring_available",
            "reports_generated_today",
            "daily_report_limit_reached",
            "created_at",
            "updated_at",
        ]
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

    def validate_default_slack_notification_integration(self, value: IntegrationRecord | None) -> int | None:
        return value.id if value is not None else None

    def validate(self, attrs: dict) -> dict:
        attrs = super().validate(attrs)
        # A new channel without its workspace must not keep the old binding, which may name a
        # workspace that cannot see the new channel.
        if "default_slack_notification_channel" in attrs and (
            not attrs["default_slack_notification_channel"] or "default_slack_notification_integration_id" not in attrs
        ):
            attrs["default_slack_notification_integration_id"] = None
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
        if integration.kind == IntegrationKind.GITHUB:
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
    review_decision = serializers.ChoiceField(
        choices=SignalReportPullRequest.ReviewDecision.choices,
        allow_null=True,
        help_text=(
            "Current GitHub code review decision: approved, changes_requested, or review_required. "
            "Null when GitHub does not provide a review decision."
        ),
    )
    merged_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When GitHub reports that this pull request merged. Null when it has not merged or the time is unavailable.",
    )
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
    takeover_claim_id = serializers.UUIDField(
        required=False,
        help_text=(
            "With takeover, the claim the caller expects to replace. The takeover is rejected when a different "
            "claim is active, so a takeover based on a stale read cannot replace a newer claim."
        ),
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
        if attrs.get("takeover_claim_id") and not attrs.get("takeover"):
            raise serializers.ValidationError("takeover_claim_id requires takeover.")
        return attrs


class SignalReportAssigneeSerializer(serializers.Serializer):
    claim_id = serializers.UUIDField(allow_null=True, help_text="Identifier for the active work attempt.")
    kind = serializers.ChoiceField(choices=SignalActorKind.choices)
    user = _UserSerializer(allow_null=True)
    task_id = serializers.UUIDField(allow_null=True)
    agent = serializers.CharField(allow_null=True)
    claimed_at = serializers.DateTimeField(allow_null=True)
    responsible_user = _UserSerializer(
        allow_null=True,
        help_text=(
            "The person who answers for the claim: the user for a user claim, the user an MCP agent acts for, or "
            "the user who started an internal task. Null when no person stands behind the claim."
        ),
    )


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


def report_metric_access_policy(context: dict) -> ReportMetricAccessPolicy:
    """The viewer's policy for this request, built once per serializer context.

    Report metrics, check configs, and check results all carry data materialized without a viewer,
    so every one of them is gated by the same policy rather than by three readings of "who may see a
    query and its value".
    """
    context_key = "_report_metric_access_policy"
    cached = context.get(context_key)
    if isinstance(cached, ReportMetricAccessPolicy):
        return cached

    request = context.get("request")
    get_team = context.get("get_team")
    team = get_team() if callable(get_team) else None
    policy = ReportMetricAccessPolicy(
        request=request if isinstance(request, Request) else None,
        team=team if isinstance(team, Team) else None,
    )
    context[context_key] = policy
    return policy


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
    goal_value = _MetricFloatField(
        allow_null=True,
        required=False,
        default=None,
        help_text="Proposed threshold after release. Informational only; does not schedule a check.",
    )
    goal_direction = serializers.ChoiceField(
        choices=("at_most", "at_least"),
        allow_null=True,
        required=False,
        default=None,
        help_text="Whether success means at most or at least goal_value.",
    )
    goal_grain = serializers.ChoiceField(
        choices=("whole_window", "per_interval"),
        required=False,
        default="whole_window",
        help_text="Whether the goal compares with the whole query window or each chart bucket.",
    )
    decision_window_days = serializers.IntegerField(
        min_value=1,
        max_value=30,
        allow_null=True,
        required=False,
        default=None,
        help_text="Suggested days after release before assessing impact, not a monitoring schedule.",
    )
    minimum_data_points = serializers.IntegerField(
        min_value=1,
        max_value=1000,
        allow_null=True,
        required=False,
        default=None,
        help_text="Optional number of qualifying observations before assessing impact.",
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
        return report_metric_access_policy(self.context)


class ReportMetricWriteSerializer(ReportMetricSerializer):
    """Authoring shape: unlike a read response, the live query cannot be absent or redacted."""

    query = ChartQueryField(help_text=_REPORT_METRIC_QUERY_HELP)
    comparison = ReportMetricComparisonSerializer(
        allow_null=True,
        required=False,
        default=None,
        help_text="Legacy optional comparison. New report metrics must omit it.",
    )
    # Proposed goals live in follow-up checks, so the metric authoring schema must not advertise them.
    goal_value = None  # type: ignore[assignment]
    goal_direction = None  # type: ignore[assignment]
    goal_grain = None  # type: ignore[assignment]
    decision_window_days = None  # type: ignore[assignment]
    minimum_data_points = None  # type: ignore[assignment]

    def to_internal_value(self, data: object) -> dict[str, object]:
        # DRF ignores undeclared keys, so check the raw payload to keep the rejection explicit.
        # `goal_grain` stays out of this check: an older client fills its schema default on every metric.
        if isinstance(data, Mapping) and any(
            data.get(field) is not None
            for field in ("goal_value", "goal_direction", "decision_window_days", "minimum_data_points")
        ):
            raise serializers.ValidationError("Write proposed goals as follow-up checks, not report metrics.")
        return super().to_internal_value(data)


class ReportMetricListSerializer(ReportMetricSerializer):
    """Snapshot-only metric shape for report lists.

    Omitting query definitions keeps the paginated inbox payload bounded.
    """

    query = None  # type: ignore[assignment]  # removes the inherited field from the list projection


class ReportSourceSuggestionSerializer(serializers.Serializer):
    product = serializers.ChoiceField(
        choices=SuggestedSourceProduct.choices,
        help_text="The product the team does not use and could turn on to give reports like this one better evidence.",
    )
    reason = serializers.CharField(
        help_text="One sentence on what the product would have shown for this report.",
    )


class RankingStatus(TextChoices):
    SCORED = "scored", "scored"
    STALE = "stale", "stale"
    UNSCORED = "unscored", "unscored"
    NOT_AVAILABLE = "not_available", "not_available"


class RankingOutcomesStatus(TextChoices):
    SCORED = "scored", "scored"
    UNSCORED = "unscored", "unscored"
    NOT_AVAILABLE = "not_available", "not_available"


class ReportRankingPredictionSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(
        choices=RankingOutcome.choices,
        help_text="Outcome the model predicts. Read inbox-ranking-outcomes-list for what each outcome means.",
    )
    probability = serializers.FloatField(
        help_text="The model's calibrated probability that the outcome happens within the outcome's horizon."
    )
    lift = serializers.FloatField(
        allow_null=True,
        help_text=(
            "The probability divided by the outcome's base rate. 1.0 is an average report, 2.7 means 2.7x as "
            "likely as the average report. Compare lifts across outcomes, not raw probabilities. Null when the "
            "model has no saved base rate for the outcome."
        ),
    )
    readable = serializers.BooleanField(
        help_text=(
            "True when the training run could read the outcome's holdout AUC. Treat other outcomes with caution."
        )
    )


class ReportRankingSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=RankingStatus.choices,
        help_text=(
            "scored: the predictions describe the current text. stale: the title or summary changed after the text "
            "the model read, so the predictions describe the old text and the model sorts and filters treat the report as "
            "unscored. unscored: the model has not scored the report yet, or skipped it. This does not mean a low "
            "score. not_available: you cannot see the ranking model's output, so every other field is empty."
        ),
    )
    model = serializers.CharField(
        allow_null=True,
        help_text=(
            "Key of the served model that wrote the score, as `<model_name>@<model_version>`. "
            "Do not compare predictions from different keys."
        ),
    )
    scored_at = serializers.DateTimeField(allow_null=True, help_text="When the scoring sweep scored the report.")
    predictions = ReportRankingPredictionSerializer(
        many=True,
        help_text=(
            "The served model's predictions, one per public outcome that it scored. A prediction says what may "
            "happen, never what did: the report's status and its PR fields say whether it was resolved."
        ),
    )


class RankingOutcomeInfoSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(
        choices=RankingOutcome.choices, help_text="Name of the outcome in the `ranking` field's predictions."
    )
    label = serializers.CharField(  # type: ignore[assignment]  # field name intentionally shadows Field.label
        help_text="Short label the inbox shows for the outcome."
    )
    description = serializers.CharField(help_text="What the outcome predicts, in one sentence.")
    horizon_days = serializers.IntegerField(
        allow_null=True,
        help_text="Days after scoring within which the outcome counts. Null when the served model did not save it.",
    )
    cohort = serializers.CharField(
        allow_null=True,
        help_text="Name of the report set the outcome was trained on. Null when the served model did not save it.",
    )
    base_rate = serializers.FloatField(
        allow_null=True,
        help_text=(
            "The outcome's base rate: a report's lift is its probability divided by this value. "
            "Null when the served model has no saved base rate for the outcome."
        ),
    )
    readable = serializers.BooleanField(
        help_text=(
            "True when the training run could read the outcome's holdout AUC. Treat other outcomes with caution."
        )
    )


class RankingOutcomesResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=RankingOutcomesStatus.choices,
        help_text=(
            "scored: the served model has scored reports in this project. unscored: no readable score yet. "
            "not_available: you cannot see the ranking model's output."
        ),
    )
    model = serializers.CharField(
        allow_null=True,
        help_text="Key of the served model, as `<model_name>@<model_version>`, from the project's latest score.",
    )
    outcomes = RankingOutcomeInfoSerializer(many=True, help_text="One entry per public outcome, in the inbox order.")


def _ranking_payload(
    status: RankingStatus,
    *,
    model: str | None = None,
    scored_at: datetime | None = None,
    predictions: list[dict] | None = None,
) -> dict:
    return {"status": status.value, "model": model, "scored_at": scored_at, "predictions": predictions or []}


class PersonalRankingStatus(TextChoices):
    READY = "ready", "ready"
    UNAVAILABLE = "unavailable", "unavailable"


class PersonalRankingTier(TextChoices):
    TOP = "top", "top"
    WORTH_A_LOOK = "worth_a_look", "worth_a_look"
    LATER = "later", "later"


class PersonalRankingRankedBy(TextChoices):
    LLM = "llm", "llm"
    MODEL = "model", "model"


class PersonalRankingNeedsYou(TextChoices):
    SUGGESTED_REVIEWER = "suggested_reviewer", "suggested_reviewer"
    CLAIMED = "claimed", "claimed"
    WAITING_ON_INPUT = "waiting_on_input", "waiting_on_input"


class PersonalRankingQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text="The most reports to return, best first. Defaults to 25. Values above the configured maximum (50) use the maximum.",
    )
    refresh = serializers.BooleanField(
        default=False,
        help_text=(
            "Start a new build even when the stored one is current. The build runs in the background, so the "
            "response has `building: true`. Pass `wait_seconds` to wait for it."
        ),
    )
    focus = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
        help_text=(
            "Free text about what to put first, such as `error tracking` or `billing reports`. A request with "
            "focus always starts a new build, and an unfocused request never reuses it. Pass `wait_seconds` to "
            "wait for it."
        ),
    )
    wait_seconds = serializers.IntegerField(
        default=0,
        min_value=0,
        max_value=30,
        help_text=(
            "When the request starts a build or one is running, wait up to this many seconds for its list. "
            "Defaults to 0, which returns at once. A build usually takes 10 to 60 seconds."
        ),
    )


class PersonalRankingReportSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The report id. Pass it to inbox-reports-retrieve for the full report.")
    title = serializers.CharField(help_text="The report title.")
    status = serializers.ChoiceField(choices=SignalReport.Status.choices, help_text="The report status.")
    priority = serializers.ChoiceField(
        choices=AutonomyPriority.choices, allow_null=True, help_text="The report priority, P0 to P4, or null."
    )
    implementation_pr_state = serializers.ChoiceField(
        choices=SignalReportAssignment.PrState.choices,
        allow_null=True,
        help_text="The state of the report's implementation pull request, or null when it has none.",
    )
    ranking = ReportRankingSerializer(help_text="The ranking model's predictions for the report.")


class PersonalRankingMatchedSerializer(serializers.Serializer):
    theme = serializers.CharField(
        allow_null=True, help_text="The theme of your activity summary that the report matches, or null."
    )
    needs_you = serializers.ListField(
        child=serializers.ChoiceField(choices=PersonalRankingNeedsYou.choices),
        help_text="Why the report needs you: you are a suggested reviewer, you claimed it, or it waits on your input.",
    )


class PersonalRankingEntrySerializer(serializers.Serializer):
    rank = serializers.IntegerField(help_text="The position in your list. 1 is the first.")
    tier = serializers.ChoiceField(choices=PersonalRankingTier.choices, help_text="top, worth_a_look or later.")
    reason = serializers.CharField(help_text="Why the report has this place in your list.")
    next_step = serializers.CharField(
        allow_null=True, help_text="A suggested next step for the top entries. Null for the others."
    )
    matched = PersonalRankingMatchedSerializer(help_text="What in your work the report matches.")
    ranked_by = serializers.ChoiceField(
        choices=PersonalRankingRankedBy.choices,
        help_text="llm: the language model placed the report. model: it kept its place in the inbox order.",
    )
    report = PersonalRankingReportSerializer(help_text="A compact view of the report.")


class PersonalRankingFoldSerializer(serializers.Serializer):
    report_id = serializers.UUIDField(help_text="The report that the list leaves out.")
    into_report_id = serializers.UUIDField(help_text="The report in the list that covers the same work.")
    reason = serializers.CharField(help_text="Why the two reports are about the same work.")


class PersonalRankingSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=PersonalRankingStatus.choices,
        help_text="ready: the list is in `results`. unavailable: personal ranking is off now, and `results` is empty.",
    )
    personalized = serializers.BooleanField(
        help_text=(
            "True when the language model ranked the list with your activity summary. False when you have no "
            "summary yet or the build fell back to the inbox order."
        )
    )
    cached = serializers.BooleanField(
        help_text=(
            "True when the list is a stored one. False when it is the inbox order fallback or the new list "
            "that `wait_seconds` waited for."
        )
    )
    stale = serializers.BooleanField(
        help_text=(
            "True when the list does not match your current inbox or focus. When `building` is true, a newer "
            "list is on the way. Otherwise you reached the build limit, so try again later."
        )
    )
    building = serializers.BooleanField(
        help_text=(
            "True when a new list is being built in the background. Call again in a few seconds, or pass "
            "`wait_seconds`, to get it."
        )
    )
    fallback_reason = serializers.CharField(
        allow_null=True,
        help_text=(
            "Why the list is in inbox order and not ranked by the language model. building: no list is stored "
            "yet and one is being built. rate_limited: no list is stored yet and you reached the build limit. "
            "build_failed: no list is stored yet and the build could not start. llm_error, timeout, "
            "malformed_output, truncated_output, no_candidates or ai_not_approved: the stored build fell back. "
            "Null when the model ranked it."
        ),
    )
    generated_at = serializers.DateTimeField(allow_null=True, help_text="When the list was built.")
    latency_ms = serializers.IntegerField(
        allow_null=True,
        help_text="How long the model call of the build took, in ms. Null when there was no model call.",
    )
    activity_summary_version = serializers.IntegerField(
        allow_null=True, help_text="The version of your activity summary that the build read, or null."
    )
    candidates_considered = serializers.IntegerField(help_text="How many reports the build considered.")
    ranked_count = serializers.IntegerField(
        help_text="How many reports the stored list ranks. `results` holds at most `limit` of them."
    )
    results = PersonalRankingEntrySerializer(
        many=True,
        help_text=(
            "Your reports, best first. A report that left your inbox since the build, for example a resolved one, "
            "is left out."
        ),
    )
    folded = PersonalRankingFoldSerializer(
        many=True, help_text="Reports the list leaves out because another report in it covers the same work."
    )


def personal_ranking_payload(served: "ServedRanking") -> dict[str, Any]:
    def ranking(predictions: ReportPredictions | None) -> dict:
        if predictions is None:
            return _ranking_payload(RankingStatus.NOT_AVAILABLE)
        return _ranking_payload(
            RankingStatus(predictions.status),
            model=predictions.model,
            scored_at=predictions.scored_at,
            predictions=[dataclasses.asdict(prediction) for prediction in predictions.predictions],
        )

    return {
        **{
            field.name: getattr(served, field.name)
            for field in dataclasses.fields(served)
            if field.name not in {"results", "folded"}
        },
        "results": [
            {
                "rank": entry.rank,
                "tier": entry.tier,
                "reason": entry.reason,
                "next_step": entry.next_step,
                "matched": {"theme": entry.matched_theme, "needs_you": list(entry.needs_you)},
                "ranked_by": entry.ranked_by,
                "report": {
                    "id": entry.report.id,
                    "title": entry.report.title,
                    "status": entry.report.status,
                    "priority": entry.report.priority,
                    "implementation_pr_state": entry.report.pull_request_state,
                    "ranking": ranking(entry.report.predictions),
                },
            }
            for entry in served.results
        ],
        "folded": [dataclasses.asdict(fold) for fold in served.folded],
    }


class SignalReportPriorityUpdateSerializer(serializers.Serializer):
    priority = serializers.ChoiceField(
        choices=AutonomyPriority.choices,
        help_text="New report priority, from P0 (critical) to P4 (minimal).",
    )


class ReviewerStateSerializer(serializers.Serializer):
    reviewers_id = serializers.UUIDField(
        allow_null=True, help_text="Current reviewer artefact ID, or null before the first list."
    )
    corrections_id = serializers.UUIDField(
        allow_null=True, help_text="Current corrections artefact ID, or null before corrections are stored."
    )


class ReviewerProposalSerializer(serializers.Serializer):
    expected_reviewers = ReviewerStateSerializer(
        required=False,
        help_text="Report reviewer_assignment.state read before selection began. Required when reviewer corrections are enabled.",
    )
    reviewer_outcome = serializers.ChoiceField(
        choices=ReviewerSelectionOutcome.choices,
        required=False,
        help_text=(
            "A successful selection, a deliberate empty result, or an unavailable lookup. "
            "Defaults to selected when omitted."
        ),
    )
    reviewer_retry_reason = serializers.CharField(
        required=False, max_length=500, help_text="Reason the reviewer lookup failed."
    )


class ReviewerControlResponseSerializer(serializers.Serializer):
    state = ReviewerStateSerializer(help_text="State token for a selection, replacement, or list confirmation.")
    pinned_user_uuids = serializers.ListField(
        child=serializers.UUIDField(), help_text="People an automatic selection must retain."
    )
    excluded_user_uuids = serializers.ListField(
        child=serializers.UUIDField(), help_text="People an automatic selection must not restore."
    )
    confirmed = serializers.BooleanField(help_text="A person explicitly confirmed the complete reviewer list.")
    needs_review = serializers.BooleanField(
        help_text="Older edits need recovery on the next protected write, or have incomplete history. Automatic changes are paused until recovery or list confirmation."
    )
    enabled = serializers.BooleanField(help_text="Whether this report uses saved reviewer corrections.")

    def to_representation(self, instance: ReviewerRules) -> dict[str, object]:
        snapshot = instance.read()
        return {
            "state": snapshot.state.model_dump(mode="json"),
            "pinned_user_uuids": [entry.user_uuid for entry in snapshot.corrections.pinned if entry.user_uuid],
            "excluded_user_uuids": [entry.user_uuid for entry in snapshot.corrections.excluded if entry.user_uuid],
            "confirmed": snapshot.corrections.confirmed,
            "needs_review": snapshot.corrections.needs_review,
            "enabled": instance.enabled or snapshot.state.corrections_id is not None,
        }


class ReportPlanStepSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="The step's report id.")
    title = serializers.CharField(read_only=True, allow_null=True, help_text="The step's report title.")
    status = serializers.ChoiceField(
        read_only=True,
        choices=SignalReport.Status.choices,
        help_text="The step's report status. Monitoring reads as resolved when its rollout is disabled.",
    )
    depends_on = serializers.ListField(
        child=serializers.UUIDField(),
        read_only=True,
        help_text="Ids of the other steps in this plan that this step builds on. Empty when it builds on none.",
    )
    implementation_pr_url = serializers.CharField(
        read_only=True, allow_null=True, help_text="The step's implementation pull request, if one is attached."
    )
    implementation_pr_state = serializers.ChoiceField(
        read_only=True,
        choices=SignalReportAssignment.PrState.choices,
        allow_null=True,
        help_text="Latest known state of that pull request: unknown, draft, open, closed, or merged.",
    )
    suppression_source = serializers.SerializerMethodField(
        help_text="Who or what suppressed the step, with the same values as the report's `suppression_source`. Null unless the step is suppressed.",
    )

    @extend_schema_field(serializers.ChoiceField(choices=SignalReportSuppressionSource.choices, allow_null=True))
    def get_suppression_source(self, step: "ReportPlanStep") -> str | None:
        return self.context.get("step_suppression_sources", {}).get(step.id)


class ReportPlanSerializer(serializers.Serializer):
    id = serializers.UUIDField(
        read_only=True,
        help_text="The plan's report id. Equals the report's own id when the report is the plan.",
    )
    title = serializers.CharField(read_only=True, allow_null=True, help_text="The plan's report title.")
    status = serializers.ChoiceField(
        read_only=True,
        choices=SignalReport.Status.choices,
        help_text="The plan's report status. Monitoring reads as resolved when its rollout is disabled.",
    )
    steps = ReportPlanStepSerializer(
        many=True,
        read_only=True,
        help_text="The reports linked to the plan with `part_of`, in the order they were linked. Deleted steps are left out.",
    )


class SignalReportSerializerExtension(OpenApiSerializerExtension):
    target_class = "products.signals.backend.serializers.SignalReportSerializer"
    match_subclasses = True

    def map_serializer(self, auto_schema: "AutoSchema", direction: "Direction") -> dict[str, object]:
        schema: dict[str, object] = auto_schema._map_serializer(self.target, direction, bypass_extensions=True)
        required = schema.get("required")
        if isinstance(required, list):
            # The disabled rollout omits this timestamp, so responses cannot require it.
            schema["required"] = [name for name in required if name != "monitoring_started_at"]
        return schema


class StartupProvider(TextChoices):
    CLAUDE = "claude", "Claude"
    CODEX = "codex", "Codex"
    PI = "pi", "Pi"


class StartupPhase(TextChoices):
    SESSION_SETUP = "session_setup", "Session setup"
    SDK_INITIALIZATION = "sdk_initialization", "SDK initialization"
    SETUP_HOOKS = "setup_hooks", "Setup hooks"


class StartupRetryability(TextChoices):
    REQUIRES_ACTION = "requires_action", "Requires action"
    TRANSIENT = "transient", "Transient"
    UNKNOWN = "unknown", "Unknown"


class ReportStartupFailureSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(
        choices=StartupProvider.choices, help_text="Agent provider that failed to start."
    )
    phase = serializers.ChoiceField(choices=StartupPhase.choices, help_text="Startup stage that failed.")
    reason = serializers.CharField(allow_null=True, help_text="Validated provider reason code, when available.")
    retryability = serializers.ChoiceField(
        choices=StartupRetryability.choices, help_text="Whether an unchanged startup can be retried."
    )
    task_id = serializers.UUIDField(help_text="Research task that could not start.")
    run_id = serializers.UUIDField(help_text="Failed research task run.")
    message = serializers.CharField(help_text="Safe explanation and suggested next action.")


class ReportResearchMode(TextChoices):
    CODE = "code", "Code context"
    DATA_ONLY = "data_only", "Project data"


class ReportRepositoryStatus(TextChoices):
    AVAILABLE = "available", "Available"
    NO_INTEGRATION = "no_integration", "Not connected"
    NO_REPOSITORIES = "no_repositories", "No repositories"
    SELECTION_UNRESOLVED = "selection_unresolved", "No repository selected"
    GITHUB_UNAVAILABLE = "github_unavailable", "GitHub unavailable"


class ReportResearchContextSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=ReportResearchMode.choices, help_text="Whether research had access to a repository."
    )
    repository_status = serializers.ChoiceField(
        choices=ReportRepositoryStatus.choices,
        help_text="Code availability when the report was researched; not a live integration health check.",
    )


class SignalReportSerializer(serializers.ModelSerializer):
    startup_failure = ReportStartupFailureSerializer(
        read_only=True,
        allow_null=True,
        required=False,
        help_text="Startup failure from the latest failed research attempt, when available.",
    )
    research_context = serializers.SerializerMethodField(
        help_text="Evidence available to the latest research pass. Null for legacy reports."
    )
    reviewer_assignment = serializers.SerializerMethodField(
        help_text="Reviewer control and state token for preparing an automatic proposal."
    )

    @extend_schema_field(ReviewerControlResponseSerializer(allow_null=True))
    def get_reviewer_assignment(self, obj: SignalReport) -> dict | None:
        if isinstance(self, SignalReportListSerializer):
            return None
        service = ReviewerRules(team=obj.team, report_id=str(obj.id))
        return dict(ReviewerControlResponseSerializer(service).data)

    monitoring_started_at = serializers.DateTimeField(
        read_only=True,
        required=False,
        allow_null=True,
        help_text="Original implementation-complete time for this Monitoring period, null before entry. Present only when Monitoring is enabled.",
    )
    status = serializers.SerializerMethodField(
        help_text="Current report status. Monitoring reads as resolved when its rollout is disabled.",
    )
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
    tags = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text=(
            "Free-form lowercase kebab-case slug tags for grouping and filtering reports, at most 10. "
            "Empty when the report has no tags."
        ),
    )
    refund_ineligibility_reason = serializers.SerializerMethodField(
        help_text=(
            "Why refunding this report's PR would be rejected right now, or null when a refund "
            "would be accepted (see the field's schema for the reason values)."
        ),
    )
    summary_lead = serializers.SerializerMethodField(
        help_text=(
            "The opening of `summary` as plain text on one line: the text before its first section heading, "
            f"with chart links removed and other links reduced to their text. At most {SUMMARY_LEAD_LIMIT} characters."
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
    suppression_source = serializers.SerializerMethodField(
        help_text=(
            "Who or what suppressed the report. Null unless status is suppressed. `dismissed`: a person or "
            "agent dismissed it, it was merged into another report, or its pull request closed without "
            "merging; dismissal_reason says which when one was given. `safety_judge`: the safety judge "
            "marked it unsafe. `not_actionable`: the actionability judge marked it not actionable. "
            "`system`: suppressed by the pipeline for another reason. Every value except `dismissed` is "
            "a verdict nobody has reviewed, listed by the `held_back` inbox view."
        ),
    )
    suppression_explanation = serializers.SerializerMethodField(
        help_text=(
            "The judge's explanation when suppression_source is `safety_judge` or `not_actionable`. "
            "Null otherwise, or when the judge gave none."
        ),
    )
    repo_slug = serializers.SerializerMethodField(
        help_text=(
            "`organization/repository` the report's work targets, from the latest repo-selection "
            "artefact (when present). Lets list cards show repository context without a per-card fetch."
        ),
    )
    is_self_improvement_report = serializers.SerializerMethodField(
        help_text=(
            "Whether this is a scout self-improvement report. Most update a team-owned skill in the skills "
            "store, but reports with a selected repository can still produce a pull request."
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
    ranking = serializers.SerializerMethodField(
        help_text=(
            "The served ranking model's predictions from the latest ranking score artefact. Its status says "
            "whether the report is scored, stale or unscored, or that the user cannot see the ranking model."
        ),
    )
    source_suggestion = serializers.SerializerMethodField(
        help_text=(
            "A product the team does not use that would have given this report better evidence, from the "
            "latest source suggestion artefact. Null when there is none, or when the team now uses the "
            "product. Always null in list responses, because its in-use check can query ClickHouse."
        ),
    )
    collapsed_note_count = serializers.SerializerMethodField(
        help_text=(
            "How many scout notes this report received beyond the few its work log keeps as entries. "
            "0 when nothing was dropped. These say the finding still holds, so the count is shown in "
            "place of the entries."
        ),
    )
    plan = serializers.SerializerMethodField(
        help_text=(
            "The plan this report leads or is a step of, with every step in it. A report that other reports "
            "link to with `part_of` is a plan. Null when the report is in no plan, and always null in list "
            "responses, because finding a plan's steps costs several queries per report."
        ),
    )

    class Meta:
        model = SignalReport
        fields = [
            "id",
            "title",
            "summary",
            "summary_lead",
            "reviewer_assignment",
            "status",
            "monitoring_started_at",
            "total_weight",  # Used for priority scoring
            "signal_count",  # Used for occurrence count
            "signals_at_run",  # Snooze threshold: re-promote when signal_count >= this value
            "collapsed_note_count",  # Scout notes the work log dropped, rendered as one line instead
            "startup_failure",
            "created_at",
            "updated_at",
            "artefact_count",
            "charts",
            "metrics",
            "suggested_prompts",
            "tags",
            "source_suggestion",
            "priority",
            "actionability",
            "already_addressed",
            "dismissal_reason",
            "dismissal_note",
            "suppression_source",
            "suppression_explanation",
            "repo_slug",
            "is_self_improvement_report",
            "research_context",
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
            "ranking",
            "plan",
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

    def _monitoring_enabled(self, obj: SignalReport) -> bool:
        enabled_by_team = cast(dict[int, bool], self.context.setdefault("report_monitoring_enabled_by_team", {}))
        if obj.team_id not in enabled_by_team:
            enabled_by_team[obj.team_id] = team_report_monitoring_enabled(obj.team_id)
        return enabled_by_team[obj.team_id]

    def to_representation(self, instance: SignalReport) -> dict[str, object]:
        representation = super().to_representation(instance)
        if not self._monitoring_enabled(instance):
            representation.pop("monitoring_started_at", None)
        return representation

    def _display_status(self, obj: SignalReport, status: str) -> str:
        if status == SignalReport.Status.MONITORING and not self._monitoring_enabled(obj):
            return SignalReport.Status.RESOLVED
        return status

    @extend_schema_field(serializers.ChoiceField(choices=SignalReport.Status.choices))
    def get_status(self, obj: SignalReport) -> str:
        return self._display_status(obj, obj.status)

    @extend_schema_field(ReportPlanSerializer(allow_null=True))
    def get_plan(self, obj: SignalReport) -> dict | None:
        plans_map: dict[str, ReportPlan | None] = self.context.get("report_plans_map", {})
        plan = plans_map.get(str(obj.id))
        if plan is None:
            return None
        plan = dataclasses.replace(
            plan,
            status=self._display_status(obj, plan.status),
            steps=tuple(
                dataclasses.replace(step, status=self._display_status(obj, step.status)) for step in plan.steps
            ),
        )
        suppressed_step_ids = [step.id for step in plan.steps if step.status == SignalReport.Status.SUPPRESSED]
        step_suppression_sources = {
            str(step_report.id): suppression[0].value
            for step_report in SignalReport.objects.filter(
                team_id=obj.team_id, id__in=suppressed_step_ids
            ).prefetch_related(*self._suppression_prefetches())
            if (suppression := self._suppression(step_report)) is not None
        }
        return dict(ReportPlanSerializer(plan, context={"step_suppression_sources": step_suppression_sources}).data)

    @staticmethod
    def _suppression_prefetches() -> list[Prefetch]:
        return [
            Prefetch(
                "artefacts",
                queryset=SignalReportArtefact.objects.filter(type=artefact_type).order_by("-created_at"),
                to_attr=to_attr,
            )
            for artefact_type, to_attr in (
                (SignalReportArtefact.ArtefactType.DISMISSAL, "prefetched_dismissal_artefacts"),
                (SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT, "prefetched_safety_artefacts"),
                (SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT, "prefetched_actionability_artefacts"),
            )
        ]

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

    def get_summary_lead(self, obj: SignalReport) -> str:
        return summary_lead(obj.summary, SUMMARY_LEAD_LIMIT)

    def get_is_self_improvement_report(self, obj: SignalReport) -> bool:
        return is_self_improvement_title(obj.title)

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
        return priority_from_judgment(art.content)

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

    def _get_safety_artefact_data(self, obj: SignalReport) -> dict | None:
        prefetched = getattr(obj, "prefetched_safety_artefacts", None)
        if prefetched is not None:
            art = prefetched[0] if prefetched else None
        else:
            art = (
                obj.artefacts.filter(type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT)
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

    def _has_dismissal_artefact(self, obj: SignalReport) -> bool:
        prefetched = getattr(obj, "prefetched_dismissal_artefacts", None)
        if prefetched is not None:
            return bool(prefetched)
        return obj.artefacts.filter(type=SignalReportArtefact.ArtefactType.DISMISSAL).exists()

    def _suppression(self, obj: SignalReport) -> tuple[SignalReportSuppressionSource, str | None] | None:
        # Mirrors the `dismissed` / `held_back` inbox views: a dismissal artefact means someone chose
        # it, so it wins over any verdict the report also carries.
        if obj.status != SignalReport.Status.SUPPRESSED:
            return None
        if self._has_dismissal_artefact(obj):
            return SignalReportSuppressionSource.DISMISSED, None
        safety = self._get_safety_artefact_data(obj)
        if safety is not None and safety.get("choice") is False:
            explanation = safety.get("explanation")
            return SignalReportSuppressionSource.SAFETY_JUDGE, explanation if isinstance(explanation, str) else None
        actionability = self._get_actionability_artefact_data(obj)
        if actionability is not None and actionability.get("actionability") == ActionabilityChoice.NOT_ACTIONABLE:
            explanation = actionability.get("explanation")
            return SignalReportSuppressionSource.NOT_ACTIONABLE, explanation if isinstance(explanation, str) else None
        return SignalReportSuppressionSource.SYSTEM, None

    @extend_schema_field(serializers.ChoiceField(choices=SignalReportSuppressionSource.choices, allow_null=True))
    def get_suppression_source(self, obj: SignalReport) -> str | None:
        suppression = self._suppression(obj)
        return suppression[0].value if suppression is not None else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_suppression_explanation(self, obj: SignalReport) -> str | None:
        suppression = self._suppression(obj)
        explanation = suppression[1] if suppression is not None else None
        return explanation or None

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

    @extend_schema_field(ReportResearchContextSerializer(allow_null=True))
    def get_research_context(self, obj: SignalReport) -> dict[str, str] | None:
        data = self._get_repo_selection_artefact_data(obj)
        context = data.get("research_context") if data else None
        if not isinstance(context, dict):
            return None
        serializer = ReportResearchContextSerializer(data=context)
        return dict(serializer.validated_data) if serializer.is_valid() else None

    @extend_schema_field(ReportRankingSerializer)
    def get_ranking(self, obj: SignalReport) -> dict:
        request = self.context.get("request")
        can_view = self.context.get("can_view_inbox_ranking")
        if request is None or not (can_view() if can_view is not None else request.user.is_staff):
            return _ranking_payload(RankingStatus.NOT_AVAILABLE)

        prefetched = getattr(obj, "prefetched_ranking_score_artefacts", None)
        if prefetched is not None:
            art = prefetched[0] if prefetched else None
        else:
            art = (
                obj.artefacts.filter(type=SignalReportArtefact.ArtefactType.RANKING_SCORE)
                .order_by("-created_at")
                .first()
            )
        prefetched_edits = getattr(obj, "prefetched_latest_edit_artefacts", None)
        if prefetched_edits is not None:
            latest_edit_at = prefetched_edits[0].created_at if prefetched_edits else None
        else:
            latest_edit_at = (
                obj.artefacts.filter(type__in=EDIT_ARTEFACT_TYPES)
                .order_by("-created_at")
                .values_list("created_at", flat=True)
                .first()
            )
        read = read_report_predictions(art, latest_edit_at)
        if read.status == "unscored":
            return _ranking_payload(RankingStatus.UNSCORED)
        # Agents get rounded values because extra digits suggest precision the model does not have.
        for_agent = is_mcp_request(request)
        return _ranking_payload(
            RankingStatus(read.status),
            model=read.model,
            scored_at=read.scored_at,
            predictions=[
                {
                    "outcome": entry.outcome,
                    "probability": round(entry.probability, 2) if for_agent else entry.probability,
                    "lift": round(entry.lift, 1) if for_agent and entry.lift is not None else entry.lift,
                    "readable": entry.readable,
                }
                for entry in read.predictions
            ],
        )

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
        if obj.status in {SignalReport.Status.RESOLVED, SignalReport.Status.CLOSED, SignalReport.Status.MONITORING}:
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
        responsible = self._get_responsible_user(assignment)
        return {
            "claim_id": str(assignment.claim_id) if assignment.claim_id else None,
            "kind": assignment.actor_kind,
            "user": _UserSerializer(assignment.actor_user).data if assignment.actor_user else None,
            "task_id": str(assignment.actor_task_id) if assignment.actor_task_id else None,
            "agent": assignment.actor_agent,
            "claimed_at": assignment.claimed_at,
            "responsible_user": _UserSerializer(responsible).data if responsible else None,
        }

    def _get_responsible_user(self, claim: "ReportClaim") -> User | None:
        from products.signals.backend.report_claims import responsible_user

        users = self.context.get("claim_responsible_users_map")
        return users.get(claim.claim_id) if users is not None else responsible_user(claim)

    def _get_assignment(self, obj: SignalReport) -> "ReportClaim | None":
        from products.signals.backend.report_claims import get_active_claim

        claims = self.context.setdefault("claims_map", {})
        report_id = str(obj.id)
        if report_id not in claims:
            claims[report_id] = get_active_claim(team_id=obj.team_id, report_id=report_id)
        return claims[report_id]

    @extend_schema_field(ReportSourceSuggestionSerializer(allow_null=True))
    def get_source_suggestion(self, obj: SignalReport) -> dict | None:
        suggestions_map: dict[str, SourceSuggestion | None] = self.context.get("source_suggestions_map", {})
        suggestion = suggestions_map.get(str(obj.id))
        return suggestion.model_dump(mode="json") if suggestion else None

    def get_collapsed_note_count(self, obj: SignalReport) -> int:
        return max(0, (obj.corroboration_count or 0) - MAX_SCOUT_REPORT_NOTES)

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
    inbox_merge_key = serializers.SerializerMethodField(
        help_text=(
            "Coarse sort key from the ranker named by the list response's ranker field, for sort=recommended "
            "only. Lower keys rank first. It is the score decile of the ranker's outcome (open, action or fix), "
            "then the priority as a tiebreak. The priority ranker uses the priority only. "
            "Reports without a usable score sort after scored ones. Null for every other sort."
        ),
    )

    class Meta(SignalReportSerializer.Meta):
        fields = [*SignalReportSerializer.Meta.fields, "inbox_merge_key"]
        read_only_fields = fields

    def get_inbox_merge_key(self, obj: SignalReport) -> int | None:
        ranker = self.context.get("inbox_ranker")
        if ranker is None:
            return None
        decile = None if ranker == "priority" else getattr(obj, f"ranking_{ranker}_score_decile", None)
        return inbox_merge_key(decile, getattr(obj, "priority_sort_rank", None))


class SignalReportSectionCountsSerializer(serializers.Serializer):
    pull_requests = serializers.IntegerField(help_text="Ready reports with an implementation pull request.")
    reports = serializers.IntegerField(help_text="Ready reports without an implementation pull request.")


class SignalReportFilterQuerySerializer(serializers.Serializer):
    exclude = RepeatedOrCommaSeparatedListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
        max_length=100,
        help_text=(
            "Report ids to leave out of the results and counts, for example the reports a client already "
            "shows, as repeated parameters or comma-separated. The other reports keep their order. At most 100."
        ),
    )
    include_unlisted = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Include reports kept out of the shared inbox. A report is kept out when the scout that "
            "authored it turned off its `inbox` output destination. Defaults to false. Fetching a report "
            "by id always works, whatever this value is."
        ),
    )


class SignalReportListQuerySerializer(SignalReportFilterQuerySerializer):
    count_only = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Return the filtered total with an empty results page. Skips report ordering, "
            "serialization, and decorative metadata lookups. Defaults to false."
        ),
    )
    include_source_metadata = serializers.BooleanField(
        required=False,
        default=True,
        help_text=(
            "Fill `source_products` and `scout_name` on each row. These come from ClickHouse, so pass "
            "false to skip that lookup and get the page from Postgres only: rows then carry an empty "
            "`source_products` and a null `scout_name`. Load them after with `source_metadata`. "
            "Defaults to true."
        ),
    )


# One list page, with room for a next page's ids that have not loaded yet.
MAX_SOURCE_METADATA_REPORTS = 100


class SignalReportSourceMetadataRequestSerializer(serializers.Serializer):
    report_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=MAX_SOURCE_METADATA_REPORTS,
        help_text=f"Reports to describe. At most {MAX_SOURCE_METADATA_REPORTS} ids per call.",
    )


class SignalReportSourceMetadataSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Report id.")
    source_products = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Distinct source products contributing signals to this report. Empty when it has none yet.",
    )
    scout_name = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="skill_name slug of the scout that authored this report, when scout-authored; null otherwise.",
    )


class SignalReportSourceMetadataResponseSerializer(serializers.Serializer):
    reports = SignalReportSourceMetadataSerializer(
        many=True,
        read_only=True,
        help_text=(
            "One entry per requested id, in request order, duplicates removed. An id with no signals in "
            "this project, including one that is not a report here, gets empty values."
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
    total_spend = serializers.FloatField(
        read_only=True,
        allow_null=True,
        help_text="Accounted customer spend in USD cents, including fractional cents. May be partial; null for untracked signals.",
    )
    spend_accounting_failed_stages = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        default=list,
        help_text="Pipeline stages with generations whose spend could not be accounted for. Cleared when accounting recovers.",
    )
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


@extend_schema_field(SignalReportSerializer)
class SerializedSignalReportField(serializers.JSONField):
    pass


class ReportSignalsResponseSerializer(serializers.Serializer):
    """Response body for GET /api/projects/:id/signals/reports/:id/signals/."""

    report = SerializedSignalReportField(help_text="The report these signals were clustered into.")
    signals = SignalNodeSerializer(many=True, help_text="All signals contributing to the report.")


# ── Report checks ───────────────────────────────────────────────────────────────


# Shown in place of a check result's explanation when the viewer cannot read the measured data.
CHECK_RESULT_HIDDEN_EXPLANATION = (
    "You don't have access to the data this check measures. Ask a project admin to grant it."
)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, TypeError):
        return False
    return True


@extend_schema_field(
    PolymorphicProxySerializer(
        component_name="SignalReportCheckConfig",
        # Same cast as SignalExtra above: spectacular's PydanticExtension resolves these at
        # schema-build time, but the stubs only know about DRF serializers.
        serializers=cast(list, list(CHECK_CONFIG_SCHEMAS.values())),
        resource_type_field_name=None,
    )
)
class SignalReportCheckConfigField(serializers.JSONField):
    """Kind-specific check configuration, validated against its kind's schema on every write."""


@extend_schema_field(MetricThresholdConfig)  # type: ignore[arg-type]
class MetricThresholdCheckConfigField(serializers.JSONField):
    """Metric threshold check configuration, for requests that accept no other kind."""


def redact_check_config(config: Mapping[str, object], policy: ReportMetricAccessPolicy) -> dict[str, object]:
    """Hide the data-bearing fields of a check config this viewer may not read.

    The query names events, actions, and property filters with literal values, and the baseline is a
    number measured without a viewer, so both go through the same gate as a report metric's query
    and snapshot. The comparison and schedule stay: they are the author's expectation, not data.
    """
    redacted = dict(config)
    if "query" in redacted and not policy.may_read_query(config):
        redacted["query"] = None
    if "baseline_value" in redacted and not policy.may_read_snapshot(config):
        redacted["baseline_value"] = None
    return redacted


class MonitoringCheckTimingSerializer(serializers.Serializer):
    state = serializers.ChoiceField(
        choices=MonitoringCheckTimingState.choices,
        help_text="Whether this check has an interim measurement due, is paused, or has finished its observation window. No state implies a final verdict.",
    )
    started_at = serializers.DateTimeField(
        allow_null=True, help_text="Original Monitoring start for this check's report."
    )
    ends_at = serializers.DateTimeField(
        allow_null=True,
        help_text="End of this check's soak window, independent of its target reference period and safety expiry.",
    )
    next_measurement_at = serializers.DateTimeField(
        allow_null=True,
        help_text="Stored next interim attempt, only when it falls before the soak deadline and expiry. Null when no interim measurement is scheduled.",
    )


class SignalReportCheckSerializerExtension(OpenApiSerializerExtension):
    target_class = "products.signals.backend.serializers.SignalReportCheckSerializer"

    def map_serializer(self, auto_schema: "AutoSchema", direction: "Direction") -> dict[str, object]:
        schema: dict[str, object] = auto_schema._map_serializer(self.target, direction, bypass_extensions=True)
        required = schema.get("required")
        if isinstance(required, list):
            schema["required"] = [name for name in required if name != "monitoring_timing"]
        return schema


class SignalReportCheckSerializer(serializers.ModelSerializer):
    monitoring_timing = serializers.SerializerMethodField(
        help_text="Server-derived timing for open checks on Monitoring reports, including archived Monitoring periods. Omitted when Monitoring is disabled or the check is outside that lane.",
    )
    config = SignalReportCheckConfigField(
        help_text=(
            "What the check measures and what the result must satisfy; the shape depends on `kind`. "
            "`query` and `baseline_value` are null when you cannot read the data they describe."
        )
    )

    def _monitoring_enabled(self, instance: SignalReportCheck) -> bool:
        enabled_by_team = cast(dict[int, bool], self.context.setdefault("report_monitoring_enabled_by_team", {}))
        if instance.team_id not in enabled_by_team:
            enabled_by_team[instance.team_id] = team_report_monitoring_enabled(instance.team_id)
        return enabled_by_team[instance.team_id]

    @extend_schema_field(MonitoringCheckTimingSerializer(allow_null=True))
    def get_monitoring_timing(self, instance: SignalReportCheck) -> dict[str, object] | None:
        now = cast(datetime, self.context.setdefault("report_check_timing_now", timezone.now()))
        timing = MonitoringCheckTiming.for_check(instance, now=now)
        if timing is None or not self._monitoring_enabled(instance):
            return None
        return dict(MonitoringCheckTimingSerializer(timing).data)

    def to_representation(self, instance: SignalReportCheck) -> dict[str, object]:
        representation = dict(super().to_representation(instance))
        if representation.get("monitoring_timing") is None:
            representation.pop("monitoring_timing", None)
        config = representation.get("config")
        if isinstance(config, Mapping):
            config = dict(config)
            if "monitoring" in config:
                if not self._monitoring_enabled(instance):
                    config.pop("monitoring")
            if instance.kind == SignalReportCheck.Kind.METRIC_THRESHOLD:
                metric = next(
                    (
                        metric
                        for metric in instance.report.metrics or []
                        if isinstance(metric, Mapping)
                        and metric.get("metric_id") == config.get("metric_id")
                        and metric.get("query") == config.get("query")
                    ),
                    None,
                )
                if metric is not None:
                    for field, source in (("metric_kind", "kind"), ("value_format", "value_format"), ("unit", "unit")):
                        if config.get(field) is None:
                            config[field] = metric.get(source)
            representation["config"] = redact_check_config(config, report_metric_access_policy(self.context))
        return representation

    class Meta:
        model = SignalReportCheck
        fields = [
            "id",
            "title",
            "rationale",
            "kind",
            "status",
            "config",
            "monitoring_timing",
            "approved_at",
            "next_run_at",
            "soak_minutes",
            "run_interval_minutes",
            "runs_remaining",
            "expires_at",
            "last_run_at",
            "last_outcome",
            "last_outcome_reason",
            "dispatched_at",
            "consecutive_errors",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "title": {"help_text": "Short label for the expectation, e.g. `Checkout 500s stay below 10 a day`."},
            "rationale": {"help_text": "Why the author set the check."},
            "kind": {"help_text": "How the check is evaluated."},
            "status": {
                "help_text": (
                    "`pending` while the check waits for the report to resolve, `active` while it still runs; "
                    "every other value is terminal."
                )
            },
            "next_run_at": {
                "help_text": (
                    "Stored coordinator schedule, provisional while pending. During Monitoring this can be the "
                    "observation-window end rather than another measurement; use `monitoring_timing` for interim timing."
                )
            },
            "soak_minutes": {
                "help_text": (
                    "This check's observation window during Monitoring, in minutes. Otherwise the minimum wait after "
                    "resolution; metric checks also wait for a full post-resolution query window. Null on legacy checks."
                )
            },
            "run_interval_minutes": {
                "help_text": "Gap between interim Monitoring measurements or recurring verdicts. Null uses the Monitoring executor's default cadence, otherwise denotes a one-shot check."
            },
            "runs_remaining": {
                "help_text": "Terminal evaluations still owed before the check retires as passed. Interim Monitoring observations do not consume this count."
            },
            "expires_at": {"help_text": "Horizon after which the check retires without running again."},
            "last_run_at": {"help_text": "When the check last ran; null before its first run."},
            "last_outcome": {"help_text": "Verdict of the most recent run."},
            "last_outcome_reason": {
                "help_text": (
                    "Why the most recent run could not settle the claim. Set only when `last_outcome` is "
                    "`inconclusive`: `awaiting_data`, `unmeasurable`, `needs_manual_verification`, or "
                    "`no_fix_to_measure`."
                )
            },
            "dispatched_at": {
                "help_text": (
                    "When the `agent` check's scout run started, cleared as soon as a verdict is recorded. "
                    "A non-null value is what tells a reader the check is running rather than waiting, "
                    "because dispatch also pushes `next_run_at` out to the result window. "
                    "Always null on a `metric_threshold` check, which is measured in the tick that collects it."
                )
            },
            "consecutive_errors": {"help_text": "Runs that could not be measured since the last clean one."},
        }


class SignalReportCheckReplacementSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=MAX_CHECK_TITLE_LENGTH, help_text="Label for the new metric check.")
    rationale = serializers.CharField(
        required=False, allow_blank=True, max_length=MAX_CHECK_RATIONALE_LENGTH, help_text="Why this check is better."
    )
    config = MetricThresholdCheckConfigField(
        help_text="Metric threshold configuration, including a bounded query and comparison."
    )

    def validate_config(self, value: dict) -> dict:
        try:
            parse_check_config(SignalReportCheck.Kind.METRIC_THRESHOLD, value)
        except CheckConfigValidationError as error:
            raise serializers.ValidationError(str(error))
        return value


class SignalReportCheckWriteSerializer(serializers.Serializer):
    """Request body for creating a check on a report.

    The schedule is the check's own: `next_run_at` says when to look, rather than the system
    deriving a soak window from a merged pull request that many fixes never have.
    """

    title = serializers.CharField(
        max_length=MAX_CHECK_TITLE_LENGTH,
        help_text="Short label for the expectation, e.g. `Checkout 500s stay below 10 a day`.",
    )
    rationale = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_CHECK_RATIONALE_LENGTH,
        help_text="Why the check is worth running.",
    )
    kind = serializers.ChoiceField(
        choices=SignalReportCheck.Kind.choices,
        help_text="How the check is evaluated.",
    )
    config = SignalReportCheckConfigField(
        help_text="What the check measures and what the result must satisfy; the shape depends on `kind`."
    )
    next_run_at = serializers.DateTimeField(
        required=False,
        help_text=(
            "When to first evaluate the check. Must be in the future and within "
            f"{MAX_CHECK_HORIZON.days} days. Defaults to {DEFAULT_FIRST_RUN_AFTER.days} days from now."
        ),
    )
    run_interval_minutes = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=MIN_CHECK_INTERVAL_MINUTES,
        max_value=MAX_CHECK_INTERVAL_MINUTES,
        help_text=(
            f"Gap between runs for a recurring check, between {MIN_CHECK_INTERVAL_MINUTES} and "
            f"{MAX_CHECK_INTERVAL_MINUTES} minutes. Omit for a one-shot check."
        ),
    )
    runs_remaining = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_CHECK_RUNS,
        help_text=f"How many times to evaluate the check, at most {MAX_CHECK_RUNS}. Defaults to 1.",
    )
    expires_at = serializers.DateTimeField(
        required=False,
        help_text=(
            "Horizon after which the check retires unrun. Defaults to "
            f"{DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN.days} days after the last scheduled run, or the "
            f"{MAX_CHECK_HORIZON.days}-day horizon if that comes first."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        now = timezone.now()
        horizon = now + MAX_CHECK_HORIZON

        next_run_at = attrs.get("next_run_at") or now + DEFAULT_FIRST_RUN_AFTER
        if next_run_at <= now:
            raise serializers.ValidationError({"next_run_at": "must be in the future."})
        if next_run_at > horizon:
            raise serializers.ValidationError({"next_run_at": f"must be within {MAX_CHECK_HORIZON.days} days."})

        interval = attrs.get("run_interval_minutes")
        runs = attrs.get("runs_remaining", 1)
        if interval is None and runs != 1:
            raise serializers.ValidationError(
                {"run_interval_minutes": "a check that runs more than once needs an interval."}
            )

        last_run_at = next_run_at + timedelta(minutes=interval * (runs - 1)) if interval else next_run_at
        if last_run_at > horizon:
            raise serializers.ValidationError(
                {
                    "run_interval_minutes": (
                        f"the last run must fall within {MAX_CHECK_HORIZON.days} days. "
                        "Use a shorter interval or fewer runs."
                    )
                }
            )

        # The padding after the last run is a default, not something the caller asked for, so it
        # gives way to the horizon. Letting it overflow would reject a legal schedule and blame an
        # `expires_at` the caller never sent.
        expires_at = attrs.get("expires_at") or min(last_run_at + DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN, horizon)
        if expires_at <= next_run_at:
            raise serializers.ValidationError({"expires_at": "must be after the first run."})
        if expires_at > horizon:
            raise serializers.ValidationError({"expires_at": f"must be within {MAX_CHECK_HORIZON.days} days."})

        try:
            parse_check_config(attrs["kind"], attrs["config"])
        except CheckConfigValidationError as error:
            raise serializers.ValidationError({"config": str(error)})
        config = attrs["config"]
        if isinstance(config, Mapping) and config.get("metric_id") is not None and config.get("query") is not None:
            raise serializers.ValidationError(
                {"config": "provide either metric_id or query, not both. The metric's query is copied onto the check."}
            )

        attrs["next_run_at"] = next_run_at
        attrs["expires_at"] = expires_at
        attrs["runs_remaining"] = runs
        return attrs


# The head fields a reader needs to show a score: readability and the base rate behind each lift.
_COMPACT_RANKING_HEAD_FIELDS = ("head", "readable", "refit_classification_threshold")


def compact_ranking_score_content(content: dict) -> dict:
    """Drop the copied model metadata from a `ranking_score` row, except the head fields that read a score.

    The metadata holds training and holdout data that is tens of KB per model, so a work log with a
    few scores is mostly metadata. The single-artefact read keeps the full row.
    """
    results = content.get("results")
    if not isinstance(results, dict):
        return content
    compact_results = {}
    for key, result in results.items():
        if not isinstance(result, dict):
            compact_results[key] = result
            continue
        metadata = result.get("metadata")
        heads = metadata.get("heads") if isinstance(metadata, dict) else None
        compact_heads = [
            {field: entry[field] for field in _COMPACT_RANKING_HEAD_FIELDS if field in entry}
            for entry in (heads if isinstance(heads, list) else [])
            if isinstance(entry, dict)
        ]
        compact_results[key] = {**result, "metadata": {"heads": compact_heads}}
    return {**content, "results": compact_results}


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
            scout_display_names = cast(
                Mapping[str, str] | None,
                self.context.get("signals_scout_display_names"),
            )
            return enrich_reviewer_dicts_with_org_members(
                obj.team_id,
                parsed,
                login_to_user=reviewer_login_map,
                uuid_to_user=reviewer_uuid_map,
                scout_display_names=scout_display_names,
                manual_adders=trusted_manual_reviewer_adders(obj, parsed, self.context.get("signals_reviewer_history")),
            )

        if obj.type in {
            SignalReportArtefact.ArtefactType.CHECK_RESULT,
            SignalReportArtefact.ArtefactType.CHECK_OBSERVATION,
        } and isinstance(parsed, dict):
            return self._redact_check_result(obj, parsed)

        if (
            obj.type == SignalReportArtefact.ArtefactType.RANKING_SCORE
            and isinstance(parsed, dict)
            and self.context.get("signals_compact_ranking_scores")
        ):
            return compact_ranking_score_content(parsed)

        if obj.type == SignalReportArtefact.ArtefactType.IMPACT_MEASUREMENT_PLAN and isinstance(parsed, dict):
            policy = report_metric_access_policy(self.context)
            if not policy.may_read_query(parsed) or (
                parsed.get("eligibility_query") is not None
                and not policy.may_read_query({"query": parsed["eligibility_query"]})
            ):
                return {
                    "metric_id": parsed.get("metric_id"),
                    "title": parsed.get("title"),
                    "activated": parsed.get("activated", False),
                    "retired": parsed.get("retired", False),
                }

        return parsed

    def _redact_check_result(self, obj: SignalReportArtefact, content: dict) -> dict:
        """Hide a check result's measured numbers from a viewer who may not read the check's query.

        The value was measured without a viewer, exactly like a report metric snapshot, so the same
        policy decides. The outcome tag stays so the timeline still reads; the numbers and the line
        that quotes them do not. A result whose check no longer exists fails closed.

        An `agent` result is not measured that way and is not gated here. A scout run wrote it from
        what its own token could read, which is the provenance every other thing that run writes on
        the report already has, and the policy would refuse it outright because it judges a stored
        query an agent check does not carry.
        """
        policy = report_metric_access_policy(self.context)
        checks: dict[str, tuple[str, object] | None] = self.context.setdefault("_signals_check_configs", {})
        check_id = str(content.get("check_id"))
        if check_id not in checks:
            checks[check_id] = (
                SignalReportCheck.all_teams.filter(id=check_id, report_id=obj.report_id)
                .values_list("kind", "config")
                .first()
                if _is_uuid(check_id)
                else None
            )
        check = checks[check_id]
        if check is not None:
            kind, config = check
            if kind == SignalReportCheck.Kind.AGENT:
                return content
            if isinstance(config, Mapping) and policy.may_read_snapshot(config):
                return content
        return {
            **content,
            "observed_value": None,
            "baseline_value": None,
            "explanation": CHECK_RESULT_HIDDEN_EXPLANATION,
            **(
                {"comparison": None, "matches": None, "error": None}
                if obj.type == SignalReportArtefact.ArtefactType.CHECK_OBSERVATION
                else {}
            ),
        }


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
        help_text="GitHub login (case-insensitive). Stored lowercased. Required unless `user_uuid` is given.",
    )
    user_uuid = serializers.UUIDField(
        required=False,
        help_text=(
            "PostHog user UUID. Must be an org member on this team; a linked GitHub account is not "
            "required. Required unless `github_login` is given. If supplied together with "
            "`github_login`, the user's own identity wins."
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


class SuggestedReviewerCommitSerializer(serializers.Serializer):
    """Commit evidence behind a suggested reviewer."""

    sha = serializers.CharField(help_text="Commit SHA.")
    url = serializers.CharField(help_text="Link to the commit.")
    reason = serializers.CharField(allow_blank=True, help_text="Why the commit makes this reviewer relevant.")


class SuggestedReviewerEntryReadSerializer(serializers.Serializer):
    """One reviewer as the read path returns it: the stored entry plus read-time enrichment.

    `source_label`, `explanation` and `user` are computed on read, not stored, so a caller cannot
    write them.
    """

    github_login = serializers.CharField(
        allow_null=True, help_text="GitHub login, lowercased. Null when the reviewer has no linked account."
    )
    user_uuid = serializers.CharField(
        allow_null=True,
        help_text="PostHog user this entry routes to. Null on entries written before reviewers had one.",
    )
    github_name = serializers.CharField(allow_null=True, help_text="Display name, when the writer supplied one.")
    relevant_commits = SuggestedReviewerCommitSerializer(
        many=True, help_text="Commits attributed to this reviewer. Empty when the pick came from elsewhere."
    )
    reason = serializers.CharField(allow_null=True, help_text="Why this reviewer was chosen.")
    is_skill_owner = serializers.BooleanField(
        help_text="True when the scout owner guardrail added the entry rather than commit authorship."
    )
    is_default_owner = serializers.BooleanField(
        help_text=(
            "True when no evidence selected anyone and the report fell back to the project's default owner. "
            "The entry routes the report, but it is not ownership evidence."
        )
    )
    source_skill = serializers.CharField(
        allow_null=True, help_text="Scout skill whose run wrote the entry. Null when no scout did."
    )
    source_label = serializers.CharField(help_text="Where the suggestion came from, for display.")
    explanation = serializers.CharField(
        allow_null=True, help_text="One line of evidence for display. Null when there is none to show."
    )
    user = _UserSerializer(allow_null=True, help_text="Resolved org member. Null when the entry resolves to nobody.")


class SignalReportSuggestedReviewersArtefactSerializer(SignalReportArtefactSerializer):
    """The artefact, for a path that only ever returns a `suggested_reviewers` one.

    `content` is polymorphic on the base serializer, so a generated client types it as unknown.
    Here the type is fixed, so the entry shape can be declared. Runtime output is unchanged —
    `get_content` delegates to the base.
    """

    # The path only returns this one type, so narrowing the discriminator lets a client match on it
    # instead of the whole artefact enum.
    type = serializers.ChoiceField(
        choices=[SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS],
        read_only=True,
        help_text="Always `suggested_reviewers` on this path.",
    )

    @extend_schema_field(SuggestedReviewerEntryReadSerializer(many=True))
    def get_content(self, obj: SignalReportArtefact) -> dict | list:
        return super().get_content(obj)


class SignalReportArtefactWriteSerializer(serializers.Serializer):
    MAX_ENTRIES = 10
    REMOVAL_NOTE_MAX_LENGTH = 500

    action = serializers.ChoiceField(
        choices=ReviewerEditAction.choices,
        default="replace",
        help_text="Add or remove only the supplied people, replace the list, or explicitly confirm it.",
    )
    expected_reviewers = ReviewerStateSerializer(
        required=False,
        help_text="State from the last read. Required for replacement and confirmation when corrections are enabled.",
    )
    content = serializers.ListField(
        child=SuggestedReviewerEntryWriteSerializer(),
        allow_empty=True,
        max_length=MAX_ENTRIES,
        help_text="People to add, remove, or keep in a replacement. Send an empty list for confirmation.",
    )

    targets = serializers.ListField(
        child=SuggestedReviewerEntryWriteSerializer(),
        required=False,
        allow_empty=False,
        max_length=MAX_ENTRIES,
        help_text="Explicit add or remove targets. When supplied, content is only a fallback for older servers.",
    )
    removal_reason = serializers.ChoiceField(
        choices=ReviewerRemovalReason.choices,
        required=False,
        help_text=(
            "Why the people in `targets` are removed. Remove action only. 'wrong_area': the work should not be on "
            "them, because it is outside their area, they moved off it, or someone else owns it. 'already_covered': "
            "another reviewer already covers the report. 'unavailable': they do not have bandwidth right now. The "
            "last two say nothing about ownership. 'other': explain in removal_note. Research and scouts read the "
            "reason when they pick reviewers for later reports."
        ),
    )
    removal_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=REMOVAL_NOTE_MAX_LENGTH,
        help_text="Optional context for the removal, such as the area the person does not work on. Remove action only.",
    )

    def validate(self, attrs: dict) -> dict:
        if "targets" in attrs and attrs["action"] not in {"add", "remove"}:
            raise serializers.ValidationError({"targets": "Targets require an add or remove action."})
        attrs["removal_note"] = (attrs.get("removal_note") or "").strip() or None
        if (attrs.get("removal_reason") or attrs["removal_note"]) and attrs["action"] != "remove":
            raise serializers.ValidationError({"removal_reason": "A removal reason requires the remove action."})
        return attrs


class SignalReportLeaveReviewersSerializer(serializers.Serializer):
    removal_reason = serializers.ChoiceField(
        choices=ReviewerRemovalReason.choices,
        required=False,
        help_text=(
            "Why the user steps off. 'wrong_area': the work should not be on them, for example they moved off the "
            "area or left the team. 'already_covered': someone else is on it. 'unavailable': they do not have "
            "bandwidth right now. 'other': explain in removal_note. Research reads the reason when it picks "
            "reviewers for later reports."
        ),
    )
    removal_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=SignalReportArtefactWriteSerializer.REMOVAL_NOTE_MAX_LENGTH,
        help_text=(
            "The user's own words for why, such as \"I'm not on the payments team any more\". Scouts read it when "
            "they route later reports."
        ),
    )

    def validate_removal_note(self, value: str) -> str | None:
        return value.strip() or None


# Writable types only — `video_segment` (and any other NON_WRITABLE type) is read-only and rejected
# by the write API, so it must not be advertised as an option here.
_WRITABLE_ARTEFACT_TYPES = sorted(set(SignalReportArtefact.ArtefactType.values) - NON_WRITABLE_ARTEFACT_TYPES)

_ARTEFACT_TYPES_HELP = (
    "The artefact type. One of: "
    + ", ".join(_WRITABLE_ARTEFACT_TYPES)
    + ". Log types accumulate; status types (safety_judgment, actionability_judgment, "
    "priority_judgment, repo_selection, suggested_reviewers, channel_assignment, source_suggestion) are latest-wins — appending a new "
    "version supersedes the previous one as the report's canonical status."
)


def _validate_artefact_content_is_container(value: object) -> dict | list:
    if not isinstance(value, dict | list):
        raise serializers.ValidationError("content must be a JSON object or array.")
    return value


class SignalReportArtefactLogCreateSerializer(ReviewerProposalSerializer):
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
    """Response for the `commit` artefact diff endpoint."""

    diff = serializers.CharField(
        read_only=True,
        help_text="Unified diff (patch) text from the linked pull request or branch comparison.",
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


class PullRequestChecksPermissionErrorSerializer(serializers.Serializer):
    """Response when the GitHub App cannot read pull request checks."""

    code = serializers.CharField(read_only=True, help_text="Stable code for a missing GitHub Checks permission.")
    error = serializers.CharField(read_only=True, help_text="What the GitHub App permission prevents.")
    remediation_url = serializers.CharField(
        read_only=True,
        help_text="Project integrations settings where a project admin can reconnect GitHub.",
    )


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


class SignalReportTaskActionSerializer(serializers.Serializer):
    """One report action that starts an agent run, with whether the report offers it now."""

    action = serializers.ChoiceField(
        choices=ReportTaskActionKind.choices,
        help_text=(
            "The action. `get_it_merged` fixes CI on the report's open, approved pull request and merges it. "
            "`make_it_green` fixes failing CI on the report's open pull request and stops without merging it. "
            "`suggested_prompt` sends one of the prompts the report suggests."
        ),
    )
    available = serializers.BooleanField(help_text="Whether a run of this action can start now.")
    disabled_reason = serializers.CharField(
        allow_null=True, help_text="Why the action cannot start now. Null when `available` is true."
    )
    suggested_prompt_index = serializers.IntegerField(
        allow_null=True,
        help_text="Position of the prompt in the report's suggested prompts. Null for other actions.",
    )
    text = serializers.CharField(help_text="The message the run gets as its first request.")


class SignalReportTaskActionListResponseSerializer(serializers.Serializer):
    results = SignalReportTaskActionSerializer(
        many=True, help_text="Every action the report has, available or not, in a stable order."
    )


class SignalReportTaskActionRunRequestSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=ReportTaskActionKind.choices,
        help_text="The action to run. Use a value from the actions list, or `ask` to send your own `message`.",
    )
    suggested_prompt_index = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="Required for `suggested_prompt`: the `suggested_prompt_index` from the actions list.",
    )
    message = serializers.CharField(
        required=False,
        max_length=2000,
        help_text=(
            "Your own request for the run. Required for `ask`, where it is the question or the work you want "
            "done on the report. Optional for `get_it_merged` and `make_it_green`, where it replaces the "
            "action's fixed request and keeps its instructions and gates: pass it when you know something "
            "the report does not, such as a merge order, a failure that is already on the base branch, or "
            "an expected conflict. Not accepted for `suggested_prompt`."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        action = attrs["action"]
        if action == ReportTaskActionKind.SUGGESTED_PROMPT and attrs.get("suggested_prompt_index") is None:
            raise serializers.ValidationError(
                {"suggested_prompt_index": "Give the index of the suggested prompt to send."}
            )
        if action == ReportTaskActionKind.SUGGESTED_PROMPT and attrs.get("message"):
            raise serializers.ValidationError(
                {"message": "A suggested prompt sends its own text. Use `ask` to send your own message."}
            )
        if action == ReportTaskActionKind.ASK and not attrs.get("message"):
            raise serializers.ValidationError({"message": "Give the message to send with `ask`."})
        return attrs


class SignalReportTaskActionRunResponseSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(help_text="The task the action created. It is linked to the report.")
    run_id = serializers.UUIDField(allow_null=True, help_text="The background run that started, if one did.")
    task_url = serializers.CharField(help_text="Link to the task in PostHog.")
    run_error = serializers.CharField(
        allow_null=True, help_text="Why the run did not start. Null when it started. The task exists either way."
    )


class SignalReportTaskActionErrorSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Machine-readable error code.")
    detail = serializers.CharField(help_text="Human-readable error message.")
    task_id = serializers.UUIDField(
        required=False, help_text="For `report_action_run_active`: the task of the run that is still working."
    )
    run_id = serializers.UUIDField(
        required=False, help_text="For `report_action_run_active`: the run that is still working."
    )
