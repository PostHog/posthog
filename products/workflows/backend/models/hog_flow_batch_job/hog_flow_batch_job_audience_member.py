from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class HogFlowBatchJobAudienceMember(TeamScopedRootMixin):
    """One person of a batch run's audience, resolved once before the run pages through it."""

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["batch_job", "person_id"], name="hogflowbatchjob_audience_member_unique"),
        ]

    batch_job = models.ForeignKey(
        "workflows.HogFlowBatchJob", on_delete=models.CASCADE, related_name="audience_members"
    )
    # No database constraint, so creating the table takes no lock on the hot team table.
    team = models.ForeignKey("posthog.Team", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+")
    person_id = models.UUIDField()
