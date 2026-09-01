from typing import Any, ClassVar

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.scoping.manager import TeamScopedManager, TeamScopedQuerySet
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class PulseModel(TeamScopedRootMixin, UUIDModel):
    all_teams = models.Manager()

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        default_manager_name = "all_teams"


class ImmutableOutcomeObservationQuerySet(TeamScopedQuerySet["OutcomeObservation"]):
    def unscoped(self) -> "ImmutableOutcomeObservationQuerySet":
        return ImmutableOutcomeObservationQuerySet(self.model, using=self._db)  # type: ignore[attr-defined]

    def update(self, **kwargs: Any) -> int:
        raise OutcomeObservation.ImmutableError("Outcome observations cannot be updated")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise OutcomeObservation.ImmutableError("Outcome observations cannot be deleted")


class ImmutableOutcomeObservationScopedManager(TeamScopedManager["OutcomeObservation"]):
    use_in_migrations = True
    _queryset_class: type[TeamScopedQuerySet["OutcomeObservation"]] = ImmutableOutcomeObservationQuerySet  # type: ignore[assignment]


class ImmutableOutcomeObservationAllTeamsManager(models.Manager["OutcomeObservation"]):
    use_in_migrations = True

    def get_queryset(self) -> ImmutableOutcomeObservationQuerySet:
        return ImmutableOutcomeObservationQuerySet(self.model, using=self._db)


class ProactiveSubscriptionConfig(PulseModel):
    subscription_id = models.IntegerField()
    enabled = models.BooleanField(default=False, db_default=False)
    public_research_enabled = models.BooleanField(default=True, db_default=True)
    repository = models.CharField(max_length=255, null=True, blank=True)
    create_draft_pr = models.BooleanField(default=False, db_default=False)
    repository_grant = models.ForeignKey(
        "RepositoryGrant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    public_research_subject = models.ForeignKey(
        "PublicResearchSubject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta(PulseModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["team", "subscription_id"],
                name="sub_pulse_config_team_subscription_unique",
            )
        ]


class PublicResearchSubject(PulseModel):
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=1000, blank=True, default="")
    canonical_domain = models.CharField(max_length=255)
    allowed_result_domains = models.JSONField(default=list, db_default=models.Value("[]"))
    query_templates = models.JSONField(default=list, db_default=models.Value("[]"))
    eligible = models.BooleanField(default=True, db_default=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by_id = models.IntegerField(null=True, blank=True)
    created_by_id = models.IntegerField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)


