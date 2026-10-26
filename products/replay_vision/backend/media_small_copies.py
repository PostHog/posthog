"""The small copy of an observation frame that list views load, scaled from the large PNG already stored.

New renders and the backfill both make it from the stored frame: the backfill cannot cut a new one, because the
analysis video expires long before the frame does.
"""

import io

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils.timezone import now

import structlog
from PIL import Image

from posthog.dataclasses import frozen
from posthog.storage import object_storage

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia

logger = structlog.get_logger(__name__)

# Twice the widest list cell, so the small copy stays sharp on a high-density screen.
SMALL_COPY_WIDTH_PX = 480
# Lossy WebP, because a phone-width frame is already under the width and a PNG of it saves nothing.
SMALL_COPY_FORMAT = ExportedAsset.ExportFormat.WEBP
_WEBP_QUALITY = 80


def shrink_frame(content: bytes) -> bytes:
    """Encode a PNG frame as the small copy: at most the small width, an even height, never upscaled."""
    with Image.open(io.BytesIO(content)) as source:
        image: Image.Image = source.convert("RGB")
        if image.width > SMALL_COPY_WIDTH_PX:
            height = max(2, round(image.height * SMALL_COPY_WIDTH_PX / image.width / 2) * 2)
            image = image.resize((SMALL_COPY_WIDTH_PX, height), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="WEBP", quality=_WEBP_QUALITY)
    return out.getvalue()


def small_copy_location(large_location: str) -> str | None:
    # A fixed name beside the large object, so a retry overwrites rather than leaks.
    return f"{large_location.removesuffix('.png')}-small.webp" if large_location.endswith(".png") else None


def write_small_copy(large_location: str) -> str | None:
    """Store the small copy next to the large frame and return its location, or None when the frame is unreadable."""
    small_location = small_copy_location(large_location)
    if small_location is None:
        return None
    content = object_storage.read_bytes(large_location, missing_ok=True)
    if not content:
        return None
    object_storage.write(small_location, shrink_frame(content))
    return small_location


@frozen
class SmallCopyBackfillResult:
    candidates: int
    created: int
    failed: int


def teams_missing_small_copies() -> list[int]:
    return sorted(
        ReplayObservationMedia.objects.unscoped()
        .filter(small_asset__isnull=True)
        .values_list("team_id", flat=True)
        .distinct()
    )


def media_missing_small_copies(team_id: int, limit: int | None = None) -> QuerySet[ReplayObservationMedia]:
    # A frame that is not rendered or has expired would never be served, so it gets no copy either.
    queryset = (
        ReplayObservationMedia.objects.for_team(team_id, canonical=True)
        .filter(small_asset__isnull=True, asset__content_location__isnull=False)
        .filter(Q(asset__expires_after__isnull=True) | Q(asset__expires_after__gt=now()))
        .select_related("asset")
        .order_by("id")
    )
    return queryset[:limit] if limit is not None else queryset


def backfill_small_copies(team_id: int, limit: int | None = None) -> SmallCopyBackfillResult:
    created = failed = total = 0
    for media in media_missing_small_copies(team_id, limit).iterator(chunk_size=200):
        total += 1
        try:
            created += _add_small_copy(team_id, media)
        except Exception as error:
            # One unreadable frame must not stop the rest of the team.
            failed += 1
            logger.warning("replay_vision.small_copy_backfill_failed", media_id=str(media.id), error=str(error))
    return SmallCopyBackfillResult(candidates=total, created=created, failed=failed)


def _add_small_copy(team_id: int, media: ReplayObservationMedia) -> bool:
    large = media.asset
    small_location = write_small_copy(large.content_location or "")
    if small_location is None:
        return False
    with transaction.atomic():
        # Locked first, so a losing run creates no row whose expiry would delete the shared object.
        locked = (
            ReplayObservationMedia.objects.for_team(team_id, canonical=True)
            .select_for_update(of=("self",))
            .filter(pk=media.pk)
            .select_related("small_asset")
            .first()
        )
        linked = locked.small_asset if locked is not None else None
        if locked is None or linked is not None:
            # Gone, or linked by another writer: the object is ours alone unless that writer stored the same key.
            if linked is None or linked.content_location != small_location:
                object_storage.delete(small_location)
            return False
        small = ExportedAsset.objects.create(
            team_id=large.team_id,
            export_format=SMALL_COPY_FORMAT,
            export_context=large.export_context,
            content_location=small_location,
            expires_after=large.expires_after,
            is_system=True,
        )
        ReplayObservationMedia.objects.for_team(team_id, canonical=True).filter(pk=media.pk).update(small_asset=small)
    return True
