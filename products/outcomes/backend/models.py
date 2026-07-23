from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.outcomes.backend.criteria import OUTCOME_REACHED_EVENT as OUTCOME_REACHED_EVENT


class Outcome(TeamScopedRootMixin, UUIDModel):
    """A user-defined compound condition over events that, once met by a person, becomes a permanent dated fact.

    Criteria follow the monotone grammar in `criteria.py`: paths OR'd together, atoms AND'd
    within a path (optionally M-of-N), each atom a count/sum/distinct aggregation of matching
    events compared with >= threshold. Group-level subjects and windows are deliberately
    deferred.
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
    criteria = models.JSONField(
        help_text="Monotone criteria: paths OR'd together, atoms AND'd within a path (optionally M-of-N)."
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
    evidence = models.JSONField(
        help_text="Aggregate values only: per-condition attained vs threshold and the winning path index."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_outcome_latch"
        constraints = [
            models.UniqueConstraint(fields=["outcome", "person_id"], name="unique_outcome_person_latch"),
        ]

    def __str__(self) -> str:
        return f"{self.person_id} reached {self.outcome_id} at {self.reached_at}"
