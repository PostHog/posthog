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

import re
import logging
from datetime import timedelta

from django.utils import timezone

from pydantic import ValidationError

from posthog.dataclasses import frozen

from products.signals.backend.artefact_schemas import DISMISSAL_REASON_WRONG_REPO, Dismissal
from products.signals.backend.models import SignalReport, SignalReportArtefact

logger = logging.getLogger(__name__)

# Caps sized for a prompt block, not an archive. Wrong-repo corrections per project are rare (a
# handful over months), so the newest 20 inside a 180-day window cover the live mistakes without
# letting a long-retired repo layout steer selections forever.
MAX_CORRECTIONS = 20
CORRECTIONS_WINDOW = timedelta(days=180)
# Rows fetched (newest first) before Python-side verification. The SQL `content` prefilter below
# already narrows to wrong-repo rows, so this is a backstop against pathological volume, not the
# working limit.
_SCAN_CAP = 500
_MAX_TITLE_CHARS = 120
_MAX_NOTE_CHARS = 200

# Rendered repository names must look like 'owner/repo'. The state API validates its input the
# same way, but dismissal and repo_selection artefacts are also writable through the artefacts
# POST API with no format constraint, and these values land in a prompt where a newline could
# fake extra list entries. Anything else renders as "unrecorded".
_REPO_SHAPE_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
_MAX_REPO_CHARS = 140

# `content` is compact JSON written by pydantic's model_dump_json, so a wrong_repo dismissal
# always contains this exact substring (values with quotes are escaped, so a note can only
# false-positive into the scan, where the typed parse below re-checks the reason). Also used by the
# report-persist guard (`_reviewer_selection_written_since`) to detect a mid-run correction.
WRONG_REPO_CONTENT_NEEDLE = f'"reason":"{DISMISSAL_REASON_WRONG_REPO}"'


@frozen
class RepoCorrection:
    """One wrong-repo dismissal, flattened for prompt rendering."""

    report_title: str | None
    selected_repository: str | None
    corrected_repository: str | None
    note: str | None
    dismissed_on: str


def recent_wrong_repo_corrections(team_id: int) -> list[RepoCorrection]:
    """The team's recent wrong-repo dismissals, newest first, deduplicated.

    One entry per report, and one entry per distinct (selected, corrected) lesson: a bulk
    dismissal applies the same correction to every selected report, and without the lesson
    dedupe one sweep would fill the whole block with copies of a single lesson and evict the
    older, distinct ones.
    """
    cutoff = timezone.now() - CORRECTIONS_WINDOW
    rows = (
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            type=SignalReportArtefact.ArtefactType.DISMISSAL,
            created_at__gte=cutoff,
            content__contains=WRONG_REPO_CONTENT_NEEDLE,
        )
        # Report deletion is a status flip, not a row delete, and every other read path stops
        # serving a deleted report's content. A deleted report's title and reviewer note must
        # not keep reaching the selection prompt either.
        .exclude(report__status=SignalReport.Status.DELETED)
        .order_by("-created_at")
        .values_list("report_id", "content", "created_at", named=True)[:_SCAN_CAP]
    )

    kept: list[tuple[str, Dismissal, str]] = []
    seen_reports: set[str] = set()
    seen_lessons: set[tuple[str | None, str | None]] = set()
    for artefact in rows:
        try:
            content = Dismissal.model_validate_json(artefact.content)
        except ValidationError:
            continue
        if content.reason != DISMISSAL_REASON_WRONG_REPO:
            continue
        report_id = str(artefact.report_id)
        lesson = (sanitized_repository(content.selected_repository), sanitized_repository(content.corrected_repository))
        if report_id in seen_reports or lesson in seen_lessons:
            continue
        seen_reports.add(report_id)
        seen_lessons.add(lesson)
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
            selected_repository=sanitized_repository(content.selected_repository),
            corrected_repository=sanitized_repository(content.corrected_repository),
            note=_clean(content.note),
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


def sanitized_repository(value: str | None) -> str | None:
    """An 'owner/repo' value safe to render into a prompt, or None when it fails the shape check.

    Shared by every path that renders a stored repository field into an LLM prompt, so the
    shape gate has one definition. Lowercased to match the candidate list the selection agent
    sees. The state API already lowercases and shape-checks on write, but dismissal and
    repo_selection artefacts are also writable through the generic artefacts POST API with no
    format constraint, and these values land in a prompt where a newline could fake extra list
    entries or a fabricated section.
    """
    cleaned = (value or "").strip().lower()
    if not cleaned or len(cleaned) > _MAX_REPO_CHARS or not _REPO_SHAPE_RE.match(cleaned):
        return None
    return cleaned


def _clean(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _excerpt(value: str | None, limit: int) -> str:
    # One line per correction: reviewer text is untrusted prompt input, and newlines would let a
    # note masquerade as new list entries or a new prompt section.
    flattened = " ".join((value or "").split())
    return flattened[:limit] + ("…" if len(flattened) > limit else "")
