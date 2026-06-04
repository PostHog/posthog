import uuid
from typing import Any

from django.db.models import Case, CharField, F, FloatField, Func, IntegerField, Q, QuerySet, Value, When
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast

import structlog
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from pydantic import ValidationError as PydanticValidationError
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.replay_vision.backend.api.observation_stats import compute_observation_stats
from products.replay_vision.backend.feature_flag import ReplayVisionEnabledPermission
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import (
    ReplayScanner,
    ScannerModel,
    ScannerProvider,
    ScannerType,
)
from products.replay_vision.backend.temporal.types import ScannerResult, ScannerSnapshot

logger = structlog.get_logger(__name__)


def _jsonb_typeof(expr: Any) -> Func:
    """Postgres `JSONB_TYPEOF(value)` — built inline to avoid extending a custom Expression class."""
    return Func(expr, function="JSONB_TYPEOF", output_field=CharField())


class ScannerSnapshotSerializer(serializers.Serializer):
    """Mirrors `temporal.types.ScannerSnapshot` for OpenAPI generation."""

    name = serializers.CharField(
        help_text="Scanner name at run time.",
    )
    scanner_type = serializers.ChoiceField(
        choices=ScannerType.choices,
        help_text="Scanner type (monitor, classifier, scorer, summarizer) at run time.",
    )
    scanner_version = serializers.IntegerField(
        help_text="The `ReplayScanner.scanner_version` value at the moment the workflow ran.",
    )
    model = serializers.ChoiceField(
        choices=ScannerModel.choices,
        help_text="Concrete model that ran the observation.",
    )
    provider = serializers.ChoiceField(
        choices=ScannerProvider.choices,
        help_text="Concrete provider that ran the observation.",
    )
    emits_signals = serializers.BooleanField(
        help_text="Whether the observation was run with Signal emission enabled.",
    )
    scanner_config = serializers.JSONField(
        help_text="Scanner-type-specific configuration at run time (prompt, tags, scale, etc.).",
    )


class ScannerResultSerializer(serializers.Serializer):
    """Mirrors `temporal.types.ScannerResult` for OpenAPI generation."""

    model_output = serializers.JSONField(
        help_text="Validated scanner output. Shape depends on `scanner_snapshot.scanner_type`; always carries `confidence` and `scanner_type`.",
    )
    signals_count = serializers.IntegerField(
        min_value=0,
        help_text="Number of PostHog Signals emitted from this observation.",
    )


class ReplayObservationSerializer(serializers.ModelSerializer):
    scanner_id = serializers.UUIDField(read_only=True, help_text="The scanner that produced this observation.")
    session_id = serializers.CharField(read_only=True, help_text="Session recording id this scanner was applied to.")
    status = serializers.ChoiceField(
        choices=ObservationStatus.choices,
        read_only=True,
        help_text="Observation status (pending, running, succeeded, failed, ineligible).",
    )
    error_reason = serializers.CharField(
        read_only=True,
        allow_blank=True,
        help_text=(
            "Populated on terminal non-success statuses; formatted as `kind:human-readable message`. "
            "For `ineligible`, kind is one of no_recording / too_short / too_inactive / too_long / no_events. "
            "For `failed`, kind is one of provider_transient / provider_rejected / rasterization_failed / "
            "validation_failed / internal_error."
        ),
    )
    workflow_id = serializers.CharField(
        read_only=True,
        allow_blank=True,
        help_text="Temporal workflow id for progress queries and debugging. Empty until the workflow starts.",
    )
    scanner_snapshot = serializers.SerializerMethodField(
        help_text="Frozen view of the scanner at run time; scanner edits do not retroactively mutate this observation.",
    )
    scanner_result = serializers.SerializerMethodField(
        help_text="Result data persisted on success; null until the observation succeeds.",
    )

    @extend_schema_field(ScannerSnapshotSerializer(allow_null=True))
    def get_scanner_snapshot(self, obj: ReplayObservation) -> dict | None:
        if not obj.scanner_snapshot:
            return None  # Snapshot is supposed to be populated at create; an empty blob is a write-side bug.
        try:
            return ScannerSnapshot.model_validate(obj.scanner_snapshot).model_dump(mode="json")
        except PydanticValidationError:
            logger.exception("replay_vision.observation.malformed_scanner_snapshot", observation_id=str(obj.id))
            return None

    @extend_schema_field(ScannerResultSerializer(allow_null=True))
    def get_scanner_result(self, obj: ReplayObservation) -> dict | None:
        if not obj.scanner_result:
            return None
        try:
            return ScannerResult.model_validate(obj.scanner_result).model_dump(mode="json")
        except PydanticValidationError:
            logger.exception("replay_vision.observation.malformed_scanner_result", observation_id=str(obj.id))
            return None

    triggered_by = serializers.ChoiceField(
        choices=ObservationTrigger.choices,
        read_only=True,
        help_text="Whether this observation came from the schedule or an on-demand request.",
    )
    triggered_by_user = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who triggered an on-demand observation; null for scheduled observations.",
    )

    class Meta:
        model = ReplayObservation
        fields = [
            "id",
            "scanner_id",
            "session_id",
            "status",
            "error_reason",
            "workflow_id",
            "scanner_snapshot",
            "scanner_result",
            "triggered_by",
            "triggered_by_user",
            "started_at",
            "completed_at",
            "created_at",
        ]


