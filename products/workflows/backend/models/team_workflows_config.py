import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class EmailTrackingConsentMode(models.TextChoices):
    # No consent enforcement: tracking follows the email step's own setting only.
    OFF = "off"
    # Track by default; suppress tracking for recipients who have opted out.
    OPT_OUT = "opt_out"
    # Do not track unless the recipient has explicitly opted in.
    OPT_IN = "opt_in"


class TeamWorkflowsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # Opt-in toggle for emitting workflows engagement activity (sends, opens, clicks, bounces, etc.)
    # as standard PostHog events alongside the existing workflow metrics.
    capture_workflows_engagement_events = models.BooleanField(default=False)

    # Recipient-consent enforcement for open/click tracking on marketing emails (CNIL/ePrivacy).
    # Enforced at send time in the Node worker; transactional emails are exempt.
    email_tracking_consent_mode = models.CharField(
        max_length=16, choices=EmailTrackingConsentMode.choices, default=EmailTrackingConsentMode.OFF
    )


register_team_extension_signal(TeamWorkflowsConfig, logger=logger)
