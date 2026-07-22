import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamWorkflowsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # Opt-in toggle for emitting workflows engagement activity (sends, opens, clicks, bounces, etc.)
    # as standard PostHog events alongside the existing workflow metrics.
    capture_workflows_engagement_events = models.BooleanField(default=False)

    # Staff-controlled kill switch: while set, the CDP email worker blocks all workflow email
    # for this team at send time. Set/cleared via Django admin; audit trail lives in the activity log.
    email_sending_suspended_at = models.DateTimeField(null=True, blank=True)
    email_sending_suspension_reason = models.TextField(blank=True, default="")


register_team_extension_signal(TeamWorkflowsConfig, logger=logger)
