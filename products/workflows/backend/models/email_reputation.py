from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class EmailReputationSnapshot(TeamScopedRootMixin, UUIDModel):
    """
    Append-only daily snapshots of per-workflow and per-tenant email deliverability reputation
    (bounce/complaint rates from app_metrics2), written by the Node Temporal evaluator via raw SQL.

    Rates are volume-based, mirroring AWS SES: each snapshot covers the target's most recent sends
    up to a configured representative volume, not a fixed time window — ``emails_sent`` is that
    evaluated volume (0 for a carry-forward row written when a recently active team goes silent).

    One row per workflow (``hog_flow`` set, ``scope=WORKFLOW``) plus one aggregate row per team
    (``hog_flow`` null, ``scope=TEAM``) per evaluation run, so the table doubles as a time series
    for trend dashboards. Calculation only — enforcement (pausing bad senders) ships separately.
    """

    class Meta:
        db_table = "posthog_emailreputationsnapshot"
        constraints = [
            # One snapshot per target per run; the Node evaluator inserts ON CONFLICT DO NOTHING
            # against these so Temporal activity retries are idempotent.
            models.UniqueConstraint(
                fields=["team", "hog_flow", "evaluated_at"],
                condition=models.Q(hog_flow__isnull=False),
                name="unique_workflow_reputation_snapshot",
            ),
            models.UniqueConstraint(
                fields=["team", "evaluated_at"],
                condition=models.Q(hog_flow__isnull=True),
                name="unique_team_reputation_snapshot",
            ),
            # scope is denormalized from hog_flow nullability for readers; keep them coherent so
            # a row can't classify as one target by scope and the other by hog_flow.
            models.CheckConstraint(
                check=models.Q(scope="team", hog_flow__isnull=True)
                | models.Q(scope="workflow", hog_flow__isnull=False),
                name="email_rep_snapshot_scope_matches_target",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "evaluated_at"], name="posthog_ema_team_id_a35f59_idx"),
            # Serves the evaluator's daily plan query (recent team rows with sends, no team filter).
            models.Index(
                fields=["evaluated_at"],
                condition=models.Q(hog_flow__isnull=True, emails_sent__gt=0),
                name="eml_rep_snapshot_plan_idx",
            ),
        ]

    class Scope(models.TextChoices):
        WORKFLOW = "workflow"
        TEAM = "team"

    class State(models.TextChoices):
        INSUFFICIENT_DATA = "insufficient_data"
        HEALTHY = "healthy"
        WARNING = "warning"
        CRITICAL = "critical"

    # db_constraint=False: posthog_team is a hot table; a real FK constraint would lock it on deploy.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    # Null hog_flow marks the team-level aggregate row.
    hog_flow = models.ForeignKey("workflows.HogFlow", on_delete=models.CASCADE, null=True, blank=True)
    scope = models.CharField(max_length=20, choices=Scope)
    state = models.CharField(max_length=20, choices=State)

    bounce_rate = models.FloatField(default=0.0)
    complaint_rate = models.FloatField(default=0.0)
    emails_sent = models.BigIntegerField(default=0)

    # End of the evaluated rolling window; shared by all rows of one evaluator run.
    evaluated_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        target = f"hog_flow {self.hog_flow_id}" if self.hog_flow_id else "team"
        return f"EmailReputationSnapshot({target}, {self.state}, {self.evaluated_at})"