class RepositoryGrant(PulseModel):
    config = models.ForeignKey(ProactiveSubscriptionConfig, on_delete=models.CASCADE, related_name="+")
    authorizer_id = models.IntegerField()
    automation_owner_id = models.IntegerField()
    integration_id = models.IntegerField()
    repository_installation_id = models.CharField(max_length=255)
    repository = models.CharField(max_length=255)
    capabilities = models.JSONField(default=dict, db_default=models.Value("{}"))
    grant_version = models.PositiveIntegerField(default=1, db_default=1)
    active = models.BooleanField(default=True, db_default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class PulseRun(PulseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ANALYZING = "analyzing", "Analyzing"
        RESERVING = "reserving", "Reserving"
        EXECUTING = "executing", "Executing"
        COMPLETED = "completed", "Completed"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        SKIPPED = "skipped", "Skipped"

    subscription_id = models.IntegerField()
    delivery_id = models.UUIDField()
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING, db_default=Status.PENDING)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    wall_clock_deadline_at = models.DateTimeField(null=True, blank=True)
    config_snapshot = models.JSONField(default=dict, db_default=models.Value("{}"))
    report_snapshot_ref = models.CharField(max_length=512)
    task_id = models.UUIDField(null=True, blank=True)
    analysis_task_run_id = models.UUIDField(null=True, blank=True)
    execution_task_run_id = models.UUIDField(null=True, blank=True)
    failure_code = models.CharField(max_length=128, null=True, blank=True)
    skip_reason = models.CharField(max_length=128, null=True, blank=True)
    cancellation_requested_at = models.DateTimeField(null=True, blank=True)
    finalization_deadline_at = models.DateTimeField(null=True, blank=True)
    metrics = models.JSONField(default=dict, db_default=models.Value("{}"))

    class Meta(PulseModel.Meta):
        indexes = [
            models.Index(
                fields=["updated_at"],
                condition=models.Q(status__in=["pending", "analyzing", "reserving", "executing"]),
                name="sub_pulse_run_active_idx",
            ),
            models.Index(
                fields=["created_at"],
                condition=~models.Q(status="skipped"),
                name="sub_pulse_run_daily_idx",
            ),
            models.Index(
                fields=["team", "subscription_id", "-created_at"],
                name="sub_pulse_run_history_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "delivery_id"],
                name="sub_pulse_run_team_delivery_unique",
            ),
            models.UniqueConstraint(
                fields=["team", "subscription_id"],
                condition=models.Q(status__in=["pending", "analyzing", "reserving", "executing"]),
                name="sub_pulse_run_one_active_subscription",
            ),
        ]


class Opportunity(PulseModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        DISMISSED = "dismissed", "Dismissed"
        RESOLVED = "resolved", "Resolved"

    stable_key = models.CharField(max_length=512)
    title = models.CharField(max_length=400)
    summary = models.TextField(max_length=4000)
    status = models.CharField(max_length=16, choices=Status, default=Status.OPEN, db_default=Status.OPEN)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta(PulseModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["team", "stable_key"], name="sub_pulse_opportunity_team_key_unique")
        ]


class ActionProposal(PulseModel):
    class Kind(models.TextChoices):
        DRAFT_PR = "draft_pr", "Draft pull request"
        EXPERIMENT_DRAFT = "experiment_draft", "Experiment draft"
        RECOMMENDATION = "recommendation", "Recommendation"
        COMBINED = "combined", "Draft pull request and experiment"

    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="+")
    stable_action_key = models.CharField(max_length=512)
    kind = models.CharField(max_length=32, choices=Kind)
    normalized_target = models.JSONField(default=dict, db_default=models.Value("{}"))
    status = models.CharField(max_length=64, null=True, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta(PulseModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["team", "opportunity", "stable_action_key", "kind"],
                name="sub_pulse_proposal_identity_unique",
            )
        ]


class EvidenceSet(PulseModel):
    run = models.ForeignKey(PulseRun, on_delete=models.CASCADE, related_name="+")
    content_hash = models.CharField(max_length=64)
    item_refs = models.JSONField(default=list, db_default=models.Value("[]"))


