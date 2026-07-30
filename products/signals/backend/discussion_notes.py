"""Forwarding of inbox discussion questions into the scout steering channel.

When someone hits "Discuss" on an inbox report and types a question, the kickoff spins up a fresh
agentic task whose prompt is the report link plus that question — but nothing about it ever reaches
the scout that authored the report. Yet those questions often carry exactly the context a scout could
use next run: a correction ("this is Apple's approval flow, not a bug"), a preference ("we never JOIN
in batch exports"), or a domain fact the scout couldn't know. This module closes that gap the same way
`dismissal_notes.py` does for dismissal feedback: it also leaves the question as a `SignalScoutNote`,
which every run reads by name at cold start (`scout-notes-list`).

Unlike a dismissal — one reviewer's verdict that a report wasn't worth surfacing — a discussion
question is not a judgement on the report at all, just something a user wanted to know. So the note is
framed as context to weigh, explicitly inviting the scout to fold anything durable into its scratchpad
or ignore it as noise; the scout's own judgement decides which. It is a derived convenience, never a
record of truth: the question lives on the discussion task regardless, so forwarding is best-effort and
never allowed to fail task creation.

Authorization mirrors the dismissal path exactly. Creating a discussion task needs only `task:write`,
while the notes table is otherwise gated to skill-authoring authorization (scouts read note content
verbatim while holding privileged sandbox tools), so forwarding re-checks that the caller could have
left the note by hand — the same `_may_steer_scouts` gate the dismissal forwarder uses, which enforces
the request's token `scoped_teams` leg plus canonical-project access and the `llm_skill` editor bar. It
runs against the canonical project whose scouts read the row, and only when the task was created on the
canonical team itself, so a child environment's question never reaches the parent project's readers.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from rest_framework.request import Request

from posthog.models import Team, User

from products.signals.backend.dismissal_notes import DERIVED_NOTE_TTL, _may_steer_scouts, resolve_report_scout_skill
from products.signals.backend.models import SignalReport, SignalScoutNote
from products.signals.backend.scout_harness.tools.notes import leave_note

logger = logging.getLogger(__name__)

# Report titles are unbounded TextFields; a note references them for recognition only.
_MAX_TITLE_CHARS = 200

# The kickoff prompt (frontend `buildDiscussReportPrompt`) prefixes the report URL on its own line,
# then the user's question after a blank line. We forward just the question; matching is lenient so a
# format change degrades to forwarding the whole prompt rather than dropping the note.
_PROMPT_PREFIX = "let's discuss this posthog inbox report:"


def forward_discussion_note(
    *,
    team: Team,
    report_id: str,
    text: str,
    request: Request,
) -> str | None:
    """Leave a discussion question as a scout note. Returns the created note id, or None if nothing
    was forwarded.

    Best-effort by contract: nothing here may turn a successful task creation into a 5xx — the task
    (and the question on it) already exists, so a failure must not surface. Every step past this point
    runs inside one failure boundary, because authorization and target resolution both read the
    database.
    """
    if not text or not text.strip():
        return None
    try:
        return _forward(team=team, report_id=str(report_id), text=text, request=request)
    except Exception:
        logger.exception(
            "Failed to forward a discussion question to a scout note",
            extra={"team_id": team.id, "report_id": report_id},
        )
        return None


def _forward(*, team: Team, report_id: str, text: str, request: Request) -> str | None:
    question = _extract_question(text)
    if not question:
        return None

    # Scout rows and their notes live under the canonical parent team; forwarding a child
    # environment's question would hand its report id, title, and text to an audience that may
    # have no access to that environment. Those discussions stay on the task only.
    canonical_team = team.parent_team or team
    if team.id != canonical_team.id:
        return None

    # Same gate the dismissal forwarder uses: the caller must be authorized to have written this note
    # by hand (token `scoped_teams`, canonical-project access, `llm_skill` editor), so a bare
    # `task:write` credential can't plant a scout steering note it couldn't otherwise write.
    user = request.user
    if not isinstance(user, User) or not _may_steer_scouts(request, canonical_team):
        return None

    report = SignalReport.objects.filter(team_id=canonical_team.id, id=report_id).first()
    if report is None:
        return None

    skill_name = resolve_report_scout_skill(canonical_team.id, report_id)
    content = _build_note_content(report=report, question=question)
    created = leave_note(
        team_id=canonical_team.id,
        content=content,
        skill_name=skill_name,
        created_by_id=user.id,
        expires_at=timezone.now() + DERIVED_NOTE_TTL,
        origin=SignalScoutNote.Origin.REPORT_DISCUSSION,
    )
    return created.id


def _extract_question(text: str) -> str:
    """Pull the user's question out of the kickoff prompt, tolerating format drift."""
    stripped = text.strip()
    if stripped.lower().startswith(_PROMPT_PREFIX) and "\n\n" in stripped:
        return stripped.split("\n\n", 1)[1].strip()
    return stripped


def _build_note_content(*, report: SignalReport, question: str) -> str:
    quoted = "\n".join(f"> {line}" for line in question.splitlines())
    title = (report.title or "").strip()
    title_clause = f' ("{title[:_MAX_TITLE_CHARS]}")' if title else ""
    return f"""Inbox activity: someone opened a discussion on report `{report.id}`{title_clause} and asked:

{quoted}

This is a question a user asked about a report you may have authored — context, not a directive, and
not a verdict on the report. If it points at a preference, a correction, or context that would help you
investigate better next time, weigh it and fold anything durable into your scratchpad (this note
expires). If it's a one-off question or unrelated chatter, it's fine to ignore. `inbox-reports-retrieve`
on the report id has the full report."""
