from django.db import models
from django.db.models import Q

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
    is_admin = models.BooleanField(default=False, db_default=False)
    is_owner = models.BooleanField(default=False, db_default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["integration", "slack_user_id"],
                name="uniq_slack_user_profile_cache_integration_user",
            )
        ]


class SlackSettings(UUIDModel):
    """Per-(Slack workspace, Slack user) settings for inbound `slack-posthog-code`
    events. Currently stores the routing default — which PostHog integration a
    mention from this Slack user should route to.

    Two row shapes share this table:
    - ``slack_user_id`` set → that Slack user's personal settings for this workspace.
      Written by the Slack `@PostHog project <id>` directive or the user-level
      settings UI.
    - ``slack_user_id IS NULL`` → workspace-wide fallback, applied when an
      inbound event's Slack user has no personal row yet. Written only via the
      PostHog project-level settings UI by a team admin (never via Slack).

    A user-specific row, if present, always wins over the workspace-wide row at
    resolution time.
    """

    default_integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.CASCADE,
        related_name="slack_settings_as_default",
    )
    slack_workspace_id = models.CharField(max_length=64)
    slack_user_id = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["slack_workspace_id", "slack_user_id"],
                name="uniq_slack_settings_per_user",
                condition=Q(slack_user_id__isnull=False),
            ),
            # Partial: NULL slack_user_id is the workspace-wide row, which
            # Postgres's default NULL-distinct rule wouldn't otherwise dedupe.
            models.UniqueConstraint(
                fields=["slack_workspace_id"],
                name="uniq_slack_settings_per_workspace",
                condition=Q(slack_user_id__isnull=True),
            ),
        ]

    def __str__(self) -> str:
        who = self.slack_user_id or "(workspace default)"
        return f"{self.slack_workspace_id} / {who} → integration {self.default_integration_id}"