class EvidenceToolCall(PulseModel):
    run = models.ForeignKey(PulseRun, on_delete=models.CASCADE, related_name="+")
    tool_call_id = models.CharField(max_length=255)
    tool_name = models.CharField(max_length=255)
    tool_schema_version = models.CharField(max_length=128)
    normalized_arguments_ref = models.CharField(max_length=512)
    normalized_result_ref = models.CharField(max_length=512)
    actor_id = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    result_truncated = models.BooleanField(default=False, db_default=False)
    error_class = models.CharField(max_length=255, null=True, blank=True)
    raw_arguments_ref = models.CharField(max_length=512, null=True, blank=True)
    raw_result_ref = models.CharField(max_length=512, null=True, blank=True)
    raw_expires_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)

    class Meta(PulseModel.Meta):
        indexes = [
            models.Index(
                fields=["raw_expires_at", "id"],
                condition=models.Q(purged_at__isnull=True, raw_expires_at__isnull=False),
                name="sub_pulse_ev_expiry_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(fields=["run", "tool_call_id"], name="sub_pulse_tool_call_run_id_unique")
        ]


class EvidenceRawBody(PulseModel):
    """Encrypted, short-lived raw MCP payloads kept separately from durable provenance."""

    tool_call = models.OneToOneField(EvidenceToolCall, on_delete=models.CASCADE, related_name="raw_body")
    encrypted_arguments = EncryptedTextField(null=True, blank=True)
    encrypted_result = EncryptedTextField(null=True, blank=True)


class RunAction(PulseModel):
    class Kind(models.TextChoices):
        DRAFT_PR = "draft_pr", "Draft pull request"
        EXPERIMENT_DRAFT = "experiment_draft", "Experiment draft"
        RECOMMENDATION = "recommendation", "Recommendation"
        COMBINED = "combined", "Draft pull request and experiment"

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        SELECTED = "selected", "Selected"
        EXECUTING = "executing", "Executing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    class MetricUnit(models.TextChoices):
        COUNT = "count", "Count"
        RATIO = "ratio", "Ratio"
        PERCENT = "percent", "Percent"
        CURRENCY = "currency", "Currency"
        DURATION = "duration", "Duration"
        OTHER = "other", "Other"

    class MetricDirection(models.TextChoices):
        INCREASE = "increase", "Increase"
        DECREASE = "decrease", "Decrease"
        MAINTAIN = "maintain", "Maintain"

    class ExpectedChangeType(models.TextChoices):
        ABSOLUTE = "absolute", "Absolute"
        RELATIVE_PERCENT = "relative_percent", "Relative percent"

    class ReadoutAfterDays(models.IntegerChoices):
        THREE = 3, "3 days"
        SEVEN = 7, "7 days"
        FOURTEEN = 14, "14 days"
        TWENTY_EIGHT = 28, "28 days"

    run = models.ForeignKey(PulseRun, on_delete=models.CASCADE, related_name="+")
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="+")
    proposal = models.ForeignKey(ActionProposal, on_delete=models.CASCADE, related_name="+")
    evidence_set = models.ForeignKey(EvidenceSet, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    action_key = models.CharField(max_length=512)
    kind = models.CharField(max_length=32, choices=Kind)
    title = models.CharField(max_length=400)
    rationale = models.TextField(max_length=4000)
    expected_impact = models.TextField(max_length=2000)
    why_now = models.TextField(max_length=2000, null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    effort = models.CharField(max_length=64, blank=True, default="")
    metric_name = models.CharField(max_length=255, null=True, blank=True)
    metric_unit = models.CharField(max_length=16, choices=MetricUnit, null=True, blank=True)
    metric_direction = models.CharField(max_length=16, choices=MetricDirection, null=True, blank=True)
    expected_change_type = models.CharField(max_length=32, choices=ExpectedChangeType, null=True, blank=True)
    expected_change_lower = models.DecimalField(max_digits=30, decimal_places=10, null=True, blank=True)
    expected_change_upper = models.DecimalField(max_digits=30, decimal_places=10, null=True, blank=True)
    readout_after_days = models.PositiveSmallIntegerField(choices=ReadoutAfterDays, null=True, blank=True)
    rank = models.PositiveSmallIntegerField()
    implementation_selected = models.BooleanField(default=False, db_default=False)
    acted_on = models.BooleanField(default=False, db_default=False)
    acted_on_at = models.DateTimeField(null=True, blank=True)
    acted_on_by_id = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.PROPOSED, db_default=Status.PROPOSED)

    class Meta(PulseModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["run", "action_key"], name="sub_pulse_run_action_key_unique"),
            models.UniqueConstraint(
                fields=["run"],
                condition=models.Q(implementation_selected=True),
                name="sub_pulse_run_one_selected_action",
            ),
            models.CheckConstraint(
                condition=models.Q(readout_after_days__isnull=True)
                | models.Q(
                    readout_after_days__in=[
                        3,
                        7,
                        14,
                        28,
                    ]
                ),
                name="sub_pulse_action_readout_after_days_valid",
            ),
        ]


