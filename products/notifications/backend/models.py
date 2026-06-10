from django.db import models
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UUIDModel

from products.notifications.backend.facade.enums import NotificationType, Priority, TargetType


class NotificationEvent(UUIDModel):
    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, null=True, blank=True)
    notification_type = models.CharField(max_length=32, choices=[(t.value, t.name) for t in NotificationType])
    priority = models.CharField(max_length=16, choices=[(p.value, p.name) for p in Priority], default=Priority.NORMAL)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    resource_type = models.CharField(max_length=64, null=True, blank=True)
    resource_id = models.CharField(max_length=64, blank=True, default="")
    source_url = models.CharField(max_length=512, blank=True, default="")
    source_type = models.CharField(max_length=64, null=True, blank=True)
    source_id = models.CharField(max_length=64, null=True, blank=True)
    target_type = models.CharField(max_length=16, choices=[(t.value, t.name) for t in TargetType])
    target_id = models.CharField(max_length=64)
    resolved_user_ids = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
        ]


class AgentNotice(TeamScopedRootMixin, CreatedMetaFields, UUIDModel):
    """Staff-authored notice injected into customer MCP agent sessions.

    The message text reaches customer agent context verbatim — staff-only
    authorship via Django admin is the trust boundary. The team FK is the
    visibility boundary: team-targeted notices never leave the database for
    other teams' sessions. Broadcast rows (team NULL) are visible to every
    team, so they must not carry customer-specific details.

    Targeting is the intersection of both fields: team (or broadcast) decides
    who may see the notice, and when a feature flag is set it must also
    evaluate true for the session — the flag narrows delivery within the
    team's audience, never widens it.
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="agent_notices",
        help_text="Target project. Leave empty to broadcast to all projects.",
    )
    message = models.TextField(max_length=1000)
    feature_flag = models.ForeignKey(
        "feature_flags.FeatureFlag",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="agent_notices",
        help_text="Optional feature flag (from PostHog's internal analytics project) gating delivery. "
        "Applied on top of the team targeting: the team decides who may see the notice, and this flag "
        "must additionally evaluate true for the session — it narrows delivery, never widens it.",
    )
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-starts_at"]
        indexes = [
            models.Index(fields=["team", "expires_at"], name="agent_notice_team_expires_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("starts_at")),
                name="agent_notice_expires_after_starts",
            ),
        ]


class NotificationReadState(UUIDModel):
    notification_event = models.ForeignKey(
        NotificationEvent,
        on_delete=models.CASCADE,
        related_name="read_states",
    )
    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="notification_read_states",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["notification_event", "user"],
                name="unique_read_state_per_user",
            ),
        ]
