from typing import Optional

from posthog.storage import object_storage

# How long a presigned content URL stays valid. Short — the asset viewer fetches
# it immediately on open.
CONTENT_URL_EXPIRY_SECONDS = 60


def presigned_content_url(s3_key: str) -> Optional[str]:
    """A short-lived presigned GET URL for the rendered email HTML, served inline."""
    return object_storage.get_presigned_url(
        s3_key,
        expiration=CONTENT_URL_EXPIRY_SECONDS,
        content_type="text/html; charset=utf-8",
        content_disposition="inline",
    )
