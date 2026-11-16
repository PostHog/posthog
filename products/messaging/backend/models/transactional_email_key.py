from django.db import models

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.utils import UUIDModel

from products.messaging.backend.facade.contracts import CodeEmailSourceOrigin

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
    # Whether a person set or cleared source_url, or detection found it. Null until either happens, so detection
    # can tell a key nobody touched from one a person unlinked, and never relinks the second.
    source_origin = models.CharField(max_length=16, choices=CodeEmailSourceOrigin.choices, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "key"], name=TRANSACTIONAL_EMAIL_KEY_CONSTRAINT),
        ]
