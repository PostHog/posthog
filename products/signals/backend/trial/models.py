from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class SignalTrialGrant(TeamScopedRootMixin, UUIDModel):
    # Plain IDs retain the lifetime claim after project or organization deletion.
    team_id = models.BigIntegerField(unique=True)
    # Keep the issuing organization's lifetime count unchanged when a project moves.
    organization_id = models.UUIDField(db_index=True)
    policy_version = models.PositiveSmallIntegerField(default=1)
    allowance_microusd = models.PositiveBigIntegerField(default=10_000_000)
    report_limit = models.PositiveSmallIntegerField(default=5)
    scout_limit = models.PositiveSmallIntegerField(default=3)
    claimed_at = models.DateTimeField(auto_now_add=True)
    claimed_by_id = models.BigIntegerField()
    exhausted_at = models.DateTimeField(null=True)
    exhaustion_reason = models.CharField(max_length=32, blank=True)
    settled_microusd = models.PositiveBigIntegerField(default=0)
    incomplete_sources = models.PositiveIntegerField(default=0)
    incomplete_since = models.DateTimeField(null=True)


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
    attempt_run_ids = ArrayField(models.UUIDField(), default=list)

    class Meta:
        indexes = [
            models.Index(
                fields=["id"],
                condition=models.Q(status="reserved", active_attempts__gt=0, attempt_run_ids__len__gt=0),
                name="signals_trial_report_pending",
            )
        ]
        constraints = [
            models.UniqueConstraint(fields=["team_id", "report_id"], name="signals_trial_report_identity"),
        ]
