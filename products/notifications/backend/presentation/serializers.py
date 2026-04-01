from rest_framework import serializers


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