class OutcomePlan(PulseModel):
    class AdoptionStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        ADOPTED = "adopted", "Adopted"
        DISMISSED = "dismissed", "Dismissed"
        ABANDONED = "abandoned", "Abandoned"

    class AdoptionSource(models.TextChoices):
        MANUAL = "manual", "Manual"
        PULL_REQUEST_MERGED = "pull_request_merged", "Pull request merged"
        EXPERIMENT_LAUNCHED = "experiment_launched", "Experiment launched"

    class ReadoutStatus(models.TextChoices):
        WAITING = "waiting", "Waiting"
        SCHEDULED = "scheduled", "Scheduled"
        DUE = "due", "Due"
        MEASURING = "measuring", "Measuring"
        MEASURED = "measured", "Measured"
        INCONCLUSIVE = "inconclusive", "Inconclusive"
        CANCELLED = "cancelled", "Cancelled"

    subscription_id = models.IntegerField()
    proposal = models.ForeignKey(ActionProposal, on_delete=models.RESTRICT, related_name="+")
    source_action = models.ForeignKey(RunAction, on_delete=models.RESTRICT, related_name="+")
    measurement_spec = models.JSONField(default=dict, db_default=models.Value("{}"))
    baseline_value = models.DecimalField(max_digits=30, decimal_places=10)
    baseline_from = models.DateTimeField()
    baseline_to = models.DateTimeField()
    adoption_status = models.CharField(
        max_length=16,
        choices=AdoptionStatus,
        default=AdoptionStatus.PENDING,
        db_default=AdoptionStatus.PENDING,
    )
    adoption_source = models.CharField(max_length=32, choices=AdoptionSource, null=True, blank=True)
    adopted_at = models.DateTimeField(null=True, blank=True)
    decided_by_id = models.IntegerField(null=True, blank=True)
    readout_status = models.CharField(
        max_length=16,
        choices=ReadoutStatus,
        default=ReadoutStatus.WAITING,
        db_default=ReadoutStatus.WAITING,
    )
    next_readout_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0, db_default=0)
    claimed_by_run = models.ForeignKey(PulseRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    claimed_at = models.DateTimeField(null=True, blank=True)
    last_failure_code = models.CharField(max_length=128, null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta(PulseModel.Meta):
        indexes = [
            models.Index(
                fields=["team", "subscription_id", "readout_status", "next_readout_at"],
                name="sub_pulse_outcome_due_idx",
            ),
            models.Index(fields=["team", "adoption_status", "updated_at"], name="sub_pulse_outcome_adoption_idx"),
            models.Index(fields=["team", "claimed_at"], name="sub_pulse_outcome_claim_idx"),
            models.Index(
                fields=["next_readout_at"],
                condition=models.Q(readout_status="scheduled"),
                name="sub_pulse_out_sched_idx",
            ),
            models.Index(
                fields=["claimed_at"],
                condition=models.Q(readout_status="measuring"),
                name="sub_pulse_out_measure_idx",
            ),
            models.Index(
                fields=["updated_at", "id"],
                condition=models.Q(adoption_status="pending", readout_status="waiting"),
                name="sub_pulse_out_pending_idx",
            ),
            models.Index(
                fields=["team", "subscription_id", "-updated_at", "-created_at"],
                name="sub_pulse_out_memory_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["proposal"],
                condition=models.Q(
                    adoption_status__in=["pending", "adopted"],
                    readout_status__in=[
                        "waiting",
                        "scheduled",
                        "due",
                        "measuring",
                    ],
                ),
                name="sub_pulse_outcome_active_proposal_unique",
            )
        ]


class OutcomeObservation(PulseModel):
    class ImmutableError(RuntimeError):
        pass

    class Status(models.TextChoices):
        MEASURED = "measured", "Measured"
        INCONCLUSIVE = "inconclusive", "Inconclusive"
        FAILED = "failed", "Failed"

    class Verdict(models.TextChoices):
        IMPROVED = "improved", "Improved"
        FLAT = "flat", "Flat"
        REGRESSED = "regressed", "Regressed"
        INCONCLUSIVE = "inconclusive", "Inconclusive"

    objects: ClassVar[ImmutableOutcomeObservationScopedManager] = ImmutableOutcomeObservationScopedManager()  # type: ignore[assignment]
    all_teams: ClassVar[ImmutableOutcomeObservationAllTeamsManager] = ImmutableOutcomeObservationAllTeamsManager()

    plan = models.ForeignKey(OutcomePlan, on_delete=models.RESTRICT, related_name="+")
    run = models.ForeignKey(PulseRun, on_delete=models.RESTRICT, related_name="+")
    attempt_number = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=16, choices=Status)
    observed_value = models.DecimalField(max_digits=30, decimal_places=10, null=True, blank=True)
    observed_from = models.DateTimeField(null=True, blank=True)
    observed_to = models.DateTimeField(null=True, blank=True)
    absolute_delta = models.DecimalField(max_digits=30, decimal_places=10, null=True, blank=True)
    relative_delta = models.DecimalField(max_digits=30, decimal_places=10, null=True, blank=True)
    verdict = models.CharField(max_length=16, choices=Verdict)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    evidence_set = models.ForeignKey(EvidenceSet, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    failure_code = models.CharField(max_length=128, null=True, blank=True)

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise self.ImmutableError("Outcome observations cannot be updated")
        super().save(*args, **kwargs)

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise self.ImmutableError("Outcome observations cannot be deleted")

    class Meta(PulseModel.Meta):
        indexes = [models.Index(fields=["plan", "created_at"], name="sub_pulse_observation_plan_idx")]
        constraints = [
            models.UniqueConstraint(fields=["plan", "attempt_number"], name="sub_pulse_observation_plan_attempt_unique")
        ]


class Artifact(PulseModel):
    class Kind(models.TextChoices):
        DRAFT_PR = "draft_pr", "Draft pull request"
        EXPERIMENT_DRAFT = "experiment_draft", "Experiment draft"

    class Status(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        CREATING = "creating", "Creating"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"
        PUBLICATION_UNKNOWN = "publication_unknown", "Publication unknown"

    class ExternalState(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"
        MERGED = "merged", "Merged"
        PUBLICATION_UNKNOWN = "publication_unknown", "Publication unknown"

    run = models.ForeignKey(PulseRun, on_delete=models.CASCADE, related_name="+")
    action = models.ForeignKey(RunAction, on_delete=models.CASCADE, related_name="+")
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="+")
    proposal = models.ForeignKey(ActionProposal, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=32, choices=Kind)
    phase = models.CharField(max_length=64, blank=True, default="")
    idempotency_key = models.CharField(max_length=512)
    external_id = models.CharField(max_length=255, null=True, blank=True)
    external_url = models.URLField(max_length=2000, null=True, blank=True)
    task_id = models.UUIDField(null=True, blank=True)
    execution_task_run_id = models.UUIDField(null=True, blank=True)
    publication_lease_id = models.UUIDField(null=True, blank=True)
    experiment_id = models.IntegerField(null=True, blank=True)
    external_state = models.CharField(max_length=32, choices=ExternalState, null=True, blank=True)
    active_claim = models.BooleanField(default=False, db_default=False)
    metadata = models.JSONField(default=dict, db_default=models.Value("{}"))
    failure_code = models.CharField(max_length=128, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=Status, default=Status.RESERVED, db_default=Status.RESERVED)

    class Meta(PulseModel.Meta):
        indexes = [
            models.Index(
                fields=["updated_at"],
                condition=models.Q(status="publication_unknown", kind="draft_pr"),
                name="sub_pulse_art_pub_unknown_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(fields=["run", "kind"], name="sub_pulse_artifact_run_kind_unique"),
            models.UniqueConstraint(fields=["proposal", "kind"], name="sub_pulse_artifact_proposal_kind_unique"),
            models.UniqueConstraint(
                fields=["team", "kind", "idempotency_key"],
                name="sub_pulse_artifact_idempotency_unique",
            ),
            models.UniqueConstraint(
                fields=["opportunity"],
                condition=models.Q(kind="draft_pr", active_claim=True),
                name="sub_pulse_artifact_active_pr_claim",
            ),
        ]


class DeliveryLedger(PulseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        ACCEPTED = "accepted", "Accepted"
        DELIVERY_UNKNOWN = "delivery_unknown", "Delivery unknown"
        FAILED = "failed", "Failed"

    run = models.ForeignKey(PulseRun, on_delete=models.CASCADE, related_name="+")
    destination = models.CharField(max_length=255)
    logical_key = models.CharField(max_length=512)
    status = models.CharField(max_length=32, choices=Status, default=Status.PENDING, db_default=Status.PENDING)
    rendered_content_ref = models.CharField(max_length=512, null=True, blank=True)
    rendered_content_hash = models.CharField(max_length=64, null=True, blank=True)
    provider_idempotency_key = models.CharField(max_length=512)
    attempt_count = models.PositiveIntegerField(default=0, db_default=0)
    accepted_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=128, null=True, blank=True)

    class Meta(PulseModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["run", "destination"], name="sub_pulse_ledger_run_destination_unique"),
            models.UniqueConstraint(fields=["team", "logical_key"], name="sub_pulse_ledger_team_key_unique"),
        ]
