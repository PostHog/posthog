from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from products.notifications.backend.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    actor = UserBasicSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "notification_type",
            "priority",
            "title",
            "body",
            "read",
            "read_at",
            "source_type",
            "source_id",
            "source_url",
            "actor",
            "created_at",
        ]
        read_only_fields = fields
