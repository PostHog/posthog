from django.db import models

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.utils import UUIDModel

TRANSACTIONAL_EMAIL_KEY_CONSTRAINT = "unique_transactional_email_key_per_team"
SOURCE_URL_MAX_LENGTH = 2048


class TransactionalEmailKey(UUIDModel):
    objects = TeamScopedManager()

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    key = models.CharField(max_length=400)
    hog_flow_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    # The file in the customer's repository that sends under this key, as a link a person pasted.
    source_url = models.URLField(max_length=SOURCE_URL_MAX_LENGTH, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "key"], name=TRANSACTIONAL_EMAIL_KEY_CONSTRAINT),
        ]
