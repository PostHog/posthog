from typing import Any, NoReturn, cast

from django.db import IntegrityError
from django.db.models import CharField, Count, F, Q, QuerySet, Value
from django.db.models.functions import Coalesce, NullIf
from django.utils import timezone

import structlog
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import RecordingsQuery

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.user import User

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
    start_apply_scanner_workflow,
)
from products.replay_vision.backend.digest import provision_scanner_digest
from products.replay_vision.backend.feature_flag import ReplayVisionEnabledPermission, is_replay_vision_actions_enabled
from products.replay_vision.backend.models.replay_scanner import (
    ReplayScanner,
    SamplingMode,
    ScannerModel,
    ScannerProvider,
    ScannerType,
)
from products.replay_vision.backend.queries import (
    ESTIMATE_INTERACTIVE_MAX_EXECUTION_SECONDS,
    ESTIMATE_STALE_AFTER,
    MIN_SAMPLING_RATE,
    estimate_scanner_session_volume,
    project_monthly_observations,
    refresh_scanner_estimate,
)
from products.replay_vision.backend.quota import sum_enabled_scanner_estimates
from products.replay_vision.backend.tag_suggestions import SuggestionError, suggest_classifier_tags
from products.replay_vision.backend.tags import slugify_tag
from products.replay_vision.backend.temporal.constants import MAX_SESSION_ID_LENGTH
from products.replay_vision.backend.temporal.scanners import validate_scanner_config

# Date is set by the schedule at trigger time, not by the user — strip on save.
_QUERY_FIELDS_TO_STRIP = ("date_from", "date_to")

# Size caps enforced at the write boundary; scanner_config is copied into every observation's snapshot.
_MAX_PROMPT_LENGTH = 20_000
_MAX_TAGS = 100
_MAX_TAG_LENGTH = 100
_MAX_DESCRIPTION_LENGTH = 1_000

logger = structlog.get_logger(__name__)


def _refresh_estimate_fail_soft(scanner: ReplayScanner) -> None:
    # The estimate is advisory — never fail a scanner save over it, and keep the save's latency tail short.
    try:
        refresh_scanner_estimate(scanner, max_execution_seconds=ESTIMATE_INTERACTIVE_MAX_EXECUTION_SECONDS)
    except Exception:
        logger.exception("replay_vision.estimate_refresh_failed", scanner_id=str(scanner.id))


def _scanner_config_error_message(scanner_type: ScannerType, scanner_config: Any) -> str | None:
    if not isinstance(scanner_config, dict):
        return "Scanner configuration must be a JSON object."
    prompt = scanner_config.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return "Prompt is required."
    if len(prompt) > _MAX_PROMPT_LENGTH:
        return f"Prompt can be at most {_MAX_PROMPT_LENGTH:,} characters."
    if scanner_type == ScannerType.CLASSIFIER:
        tags = scanner_config.get("tags") or []
        if len(tags) == 0:
            return "Tag vocabulary must have at least one tag."
        if len(tags) > _MAX_TAGS:
            return f"Tag vocabulary can have at most {_MAX_TAGS} tags."
        if any(not isinstance(t, str) or not t.strip() for t in tags):
            return "Tags can't be blank."
        if any(len(t) > _MAX_TAG_LENGTH for t in tags):
            return f"Tags can be at most {_MAX_TAG_LENGTH} characters."
        # Uniqueness on the slug, since filtering/stripping/search all compare slugified tags downstream.
        slugged: dict[str, str] = {}
        for t in tags:
            slug = slugify_tag(t)
            if not slug:
                return "Tags must contain letters or numbers."
            if slug in slugged:
                return f"Tags must be unique: '{slugged[slug]}' and '{t}' are the same tag."
            slugged[slug] = t
    if scanner_type == ScannerType.SCORER:
        scale = scanner_config.get("scale")
        if not isinstance(scale, dict):
            return "Scale is required."
        min_v, max_v = scale.get("min"), scale.get("max")
        if not isinstance(min_v, (int, float)) or not isinstance(max_v, (int, float)):
            return "Scale min and max must be numbers."
        if min_v >= max_v:
            return "Scale max must be greater than min."
    try:
        scanner = validate_scanner_config(scanner_config=scanner_config, scanner_type=scanner_type)
    except (ValueError, PydanticValidationError):
        return "Scanner configuration is invalid."
    # The pydantic models ignore extra keys — reject here so typos and junk don't snapshot onto every observation.
    unknown = set(scanner_config) - set(type(scanner).model_fields)
    if unknown:
        return f"Unknown scanner configuration keys: {', '.join(sorted(unknown))}."
    return None


