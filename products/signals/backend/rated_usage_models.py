from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class SignalRatedUsage(TeamScopedRootMixin, UUIDModel):
    # Keep the first delivery's identity even if its project moves or is deleted.
    team_id = models.BigIntegerField()
    organization_id = models.UUIDField()
    day = models.DateField(db_index=True)
    cents = models.PositiveBigIntegerField()

    class Meta:
        indexes = [models.Index(fields=["organization_id", "day"], name="signals_rated_usage_org_day")]
        constraints = [models.UniqueConstraint(fields=["team_id", "day"], name="signals_rated_usage_team_day")]