class ObservationStatusCountsSerializer(serializers.Serializer):
    total = serializers.IntegerField(help_text="Total observations in the filtered set.")
    succeeded = serializers.IntegerField(help_text="Observations with `status=succeeded`.")
    failed = serializers.IntegerField(help_text="Observations with `status=failed`.")
    ineligible = serializers.IntegerField(help_text="Observations with `status=ineligible`.")
    in_flight = serializers.IntegerField(help_text="Observations not yet in a terminal status.")
    success_rate = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Percentage of (succeeded + failed) observations that succeeded; ineligible rows are excluded. "
            "Null when no observations have completed."
        ),
    )


class MonitorStatsSerializer(serializers.Serializer):
    yes_total = serializers.IntegerField(help_text="Succeeded observations whose verdict was `yes`.")
    no_total = serializers.IntegerField(help_text="Succeeded observations whose verdict was `no`.")
    inconclusive_total = serializers.IntegerField(help_text="Succeeded observations whose verdict was `inconclusive`.")


class TagCountSerializer(serializers.Serializer):
    tag = serializers.CharField(help_text="The tag value.")
    count = serializers.IntegerField(help_text="Number of succeeded observations carrying this tag.")


class ClassifierStatsSerializer(serializers.Serializer):
    fixed_ranked = TagCountSerializer(many=True, help_text="Top fixed-vocabulary tags by emission count.")
    freeform_ranked = TagCountSerializer(many=True, help_text="Top freeform tags by emission count.")
    total_with_tags = serializers.IntegerField(help_text="Succeeded observations that emitted at least one tag.")


class ScorerSummarySerializer(serializers.Serializer):
    min = serializers.FloatField(help_text="Minimum observed score.")
    p25 = serializers.FloatField(help_text="25th-percentile score.")
    median = serializers.FloatField(help_text="Median score.")
    mean = serializers.FloatField(help_text="Mean score.")
    p75 = serializers.FloatField(help_text="75th-percentile score.")
    max = serializers.FloatField(help_text="Maximum observed score.")
    count = serializers.IntegerField(help_text="Number of scored observations summarized.")


class ScorerHistogramSerializer(serializers.Serializer):
    labels = serializers.ListField(
        child=serializers.CharField(),
        help_text="Bucket labels (one per histogram bar) spanning the scanner's configured scale.",
    )
    counts = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="Observation count per bucket; same length as `labels`.",
    )


class ScorerStatsSerializer(serializers.Serializer):
    summary = ScorerSummarySerializer(
        allow_null=True,
        help_text="Score quantile summary; null when no observations have been scored.",
    )
    histogram = ScorerHistogramSerializer(
        allow_null=True,
        help_text="Score histogram; null when no observations have been scored.",
    )


