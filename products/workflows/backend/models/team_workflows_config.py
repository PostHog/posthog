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


register_team_extension_signal(TeamWorkflowsConfig, logger=logger)
