import uuid
from typing import Any, cast, get_args

from django.conf import settings
from django.db.models import Case, CharField, FloatField, Func, IntegerField, Q, QuerySet, Value, When
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast
from django.http import StreamingHttpResponse

import structlog
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from pydantic import ValidationError as PydanticValidationError
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.streaming import sse_streaming_response
from posthog.models.user import User
from posthog.renderers import ServerSentEventRenderer

from products.replay_vision.backend.api.filters import MultiChoiceFilter, OrderByFilter, ordering_enum
from products.replay_vision.backend.api.observation_progress import stream_observation_progress
from products.replay_vision.backend.api.observation_stats import compute_observation_stats
from products.replay_vision.backend.api.trigger import (
    WorkflowStartOutcome,
    check_observation_quota,
    start_apply_scanner_workflow,
)
from products.replay_vision.backend.error_kinds import ERROR_REASON_HELP_TEXT
from products.replay_vision.backend.feature_flag import ReplayVisionEnabledPermission
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.temporal.scanners.monitor import MonitorVerdict
from products.replay_vision.backend.temporal.types import ScannerResult, ScannerSnapshot

logger = structlog.get_logger(__name__)


def _jsonb_typeof(expr: Any) -> Func:
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
    model = serializers.CharField(
        help_text="Concrete model that ran the observation; historical rows may carry since-retired model ids.",
    )
    provider = serializers.CharField(
        help_text="Concrete provider that ran the observation; historical rows may carry since-retired providers.",
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


class ReplayObservationLabelSerializer(serializers.Serializer):
    """The team's shared judgement on whether the scanner scored this session correctly."""

    is_correct = serializers.BooleanField(
        help_text="True if the scanner scored this session correctly, false if not.",
    )
    feedback = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=5000,
        help_text=(
            "Optional written context on the rating, for thumbs-up and thumbs-down alike: what the scanner got "
            "right or wrong, or what it should have concluded."
        ),
    )


class ReplayObservationSerializer(serializers.ModelSerializer):
    scanner_id = serializers.UUIDField(read_only=True, help_text="The scanner that produced this observation.")
    session_id = serializers.CharField(read_only=True, help_text="Session recording id this scanner was applied to.")
    status = serializers.ChoiceField(
        choices=ObservationStatus.choices,
        read_only=True,
        help_text="Observation status (pending, running, succeeded, failed, ineligible).",
    )
    error_reason = serializers.CharField(read_only=True, allow_blank=True, help_text=ERROR_REASON_HELP_TEXT)
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
    distinct_id = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Distinct id of the person in the recorded session (the subject being watched); null if unknown.",
    )
    recording_subject_email = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Email of the person in the recorded session (the subject being watched, not the user who triggered "
            "the observation), captured at scan time. Null when the session had no identified person."
        ),
    )
    previous_observation_id = serializers.SerializerMethodField(
        help_text="Id of the newer sibling observation for the same scanner (prev/next nav); only set on retrieve, null at the start.",
    )
    next_observation_id = serializers.SerializerMethodField(
        help_text="Id of the older sibling observation for the same scanner (prev/next nav); only set on retrieve, null at the end.",
    )

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_previous_observation_id(self, _obj: ReplayObservation) -> uuid.UUID | None:
        return (self.context.get("neighbors") or {}).get("previous")

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_next_observation_id(self, _obj: ReplayObservation) -> uuid.UUID | None:
        return (self.context.get("neighbors") or {}).get("next")

    # `label` shadows DRF's Field.label attribute; the field name is intentional.
    label = serializers.SerializerMethodField(  # type: ignore[assignment]
        help_text="The team's shared label on this observation (correct/incorrect + feedback), or null if unlabeled.",
    )

    @extend_schema_field(ReplayObservationLabelSerializer(allow_null=True))
    def get_label(self, obj: ReplayObservation) -> dict | None:
        # Reverse one-to-one from select_related("label"); getattr returns None when unlabeled.
        label = getattr(obj, "label", None)
        if label is None:
            return None
        return {"is_correct": label.is_correct, "feedback": label.feedback}

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
            "distinct_id",
            "recording_subject_email",
            "previous_observation_id",
            "next_observation_id",
            "label",
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


