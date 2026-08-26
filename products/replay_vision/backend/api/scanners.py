import json
from typing import Any, NoReturn, cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import CharField, Count, F, IntegerField, OuterRef, Prefetch, Q, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce, NullIf
from django.utils import timezone

import structlog
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_field,
    extend_schema_view,
)
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, Throttled, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import RecordingsQuery

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.event_usage import report_user_action
from posthog.exceptions import QuotaLimitExceeded
from posthog.models.tag import tagify
from posthog.models.tagged_item import TaggedItem
from posthog.models.user import User
from posthog.permissions import get_authenticator_scopes
from posthog.rate_limit import (
    AIBurstRateThrottle,
    AISustainedRateThrottle,
    ReplayVisionEstimateBurstRateThrottle,
    ReplayVisionEstimateSustainedRateThrottle,
)

from products.access_control.backend.presentation.access_control import (
    AccessControlViewSetMixin,
    UserAccessControlSerializerMixin,
)
from products.replay_vision.backend.api.errors import ReplayVisionErrorSerializer
from products.replay_vision.backend.api.filters import (
    MultiChoiceFilter,
    OrderByFilter,
    ordering_enum,
    split_csv,
    validate_csv_choices,
)
from products.replay_vision.backend.api.trigger import (
    WorkflowStartOutcome,
    check_observation_quota,
    check_scanner_quota,
    check_team_in_flight_capacity,
    start_apply_scanner_workflow,
)
from products.replay_vision.backend.billing import observation_credits_case, observation_credits_for_model
from products.replay_vision.backend.digest import provision_scanner_digest
from products.replay_vision.backend.feedback_themes import cached_feedback_themes
from products.replay_vision.backend.impact import (
    DEFAULT_IMPACT_WINDOW_DAYS,
    compute_scanner_impact,
    create_affected_cohort,
)
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import (
    ReplayScanner,
    SamplingMode,
    ScannerModel,
    ScannerProvider,
    ScannerType,
    apply_experiment_targeting,
)
from products.replay_vision.backend.queries import (
    ESTIMATE_STALE_AFTER,
    MIN_SAMPLING_RATE,
    PREVIEW_ESTIMATE_BUDGET,
    SAVE_ESTIMATE_BUDGET,
    estimate_scanner_session_volume,
    project_monthly_observations,
    refresh_scanner_estimate,
)
from products.replay_vision.backend.quota import (
    ScannerBudget,
    ScannerSpend,
    compute_scanner_budgets,
    credits_used_by_scanner,
    current_period_bounds,
    spend_projection,
)
from products.replay_vision.backend.scanner_access import is_experiment_accessible
from products.replay_vision.backend.scanner_config import (
    MAX_PROMPT_LENGTH,
    MAX_TAG_LENGTH,
    acting_user,
    scanner_config_error,
)
from products.replay_vision.backend.scanner_draft import DraftError, draft_scanner_from_goal
from products.replay_vision.backend.scanning import MAX_SESSIONS_PER_SCAN, run_inline_scan, scan_existing_scanner
from products.replay_vision.backend.session_limits import MAX_SESSION_ID_LENGTH
from products.replay_vision.backend.tag_suggestions import SuggestionError, suggest_classifier_tags
from products.replay_vision.backend.temporal.constants import VISION_SIGNALS_SOURCE_PRODUCT, VISION_SIGNALS_SOURCE_TYPE
from products.replay_vision.backend.temporal.metrics import record_scanner_limit_reached
from products.signals.backend.facade.api import get_outcomes_for_signal_source_slice

# Date is set by the schedule at trigger time, not by the user — strip on save.
_QUERY_FIELDS_TO_STRIP = ("date_from", "date_to")


def _reject_direct_experiment_exposure(query: dict[str, Any]) -> None:
    # Exposure is derived from experiment_targeting at scan time, never persisted in the query blob:
    # writable exposure there would bypass experiment_targeting's access check and let an editor run
    # the exposure filter under the creator's access.
    if query.get("experiment_exposure") is not None:
        raise serializers.ValidationError(
            "Recording filter can't set experiment exposure directly. Set experiment_targeting instead."
        )


# Size caps enforced at the write boundary; scanner_config and query are copied into every observation's snapshot.
_MAX_DESCRIPTION_LENGTH = 1_000
_MAX_QUERY_BYTES = 50_000

# Each tag costs get_or_create round trips in set_tags_on_object, so cap the list.
_MAX_TAGS = 32

logger = structlog.get_logger(__name__)


# Query keys that narrow which sessions a scanner matches. Date keys are schedule-controlled
# and stripped on save, so they never count as user-chosen filters.
_QUERY_FILTER_KEYS = (
    "events",
    "actions",
    "properties",
    "console_log_filters",
    "having_predicates",
    "duration",
    "distinct_ids",
)


def _scanner_lifecycle_properties(scanner: ReplayScanner) -> dict[str, Any]:
    """Config choices at save time, so launch dashboards can see whether the defaults get changed.
    Filter *values* stay out: they can carry customer data (URLs, emails)."""
    query = scanner.query if isinstance(scanner.query, dict) else {}
    estimate = scanner.estimated_monthly_observations
    return {
        "scanner_id": str(scanner.id),
        "scanner_type": scanner.scanner_type,
        "model": scanner.model,
        # The model's price, so experiments on the model picker can compare spend without joining a price table.
        "credits_per_observation": observation_credits_for_model(scanner.model),
        "sampling_rate": scanner.sampling_rate,
        "sampling_mode": scanner.sampling_mode,
        "enabled": scanner.enabled,
        "has_filters": any(query.get(key) for key in _QUERY_FILTER_KEYS),
        "estimated_monthly_observations": estimate,
        "estimated_monthly_credits": (
            estimate * observation_credits_for_model(scanner.model) if estimate is not None else None
        ),
        "team_id": scanner.team_id,
        "organization_id": str(scanner.team.organization_id),
    }


def _refresh_estimate_fail_soft(scanner: ReplayScanner) -> None:
    # The estimate is advisory — never fail a scanner save over it, and keep the save's latency tail short.
    try:
        refresh_scanner_estimate(scanner, budget=SAVE_ESTIMATE_BUDGET)
    except Exception:
        logger.exception("replay_vision.estimate_refresh_failed", scanner_id=str(scanner.id))


class FeedbackThemeSessionSerializer(serializers.Serializer):
    observation_id = serializers.CharField(help_text="Observation whose feedback comment backs this theme.")
    session_id = serializers.CharField(help_text="Session recording the feedback comment was about.")


class FeedbackThemeSerializer(serializers.Serializer):
    theme = serializers.CharField(
        help_text='Short failure mode in sentence case, for example "Review page mistaken for confirmation".'
    )
    count = serializers.IntegerField(help_text="How many feedback comments describe this failure mode.")
    examples = serializers.ListField(
        child=serializers.CharField(),
        help_text="Up to two short representative quotes from the feedback comments.",
    )
    sessions = FeedbackThemeSessionSerializer(
        many=True,
        help_text="The rated sessions whose feedback comments back this theme. Empty for summaries generated "
        "before session tracking.",
    )


class FeedbackThemesSerializer(serializers.Serializer):
    themes = FeedbackThemeSerializer(many=True, help_text="Recurring failure modes, most frequent first.")
    feedback_count = serializers.IntegerField(
        help_text="Number of thumbs-down feedback comments the summary was generated from."
    )
    generated_at = serializers.DateTimeField(help_text="When the summary was generated.")


class ScannerExperimentTargetingSerializer(serializers.Serializer):
    """The experiment a scanner watches. Scans derive their person-scoped exposure filter from
    this blob at query time, so it is the only place an experiment can enter a scanner's
    targeting — which is what lets the write-side access check and read-side redaction cover it."""

    experiment_id = serializers.IntegerField(
        min_value=1,
        help_text="The experiment the scanner watches.",
    )
    variant = serializers.CharField(
        max_length=400,
        allow_blank=False,
        allow_null=True,
        required=False,
        default=None,
        help_text="Narrow to sessions of people exposed to this variant. Null means every variant.",
    )


@extend_schema_field(ScannerExperimentTargetingSerializer(allow_null=True))
class ScannerExperimentTargetingField(serializers.JSONField):
    """The experiment-targeting blob, always validated whole.

    A JSONField subclass rather than a nested serializer field so a partial PATCH can't save a
    half-filled object: DRF propagates the parent's `partial` into nested serializers, but this
    validates every write through a fresh non-partial serializer. Decorating the class (not an
    instance) is what makes `extend_schema_field` land, so the generated types get the real shape.
    """

    def to_internal_value(self, data: Any) -> Any:
        data = super().to_internal_value(data)
        if data is None:
            return None
        nested = ScannerExperimentTargetingSerializer(data=data)
        nested.is_valid(raise_exception=True)
        return dict(nested.validated_data)


