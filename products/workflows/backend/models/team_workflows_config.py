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

    # Staff-controlled kill switch: while set, the CDP email worker blocks all workflow email
    # for this team at send time. Set/cleared via Django admin; audit trail lives in the activity log.
    email_sending_suspended_at = models.DateTimeField(null=True, blank=True)
    email_sending_suspension_reason = models.TextField(blank=True, default="")

    # Last-known state of the team's AWS SES tenant, mirrored so state *changes* can trigger
    # customer emails exactly once (EventBridge events are best-effort; a periodic sweep
    # reconciles). Empty string = never synced; the first sync only notifies a tenant that is
    # already paused or already carries high-impact findings.
    # Both fields mirror AWS enums verbatim, so they're sized well past today's longest value
    # ("REINSTATED", "NONE") — a new level must not start failing writes.
    # db_default so raw INSERTs from non-Django writers keep working.
    ses_tenant_sending_status = models.CharField(max_length=32, blank=True, default="", db_default="")
    ses_tenant_reputation_impact = models.CharField(max_length=32, blank=True, default="", db_default="")
    ses_tenant_state_synced_at = models.DateTimeField(null=True, blank=True)


register_team_extension_signal(TeamWorkflowsConfig, logger=logger)
