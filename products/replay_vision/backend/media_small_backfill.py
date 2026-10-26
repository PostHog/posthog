"""Give media rendered before small copies existed a small copy, scaled from the large PNG already stored.

It reads the large frame rather than cutting a new one from the analysis video, because that video expires long
before the frame does.
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
from products.replay_vision.backend.temporal.media_types import SMALL_THUMBNAIL_WIDTH_PX

logger = structlog.get_logger(__name__)


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


def shrink_png(content: bytes, width: int = SMALL_THUMBNAIL_WIDTH_PX) -> bytes:
    """Scale a PNG to `width` with an even height, the way the rasterizer's ffmpeg filter does, and never upscale."""
    with Image.open(io.BytesIO(content)) as image:
        if image.width > width:
            height = max(2, round(image.height * width / image.width / 2) * 2)
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="PNG")
    return out.getvalue()


class SmallCopyBackfill:
    def __init__(self, team_id: int, *, limit: int | None = None) -> None:
        self.team_id = team_id
        self.limit = limit

    def candidates(self) -> QuerySet[ReplayObservationMedia]:
        # A frame that is not rendered or has expired would never be served, so it gets no copy either.
        queryset = (
            ReplayObservationMedia.objects.for_team(self.team_id, canonical=True)
            .filter(small_asset__isnull=True, asset__content_location__isnull=False)
            .filter(Q(asset__expires_after__isnull=True) | Q(asset__expires_after__gt=now()))
            .select_related("asset")
            .order_by("id")
        )
        return queryset[: self.limit] if self.limit is not None else queryset

    def run(self, *, dry_run: bool) -> SmallCopyBackfillResult:
        candidates = self.candidates()
        if dry_run:
            return SmallCopyBackfillResult(candidates=candidates.count(), created=0, failed=0)
        created = failed = total = 0
        for media in candidates.iterator(chunk_size=200):
            total += 1
            try:
                created += self._add_small_copy(media)
            except Exception as error:
                # One unreadable frame must not stop the rest of the team.
                failed += 1
                logger.warning("replay_vision.small_copy_backfill_failed", media_id=str(media.id), error=str(error))
        return SmallCopyBackfillResult(candidates=total, created=created, failed=failed)

    def _add_small_copy(self, media: ReplayObservationMedia) -> bool:
        large = media.asset
        location = large.content_location or ""
        if not location.endswith(".png"):
            return False
        content = object_storage.read_bytes(location, missing_ok=True)
        if not content:
            return False
        # Next to the large object, named as a fresh render names its copy, so a rerun overwrites rather than leaks.
        small_location = f"{location.removesuffix('.png')}-small.png"
        object_storage.write(small_location, shrink_png(content))

        with transaction.atomic():
            small = ExportedAsset.objects.create(
                team_id=large.team_id,
                export_format=ExportedAsset.ExportFormat.PNG,
                export_context={**(large.export_context or {}), "media_size": ReplayObservationMedia.Size.SMALL.value},
                content_location=small_location,
                expires_after=large.expires_after,
                is_system=True,
            )
            linked = (
                ReplayObservationMedia.objects.for_team(self.team_id, canonical=True)
                .filter(pk=media.pk, small_asset__isnull=True)
                .update(small_asset=small)
            )
            if not linked:
                # A render landed a copy of its own since the read, so this one has nothing pointing at it.
                ExportedAsset.objects.filter(pk=small.pk).update(expires_after=now())
        return bool(linked)
