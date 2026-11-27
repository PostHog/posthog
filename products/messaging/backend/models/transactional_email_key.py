from django.db import connection, models

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


TRANSACTIONAL_EMAIL_KEY_LOCK = "transactional-email-keys"


def lock_team_keys(team_id: int) -> None:
    """Held by a send while it adds a key, and by anything that must not race one, such as a template import."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"{TRANSACTIONAL_EMAIL_KEY_LOCK}:{team_id}"]
        )
