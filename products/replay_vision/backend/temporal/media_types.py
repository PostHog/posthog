"""Types for the observation media workflow: a thumbnail per succeeded observation, plus a frame per summary chapter."""

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field

# The footer height of analysis videos rendered before the rasterizer reported it as `footer_height_px`.
LEGACY_ANALYSIS_FOOTER_HEIGHT_PX = 32

THUMBNAIL_WIDTH_PX = 1280

# Far enough in to clear the loading screen a session opens on.
FALLBACK_THUMBNAIL_FRACTION = 0.25


MEDIA_WORKFLOW_NAME = "replay-vision-media"

# Bounds the frame render's retry chain, queue wait included.
THUMBNAIL_SCHEDULE_TO_CLOSE = dt.timedelta(hours=6)
# Past the retry chain, so a stuck render fails its own activity rather than the whole child.
MEDIA_WORKFLOW_EXECUTION_TIMEOUT = THUMBNAIL_SCHEDULE_TO_CLOSE + dt.timedelta(minutes=30)


def build_media_workflow_id(observation_id: UUID) -> str:
    """One id per observation, so a retried scan cannot start a second render beside one still running."""
    return f"{MEDIA_WORKFLOW_NAME}-{observation_id}"


class ObservationMediaInputs(BaseModel, frozen=True):
    """Input to ObservationMediaWorkflow, started fail-soft once an observation has succeeded."""

    team_id: int
    observation_id: UUID
    session_id: str
    analysis_asset_id: int
    # Video-time seconds, used to pick a moment when the model cited none.
    signal_video_times: list[tuple[int, int]] = Field(default_factory=list)
    thumbnail_video_s: int | None = None


class ExtractThumbnailsFrame(BaseModel, frozen=True):
    video_time_s: float
    id: str
    # A required frame fails the batch when it cannot be cut; any other frame is left out instead.
    required: bool


class ExtractThumbnailsActivityInput(BaseModel, frozen=True):
    """Input sent to the Node.js `extract-thumbnails` activity; field names match its TypeScript interface."""

    source_s3_uri: str
    frames: list[ExtractThumbnailsFrame]
    footer_crop_px: int
    width: int
    s3_bucket: str
    s3_key_prefix: str


class ExtractedFrame(BaseModel, frozen=True):
    id: str
    s3_uri: str
    file_size_bytes: int


class ExtractThumbnailsActivityOutput(BaseModel, frozen=True):
    frames: list[ExtractedFrame] = Field(default_factory=list)


class PreparedFrame(BaseModel, frozen=True):
    """One media slot the render fills: the observation's thumbnail, or one summary chapter's frame."""

    kind: str
    position: int
    media_asset_id: int
    object_id: str
    video_start_ms: int
    rec_start_ms: int | None


class PrepareObservationMediaOutput(BaseModel, frozen=True):
    frames: list[PreparedFrame]
    activity_input: ExtractThumbnailsActivityInput


class FinalizeObservationMediaInputs(BaseModel, frozen=True):
    team_id: int
    observation_id: UUID
    frames: list[PreparedFrame]
    result: ExtractThumbnailsActivityOutput
