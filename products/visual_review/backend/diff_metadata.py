"""Schema for the system-computed `diff_metadata` JSON column on RunSnapshot.

This file is the single source of truth for what the diff pipeline can
write into that column. Storage is JSONB so the DB itself enforces nothing;
correctness comes from routing every write through `DiffMetadata.model_dump`
and every read through `DiffMetadata.model_validate`. Adding a new key
later means adding a field with a default — old rows still validate, new
rows populate it.

Kept separate from `facade/contracts.py` (which is dataclass-based, public
API contracts) because this is internal storage shape, not a public DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DiffCluster(BaseModel):
    """One connected region of differing pixels in a snapshot diff."""

    model_config = ConfigDict(frozen=True)

    bbox: tuple[int, int, int, int] = Field(description="(x, y, width, height) in image coordinates")
    px: int = Field(ge=0, description="Total differing pixels in this cluster")
    centroid: tuple[float, float] = Field(description="(x, y) center of mass in image coordinates")


class ClusterSummary(BaseModel):
    """Spatial clustering of differing pixels for a single diff.

    `total` counts all clusters that passed the lib's lower-bound filters
    (pixel count + bbox dimensions + dilation merge); `items` may be a
    truncated top-N by pixel_count when `truncated` is True. Frontend uses
    `total` to label scattered diffs differently from localized ones even
    when only the top items are shipped.
    """

    model_config = ConfigDict(frozen=True)

    items: list[DiffCluster]
    total: int = Field(ge=0)
    truncated: bool


class DiffMetadata(BaseModel):
    """Container for everything the diff pipeline writes into the
    `diff_metadata` JSONB column.

    Empty (`{}`) for snapshots that haven't been diffed yet, or for
    snapshots where the pipeline produced nothing storable here. New keys
    land as new fields with defaults so old rows still validate.
    """

    model_config = ConfigDict(extra="ignore")  # forward-compat: ignore unknown keys on read

    cluster_summary: ClusterSummary | None = None
    size_mismatch: bool = False  # baseline and current had different dimensions; pixelhog padded to largest
