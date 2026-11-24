"""
Django models for hogs.

A hog is a persistent agent with one area of responsibility. Its chat holds only what it
chose to tell its owner; the work itself runs as task runs in the tasks product.
"""

import uuid

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin

from .facade.enums import (
    HogActionStatus,
    HogMessageAuthor,
    HogReportFollowUp,
    HogReportPriority,
    HogReportStatus,
    HogRuleEffect,
    HogStatus,
    HogWakeCause,
)


class Hog(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    created_by = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    name = models.CharField(max_length=80)
    emoji = models.CharField(max_length=16, default="🦔")
    color = models.CharField(max_length=16, default="#00A884")
    responsibility = models.TextField(blank=True, default="")
    memory = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=HogStatus.choices, default=HogStatus.SETUP.value)
    # IDs of the owner's MCP store installations this hog may use. Empty mounts none.
    mcp_installation_ids = models.JSONField(default=list)
    current_task_id = models.UUIDField(null=True, blank=True)
    current_run_id = models.UUIDField(null=True, blank=True)
    # Set when a wake is dispatched and cleared when the hog goes idle.
    working_since = models.DateTimeField(null=True, blank=True)
    # How many hog-to-hog notes led to the current wake. A wake from anything else resets it to 0.
    wake_hops = models.PositiveSmallIntegerField(default=0)
    last_message_at = models.DateTimeField(null=True, blank=True)
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["team", "created_by", "deleted"], name="hogs_hog_owner_idx")]

    def __str__(self) -> str:
        return self.name


class HogMessage(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    hog = models.ForeignKey(Hog, on_delete=models.CASCADE, related_name="messages")
    author = models.CharField(max_length=16, choices=HogMessageAuthor.choices)
    content = models.TextField()
    # False keeps the message out of the owner's chat: notes between hogs and wake records.
    in_chat = models.BooleanField(default=True)
    # The hog that sent this message to `hog`, for messages between hogs.
    from_hog = models.ForeignKey(Hog, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # For the owner's messages: when the hog was woken with it, and when the hog first acted after it.
    delivered_at = models.DateTimeField(null=True, blank=True)
    seen_at = models.DateTimeField(null=True, blank=True)
    # For the hog's messages: when the owner opened the chat.
    read_at = models.DateTimeField(null=True, blank=True)
    task_run_id = models.UUIDField(null=True, blank=True)
    # Set when the message is a report or an approval request. The chat draws it as a card the owner can act on.
    report = models.ForeignKey("HogReport", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    action = models.ForeignKey("HogAction", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["hog", "created_at"], name="hogs_message_hog_created_idx")]


class HogSchedule(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    hog = models.ForeignKey(Hog, on_delete=models.CASCADE, related_name="schedules")
    # What the hog told itself to do when this fires.
    prompt = models.TextField()
    # A 5-field cron expression in UTC for a repeating schedule. Null means it fires once.
    cron_expression = models.CharField(max_length=120, null=True, blank=True)
    next_fire_at = models.DateTimeField(null=True, blank=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["enabled", "next_fire_at"], name="hogs_schedule_due_idx")]


class HogWake(TeamScopedRootMixin):
    """One attempt to wake a hog. The hourly cap counts these."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    hog = models.ForeignKey(Hog, on_delete=models.CASCADE, related_name="wakes")
    cause = models.CharField(max_length=16, choices=HogWakeCause.choices)
    hops = models.PositiveSmallIntegerField(default=0)
    # True when the hourly cap stopped this wake.
    refused = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["hog", "created_at"], name="hogs_wake_hog_created_idx")]


class HogReport(TeamScopedRootMixin):
    """A finding a hog published for its owner to act on."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    hog = models.ForeignKey(Hog, on_delete=models.CASCADE, related_name="reports")
    title = models.CharField(max_length=200)
    summary = models.TextField()
    priority = models.CharField(max_length=2, choices=HogReportPriority.choices, default=HogReportPriority.P3.value)
    impact = models.TextField(blank=True, default="")
    proposal = models.TextField(blank=True, default="")
    # A list of {description, source, kind}.
    evidence = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=HogReportStatus.choices, default=HogReportStatus.OPEN.value)
    verdict_reason = models.CharField(max_length=200, blank=True, default="")
    # Which follow-up the owner started from the report: implement or investigate. Blank until they do.
    follow_up = models.CharField(max_length=16, choices=HogReportFollowUp.choices, blank=True, default="")
    read_at = models.DateTimeField(null=True, blank=True)
    task_run_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["hog", "status", "created_at"], name="hogs_report_hog_status_idx")]


class HogTrigger(TeamScopedRootMixin):
    """An external event source that wakes a hog when something posts to it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    hog = models.ForeignKey(Hog, on_delete=models.CASCADE, related_name="triggers")
    name = models.CharField(max_length=120)
    # What the hog should do with an event from this source.
    instructions = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    fire_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class HogEvent(TeamScopedRootMixin):
    """One event a trigger received. The record also makes a repeated delivery harmless."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    trigger = models.ForeignKey(HogTrigger, on_delete=models.CASCADE, related_name="events")
    # The sender's own ID for the event. A second event with the same ID is dropped.
    external_id = models.CharField(max_length=200, null=True, blank=True)
    payload = models.TextField()
    woke_hog = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["trigger", "external_id"],
                condition=models.Q(external_id__isnull=False),
                name="hogs_event_trigger_external_id_uniq",
            )
        ]


class HogAction(TeamScopedRootMixin):
    """Something a hog wants to do outside PostHog, held until the owner's rules or the owner allow it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    hog = models.ForeignKey(Hog, on_delete=models.CASCADE, related_name="actions")
    # A short name for the class of side effect, such as slack-message or github-pr. Rules match on it.
    kind = models.CharField(max_length=60)
    label = models.CharField(max_length=200)
    # Exactly what would be sent or changed. The owner may edit it before approving.
    draft = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=HogActionStatus.choices, default=HogActionStatus.PENDING.value)
    result = models.TextField(blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    task_run_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["hog", "status", "created_at"], name="hogs_action_hog_status_idx")]


class HogRule(TeamScopedRootMixin):
    """The owner's standing answer for one kind of action by one hog."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    hog = models.ForeignKey(Hog, on_delete=models.CASCADE, related_name="rules")
    kind = models.CharField(max_length=60)
    effect = models.CharField(max_length=8, choices=HogRuleEffect.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["hog", "kind"], name="hogs_rule_hog_kind_uniq")]