class CoverageStatsSerializer(serializers.Serializer):
    recent_sessions = serializers.IntegerField(
        help_text="Distinct sessions observed within the last `recent_days` days."
    )
    total_sessions = serializers.IntegerField(help_text="Distinct sessions observed overall.")
    recent_days = serializers.IntegerField(help_text="Window size in days used for `recent_sessions`.")


class ObservationStatsSerializer(serializers.Serializer):
    status_counts = ObservationStatusCountsSerializer(help_text="Counts of observations by terminal status.")
    coverage = CoverageStatsSerializer(help_text="Session-level scanner coverage.")
    available_tags = serializers.ListField(
        child=serializers.CharField(),
        help_text="All distinct tags (fixed + freeform) emitted by succeeded observations in the filtered set.",
    )
    monitor = MonitorStatsSerializer(
        allow_null=True,
        help_text="Monitor-type aggregates; null when the scanner is not a monitor.",
    )
    classifier = ClassifierStatsSerializer(
        allow_null=True,
        help_text="Classifier-type aggregates; null when the scanner is not a classifier.",
    )
    scorer = ScorerStatsSerializer(
        allow_null=True,
        help_text="Scorer-type aggregates; null when the scanner is not a scorer.",
    )


# Single source of truth for orderable fields; the list endpoint's OpenAPI override mirrors these as a string enum.
OBSERVATION_ORDER_FIELDS = ("created_at", "started_at", "completed_at", "status")

# JSONB-backed sort keys; numeric values (`result_score`, `scanner_version`) need a numeric cast in the filter.
_JSONB_ORDER_KEYS = ("result_score", "result_verdict", "scanner_version")
_ALL_ORDER_KEYS = OBSERVATION_ORDER_FIELDS + _JSONB_ORDER_KEYS


def _ordering_enum(fields: tuple[str, ...] = _ALL_ORDER_KEYS) -> list[str]:
    """Ascending + descending (`-`-prefixed) variants of each field, matching OrderingFilter's accepted values."""
    return [value for field in fields for value in (field, f"-{field}")]


class _OrderByFilter(django_filters.CharFilter):
    """Ordering filter supporting plain columns and JSONB-backed keys with numeric casts and nulls-last."""

    def filter(self, qs: QuerySet[ReplayObservation], value: str) -> QuerySet[ReplayObservation]:
        if not value:
            return qs
        descending = value.startswith("-")
        key = value[1:] if descending else value
        if key not in _ALL_ORDER_KEYS:
            raise ValidationError({"order_by": f"Invalid order_by '{value}'. Allowed keys: {sorted(_ALL_ORDER_KEYS)}."})
        if key in OBSERVATION_ORDER_FIELDS:
            return qs.order_by(("-" if descending else "") + key, "id")
        if key == "result_score":
            # CASE-guard the cast so a non-numeric `score` (schema drift, manual fixup) doesn't 500 the query.
            score_jsonb = KeyTransform("score", KeyTransform("model_output", "scanner_result"))
            score_text = KeyTextTransform("score", KeyTextTransform("model_output", "scanner_result"))
            qs = qs.annotate(
                _score_type=_jsonb_typeof(score_jsonb),
                _order_score=Case(
                    When(_score_type="number", then=Cast(score_text, FloatField())),
                    default=Value(None),
                    output_field=FloatField(),
                ),
            )
            expr = F("_order_score").desc(nulls_last=True) if descending else F("_order_score").asc(nulls_last=True)
            return qs.order_by(expr, "id")
        if key == "scanner_version":
            version_jsonb = KeyTransform("scanner_version", "scanner_snapshot")
            version_text = KeyTextTransform("scanner_version", "scanner_snapshot")
            qs = qs.annotate(
                _version_type=_jsonb_typeof(version_jsonb),
                _order_version=Case(
                    When(_version_type="number", then=Cast(version_text, IntegerField())),
                    default=Value(None),
                    output_field=IntegerField(),
                ),
            )
            expr = F("_order_version").desc(nulls_last=True) if descending else F("_order_version").asc(nulls_last=True)
            return qs.order_by(expr, "id")
        # `result_verdict` — short text enum, annotated so we get nulls-last like the other JSONB keys.
        qs = qs.annotate(
            _order_verdict=KeyTextTransform("verdict", KeyTextTransform("model_output", "scanner_result")),
        )
        expr = F("_order_verdict").desc(nulls_last=True) if descending else F("_order_verdict").asc(nulls_last=True)
        return qs.order_by(expr, "id")


