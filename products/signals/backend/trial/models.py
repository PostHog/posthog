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
