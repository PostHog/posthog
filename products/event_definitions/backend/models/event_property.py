from django.db import models
from django.db.models.expressions import F
from django.db.models.functions import Coalesce

from posthog.models.utils import UniqueConstraintByExpression, sane_repr


class EventProperty(models.Model):
    id = models.BigAutoField(primary_key=True)
    # db_index=False: the bare (team_id) auto-FK index is a strict prefix of every (team_id, X)
    # composite, so it adds no read value while burning ~143 GB of bloat. Dropped via concurrent
    # migration; this flag prevents Django from regenerating it.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_index=False)
    project = models.ForeignKey("posthog.Project", on_delete=models.CASCADE, null=True)
    event = models.CharField(max_length=400, null=False)
    property = models.CharField(max_length=400, null=False)

    class Meta:
        db_table = "posthog_eventproperty"
        constraints = [
            UniqueConstraintByExpression(
                concurrently=True,
                name="posthog_event_property_unique_proj_event_property",
                expression="(coalesce(project_id, team_id), event, property)",
            ),
        ]
        indexes = [
            models.Index(fields=["project"], name="posthog_eve_proj_id_dd2337d2"),
            # (team_id, event) — kept for the cross-team event_screenshots Temporal JOIN, which
            # the planner empirically uses for the Nested Loop inner probe. REINDEXed (not dropped)
            # in the Tier 2 migration to reclaim ~720 GB of bloat at natural size.
            models.Index(fields=["team", "event"]),
            # (coalesce(project_id, team_id), event) — kept here pending PR #57590 (REINDEX of the
            # bloated unique constraint). The unique constraint covers this index as a strict
            # leading prefix, but at 1187 GB bloated it is far larger than the ~67 GB target index;
            # dropping before the unique constraint is reindexed would migrate any residual queries
            # onto a much wider working set. A separate follow-up PR drops this once #57590 ships.
            models.Index(Coalesce(F("project_id"), F("team_id")), F("event"), name="posthog_eve_proj_id_22de03_idx"),
            # (coalesce(project_id, team_id), property) — used by property-definition listing
            # filtered on a single property. Kept.
            models.Index(Coalesce(F("project_id"), F("team_id")), F("property"), name="posthog_eve_proj_id_26dbfb_idx"),
        ]

    __repr__ = sane_repr("event", "property", "team_id")