class ReplayScannerSerializer(TaggedItemSerializerMixin, UserAccessControlSerializerMixin, serializers.ModelSerializer):
    """A Replay Vision scanner: its type, targeting query, and AI configuration."""

    experiment_targeting = ScannerExperimentTargetingField(
        required=False,
        allow_null=True,
        help_text=(
            "The experiment this scanner's targeting watches, if any. "
            "Set null when the experiment targeting is removed."
        ),
    )
    name = serializers.CharField(
        max_length=255,
        help_text="Human-readable scanner name. Unique within the team.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=_MAX_DESCRIPTION_LENGTH,
        help_text="Free-form description shown in the scanner management UI.",
    )
    # Redeclared over the mixin's bare ListField so the generated types get string[] instead of unknown[].
    tags = serializers.ListField(
        child=serializers.CharField(max_length=255),  # Tag.name column limit.
        required=False,
        max_length=_MAX_TAGS,
        help_text=(
            "Organizational tags for this scanner. Distinct from a classifier's categories in scanner_config. "
            "Tags cannot contain commas."
        ),
    )
    scanner_type = serializers.ChoiceField(
        choices=ScannerType.choices,
        help_text="What the scanner does: monitor, classifier, scorer, or summarizer.",
    )
    scanner_config = serializers.JSONField(
        help_text=(
            "Type-specific configuration. All scanner types require `prompt`; monitors add optional `allow_inconclusive`, "
            "classifiers add `tags`, scorers add `scale`, summarizers add optional `length`."
        ),
    )
    query = extend_schema_field(RecordingsQuery)(  # type: ignore[arg-type, type-var]
        serializers.JSONField(
            required=False,
            help_text=(
                "Persisted `RecordingsQuery` shape used to pick candidate sessions. "
                "`date_from`/`date_to` are stripped on save — the schedule controls time, not the user."
            ),
        )
    )
    sampling_rate = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        help_text=(
            "0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling). "
            "Use exactly 0 to pause scanning; non-zero rates below 0.0001 (0.01%) are rejected as below "
            "the sampling precision."
        ),
    )
    sampling_mode = serializers.ChoiceField(
        choices=SamplingMode.choices,
        required=False,
        help_text="Quality pre-filter applied before random sampling. focused = top sessions only, balanced = drops the lowest-quality, comprehensive = no filter (default).",
    )
    credit_limit = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        # int4 bound: DRF never runs full_clean, so an over-int4 value would 500 in Postgres, not 400.
        max_value=2147483647,
        help_text=(
            "Optional cap on this scanner's own credit spend per billing period. Null means no scanner-level "
            "cap. When reached, this scanner stops scanning until the period resets. It stays enabled and "
            "does not scan the sessions it skipped."
        ),
    )
    provider = serializers.ChoiceField(
        choices=ScannerProvider.choices,
        required=False,
        help_text="LLM provider. v1 is Google-only.",
    )
    model = serializers.ChoiceField(
        choices=ScannerModel.choices,
        help_text="Concrete model to use for this scanner.",
    )
    enabled = serializers.BooleanField(
        required=False,
        help_text="When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work.",
    )
    emits_signals = serializers.BooleanField(
        required=False,
        help_text="When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals.",
    )

    scanner_version = serializers.IntegerField(
        read_only=True,
        help_text="Increments on every config-changing save. Observations snapshot this value.",
    )
    estimated_monthly_observations = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="Latest projected observations/month for this scanner. Null until first computed.",
    )
    credits_per_observation = serializers.SerializerMethodField(
        help_text="Credits one observation by this scanner costs (1 credit = $0.01), derived from `model`.",
    )
    estimated_monthly_credits = serializers.SerializerMethodField(
        help_text="`estimated_monthly_observations` priced at `credits_per_observation`. Null until the estimate is first computed.",
    )
    credits_this_month = serializers.SerializerMethodField(
        help_text=(
            "Credits this scanner's succeeded observations consumed in the current billing period "
            "(1 credit = $0.01). Matches the window of the org-wide quota meter."
        ),
    )
    observations_this_month = serializers.SerializerMethodField(
        help_text="Succeeded observations this scanner produced in the current billing period.",
    )
    credits_used_against_limit = serializers.SerializerMethodField(
        help_text=(
            "Credits counted against `credit_limit` for the current billing period: settled receipts plus "
            "in-flight observations and running prompt tests, priced from their frozen snapshot model. This "
            "is what the limit gate measures, so it includes work still in progress. It is not the same as "
            "`credits_this_month`, which counts only succeeded observations."
        ),
    )
    limit_reached = serializers.SerializerMethodField(
        help_text=(
            "Whether this scanner has stopped because of its own credit limit. True when `credit_limit` is "
            "set and the budget left cannot cover one more observation, which is the same test the scanner's "
            "enforcement gates apply. Always false when no limit is set."
        ),
    )
    last_swept_at = serializers.DateTimeField(
        read_only=True,
        help_text="Watermark for the scanner's last scheduled fire. Mirrors Temporal schedule state for recovery.",
    )
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who created the scanner.",
    )
    feedback_themes = serializers.SerializerMethodField(
        help_text="AI summary of the team's written thumbs-down feedback into recurring failure modes. "
        "Refreshed with prompt recommendations; null until enough feedback accumulates."
    )

    @extend_schema_field(FeedbackThemesSerializer(allow_null=True))
    def get_feedback_themes(self, scanner: ReplayScanner) -> dict[str, Any] | None:
        cached = cached_feedback_themes(scanner)
        if not cached:
            return None
        # The staleness fingerprint is internal bookkeeping, not API surface.
        return {
            # Summaries cached before session tracking lack the key, so default it to keep the shape stable.
            "themes": [{**theme, "sessions": theme.get("sessions") or []} for theme in cached.get("themes") or []],
            "feedback_count": cached.get("feedback_count", 0),
            "generated_at": cached.get("generated_at"),
        }

    class Meta:
        model = ReplayScanner
        fields = [
            "id",
            "name",
            "description",
            "tags",
            "scanner_type",
            "scanner_config",
            "query",
            "sampling_rate",
            "sampling_mode",
            "credit_limit",
            "provider",
            "model",
            "enabled",
            "emits_signals",
            "experiment_targeting",
            "scanner_version",
            "estimated_monthly_observations",
            "credits_per_observation",
            "estimated_monthly_credits",
            "credits_this_month",
            "observations_this_month",
            "credits_used_against_limit",
            "limit_reached",
            "last_swept_at",
            "created_at",
            "created_by",
            "updated_at",
            "feedback_themes",
            "user_access_level",
        ]
        read_only_fields = [
            "id",
            "scanner_version",
            "estimated_monthly_observations",
            "credits_per_observation",
            "estimated_monthly_credits",
            "credits_this_month",
            "observations_this_month",
            "credits_used_against_limit",
            "limit_reached",
            "last_swept_at",
            "created_at",
            "created_by",
            "updated_at",
            "feedback_themes",
            "user_access_level",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_credits_per_observation(self, scanner: ReplayScanner) -> int:
        return observation_credits_for_model(scanner.model)

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_estimated_monthly_credits(self, scanner: ReplayScanner) -> int | None:
        if scanner.estimated_monthly_observations is None:
            return None
        return scanner.estimated_monthly_observations * observation_credits_for_model(scanner.model)

    def _page_scanner_ids(self, scanner: ReplayScanner) -> list[UUID]:
        root = self.root
        instance = root.instance if isinstance(root, serializers.ListSerializer) else None
        return [s.id for s in instance] if instance is not None else [scanner.id]

    def _scanner_spend(self, scanner: ReplayScanner) -> ScannerSpend:
        # The context dict is shared across the list's children, so the page's totals are computed once.
        totals = self.context.get("_scanner_credits_used")
        if totals is None:
            totals = credits_used_by_scanner(
                self.context["get_team"]().organization_id, self._page_scanner_ids(scanner)
            )
            self.context["_scanner_credits_used"] = totals
        return totals.get(scanner.id, ScannerSpend(0, 0))

    def _scanner_budget(self, scanner: ReplayScanner) -> ScannerBudget:
        """The limit-facing figure. Separate from `_scanner_spend` on purpose: that one is the displayed
        spend read from observation rows, this one is the delete-proof ledger draw the cap is enforced on."""
        budgets = self.context.get("_scanner_budgets")
        if budgets is None:
            budgets = compute_scanner_budgets(
                self.context["get_team"]().organization_id, self._page_scanner_ids(scanner)
            )
            self.context["_scanner_budgets"] = budgets
        # Indexed, not `.get(default)` like `_scanner_spend`: a missing entry means the page id list didn't
        # cover this scanner, and defaulting a limit figure to zero would report a blocked scanner as fine.
        # Displayed spend can safely fall back to zero; this cannot.
        try:
            return budgets[scanner.id]
        except KeyError:
            raise KeyError(
                f"Scanner {scanner.id} missing from the page's budget batch; the serializer ran outside "
                f"the list context that precomputes _page_scanner_ids"
            ) from None

    @extend_schema_field(serializers.IntegerField())
    def get_credits_this_month(self, scanner: ReplayScanner) -> int:
        return self._scanner_spend(scanner).credits

    @extend_schema_field(serializers.IntegerField())
    def get_observations_this_month(self, scanner: ReplayScanner) -> int:
        return self._scanner_spend(scanner).observations

    @extend_schema_field(serializers.IntegerField())
    def get_credits_used_against_limit(self, scanner: ReplayScanner) -> int:
        return self._scanner_budget(scanner).credits_used

    @extend_schema_field(serializers.BooleanField())
    def get_limit_reached(self, scanner: ReplayScanner) -> bool:
        # `blocked`, not `exhausted`: the enforcement gates admit an observation only when its full cost
        # fits, so a scanner with under one observation of headroom is already stopped. Reporting
        # `exhausted` here would tell the user a blocked scanner is fine.
        return self._scanner_budget(scanner).blocked

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Surface the (team_id, name) uniqueness as a 400 instead of letting the DB raise 500.
        name = attrs.get("name")
        if name is not None:
            team = self.context["get_team"]()
            duplicates = ReplayScanner.objects.filter(team=team, name=name)
            if self.instance is not None:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError({"name": "A scanner with this name already exists in this team."})
        self._reject_scanner_type_change(attrs)
        self._validate_scanner_config(attrs)
        self._validate_and_strip_query(attrs)
        self._drop_redacted_targeting_clear(attrs)
        return attrs

    def _drop_redacted_targeting_clear(self, attrs: dict[str, Any]) -> None:
        # to_representation redacts experiment_targeting to null for callers denied the experiment,
        # and the editor form writes the whole object back on save. Without this, any save by such
        # a caller would carry experiment_targeting=None and silently clear targeting they can't
        # see. Dropping the key treats it as untouched; a caller who can view the experiment can
        # still clear it explicitly.
        if (
            "experiment_targeting" in attrs
            and attrs["experiment_targeting"] is None
            and self.instance is not None
            and self.instance.experiment_targeting
            and not self._can_view_targeted_experiment(self.instance.experiment_targeting)
        ):
            attrs.pop("experiment_targeting")

    def validate_experiment_targeting(self, value: dict[str, Any] | None) -> dict[str, Any] | None:
        # The field already validated the blob's shape; this adds the access check, which needs the
        # request context the field lacks. Filtered by the caller's experiment access (not just the
        # team) so a scanner-editor can't confirm an experiment they can't view exists — a denied or
        # cross-team id reads as not-found.
        if value is None:
            return None
        if not self._can_view_targeted_experiment(value):
            raise serializers.ValidationError("Experiment not found in this project.")
        return value

    def validate_sampling_rate(self, value: float) -> float:
        # Below one modulo bucket the candidate query samples nothing — reject instead of silently scanning zero.
        if 0 < value < MIN_SAMPLING_RATE:
            raise serializers.ValidationError(
                f"Sampling rate must be 0 (paused) or at least {MIN_SAMPLING_RATE} (0.01%)."
            )
        return value

    def validate_tags(self, value: list[str]) -> list[str]:
        # The list endpoint's tags filter is comma-separated, so a comma inside a tag name
        # would make the tag impossible to filter on.
        if any("," in tag for tag in value):
            raise serializers.ValidationError("Tags cannot contain commas.")
        return value

    def _reject_scanner_type_change(self, attrs: dict[str, Any]) -> None:
        if self.instance is None or "scanner_type" not in attrs:
            return
        if attrs["scanner_type"] != self.instance.scanner_type:
            raise serializers.ValidationError(
                {"scanner_type": "Scanner type is fixed after creation. Create a new scanner to use a different type."}
            )

    def _validate_scanner_config(self, attrs: dict[str, Any]) -> None:
        # Skip when neither field is touched on PATCH — the existing combination has already been validated.
        if "scanner_config" not in attrs and "scanner_type" not in attrs:
            return
        scanner_type = attrs.get("scanner_type", getattr(self.instance, "scanner_type", None))
        scanner_config = attrs.get("scanner_config", getattr(self.instance, "scanner_config", None))
        if scanner_type is None:
            return  # Upstream `scanner_type` ChoiceField rejects this on create; PATCH with no instance is unreachable.
        message = scanner_config_error(ScannerType(scanner_type), scanner_config)
        if message is not None:
            raise serializers.ValidationError({"scanner_config": message})

    def _validate_and_strip_query(self, attrs: dict[str, Any]) -> None:
        if "query" not in attrs:
            return
        try:
            RecordingsQuery.model_validate(attrs["query"])
        except PydanticValidationError:
            raise serializers.ValidationError({"query": "Recording filter is invalid."})
        _reject_direct_experiment_exposure(attrs["query"])
        # Persist exactly what the user sent (validated), minus the date keys the schedule controls.
        attrs["query"] = {k: v for k, v in attrs["query"].items() if k not in _QUERY_FIELDS_TO_STRIP}
        if len(json.dumps(attrs["query"], separators=(",", ":")).encode()) > _MAX_QUERY_BYTES:
            raise serializers.ValidationError(
                {"query": f"Recording filter is too large. Keep it under {_MAX_QUERY_BYTES // 1000} KB."}
            )

    def to_representation(self, instance: ReplayScanner) -> dict[str, Any]:
        data = super().to_representation(instance)
        # `is not None` (not falsy) so empty-dict queries still revalidate against future schema changes.
        if data.get("query") is not None:
            try:
                RecordingsQuery.model_validate(data["query"])
            except PydanticValidationError:
                logger.exception("replay_vision.scanner.malformed_query", scanner_id=str(instance.id))
                data["query"] = None
        # Don't disclose an experiment (its id and variants) to a viewer who can't access it: a
        # scanner is viewable at a coarser grain than its targeted experiment. Mirrors the write-side
        # check in validate_experiment_targeting — a caller without experiment access sees null.
        if data.get("experiment_targeting") and not self._can_view_targeted_experiment(data["experiment_targeting"]):
            data["experiment_targeting"] = None
        return data

    def _can_view_targeted_experiment(self, targeting: dict[str, Any]) -> bool:
        experiment_id = targeting.get("experiment_id")
        if experiment_id is None:
            return False
        get_team = self.context.get("get_team")
        if get_team is None:  # no request context (e.g. internal serialization); don't over-redact
            return True
        return is_experiment_accessible(self.user_access_control, get_team().id, experiment_id)

    def create(self, validated_data: dict[str, Any]) -> ReplayScanner:
        team = self.context["get_team"]()
        user = acting_user(self.context)
        if not team.organization.is_ai_data_processing_approved:
            raise serializers.ValidationError(
                "Your organization needs to allow AI analysis before you can create a Replay Vision scanner."
            )
        # Tags become TaggedItem rows below, not a scanner column.
        tags = validated_data.pop("tags", None)
        # One transaction so a failed tag write can't leave an untagged scanner behind. Side effects stay outside.
        with transaction.atomic():
            try:
                # last_swept_at is seeded a settle-interval back by the model default (initial_watermark) to avoid a cold start.
                scanner = ReplayScanner.objects.create(team=team, created_by=user, **validated_data)
            except IntegrityError as e:
                self._reraise_unique_name_violation(e)
            self._attempt_set_tags(tags, scanner)
        _refresh_estimate_fail_soft(scanner)
        # Every scanner starts with a built-in featured digest so the overview has a summary to show.
        provision_scanner_digest(scanner, user)
        report_user_action(
            user,
            "replay_vision_scanner_created",
            _scanner_lifecycle_properties(scanner),
            team=team,
            request=self.context.get("request"),
        )
        return scanner

    def update(self, instance: ReplayScanner, validated_data: dict[str, Any]) -> ReplayScanner:
        # Tags are not a scanner column: keep them out of the before/after getattr diff below.
        # The mixin's update (reached via super()) persists them as TaggedItem rows.
        tags = validated_data.pop("tags", None)
        # Compared as tagify()d names, since that is what set_tags_on_object stores.
        tags_changed = tags is not None and {tagify(t) for t in tags} != set(
            instance.tagged_items.values_list("tag__name", flat=True)
        )
        # The UI PATCHes the whole form on save, so edits are detected by comparing values, not keys.
        before = {field: getattr(instance, field) for field in validated_data}
        was_enabled = instance.enabled
        limit_changed = "credit_limit" in validated_data and validated_data["credit_limit"] != instance.credit_limit
        # One transaction so a failed tag write can't leave the columns updated with stale tags. Side effects stay outside.
        with transaction.atomic():
            try:
                scanner = super().update(instance, validated_data)
            except IntegrityError as e:
                self._reraise_unique_name_violation(e)
        if limit_changed:
            # A changed limit starts a fresh notification cycle: reaching the new limit is news.
            # Targeted update because the model save deliberately never writes this sweep-owned column.
            ReplayScanner.objects.filter(pk=scanner.pk).update(limit_notified_period_start=None)
            scanner.limit_notified_period_start = None
        # Model save clears `estimated_at` when volume inputs change. Re-enables only refresh inline when
        # the background refresher has fallen behind, so a stale number never enters the quota sum.
        needs_refresh = scanner.estimated_at is None or (
            scanner.enabled and not was_enabled and timezone.now() - scanner.estimated_at >= ESTIMATE_STALE_AFTER
        )
        if needs_refresh:
            _refresh_estimate_fail_soft(scanner)
        changed_fields = sorted(field for field, value in before.items() if getattr(scanner, field) != value)
        if tags_changed:
            changed_fields = sorted([*changed_fields, "tags"])
        request = self.context.get("request")
        user = acting_user(self.context)
        team = self.context["get_team"]()
        if scanner.enabled != was_enabled:
            report_user_action(
                user,
                "replay_vision_scanner_enabled" if scanner.enabled else "replay_vision_scanner_disabled",
                _scanner_lifecycle_properties(scanner),
                team=team,
                request=request,
            )
        # A pure enable/disable toggle is not a config edit. A save that also flips enabled fires both events.
        if any(field != "enabled" for field in changed_fields):
            report_user_action(
                user,
                "replay_vision_scanner_edited",
                {**_scanner_lifecycle_properties(scanner), "edited_fields": changed_fields},
                team=team,
                request=request,
            )
        return scanner

    @staticmethod
    def _reraise_unique_name_violation(error: IntegrityError) -> NoReturn:
        # Narrow to the unique-name constraint so other future constraints aren't mis-reported as duplicates.
        if "replay_scanner_unique_team_name" in str(error):
            raise serializers.ValidationError({"name": "A scanner with this name already exists in this team."})
        raise error


SCANNER_ORDER_FIELDS = (
    "name",
    "created_at",
    "updated_at",
    "scanner_type",
    "enabled",
    "sampling_rate",
    "created_by",
    "credits_this_month",
)
_SCANNER_ENABLED_CHOICES = frozenset({"enabled", "disabled"})
# Map `?enabled=true/false/1/0` to the CSV form so the conventional boolean stays supported.
_SCANNER_ENABLED_ALIASES = {"true": "enabled", "false": "disabled", "1": "enabled", "0": "disabled"}


class _ScannerOrderByFilter(OrderByFilter):
    """Plain columns + `created_by` sorted by the display label so UI order matches the column."""

    _allowed_keys = frozenset(SCANNER_ORDER_FIELDS)

    def _handle(self, qs: QuerySet[ReplayScanner], key: str, descending: bool) -> QuerySet[ReplayScanner]:
        if key == "credits_this_month":
            # Same window and pricing as `credits_this_month`, in SQL so the database can order by it.
            organization_id = qs.values_list("team__organization_id", flat=True).first()
            if organization_id is None:
                return qs.order_by(self._tiebreaker)
            period = current_period_bounds(organization_id)
            spend = (
                ReplayObservation.objects.filter(
                    scanner_id=OuterRef("pk"),
                    status=ObservationStatus.SUCCEEDED,
                    created_at__gte=period.start,
                    created_at__lt=period.end,
                )
                .order_by()
                .values("scanner_id")
                .annotate(total=Sum(observation_credits_case()))
                .values("total")
            )
            qs = qs.annotate(
                _order_credits=Coalesce(Subquery(spend, output_field=IntegerField()), Value(0)),
            )
            return self._order_plain(qs, "_order_credits", descending)
        if key == "created_by":
            # Mirrors the frontend `createdByLabel` fallback so a row rendered "Brown" sorts on "Brown", not its email.
            qs = qs.annotate(
                _order_created_by=Coalesce(
                    NullIf(F("created_by__first_name"), Value("")),
                    NullIf(F("created_by__last_name"), Value("")),
                    F("created_by__email"),
                    output_field=CharField(),
                ),
            )
            return self._order_nulls_last(qs, "_order_created_by", descending)
        return self._order_plain(qs, key, descending)


class ReplayScannerFilter(django_filters.FilterSet):
    enabled = django_filters.CharFilter(
        method="_filter_enabled",
        help_text="Filter by enabled state. Accepts a comma-separated list of `enabled`/`disabled`.",
    )
    scanner_type = MultiChoiceFilter(
        field_name="scanner_type",
        valid_choices=frozenset(v for v, _ in ScannerType.choices),
        help_text=("Filter by scanner type (monitor, classifier, scorer, summarizer). Accepts a comma-separated list."),
    )
    emits_signals = django_filters.BooleanFilter(
        field_name="emits_signals",
        help_text="Filter to scanners that emit Signals.",
    )
    created_by = django_filters.CharFilter(
        method="_filter_created_by",
        help_text="Filter to scanners created by the given user IDs (comma-separated).",
    )
    search = django_filters.CharFilter(
        method="_filter_search",
        help_text="Case-insensitive substring match across name, description, and the prompt in scanner_config.",
    )
    experiment_id = django_filters.CharFilter(
        method="_filter_experiment_id",
        help_text="Filter to scanners whose targeting watches the given experiment.",
    )
    tags = django_filters.CharFilter(
        method="_filter_tags",
        help_text="Filter to scanners carrying at least one of the given tags (comma-separated).",
    )
    order_by = _ScannerOrderByFilter(
        help_text=f"Sort scanners by {', '.join(SCANNER_ORDER_FIELDS)}. Prefix with `-` for descending.",
    )

    class Meta:
        model = ReplayScanner
        fields = ["enabled", "scanner_type", "emits_signals", "created_by", "search", "experiment_id", "tags"]

    @staticmethod
    def _filter_enabled(queryset: QuerySet[ReplayScanner], _name: str, value: str) -> QuerySet[ReplayScanner]:
        # `method=` bypasses `MultiChoiceFilter.filter`, so call the shared validator directly.
        normalized = ",".join(_SCANNER_ENABLED_ALIASES.get(v.strip().lower(), v) for v in split_csv(value))
        values = set(validate_csv_choices(normalized, _SCANNER_ENABLED_CHOICES, "enabled"))
        if not values or values == _SCANNER_ENABLED_CHOICES:
            return queryset
        return queryset.filter(enabled=("enabled" in values))

    @staticmethod
    def _filter_created_by(queryset: QuerySet[ReplayScanner], _name: str, value: str) -> QuerySet[ReplayScanner]:
        tokens = split_csv(value)
        if not tokens:
            return queryset
        invalid = sorted(t for t in tokens if not t.isdecimal())
        if invalid:
            raise ValidationError({"created_by": f"Non-numeric value(s) {invalid}; user IDs must be integers."})
        return queryset.filter(created_by_id__in=tokens)

    def _filter_experiment_id(
        self, queryset: QuerySet[ReplayScanner], _name: str, value: str
    ) -> QuerySet[ReplayScanner]:
        # An int, not NumberFilter's Decimal, which the JSONField lookup can't serialize to JSON.
        # isdecimal, not isdigit: isdigit accepts characters like superscripts that int() rejects.
        # Cap at the Postgres bigint max the id column can hold: a larger value can't be a real PK,
        # and feeding it to the id lookup below raises NumericValueOutOfRange (a 500) instead of a 400.
        stripped = value.strip()
        if not stripped.isdecimal() or not 1 <= int(stripped) <= 9223372036854775807:
            raise ValidationError({"experiment_id": "Must be a positive integer."})
        experiment_id = int(stripped)
        # Gate on the caller's experiment access, mirroring validate_experiment_targeting and
        # _can_view_targeted_experiment: without it, a scanner-viewer could pass ?experiment_id= to
        # confirm (by match count and returned scanner names) that a scanner targets an experiment
        # they can't otherwise see. An inaccessible or nonexistent id reads as no matches.
        # Reuse the viewset's resolved team and access control rather than reparsing the URL:
        # view.team_id handles @current and token-derived teams, and user_access_control is already built.
        view = self.request.parser_context.get("view") if self.request else None
        if view is None or not is_experiment_accessible(view.user_access_control, view.team_id, experiment_id):
            return queryset.none()
        return queryset.filter(experiment_targeting__experiment_id=experiment_id)

    @staticmethod
    def _filter_search(queryset: QuerySet[ReplayScanner], _name: str, value: str) -> QuerySet[ReplayScanner]:
        q = value.strip()
        if not q:
            return queryset
        return queryset.filter(
            Q(name__icontains=q) | Q(description__icontains=q) | Q(scanner_config__prompt__icontains=q)
        )

    @staticmethod
    def _filter_tags(queryset: QuerySet[ReplayScanner], _name: str, value: str) -> QuerySet[ReplayScanner]:
        # Writes normalize tag names through tagify(), so filter values must be normalized the same way.
        tags = [tagify(tag) for tag in split_csv(value)]
        if not tags:
            return queryset
        # distinct(): a scanner matching several requested tags would otherwise appear once per match.
        return queryset.filter(tagged_items__tag__name__in=tags).distinct()


class ObserveRequestSerializer(serializers.Serializer):
    """Body of POST /vision/scanners/{id}/observe/."""

    session_id = serializers.CharField(
        max_length=MAX_SESSION_ID_LENGTH,
        help_text="ID of the session recording to apply the scanner to.",
    )


class ObserveResponseSerializer(serializers.Serializer):
    """Async-accepted response for POST /vision/scanners/{id}/observe/."""

    workflow_id = serializers.CharField(
        help_text=(
            "Temporal workflow id for this scanner application. Look up the resulting "
            "ReplayObservation via GET /vision/scanners/{id}/observations/?session_id=<session_id>."
        ),
    )


# One request can start at most this many scans. Bounds the fan-out of a single bulk trigger well
# under the in-flight caps; the frontend selects from one loaded page, so this is rarely the binding
# limit — the concurrency headroom usually is.


class BulkObserveRequestSerializer(serializers.Serializer):
    """Body of POST /vision/scanners/{id}/bulk_observe/."""

    session_ids = serializers.ListField(
        child=serializers.CharField(max_length=MAX_SESSION_ID_LENGTH),
        allow_empty=False,
        max_length=MAX_SESSIONS_PER_SCAN,
        help_text=(
            f"Session recording IDs to scan on demand, at most {MAX_SESSIONS_PER_SCAN} per request. "
            "Scans start until the in-flight limit or monthly credit quota is reached; the rest are "
            "reported as skipped rather than failing the whole batch. Already-running sessions are a no-op."
        ),
    )


class BulkObserveResultSerializer(serializers.Serializer):
    """Per-session outcome of a bulk scan trigger."""

    session_id = serializers.CharField(help_text="The session recording this outcome is for.")
    # Named scan_outcome (not outcome) so its generated enum doesn't collide with other products'
    # `outcome` enums — a bare `outcome` ChoiceField forces the shared OutcomeEnum to be renamed.
    scan_outcome = serializers.ChoiceField(
        choices=[
            ("started", "Started"),
            ("already_running", "Already running"),
            ("already_scanned", "Already scanned"),
            ("skipped_limit", "Skipped, in-flight limit reached"),
            ("skipped_quota", "Skipped, the org's credit quota for this period was reached"),
            ("skipped_scanner_limit", "Skipped, scanner's own credit limit reached"),
            ("failed", "Failed to start"),
        ],
        help_text=(
            "'started' - a scan workflow was kicked off; 'already_running' - a scan for this session is "
            "already in flight (no-op, not recharged); 'already_scanned' - this scanner already has a "
            "finished observation for this session, so nothing was started and nothing was charged (read "
            "it back, or use the retry action to run it again); 'skipped_limit' - the in-flight cap was "
            "reached before this session; 'skipped_quota' - the org's credit quota for this period would "
            "be exceeded; 'skipped_scanner_limit' - this scanner's own credit limit would be exceeded; "
            "'failed' - the workflow failed to start."
        ),
    )


class ObserveAlreadyScannedSerializer(serializers.Serializer):
    """200 from POST /vision/scanners/{id}/observe/ - nothing started, the answer already exists."""

    observation_id = serializers.UUIDField(
        help_text=(
            "The settled observation this scanner already has for the session. Nothing was started and "
            "nothing was charged; read it from /vision/scanners/{id}/observations/, or use the retry "
            "action on it to scan the session again."
        ),
    )


class BulkObserveResponseSerializer(serializers.Serializer):
    """Result of POST /vision/scanners/{id}/bulk_observe/ — partial success by design."""

    started = serializers.IntegerField(help_text="How many new scans were started.")
    results = BulkObserveResultSerializer(
        many=True,
        help_text="Per-session outcomes, in request order (deduplicated).",
    )


class InlineScanRequestSerializer(serializers.Serializer):
    """Body of POST /vision/scanners/inline_scan/ - a prompt plus the sessions to point it at."""

    session_ids = serializers.ListField(
        child=serializers.CharField(max_length=MAX_SESSION_ID_LENGTH),
        allow_empty=False,
        max_length=MAX_SESSIONS_PER_SCAN,
        help_text=(
            f"Session recording IDs to scan, at most {MAX_SESSIONS_PER_SCAN} per request. Scans start "
            "until the in-flight limit or monthly credit quota is reached; the rest are reported as "
            "skipped rather than failing the whole batch."
        ),
    )
    prompt = serializers.CharField(
        max_length=MAX_PROMPT_LENGTH,
        help_text="What to look for in these sessions, in plain language. The same instruction a saved scanner carries.",
    )
    scanner_type = serializers.ChoiceField(
        choices=ScannerType.choices,
        required=False,
        default=ScannerType.MONITOR,
        help_text="What the scan produces. Defaults to monitor, an open-ended observation against the prompt.",
    )
    scanner_config = serializers.JSONField(
        required=False,
        default=dict,
        help_text=(
            "Type-specific configuration beyond the prompt: `tags` for a classifier, `scale` for a scorer, "
            "optional `length` for a summarizer. Omit it for a monitor. `prompt` belongs in the `prompt` "
            "field and is rejected here."
        ),
    )
    model = serializers.ChoiceField(
        choices=ScannerModel.choices,
        required=False,
        default=ScannerModel.GEMINI_3_FLASH_PREVIEW,
        help_text="Model to scan with. Determines what each observation costs in credits.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        config = attrs["scanner_config"]
        if not isinstance(config, dict):
            raise serializers.ValidationError({"scanner_config": "Scanner configuration must be a JSON object."})
        if "prompt" in config:
            raise serializers.ValidationError({"scanner_config": "Set the prompt in `prompt`, not here."})
        # One config from here on, validated exactly like a saved scanner's. The key covers it whole.
        merged = {**config, "prompt": attrs["prompt"]}
        message = scanner_config_error(ScannerType(attrs["scanner_type"]), merged)
        if message is not None:
            raise serializers.ValidationError({"scanner_config": message})
        attrs["scanner_config"] = merged
        return attrs


class InlineScanResponseSerializer(BulkObserveResponseSerializer):
    """`bulk_observe`'s partial-success shape plus the id to read the results back through."""

    scan_id = serializers.UUIDField(
        allow_null=True,
        help_text=(
            "Read results from `/vision/scanners/{scan_id}/observations/`. Stable for a given prompt and "
            "model, so asking the same question again returns the same id. Null when nothing was started "
            "and nothing existed to read, which happens when the quota is already used up."
        ),
    )


class EstimateRequestSerializer(serializers.Serializer):
    """Body of POST /vision/scanners/estimate/ — a proposed, unsaved scanner config."""

    query = extend_schema_field(RecordingsQuery)(  # type: ignore[arg-type, type-var]
        serializers.JSONField(
            required=False,
            help_text=(
                "Proposed `RecordingsQuery` for the candidate filter. `date_from`/`date_to` are "
                "ignored — the estimate always uses a fixed 30-day lookback. Omit to estimate "
                "against all recordings."
            ),
        )
    )
    sampling_rate = serializers.FloatField(
        required=False,
        default=1.0,
        min_value=0.0,
        max_value=1.0,
        help_text="0..1 downsample applied to matched sessions. Defaults to 1.0 (no downsampling).",
    )
    sampling_mode = serializers.ChoiceField(
        choices=SamplingMode.choices,
        required=False,
        default=SamplingMode.COMPREHENSIVE,
        help_text=(
            "Quality pre-filter applied to the matched-session count, mirroring the sweep's candidate query. "
            "Defaults to comprehensive (no filter)."
        ),
    )
    scanner_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "The scanner being edited, excluded from `other_enabled_scanners_monthly_credits` so its stored estimate "
            "isn't double-counted in the forecast. Omit (or null) when estimating a brand-new scanner."
        ),
    )
    model = serializers.ChoiceField(
        choices=ScannerModel.choices,
        required=False,
        default=ScannerModel.GEMINI_3_FLASH_PREVIEW,
        help_text="Proposed model; determines `credits_per_observation` in the response.",
    )

    experiment_targeting = ScannerExperimentTargetingField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Proposed experiment targeting, merged into the query as its exposure filter the same "
            "way a saved scanner derives it. The estimate then runs as the requesting user."
        ),
    )

    def validate_query(self, value: dict[str, Any]) -> dict[str, Any]:
        try:
            RecordingsQuery.model_validate(value)
        except PydanticValidationError:
            raise serializers.ValidationError("Recording filter is invalid.")
        _reject_direct_experiment_exposure(value)
        return {k: v for k, v in value.items() if k not in _QUERY_FIELDS_TO_STRIP}


