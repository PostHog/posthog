from collections.abc import Collection
from datetime import datetime
from typing import Literal
from uuid import UUID

from django.db.models import QuerySet
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.storage import object_storage

from products.exports.backend.models.exported_asset import ExportedAsset

HEATMAP_HISTORY_PREFIX = "heatmap_screenshot_history/"


@frozen
class HeatmapHistoryImage:
    content: bytes
    expires_after: datetime


def _live_assets(team_id: int) -> QuerySet[ExportedAsset]:
    return ExportedAsset.objects_including_ttl_deleted.filter(
        team_id=team_id,
        is_system=True,
        content_location__startswith=HEATMAP_HISTORY_PREFIX,
        expires_after__gt=timezone.now(),
    )


def reserve_heatmap_history_asset(
    *, team_id: int, request_id: UUID, variant: Literal["full", "thumbnail"], expires_after: datetime
) -> int:
    asset = ExportedAsset.objects.create(
        team_id=team_id,
        is_system=True,
        export_format=ExportedAsset.ExportFormat.JPEG,
        expires_after=expires_after,
        content_location=f"{HEATMAP_HISTORY_PREFIX}team-{team_id}/{request_id}/{variant}.jpg",
        export_context={"heatmap_history_request_id": str(request_id), "variant": variant},
    )
    return asset.id


def get_heatmap_history_asset_expiries(*, team_id: int, asset_ids: Collection[int]) -> dict[int, datetime]:
    return {
        asset_id: expires_after
        for asset_id, expires_after in _live_assets(team_id).filter(id__in=asset_ids).values_list("id", "expires_after")
        if expires_after is not None
    }


def write_heatmap_history_asset(*, team_id: int, asset_id: int, content: bytes) -> None:
    asset = _live_assets(team_id).get(id=asset_id)
    assert asset.content_location is not None
    object_storage.write(asset.content_location, content, extras={"ContentType": "image/jpeg"})


def read_heatmap_history_asset(*, team_id: int, asset_id: int) -> HeatmapHistoryImage | None:
    asset = _live_assets(team_id).filter(id=asset_id).first()
    if asset is None or asset.expires_after is None:
        return None
    assert asset.content_location is not None
    content = object_storage.read_bytes(asset.content_location, missing_ok=True)
    return None if content is None else HeatmapHistoryImage(content=content, expires_after=asset.expires_after)


def expire_heatmap_history_assets(*, team_id: int, asset_ids: Collection[int]) -> None:
    _live_assets(team_id).filter(id__in=asset_ids).update(expires_after=timezone.now())
