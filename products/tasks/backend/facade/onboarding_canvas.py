"""Bridge to the canvas product's teaching-tour seeding.

The tour itself (source, publish, get-or-seed semantics) lives in
``products.canvas.backend.teaching``, tach-exposed for this import; this module
adapts it to the shape the onboarding brief carries. Seeding runs synchronously
in the sign-in path so the session's followup can point at the canvas by id.
"""

from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.canvas.backend.teaching import (
    TEACHING_CANVAS_NAME as TEACHING_CANVAS_NAME,
    seed_teaching_canvas,
)


@frozen
class TeachingCanvas:
    channel_id: UUID
    canvas_id: UUID


def ensure_teaching_canvas(
    team_id: int, channel_id: UUID, user: User, *, refresh: bool = False
) -> TeachingCanvas | None:
    canvas_id = seed_teaching_canvas(team_id=team_id, channel_id=channel_id, user=user, refresh=refresh)
    if canvas_id is None:
        return None
    return TeachingCanvas(channel_id=channel_id, canvas_id=canvas_id)