class ScannerTypeStatsSerializer(serializers.Serializer):
    """Per-scanner-type count of enabled vs total scanners."""

    enabled = serializers.IntegerField(help_text="Number of enabled scanners of this type.")
    total = serializers.IntegerField(help_text="Number of scanners of this type (enabled + disabled).")


class ScannerStatsByTypeSerializer(serializers.Serializer):
    """One `ScannerTypeStats` per scanner type — explicit fields give callers a typed shape, not `Record<string, …>`."""

    monitor = ScannerTypeStatsSerializer()
    classifier = ScannerTypeStatsSerializer()
    scorer = ScannerTypeStatsSerializer()
    summarizer = ScannerTypeStatsSerializer()


class ScannerStatsResponseSerializer(serializers.Serializer):
    """Team-wide scanner counts independent of any list-filter state."""

    total = serializers.IntegerField(help_text="Total scanners on the team.")
    enabled = serializers.IntegerField(help_text="Number of enabled scanners on the team.")
    by_type = ScannerStatsByTypeSerializer(
        help_text="Per-scanner-type breakdown (monitor / classifier / scorer / summarizer)."
    )


class ScannerCreatorsResponseSerializer(serializers.Serializer):
    """Distinct creators across all scanners on the team — feeds the `Created by` filter dropdown."""

    creators = UserBasicSerializer(
        many=True,
        help_text=(
            "Users who created at least one scanner on this team. Returned regardless of pagination state "
            "so the dropdown stays stable across pages."
        ),
    )


