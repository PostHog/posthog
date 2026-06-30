"""Stampede data model.

Five tables: Partition, Enrollment, Slot, Trial, QueueEvent.

These are instance-global infra tables: Stampede is the merge queue for PostHog's own
monorepo, so rows key on `repo` ("owner/name"), not on a customer Team. They are
acknowledged as legitimately unscoped in `.github/scripts/check-idor-model-coverage.py`.
"""

from django.db import models
from django.db.models import Q

from posthog.models.utils import UUIDModel


class Strategy(models.TextChoices):
    OPTIMISTIC = "optimistic"
    SERIAL = "serial"
    SPECULATIVE = "speculative"
    BATCHED = "batched"
    AUTO = "auto"  # engine default = serial; Cowboy selects live


class PartitionMode(models.TextChoices):
    HYBRID = "hybrid"  # queue runs alongside direct merges
    EXCLUSIVE = "exclusive"  # every merge goes through the queue


class Partition(UUIDModel):
    """Identity + resolved config + runtime state.

    Predicate / strategy / config are authored in `partitions.yml` and synced into this
    table on deploy; only the runtime fields (`mode`, `frozen_at`, `frozen_by_*`) are
    mutated at runtime via the facade.
    """

    name = models.SlugField(unique=True)
    predicate = models.TextField()  # condition grammar; synced from yml
    strategy = models.CharField(max_length=16, choices=Strategy.choices, default=Strategy.SERIAL)
    speculation_depth = models.PositiveIntegerField(null=True)  # null → engine default
    max_batch_size = models.PositiveIntegerField(null=True)  # null → engine default
    ci_scope = models.JSONField(default=dict)  # affected-target selector for this partition
    precedence = models.IntegerField(default=0)  # tiebreak for the deterministic spanning route
    # runtime-mutable (not from yml):
    mode = models.CharField(max_length=16, choices=PartitionMode.choices, default=PartitionMode.HYBRID)
    frozen_at = models.DateTimeField(null=True)
    frozen_by_id = models.CharField(max_length=255, null=True)
    frozen_by_kind = models.CharField(max_length=16, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_frozen(self) -> bool:
        return self.frozen_at is not None


class EnrollmentState(models.TextChoices):
    ACTIVE = "active"  # in the queue across one or more slots
    MERGED = "merged"  # terminal: all slots green, merged to master
    EJECTED = "ejected"  # terminal for this enrollment; a re-enroll creates a new row
    DEQUEUED = "dequeued"  # terminal: removed by a human/agent


class Enrollment(UUIDModel):
    """A PR in the queue (PR-level — the thing that merges)."""

    repo = models.CharField(max_length=255)  # "owner/name"
    number = models.PositiveIntegerField()  # PR number
    head_sha = models.CharField(max_length=40)  # head being validated
    state = models.CharField(max_length=16, choices=EnrollmentState.choices, default=EnrollmentState.ACTIVE)
    approval_ref = models.CharField(max_length=255)  # approving review; re-enroll lands under it
    enrolled_by_id = models.CharField(max_length=255)
    enrolled_by_kind = models.CharField(max_length=16)  # ActorKind
    parent = models.ForeignKey(
        "self", null=True, on_delete=models.SET_NULL, related_name="children"
    )  # stack dependency edge
    eject_count = models.PositiveIntegerField(default=0)
    cycle_count = models.PositiveIntegerField(default=0)  # vs the Cowboy cycle cap
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    merged_at = models.DateTimeField(null=True)
    ejected_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            # at most one ACTIVE enrollment per PR
            models.UniqueConstraint(
                fields=["repo", "number"],
                condition=Q(state="active"),
                name="uniq_active_enrollment_per_pr",
            ),
        ]
        indexes = [models.Index(fields=["repo", "number"]), models.Index(fields=["state"])]


class SlotState(models.TextChoices):
    ENROLLED = "enrolled"  # holding a position, awaiting trial
    TRIALING = "trialing"  # a trial is running
    GREEN = "green"  # passed; waiting for sibling slots before the PR merges
    EJECTED = "ejected"  # trial failed (non-flaky)
    HELD = "held"  # blocked by an unlanded stack parent or a freeze


