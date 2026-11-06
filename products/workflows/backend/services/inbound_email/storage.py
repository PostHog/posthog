"""Where a team's mail lives in object storage, and the short-lived links that read it."""

import json
from dataclasses import asdict
from typing import Any
from urllib.parse import quote
from uuid import UUID

from django.conf import settings

from posthog.storage import object_storage

from products.workflows.backend.services.inbound_email.parsing import ParsedEmail

LINK_EXPIRY_SECONDS = 60 * 60
_DELETE_BATCH = 1000


def bucket() -> str:
    return settings.WORKFLOWS_INBOUND_EMAIL_BUCKET or settings.OBJECT_STORAGE_BUCKET


def team_prefix(team_id: int) -> str:
    return f"inbound-email/teams/{team_id}/"


def email_prefix(team_id: int, email_id: UUID) -> str:
    return f"{team_prefix(team_id)}{email_id}/"


def raw_key(team_id: int, email_id: UUID) -> str:
    return f"{email_prefix(team_id, email_id)}raw.eml"


def content_key(team_id: int, email_id: UUID) -> str:
    return f"{email_prefix(team_id, email_id)}content.json"


def attachment_key(team_id: int, email_id: UUID, index: int) -> str:
    return f"{email_prefix(team_id, email_id)}attachments/{index}"


def write_message(team_id: int, email_id: UUID, raw: bytes, parsed: ParsedEmail | None) -> None:
    """The row is written after this, so a retry that finds no row rewrites the same keys."""
    object_storage.write(raw_key(team_id, email_id), raw, bucket=bucket())
    if parsed is None:
        return
    for attachment in parsed.attachments:
        object_storage.write(attachment_key(team_id, email_id, attachment.index), attachment.content, bucket=bucket())
    document: dict[str, Any] = {
        "text": parsed.text,
        "html": parsed.html,
        "reply_text": parsed.reply_text,
        "body_truncated": parsed.body_truncated,
        "headers": [asdict(header) for header in parsed.headers],
        "attachments_dropped": parsed.attachments_dropped,
        "attachments": [
            {
                "index": attachment.index,
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "size": attachment.size,
                "content_id": attachment.content_id,
                "inline": attachment.inline,
            }
            for attachment in parsed.attachments
        ],
    }
    object_storage.write(content_key(team_id, email_id), json.dumps(document), bucket=bucket())


def read_content(team_id: int, email_id: UUID) -> dict[str, Any] | None:
    document = object_storage.read(content_key(team_id, email_id), bucket=bucket(), missing_ok=True)
    return json.loads(document) if document else None


def download_link(key: str, filename: str) -> str | None:
    """Served as a download of opaque bytes, so a hostile HTML or SVG attachment can't run on the storage origin."""
    return object_storage.get_presigned_url(
        key,
        expiration=LINK_EXPIRY_SECONDS,
        content_type="application/octet-stream",
        content_disposition=f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
        bucket=bucket(),
    )


def delete_prefix(prefix: str) -> int:
    """Raises when an object survives, so callers keep the row that lets a later run find it again."""
    deleted = 0
    batch: list[str] = []
    for key in object_storage.iter_keys(prefix, bucket=bucket()):
        batch.append(key)
        if len(batch) == _DELETE_BATCH:
            deleted += _delete_batch(batch)
            batch = []
    return deleted + (_delete_batch(batch) if batch else 0)


def _delete_batch(keys: list[str]) -> int:
    failed = object_storage.delete_objects(keys, bucket=bucket())
    if failed:
        raise object_storage.ObjectStorageError(f"{len(failed)} inbound email objects were not deleted")
    return len(keys)