class EstimateResponseSerializer(serializers.Serializer):
    """Forward-looking volume and credit-cost estimate for a proposed scanner."""

    matched_sessions_in_window = serializers.IntegerField(
        help_text=(
            "Distinct sessions matching the query within the 30-day lookback, after the sampling_mode quality "
            "filter but before random sampling."
        ),
    )
    window_days = serializers.IntegerField(
        help_text=(
            "Lookback window the estimate is based on. Normally 30; smaller when the team has fewer days of recordings."
        ),
    )
    estimated_observations_per_month = serializers.IntegerField(
        help_text=(
            "Projected monthly observations: quality-filtered matched sessions scaled to 30 days, times sampling_rate."
        ),
    )
    credits_per_observation = serializers.IntegerField(
        help_text="Credits one observation costs at the proposed `model` (1 credit = $0.01).",
    )
    estimated_credits_per_month = serializers.IntegerField(
        help_text="`estimated_observations_per_month` priced at `credits_per_observation`.",
    )
    other_enabled_scanners_monthly_credits = serializers.IntegerField(
        help_text=(
            "Credit-weighted projected monthly spend of the org's other enabled scanners (excluding `scanner_id`), "
            "from their cached estimates. Read from the same snapshot as this estimate so the forecast can't "
            "double-count the edited scanner."
        ),
    )
    active_backfill_credits = serializers.IntegerField(
        help_text=(
            "Committed-but-unspent credits of the org's active backfills, the same figure the quota snapshot's "
            "projection carries. A one-off charge rather than a monthly rate, so the forecast shows it as its own "
            "segment instead of adding it to a per-month total."
        ),
    )
    sampling_rate = serializers.FloatField(
        help_text="Sampling rate applied to the projection. Echoed from the request.",
    )


