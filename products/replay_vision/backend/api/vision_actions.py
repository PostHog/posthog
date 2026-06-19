from typing import Any, NoReturn, cast

from django.db import IntegrityError
from django.db.models import QuerySet

import structlog
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.models.integration import Integration
from posthog.models.user import User

from products.replay_vision.backend.feature_flag import (
    ReplayVisionActionsEnabledPermission,
    ReplayVisionEnabledPermission,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.models.vision_action import ActionMode, TriggerType, VisionAction
from products.replay_vision.backend.rrule import validate_rrule

logger = structlog.get_logger(__name__)


class TriggerConfigSerializer(serializers.Serializer):
    """Schedule trigger parameters. Threshold triggers are reserved and rejected at the API for now."""

    rrule = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="iCal RRULE string controlling the schedule cadence (no DTSTART — the start is managed separately).",
    )
    timezone = serializers.CharField(
        required=False,
        default="UTC",
        help_text="IANA timezone name the RRULE is expanded in, e.g. 'Europe/Prague'. Defaults to 'UTC'.",
    )


class SelectionSerializer(serializers.Serializer):
    """Observation filter applied at synthesis time. All keys optional; this typed shape is the
    allowlist, so unknown input keys are dropped rather than persisted."""

    scanner_type = serializers.CharField(
        required=False,
        help_text="Filter observations by scanner type (monitor/classifier/scorer/summarizer).",
    )
    scanner_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Restrict to observations produced by these scanner IDs.",
    )
    verdict = serializers.CharField(
        required=False,
        help_text="Filter to observations with this monitor verdict.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Filter to observations carrying any of these classifier tags.",
    )
    min_score = serializers.FloatField(
        required=False,
        help_text="Lower bound (inclusive) on scorer score.",
    )
    max_score = serializers.FloatField(
        required=False,
        help_text="Upper bound (inclusive) on scorer score.",
    )
    status = serializers.CharField(
        required=False,
        help_text="Filter to observations with this processing status.",
    )
    window_days = serializers.IntegerField(
        required=False,
        help_text="Lookback window in days for the observations gathered at synthesis time.",
    )


class SynthesisConfigSerializer(serializers.Serializer):
    """Options for the group-summary synthesis step."""

    prompt_guide = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Free-form guidance steering how the group summary is written.",
    )


class DeliveryTargetSerializer(serializers.Serializer):
    """A single delivery destination. MVP supports Slack only."""

    type = serializers.ChoiceField(
        choices=[("slack", "Slack")],
        help_text="Destination channel type. MVP supports 'slack' only.",
    )
    integration_id = serializers.IntegerField(
        help_text="ID of the Slack Integration on this team used to deliver the summary.",
    )
    channel = serializers.CharField(
        help_text="Slack channel ID or name the summary is posted to.",
    )


class VisionActionSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        max_length=255,
        help_text="Human-readable action name. Unique within the team.",
    )
    scanner = TeamScopedPrimaryKeyRelatedField(
        queryset=ReplayScanner.objects.all(),
        help_text="Scanner whose observations this action operates on. Must belong to the same team.",
    )
    enabled = serializers.BooleanField(
        required=False,
        help_text="When false, the scheduler skips this action.",
    )
    trigger_type = serializers.ChoiceField(
        choices=TriggerType.choices,
        required=False,
        help_text="What fires the action. MVP supports 'schedule' only.",
    )
    mode = serializers.ChoiceField(
        choices=ActionMode.choices,
        required=False,
        help_text="What the action produces. MVP supports 'group_summary' only.",
    )
    trigger_config = TriggerConfigSerializer(
        required=False,
        help_text="Trigger parameters. For schedule triggers: {rrule, timezone}.",
    )
    selection = SelectionSerializer(
        required=False,
        help_text="Observation filter applied at synthesis time.",
    )
    synthesis_config = SynthesisConfigSerializer(
        required=False,
        help_text="Synthesis options for the group summary, e.g. {prompt_guide}.",
    )
    delivery_config = DeliveryTargetSerializer(
        many=True,
        required=False,
        help_text="List of delivery destinations the synthesized summary is sent to.",
    )

    next_run_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Computed next fire time for schedule triggers; the scheduler scans this.",
    )
    last_run_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Timestamp of the most recent run, or null if it has never run.",
    )
    hog_flow_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="ID of the delivery flow provisioned for this action. Null until delivery is wired up.",
    )
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who created the action.",
    )

    class Meta:
        model = VisionAction
        fields = [
            "id",
            "name",
            "scanner",
            "enabled",
            "trigger_type",
            "mode",
            "trigger_config",
            "selection",
            "synthesis_config",
            "delivery_config",
            "next_run_at",
            "last_run_at",
            "hog_flow_id",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "next_run_at",
            "last_run_at",
            "hog_flow_id",
            "created_at",
            "created_by",
            "updated_at",
        ]

    def validate_trigger_type(self, value: str) -> str:
        if value == TriggerType.THRESHOLD:
            raise serializers.ValidationError("Threshold triggers are not supported yet. Use 'schedule'.")
        return value

    def validate_mode(self, value: str) -> str:
        if value == ActionMode.PER_OBSERVATION:
            raise serializers.ValidationError("Per-observation mode is not supported yet. Use 'group_summary'.")
        return value

    def validate_delivery_config(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # IDOR guard: every referenced integration must belong to the team.
        team = self.context["get_team"]()
        for target in value:
            if target.get("type") != "slack":
                raise serializers.ValidationError("Only 'slack' delivery targets are supported.")
            # DeliveryTargetSerializer guarantees integration_id is present and an int — subscript so
            # mypy sees a concrete value, not Optional, for the id lookup.
            integration_id = target["integration_id"]
            if not Integration.objects.filter(team=team, id=integration_id, kind="slack").exists():
                raise serializers.ValidationError(f"Slack integration {integration_id} not found in this team.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        self._validate_schedule(attrs)
        self._validate_unique_name(attrs)
        return attrs

    def _validate_schedule(self, attrs: dict[str, Any]) -> None:
        trigger_type = attrs.get("trigger_type", getattr(self.instance, "trigger_type", TriggerType.SCHEDULE))
        trigger_config = attrs.get("trigger_config", getattr(self.instance, "trigger_config", None)) or {}
        if trigger_type != TriggerType.SCHEDULE:
            return
        rrule = trigger_config.get("rrule")
        if not rrule:
            return
        try:
            validate_rrule(rrule)
        except ValueError as e:
            raise serializers.ValidationError({"trigger_config": {"rrule": str(e)}})

    def _validate_unique_name(self, attrs: dict[str, Any]) -> None:
        # Surface the (team, name) uniqueness as a 400 instead of letting the DB raise 500.
        name = attrs.get("name")
        if name is None:
            return
        team = self.context["get_team"]()
        duplicates = VisionAction.objects.for_team(team.id).filter(name=name)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError({"name": "An action with this name already exists in this team."})

    def create(self, validated_data: dict[str, Any]) -> VisionAction:
        team = self.context["get_team"]()
        user = cast(User, self.context["request"].user)
        try:
            # for_team()'s filter doesn't propagate into create(), so team is still passed explicitly.
            return VisionAction.objects.for_team(team.id).create(team=team, created_by=user, **validated_data)
        except IntegrityError as e:
            self._reraise_unique_name_violation(e)

    def update(self, instance: VisionAction, validated_data: dict[str, Any]) -> VisionAction:
        try:
            return super().update(instance, validated_data)
        except IntegrityError as e:
            self._reraise_unique_name_violation(e)

    @staticmethod
    def _reraise_unique_name_violation(error: IntegrityError) -> NoReturn:
        if "vision_action_unique_team_name" in str(error):
            raise serializers.ValidationError({"name": "An action with this name already exists in this team."})
        raise error


class VisionActionViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations."""

    scope_object = "vision_action"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create", "update", "partial_update", "destroy"]
    permission_classes = [ReplayVisionEnabledPermission, ReplayVisionActionsEnabledPermission]
    serializer_class = VisionActionSerializer
    # `objects` is fail-closed; `safely_get_queryset` re-scopes to the request team.
    queryset = VisionAction.objects.unscoped()
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    # Configuring an action reads observations derived from recordings and sends them off-platform.
    _CONFIG_ACTIONS = {"create", "update", "partial_update"}

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        if self.action in self._CONFIG_ACTIONS:
            return ["vision_action:write", "session_recording:read"]
        return None

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if self.action in self._CONFIG_ACTIONS and not self.user_access_control.check_access_level_for_resource(
            "session_recording", required_level="viewer"
        ):
            raise PermissionDenied("Configuring a Replay Vision action requires session_recording read access.")

    def safely_get_queryset(self, queryset: QuerySet[VisionAction]) -> QuerySet[VisionAction]:
        return queryset.filter(team_id=self.team_id).select_related("scanner", "created_by").order_by("name", "id")
