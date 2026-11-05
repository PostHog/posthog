from django.db import models


class EmailHardBounce(models.Model):
    """
    Instance-global list of email addresses that do not exist. A hard bounce that proves the address does
    not exist adds it, whichever team sent the email. Every team's sends skip a listed address, except a
    team that removed the address from its own suppression list. A later successful delivery from any team
    proves the address exists, and deletes the row.

    The table has no team_id because the fact belongs to the address, not to a team.
    """

    # Lower-cased recipient email address.
    email = models.CharField(max_length=512, primary_key=True)
    first_bounced_at = models.DateTimeField()
    last_bounced_at = models.DateTimeField()

    class Meta:
        db_table = "posthog_emailhardbounce"

    def __str__(self) -> str:
        return self.email