class SuggestTagsRequestSerializer(serializers.Serializer):
    """Body of POST /vision/scanners/suggest_tags/ — the classifier config currently being edited."""

    prompt = serializers.CharField(
        max_length=10000,
        help_text="The classifier's instruction prompt — the single dimension to categorize sessions by.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        default=list,
        max_length=200,
        help_text="The categories already configured, so suggestions never duplicate one the user has.",
    )
    multi_label = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether the classifier assigns multiple tags per session.",
    )
    allow_freeform_tags = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether the classifier may emit tags outside the fixed vocabulary.",
    )
    scanner_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "Existing scanner to ground suggestions in its own observations (the tags and reasoning it has "
            "already produced on real recordings). Omit for an unsaved scanner."
        ),
    )


class TagSuggestionSerializer(serializers.Serializer):
    """One grounded tag suggestion."""

    tag = serializers.CharField(help_text="Suggested tag to add to the vocabulary, normalized to lowercase.")
    rationale = serializers.CharField(
        help_text="One sentence explaining the specific evidence this tag is grounded in."
    )
    source = serializers.ChoiceField(  # type: ignore[assignment]
        choices=["observed", "product", "prompt"],
        help_text=(
            "Primary grounding: observed=a category this scanner already emitted on recordings; "
            "product=the org's events/screens; prompt=the scanner's stated goal."
        ),
    )


class SuggestTagsResponseSerializer(serializers.Serializer):
    """Grounded tag suggestions for the classifier config editor."""

    suggestions = TagSuggestionSerializer(
        many=True,
        help_text="Suggested tags to add, most relevant first. May be empty when the evidence is too thin.",
    )


class DraftScannerRequestSerializer(serializers.Serializer):
    """Body of POST /vision/scanners/draft/ — the user's goal, stated in their own words."""

    goal = serializers.CharField(
        max_length=2000,
        help_text="What the user wants to accomplish, e.g. 'find out where users get stuck during onboarding'.",
    )


class DraftScannerResponseSerializer(serializers.Serializer):
    """An AI-drafted scanner configuration, ready to seed the creation wizard. Nothing is persisted."""

    name = serializers.CharField(help_text="Drafted scanner name.")
    description = serializers.CharField(help_text="Drafted one-sentence description.")
    scanner_type = serializers.ChoiceField(
        choices=ScannerType.choices, help_text="The scanner type the draft picked for the goal."
    )
    scanner_config = serializers.JSONField(
        help_text="Type-specific config for the drafted `scanner_type`; always includes `prompt`."
    )
    rationale = serializers.CharField(
        allow_blank=True,
        help_text="Why the draft picked this scanner type and configuration, addressed to the user.",
    )
    query = extend_schema_field(RecordingsQuery)(  # type: ignore[arg-type, type-var]
        serializers.JSONField(
            allow_null=True,
            help_text=(
                "`RecordingsQuery` narrowing which sessions get scanned; null when the draft targets every session."
            ),
        )
    )


