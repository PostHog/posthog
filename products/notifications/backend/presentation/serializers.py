from rest_framework import serializers

from products.notifications.backend.facade.enums import SourceType


class NotificationEventSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    team_id = serializers.IntegerField(allow_null=True)
    notification_type = serializers.CharField()
    priority = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    read = serializers.BooleanField()
    read_at = serializers.DateTimeField(allow_null=True)
    resource_type = serializers.CharField(allow_null=True)
    resource_id = serializers.CharField()
    source_url = serializers.CharField()
    source_type = serializers.ChoiceField(choices=[(s.value, s.name) for s in SourceType], allow_null=True)
    source_id = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
