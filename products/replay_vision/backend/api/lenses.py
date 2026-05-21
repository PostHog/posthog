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
from products.replay_vision.backend.models.replay_lens import LensModel, LensProvider, LensType, ReplayLens
from products.replay_vision.backend.models.replay_observation import ObservationTrigger
from products.replay_vision.backend.temporal.constants import (
    APPLY_LENS_WORKFLOW_NAME,
    MAX_SESSION_ID_LENGTH,
    build_apply_lens_workflow_id,
)
from products.replay_vision.backend.temporal.lenses import validate_lens_config
from products.replay_vision.backend.temporal.types import ApplyLensInputs

# Date is set by the schedule at trigger time, not by the user — strip on save.
_QUERY_FIELDS_TO_STRIP = ("date_from", "date_to")

logger = structlog.get_logger(__name__)


class ReplayLensSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        max_length=255,
        help_text="Human-readable lens name. Unique within the team.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Free-form description shown in the lens management UI.",
    )
    lens_type = serializers.ChoiceField(
        choices=LensType.choices,
        help_text="What the lens does: monitor, classifier, scorer, summarizer, or indexer.",
    )
    lens_config = serializers.JSONField(
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
        choices=LensProvider.choices,
        required=False,
        help_text="LLM provider. v1 is Google-only.",
    )
    model = serializers.ChoiceField(
        choices=LensModel.choices,
        help_text="Concrete model to use for this lens.",
    )
    enabled = serializers.BooleanField(
        required=False,
        help_text="When false, the reconciler removes the lens's Temporal schedule. On-demand triggers still work.",
    )
    emits_signals = serializers.BooleanField(
        required=False,
        help_text="When true, the prompt is augmented with the Signal side mission and the lens emits PostHog Signals.",
    )

    lens_version = serializers.IntegerField(
        read_only=True,
        help_text="Increments on every config-changing save. Observations snapshot this value.",
    )
    last_swept_at = serializers.DateTimeField(
        read_only=True,
        help_text="Watermark for the lens's last scheduled fire. Mirrors Temporal schedule state for recovery.",
    )
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who created the lens.",
    )

    class Meta:
        model = ReplayLens
        fields = [
            "id",
            "name",
            "description",
            "lens_type",
            "lens_config",
            "query",
            "sampling_rate",
            "provider",
            "model",
            "enabled",
            "emits_signals",
            "lens_version",
            "last_swept_at",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "lens_version",
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
            duplicates = ReplayLens.objects.filter(team=team, name=name)
            if self.instance is not None:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError({"name": "A lens with this name already exists in this team."})
        self._validate_lens_config(attrs)
        self._validate_and_strip_query(attrs)
        return attrs

    def _validate_lens_config(self, attrs: dict[str, Any]) -> None:
        # Skip when neither field is touched on PATCH — the existing combination has already been validated.
        if "lens_config" not in attrs and "lens_type" not in attrs:
            return
        lens_type = attrs.get("lens_type", getattr(self.instance, "lens_type", None))
        lens_config = attrs.get("lens_config", getattr(self.instance, "lens_config", None))
        if lens_type is None:
            return  # Upstream `lens_type` ChoiceField rejects this on create; PATCH with no instance is unreachable.
        try:
            validate_lens_config(lens_config=lens_config, lens_type=LensType(lens_type))
        except (ValueError, PydanticValidationError) as exc:
            raise serializers.ValidationError({"lens_config": str(exc)})

    def _validate_and_strip_query(self, attrs: dict[str, Any]) -> None:
        if "query" not in attrs:
            return
        try:
            RecordingsQuery.model_validate(attrs["query"])
        except PydanticValidationError as exc:
            raise serializers.ValidationError({"query": str(exc)})
        # Persist exactly what the user sent (validated), minus the date keys the schedule controls.
        attrs["query"] = {k: v for k, v in attrs["query"].items() if k not in _QUERY_FIELDS_TO_STRIP}

    def to_representation(self, instance: ReplayLens) -> dict[str, Any]:
        data = super().to_representation(instance)
        # `is not None` (not falsy) so empty-dict queries still revalidate against future schema changes.
        if data.get("query") is not None:
            try:
                RecordingsQuery.model_validate(data["query"])
            except PydanticValidationError:
                logger.exception("replay_vision.lens.malformed_query", lens_id=str(instance.id))
                data["query"] = None
        return data

    def create(self, validated_data: dict[str, Any]) -> ReplayLens:
        team = self.context["get_team"]()
        user = cast(User, self.context["request"].user)
        try:
            return ReplayLens.objects.create(team=team, created_by=user, **validated_data)
        except IntegrityError as e:
            self._reraise_unique_name_violation(e)

    def update(self, instance: ReplayLens, validated_data: dict[str, Any]) -> ReplayLens:
        try:
            return super().update(instance, validated_data)
        except IntegrityError as e:
            self._reraise_unique_name_violation(e)

    @staticmethod
    def _reraise_unique_name_violation(error: IntegrityError) -> NoReturn:
        # Narrow to the unique-name constraint so other future constraints aren't mis-reported as duplicates.
        if "replay_lens_unique_team_name" in str(error):
            raise serializers.ValidationError({"name": "A lens with this name already exists in this team."})
        raise error


class ReplayLensFilter(django_filters.FilterSet):
    enabled = django_filters.BooleanFilter(
        field_name="enabled",
        help_text="Filter to enabled vs disabled lenses.",
    )
    lens_type = django_filters.ChoiceFilter(
        field_name="lens_type",
        choices=LensType.choices,
        help_text="Filter by lens type (monitor, classifier, scorer, summarizer, indexer).",
    )
    emits_signals = django_filters.BooleanFilter(
        field_name="emits_signals",
        help_text="Filter to lenses that emit Signals.",
    )
    order_by = django_filters.OrderingFilter(
        fields=(
            ("name", "name"),
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
            ("lens_type", "lens_type"),
        ),
        help_text="Sort lenses by name, created_at, updated_at, or lens_type. Prefix with `-` for descending.",
    )

    class Meta:
        model = ReplayLens
        fields = ["enabled", "lens_type", "emits_signals"]


class ObserveRequestSerializer(serializers.Serializer):
    """Body of POST /vision/lenses/{id}/observe/."""

    session_id = serializers.CharField(
        max_length=MAX_SESSION_ID_LENGTH,
        help_text="ID of the session recording to apply the lens to.",
    )


class ObserveResponseSerializer(serializers.Serializer):
    """Async-accepted response for POST /vision/lenses/{id}/observe/."""

    workflow_id = serializers.CharField(
        help_text=(
            "Temporal workflow id for this lens application. Look up the resulting "
            "ReplayObservation via GET /vision/lenses/{id}/observations/?session_id=<session_id>."
        ),
    )


@extend_schema(tags=[VISION_TAG])
class ReplayLensViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """CRUD for Replay Vision lenses."""

    scope_object = "replay_lens"
    # Custom actions must be listed explicitly or personal-API-key callers 403 silently.
    scope_object_write_actions = ["create", "update", "partial_update", "destroy", "observe"]
    permission_classes = [ReplayVisionEnabledPermission]
    serializer_class = ReplayLensSerializer
    queryset = ReplayLens.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = ReplayLensFilter
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet[ReplayLens]) -> QuerySet[ReplayLens]:
        return queryset.filter(team_id=self.team_id).select_related("created_by").order_by("name", "id")

    @extend_schema(
        request=ObserveRequestSerializer,
        responses={202: ObserveResponseSerializer},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="observe",
        required_scopes=["replay_lens:write", "session_recording:read"],
    )
    def observe(self, request: Request, **kwargs: Any) -> Response:
        """Apply this lens to one specific session, on demand. Returns 202 with the workflow handle."""
        lens = self.get_object()
        # Observation output exposes recording contents, so observe requires session_recording read.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Triggering an on-demand observation requires session_recording read access.")

        body = ObserveRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        session_id: str = body.validated_data["session_id"]
        user = cast(User, request.user)

        workflow_id = build_apply_lens_workflow_id(lens.id, session_id)
        try:
            client = sync_connect()
            async_to_sync(client.start_workflow)(  # type: ignore[misc]
                APPLY_LENS_WORKFLOW_NAME,  # type: ignore[arg-type]
                ApplyLensInputs(  # type: ignore[arg-type]
                    lens_id=lens.id,
                    session_id=session_id,
                    team_id=lens.team_id,
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
