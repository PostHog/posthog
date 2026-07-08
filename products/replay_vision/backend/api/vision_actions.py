import uuid
from typing import Any, NoReturn, cast, get_args

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.serializers import BaseSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.models.integration import Integration
from posthog.models.user import User

from products.replay_vision.backend.api.delivery import archive_delivery, provision_delivery
from products.replay_vision.backend.feature_flag import (
    ReplayVisionActionsEnabledPermission,
    ReplayVisionEnabledPermission,
)
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.models.vision_action import (
    ActionMode,
    TriggerType,
    VisionAction,
    VisionActionRun,
    VisionActionRunStatus,
)
from products.replay_vision.backend.rrule import validate_rrule, validate_timezone
from products.replay_vision.backend.temporal.scanners.monitor import MonitorVerdict

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
    """The action's targeting predicate ("run this on…") applied when gathering observations. All keys
    optional; this typed shape is the allowlist, so unknown input keys are dropped rather than persisted."""

    scanner_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Restrict to observations produced by these scanner IDs. Defaults to the bound scanner.",
    )
    verdict = serializers.ListField(
        child=serializers.ChoiceField(choices=[(v, v) for v in get_args(MonitorVerdict)]),
        required=False,
        help_text="Only run on monitor observations with one of these verdicts (yes/no/inconclusive).",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Only run on classifier observations carrying any of these tags (fixed or freeform).",
    )
    min_score = serializers.FloatField(
        required=False,
        help_text="Only run on scorer observations with a score at or above this value (inclusive).",
    )
    max_score = serializers.FloatField(
        required=False,
        help_text="Only run on scorer observations with a score at or below this value (inclusive).",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        min_score = attrs.get("min_score")
        max_score = attrs.get("max_score")
        if min_score is not None and max_score is not None and min_score > max_score:
            raise serializers.ValidationError({"min_score": "min_score cannot exceed max_score."})
        return attrs


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
        help_text="Targeting predicate: which of the scanner's observations this action runs on.",
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
    hog_flow_id = serializers.UUIDField(
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
        try:
            validate_timezone(trigger_config.get("timezone", "UTC"))
        except ValueError as e:
            raise serializers.ValidationError({"trigger_config": {"timezone": str(e)}})
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


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="scanner",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Filter to the actions belonging to one scanner.",
            )
        ]
    )
)
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
        queryset = queryset.filter(team_id=self.team_id).select_related("scanner", "created_by")
        # The per-scanner "Actions" tab scopes the list to one scanner.
        scanner_id = self.request.query_params.get("scanner")
        if scanner_id:
            try:
                uuid.UUID(scanner_id)
            except ValueError:
                # A malformed ?scanner= would otherwise raise ValueError when the UUID column builds the
                # query — uncaught by DRF, so a 500. Treat unparseable input as "matches nothing".
                return queryset.none()
            queryset = queryset.filter(scanner_id=scanner_id)
        return queryset.order_by("name", "id")

    def perform_create(self, serializer: BaseSerializer) -> None:
        # Atomic so a destination-provisioning failure rolls back the action row rather than leaving an
        # action that looks created but never delivers.
        with transaction.atomic():
            action = serializer.save()
            provision_delivery(action, request=self.request, team=self.team)

    def perform_update(self, serializer: BaseSerializer) -> None:
        instance = cast(VisionAction, serializer.instance)
        # Snapshot the destination-affecting fields BEFORE save() — DRF mutates `instance` in place, so
        # these must be read pre-save for the change comparison to be meaningful.
        old_delivery = instance.delivery_config
        old_enabled = instance.enabled
        old_name = instance.name
        # Atomic so a re-provision failure rolls the action edit back too (parity with perform_create).
        with transaction.atomic():
            action = serializer.save()
            # Re-provision only when something the destinations reflect changed: delivery targets, the
            # enabled flag, or the name (each destination is named after the action). Cadence/selection
            # edits don't touch the destinations, so they must not churn them.
            if action.delivery_config != old_delivery or action.enabled != old_enabled or action.name != old_name:
                provision_delivery(action, request=self.request, team=self.team)

    def perform_destroy(self, instance: VisionAction) -> None:
        archive_delivery(instance, team=self.team)
        super().perform_destroy(instance)


# Human-readable copy for the engine's controlled skip/abort reasons (see temporal.vision_actions —
# _validate skip reasons and SynthesisStatus). Unmapped values fall through to the raw string.
# Copy stays neutral (no "Skipped —"/"Failed —" prefix): the run's status drives the banner heading,
# so the abort reasons read correctly under the "failed" banner they actually carry.
_RUN_REASON_LABELS = {
    "skipped_empty": "No new observations in this window to summarize.",
    "skipped_over_budget": "The team is over its AI-credit budget.",
    "no_delivery": "No delivery destination is configured for this action.",
    # Alias: runs recorded before #66892 stored the old "no_delivery_flow" enum; map it to the same copy.
    "no_delivery_flow": "No delivery destination is configured for this action.",
    "disabled": "The action was disabled when this run was due.",
    "not_found": "The action no longer exists.",
    "aborted_no_consent": "AI data processing isn't enabled for this organization.",
    "aborted_no_user": "The action's creator no longer has access.",
}


