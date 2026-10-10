from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from django.db import transaction

import structlog

from posthog.storage import object_storage

logger = structlog.get_logger(__name__)

HEATMAP_HISTORY_PREFIX = "heatmap_screenshot_history"
Variant = Literal["full", "thumbnail"]
VARIANTS: tuple[Variant, ...] = ("full", "thumbnail")


def image_key(team_id: int, request_id: UUID, variant: Variant) -> str:
    return f"{HEATMAP_HISTORY_PREFIX}/team-{team_id}/{request_id}/{variant}.jpg"


def write_image(team_id: int, request_id: UUID, variant: Variant, content: bytes) -> None:
    object_storage.write(image_key(team_id, request_id, variant), content, extras={"ContentType": "image/jpeg"})


def read_image(team_id: int, request_id: UUID, variant: Variant) -> bytes | None:
    return object_storage.read_bytes(image_key(team_id, request_id, variant), missing_ok=True)


def delete_images_now(team_id: int, request_ids: Iterable[UUID]) -> set[UUID]:
    keys = {image_key(team_id, request_id, variant): request_id for request_id in request_ids for variant in VARIANTS}
    if not keys:
        return set()
    try:
        failed = object_storage.delete_objects(list(keys))
    except Exception:
        logger.warning("heatmap_history.image_delete_failed", team_id=team_id, exc_info=True)
        return set(keys.values())
    return {keys[key] for key in failed if key in keys}


def delete_images_on_commit(team_id: int, request_ids: Iterable[UUID]) -> None:
    pending = list(request_ids)
    if pending:
        transaction.on_commit(lambda: delete_images_now(team_id, pending))
