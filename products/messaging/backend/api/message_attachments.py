from django.conf import settings
from django.http import JsonResponse

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import MessageRecipientPreference
from posthog.models.utils import uuid7
from posthog.storage import object_storage


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
    def upload(self, request, **kwargs):
        file = request.FILES.get("file")
        if not file:
            return JsonResponse({"error": "Missing file"}, status=400)

        object_path = f"{request.team.id}/{str(uuid7())}"
        object_storage.write(
            object_path,
            file,
            bucket=settings.OBJECT_STORAGE_MESSAGING_ATTACHMENTS_BUCKET or "posthog-message-attachments-dev",
        )

        file_url = object_storage.url(
            object_path,
            bucket=settings.OBJECT_STORAGE_MESSAGING_ATTACHMENTS_BUCKET or "posthog-message-attachments-dev",
        )

        return Response(
            {
                "file_url": file_url,
            }
        )