class Slot(UUIDModel):
    """A PR's membership + position in one partition."""

    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="slots")
    partition = models.ForeignKey(Partition, on_delete=models.PROTECT, related_name="slots")
    state = models.CharField(max_length=16, choices=SlotState.choices, default=SlotState.ENROLLED)
    enqueued_at = models.DateTimeField()  # ORDERING KEY; reset on re-enroll → back of line
    current_trial = models.ForeignKey("Trial", null=True, on_delete=models.SET_NULL, related_name="+")
    projected_base_sha = models.CharField(max_length=40, null=True)  # base of the projected state
    projected_predecessor_shas = models.JSONField(default=list)  # in-flight predecessors (speculative)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["enrollment", "partition"], name="uniq_slot_per_partition"),
        ]
        indexes = [
            # the line within a partition: WHERE partition=? AND state=? ORDER BY enqueued_at, id
            models.Index(fields=["partition", "state", "enqueued_at"]),
        ]


class TrialKind(models.TextChoices):
    SINGLE = "single"
    BATCH = "batch"


class TrialState(models.TextChoices):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    # note: freeze lets in-flight trials FINISH — there is no "cancelled-by-freeze" state.


class Trial(UUIDModel):
    """One full-suite CI attempt against a projected state (one slot, or many when batched)."""

    partition = models.ForeignKey(Partition, on_delete=models.PROTECT, related_name="trials")
    kind = models.CharField(max_length=16, choices=TrialKind.choices, default=TrialKind.SINGLE)
    slots = models.ManyToManyField(Slot, related_name="trials")  # one (single) or many (batch)
    state = models.CharField(max_length=16, choices=TrialState.choices, default=TrialState.PENDING)
    projected_base_sha = models.CharField(max_length=40)  # what the full suite ran against
    projected_head_shas = models.JSONField(default=list)  # predecessors folded into the projection
    workflow_id = models.CharField(max_length=255, null=True)  # Temporal handle
    ci_run_ref = models.CharField(max_length=255, null=True)  # link to the CI run
    failing_tests = models.JSONField(null=True)  # populated on FAILED
    flaky_retried = models.BooleanField(default=False)  # this trial was a flaky retry
    parent_trial = models.ForeignKey(
        "self", null=True, on_delete=models.SET_NULL, related_name="bisection_children"
    )  # bisection lineage
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [models.Index(fields=["partition", "state"]), models.Index(fields=["workflow_id"])]


class QueueEventType(models.TextChoices):
    ENROLLED = "enrolled"
    TRIAL_STARTED = "trial_started"
    TRIAL_FINISHED = "trial_finished"
    MERGED = "merged"
    EJECTED = "ejected"
    REQUEUED = "requeued"
    HELD = "held"
    DEQUEUED = "dequeued"
    FROZEN = "frozen"
    UNFROZEN = "unfrozen"
    CONFLICT = "conflict"
    BREAK_GLASS_USED = "break_glass_used"
    CYCLE_CAP_HIT = "cycle_cap_hit"
    SHADOW_DECISION = "shadow_decision"  # payload: {hook, would_be, taken}


class QueueEvent(UUIDModel):
    """Append-only audit/observability log. Never updated or deleted.

    The single source for `engineering_analytics` emission, the break-glass
    audit, and Cowboy's shadow-decision records.
    """

    type = models.CharField(max_length=32, choices=QueueEventType.choices)
    enrollment = models.ForeignKey(Enrollment, null=True, on_delete=models.SET_NULL, related_name="events")
    slot = models.ForeignKey(Slot, null=True, on_delete=models.SET_NULL, related_name="events")
    trial = models.ForeignKey(Trial, null=True, on_delete=models.SET_NULL, related_name="events")
    partition = models.ForeignKey(Partition, null=True, on_delete=models.SET_NULL, related_name="events")
    actor_id = models.CharField(max_length=255, null=True)
    actor_kind = models.CharField(max_length=16, null=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["type", "created_at"]), models.Index(fields=["enrollment"])]