class ReplayScannerSerializer(serializers.ModelSerializer):
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
    last_swept_at = serializers.DateTimeField(
        read_only=True,
        help_text="Watermark for the scanner's last scheduled fire. Mirrors Temporal schedule state for recovery.",
    )
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who created the scanner.",
    )

    class Meta:
        model = ReplayScanner
        fields = [
            "id",
            "name",
            "description",
            "scanner_type",
            "scanner_config",
            "query",
            "sampling_rate",
            "sampling_mode",
            "provider",
            "model",
            "enabled",
            "emits_signals",
            "scanner_version",
            "estimated_monthly_observations",
            "last_swept_at",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "scanner_version",
            "estimated_monthly_observations",
            "last_swept_at",
            "created_at",
            "created_by",
            "updated_at",
        ]

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
        return attrs

    def validate_sampling_rate(self, value: float) -> float:
        # Below one modulo bucket the candidate query samples nothing — reject instead of silently scanning zero.
        if 0 < value < MIN_SAMPLING_RATE:
            raise serializers.ValidationError(
                f"Sampling rate must be 0 (paused) or at least {MIN_SAMPLING_RATE} (0.01%)."
            )
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
        message = _scanner_config_error_message(ScannerType(scanner_type), scanner_config)
        if message is not None:
            raise serializers.ValidationError({"scanner_config": message})

    def _validate_and_strip_query(self, attrs: dict[str, Any]) -> None:
        if "query" not in attrs:
            return
        try:
            RecordingsQuery.model_validate(attrs["query"])
        except PydanticValidationError:
            raise serializers.ValidationError({"query": "Recording filter is invalid."})
        # Persist exactly what the user sent (validated), minus the date keys the schedule controls.
        attrs["query"] = {k: v for k, v in attrs["query"].items() if k not in _QUERY_FIELDS_TO_STRIP}

    def to_representation(self, instance: ReplayScanner) -> dict[str, Any]:
        data = super().to_representation(instance)
        # `is not None` (not falsy) so empty-dict queries still revalidate against future schema changes.
        if data.get("query") is not None:
            try:
                RecordingsQuery.model_validate(data["query"])
            except PydanticValidationError:
                logger.exception("replay_vision.scanner.malformed_query", scanner_id=str(instance.id))
                data["query"] = None
        return data

    def create(self, validated_data: dict[str, Any]) -> ReplayScanner:
        team = self.context["get_team"]()
        user = cast(User, self.context["request"].user)
        try:
            # last_swept_at is seeded a settle-interval back by the model default (initial_watermark) to avoid a cold start.
            scanner = ReplayScanner.objects.create(team=team, created_by=user, **validated_data)
        except IntegrityError as e:
            self._reraise_unique_name_violation(e)
        _refresh_estimate_fail_soft(scanner)
        # Every scanner starts with a built-in daily digest so the overview has a summary to show.
        # Flag-gated so teams without the actions feature don't accrue synthesis runs they can't see.
        if is_replay_vision_actions_enabled(user, team):
            provision_scanner_digest(scanner, user)
        return scanner

    def update(self, instance: ReplayScanner, validated_data: dict[str, Any]) -> ReplayScanner:
        was_enabled = instance.enabled
        try:
            scanner = super().update(instance, validated_data)
        except IntegrityError as e:
            self._reraise_unique_name_violation(e)
        # Model save clears `estimated_at` when volume inputs change. Re-enables only refresh inline when
        # the background refresher has fallen behind, so a stale number never enters the quota sum.
        needs_refresh = scanner.estimated_at is None or (
            scanner.enabled and not was_enabled and timezone.now() - scanner.estimated_at >= ESTIMATE_STALE_AFTER
        )
        if needs_refresh:
            _refresh_estimate_fail_soft(scanner)
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
)
_SCANNER_ENABLED_CHOICES = frozenset({"enabled", "disabled"})
# Map `?enabled=true/false/1/0` to the CSV form so the conventional boolean stays supported.
_SCANNER_ENABLED_ALIASES = {"true": "enabled", "false": "disabled", "1": "enabled", "0": "disabled"}


