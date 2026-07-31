import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal
from posthog.rbac.decorators import field_access_control

logger = logging.getLogger(__name__)


class TeamSecureConnectionsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)
    cdp_approved_connections = field_access_control(models.JSONField(default=dict), "project", "admin")


register_team_extension_signal(TeamSecureConnectionsConfig, logger=logger)
