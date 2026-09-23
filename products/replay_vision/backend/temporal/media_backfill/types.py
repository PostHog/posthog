from uuid import UUID

from pydantic import BaseModel


class MediaBackfillInputs(BaseModel, frozen=True):
    """Input to ReplayVisionMediaBackfillWorkflow. The schedule passes none of it."""

    # Overrides the per-tick cap, for a one-off manual run.
    limit: int | None = None


class MediaBackfillCandidate(BaseModel, frozen=True):
    """One observation that has no media and whose analysis video is still stored."""

    team_id: int
    observation_id: UUID
    session_id: str
    analysis_asset_id: int


class FindMediaBackfillCandidatesOutput(BaseModel, frozen=True):
    candidates: list[MediaBackfillCandidate] = []
    # Observations that looked eligible until their analysis video turned out to be gone.
    without_video: int = 0
    # Observations whose render was tried recently and is waiting out its cooldown.
    cooling_off: int = 0
