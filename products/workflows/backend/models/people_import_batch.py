from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class PeopleImportBatch(TeamScopedRootMixin, UUIDModel):
    """A list too long for one people import, split into parts that fill one cohort.

    The cohort fills once, after every part's people exist, so it shows as ready only when the whole list is in. An
    import that only updates people gets a one-part row too, which exists only once its caller committed.
    """

    # db_constraint=False: a real FK constraint to a hot table takes a parent-table lock on creation.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    cohort_id = models.IntegerField()
    parts = models.PositiveIntegerField()
    ready_parts = models.JSONField(
        default=dict, blank=True, help_text="The stored rows of each part whose people exist, by part number."
    )
    failed = models.BooleanField(default=False)
    fill_claimed_at = models.DateTimeField(
        null=True, blank=True, help_text="When a task last took on filling the cohort, so only one fills it at a time."
    )
    created_at = models.DateTimeField(auto_now_add=True)
