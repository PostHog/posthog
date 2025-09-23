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

        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
        ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".svg"}
        ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/svg+xml"}
        _, file_extension = os.path.splitext(file.name)

        if file.size > MAX_FILE_SIZE:
            return JsonResponse({"error": "File too large"}, status=400)

        if file_extension.lower() not in ALLOWED_EXTENSIONS:
            return JsonResponse({"error": "Invalid file type"}, status=400)

        if file.content_type not in ALLOWED_MIME_TYPES:
            return JsonResponse({"error": "Invalid MIME type"}, status=400)

        object_name = f"{str(uuid7())}{file_extension}"
        object_path = f"assets/{self.team_id}/{object_name}"
        object_storage.write(object_path, file, bucket=settings.MESSAGING_ATTACHMENTS_OBJECT_STORAGE_BUCKET)

        object_url = f"https://{settings.MESSAGING_ATTACHMENTS_CDN_DOMAIN}/{object_path}"

        return Response(
            {
                "file_url": object_url,
            }
        )
