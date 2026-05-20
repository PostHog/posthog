import uuid

from django.db.models import QuerySet

import structlog
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_field
from pydantic import ValidationError as PydanticValidationError
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.replay_vision.backend.api.constants import VISION_TAG
from products.replay_vision.backend.feature_flag import ReplayVisionEnabledPermission
from products.replay_vision.backend.models.replay_lens import LensModel, LensProvider, LensType, ReplayLens
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.temporal.types import LensResult, LensSnapshot

logger = structlog.get_logger(__name__)


class LensSnapshotSerializer(serializers.Serializer):
    """Mirrors `temporal.types.LensSnapshot` for OpenAPI generation."""

    name = serializers.CharField(
        help_text="Lens name at run time.",
    )
    lens_type = serializers.ChoiceField(
        choices=LensType.choices,
        help_text="Lens type (monitor, classifier, scorer, summarizer, indexer) at run time.",
    )
    lens_version = serializers.IntegerField(
        help_text="The `ReplayLens.lens_version` value at the moment the workflow ran.",
    )
    model = serializers.ChoiceField(
        choices=LensModel.choices,
        help_text="Concrete model that ran the observation.",
    )
    provider = serializers.ChoiceField(
        choices=LensProvider.choices,
        help_text="Concrete provider that ran the observation.",
    )
    emits_signals = serializers.BooleanField(
        help_text="Whether the observation was run with Signal emission enabled.",
    )
    lens_config = serializers.JSONField(
        help_text="Lens-type-specific configuration at run time (prompt, tags, scale, etc.).",
    )


class LensResultSerializer(serializers.Serializer):
    """Mirrors `temporal.types.LensResult` for OpenAPI generation."""

    model_output = serializers.JSONField(
        help_text="Validated lens output. Shape depends on `lens_snapshot.lens_type`; always carries `confidence` and `lens_type`.",
    )
    signals_count = serializers.IntegerField(
        min_value=0,
        help_text="Number of PostHog Signals emitted from this observation.",
    )


class ReplayObservationSerializer(serializers.ModelSerializer):
    lens_id = serializers.UUIDField(read_only=True, help_text="The lens that produced this observation.")
    session_id = serializers.CharField(read_only=True, help_text="Session recording id this lens was applied to.")
    status = serializers.ChoiceField(
        choices=ObservationStatus.choices,
        read_only=True,
        help_text="Observation status (pending, running, succeeded, failed).",
    )
    error_reason = serializers.CharField(
        read_only=True,
        allow_blank=True,
        help_text="Populated on failure; includes the malformed model response when validation fails.",
    )
    workflow_id = serializers.CharField(
        read_only=True,
        allow_blank=True,
        help_text="Temporal workflow id for progress queries and debugging. Empty until the workflow starts.",
    )
    lens_snapshot = serializers.SerializerMethodField(
        help_text="Frozen view of the lens at run time; lens edits do not retroactively mutate this observation.",
    )
    lens_result = serializers.SerializerMethodField(
        help_text="Result data persisted on success; null until the observation succeeds.",
    )

    @extend_schema_field(LensSnapshotSerializer(allow_null=True))
    def get_lens_snapshot(self, obj: ReplayObservation) -> dict | None:
        if not obj.lens_snapshot:
            return None  # Snapshot is supposed to be populated at create; an empty blob is a write-side bug.
        try:
            return LensSnapshot.model_validate(obj.lens_snapshot).model_dump(mode="json")
        except PydanticValidationError:
            logger.exception("replay_vision.observation.malformed_lens_snapshot", observation_id=str(obj.id))
            return None

    @extend_schema_field(LensResultSerializer(allow_null=True))
    def get_lens_result(self, obj: ReplayObservation) -> dict | None:
        if not obj.lens_result:
            return None
        try:
            return LensResult.model_validate(obj.lens_result).model_dump(mode="json")
        except PydanticValidationError:
            logger.exception("replay_vision.observation.malformed_lens_result", observation_id=str(obj.id))
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
            "lens_id",
            "session_id",
            "status",
            "error_reason",
            "workflow_id",
            "lens_snapshot",
            "lens_result",
            "triggered_by",
            "triggered_by_user",
            "started_at",
            "completed_at",
            "created_at",
        ]


class ReplayObservationFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(
        field_name="status",
        choices=ObservationStatus.choices,
        help_text="Filter by observation status.",
    )
    triggered_by = django_filters.ChoiceFilter(
        field_name="triggered_by",
        choices=ObservationTrigger.choices,
        help_text="Filter by trigger source (schedule or on_demand).",
    )
    session_id = django_filters.CharFilter(
        field_name="session_id",
        help_text="Filter to observations of a specific session recording.",
    )
    order_by = django_filters.OrderingFilter(
        fields=(
            ("created_at", "created_at"),
            ("started_at", "started_at"),
            ("completed_at", "completed_at"),
            ("status", "status"),
        ),
        help_text="Sort observations by created_at, started_at, completed_at, or status. Prefix with `-` for descending.",
    )

    class Meta:
        model = ReplayObservation
        fields = ["status", "triggered_by", "session_id"]


@extend_schema(tags=[VISION_TAG])
class ReplayObservationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only access to observations produced by a lens."""

    scope_object = "replay_lens"
    required_scopes = ["replay_lens:read", "session_recording:read"]
    permission_classes = [ReplayVisionEnabledPermission]
    serializer_class = ReplayObservationSerializer
    queryset = ReplayObservation.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = ReplayObservationFilter

    def safely_get_queryset(self, queryset: QuerySet[ReplayObservation]) -> QuerySet[ReplayObservation]:
        try:
            lens_id = uuid.UUID(self.kwargs["parent_lookup_lens_id"])
        except (KeyError, ValueError):
            raise NotFound()
        lens = ReplayLens.objects.filter(team_id=self.team_id, id=lens_id).first()
        if lens is None:
            raise NotFound()
        # Observations expose recording-derived output, so observe inherits the lens's RBAC and also requires session_recording read.
        self.check_object_permissions(self.request, lens)
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading replay observations requires session_recording read access.")
        return (
            queryset.filter(team_id=self.team_id, lens_id=lens_id)
            .select_related("triggered_by_user")
            .order_by("-created_at", "id")
        )
