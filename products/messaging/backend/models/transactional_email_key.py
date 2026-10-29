from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

TRANSACTIONAL_EMAIL_KEY_CONSTRAINT = "unique_transactional_email_key_per_team"


class TransactionalEmailKey(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    key = models.CharField(max_length=400)
    hog_flow_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "key"], name=TRANSACTIONAL_EMAIL_KEY_CONSTRAINT),
        ]
