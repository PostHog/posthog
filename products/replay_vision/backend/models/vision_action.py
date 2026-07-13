from typing import Any

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.replay_vision.backend.rrule import compute_next_occurrences


def default_selection() -> dict[str, Any]:
    # Past day's observations from the bound scanner — the most common "and then" group summary.
    return {"window_days": 1}


class TriggerType(models.TextChoices):
    SCHEDULE = "schedule", "Schedule"
    THRESHOLD = "threshold", "Threshold"  # reserved for alerts; rejected at the API for now


class ActionMode(models.TextChoices):
    GROUP_SUMMARY = "group_summary", "Group summary"  # one summary synthesized from a group of observations
    PER_OBSERVATION = "per_observation", "Per observation"  # reserved; rejected at the API for now


class VisionAction(TeamScopedRootMixin, UUIDModel):
    """An "and then…" automation over a scanner's observations: gather, (optionally) synthesize, deliver.

    MVP is schedule-triggered group summaries; the trigger_type/mode enums leave room for
    threshold alerts and per-observation reactions without a schema change.
    """

    all_teams = models.Manager()  # noqa: DJ012 — escape hatch for cross-team Temporal/admin access

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="vision_actions")
    scanner = models.ForeignKey(
        "replay_vision.ReplayScanner",
        on_delete=models.CASCADE,
        related_name="vision_actions",
        help_text="Scanner whose observations this action operates on. An action runs as a child of this scanner's sweep.",
    )
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)

    trigger_type = models.CharField(
        max_length=20,
        choices=TriggerType.choices,
        default=TriggerType.SCHEDULE,
        help_text="What fires the action. MVP supports 'schedule' only.",
    )
    mode = models.CharField(
        max_length=20,
        choices=ActionMode.choices,
        default=ActionMode.GROUP_SUMMARY,
        help_text="What the action produces. MVP supports 'group_summary' only.",
    )

    next_run_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Computed next fire time for schedule triggers; the scheduler scans this.",
    )
    last_run_at = models.DateTimeField(null=True, blank=True)

    trigger_config = models.JSONField(
        default=dict,
        help_text="Trigger parameters. Schedule: {rrule, timezone}. Threshold (reserved): {metric, window, op, value}.",
    )
    selection = models.JSONField(
        default=default_selection,
        help_text=(
            "Observation filter applied at synthesis time, over the action's bound `scanner` "
            "(one action per scanner). Supported keys: scanner_ids (list[str], to override the bound "
            "scanner), verdict, tags, scores, status, window_days."
        ),
    )
    synthesis_config = models.JSONField(default=dict, help_text="Synthesis options, e.g. {prompt_guide}.")
    # How many observations may feed one group summary. When the window holds more, they're sampled
    # evenly across it (not just the newest). Not exposed in the API/UI yet — tune via Django admin.
    max_observations = models.PositiveIntegerField(
        default=100,
        validators=[MinValueValidator(1)],
        help_text="Max observations included in one group summary; sampled across the window when exceeded.",
    )
    delivery_config = models.JSONField(
        default=list,
        help_text="List of destination targets, e.g. [{type: 'slack', integration_id, channel}].",
    )

    hog_flow = models.ForeignKey(
        "workflows.HogFlow",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Delivery flow provisioned by the API; the action emits an event this flow delivers.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="vision_action_unique_team_name"),
        ]
        indexes = [
            models.Index(
                fields=["team", "next_run_at"],
                name="vision_action_due_idx",
                condition=models.Q(enabled=True),
            ),
        ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Cache the schedule key so save() can detect cadence changes. Guard against deferred-field
        # recursion the same way Subscription does (accessing a deferred field triggers a reload).
        if not ({"trigger_type", "trigger_config"} & self.get_deferred_fields()):
            self._cached_schedule_key = self._schedule_key()

    def _schedule_key(self) -> tuple[str, str] | None:
        # Both the rrule AND the timezone determine the next fire time, so a change to either must
        # trigger a recompute — keying on the rrule alone would miss a timezone-only edit.
        if self.trigger_type != TriggerType.SCHEDULE:
            return None
        cfg = self.trigger_config or {}
        rrule = cfg.get("rrule")
        if not rrule:
            return None
        return (rrule, cfg.get("timezone", "UTC"))

    def _recompute_next_run_at(self) -> None:
        key = self._schedule_key()
        if key is None:
            self.next_run_at = None
            return
        rrule, timezone_str = key
        starts_at = self.created_at or timezone.now()
        occurrences = compute_next_occurrences(
            rrule_string=rrule, starts_at=starts_at, timezone_str=timezone_str, count=1
        )
        self.next_run_at = occurrences[0] if occurrences else None

    def save(self, *args: Any, **kwargs: Any) -> None:
        # UUIDModel assigns `id` at __init__, so `not self.id` never detects a create —
        # `_state.adding` is the correct new-vs-persisted signal here.
        current_key = self._schedule_key()
        if self._state.adding or getattr(self, "_cached_schedule_key", None) != current_key:
            self._recompute_next_run_at()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = [*update_fields, "next_run_at"]
        super().save(*args, **kwargs)
        self._cached_schedule_key = current_key

    def __str__(self) -> str:
        return f"{self.name} ({self.trigger_type})"


class VisionActionRunStatus(models.TextChoices):
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class VisionActionRun(TeamScopedRootMixin, UUIDModel):
    """History of a single VisionAction execution. The full synthesized report lives here (not on
    the Temporal wire) and backs the 'view full group summary' link."""

    all_teams = models.Manager()  # noqa: DJ012 — escape hatch for cross-team Temporal/admin access

    vision_action = models.ForeignKey(VisionAction, on_delete=models.CASCADE, related_name="runs")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")

    temporal_workflow_id = models.CharField(max_length=255, null=True, blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=VisionActionRunStatus.choices, default=VisionActionRunStatus.RUNNING
    )
    synthesized_markdown = models.TextField(blank=True, default="")
    # Channel-formatted delivery payloads keyed by channel, e.g. {"slack": "...", "email": "..."} —
    # generic so new channels don't each add a column. synthesized_markdown stays the canonical report.
    output = models.JSONField(default=dict)
    observation_count = models.PositiveIntegerField(default=0)
    # UUIDs of the ReplayObservations this run's summary actually included, in summary order. Empty for
    # runs created before this was tracked (and for skipped/failed runs that summarized nothing).
    observation_ids = models.JSONField(default=list)
    error = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_manager_name = "all_teams"
        indexes = [
            models.Index(fields=["vision_action", "-created_at"], name="vision_action_run_recent_idx"),
        ]

    def __str__(self) -> str:
        return f"Run {self.id} of {self.vision_action_id} ({self.status})"
