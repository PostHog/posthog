from rest_framework import serializers

from products.notifications.backend.facade.enums import SourceType


class AgentNoticeSerializer(serializers.Serializer):
    """Read serializer for `AgentNoticeData` facade DTOs."""

    id = serializers.UUIDField(help_text="Unique identifier of the notice.")
    message = serializers.CharField(help_text="Notice text intended for the project's AI agent sessions.")
    feature_flag_key = serializers.CharField(
        allow_null=True,
        help_text="Optional feature flag key gating delivery; when set, deliver only if the flag evaluates true.",
    )
    starts_at = serializers.DateTimeField(help_text="When the notice becomes active.")
    expires_at = serializers.DateTimeField(help_text="When the notice stops being delivered.")
    created_at = serializers.DateTimeField(help_text="When the notice was created.")


class NotificationEventSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    team_id = serializers.IntegerField(allow_null=True)
    notification_type = serializers.CharField()
    priority = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    read = serializers.BooleanField()
    read_at = serializers.DateTimeField(allow_null=True)
    target_type = serializers.CharField()
    target_id = serializers.CharField()
    resource_type = serializers.CharField(allow_null=True)
    resource_id = serializers.CharField()
    source_url = serializers.CharField()
    source_type = serializers.ChoiceField(choices=[(s.value, s.name) for s in SourceType], allow_null=True)
    source_id = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