class ScannerImpactSerializer(serializers.Serializer):
    """Who this scanner's findings affected in the window; counted from observations, not estimated."""

    affected_sessions = serializers.IntegerField(
        read_only=True,
        help_text=(
            "Distinct sessions with an affected observation in the window. For monitors only verdict-yes "
            "observations count; for other scanner types every succeeded observation counts."
        ),
    )
    affected_users = serializers.IntegerField(
        read_only=True,
        help_text=(
            "Distinct users behind the affected sessions, by distinct ID. May include anonymous "
            "device IDs when the recorded sessions were not identified."
        ),
    )
    sessions_without_user = serializers.IntegerField(
        read_only=True,
        help_text="Affected sessions whose recording carried no distinct ID at all.",
    )
    window_days = serializers.IntegerField(
        read_only=True,
        help_text="Trailing window the counts cover, in days.",
    )


class _ImpactQualifiersSerializer(serializers.Serializer):
    """Shared impact parameters. Monitors take none; classifiers require `tag`; scorers require a score bound."""

    window_days = serializers.IntegerField(
        required=False,
        default=DEFAULT_IMPACT_WINDOW_DAYS,
        min_value=1,
        max_value=90,
        help_text="Trailing window of observations to count. Defaults to 30 days.",
    )
    tag = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        max_length=MAX_TAG_LENGTH,
        help_text=(
            "Classifier scanners only, required for them: count sessions carrying this tag "
            "(fixed or freeform). Not applicable to other scanner types."
        ),
    )
    min_score = serializers.FloatField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Scorer scanners only: count sessions scoring at or above this value. Scorers require "
            "`min_score` and/or `max_score`. Not applicable to other scanner types."
        ),
    )
    max_score = serializers.FloatField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Scorer scanners only: count sessions scoring at or below this value.",
    )


class ScannerImpactQuerySerializer(_ImpactQualifiersSerializer):
    """Query parameters of GET /vision/scanners/:id/impact/."""


class AffectedCohortRequestSerializer(_ImpactQualifiersSerializer):
    """Body of POST /vision/scanners/:id/affected_cohort/. Same qualifiers as the impact GET."""


class AffectedCohortResponseSerializer(serializers.Serializer):
    """The static cohort created from the scanner's affected users."""

    cohort_id = serializers.IntegerField(
        read_only=True,
        help_text="ID of the created static cohort; usable anywhere cohorts are (funnels, surveys, experiments).",
    )
    name = serializers.CharField(
        read_only=True,
        help_text="Generated cohort name, stamped with the creation date since the snapshot doesn't live-update.",
    )
    users_in_cohort = serializers.IntegerField(
        read_only=True,
        help_text=(
            "Persons actually in the created cohort. Can be lower than `affected_users`: matched "
            "distinct IDs without a person profile are dropped, and merged persons deduplicate."
        ),
    )
    window_days = serializers.IntegerField(
        read_only=True,
        help_text="Trailing window the cohort was drawn from, in days.",
    )


class ScannerSelfDrivingStatsSerializer(serializers.Serializer):
    """Response of GET /vision/scanners/:id/self_driving_stats/."""

    signals_emitted = serializers.IntegerField(
        help_text="Signals this scanner has pushed into the Signals inbox, all time."
    )
    reports_contributed = serializers.IntegerField(
        help_text=(
            "Signal reports that include at least one of this scanner's signals. Reports usually "
            "aggregate signals from several sources, so this counts contributions, not sole causes."
        )
    )
    prs_opened = serializers.IntegerField(help_text="Implementation PRs opened by self-driving on those reports.")
    prs_merged = serializers.IntegerField(help_text="Of the opened PRs, how many have merged.")