_MONITOR_VERDICTS = frozenset({"yes", "no", "inconclusive"})


class _MultiChoiceFilter(django_filters.CharFilter):
    """CSV-encoded multi-value filter; 400s on values outside `valid_choices` when supplied."""

    def __init__(
        self,
        *args: Any,
        valid_choices: frozenset[str] | None = None,
        error_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._valid_choices = valid_choices
        # When `field_name` is an ORM traversal path (e.g. `scanner_result__model_output__verdict`), the
        # default error dict key would leak it; override so the response keys match the public param name.
        self._error_key = error_key

    def filter(self, qs: QuerySet[ReplayObservation], value: str | None) -> QuerySet[ReplayObservation]:
        if not value:
            return qs
        values = [v for v in (v.strip() for v in value.split(",")) if v]
        if not values:
            return qs
        if self._valid_choices is not None:
            invalid = sorted({v for v in values if v not in self._valid_choices})
            if invalid:
                key = self._error_key or self.field_name
                raise ValidationError({key: f"Invalid value(s) {invalid}; allowed: {sorted(self._valid_choices)}."})
        # nosemgrep: orm-field-injection -- `field_name` is a class-init constant; `values` validated above.
        return qs.filter(**{f"{self.field_name}__in": values})


class ReplayObservationFilter(django_filters.FilterSet):
    status = _MultiChoiceFilter(
        field_name="status",
        valid_choices=frozenset(v for v, _ in ObservationStatus.choices),
        help_text="Filter by observation status. Accepts a comma-separated list.",
    )
    triggered_by = _MultiChoiceFilter(
        field_name="triggered_by",
        valid_choices=frozenset(v for v, _ in ObservationTrigger.choices),
        help_text="Filter by trigger source (schedule or on_demand). Accepts a comma-separated list.",
    )
    verdict = _MultiChoiceFilter(
        field_name="scanner_result__model_output__verdict",
        valid_choices=_MONITOR_VERDICTS,
        error_key="verdict",
        help_text="Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).",
    )
    tags = django_filters.CharFilter(
        method="_filter_tags",
        help_text=(
            "Filter classifier observations whose fixed or freeform tags include any of the given values "
            "(comma-separated). Matches if the tag appears in either `tags` or `tags_freeform`."
        ),
    )
    session_id = django_filters.CharFilter(
        field_name="session_id",
        help_text="Filter to observations of a specific session recording.",
    )
    order_by = _OrderByFilter(
        help_text=(
            "Sort observations by created_at, started_at, completed_at, status, result_score, result_verdict, "
            "or scanner_version. Prefix with `-` for descending. JSONB-backed keys (result_*, scanner_version) "
            "sort nulls last regardless of direction."
        ),
    )

    class Meta:
        model = ReplayObservation
        fields = ["status", "triggered_by", "session_id"]

    @classmethod
    def schema_parameters(cls) -> list[OpenApiParameter]:
        """Mirror declared filters as `OpenApiParameter`s for `@action` methods drf-spectacular can't auto-discover."""
        return [
            OpenApiParameter(
                name,
                str,
                OpenApiParameter.QUERY,
                required=False,
                description=str(field.extra.get("help_text", "")),
            )
            for name, field in cls.declared_filters.items()
            if name != "order_by"
        ]

    def _filter_tags(
        self, queryset: QuerySet[ReplayObservation], _name: str, value: str
    ) -> QuerySet[ReplayObservation]:
        tags = [t for t in (t.strip() for t in value.split(",")) if t]
        if not tags:
            return queryset
        # `__contains` on a JSONB array uses the `@>` operator: matches when the stored array contains the given element.
        q = Q()
        for tag in tags:
            q |= Q(scanner_result__model_output__tags__contains=[tag])
            q |= Q(scanner_result__model_output__tags_freeform__contains=[tag])
        return queryset.filter(q)


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
                enum=_ordering_enum(),
                description=(
                    "Sort observations. Plain keys: created_at, started_at, completed_at, status. JSONB keys: "
                    "result_score (scorer), result_verdict (monitor), scanner_version. Prefix with `-` for descending."
                ),
            )
        ]
    )
)
class ReplayObservationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only access to observations produced by a scanner."""

    scope_object = "replay_scanner"
    required_scopes = ["replay_scanner:read", "session_recording:read"]
    permission_classes = [ReplayVisionEnabledPermission]
    serializer_class = ReplayObservationSerializer
    queryset = ReplayObservation.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = ReplayObservationFilter

    def _scanner_for_url(self) -> ReplayScanner:
        # Per-request cache so `stats` doesn't re-run the RBAC + scanner-lookup roundtrip.
        cached = getattr(self, "_scanner_for_url_cache", None)
        if cached is not None:
            return cached
        try:
            scanner_id = uuid.UUID(self.kwargs["parent_lookup_scanner_id"])
        except (KeyError, ValueError):
            raise NotFound()
        scanner = ReplayScanner.objects.filter(team_id=self.team_id, id=scanner_id).first()
        if scanner is None:
            raise NotFound()
        # Observations expose recording-derived output, so they inherit the scanner's RBAC and also require session_recording read.
        self.check_object_permissions(self.request, scanner)
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading replay observations requires session_recording read access.")
        self._scanner_for_url_cache = scanner
        return scanner

    def safely_get_queryset(self, queryset: QuerySet[ReplayObservation]) -> QuerySet[ReplayObservation]:
        scanner = self._scanner_for_url()
        return (
            queryset.filter(team_id=self.team_id, scanner_id=scanner.id)
            .select_related("triggered_by_user")
            .order_by("-created_at", "id")
        )

    @extend_schema(
        parameters=ReplayObservationFilter.schema_parameters(),
        responses={200: ObservationStatsSerializer},
        description=(
            "Aggregate counts and per-scanner-type distributions over the filtered observation set. "
            "Same filters as the list endpoint apply."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def stats(self, request: Request, **kwargs: Any) -> Response:
        scanner = self._scanner_for_url()
        queryset = self.filter_queryset(self.get_queryset())
        payload = compute_observation_stats(scanner, queryset)
        return Response(payload)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                "session_id",
                str,
                OpenApiParameter.QUERY,
                required=True,
                description="Session recording id to return observations for.",
            )
        ]
    )
)
class SessionReplayObservationViewSet(ReplayObservationViewSet):
    """Read-only access to a session's observations across every scanner the caller can read, for the replay-page dock."""

    # The dock fetches one session's observations; `session_id` is required and enforced in
    # safely_get_queryset, so this viewset needs none of the base's optional list filters.
    filter_backends: list = []

    def safely_get_queryset(self, queryset: QuerySet[ReplayObservation]) -> QuerySet[ReplayObservation]:
        # Observations expose recording-derived output, so reading them requires session_recording read.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading replay observations requires session_recording read access.")
        # Observations inherit their scanner's RBAC. The generic access filter keys on the ReplayObservation
        # row rather than its scanner, so scope explicitly to the scanners this caller can read.
        readable_scanner_ids = list(
            self.user_access_control.filter_queryset_by_access_level(
                ReplayScanner.objects.filter(team_id=self.team_id)
            ).values_list("id", flat=True)
        )
        queryset = (
            queryset.filter(team_id=self.team_id, scanner_id__in=readable_scanner_ids)
            .select_related("triggered_by_user")
            .order_by("-created_at", "id")
        )
        # A bare list would scan the whole team's observation history; the replay page always has a session.
        if self.action == "list":
            session_id = self.request.query_params.get("session_id")
            if not session_id:
                raise ValidationError("The `session_id` query parameter is required.")
            queryset = queryset.filter(session_id=session_id)
        return queryset

    # Hide `stats/` on the session-scoped viewset — it has no `parent_lookup_scanner_id` to dispatch on.
    def stats(self, request: Request, **kwargs: Any) -> Response:  # type: ignore[override]
        raise NotFound()
