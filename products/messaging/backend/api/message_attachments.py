from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import MessageRecipientPreference
from posthog.plugins import plugin_server_api


class MessagePreferencesSerializer(serializers.ModelSerializer):
    identifier = serializers.CharField()
    updated_at = serializers.DateTimeField()
    preferences = serializers.JSONField()

    class Meta:
        model = MessageRecipientPreference
        fields = [
            "id",
            "identifier",
            "updated_at",
            "preferences",
        ]
        read_only_fields = [
            "id",
            "identifier",
            "created_at",
            "updated_at",
            "created_by",
        ]


class MessageAttachmentsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    @action(detail=False, methods=["post"])
    def upload_attachment(self, request, **kwargs):
        file_url = plugin_server_api.upload_messaging_attachment(
            self.team_id,
            request.FILES.get("file"),
        )

        return Response(
            {
                "file_url": file_url,
            }
        )
