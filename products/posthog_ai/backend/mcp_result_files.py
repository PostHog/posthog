from uuid import uuid4

from django.conf import settings

from posthog.storage import object_storage

MCP_RESULT_FILE_MAX_BYTES = 8 * 1024 * 1024
MCP_RESULT_FILE_URL_TTL_SECONDS = 3600


class MCPResultFiles:
    @staticmethod
    def store(*, team_id: int, content: str) -> str:
        key = f"{settings.OBJECT_STORAGE_EXPORTS_FOLDER}/mcp_results/team_{team_id}/{uuid4()}/result.json"
        object_storage.write(
            key,
            content,
            extras={
                "ContentType": "application/json",
                "CacheControl": "private, no-store",
                "Tagging": f"ttl_days=21&team_id={team_id}",
            },
        )
        url = object_storage.get_presigned_url(key, expiration=MCP_RESULT_FILE_URL_TTL_SECONDS)
        if not url:
            raise object_storage.ObjectStorageError("Could not sign the result download URL")
        return url
