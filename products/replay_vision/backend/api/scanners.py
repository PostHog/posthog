import datetime as dt
from typing import Any, NoReturn, cast

from django.conf import settings
from django.db import IntegrityError
from django.db.models import QuerySet

import structlog
import django_filters
from asgiref.sync import async_to_sync
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_field
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.schema import RecordingsQuery

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.user import User
from posthog.temporal.common.client import sync_connect

from products.replay_vision.backend.api.constants import VISION_TAG
from products.replay_vision.backend.feature_flag import ReplayVisionEnabledPermission
from products.replay_vision.backend.models.replay_observation import ObservationTrigger
from products.replay_vision.backend.models.replay_scanner import (
    ReplayScanner,
    ScannerModel,
    ScannerProvider,
    ScannerType,
)
from products.replay_vision.backend.queries import estimate_scanner_session_volume
from products.replay_vision.backend.temporal.constants import (
    APPLY_SCANNER_WORKFLOW_NAME,
    MAX_SESSION_ID_LENGTH,
    build_apply_scanner_workflow_id,
)
from products.replay_vision.backend.temporal.scanners import validate_scanner_config
from products.replay_vision.backend.temporal.types import ApplyScannerInputs

# Date is set by the schedule at trigger time, not by the user — strip on save.
_QUERY_FIELDS_TO_STRIP = ("date_from", "date_to")

logger = structlog.get_logger(__name__)


class ReplayScannerSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        max_length=255,
        help_text="Human-readable scanner name. Unique within the team.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Free-form description shown in the scanner management UI.",
    )
    scanner_type = serializers.ChoiceField(
        choices=ScannerType.choices,
        help_text="What the scanner does: monitor, classifier, scorer, summarizer, or indexer.",
    )
    scanner_config = serializers.JSONField(
        help_text=(
            "Type-specific configuration. Monitor/classifier/scorer/summarizer require `prompt`; "
            "classifiers add `tags`, scorers add `scale`. Indexer is fixed-task and rejects `prompt`."
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
        help_text="0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling).",
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
            "provider",
            "model",
            "enabled",
            "emits_signals",
            "scanner_version",
            "last_swept_at",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "scanner_version",
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
        self._validate_scanner_config(attrs)
        self._validate_and_strip_query(attrs)
        return attrs

    def _validate_scanner_config(self, attrs: dict[str, Any]) -> None:
        # Skip when neither field is touched on PATCH — the existing combination has already been validated.
        if "scanner_config" not in attrs and "scanner_type" not in attrs:
            return
        scanner_type = attrs.get("scanner_type", getattr(self.instance, "scanner_type", None))
        scanner_config = attrs.get("scanner_config", getattr(self.instance, "scanner_config", None))
        if scanner_type is None:
            return  # Upstream `scanner_type` ChoiceField rejects this on create; PATCH with no instance is unreachable.
        try:
            validate_scanner_config(scanner_config=scanner_config, scanner_type=ScannerType(scanner_type))
        except (ValueError, PydanticValidationError) as exc:
            raise serializers.ValidationError({"scanner_config": str(exc)})

    def _validate_and_strip_query(self, attrs: dict[str, Any]) -> None:
        if "query" not in attrs:
            return
        try:
            RecordingsQuery.model_validate(attrs["query"])
        except PydanticValidationError as exc:
            raise serializers.ValidationError({"query": str(exc)})
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
            return ReplayScanner.objects.create(team=team, created_by=user, **validated_data)
        except IntegrityError as e:
            self._reraise_unique_name_violation(e)

    def update(self, instance: ReplayScanner, validated_data: dict[str, Any]) -> ReplayScanner:
        try:
            return super().update(instance, validated_data)
        except IntegrityError as e:
            self._reraise_unique_name_violation(e)

    @staticmethod
    def _reraise_unique_name_violation(error: IntegrityError) -> NoReturn:
        # Narrow to the unique-name constraint so other future constraints aren't mis-reported as duplicates.
        if "replay_scanner_unique_team_name" in str(error):
            raise serializers.ValidationError({"name": "A scanner with this name already exists in this team."})
        raise error


class ReplayScannerFilter(django_filters.FilterSet):
    enabled = django_filters.BooleanFilter(
        field_name="enabled",
        help_text="Filter to enabled vs disabled scanners.",
    )
    scanner_type = django_filters.ChoiceFilter(
        field_name="scanner_type",
        choices=ScannerType.choices,
        help_text="Filter by scanner type (monitor, classifier, scorer, summarizer, indexer).",
    )
    emits_signals = django_filters.BooleanFilter(
        field_name="emits_signals",
        help_text="Filter to scanners that emit Signals.",
    )
    order_by = django_filters.OrderingFilter(
        fields=(
            ("name", "name"),
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
            ("scanner_type", "scanner_type"),
        ),
        help_text="Sort scanners by name, created_at, updated_at, or scanner_type. Prefix with `-` for descending.",
    )

    class Meta:
        model = ReplayScanner
        fields = ["enabled", "scanner_type", "emits_signals"]


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

    def validate_query(self, value: dict[str, Any]) -> dict[str, Any]:
        try:
            RecordingsQuery.model_validate(value)
        except PydanticValidationError as exc:
            raise serializers.ValidationError(str(exc))
        return {k: v for k, v in value.items() if k not in _QUERY_FIELDS_TO_STRIP}


class EstimateResponseSerializer(serializers.Serializer):
    """Forward-looking observation-volume estimate for a proposed scanner. Pricing-agnostic."""

    matched_sessions_in_window = serializers.IntegerField(
        help_text="Distinct sessions matching the query within the 30-day lookback, before sampling.",
    )
    window_days = serializers.IntegerField(
        help_text=(
            "Lookback window the estimate is based on. Normally 30; smaller when the team has fewer days of recordings."
        ),
    )
    estimated_observations_per_month = serializers.IntegerField(
        help_text="Projected monthly observations: matched sessions scaled to 30 days, times sampling_rate.",
    )
    sampling_rate = serializers.FloatField(
        help_text="Sampling rate applied to the projection. Echoed from the request.",
    )


@extend_schema(tags=[VISION_TAG])
class ReplayScannerViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """CRUD for Replay Vision scanners."""

    scope_object = "replay_scanner"
    # Custom actions must be listed explicitly or personal-API-key callers 403 silently.
    scope_object_write_actions = ["create", "update", "partial_update", "destroy", "observe"]
    permission_classes = [ReplayVisionEnabledPermission]
    serializer_class = ReplayScannerSerializer
    queryset = ReplayScanner.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = ReplayScannerFilter
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet[ReplayScanner]) -> QuerySet[ReplayScanner]:
        return queryset.filter(team_id=self.team_id).select_related("created_by").order_by("name", "id")

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

        body = ObserveRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        session_id: str = body.validated_data["session_id"]
        user = cast(User, request.user)

        workflow_id = build_apply_scanner_workflow_id(scanner.id, session_id)
        try:
            client = sync_connect()
            async_to_sync(client.start_workflow)(  # type: ignore[misc]
                APPLY_SCANNER_WORKFLOW_NAME,  # type: ignore[arg-type]
                ApplyScannerInputs(  # type: ignore[arg-type]
                    scanner_id=scanner.id,
                    session_id=session_id,
                    team_id=scanner.team_id,
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=user.id,
                ),
                id=workflow_id,
                task_queue=settings.REPLAY_VISION_TASK_QUEUE,
                execution_timeout=dt.timedelta(hours=1),
            )
        except WorkflowAlreadyStartedError as exc:
            # Pin to our own workflow_id so a future id_reuse_policy change can't silently 202 an unrelated run.
            if exc.workflow_id != workflow_id:
                logger.exception("replay_vision.observe.workflow_id_mismatch", workflow_id=workflow_id)
                return Response(
                    {"error": "Failed to start observation workflow"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            logger.info("replay_vision.observe.workflow_already_started", workflow_id=workflow_id)
        except Exception:
            logger.exception("replay_vision.observe.workflow_start_failed", workflow_id=workflow_id)
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

        # validate_query already validated this; the empty-dict default needs `kind` to parse.
        query_dict: dict[str, Any] = dict(body.validated_data.get("query") or {})
        query_dict.setdefault("kind", "RecordingsQuery")
        recordings_query = RecordingsQuery.model_validate(query_dict)

        estimate = estimate_scanner_session_volume(team=self.team, query=recordings_query)
        sessions_per_day = estimate.matched_sessions / estimate.effective_window_days
        observations_per_month = round(sessions_per_day * 30 * sampling_rate)

        return Response(
            EstimateResponseSerializer(
                {
                    "matched_sessions_in_window": estimate.matched_sessions,
                    "window_days": estimate.effective_window_days,
                    "estimated_observations_per_month": observations_per_month,
                    "sampling_rate": sampling_rate,
                }
            ).data
        )
