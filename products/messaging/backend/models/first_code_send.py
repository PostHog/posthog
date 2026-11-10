from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

FIRST_CODE_SEND_CONSTRAINT = "unique_first_code_send_per_team"


class FirstCodeSend(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team"], name=FIRST_CODE_SEND_CONSTRAINT),
        ]
