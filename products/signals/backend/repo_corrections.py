"""Feeding wrong-repo dismissal corrections back into repository selection.

When someone dismisses a report with the `wrong_repo` reason, the dismissal artefact records
which repository the pipeline had selected and (when given) which one the reviewer said it
should have been. This module turns a project's recent record of those mistakes into a rendered
prompt block that `select_repository_for_team` passes to the selection agent, so a correction a
reviewer made once is in front of the agent on every later selection for that project.

Rendering is caller-side by design: the selection agent's SQL surface is deliberately limited to
`system.integration_repository_cache`, and a block injected by the caller is guaranteed seen,
whereas a lookup the agent may choose to run is guaranteed nothing.

Best-effort by contract: selection must not fail because feedback rendering broke, so the block
builder catches everything and returns None on failure.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.utils import timezone

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReport, SignalReportArtefact

logger = logging.getLogger(__name__)

# Caps sized for a prompt block, not an archive. Wrong-repo corrections per project are rare (a
# handful over months), so the newest 20 inside a 180-day window cover the live mistakes without
# letting a long-retired repo layout steer selections forever.
MAX_CORRECTIONS = 20
CORRECTIONS_WINDOW = timedelta(days=180)
# Dismissal artefacts scanned newest-first before Python-side reason filtering. `content` is a
# JSON text column, so the reason code cannot be filtered in SQL.
_SCAN_CAP = 500
_MAX_TITLE_CHARS = 120
_MAX_NOTE_CHARS = 200

_WRONG_REPO_REASON = "wrong_repo"


@frozen
class RepoCorrection:
    """One wrong-repo dismissal, flattened for prompt rendering."""

    report_title: str | None
    selected_repository: str | None
    corrected_repository: str | None
    note: str | None
    dismissed_on: str


def recent_wrong_repo_corrections(team_id: int) -> list[RepoCorrection]:
    """The team's recent wrong-repo dismissals, newest first, one per report.

    One dismissal per report: a report dismissed twice as wrong-repo teaches the same lesson
    twice, and the newest entry carries the freshest correction.
    """
    cutoff = timezone.now() - CORRECTIONS_WINDOW
    rows = (
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            type=SignalReportArtefact.ArtefactType.DISMISSAL,
            created_at__gte=cutoff,
        )
        .order_by("-created_at")
        .values_list("report_id", "content", "created_at", named=True)[:_SCAN_CAP]
    )

    kept: list[tuple[str, dict, str]] = []
    seen_reports: set[str] = set()
    for artefact in rows:
        try:
            content = json.loads(artefact.content)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(content, dict) or content.get("reason") != _WRONG_REPO_REASON:
            continue
        report_id = str(artefact.report_id)
        if report_id in seen_reports:
            continue
        seen_reports.add(report_id)
        kept.append((report_id, content, artefact.created_at.date().isoformat()))
        if len(kept) >= MAX_CORRECTIONS:
            break

    if not kept:
        return []

    titles = {
        str(report_id): title
        for report_id, title in SignalReport.objects.filter(
            team_id=team_id, id__in=[report_id for report_id, _, _ in kept]
        ).values_list("id", "title")
    }
    return [
        RepoCorrection(
            report_title=titles.get(report_id),
            selected_repository=_clean(content.get("selected_repository")),
            corrected_repository=_clean(content.get("corrected_repository")),
            note=_clean(content.get("note")),
            dismissed_on=dismissed_on,
        )
        for report_id, content, dismissed_on in kept
    ]


def wrong_repo_corrections_block(team_id: int) -> str | None:
    """Rendered prompt lines of the team's past wrong-repo corrections, or None when there are none."""
    try:
        corrections = recent_wrong_repo_corrections(team_id)
    except Exception:
        logger.exception("Failed to build repo-selection corrections block", extra={"team_id": team_id})
        return None
    if not corrections:
        return None
    return "\n".join(_render(correction) for correction in corrections)


def _render(correction: RepoCorrection) -> str:
    selected = f"`{correction.selected_repository}`" if correction.selected_repository else "an unrecorded repository"
    verdict = (
        f"a reviewer dismissed it as the wrong repository and named `{correction.corrected_repository}` instead"
        if correction.corrected_repository
        else "a reviewer dismissed it as the wrong repository (no correct repository named)"
    )
    title_clause = f' about "{_excerpt(correction.report_title, _MAX_TITLE_CHARS)}"' if correction.report_title else ""
    note_clause = f' Reviewer note: "{_excerpt(correction.note, _MAX_NOTE_CHARS)}"' if correction.note else ""
    return f"- {correction.dismissed_on}: a report{title_clause} selected {selected}; {verdict}.{note_clause}"


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _excerpt(value: str | None, limit: int) -> str:
    # One line per correction: reviewer text is untrusted prompt input, and newlines would let a
    # note masquerade as new list entries or a new prompt section.
    flattened = " ".join((value or "").split())
    return flattened[:limit] + ("…" if len(flattened) > limit else "")
