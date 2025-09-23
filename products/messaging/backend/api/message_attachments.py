import os

from django.conf import settings
from django.http import JsonResponse

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.utils import uuid7
from posthog.storage import object_storage


class MessageAttachmentsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    @action(detail=False, methods=["post"])
    def upload(self, request, **kwargs):
        file = request.FILES.get("file")
        if not file:
            return JsonResponse({"error": "Missing file"}, status=400)

        _, file_extension = os.path.splitext(file.name)

        object_name = f"{str(uuid7())}{file_extension}"
        object_path = f"{self.team_id}/{object_name}"
try:
    object_storage.write(object_path, file, bucket=settings.MESSAGING_ATTACHMENTS_OBJECT_STORAGE_BUCKET)
except Exception as e:
    return JsonResponse({"error": "Upload failed"}, status=500)

        object_url = f"https://{settings.MESSAGING_ATTACHMENTS_CDN_DOMAIN}/{object_path}"

        return Response(
            {
                "file_url": object_url,
            }
        )
