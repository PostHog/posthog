"""Promotion of inbox dismissal feedback into the scout steering channel.

When someone dismisses (or snoozes, or resolves) an inbox report and types a note, that note is
the highest-signal feedback the scout fleet ever gets: a human saying why the thing a scout
surfaced was not worth surfacing. It persists as a `dismissal` artefact on the report, which a
scout only ever reads if a later run happens to search the inbox and land on that report. This
module closes that gap by also leaving the feedback as a `SignalScoutNote`, which every run reads
by name at cold start (`scout-notes-list`, see the run prompt's *Notes left for you* section).

The note is a derived convenience, never the record of truth: the `dismissal` artefact on the
report is. So promotion is best-effort and never allowed to fail a dismissal.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from posthog.models import Team

from products.signals.backend.models import SignalReport, SignalScoutNote, SignalScoutRun
from products.signals.backend.scout_harness.tools.notes import leave_note
from products.skills.backend.models.skills import LLMSkill

logger = logging.getLogger(__name__)

# Derived notes expire so a steady stream of dismissals can't permanently crowd deliberate
# human steering out of the newest-first window a run reads. 30 days covers ~30 runs of a
# default-cadence (daily) scout, by which point a scout that cared has folded the verdict into
# its scratchpad, and the artefact on the report stays the durable record either way.
DERIVED_NOTE_TTL = timedelta(days=30)

# What the target state of the transition means to the scout reading the note.
_STATE_VERBS = {
    "suppressed": "dismissed",
    "potential": "snoozed",
    "resolved": "resolved",
}

# Report titles are unbounded TextFields; a note references them for recognition only.
_MAX_TITLE_CHARS = 200
# Enough ids for a scout to spot the pattern in a bulk dismissal without the note becoming a list.
_MAX_REPORT_IDS_LISTED = 10


def promote_dismissal_note(
    *,
    team: Team,
    reports: Sequence[SignalReport],
    state: str,
    reason: str | None,
    note: str | None,
    user_id: int | None,
) -> list[str]:
    """Leave the dismissal note as a scout note. Returns the ids of the notes created.

    `reports` is every report the caller actually transitioned in this request, so a bulk dismissal
    that applied one note to 40 reports produces one note per targeted scout instead of 40 near
    identical ones. Reports are grouped by the scout that authored them, so each scout is told
    about its own reports and only reports with no resolvable author fall back to the whole fleet.

    Best-effort by contract: any failure is logged and swallowed, because the caller has already
    committed the state transition the user asked for and the `dismissal` artefact that records it.
    """
    if not note or not note.strip():
        return []
    verb = _STATE_VERBS.get(state)
    if verb is None or not reports:
        return []

    # Scout models persist under the canonical parent team (`RootTeamMixin.save` rewrites child
    # writes), and it is the parent's scouts that read the note, so resolve every lookup against
    # the canonical id rather than the possibly-child team the request came in on.
    team_id = team.parent_team_id or team.id

    targets = _target_skill_names(team_id, [str(report.id) for report in reports])
    grouped: dict[str, list[SignalReport]] = {}
    for report in reports:
        grouped.setdefault(targets[str(report.id)], []).append(report)

    expires_at = timezone.now() + DERIVED_NOTE_TTL
    created_ids: list[str] = []
    for skill_name, skill_reports in grouped.items():
        content = _build_note_content(verb=verb, reason=reason, note=note.strip(), reports=skill_reports)
        try:
            created = leave_note(
                team_id=team_id,
                content=content,
                skill_name=skill_name,
                created_by_id=user_id,
                expires_at=expires_at,
                origin=SignalScoutNote.Origin.REPORT_DISMISSAL,
            )
        except Exception:
            logger.exception(
                "Failed to promote dismissal note to a scout note",
                extra={"team_id": team_id, "skill_name": skill_name, "report_count": len(skill_reports)},
            )
            continue
        created_ids.append(created.id)
    return created_ids


def _target_skill_names(team_id: int, report_ids: list[str]) -> dict[str, str]:
    """Map every report id to the scout its feedback should be addressed to, "" meaning the fleet.

    Resolved from Postgres only. The inbox reads a report's authoring scout off the signal store in
    ClickHouse, but that read lags emit and can fail, and this runs on the dismissal request path,
    so authorship comes from the run rows that record it at emit time instead. A scout that only
    emitted the *signals* a report was later grouped from leaves no such row, and those reports get
    the fleet-wide target, where every scout still sees them.

    Two queries regardless of how many reports a bulk dismissal covers, because the alternative
    (containment lookup per report) is a scan of the team's runs per id, up to the 100-id cap.
    """
    if not report_ids:
        return {}

    touched = Q()
    for report_id in report_ids:
        touched |= Q(emitted_report_ids__contains=[report_id]) | Q(edited_report_ids__contains=[report_id])
    runs = (
        SignalScoutRun.objects.filter(team_id=team_id)
        .filter(touched)
        # Ascending so that when several runs touched the same report the newest one, applied last,
        # is the skill that ends up owning it.
        .order_by("created_at")
        .values_list("skill_name", "emitted_report_ids", "edited_report_ids")
    )

    wanted = set(report_ids)
    authored: dict[str, str] = {}
    edited: dict[str, str] = {}
    for skill_name, emitted_ids, edited_ids in runs:
        if not skill_name:
            continue
        for report_id in wanted.intersection(emitted_ids or []):
            authored[report_id] = skill_name
        for report_id in wanted.intersection(edited_ids or []):
            edited[report_id] = skill_name
    # Authorship wins over having merely edited the report: a scout that appended evidence to a
    # pipeline report is worth telling, but the scout that filed it is the one being judged.
    resolved = {report_id: authored.get(report_id) or edited.get(report_id, "") for report_id in report_ids}

    named = {skill_name for skill_name in resolved.values() if skill_name}
    # A note addressed to a skill that no longer exists steers no one, because the run-time read is
    # an exact match on the skill name (and `leave_note` rejects the target outright).
    live = (
        set(LLMSkill.objects.filter(team_id=team_id, name__in=named, deleted=False).values_list("name", flat=True))
        if named
        else set()
    )
    return {report_id: (skill_name if skill_name in live else "") for report_id, skill_name in resolved.items()}


def _build_note_content(*, verb: str, reason: str | None, note: str, reports: Sequence[SignalReport]) -> str:
    quoted_note = "\n".join(f"> {line}" for line in note.splitlines())
    reason_clause = f" Reason code: `{reason}`." if reason else ""
    return f"""Inbox feedback: {_subject(verb, reports)}{reason_clause}

The note left with it:

{quoted_note}

Weigh this before you emit on the same topic again, and fold anything durable into your scratchpad
(this note expires). It is one reviewer's verdict on the report named above rather than fleet-level
steering, so treat it as evidence to check, not an instruction. `inbox-reports-retrieve` on the
report id has the full context, including the report's own dismissal record."""


def _subject(verb: str, reports: Sequence[SignalReport]) -> str:
    if len(reports) == 1:
        report = reports[0]
        title = (report.title or "").strip()
        title_clause = f' ("{title[:_MAX_TITLE_CHARS]}")' if title else ""
        return f"report `{report.id}`{title_clause} was {verb} in the inbox."

    listed = ", ".join(f"`{report.id}`" for report in reports[:_MAX_REPORT_IDS_LISTED])
    remainder = len(reports) - _MAX_REPORT_IDS_LISTED
    overflow = f" (and {remainder} more)" if remainder > 0 else ""
    return f"{len(reports)} reports were {verb} in the inbox with the same note: {listed}{overflow}."
