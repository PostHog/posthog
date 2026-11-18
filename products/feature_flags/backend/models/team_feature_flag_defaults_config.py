from django.db import models


class TeamFeatureFlagDefaultsConfig(models.Model):
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True, related_name="+")

    enabled = models.BooleanField(default=False)

    # Matches FeatureFlag.filters["groups"] structure:
    # [{"properties": [...], "rollout_percentage": N, "variant": null}, ...]
    default_groups = models.JSONField(default=list)
