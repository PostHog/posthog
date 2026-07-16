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
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.replay_vision.backend.api.delivery import archive_delivery, provision_delivery
from products.replay_vision.backend.feature_flag import (
    ReplayVisionActionsEnabledPermission,
    ReplayVisionEnabledPermission,
)
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.models.vision_action import (
    ActionMode,
    AlertDirection,
    AlertFrequency,
    AlertMetric,
    TriggerType,
    VisionAction,
    VisionActionRun,
    VisionActionRunStatus,
)
from products.replay_vision.backend.rrule import validate_rrule, validate_timezone
from products.replay_vision.backend.scanner_access import readable_scanner_ids
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


class AlertConfigSerializer(serializers.Serializer):
    """The alert condition for mode='alert', applied after `selection` targeting. 'every_match'
    notifies about each new match since the previous check; 'on_breach' compares a metric to a
    threshold over a rolling window and notifies on the transition into breach."""

    frequency = serializers.ChoiceField(
        choices=AlertFrequency.choices,
        required=False,
        default=AlertFrequency.ON_BREACH,
        help_text=(
            "'every_match' notifies about every new matching observation (batched per check); "
            "'on_breach' notifies once when the threshold condition starts holding. Defaults to 'on_breach'."
        ),
    )
    metric = serializers.ChoiceField(
        choices=AlertMetric.choices,
        required=False,
        default=AlertMetric.COUNT,
        help_text=(
            "What to measure over the window: 'count' of targeted observations, or 'avg_score' "
            "(the mean scorer score; scorer scanners only). every_match supports 'count' only."
        ),
    )
    threshold = serializers.FloatField(
        required=False,
        help_text=(
            "The alert fires when the metric is at or above ('above') or at or below ('below') this "
            "value, per 'direction'. Required for on_breach; ignored for every_match."
        ),
    )
    direction = serializers.ChoiceField(
        choices=AlertDirection.choices,
        required=False,
        default=AlertDirection.ABOVE,
        help_text=(
            "Which side of the threshold breaches: 'above' fires when the metric is at or above it, "
            "'below' when at or below (e.g. an average score dropping under a floor). Both inclusive. "
            "Defaults to 'above'; ignored for every_match."
        ),
    )
    window_days = serializers.ChoiceField(
        choices=[(d, f"{d} day{'s' if d != 1 else ''}") for d in (1, 3, 7, 14, 30)],
        required=False,
        help_text=(
            "Rolling lookback window for on_breach conditions, ending at each check. Defaults to 1 day. "
            "every_match ignores it (each check covers what's new since the previous one)."
        ),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        frequency = attrs.get("frequency", AlertFrequency.ON_BREACH)
        if frequency == AlertFrequency.EVERY_MATCH:
            if attrs.get("metric", AlertMetric.COUNT) == AlertMetric.AVG_SCORE:
                raise serializers.ValidationError(
                    {"metric": "every_match alerts count new matches; avg_score requires on_breach."}
                )
        else:
            if attrs.get("threshold") is None:
                raise serializers.ValidationError({"threshold": "on_breach alerts require a threshold."})
        return attrs

    def to_representation(self, instance: dict[str, Any]) -> dict[str, Any]:
        # Non-alert actions store the {} default; represent it as-is rather than KeyErroring on the
        # required fields. Writes still validate the full shape whenever alert_config is provided.
        if not instance:
            return {}
        return cast(dict[str, Any], super().to_representation(instance))


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


# Alerts ride the scanner's sweep, so each enabled alert adds evaluation work to every sweep tick —
# cap the fan-out one scanner can accumulate.
MAX_ENABLED_ALERTS_PER_SCANNER = 10


class VisionActionSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    """A Replay Vision action: a scheduled "and then…" automation over a scanner's observations."""

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
    is_scanner_digest = serializers.BooleanField(
        required=False,
        help_text=(
            "Marks this action as the scanner's built-in daily digest, the one summary surfaced on the "
            "scanner overview. At most one digest per scanner."
        ),
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
    alert_config = AlertConfigSerializer(
        required=False,
        help_text="Alert condition; required when mode is 'alert', ignored otherwise.",
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
            "is_scanner_digest",
            "trigger_type",
            "mode",
            "trigger_config",
            "selection",
            "synthesis_config",
            "alert_config",
            "delivery_config",
            "next_run_at",
            "last_run_at",
            "hog_flow_id",
            "created_at",
            "created_by",
            "updated_at",
            "user_access_level",
        ]
        read_only_fields = [
            "id",
            "next_run_at",
            "last_run_at",
            "hog_flow_id",
            "created_at",
            "created_by",
            "updated_at",
            "user_access_level",
        ]

    def validate_trigger_type(self, value: str) -> str:
        if value == TriggerType.THRESHOLD:
            raise serializers.ValidationError("Threshold triggers are not supported yet. Use 'schedule'.")
        return value

    def validate_mode(self, value: str) -> str:
        if value == ActionMode.PER_OBSERVATION:
            raise serializers.ValidationError(
                "Per-observation mode is not supported yet. Use 'group_summary' or 'alert'."
            )
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
        self._validate_unique_digest(attrs)
        self._validate_alert(attrs)
        self._validate_scanner_access(attrs)
        return attrs

    def _validate_scanner_access(self, attrs: dict[str, Any]) -> None:
        # The engine reads observations as the action's CREATOR (fail-closed run-time gate in
        # scanner_access.readable_scanner_ids). Without this write-time check, an editor with less
        # scanner access than the creator could re-point a creator-privileged action at data the
        # editor can't read and receive it via the delivery channel. Only re-check when the
        # targeting actually changes, so unrelated edits (rename, disable) don't require it.
        if "scanner" not in attrs and "selection" not in attrs:
            return
        scanner = attrs.get("scanner", getattr(self.instance, "scanner", None))
        selection = attrs.get("selection", getattr(self.instance, "selection", None)) or {}
        requested = [str(s) for s in (selection.get("scanner_ids") or ([scanner.id] if scanner else []))]
        if not requested:
            return
        request = self.context.get("request")
        if request is None or not getattr(request.user, "is_authenticated", False):
            return
        team = self.context["get_team"]()
        readable = set(readable_scanner_ids(request.user, team, requested))
        if set(requested) - readable:
            raise serializers.ValidationError(
                {"scanner": "You don't have access to one or more scanners this action targets."}
            )

    def _validate_alert(self, attrs: dict[str, Any]) -> None:
        mode = attrs.get("mode", getattr(self.instance, "mode", ActionMode.GROUP_SUMMARY))
        if mode != ActionMode.ALERT:
            return
        alert_config = attrs.get("alert_config", getattr(self.instance, "alert_config", None)) or {}
        if not alert_config:
            raise serializers.ValidationError({"alert_config": "Alert actions require an alert_config."})
        if alert_config.get("metric") == AlertMetric.AVG_SCORE:
            scanner = attrs.get("scanner", getattr(self.instance, "scanner", None))
            if scanner is not None and scanner.scanner_type != ScannerType.SCORER:
                raise serializers.ValidationError(
                    {"alert_config": "The avg_score metric only applies to scorer scanners."}
                )
        self._validate_alert_cap(attrs)

    def _validate_alert_cap(self, attrs: dict[str, Any]) -> None:
        # Alerts evaluate on the scanner's sweep, so unbounded alert fan-out multiplies sweep work.
        # Cap enabled alerts per scanner; disabled ones don't cost anything and don't count.
        enabled = attrs.get("enabled", getattr(self.instance, "enabled", True))
        scanner = attrs.get("scanner", getattr(self.instance, "scanner", None))
        if not enabled or scanner is None:
            return
        team = self.context["get_team"]()
        others = VisionAction.objects.for_team(team.id).filter(scanner=scanner, mode=ActionMode.ALERT, enabled=True)
        if self.instance is not None:
            others = others.exclude(pk=self.instance.pk)
        if others.count() >= MAX_ENABLED_ALERTS_PER_SCANNER:
            raise serializers.ValidationError(
                {"mode": f"A scanner can have at most {MAX_ENABLED_ALERTS_PER_SCANNER} enabled alerts."}
            )

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

    def _validate_unique_digest(self, attrs: dict[str, Any]) -> None:
        # Surface the one-digest-per-scanner constraint as a 400 instead of letting the DB raise 500.
        if not attrs.get("is_scanner_digest"):
            return
        scanner = attrs.get("scanner") or getattr(self.instance, "scanner", None)
        if scanner is None:
            return
        team = self.context["get_team"]()
        duplicates = VisionAction.objects.for_team(team.id).filter(scanner=scanner, is_scanner_digest=True)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError({"is_scanner_digest": "This scanner already has a daily digest."})

    def create(self, validated_data: dict[str, Any]) -> VisionAction:
        team = self.context["get_team"]()
        user = cast(User, self.context["request"].user)
        try:
            # for_team()'s filter doesn't propagate into create(), so team is still passed explicitly.
            return VisionAction.objects.for_team(team.id).create(team=team, created_by=user, **validated_data)
        except IntegrityError as e:
            self._reraise_unique_violation(e)

    def update(self, instance: VisionAction, validated_data: dict[str, Any]) -> VisionAction:
        try:
            return super().update(instance, validated_data)
        except IntegrityError as e:
            self._reraise_unique_violation(e)

    @staticmethod
    def _reraise_unique_violation(error: IntegrityError) -> NoReturn:
        if "vision_action_unique_team_name" in str(error):
            raise serializers.ValidationError({"name": "An action with this name already exists in this team."})
        if "vision_action_unique_scanner_digest" in str(error):
            raise serializers.ValidationError({"is_scanner_digest": "This scanner already has a daily digest."})
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

    # Deliberately NOT an AccessControlViewSetMixin: vision_action inherits its access level
    # from replay_scanner (see RESOURCE_INHERITANCE_MAP) so the product is configured via a
    # single rule. Exposing `/{id}/access_controls` here would let an object-level grant on
    # one action bypass that shared resource-level setting.
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

    def get_object(self) -> VisionAction:
        action = super().get_object()
        # Per-scanner object-level grants are stored against `replay_scanner` + the scanner's id, not
        # `vision_action` + the action's id — the default get_object() check above (against `action`
        # itself) can only ever see the resource-level default, never a scanner-specific override. Check
        # the scanner directly too, mirroring the `retry`/`label` pattern in observations.py, so a
        # scanner-specific grant or restriction actually applies to its actions.
        self.check_object_permissions(self.request, action.scanner)
        return action

    def safely_get_queryset(self, queryset: QuerySet[VisionAction]) -> QuerySet[VisionAction]:
        queryset = queryset.filter(team_id=self.team_id).select_related("scanner", "created_by")
        if self.action == "list":
            # `vision_action` never carries its own object-level access-control rows (see the class
            # docstring), so the generic queryset filtering in TeamAndOrgViewSetMixin is a no-op for this
            # model. Filter to the caller's accessible scanners explicitly instead, mirroring the
            # `creators`/`stats` pattern in scanners.py, so a scanner-level restriction actually hides
            # that scanner's actions from the list.
            accessible_scanners = self.user_access_control.filter_queryset_by_access_level(
                ReplayScanner.objects.filter(team_id=self.team_id)
            )
            queryset = queryset.filter(scanner_id__in=accessible_scanners.values_list("id", flat=True))
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
        # The resource-level check in `has_permission` only reflects the project-wide default; object-check
        # the target scanner too so a scanner-specific restriction blocks new actions on it as well.
        self.check_object_permissions(self.request, serializer.validated_data["scanner"])
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
    "skipped_not_breached": "The alert condition wasn't met in this window.",
    "skipped_over_budget": "The team is over its AI-credit budget.",
    "not_breached": "The alert condition wasn't met in this window.",
    "still_breached": "The condition is still met; an earlier check already sent the notification.",
    # Legacy: the engine no longer skips actions with no delivery_config (digest runs are in-app only).
    # Keep both keys so historical run rows still display a readable reason rather than the raw enum.
    "no_delivery": "No delivery destination is configured for this action.",
    "no_delivery_flow": "No delivery destination is configured for this action.",
    "disabled": "The action was disabled when this run was due.",
    "not_found": "The action no longer exists.",
    "aborted_no_consent": "AI data processing isn't enabled for this organization.",
    "aborted_no_user": "The action's creator no longer has access.",
}


class RunObservationSerializer(serializers.Serializer):
    """One recording an action run included in its summary — the 'recordings included' list on the run detail view."""

    index = serializers.SerializerMethodField(
        help_text=(
            "1-based reference number of this observation in the summary, stable across deletions. The "
            "synthesized report cites observations by this number (rendered like `[3]`), so consumers use "
            "it to resolve a citation to its observation."
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

    @extend_schema_field(serializers.IntegerField())
    def get_index(self, obs: ReplayObservation) -> int:
        # Position is supplied by the parent (`get_observations`) via context, keyed by observation id — it
        # depends on the run's `observation_ids` order, which a single observation can't know on its own.
        return int(self.context["observation_index_by_id"][str(obs.id)])

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
        # then drop any deleted ones — so a deletion leaves a gap rather than renumbering the survivors. The
        # position rides to the serializer via context (keyed by id) rather than a transient attr on the model.
        ordered = []
        index_by_id: dict[str, int] = {}
        for position, i in enumerate(ids, start=1):
            obs = by_id.get(i)
            if obs is None:
                continue
            index_by_id[str(obs.id)] = position
            ordered.append(obs)
        context = {**self.context, "observation_index_by_id": index_by_id}
        return cast(list[dict[str, Any]], RunObservationSerializer(ordered, many=True, context=context).data)


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
        action = VisionAction.objects.for_team(self.team_id).select_related("scanner").filter(id=action_id).first()
        if action is None:
            raise NotFound()
        # Runs expose recording-derived summaries, so reading them inherits the action's RBAC and also
        # requires session_recording read (mirrors the observations endpoint). Per-scanner object-level
        # grants are stored against `replay_scanner` + the scanner's id, not `vision_action` + the action's
        # id, so check the scanner directly — checking `action` itself would only ever see the
        # resource-level default.
        self.check_object_permissions(self.request, action.scanner)
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading vision action runs requires session_recording read access.")
        return action

    def safely_get_queryset(self, queryset: QuerySet[VisionActionRun]) -> QuerySet[VisionActionRun]:
        action = self._action_for_url()
        return (
            queryset.filter(team_id=self.team_id, vision_action_id=action.id)
            # Alert-state bookkeeping runs exist so the engine can resolve breach transitions
            # (alerts._EVALUATED_SKIP_REASONS — literals duplicated here to keep the temporal
            # package off the API import path). They aren't user-facing outcomes: run history
            # shows actual firings, failures, and summary skips, not every quiet check.
            .exclude(
                status=VisionActionRunStatus.SKIPPED,
                error__skip_reason__in=["not_breached", "still_breached"],
            )
            .order_by("-created_at", "id")
        )