class RunObservationSerializer(serializers.Serializer):
    """One recording an action run included in its summary — the 'recordings included' list on the run detail view."""

    index = serializers.IntegerField(
        read_only=True,
        help_text=(
            "1-based position of this observation in the summary, stable across deletions. The synthesized "
            "report cites observations by this number (e.g. `[obs 3]`), so consumers use it to resolve a "
            "citation to its observation."
        ),
    )
    id = serializers.UUIDField(
        read_only=True,
        help_text="Observation id; links to the observation detail view.",
    )
    session_id = serializers.CharField(
        read_only=True,
        help_text="Session recording id this observation was made on.",
    )
    recording_subject_email = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Email of the person in the recorded session, captured at scan time; null if unidentified.",
    )
    title = serializers.SerializerMethodField(
        help_text="Short title from the observation's summary; null if the observation had none.",
    )
    created_at = serializers.DateTimeField(
        read_only=True,
        help_text="When the observation was produced.",
    )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_title(self, obs: ReplayObservation) -> str | None:
        result = obs.scanner_result if isinstance(obs.scanner_result, dict) else {}
        output = result.get("model_output")
        if not isinstance(output, dict):
            return None
        title = output.get("title")
        return title if isinstance(title, str) and title.strip() else None


class VisionActionRunListSerializer(serializers.ModelSerializer):
    """Lightweight run row for the per-action run list (no report body — that's fetched on retrieve)."""

    status = serializers.ChoiceField(
        choices=VisionActionRunStatus.choices,
        read_only=True,
        help_text="Run outcome: running, completed, failed, or skipped.",
    )
    scheduled_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="The scheduled fire time this run was claimed for.",
    )
    observation_count = serializers.IntegerField(
        read_only=True,
        help_text="Number of observations that fed this run's summary.",
    )
    error_reason = serializers.SerializerMethodField(
        help_text="Short human-readable reason a run skipped or failed; null on success.",
    )

    class Meta:
        model = VisionActionRun
        fields = [
            "id",
            "status",
            "scheduled_at",
            "observation_count",
            "error_reason",
            "created_at",
            "updated_at",
        ]

    # allow_null so the generated TS/MCP type is `string | null` — get_error_reason returns null for
    # successful runs, and a non-null hint would crash consumers that dereference it.
    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_error_reason(self, run: VisionActionRun) -> str | None:
        error = run.error if isinstance(run.error, dict) else {}
        # Surface only the engine's controlled skip/abort reasons, mapped to human copy. Failed runs also
        # stamp error["message"] with raw exception text (str(e)[:500]) — don't echo that to API consumers.
        for key in ("skip_reason", "aborted"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                return _RUN_REASON_LABELS.get(value, value)
        if run.status == VisionActionRunStatus.FAILED:
            return "This run failed while generating the summary."
        return None


class VisionActionRunSerializer(VisionActionRunListSerializer):
    """Full run detail: the list fields plus the synthesized report and the recordings it summarized."""

    synthesized_markdown = serializers.CharField(
        read_only=True,
        allow_blank=True,
        help_text="The synthesized group-summary report in Markdown. Empty until a run completes successfully.",
    )
    observations = serializers.SerializerMethodField(
        help_text=(
            "Recordings this run included in its summary, in summary order. Empty for runs recorded before this "
            "was tracked, and for skipped/failed runs."
        ),
    )

    class Meta(VisionActionRunListSerializer.Meta):
        fields = [*VisionActionRunListSerializer.Meta.fields, "synthesized_markdown", "observations"]

    @extend_schema_field(RunObservationSerializer(many=True))
    def get_observations(self, run: VisionActionRun) -> list[dict[str, Any]]:
        ids = run.observation_ids if isinstance(run.observation_ids, list) else []
        if not ids:
            return []
        # Scope to the run's own team (the run itself was fetched team-scoped) so a stray cross-team id
        # in the stored list can never resolve — ReplayObservation isn't fail-closed.
        by_id = {str(o.id): o for o in ReplayObservation.objects.filter(team_id=run.team_id, id__in=ids)}
        # Number by original position in `observation_ids` (what the summary's `[obs N]` markers reference),
        # then drop any deleted ones — so a deletion leaves a gap rather than renumbering the survivors.
        ordered = []
        for position, i in enumerate(ids, start=1):
            obs = by_id.get(i)
            if obs is None:
                continue
            obs.index = position
            ordered.append(obs)
        return cast(list[dict[str, Any]], RunObservationSerializer(ordered, many=True, context=self.context).data)


class VisionActionRunViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only run history for a single vision action (nested under /vision/actions/{action_id}/runs/)."""

    scope_object = "vision_action"
    # Runs surface recording-derived summaries, so reading them requires session_recording read too.
    required_scopes = ["vision_action:read", "session_recording:read"]
    permission_classes = [ReplayVisionEnabledPermission, ReplayVisionActionsEnabledPermission]
    serializer_class = VisionActionRunSerializer
    # `objects` is fail-closed; `safely_get_queryset` re-scopes to the request team.
    queryset = VisionActionRun.objects.unscoped()

    def get_serializer_class(self) -> type[BaseSerializer]:
        # The list omits the report body + observations to stay light; retrieve returns the full detail.
        return VisionActionRunListSerializer if self.action == "list" else VisionActionRunSerializer

    def _action_for_url(self) -> VisionAction:
        try:
            action_id = uuid.UUID(self.kwargs["parent_lookup_vision_action_id"])
        except (KeyError, ValueError):
            raise NotFound()
        action = VisionAction.objects.for_team(self.team_id).filter(id=action_id).first()
        if action is None:
            raise NotFound()
        # Runs expose recording-derived summaries, so reading them inherits the action's RBAC and also
        # requires session_recording read (mirrors the observations endpoint).
        self.check_object_permissions(self.request, action)
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading vision action runs requires session_recording read access.")
        return action

    def safely_get_queryset(self, queryset: QuerySet[VisionActionRun]) -> QuerySet[VisionActionRun]:
        action = self._action_for_url()
        return queryset.filter(team_id=self.team_id, vision_action_id=action.id).order_by("-created_at", "id")