class ObservationLabelDayCountSerializer(serializers.Serializer):
    date = serializers.DateField(help_text="Day (UTC) the observed sessions were scanned.")
    up = serializers.IntegerField(help_text="Observations scanned this day labeled correct (thumbs up).")
    down = serializers.IntegerField(help_text="Observations scanned this day labeled incorrect (thumbs down).")


class ObservationVersionMarkerSerializer(serializers.Serializer):
    date = serializers.DateField(help_text="First day (UTC) this prompt version produced observations in the window.")
    version = serializers.IntegerField(help_text="The scanner (prompt) version number.")


class ObservationLabelStatsSerializer(serializers.Serializer):
    up_total = serializers.IntegerField(help_text="Observations in the filtered set labeled correct (thumbs up).")
    down_total = serializers.IntegerField(help_text="Observations in the filtered set labeled incorrect (thumbs down).")
    by_day = ObservationLabelDayCountSerializer(
        many=True,
        help_text=(
            "Daily label counts over the last `recent_days` days, bucketed by the day the session was scanned "
            "so the series tracks scanner quality over time. Days without labels are omitted."
        ),
    )
    by_rating_day = ObservationLabelDayCountSerializer(
        many=True,
        help_text=(
            "Daily label counts over the last `recent_days` days, bucketed by the day the rating was last set "
            "or changed: the team's rating activity. Days without rating changes are omitted."
        ),
    )
    version_markers = ObservationVersionMarkerSerializer(
        many=True,
        help_text=(
            "First day each scanner (prompt) version produced observations within the window, for marking "
            "version changes on charts."
        ),
    )


class ObservationStatsSerializer(serializers.Serializer):
    status_counts = ObservationStatusCountsSerializer(help_text="Counts of observations by terminal status.")
    coverage = CoverageStatsSerializer(help_text="Session-level scanner coverage.")
    labels = ObservationLabelStatsSerializer(help_text="Team label (thumbs up/down) aggregates over the filtered set.")
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


class RetryResponseSerializer(serializers.Serializer):
    """Async-accepted response for POST /vision/scanners/{id}/observations/{id}/retry/."""

    workflow_id = serializers.CharField(
        help_text=(
            "Temporal workflow id for the re-run. The retried observation row is deleted; look up its "
            "replacement via GET /vision/scanners/{id}/observations/?session_id=<session_id>."
        ),
    )


# Single source of truth for orderable fields; the list endpoint's OpenAPI override mirrors these as a string enum.
OBSERVATION_ORDER_FIELDS = ("created_at", "started_at", "completed_at", "status")

# JSONB-backed sort keys; numeric values (`result_score`, `scanner_version`) need a numeric cast in the filter.
_JSONB_ORDER_KEYS = ("result_score", "result_verdict", "scanner_version")
_ALL_ORDER_KEYS = OBSERVATION_ORDER_FIELDS + _JSONB_ORDER_KEYS + ("recording_subject_email", "label")


# Derived from the scanner output schema so the filter can never drift from what monitors emit.
_MONITOR_VERDICTS = frozenset(get_args(MonitorVerdict))


class _ObservationOrderByFilter(OrderByFilter):
    """Observation-specific ordering: plain columns + JSONB-backed keys with numeric casts and nulls-last."""

    _allowed_keys = frozenset(_ALL_ORDER_KEYS)

    def _handle(self, qs: QuerySet[ReplayObservation], key: str, descending: bool) -> QuerySet[ReplayObservation]:
        if key in ("started_at", "completed_at"):
            # Null until the row starts/settles — keep in-flight rows out of the way regardless of direction.
            return self._order_nulls_last(qs, key, descending)
        if key in OBSERVATION_ORDER_FIELDS:
            return self._order_plain(qs, key, descending)
        if key == "recording_subject_email":
            # Nullable column — keep unidentified subjects out of the way regardless of direction.
            return self._order_nulls_last(qs, "recording_subject_email", descending)
        if key == "label":
            # Sort by the shared label; unlabeled observations sort last regardless of direction so
            # labeled sessions cluster together (asc: incorrect then correct; desc: correct then incorrect).
            return self._order_nulls_last(qs, "label__is_correct", descending)
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
            return self._order_nulls_last(qs, "_order_score", descending)
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
            return self._order_nulls_last(qs, "_order_version", descending)
        qs = qs.annotate(
            _order_verdict=KeyTextTransform("verdict", KeyTextTransform("model_output", "scanner_result")),
        )
        return self._order_nulls_last(qs, "_order_verdict", descending)


