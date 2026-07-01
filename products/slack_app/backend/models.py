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
    latest_actor_slack_user_id = models.CharField(max_length=64, null=True, blank=True)
    # Slack `ts` of the most recent message we've already shown to the agent (either
    # in the original `<slack_thread_context>` block at task creation, or in a follow-up
    # `<slack_thread_context_update>` diff). On each follow-up, anything in the thread
    # with a strictly larger `ts` (and smaller than the just-arrived message's `ts`) is
    # rendered as a diff so the agent catches up on messages it never saw.
    last_forwarded_ts = models.CharField(max_length=64, null=True, blank=True)
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
    is_bot = models.BooleanField(default=False, db_default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Null is treated as stale (rows predating this field).
    refreshed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["integration", "slack_user_id"],
                name="uniq_slack_user_profile_cache_integration_user",
            )
        ]


class SlackSettings(UUIDModel):
    """Per-(Slack workspace, Slack user) settings for inbound Slack events.
    Currently stores the routing default — which PostHog integration a mention
    from this Slack user should route to.

    Two row shapes share this table:
    - ``slack_user_id`` set → that Slack user's personal settings for this workspace.
      Written by the Slack `@PostHog project <id>` directive or the user-level
      settings UI.
    - ``slack_user_id IS NULL`` → workspace-wide fallback, applied when an
      inbound event's Slack user has no personal row yet. Written via the
      PostHog project-level settings UI by a team admin, or via the Slack
      `@PostHog project workspace <id>` directive by a Slack workspace
      admin/owner.

    A user-specific row, if present, always wins over the workspace-wide row at
    resolution time.
    """

    # Nullable so a personal row can carry AI preferences while inheriting the
    # workspace routing default.
    default_integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.CASCADE,
        related_name="slack_settings_as_default",
        null=True,
        blank=True,
    )
    slack_workspace_id = models.CharField(max_length=64)
    slack_user_id = models.CharField(max_length=64, null=True, blank=True)
    # Keys mirror the task-run request serializer.
    ai_preferences = models.JSONField(blank=True, null=True)
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
        target = self.default_integration_id if self.default_integration_id else "(inherit)"
        return f"{self.slack_workspace_id} / {who} → integration {target}"

    @property
    def runtime_adapter(self) -> str | None:
        return (self.ai_preferences or {}).get("runtime_adapter")

    @property
    def model(self) -> str | None:
        return (self.ai_preferences or {}).get("model")

    @property
    def reasoning_effort(self) -> str | None:
        return (self.ai_preferences or {}).get("reasoning_effort")


class SlackChannel(UUIDModel):
    """Per-(Slack workspace, Slack channel) state.

    Today the only meaning of a row with ``approved_at`` set is that a user
    in the channel has acknowledged that PostHog data answered there may be
    visible to external (cross-workspace) members. Absence of a row — or a
    row with ``approved_at`` null — for an externally-shared channel means
    the bot must refuse to answer and post the approval prompt instead.
    Non-externally-shared channels skip the lookup entirely.

    The approval is workspace-scoped, not integration-scoped: a single
    workspace can be connected to multiple PostHog projects, and once any
    member of any of those orgs has consented to the bot answering in this
    channel the consent applies to all of them. Per-mention data access
    remains gated by the existing email → ``OrganizationMembership`` check,
    so workspace-scope here only governs the channel-level question
    ("can the bot speak here at all?"), not which project's data is read.

    Reserved for future per-channel configuration (denials, routing
    overrides, etc.) without needing another model.
    """

    slack_workspace_id = models.CharField(max_length=64)
    slack_channel_id = models.CharField(max_length=64)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_slack_channels",
        help_text="The PostHog user who clicked Approve. Carries the email and audit trail.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["slack_workspace_id", "slack_channel_id"],
                name="uniq_slack_channel",
            )
        ]

    @property
    def is_approved(self) -> bool:
        return self.approved_at is not None
