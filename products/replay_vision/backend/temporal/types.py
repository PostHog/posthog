from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApplyLensInputs(BaseModel):
    """Input to ApplyLensWorkflow — one lens applied to one session. The workflow creates its own observation row."""

    model_config = ConfigDict(frozen=True)

    lens_id: UUID
    session_id: str
    team_id: int
    user_id: int | None = Field(default=None, description="User who triggered on-demand; None for scheduled.")
    triggered_by: str = Field(description="`schedule` or `on_demand` — recorded on the observation row.")


class PrepSessionVideoAssetResult(BaseModel):
    """Result of prep_session_video_asset_activity."""

    model_config = ConfigDict(frozen=True)

    asset_id: int
    team_api_token: str
    team_name: str


class UploadedVideo(BaseModel):
    """Reference to a video uploaded to Gemini for lens application."""

    model_config = ConfigDict(frozen=True)

    file_uri: str
    gemini_file_name: str = Field(description="Gemini file identifier for deletion (e.g. 'files/abc123').")
    mime_type: str
    duration: int = Field(description="Duration in seconds.")


class UploadVideoToGeminiOutput(BaseModel):
    """Result of upload_video_to_gemini_activity."""

    model_config = ConfigDict(frozen=True)

    uploaded_video: UploadedVideo
    inactivity_periods: list[dict[str, Any]] | None = Field(
        default=None,
        description="ReplayInactivityPeriod model_dump()s, used by the workflow to slice segments.",
    )


class VisionVideoSegmentSpec(BaseModel):
    """A time slice of the uploaded video to feed to one Gemini call."""

    model_config = ConfigDict(frozen=True)

    segment_index: int
    recording_start_time: float = Field(description="Seconds from start of video.")
    recording_end_time: float = Field(description="Seconds from start of video.")

    @model_validator(mode="after")
    def _validate_range(self) -> "VisionVideoSegmentSpec":
        if self.recording_end_time <= self.recording_start_time:
            raise ValueError("recording_end_time must be greater than recording_start_time")
        return self


class SegmentLensOutput(BaseModel):
    """Wrapper around a single lens-type-specific segment output, carried through the workflow."""

    model_config = ConfigDict(frozen=True)

    segment_index: int
    output_json: str = Field(description="JSON-serialized SegmentOutput model from the lens implementation.")


class FinalLensOutput(BaseModel):
    """Wrapper around the consolidated lens output, carried into the terminal emit activity."""

    model_config = ConfigDict(frozen=True)

    output_json: str = Field(description="JSON-serialized FinalOutput model from the lens implementation.")
    confidence: float = Field(ge=0.0, le=1.0)
    extra: dict[str, Any] = Field(default_factory=dict, description="Top-level extras to stamp on the event payload.")
