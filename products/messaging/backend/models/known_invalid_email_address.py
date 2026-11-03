from django.db import models


class KnownInvalidEmailAddress(models.Model):
    """
    Instance-global list of email addresses that do not exist. A hard bounce that proves the address
    does not exist, such as "550 5.1.1 user unknown", adds it, whichever team sent the email. This list
    blocks the address for every team except a team that removed it from its own list. A later
    successful delivery from any team deletes the row.

    The table has no team_id because the fact belongs to the address, not to a team. It stores a
    SHA-256 hash of the lower-cased address, so a raw address never leaves the team that emailed it.
    """

    identifier_hash = models.CharField(max_length=64, primary_key=True)
    first_bounced_at = models.DateTimeField()
    last_bounced_at = models.DateTimeField()
    # The team whose send bounced last. Kept for support investigations only. Never shown to other teams.
    last_bounced_team_id = models.BigIntegerField()

    class Meta:
        db_table = "posthog_knowninvalidemailaddress"

    def __str__(self) -> str:
        return f"Known invalid address {self.identifier_hash[:12]}"
