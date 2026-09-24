"""Types for the observation media workflow: one thumbnail per succeeded observation."""

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field

# Matches `footerHeight` in common/replay-headless/src/standalone-player.ts.
ANALYSIS_FOOTER_HEIGHT_PX = 32

THUMBNAIL_WIDTH_PX = 1280

# Far enough in to clear the loading screen a session opens on.
FALLBACK_THUMBNAIL_FRACTION = 0.25


MEDIA_WORKFLOW_NAME = "replay-vision-media"

# Bounds the thumbnail's retry chain, queue wait included.
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


class ExtractThumbnailActivityInput(BaseModel, frozen=True):
    """Input sent to the Node.js `extract-thumbnail` activity; field names match its TypeScript interface."""

    source_s3_uri: str
    video_time_s: float
    footer_crop_px: int = ANALYSIS_FOOTER_HEIGHT_PX
    width: int = THUMBNAIL_WIDTH_PX
    s3_bucket: str
    s3_key_prefix: str
    id: str


class ExtractThumbnailActivityOutput(BaseModel, frozen=True):
    s3_uri: str
    file_size_bytes: int = 0


class PrepareObservationThumbnailOutput(BaseModel, frozen=True):
    media_asset_id: int
    activity_input: ExtractThumbnailActivityInput
    video_start_ms: int
    rec_start_ms: int | None


class FinalizeObservationThumbnailInputs(BaseModel, frozen=True):
    team_id: int
    observation_id: UUID
    media_asset_id: int
    video_start_ms: int
    rec_start_ms: int | None
    result: ExtractThumbnailActivityOutput
