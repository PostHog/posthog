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

from typing import Literal

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


class ShiftBand(BaseModel):
    """One run of rows the current image gained or lost.

    A deleted band has no rows of its own in the current image; `y` is the
    seam the removed rows left behind and `rows` counts what went away.
    """

    model_config = ConfigDict(frozen=True)

    y: int = Field(ge=0, description="First row of the band, in current-image coordinates")
    rows: int = Field(ge=0, description="How many rows the band covers")
    kind: Literal["inserted", "deleted"]


class RowShift(BaseModel):
    """A vertical shift between baseline and current, separated from the real change.

    Row alignment pairs the rows that exist in both images, so the pixels
    below an inserted row stop counting as differences. `residual_*` is what
    is left after that pairing, which is the number the classifier thresholds
    on. `raw_diff_percentage` keeps what the same pair measured without
    alignment, so the UI can say what the shift would have cost.
    """

    model_config = ConfigDict(frozen=True)

    inserted_rows: int = Field(ge=0)
    deleted_rows: int = Field(ge=0)
    changed_rows: int = Field(ge=0)
    residual_pixel_count: int = Field(ge=0)
    # Inserted rows whose pixels equal a deleted row's: content that moved
    # somewhere else on the page, not padding that appeared. Every inserted
    # row when the image was too big to check. Zero on rows written before
    # this field existed.
    relocated_rows: int = Field(ge=0, default=0)
    residual_percentage: float
    raw_diff_percentage: float
    bands: list[ShiftBand]

    @property
    def shifted_rows(self) -> int:
        """How far the rows moved. What the absorb cap judges.

        A page that grew has only inserts and one that shrank has only deletes.
        A same-height translation shows up as both, so the larger side is the
        movement, not the sum.
        """
        return max(self.inserted_rows, self.deleted_rows)


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
    # Present whenever row alignment succeeded, including on snapshots the
    # classifier absorbed as noise. An absorbed row keeps its shift here so
    # the UI can show what moved instead of showing nothing.
    row_shift: RowShift | None = None
