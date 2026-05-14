from rest_framework import serializers

from products.notifications.backend.facade.enums import SourceType


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