class _ScannerOrderByFilter(OrderByFilter):
    """Plain columns + `created_by` sorted by the display label so UI order matches the column."""

    _allowed_keys = frozenset(SCANNER_ORDER_FIELDS)

    def _handle(self, qs: QuerySet[ReplayScanner], key: str, descending: bool) -> QuerySet[ReplayScanner]:
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
    order_by = _ScannerOrderByFilter(
        help_text=(
            "Sort scanners by name, created_at, updated_at, scanner_type, enabled, sampling_rate, or "
            "created_by. Prefix with `-` for descending."
        ),
    )

    class Meta:
        model = ReplayScanner
        fields = ["enabled", "scanner_type", "emits_signals", "created_by", "search"]

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
        invalid = sorted(t for t in tokens if not t.isdigit())
        if invalid:
            raise ValidationError({"created_by": f"Non-numeric value(s) {invalid}; user IDs must be integers."})
        return queryset.filter(created_by_id__in=tokens)

    @staticmethod
    def _filter_search(queryset: QuerySet[ReplayScanner], _name: str, value: str) -> QuerySet[ReplayScanner]:
        q = value.strip()
        if not q:
            return queryset
        return queryset.filter(
            Q(name__icontains=q) | Q(description__icontains=q) | Q(scanner_config__prompt__icontains=q)
        )


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
            "The scanner being edited, excluded from `other_enabled_scanners_monthly` so its stored estimate isn't "
            "double-counted in the forecast. Omit (or null) when estimating a brand-new scanner."
        ),
    )

    def validate_query(self, value: dict[str, Any]) -> dict[str, Any]:
        try:
            RecordingsQuery.model_validate(value)
        except PydanticValidationError:
            raise serializers.ValidationError("Recording filter is invalid.")
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
    """Forward-looking observation-volume estimate for a proposed scanner. Pricing-agnostic."""

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
    other_enabled_scanners_monthly = serializers.IntegerField(
        help_text=(
            "Summed projected monthly observations of the org's other enabled scanners (excluding `scanner_id`), from "
            "their cached estimates. Read from the same snapshot as this estimate so the forecast can't double-count "
            "the edited scanner."
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
        help_text="The current tag vocabulary, so suggestions never duplicate a tag the user already has.",
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
                description=(
                    "Sort scanners by name, created_at, updated_at, scanner_type, enabled, sampling_rate, or "
                    "created_by. Prefix with `-` for descending."
                ),
            )
        ]
    )
)
class ReplayScannerViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """CRUD for Replay Vision scanners."""

    scope_object = "replay_scanner"
    # Custom actions must be listed explicitly or personal-API-key callers 403 silently.
    scope_object_read_actions = ["list", "retrieve", "creators", "stats"]
    scope_object_write_actions = ["create", "update", "partial_update", "destroy", "observe"]
    permission_classes = [ReplayVisionEnabledPermission]
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
        return None

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if self.action in self._CONFIG_ACTIONS and not self.user_access_control.check_access_level_for_resource(
            "session_recording", required_level="viewer"
        ):
            raise PermissionDenied("Configuring a Replay Vision scanner requires session_recording read access.")

    def safely_get_queryset(self, queryset: QuerySet[ReplayScanner]) -> QuerySet[ReplayScanner]:
        return queryset.filter(team_id=self.team_id).select_related("created_by").order_by("name", "id")

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
        responses={202: ObserveResponseSerializer},
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
        # Observation output exposes recording contents, so observe requires session_recording read.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Triggering an on-demand observation requires session_recording read access.")

        check_observation_quota(self.team.organization_id)

        body = ObserveRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        session_id: str = body.validated_data["session_id"]
        user = cast(User, request.user)

        workflow_id, outcome = start_apply_scanner_workflow(scanner, session_id, triggered_by_user_id=user.id)
        if outcome is WorkflowStartOutcome.FAILED:
            return Response(
                {"error": "Failed to start observation workflow"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            ObserveResponseSerializer({"workflow_id": workflow_id}).data,
            status=status.HTTP_202_ACCEPTED,
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
        scanner_id = body.validated_data.get("scanner_id")
        if scanner_id is not None and not ReplayScanner.objects.filter(team_id=self.team_id, pk=scanner_id).exists():
            raise serializers.ValidationError({"scanner_id": "No scanner with this id exists in this project."})

        # validate_query already validated this; the empty-dict default needs `kind` to parse.
        query_dict: dict[str, Any] = dict(body.validated_data.get("query") or {})
        query_dict.setdefault("kind", "RecordingsQuery")
        recordings_query = RecordingsQuery.model_validate(query_dict)

        estimate = estimate_scanner_session_volume(
            team=self.team, query=recordings_query, sampling_mode=body.validated_data["sampling_mode"]
        )
        observations_per_month = project_monthly_observations(estimate, sampling_rate)

        # The OTHER enabled scanners' projected total (same source as the quota snapshot), so the editor adds this
        # estimate on top of a consistent snapshot instead of subtracting a possibly-stale per-scanner field.
        other_enabled_scanners_monthly = sum_enabled_scanner_estimates(
            self.team.organization_id, exclude_scanner_id=scanner_id
        )

        return Response(
            EstimateResponseSerializer(
                {
                    "matched_sessions_in_window": estimate.matched_sessions,
                    "window_days": estimate.effective_window_days,
                    "estimated_observations_per_month": observations_per_month,
                    "other_enabled_scanners_monthly": other_enabled_scanners_monthly,
                    "sampling_rate": sampling_rate,
                }
            ).data
        )

    @extend_schema(
        request=SuggestTagsRequestSerializer,
        responses={200: SuggestTagsResponseSerializer},
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
            raise PermissionDenied("Suggesting classifier tags requires session_recording read access.")

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
                {"error": "Couldn't generate tag suggestions right now. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(SuggestTagsResponseSerializer({"suggestions": suggestions}).data)
