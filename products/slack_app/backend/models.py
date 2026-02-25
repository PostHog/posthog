from django.conf import settings
from django.db import models


class SlackUserRepoPreference(models.Model):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="slack_repo_preferences")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="slack_repo_preferences")
    channel = models.CharField(max_length=64)
    repository = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "user", "channel"], name="uniq_slack_repo_pref_team_user_channel")
        ]


class SlackUserProfileCache(models.Model):
    integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.CASCADE,
        related_name="slack_user_profile_cache",
    )
    slack_user_id = models.CharField(max_length=64)
    email = models.EmailField(blank=True, null=True)
    display_name = models.CharField(max_length=255, blank=True, default="")
    real_name = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["integration", "slack_user_id"],
                name="uniq_slack_user_profile_cache_integration_user",
            )
        ]
