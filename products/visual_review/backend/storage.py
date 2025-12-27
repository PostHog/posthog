"""
Storage utilities for visual review artifacts.
"""

import os
from typing import Any

from django.conf import settings

from posthog.storage import object_storage


class ArtifactStorage:
    """
    Handles S3 storage operations for visual review artifacts.
    Content-addressable: same hash = same key = deduplication.
    """

    FOLDER = os.getenv("OBJECT_STORAGE_VISUAL_REVIEW_FOLDER", "visual_review")
    MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10MB per image
    PRESIGNED_EXPIRATION = 60 * 15  # 15 minutes

    def __init__(self, project_id: str):
        self.project_id = project_id

    def _key(self, content_hash: str) -> str:
        return f"{self.FOLDER}/{self.project_id}/{content_hash}"

    def get_presigned_upload_url(self, content_hash: str) -> dict[str, Any] | None:
        if not settings.OBJECT_STORAGE_ENABLED:
            return None

        return object_storage.get_presigned_post(
            file_key=self._key(content_hash),
            conditions=[
                ["content-length-range", 0, self.MAX_SIZE_BYTES],
                ["starts-with", "$Content-Type", "image/"],
            ],
            expiration=self.PRESIGNED_EXPIRATION,
        )

    def get_presigned_download_url(self, content_hash: str, expiration: int = 3600) -> str | None:
        if not settings.OBJECT_STORAGE_ENABLED:
            return None

        return object_storage.get_presigned_url(file_key=self._key(content_hash), expiration=expiration)

    def exists(self, content_hash: str) -> bool:
        if not settings.OBJECT_STORAGE_ENABLED:
            return False

        return object_storage.head_object(file_key=self._key(content_hash)) is not None

    def get_metadata(self, content_hash: str) -> dict[str, Any] | None:
        if not settings.OBJECT_STORAGE_ENABLED:
            return None

        return object_storage.head_object(file_key=self._key(content_hash))

    def delete(self, content_hash: str) -> None:
        if not settings.OBJECT_STORAGE_ENABLED:
            return

        object_storage.delete(self._key(content_hash))

    def write(self, content_hash: str, content: bytes) -> str:
        """
        Directly write content to storage (for server-side uploads like diff images).
        Returns the storage key.
        """
        key = self._key(content_hash)
        object_storage.write(key, content, extras={"ContentType": "image/png"})
        return key
