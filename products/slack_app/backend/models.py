from django.db import models

from posthog.models.utils import UUIDModel


class SlackThreadTaskMapping(UUIDModel):
    """Maps Slack threads to task runs so follow-up messages can be forwarded to the running agent."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="slack_thread_task_mappings")
    integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.CASCADE,
        related_name="slack_thread_task_mappings",
    )
    slack_workspace_id = models.CharField(max_length=64)
    channel = models.CharField(max_length=64)
    thread_ts = models.CharField(max_length=64)
    task = models.ForeignKey(
        "tasks.Task",
        on_delete=models.CASCADE,
        related_name="slack_thread_mappings",
    )
    task_run = models.ForeignKey(
        "tasks.TaskRun",
        on_delete=models.CASCADE,
        related_name="slack_thread_mappings",
    )
    mentioning_slack_user_id = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["integration", "channel", "thread_ts"],
                name="uniq_slack_thread_task_mapping",
            )
        ]


class SlackUserProfileCache(UUIDModel):
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
