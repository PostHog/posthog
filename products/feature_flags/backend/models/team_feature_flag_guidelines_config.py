import logging

from django.db import models

from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamFeatureFlagGuidelinesConfig(models.Model):
    """Project-level link to an internal feature-flag best-practices / SOP doc.

    When enabled, the URL is surfaced on the flag creation form and injected into
    the MCP environment context so agents creating flags follow the same guidelines.
    """

    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True)

    enabled = models.BooleanField(default=False)

    # An empty string means "not set"; the URL is validated at the serializer boundary.
    url = models.CharField(max_length=800, blank=True, default="")


register_team_extension_signal(TeamFeatureFlagGuidelinesConfig, logger=logger)
