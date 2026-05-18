import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamWebAnalyticsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    overview_lazy_precomputation_enabled = models.BooleanField(
        default=False,
        help_text=(
            "Whether to populate and serve the WebOverview tile from the lazy precomputation cache "
            "(`web_analytics_overview_lazy`). Off by default; enable per team during rollout."
        ),
    )


register_team_extension_signal(TeamWebAnalyticsConfig, logger=logger)
