"""Forwarding of inbox report feedback into the scout steering channel.

The report body ends with a thumbs rating ("Was this report useful?"). Someone who rates a report
can also leave a note saying what was useful or off. That note is high-signal — a human telling the
scout that filed the report whether the thing it surfaced landed, and why — but until now it only
became a product-analytics event, which no scout ever reads. This module closes that gap the same
way `dismissal_notes.py` and `discussion_notes.py` do: it also leaves the note as a `SignalScoutNote`,
which every run reads by name at cold start (`scout-notes-list`).

Only forwarded when the report has a resolvable authoring scout (`resolve_report_scout_skill` returns
a live skill): feedback is a verdict on one scout's own report, so a note with no scout to address
would be fleet-wide noise. The bare thumb never forwards — only a rating carrying a note does, since
the note is the part a scout can act on.

Authorization mirrors `discussion_notes`, not `dismissal_notes`: the feedback text has no second path
to a run (a dismissal's does, through the `dismissal_note` field on the reports API), so this note is
its sole carrier and the full notes-write gate applies — `principal_may_steer_scouts` (canonical-project
access, the `llm_skill` editor bar, and the token's `scoped_teams`) plus the `signal_scout:write` /
`llm_skill:write` key scopes. Forwarding runs against the canonical project whose scouts read the row,
and only when the feedback landed on the canonical team itself, so a child environment's note never
reaches the parent project's readers. Best-effort by contract: the rating and its note already exist as
an analytics event, so a failure here must never surface to the user.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from django.utils import timezone

from posthog.models import Team, User

from products.signals.backend.dismissal_notes import (
    DERIVED_NOTE_TTL,
    principal_may_steer_scouts,
    resolve_report_scout_skill,
)
from products.signals.backend.models import SignalReport, SignalScoutNote
from products.signals.backend.scout_harness.tools.notes import leave_note

logger = logging.getLogger(__name__)

# Report titles are unbounded TextFields; a note references them for recognition only.
_MAX_TITLE_CHARS = 200
# The note is quoted into a scout note capped at MAX_NOTE_CONTENT_LENGTH. The feedback box caps input
# well below this, so the truncation only bites on a hand-crafted request — where losing the tail of a
# note beats losing the whole note to an oversize rejection.
_MAX_NOTE_CHARS = 4_000

# The scopes the notes API demands of a token writing a note by hand, which this path forwards under.
_REQUIRED_NOTE_SCOPES = ("signal_scout:write", "llm_skill:write")

# How each rating reads in the note. Kept to the two the thumbs can produce; an unknown sentiment
# drops the report rather than guess a verdict.
_SENTIMENT_VERBS = {
    "positive": "found useful",
    "negative": "did not find useful",
}


def forward_feedback_note(
    *,
    team: Team,
    report_id: str,
    sentiment: str,
    note: str,
    user_id: int | None,
    scoped_team_ids: Sequence[int] | None,
    api_scopes: Sequence[str] | None,
) -> str | None:
    """Leave a report's feedback note as a scout note. Returns the created note id, or None if
    nothing was forwarded.

    `scoped_team_ids` and `api_scopes` describe the calling credential (both None for session auth);
    the caller reads them off the request so this stays independent of HTTP.

    Best-effort by contract: the rating and note already exist as an analytics event, so nothing here
    may turn a successful feedback submission into a 5xx. Every step past this point runs inside one
    failure boundary, because authorization and target resolution both read the database.
    """
    if not note or not note.strip():
        return None
    try:
        return _forward(
            team=team,
            report_id=str(report_id),
            sentiment=sentiment,
            note=note.strip(),
            user_id=user_id,
            scoped_team_ids=scoped_team_ids,
            api_scopes=api_scopes,
        )
    except Exception:
        logger.exception(
            "Failed to forward report feedback to a scout note",
            extra={"team_id": team.id, "report_id": report_id},
        )
        return None


def _forward(
    *,
    team: Team,
    report_id: str,
    sentiment: str,
    note: str,
    user_id: int | None,
    scoped_team_ids: Sequence[int] | None,
    api_scopes: Sequence[str] | None,
) -> str | None:
    verb = _SENTIMENT_VERBS.get(sentiment)
    if verb is None:
        return None

    # Scout rows and their notes live under the canonical parent team; forwarding a child
    # environment's feedback would hand its report id, title, and note to an audience that may
    # have no access to that environment. Those stay on the analytics event only.
    canonical_team = team.parent_team or team
    if team.id != canonical_team.id:
        return None

    if not _may_write_note(
        user_id=user_id, scoped_team_ids=scoped_team_ids, api_scopes=api_scopes, team=canonical_team
    ):
        return None

    # Feedback is a verdict on one scout's own report. With no authoring scout to address (a
    # pipeline report, or one whose scout's skill was deleted) there is no one to steer, so the
    # note would be fleet-wide noise — skip rather than broadcast.
    skill_name = resolve_report_scout_skill(canonical_team.id, report_id)
    if not skill_name:
        return None

    report = SignalReport.objects.filter(team_id=canonical_team.id, id=report_id).first()
    if report is None:
        return None

    content = _build_note_content(report=report, verb=verb, note=note)
    created = leave_note(
        team_id=canonical_team.id,
        content=content,
        skill_name=skill_name,
        created_by_id=user_id,
        expires_at=timezone.now() + DERIVED_NOTE_TTL,
        origin=SignalScoutNote.Origin.REPORT_FEEDBACK,
    )
    return created.id


def _may_write_note(
    *, user_id: int | None, scoped_team_ids: Sequence[int] | None, api_scopes: Sequence[str] | None, team: Team
) -> bool:
    """Whether this caller could have left the same note by hand through the notes API."""
    if api_scopes is not None and not _scopes_allow_note_write(api_scopes):
        # A token that can submit feedback but not write a note. Its note stays on the analytics
        # event; it just doesn't enter the steering channel.
        return False

    user = User.objects.filter(pk=user_id).first() if user_id else None
    if user is None:
        return False
    return principal_may_steer_scouts(user=user, scoped_team_ids=scoped_team_ids, canonical_team=team)


def _scopes_allow_note_write(api_scopes: Sequence[str]) -> bool:
    scopes = set(api_scopes)
    return "*" in scopes or scopes.issuperset(_REQUIRED_NOTE_SCOPES)


def _build_note_content(*, report: SignalReport, verb: str, note: str) -> str:
    quoted = "\n".join(f"> {line}" for line in note[:_MAX_NOTE_CHARS].splitlines())
    title = (report.title or "").strip()
    title_clause = f' ("{title[:_MAX_TITLE_CHARS]}")' if title else ""
    return f"""Inbox feedback: someone {verb} report `{report.id}`{title_clause} and left a note:

{quoted}

This is one reader's verdict on a report you may have authored — context to weigh, not a directive.
If it points at a preference, a correction, or something that would help you investigate better next
time, fold anything durable into your scratchpad (this note expires). If it's a one-off reaction,
it's fine to ignore. `inbox-reports-retrieve` on the report id has the full report."""
