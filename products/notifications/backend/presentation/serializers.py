from rest_framework import serializers

from products.notifications.backend.facade.enums import NotificationType, Priority


class SendTestNotificationSerializer(serializers.Serializer):
    notification_type = serializers.ChoiceField(choices=[(t.value, t.name) for t in NotificationType])
    priority = serializers.ChoiceField(choices=[(p.value, p.name) for p in Priority], default=Priority.NORMAL.value)


class NotificationEventSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    notification_type = serializers.CharField()
    priority = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    read = serializers.BooleanField()
    read_at = serializers.DateTimeField(allow_null=True)
    resource_type = serializers.CharField(allow_null=True)
    resource_id = serializers.CharField()
    source_url = serializers.CharField()
    created_at = serializers.DateTimeField()