class ReplayObservationFilter(django_filters.FilterSet):
    status = MultiChoiceFilter(
        field_name="status",
        valid_choices=frozenset(v for v, _ in ObservationStatus.choices),
        help_text="Filter by observation status. Accepts a comma-separated list.",
    )
    triggered_by = MultiChoiceFilter(
        field_name="triggered_by",
        valid_choices=frozenset(v for v, _ in ObservationTrigger.choices),
        help_text="Filter by trigger source (schedule or on_demand). Accepts a comma-separated list.",
    )
    verdict = MultiChoiceFilter(
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
    session_id = MultiChoiceFilter(
        field_name="session_id",
        help_text="Filter to observations of one or more session recordings. Accepts a comma-separated list.",
    )
    recording_subject = django_filters.CharFilter(
        field_name="recording_subject_email",
        lookup_expr="icontains",
        help_text="Filter to observations whose recording subject email contains this value (case-insensitive).",
    )
    labeled = django_filters.BooleanFilter(
        method="_filter_labeled",
        help_text=(
            "When true, return only observations that have a shared label (thumbs up or down); "
            "when false, only unlabeled observations."
        ),
    )
    order_by = _ObservationOrderByFilter(
        help_text=(
            "Sort observations by created_at, started_at, completed_at, status, recording_subject_email, "
            "result_score, result_verdict, or scanner_version. Prefix with `-` for descending. Keys that can be "
            "null (started_at, completed_at, recording_subject_email, result_*, scanner_version) sort nulls "
            "last regardless of direction."
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

    def _filter_labeled(
        self, queryset: QuerySet[ReplayObservation], _name: str, value: bool
    ) -> QuerySet[ReplayObservation]:
        return queryset.filter(label__isnull=not value)

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
                enum=ordering_enum(_ALL_ORDER_KEYS),
                description=(
                    "Sort observations. Plain keys: created_at, started_at, completed_at, status, "
                    "recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), "
                    "scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way."
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
            .select_related("triggered_by_user", "label")
            .order_by("-created_at", "id")
        )

    @extend_schema(
        parameters=[
            *ReplayObservationFilter.schema_parameters(),
            OpenApiParameter(
                "recent_days",
                int,
                OpenApiParameter.QUERY,
                description=(
                    "Window size in days for the coverage `recent_sessions` count. Clamped to [1, 365]. "
                    "Defaults to 14 when omitted."
                ),
                required=False,
            ),
        ],
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
        recent_days_raw = request.query_params.get("recent_days")
        try:
            recent_days = int(recent_days_raw) if recent_days_raw is not None else 14
        except (TypeError, ValueError):
            recent_days = 14
        payload = compute_observation_stats(scanner, queryset, recent_days=recent_days)
        return Response(payload)

    @extend_schema(request=None, responses={202: RetryResponseSerializer})
    @action(detail=True, methods=["post"], required_scopes=["replay_scanner:write", "session_recording:read"])
    def retry(self, request: Request, **kwargs: Any) -> Response:
        """Delete a failed observation and re-run its scanner on the same recording. Returns 202 with the workflow handle."""
        observation = self.get_object()
        # The nested route already resolved the scanner for RBAC; the session route pays one FK fetch.
        scanner = getattr(self, "_scanner_for_url_cache", None) or observation.scanner
        # Retry writes to the scanner; the session route's get_object only object-checks the observation row.
        self.check_object_permissions(self.request, scanner)
        if observation.status != ObservationStatus.FAILED:
            raise ValidationError("Only failed observations can be retried.")
        check_observation_quota(self.team.organization_id)
        session_id = observation.session_id
        # Free the UNIQUE(scanner, session_id) slot; the usage ledger is immutable, so the failed attempt stays counted.
        observation.delete()
        workflow_id, outcome = start_apply_scanner_workflow(
            scanner, session_id, triggered_by_user_id=cast(User, request.user).id
        )
        if outcome is WorkflowStartOutcome.ALREADY_RUNNING:
            # The prior run is still closing, so its deterministic id blocks the restart and no new row will appear.
            return Response(
                {"detail": "The previous run is still finishing. Scan the recording again in a moment."},
                status=status.HTTP_409_CONFLICT,
            )
        if outcome is WorkflowStartOutcome.FAILED:
            # `detail` (not `error`) so ApiError carries the message into the frontend toast.
            return Response(
                {
                    "detail": "Failed to start the retry. The recording now shows as not scanned and can be scanned again."
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(RetryResponseSerializer({"workflow_id": workflow_id}).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        methods=["POST"],
        request=ReplayObservationLabelSerializer,
        responses={200: ReplayObservationLabelSerializer},
        description=(
            "Set or update the observation's shared label: whether the scanner scored the session correctly, "
            "plus optional feedback on what it got wrong. One label per observation, shared across the team; "
            "these labels feed prompt improvement. Requires session recording edit access."
        ),
    )
    @extend_schema(
        methods=["DELETE"],
        responses={204: None},
        description="Remove the observation's shared label. Requires session recording edit access.",
    )
    @action(
        detail=True,
        methods=["post", "delete"],
        url_path="label",
        # Shared team data: writing requires the scanner write scope, mirroring the scanner-edit gate.
        required_scopes=["replay_scanner:write", "session_recording:read"],
    )
    def label(self, request: Request, **kwargs: Any) -> Response:
        observation = self.get_object()
        # Editing the shared label needs edit access, not just the viewer access reading needs.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="editor"):
            raise PermissionDenied("Editing observation labels requires session_recording edit access.")
        user = cast(User, request.user)
        if request.method == "DELETE":
            ReplayObservationLabel.objects.filter(observation=observation, team_id=observation.team_id).delete()
            return Response(status=204)
        input_serializer = ReplayObservationLabelSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        # team_id in the lookup keeps the query team-scoped.
        label, _ = ReplayObservationLabel.objects.update_or_create(
            observation=observation,
            team_id=observation.team_id,
            defaults={
                "is_correct": input_serializer.validated_data["is_correct"],
                "feedback": input_serializer.validated_data.get("feedback", ""),
                "created_by": user,
            },
        )
        return Response(ReplayObservationLabelSerializer(label).data)


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
            .select_related("triggered_by_user", "label")
            .order_by("-created_at", "id")
        )
        # A bare list would scan the whole team's observation history; the replay page always has a session.
        if self.action == "list":
            session_id = self.request.query_params.get("session_id")
            if not session_id:
                raise ValidationError("The `session_id` query parameter is required.")
            queryset = queryset.filter(session_id=session_id)
        return queryset

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        observation = self.get_object()
        context = {**self.get_serializer_context(), "neighbors": self._observation_neighbors(observation)}
        return Response(self.get_serializer(observation, context=context).data)

    @staticmethod
    def _observation_neighbors(observation: ReplayObservation) -> dict[str, uuid.UUID | None]:
        # Newest-first list order, so the newer sibling is "previous" and the older one is "next".
        siblings = ReplayObservation.objects.filter(
            team_id=observation.team_id, scanner_id=observation.scanner_id
        ).values_list("id", flat=True)
        # Tie-break on id to mirror the list's (-created_at, id) order, so same-timestamp siblings aren't skipped.
        return {
            "previous": siblings.filter(
                Q(created_at__gt=observation.created_at) | Q(created_at=observation.created_at, id__lt=observation.id)
            )
            .order_by("created_at", "-id")
            .first(),
            "next": siblings.filter(
                Q(created_at__lt=observation.created_at) | Q(created_at=observation.created_at, id__gt=observation.id)
            )
            .order_by("-created_at", "id")
            .first(),
        }

    # Hide `stats/` on the session-scoped viewset — it has no `parent_lookup_scanner_id` to dispatch on.
    def stats(self, request: Request, **kwargs: Any) -> Response:  # type: ignore[override]
        raise NotFound()

    @extend_schema(exclude=True)
    @action(detail=True, methods=["GET"], url_path="progress", renderer_classes=[ServerSentEventRenderer])
    def progress(self, request: Request, **kwargs: Any) -> StreamingHttpResponse:
        """Stream live progress (phase + rendering frame counts) for one in-flight observation as SSE.

        `get_object()` applies the same RBAC scoping as retrieve, so this can't leak observations the caller
        can't read. The stream self-terminates once the observation reaches a terminal state.
        """
        # The generator is `async def` — WSGI can't consume an async iterator, so fail loudly there.
        if getattr(settings, "SERVER_GATEWAY_INTERFACE", "ASGI") != "ASGI":
            raise RuntimeError("observation progress stream requires ASGI.")
        observation = self.get_object()
        return sse_streaming_response(stream_observation_progress(observation), endpoint="replay_vision_observation")
