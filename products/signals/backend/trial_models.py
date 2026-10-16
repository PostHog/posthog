from django.db import models
from django.db.models.functions import Coalesce

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class SignalTrialOrganization(models.Model):
    # Allocation/history rows deliberately outlive project deletion.
    organization_id = models.UUIDField(primary_key=True)
    grants_claimed = models.PositiveSmallIntegerField(default=0)
    flag_enabled = models.BooleanField(null=True)
    flag_checked_at = models.DateTimeField(null=True)
    billing_migrated_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(grants_claimed__lte=3), name="signals_trial_org_grants_max"),
        ]


class SignalTrialGrant(TeamScopedRootMixin, UUIDModel):
    team_id = models.BigIntegerField(unique=True)
    organization = models.ForeignKey(SignalTrialOrganization, on_delete=models.PROTECT)
    policy_version = models.PositiveSmallIntegerField(default=1)
    allowance_microusd = models.PositiveBigIntegerField(default=10_000_000)
    report_limit = models.PositiveSmallIntegerField(default=5)
    scout_limit = models.PositiveSmallIntegerField(default=3)
    claimed_at = models.DateTimeField(auto_now_add=True)
    claimed_by_id = models.BigIntegerField()
    exhausted_at = models.DateTimeField(null=True)
    exhaustion_reason = models.CharField(max_length=32, blank=True)
    settled_microusd = models.PositiveBigIntegerField(default=0)
    reserved_microusd = models.PositiveBigIntegerField(default=0)
    overrun_microusd = models.PositiveBigIntegerField(default=0)


class SignalTrialOperation(TeamScopedRootMixin, UUIDModel):
    class Funding(models.TextChoices):
        TRIAL = "trial", "Trial"
        PAID = "paid", "Paid"
        EXISTING = "existing", "Existing"

    class Stage(models.TextChoices):
        SCOUT = "scout", "Scout"
        SHORT = "short", "Short stage"
        RESEARCH = "research", "Research"
        REPORT_PASS = "report_pass", "Report pass"
        REPO_SELECTION = "repo_selection", "Repository selection"
        GENERATION = "generation", "Supporting generation"
        IMPLEMENTATION = "implementation", "Implementation"

    team_id = models.BigIntegerField(db_index=True)
    environment_id = models.BigIntegerField()
    organization_id = models.UUIDField()
    operation_key = models.CharField(max_length=255)
    grant = models.ForeignKey(SignalTrialGrant, null=True, on_delete=models.PROTECT)
    funding = models.CharField(max_length=16, choices=Funding)
    policy_version = models.PositiveSmallIntegerField(default=1)
    stage = models.CharField(max_length=32, choices=Stage)
    report_id = models.UUIDField(null=True)
    report_pass_id = models.UUIDField(null=True)
    task_run_id = models.UUIDField(null=True, unique=True)
    model = models.CharField(max_length=255, blank=True)
    runtime = models.CharField(max_length=32, blank=True)
    estimated_microusd = models.PositiveBigIntegerField(default=0)
    settled_microusd = models.PositiveBigIntegerField(default=0)
    reserved_microusd = models.PositiveBigIntegerField(default=0)
    accounting_complete = models.BooleanField(default=False)
    admitted_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    cancel_requested_at = models.DateTimeField(null=True)
    cancelled_at = models.DateTimeField(null=True)
    gateway_mint_attempts = models.PositiveIntegerField(default=0)
    last_reconciled_at = models.DateTimeField(null=True)
    next_reconcile_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [
            models.Index(
                Coalesce("next_reconcile_at", "admitted_at"),
                "admitted_at",
                condition=models.Q(funding="trial"),
                name="signals_trial_reconcile_due",
            ),
        ]
        constraints = [
            models.UniqueConstraint(fields=["team_id", "operation_key"], name="signals_trial_operation_identity"),
        ]


class SignalTrialReportReservation(TeamScopedRootMixin, UUIDModel):
    class Status(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        CONSUMED = "consumed", "Consumed"
        RELEASED = "released", "Released"

    team_id = models.BigIntegerField(db_index=True)
    grant = models.ForeignKey(SignalTrialGrant, on_delete=models.PROTECT)
    report_id = models.UUIDField()
    status = models.CharField(max_length=16, choices=Status, default=Status.RESERVED)
    created_at = models.DateTimeField(auto_now_add=True)
    consumed_at = models.DateTimeField(null=True)
    active_attempts = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team_id", "report_id"], name="signals_trial_report_identity"),
        ]


class SignalTrialCostSource(TeamScopedRootMixin, UUIDModel):
    team_id = models.BigIntegerField(db_index=True)
    operation = models.ForeignKey(SignalTrialOperation, on_delete=models.PROTECT)
    source_id = models.CharField(max_length=255)
    is_task = models.BooleanField()
    token_cost_microusd = models.PositiveBigIntegerField(null=True)
    compute_cost_microusd = models.PositiveBigIntegerField(null=True)
    complete = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team_id", "source_id", "is_task"], name="signals_trial_cost_identity"),
        ]
