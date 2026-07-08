"""Django models for tracing."""

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel
from posthog.utils import generate_short_id

# Define your models here
# Important:
# - Keep models thin, no business logic, use logic.py instead
# - Use types from facade/contracts.py or facade/enums.py where applicable
# - Do not use ForeignKeys to models outside this app unless allowed, as you will make implicit dependencies.
# - If you make a ForeignKey to a common model, disallow reverse relations with related_name='+'


class TracingView(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """A saved set of tracing filters (date range, services, attribute filters, sort, view mode).

    Content-only storage — `filters` mirrors the frontend `TracingFilters` shape; restoring a view
    just replays those filters into `tracingFiltersLogic`.
    """

    # FKs to the hot posthog_team / posthog_user tables use db_constraint=False so creating this
    # table takes no lock on those parents; the real constraints are added lock-free via
    # AddForeignKeyNotValid in the migration. created_by overrides CreatedMetaFields for the same reason.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    # Human-friendly id used in the API/URL instead of exposing the UUID primary key.
    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    name = models.CharField(max_length=400)
    filters = models.JSONField(default=dict)
    pinned = models.BooleanField(default=False)

    class Meta:
        db_table = "tracing_tracingview"
        unique_together = ("team", "short_id")
        indexes = [
            models.Index(fields=["team_id", "-created_at"], name="tracing_view_team_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} (Team: {self.team})"
