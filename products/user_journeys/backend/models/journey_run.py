"""One replay of a journey in a headless browser, and what happened at each of its steps."""

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.user_journeys.backend.facade.contracts import (
    DEFAULT_VIEWPORT_HEIGHT,
    DEFAULT_VIEWPORT_WIDTH,
    MAX_BRANCH_LENGTH,
    MAX_COMMIT_SHA_LENGTH,
    MAX_URL_LENGTH,
)
from products.user_journeys.backend.facade.enums import (
    JourneyRunStatus,
    JourneyRunStepStatus,
    JourneyRunTrigger,
    JourneyStepFailureReason,
    JourneyVisualChange,
)

# A blake3 hex digest. Screenshots are stored under their content hash, so equal images share one object.
SCREENSHOT_HASH_LENGTH = 64


class JourneyRun(TeamScopedRootMixin, UUIDModel):
    Trigger = JourneyRunTrigger
    Status = JourneyRunStatus

    # No database constraint: creating one takes a lock on `posthog_team` that queues behind
    # live writes. Django still cascades the delete in Python.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    journey = models.ForeignKey("user_journeys.Journey", on_delete=models.CASCADE, related_name="runs")
    # No database constraint, for the same reason on `posthog_user`.
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    trigger = models.CharField(max_length=16, choices=Trigger.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING.value)
    # The URL the browser opened, after `base_url` replaced its origin. Set when the run starts.
    start_url = models.CharField(max_length=MAX_URL_LENGTH, null=True, blank=True)
    # An origin that replaces the recorded one, so a journey recorded on production can run against a preview.
    base_url = models.CharField(max_length=MAX_URL_LENGTH, null=True, blank=True)
    commit_sha = models.CharField(max_length=MAX_COMMIT_SHA_LENGTH, null=True, blank=True)
    branch = models.CharField(max_length=MAX_BRANCH_LENGTH, null=True, blank=True)
    viewport_width = models.PositiveIntegerField(default=DEFAULT_VIEWPORT_WIDTH)
    viewport_height = models.PositiveIntegerField(default=DEFAULT_VIEWPORT_HEIGHT)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # Why the run could not finish its steps, for example because no browser was available.
    error = models.TextField(null=True, blank=True)
    baseline_run = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="compared_runs"
    )
    # The deploy that started this run. Null for a run a person started.
    deploy = models.ForeignKey(
        "user_journeys.JourneyDeploy", on_delete=models.SET_NULL, null=True, blank=True, related_name="runs"
    )

    class Meta:
        indexes = [
            models.Index(fields=["journey", "-created_at"], name="uj_run_journey_created_idx"),
            # Serves the baseline lookup: the newest passed run of a journey at one viewport.
            models.Index(
                fields=["journey", "viewport_width", "viewport_height", "-created_at"],
                condition=models.Q(status="passed"),
                name="uj_run_passed_baseline_idx",
            ),
        ]
        constraints = [
            # At most one run of a journey waits or runs at a time, so repeated clicks or deploys can't
            # stack up browser sessions for the same journey.
            models.UniqueConstraint(
                fields=["journey"],
                condition=models.Q(status__in=["pending", "running"]),
                name="uj_run_one_active_per_journey",
            ),
        ]


class JourneyRunStep(TeamScopedRootMixin, UUIDModel):
    Status = JourneyRunStepStatus
    FailureReason = JourneyStepFailureReason
    VisualChange = JourneyVisualChange

    # No database constraint, for the same reason as on `JourneyRun.team`.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    run = models.ForeignKey(JourneyRun, on_delete=models.CASCADE, related_name="steps")
    index = models.PositiveSmallIntegerField()
    # The `JourneyStep` contract as it was when the run started.
    step = models.JSONField()
    status = models.CharField(max_length=16, choices=Status.choices)
    failure_reason = models.CharField(max_length=48, choices=FailureReason.choices, null=True, blank=True)
    message = models.TextField(blank=True, default="")
    screenshot_hash = models.CharField(max_length=SCREENSHOT_HASH_LENGTH, null=True, blank=True)
    baseline_screenshot_hash = models.CharField(max_length=SCREENSHOT_HASH_LENGTH, null=True, blank=True)
    diff_screenshot_hash = models.CharField(max_length=SCREENSHOT_HASH_LENGTH, null=True, blank=True)
    diff_percentage = models.FloatField(null=True, blank=True)
    visual_change = models.CharField(max_length=16, choices=VisualChange.choices, null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "index"], name="uj_run_step_unique_index")]
