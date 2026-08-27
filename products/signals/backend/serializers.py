import json
from collections.abc import Mapping
from typing import cast

from django.db.models import Q

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

from posthog.models import User

from products.signals.backend import contracts
from products.signals.backend.billing import REFUND_INELIGIBILITY_REASONS, refund_ineligibility_reason
from products.signals.backend.contracts import DEFAULT_NOT_ACTIONABLE_KEY, STEERING_KEY, STEERING_MAX_LENGTH
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.warehouse_sources.backend.facade.types import ExternalDataSchemaStatus

from .artefact_schemas import NON_WRITABLE_ARTEFACT_TYPES
from .daily_limit import reports_generated_today, team_day_start
from .models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalReportRefund,
    SignalSourceConfig,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from .report_charts import CHART_SIZES, MAX_CHART_CAPTION_LENGTH, MAX_CHART_ID_LENGTH, MAX_CHART_TITLE_LENGTH
from .report_generation.resolve_reviewers import enrich_reviewer_dicts_with_org_members

DEFAULT_SESSION_ANALYSIS_SAMPLE_RATE = 0.1


# Maps (source_product, source_type) → (ExternalDataSourceType value, schema name)
_DATA_IMPORT_SOURCE_MAP: dict[tuple[str, str], tuple[str, str]] = {
    (SignalSourceConfig.SourceProduct.GITHUB, SignalSourceConfig.SourceType.ISSUE): ("Github", "issues"),
    (SignalSourceConfig.SourceProduct.LINEAR, SignalSourceConfig.SourceType.ISSUE): ("Linear", "issues"),
    (SignalSourceConfig.SourceProduct.ZENDESK, SignalSourceConfig.SourceType.TICKET): ("Zendesk", "tickets"),
    (SignalSourceConfig.SourceProduct.PGANALYZE, SignalSourceConfig.SourceType.ISSUE): ("PgAnalyze", "issues"),
}


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
    status = serializers.SerializerMethodField()
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

    def get_status(self, obj: SignalSourceConfig) -> str | None:
        mapping = _DATA_IMPORT_SOURCE_MAP.get((obj.source_product, obj.source_type))
        if mapping is None:
            return None
        ext_source_type, schema_name = mapping
        return self._get_data_import_status(obj.team_id, ext_source_type, schema_name)

    def _get_data_import_status(self, team_id: int, ext_source_type: str, schema_name: str) -> str | None:
        from products.warehouse_sources.backend.facade.models import ExternalDataSchema

        statuses = set(
            ExternalDataSchema.objects.filter(
                Q(name=schema_name) | Q(name__endswith=f".{schema_name}"),
                team_id=team_id,
                source__source_type=ext_source_type,
            )
            .exclude(source__deleted=True)
            .values_list("status", flat=True)
        )
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
            "max_reports_per_day",
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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]
        extra_kwargs = {
            "slack_notification_channel": {
                "help_text": (
                    "Slack channel target in the same `channel_id|#channel-name` shape PostHog uses elsewhere "
                    "(only the channel id is required). Null disables Slack notifications."
                )
            },
            "slack_notification_min_priority": {
                "help_text": (
                    "Minimum report priority that triggers a Slack notification. P0 is highest. "
                    "Null means notify on every priority (and reports without a priority judgment)."
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
        help_text="`channel_id|#channel-name` target — same convention used by Insight Alerts.",
    )
    slack_notification_min_priority = serializers.ChoiceField(
        choices=AutonomyPriority.choices,
        required=False,
        allow_null=True,
        help_text="P0 is highest. Null = notify for every priority.",
    )


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
    suggested_prompts = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text=(
            "Follow-up questions the report's author suggests asking about it, in the order they were "
            "written. The inbox offers them above the `Ask AI` box; clicking one fills the box with it."
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
    is_suggested_reviewer = serializers.BooleanField(read_only=True, default=False)
    source_products = serializers.SerializerMethodField(
        help_text="Distinct source products contributing signals to this report (from ClickHouse).",
    )
    scout_name = serializers.SerializerMethodField(
        help_text="skill_name slug of the scout that authored this report, when scout-authored (from ClickHouse); null otherwise.",
    )
    implementation_pr_url = serializers.SerializerMethodField(
        help_text="PR URL from the latest implementation task run, if available.",
    )
    implementation_pr_merged = serializers.SerializerMethodField(
        help_text=(
            "Whether that implementation PR is merged, per the GitHub webhook. False when there is no "
            "PR or it hasn't merged. Report status doesn't imply this: a resolved report may have been "
            "resolved directly, without a merged PR."
        ),
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
            "suggested_prompts",
            "priority",
            "actionability",
            "already_addressed",
            "dismissal_reason",
            "dismissal_note",
            "is_suggested_reviewer",
            "source_products",
            "scout_name",
            "implementation_pr_url",
            "implementation_pr_merged",
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

    def get_implementation_pr_url(self, obj: SignalReport) -> str | None:
        implementation_pr_url_map: dict[str, str] | None = self.context.get("implementation_pr_url_map")
        if implementation_pr_url_map is not None:
            return implementation_pr_url_map.get(str(obj.id))
        value = getattr(obj, "implementation_pr_url", None)
        return value if isinstance(value, str) else None

    def get_implementation_pr_merged(self, obj: SignalReport) -> bool:
        merged_report_ids: set[str] | None = self.context.get("implementation_pr_merged_ids")
        if merged_report_ids is not None:
            return str(obj.id) in merged_report_ids
        # Annotated path: the JSON flag arrives as text, and NULL means no PR-bearing run at all.
        value = getattr(obj, "implementation_pr_merged", None)
        return value in (True, "true", "True")

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
        return refund_ineligibility_reason(
            has_refund=getattr(obj, "refund", None) is not None,
            billing_exempt=bool(obj.billing_exempt_reason),
            billable_run_at=getattr(obj, "first_billable_pr_run_at", None),
            period=period,
        )


# ── Report `signals` action ─────────────────────────────────────────────────────
#
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
    content = serializers.SerializerMethodField()
    created_by = _UserSerializer(
        read_only=True,
        allow_null=True,
        help_text="User the artefact is attributed to, when a user produced it. Null for task/system writes.",
    )
    task_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="Task the artefact is attributed to, when an agent produced it. Null for user/system writes.",
    )

    class Meta:
        model = SignalReportArtefact
        fields = ["id", "type", "content", "created_at", "updated_at", "created_by", "task_id"]
        read_only_fields = fields

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
            return enrich_reviewer_dicts_with_org_members(
                obj.team_id,
                parsed,
                login_to_user=reviewer_login_map,
            )

        return parsed


class SuggestedReviewerEntryWriteSerializer(serializers.Serializer):
    """Single entry in a PUT body for a `suggested_reviewers` artefact.

    Each entry must identify a reviewer by at least one of `github_login` or `user_uuid`.
    The server canonicalizes to a lowercase `github_login` — if `user_uuid` is supplied,
    it must map to an org member on this team with a linked GitHub login.
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
            "PostHog user UUID. Must be an org member on this team with a linked GitHub identity. "
            "If supplied together with `github_login`, the server-resolved login from the user wins."
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
