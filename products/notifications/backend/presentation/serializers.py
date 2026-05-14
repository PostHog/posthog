from rest_framework import serializers

from products.notifications.backend.facade.enums import Priority, SourceType

NOTIFICATION_STYLE_CHOICES = ["envelope", "scroll", "galactic"]


class NotificationEventSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Unique identifier for this notification event.")
    team_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the team this notification belongs to, or null when the notification is organization-scoped.",
    )
    notification_type = serializers.CharField(
        help_text=(
            "What kind of notification this is — for example 'alert_firing', 'comment_mention', "
            "'issue_assigned', 'approval_requested', 'approval_resolved', 'experiment_concluded', "
            "or 'concierge'."
        ),
    )
    priority = serializers.CharField(
        help_text="Delivery priority: 'normal' (popover only) or 'critical' (popover plus persistent toast).",
    )
    title = serializers.CharField(help_text="Short headline shown to the user in the notification UI.")
    body = serializers.CharField(help_text="Full message body shown beneath the title.")
    read = serializers.BooleanField(help_text="Whether the current user has marked this notification as read.")
    read_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the current user marked this notification as read, or null if still unread.",
    )
    resource_type = serializers.CharField(
        allow_null=True,
        help_text=(
            "Type of resource this notification points at, e.g. 'dashboard', 'insight', 'alert', 'comment'. "
            "Null when the notification is not tied to a specific resource."
        ),
    )
    resource_id = serializers.CharField(
        help_text="ID of the linked resource (matches resource_type). Empty when not applicable.",
    )
    source_url = serializers.CharField(
        help_text="Relative PostHog URL to navigate to when the user clicks the notification.",
    )
    source_type = serializers.ChoiceField(
        choices=[(s.value, s.name) for s in SourceType],
        allow_null=True,
        help_text="Subsystem that produced the notification (e.g. 'alerts', 'comments'). Null if unattributed.",
    )
    source_id = serializers.CharField(
        allow_null=True,
        help_text="ID of the producing record in the source subsystem (e.g. alert ID, comment ID).",
    )
    created_at = serializers.DateTimeField(help_text="When the notification was created, in ISO 8601 format.")


class SendConciergeNotificationSerializer(serializers.Serializer):
    target_user_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        help_text=(
            "IDs of the PostHog users who should receive this notification. Each user will receive the "
            "notification in their current project. Users without a current team are skipped."
        ),
    )
    title = serializers.CharField(
        max_length=255,
        help_text="Short headline shown to the user in the notification UI (max 255 characters).",
    )
    body = serializers.CharField(
        allow_blank=True,
        help_text="Main message body shown beneath the title. Can be left blank if the long-form wizard text carries the message.",
    )
    priority = serializers.ChoiceField(
        choices=[(p.value, p.name) for p in Priority],
        default=Priority.NORMAL.value,
        help_text="Delivery priority: 'normal' (popover only) or 'critical' (popover plus persistent toast).",
    )
    notification_style = serializers.ChoiceField(
        choices=[(s, s) for s in NOTIFICATION_STYLE_CHOICES],
        default="envelope",
        help_text="Visual style for the notification: 'envelope', 'scroll', or 'galactic'.",
    )
    skill = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional skill identifier used by the wizard UI to render an associated capability for the user.",
    )
    long_form_wizard_text = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional long-form text shown in the notification wizard expanded view.",
    )


class SendConciergeNotificationSkippedSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(help_text="ID of the user that was skipped.")
    reason = serializers.CharField(help_text="Human-readable reason the notification was not delivered to this user.")


class SendConciergeNotificationResponseSerializer(serializers.Serializer):
    sent = serializers.IntegerField(help_text="Number of users that successfully received the notification.")
    skipped = SendConciergeNotificationSkippedSerializer(
        many=True,
        help_text="List of users that were skipped, with the reason for each (e.g. no current team, suppressed by feature flag).",
    )
    notification_event_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="IDs of the NotificationEvent rows that were created, one per successfully delivered user.",
    )