@extend_schema_view(
    list=extend_schema(
        parameters=[
            # OrderingFilter renders as an array by default, which the MCP client serializes as a JSON-bracketed
            # string the filter rejects. Declare it as a single-value string enum so it serializes as ?order_by=field.
            OpenApiParameter(
                "order_by",
                str,
                OpenApiParameter.QUERY,
                required=False,
                enum=ordering_enum(SCANNER_ORDER_FIELDS),
                description=(f"Sort scanners by {', '.join(SCANNER_ORDER_FIELDS)}. Prefix with `-` for descending."),
            )
        ]
    )
)
class ReplayScannerViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    """CRUD for Replay Vision scanners."""

    scope_object = "replay_scanner"
    # Custom actions must be listed explicitly or personal-API-key callers 403 silently.
    scope_object_read_actions = ["list", "retrieve", "creators", "stats", "self_driving_stats"]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "destroy",
        "observe",
        "bulk_observe",
        "inline_scan",
    ]
    serializer_class = ReplayScannerSerializer
    queryset = ReplayScanner.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = ReplayScannerFilter
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    # Same authorization as /observe/: configuring a scanner indirectly exposes recording contents.
    _CONFIG_ACTIONS = {"create", "update", "partial_update"}

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        if self.action in self._CONFIG_ACTIONS:
            return ["replay_scanner:write", "session_recording:read"]
        # Falls through to AccessControlViewSetMixin's scope requirements for its
        # access_controls/resource_access_controls/users_with_access actions.
        return super().dangerously_get_required_scopes(request, view)

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if self.action in self._CONFIG_ACTIONS and not self.user_access_control.check_access_level_for_resource(
            "session_recording", required_level="viewer"
        ):
            raise PermissionDenied("Configuring a Replay Vision scanner requires session_recording read access.")

    def safely_get_queryset(self, queryset: QuerySet[ReplayScanner]) -> QuerySet[ReplayScanner]:
        # `queryset` comes off the fail-closed default manager, so every action here — list, retrieve,
        # update, destroy — is configured-only. An inline scan's id is not a scanner id as far as this
        # viewset is concerned; its results are read through the observations endpoint instead.
        return (
            queryset.filter(team_id=self.team_id)
            .select_related("created_by")
            # prefetched_tags feeds the tags in to_representation; without it list serialization is N+1.
            .prefetch_related(
                Prefetch(
                    "tagged_items",
                    queryset=TaggedItem.objects.select_related("tag"),
                    to_attr="prefetched_tags",
                )
            )
            .order_by("name", "id")
        )

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response = super().retrieve(request, *args, **kwargs)
        # Funnel entry point (created → viewed → rated).
        report_user_action(
            cast(User, request.user),
            "replay_vision_scanner_viewed",
            {"scanner_id": str(response.data["id"])},
            team=self.team,
            request=request,
        )
        return response

    def perform_destroy(self, instance: ReplayScanner) -> None:
        # Snapshot lifecycle props before the row is deleted.
        properties = _scanner_lifecycle_properties(instance)
        super().perform_destroy(instance)
        report_user_action(
            cast(User, self.request.user),
            "replay_vision_scanner_deleted",
            properties,
            team=self.team,
            request=self.request,
        )

    @extend_schema(responses={200: ScannerCreatorsResponseSerializer})
    @action(detail=False, methods=["get"], pagination_class=None)
    def creators(self, request: Request, **kwargs: Any) -> Response:
        """Distinct creators across the team's scanners — feeds the `Created by` filter dropdown."""
        # Mirror the per-resource RBAC the `list` action applies — the dropdown must not leak creator
        # identities for scanners the caller can't see.
        accessible = self.user_access_control.filter_queryset_by_access_level(
            ReplayScanner.objects.filter(team_id=self.team_id, created_by_id__isnull=False)
        )
        users = User.objects.filter(
            id__in=accessible.values_list("created_by_id", flat=True),
        ).order_by("first_name", "last_name", "email", "id")
        return Response({"creators": UserBasicSerializer(users, many=True).data})

    @extend_schema(responses={200: ScannerStatsResponseSerializer})
    @action(detail=False, methods=["get"], pagination_class=None)
    def stats(self, request: Request, **kwargs: Any) -> Response:
        """Team-wide scanner counts — independent of list filters, so the overview stays stable."""
        accessible = self.user_access_control.filter_queryset_by_access_level(
            ReplayScanner.objects.filter(team_id=self.team_id)
        )
        # `.order_by()` so the default ordering doesn't leak into GROUP BY.
        rows = accessible.order_by().values("scanner_type", "enabled").annotate(c=Count("*"))
        by_type: dict[str, dict[str, int]] = {value: {"enabled": 0, "total": 0} for value, _ in ScannerType.choices}
        total = 0
        enabled = 0
        for row in rows:
            bucket = by_type.setdefault(row["scanner_type"], {"enabled": 0, "total": 0})
            bucket["total"] += row["c"]
            total += row["c"]
            if row["enabled"]:
                bucket["enabled"] += row["c"]
                enabled += row["c"]
        return Response({"total": total, "enabled": enabled, "by_type": by_type})

    @extend_schema(
        request=ObserveRequestSerializer,
        responses={
            200: ObserveAlreadyScannedSerializer,
            202: ObserveResponseSerializer,
            503: OpenApiResponse(
                response=ReplayVisionErrorSerializer, description="The observation workflow couldn't be started."
            ),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="observe",
        required_scopes=["replay_scanner:write", "session_recording:read"],
    )
    def observe(self, request: Request, **kwargs: Any) -> Response:
        """Apply this scanner to one specific session, on demand. Returns 202 with the workflow handle."""
        scanner = self.get_object()
        user = cast(User, request.user)
        # Observation output exposes recording contents, so observe requires session_recording read.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Triggering an on-demand observation requires session_recording read access.")
        # Every scan entrypoint gates this: create_observation fails closed on consent once the workflow
        # is already running, so without the check the caller gets a 202 for a scan that never happens.
        if not self.team.organization.is_ai_data_processing_approved:
            raise ValidationError(
                "Your organization needs to allow AI analysis before you can run a Replay Vision scan."
            )

        try:
            check_observation_quota(self.team.organization_id, observation_credits_for_model(scanner.model))
        except QuotaLimitExceeded:
            self._report_quota_exhausted(scanner, "on_demand")
            raise
        # Deliberately outside the analytics wrapper above: that event means "the org ran out of
        # credits", and firing it for a self-imposed per-scanner cap would corrupt that metric.
        check_scanner_quota(scanner)
        check_team_in_flight_capacity(self.team.id)

        body = ObserveRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        session_id: str = body.validated_data["session_id"]

        workflow_id, outcome = start_apply_scanner_workflow(
            scanner, session_id, triggered_by_user_id=user.id, trigger=ObservationTrigger.ON_DEMAND
        )
        if outcome is WorkflowStartOutcome.ALREADY_SCANNED:
            existing = ReplayObservation.objects.filter(scanner_id=scanner.id, session_id=session_id).only("id").first()
            if existing is not None:
                # 200, not 202: nothing was accepted for processing, so hand back what already exists.
                return Response(
                    ObserveAlreadyScannedSerializer({"observation_id": existing.id}).data,
                    status=status.HTTP_200_OK,
                )
            # A concurrent retry deleted the row between the check and here, so there is neither a
            # started workflow nor a result to return. Falls through to the same retryable 503.
            outcome = WorkflowStartOutcome.FAILED
        if outcome is WorkflowStartOutcome.CAPPED:
            # The pre-check above passed on a snapshot; the atomic claim is the authoritative gate.
            raise Throttled(detail="This team is at its in-flight observation limit. Try again in a few minutes.")
        if outcome is WorkflowStartOutcome.FAILED:
            return Response(
                # `detail` (not `error`) so ApiError carries the message into the frontend toast.
                {"detail": "Failed to start the observation. Try again in a moment."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        report_user_action(
            user,
            "replay_vision_scan_requested_on_demand",
            {
                "scanner_id": str(scanner.id),
                "scanner_type": scanner.scanner_type,
                "model": scanner.model,
            },
            team=self.team,
            request=request,
        )
        return Response(
            ObserveResponseSerializer({"workflow_id": workflow_id}).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        request=BulkObserveRequestSerializer,
        responses={202: BulkObserveResponseSerializer},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="bulk_observe",
        required_scopes=["replay_scanner:write", "session_recording:read"],
    )
    def bulk_observe(self, request: Request, **kwargs: Any) -> Response:
        """Apply this scanner to many sessions on demand. Starts as many as fit under the in-flight
        caps and monthly credit quota, reporting the rest as skipped rather than failing the batch."""
        scanner = self.get_object()
        # Observation output exposes recording contents, so this requires session_recording read.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Triggering on-demand observations requires session_recording read access.")
        # The scan sends recordings to an LLM, the same reason observe, inline_scan and retry gate on
        # this. Without it a batch was accepted and then silently scanned nothing, because
        # create_observation fails closed on consent once the workflow is already running.
        if not self.team.organization.is_ai_data_processing_approved:
            raise ValidationError(
                "Your organization needs to allow AI analysis before you can run a Replay Vision scan."
            )

        body = BulkObserveRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        # Dedup preserving order — the same session twice in one batch would just be a wasted no-op.
        session_ids = list(dict.fromkeys(body.validated_data["session_ids"]))
        user = cast(User, request.user)

        started, results = scan_existing_scanner(scanner=scanner, session_ids=session_ids, user=user)
        if any(r["scan_outcome"] == "skipped_scanner_limit" for r in results):
            record_scanner_limit_reached("bulk")

        report_user_action(
            user,
            "replay_vision_bulk_scan_started",
            {
                "scanner_id": str(scanner.id),
                "scanner_type": scanner.scanner_type,
                "requested": len(session_ids),
                "started": started,
            },
            team=self.team,
            request=request,
        )
        # Key off the outcomes, not skip_reason: skip_reason only names the limit that would bind
        # first, and a batch that never reached the cap must not report exhaustion.
        if any(result["scan_outcome"] == "skipped_quota" for result in results):
            self._report_quota_exhausted(scanner, "bulk")
        return Response(
            BulkObserveResponseSerializer({"started": started, "results": results}).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        request=InlineScanRequestSerializer,
        responses={202: InlineScanResponseSerializer},
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="inline_scan",
        required_scopes=["replay_scanner:write", "session_recording:read"],
    )
    def inline_scan(self, request: Request, **kwargs: Any) -> Response:
        """Scan named sessions against a prompt without saving a scanner first, for one-off questions.

        The config resolves to a scanner minted on first use, so asking the same question twice reuses
        the observations it already has, while a different question about the same session gets its own.
        """
        # This action is `detail=False`, so the generic gate settles for editor access to any one
        # scanner and there is no object afterwards to narrow that against. An inline scan mints a
        # scanner and spends credits exactly as `create` does, so hold it to `create`'s bar.
        if not self.user_access_control.check_access_level_for_resource("replay_scanner", required_level="editor"):
            raise PermissionDenied("Running an inline scan requires edit access to this project's scanners.")
        # Observation output exposes recording contents, so this requires session_recording read.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Running an inline scan requires session_recording read access.")
        # The scan sends recordings to an LLM, the same reason saving a scanner gates on this.
        if not self.team.organization.is_ai_data_processing_approved:
            raise ValidationError(
                "Your organization needs to allow AI analysis before you can run a Replay Vision scan."
            )

        body = InlineScanRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        # Dedup preserving order — the same session twice in one batch would just be a wasted no-op.
        session_ids = list(dict.fromkeys(body.validated_data["session_ids"]))
        user = cast(User, request.user)
        scanner_type = ScannerType(body.validated_data["scanner_type"])
        scanner_config = body.validated_data["scanner_config"]
        model = body.validated_data["model"]

        scan = run_inline_scan(
            team=self.team,
            user=user,
            session_ids=session_ids,
            scanner_type=scanner_type,
            scanner_config=scanner_config,
            model=model,
        )
        if scan.scanner is None:
            # Nothing started and nothing already existed, so there is no id to read results through.
            # Key off the outcomes: the in-flight cap can bind here too, and that is not exhaustion.
            if any(result["scan_outcome"] == "skipped_quota" for result in scan.results):
                self._report_quota_exhausted(None, "inline")
            return Response(
                InlineScanResponseSerializer({"scan_id": None, "started": 0, "results": scan.results}).data,
                status=status.HTTP_202_ACCEPTED,
            )
        scanner, started, results = scan.scanner, scan.started, scan.results

        report_user_action(
            user,
            "replay_vision_inline_scan_requested",
            {
                "scan_id": str(scanner.id),
                "scanner_type": scanner.scanner_type,
                "model": scanner.model,
                "requested": len(session_ids),
                "started": started,
            },
            team=self.team,
            request=request,
        )
        if any(result["scan_outcome"] == "skipped_quota" for result in results):
            self._report_quota_exhausted(scanner, "inline")
        return Response(
            InlineScanResponseSerializer({"scan_id": scanner.id, "started": started, "results": results}).data,
            status=status.HTTP_202_ACCEPTED,
        )

    def _report_quota_exhausted(self, scanner: ReplayScanner | None, trigger: str) -> None:
        """A scan was blocked or capped by the org's monthly Replay vision credit limit.

        `scanner` is None when an inline scan was refused before it minted one.
        """
        report_user_action(
            cast(User, self.request.user),
            "replay_vision_quota_exhausted",
            {
                "scanner_id": str(scanner.id) if scanner is not None else None,
                "scanner_type": scanner.scanner_type if scanner is not None else None,
                "trigger": trigger,
            },
            team=self.team,
            request=self.request,
        )

    @extend_schema(parameters=[ScannerImpactQuerySerializer], responses={200: ScannerImpactSerializer})
    @action(
        detail=True,
        methods=["get"],
        url_path="impact",
        required_scopes=["replay_scanner:read", "session_recording:read"],
    )
    def impact(self, request: Request, **kwargs: Any) -> Response:
        """Affected sessions and users for this scanner over the trailing window."""
        # Impact counts are derived from recording observations; without this gate a member denied
        # session_recording access could read verdict/tag/score aggregates the observations endpoint blocks.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading scanner impact requires session_recording read access.")
        scanner = self.get_object()
        params = ScannerImpactQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        try:
            impact = compute_scanner_impact(
                scanner,
                params.validated_data["window_days"],
                tag=params.validated_data["tag"],
                min_score=params.validated_data["min_score"],
                max_score=params.validated_data["max_score"],
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return Response(ScannerImpactSerializer(instance=impact).data)

    @extend_schema(responses={200: ScannerSelfDrivingStatsSerializer})
    @action(
        detail=True,
        methods=["get"],
        url_path="self_driving_stats",
        required_scopes=["replay_scanner:read", "task:read"],
    )
    def self_driving_stats(self, request: Request, **kwargs: Any) -> Response:
        """What self-driving did with this scanner's signals: reports contributed to and PRs opened."""
        scanner = self.get_object()
        outcomes = get_outcomes_for_signal_source_slice(
            team=self.team,
            source_product=VISION_SIGNALS_SOURCE_PRODUCT,
            source_type=VISION_SIGNALS_SOURCE_TYPE,
            extra_equals={"scanner_id": str(scanner.id)},
        )
        return Response(
            ScannerSelfDrivingStatsSerializer(
                instance={
                    "signals_emitted": outcomes.signal_count,
                    "reports_contributed": outcomes.report_count,
                    "prs_opened": outcomes.pr_count,
                    "prs_merged": outcomes.merged_pr_count,
                }
            ).data
        )

    @extend_schema(
        request=AffectedCohortRequestSerializer,
        responses={201: AffectedCohortResponseSerializer},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="affected_cohort",
        required_scopes=["replay_scanner:read", "session_recording:read", "cohort:write"],
    )
    def affected_cohort(self, request: Request, **kwargs: Any) -> Response:
        """Save the users this scanner matched as a static cohort, for surveys, funnels, and retention analysis."""
        # The cohort materializes recording-derived identities; require the same recording access
        # the observations endpoint enforces before exposing per-session results.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Saving an affected cohort requires session_recording read access.")
        # `cohort:write` in required_scopes only constrains API keys; session RBAC evaluates against this
        # viewset's replay_scanner scope object, so the caller's cohort access must be checked explicitly.
        if not self.user_access_control.check_access_level_for_resource("cohort", required_level="editor"):
            raise PermissionDenied("Saving an affected cohort requires cohort edit access.")
        scanner = self.get_object()
        body = AffectedCohortRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        window_days: int = body.validated_data["window_days"]
        try:
            cohort, inserted = create_affected_cohort(
                scanner,
                cast(User, request.user),
                window_days=window_days,
                tag=body.validated_data["tag"],
                min_score=body.validated_data["min_score"],
                max_score=body.validated_data["max_score"],
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        report_user_action(
            cast(User, request.user),
            "replay_vision_affected_cohort_created",
            {
                "scanner_id": str(scanner.id),
                "scanner_type": scanner.scanner_type,
                "cohort_id": cohort.id,
                "users_in_cohort": inserted,
                "window_days": window_days,
            },
            team=self.team,
            request=request,
        )
        return Response(
            AffectedCohortResponseSerializer(
                {
                    "cohort_id": cohort.id,
                    "name": cohort.name,
                    "users_in_cohort": inserted,
                    "window_days": window_days,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=EstimateRequestSerializer,
        responses={200: EstimateResponseSerializer},
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="estimate",
        required_scopes=["replay_scanner:read", "session_recording:read"],
        throttle_classes=[ReplayVisionEstimateBurstRateThrottle, ReplayVisionEstimateSustainedRateThrottle],
    )
    def estimate(self, request: Request, **kwargs: Any) -> Response:
        """Estimate the observation volume a proposed scanner would generate, for the pre-save cost preview."""
        # The query runs over recording data, so a probed filter can leak recording metadata
        # (URLs, events, person properties, console logs); gate on session_recording read.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Estimating scanner volume requires session_recording read access.")

        body = EstimateRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        sampling_rate: float = body.validated_data["sampling_rate"]

        # Reject a scanner_id outside this project before doing any work, so it can't silently undercount the others-sum.
        # Treat missing object-level access the same as missing-entirely so a denied scanner's existence and
        # credit usage can't be inferred by comparing responses (mirrors the `suggest_tags` action below).
        scanner_id = body.validated_data.get("scanner_id")
        if scanner_id is not None:
            scanner = ReplayScanner.objects.filter(team_id=self.team_id, pk=scanner_id).first()
            if scanner is None or not self.user_access_control.check_access_level_for_object(scanner, "viewer"):
                raise serializers.ValidationError({"scanner_id": "No scanner with this id exists in this project."})

        # A denied experiment must read the same as a nonexistent one, mirroring
        # validate_experiment_targeting: the query runner's own access check answers with a 403,
        # which would confirm to a scanner-editor that a hidden experiment id exists.
        targeting = body.validated_data.get("experiment_targeting")
        if targeting is not None and not is_experiment_accessible(
            self.user_access_control, self.team_id, targeting["experiment_id"]
        ):
            raise serializers.ValidationError({"experiment_targeting": "Experiment not found in this project."})

        # validate_query already validated this; the empty-dict default needs `kind` to parse.
        query_dict: dict[str, Any] = dict(body.validated_data.get("query") or {})
        query_dict.setdefault("kind", "RecordingsQuery")
        recordings_query = apply_experiment_targeting(RecordingsQuery.model_validate(query_dict), targeting)

        estimate = estimate_scanner_session_volume(
            team=self.team,
            query=recordings_query,
            # The exposure filter's access check runs as the requesting user, so a preview can't
            # count exposed sessions of an experiment the caller is denied.
            user=cast(User, request.user),
            sampling_mode=body.validated_data["sampling_mode"],
            budget=PREVIEW_ESTIMATE_BUDGET,
        )
        observations_per_month = project_monthly_observations(estimate, sampling_rate)
        credits_per_observation = observation_credits_for_model(body.validated_data["model"])

        # One projection read, excluding the scanner being edited, so the editor adds this estimate on top of a
        # consistent snapshot instead of subtracting a possibly-stale per-scanner field.
        projection = spend_projection(self.team.organization_id, exclude_scanner_id=scanner_id)

        return Response(
            EstimateResponseSerializer(
                {
                    "matched_sessions_in_window": estimate.matched_sessions,
                    "window_days": estimate.effective_window_days,
                    "estimated_observations_per_month": observations_per_month,
                    "credits_per_observation": credits_per_observation,
                    "estimated_credits_per_month": observations_per_month * credits_per_observation,
                    "other_enabled_scanners_monthly_credits": projection.scanners_monthly_credits,
                    "active_backfill_credits": projection.backfills_committed_credits,
                    "sampling_rate": sampling_rate,
                }
            ).data
        )

    @extend_schema(
        request=SuggestTagsRequestSerializer,
        responses={
            200: SuggestTagsResponseSerializer,
            503: OpenApiResponse(
                response=ReplayVisionErrorSerializer, description="Tag suggestions couldn't be generated."
            ),
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="suggest_tags",
        required_scopes=["replay_scanner:read", "session_recording:read"],
    )
    def suggest_tags(self, request: Request, **kwargs: Any) -> Response:
        """Suggest classifier tags grounded in the scanner's own observations and the org's product data."""
        # Suggestions read recording-derived observation reasoning, so gate on session_recording read.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Suggesting categories requires session_recording read access.")

        body = SuggestTagsRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        scanner: ReplayScanner | None = None
        scanner_id = data.get("scanner_id")
        if scanner_id is not None:
            scanner = ReplayScanner.objects.filter(team_id=self.team_id, id=scanner_id).first()
            # Observations inherit the scanner's RBAC; treat missing access as not-found so existence doesn't leak.
            if scanner is None or not self.user_access_control.check_access_level_for_object(scanner, "viewer"):
                raise NotFound("Scanner not found.")

        try:
            suggestions = suggest_classifier_tags(
                team=self.team,
                user=cast(User, request.user),
                prompt=data["prompt"],
                current_tags=data["tags"],
                multi_label=data["multi_label"],
                allow_freeform_tags=data["allow_freeform_tags"],
                scanner=scanner,
                user_access_control=self.user_access_control,
            )
        except SuggestionError:
            return Response(
                {"detail": "Couldn't generate tag suggestions right now. Try again in a moment."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(SuggestTagsResponseSerializer({"suggestions": suggestions}).data)

    @extend_schema(
        request=DraftScannerRequestSerializer,
        responses={
            200: DraftScannerResponseSerializer,
            400: OpenApiResponse(
                response=ReplayVisionErrorSerializer,
                description="The goal is missing or AI consent hasn't been granted.",
            ),
            403: OpenApiResponse(
                response=ReplayVisionErrorSerializer,
                description="The caller lacks the required access, or the feature isn't enabled.",
            ),
            503: OpenApiResponse(response=ReplayVisionErrorSerializer, description="The draft couldn't be generated."),
        },
    )
    # Each call is an inline LLM request, so it gets the shared AI rate limits like prompt suggestions.
    @action(
        detail=False,
        methods=["post"],
        url_path="draft",
        required_scopes=["replay_scanner:write", "session_recording:read"],
        throttle_classes=[AIBurstRateThrottle, AISustainedRateThrottle],
    )
    def draft(self, request: Request, **kwargs: Any) -> Response:
        """Draft a full scanner configuration from a natural-language goal, for the goal-based creation flow."""
        # This action is `detail=False`, so the generic gate settles for editor access to any one scanner.
        # A draft spends model budget toward a scanner only editors can save, so hold it to `create`'s bar.
        if not self.user_access_control.check_access_level_for_resource("replay_scanner", required_level="editor"):
            raise PermissionDenied("Drafting a Replay Vision scanner requires edit access to this project's scanners.")
        # The draft feeds a scanner that will expose recording contents, so mirror the config actions' gate.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Drafting a Replay Vision scanner requires session_recording read access.")
        # Same consent requirement as scanner creation: the goal and the team's taxonomy go to the model.
        if not self.team.organization.is_ai_data_processing_approved:
            raise ValidationError(
                "Your organization needs to allow AI analysis before you can draft a Replay Vision scanner."
            )

        body = DraftScannerRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        goal = body.validated_data["goal"]
        # The goal is customer text, so only its length goes into telemetry.
        draft_properties: dict[str, Any] = {"goal_length": len(goal), "team_id": self.team_id}

        try:
            drafted = draft_scanner_from_goal(
                team=self.team,
                user=cast(User, request.user),
                goal=goal,
                user_access_control=self.user_access_control,
                # Core memory's own API is INTERNAL (session-only), so scoped tokens must not
                # receive its content through the draft either.
                include_business_context=get_authenticator_scopes(request.successful_authenticator) is None,
            )
        except DraftError:
            # Report failures too, so model errors don't read as user abandonment.
            report_user_action(
                cast(User, request.user),
                "replay_vision_scanner_drafted",
                {**draft_properties, "success": False},
                team=self.team,
                request=request,
            )
            return Response(
                {"detail": "Couldn't draft a scanner right now. Try again in a moment."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        report_user_action(
            cast(User, request.user),
            "replay_vision_scanner_drafted",
            {
                **draft_properties,
                "success": True,
                "scanner_type": drafted.scanner_type,
                # Whether the goal mapped to a real event filter or fell back to no targeting.
                "has_query": bool(drafted.query),
            },
            team=self.team,
            request=request,
        )

        return Response(
            DraftScannerResponseSerializer(
                {
                    "name": drafted.name,
                    "description": drafted.description,
                    "scanner_type": drafted.scanner_type,
                    "scanner_config": drafted.scanner_config,
                    "rationale": drafted.rationale,
                    "query": drafted.query,
                }
            ).data
        )
