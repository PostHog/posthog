from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDTModel


class RecipientList(TeamScopedRootMixin, UUIDTModel):
    """
    An uploaded list for broadcasts: a static cohort of the people in it, and one row of data per person.

    A broadcast that sends to the cohort gives each run that person's row as `{{ variables.<column> }}`.
    The rows never become person properties, so data for one send stays out of the person profile.
    """

    # db_constraint=False on these hot-table FKs so CreateModel takes no lock on posthog_team / posthog_user.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    # The cohorts product owns Cohort, so the list keeps its ID instead of a foreign key across the boundary.
    cohort_id = models.BigIntegerField()
    columns = models.JSONField(default=list)
    # Set while the cohort is soft-deleted. A deleted cohort can be restored, so the rows stay for a while.
    cohort_deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "cohort_id"], name="workflows_recipient_list_unique_cohort"),
        ]


class RecipientListRow(TeamScopedRootMixin, models.Model):
    """One person's data in a recipient list, keyed by distinct ID because a person merge keeps distinct IDs."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    recipient_list = models.ForeignKey(RecipientList, on_delete=models.CASCADE, related_name="rows")
    distinct_id = models.CharField(max_length=200)
    data = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipient_list", "distinct_id"], name="workflows_recipient_list_row_unique_distinct_id"
            ),
        ]
