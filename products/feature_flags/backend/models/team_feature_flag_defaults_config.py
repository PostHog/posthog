import logging

from django.db import models

from posthog.models import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamFeatureFlagDefaultsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    enabled = models.BooleanField(default=False)

    # Matches FeatureFlag.filters["groups"] structure:
    # [{"properties": [...], "rollout_percentage": N, "variant": null}, ...]
    default_groups = models.JSONField(default=list)


register_team_extension_signal(TeamFeatureFlagDefaultsConfig, logger=logger)
