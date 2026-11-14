from datetime import timedelta

from django.db import models

# The Node `EmailSuppressionService` holds a global entry for at most this long after its last bounce.
GLOBAL_HARD_BOUNCE_MAX_HOLD = timedelta(days=14)


class EmailHardBounce(models.Model):
    """
    Instance-global list of email addresses that do not exist. A hard bounce that proves the address does
    not exist adds it, whichever team sent the email. Every team's sends skip a listed address, except a
    team that removed the address from its own suppression list. A later successful delivery from any team
    proves the address exists. It sets `last_delivered_at`, and the entry stops blocking until a newer bounce.

    An entry only holds for as long as the address has been bouncing, from 1 day up to 14 days after its last
    bounce. After that the next send tries the address again, and a new bounce renews the entry with a longer
    hold. The Node `EmailSuppressionService` applies the hold when it reads the table.

    The table has no team_id because the fact belongs to the address, not to a team.
    """

    # Lower-cased recipient email address.
    email = models.CharField(max_length=512, primary_key=True)
    first_bounced_at = models.DateTimeField()
    last_bounced_at = models.DateTimeField()
    # The newest successful delivery to the address. A bounce older than it, processed late, does not block the address.
    last_delivered_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "posthog_emailhardbounce"

    def __str__(self) -> str:
        return self.email
