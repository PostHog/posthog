from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.notifications.backend.facade.enums import SourceType


@extend_schema_field(OpenApiTypes.OBJECT)
class _NotificationMetadataField(serializers.JSONField):
    pass


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
    metadata = _NotificationMetadataField(
        required=False,
        allow_null=True,
        help_text=(
            "Optional structured payload for rich client-side rendering, specific to the notification "
            "type. For `web_analytics_digest`, holds the weekly metrics (visitors, pageviews, sessions, "
            "bounce rate, session duration with week-over-week change), top pages, and top sources used "
            "to render the digest card."
        ),
    )
    created_at = serializers.DateTimeField()
