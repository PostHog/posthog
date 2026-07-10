import json
import logging
from collections.abc import Mapping
from typing import cast

from asgiref.sync import async_to_sync
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from rest_framework import serializers

from posthog.models import User
from posthog.temporal.common.client import sync_connect

from .artefact_schemas import NON_WRITABLE_ARTEFACT_TYPES
from .models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalSourceConfig,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from .report_generation.resolve_reviewers import enrich_reviewer_dicts_with_org_members

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

DEFAULT_SESSION_ANALYSIS_SAMPLE_RATE = 0.1


# Maps (source_product, source_type) → (ExternalDataSourceType value, schema name)
_DATA_IMPORT_SOURCE_MAP: dict[tuple[str, str], tuple[str, str]] = {
    (SignalSourceConfig.SourceProduct.GITHUB, SignalSourceConfig.SourceType.ISSUE): ("Github", "issues"),
    (SignalSourceConfig.SourceProduct.LINEAR, SignalSourceConfig.SourceType.ISSUE): ("Linear", "issues"),
    (SignalSourceConfig.SourceProduct.ZENDESK, SignalSourceConfig.SourceType.TICKET): ("Zendesk", "tickets"),
    (SignalSourceConfig.SourceProduct.PGANALYZE, SignalSourceConfig.SourceType.ISSUE): ("PgAnalyze", "issues"),
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

    # Per-row Temporal RPC: serializing N source configs issues N of these on inbox load.
    # The span surfaces that cost so the N+1 is visible per request in APM.
    @tracer.start_as_current_span("signals.source_config.session_analysis_status")
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
            # The except swallows the error, so OTel won't auto-record it on the span — mark it
            # failed explicitly, else an unreachable Temporal looks like a successful no-op in APM.
            span = trace.get_current_span()
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR))
            logger.warning("Failed to list session summarization workflows: %s", e)
        return None

    def _get_data_import_status(self, team_id: int, ext_source_type: str, schema_name: str) -> str | None:
        from products.warehouse_sources.backend.facade.models import ExternalDataSchema

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

    class Meta:
        model = SignalTeamConfig
        fields = [
            "id",
            "default_autostart_priority",
            "default_slack_notification_channel",
            "autostart_base_branches",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "default_slack_notification_channel": {
                "help_text": (
                    "Default Slack channel for this team's signal inbox notifications, in the same "
                    "`channel_id|#channel-name` shape PostHog uses elsewhere (only the channel id is required). "
                    "Null means no team-level default; per-user channels still apply."
                )
            },
        }

    def validate_autostart_base_branches(self, value: dict) -> dict:
        cleaned: dict[str, str] = {}
        for repo, branch in value.items():
            repo_key = (repo or "").strip()
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
            "dismissal_reason",
            "dismissal_note",
            "is_suggested_reviewer",
            "source_products",
            "scout_name",
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
    "priority_judgment, repo_selection, suggested_reviewers) are latest-wins — appending a new "
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


class ReviewCommentEntrySerializer(serializers.Serializer):
    """One entry in a pull request's review conversation — a submitted review, an inline
    diff-thread comment, or a top-level conversation comment, normalized to a single shape."""

    # Plain CharField (not ChoiceField) to keep GitHub's kind vocabulary out of the shared OpenAPI
    # enum namespace; the value is server-generated and simply echoed to the UI.
    kind = serializers.CharField(
        read_only=True,
        help_text="What produced this entry: 'review' (a submitted review), 'review_comment' "
        "(an inline diff-thread comment), or 'issue_comment' (a top-level conversation comment).",
    )
    author = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="GitHub login of the author, or null when GitHub did not attribute the entry.",
    )
    body = serializers.CharField(
        read_only=True,
        allow_blank=True,
        help_text="The comment or review body as GitHub-flavoured markdown. May be empty for a "
        "verdict-only review (e.g. an approval with no note).",
    )
    created_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the entry was created / the review submitted (ISO 8601).",
    )
    # Plain CharField (not ChoiceField) on purpose: keeps GitHub's review-state vocabulary out of
    # the shared OpenAPI enum namespace and avoids a name collision with other products' enums.
    review_state = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="For 'review' entries, the review verdict: APPROVED, CHANGES_REQUESTED, or "
        "COMMENTED. Null for inline and conversation comments.",
    )
    path = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="For inline diff-thread comments, the file the comment is attached to. Null otherwise.",
    )
    line = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="For inline diff-thread comments, the line in the diff the comment is attached to "
        "(falls back to the original line for an outdated thread). Null otherwise.",
    )
    html_url = serializers.URLField(
        read_only=True,
        allow_null=True,
        help_text="Link to the entry on GitHub, or null when GitHub did not provide one.",
    )


class ReviewCommentsResponseSerializer(serializers.Serializer):
    """Response for the `commit` artefact review-comments endpoint — the review conversation of the
    report's implementation pull request, merged into one time-ordered list."""

    comments = ReviewCommentEntrySerializer(
        many=True,
        read_only=True,
        help_text="Review activity for the pull request (submitted reviews, inline diff-thread "
        "comments, and conversation comments), oldest first.",
    )
    truncated = serializers.BooleanField(
        read_only=True,
        help_text="True when the pull request has more review activity than was fetched, so the "
        "newest entries may be missing and the full conversation lives on GitHub.",
    )
