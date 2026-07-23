from django.core.validators import MinValueValidator
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

# Loop guard: outcomes must never be defined over the event they themselves emit.
OUTCOME_REACHED_EVENT = "$outcome_reached"


class Outcome(TeamScopedRootMixin, UUIDModel):
    """A user-defined condition over events that, once met by a person, becomes a permanent dated fact.

    POC scope: a single monotone atom — "person performed `target_event` at least `threshold` times".
    The full criteria grammar (paths, M-of-N, sum/distinct aggregations, windows, group-level
    subjects) is deliberately deferred.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    name = models.CharField(max_length=400, help_text="Human-readable name of the outcome.")
    description = models.TextField(
        blank=True, default="", help_text="What reaching this outcome means for the business."
    )
    target_event = models.CharField(
        max_length=400, help_text="Name of the event the person must perform to reach the outcome."
    )
    threshold = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Minimum number of times the person must perform the target event.",
    )
    last_calculated_at = models.DateTimeField(
        null=True, blank=True, help_text="When the batch evaluator last ran for this outcome."
    )

    class Meta:
        db_table = "posthog_outcome"

    def __str__(self) -> str:
        return self.name


class OutcomeLatch(TeamScopedRootMixin, UUIDModel):
    """The permanent fact that a person reached an outcome.

    One row per (outcome, person); first satisfaction latches and never un-reaches.
    Rows are only ever inserted — `reached_at` is immutable once written, and the unique
    constraint is what makes `$outcome_reached` emission effectively-once.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    outcome = models.ForeignKey(Outcome, on_delete=models.CASCADE, related_name="latches")
    person_id = models.UUIDField(help_text="UUID of the person who reached the outcome.")
    distinct_id = models.CharField(
        max_length=400, help_text="A distinct ID of the person, used for display and event emission."
    )
    reached_at = models.DateTimeField(
        help_text="Timestamp of the threshold-crossing event — a function of the event set alone."
    )
    event_count = models.PositiveIntegerField(
        help_text="How many times the person had performed the target event when evaluated."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_outcome_latch"
        constraints = [
            models.UniqueConstraint(fields=["outcome", "person_id"], name="unique_outcome_person_latch"),
        ]

    def __str__(self) -> str:
        return f"{self.person_id} reached {self.outcome_id} at {self.reached_at}"
