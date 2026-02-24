from django.conf import settings
from django.db import models


class SlackUserRepoPreference(models.Model):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="slack_repo_preferences")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="slack_repo_preferences")
    repository = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "user"], name="uniq_slack_repo_pref_team_user")]
