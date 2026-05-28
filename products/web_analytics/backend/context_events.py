from datetime import datetime
from typing import Any

import structlog

from posthog.models import Team
from posthog.models.annotation import Annotation

logger = structlog.get_logger(__name__)


MAX_CONTEXT_EVENTS = 5
ANNOTATION_PREVIEW_CHARS = 140


def _preview(content: str | None) -> str:
    if not content:
        return ""
    stripped = content.strip()
    if len(stripped) <= ANNOTATION_PREVIEW_CHARS:
        return stripped
    return stripped[: ANNOTATION_PREVIEW_CHARS - 1].rstrip() + "…"


def gather_context_events(
    team: Team, date_from: datetime, date_to: datetime, limit: int = MAX_CONTEXT_EVENTS
) -> list[dict[str, Any]]:
    """Collect a small ranked list of project events within the digest window for the AI summary prompt.

    Events are purely additive context; on any internal failure this returns an empty list so summary
    generation can still proceed. Sourced from manual annotations — the lowest-risk, highest-signal
    timeline markers.
    """
    try:
        rows = Annotation.objects.filter(
            team_id=team.pk,
            deleted=False,
            date_marker__gte=date_from,
            date_marker__lte=date_to,
        ).order_by("-date_marker")[:limit]
    except Exception:
        logger.exception("failed to load annotations for context events", team_id=team.pk)
        return []

    events: list[dict[str, Any]] = []
    for row in rows:
        preview = _preview(row.content)
        if not preview:
            continue
        events.append(
            {
                "kind": "annotation",
                "name": preview,
                "date": row.date_marker.isoformat() if row.date_marker else None,
                "summary": "manual annotation",
            }
        )
    return events
