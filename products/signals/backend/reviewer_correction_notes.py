"""Forwarding of reviewer corrections on inbox reports into the scout steering channel.

A human adding or removing a suggested reviewer is the strongest routing evidence the fleet ever
gets: someone who knows the surface saying who owns it. Scouts are told to treat it as authoritative
precedent, and they cache it — a project's fleet holds a `reviewer:` scratchpad entry per surface it
has routed. Until now nothing told them a correction had happened. The only path was the project
profile's `recent_reviewer_corrections` (`scout_harness/profile/builders.py`), whose window covers
about two days of edits on a busy project, and whose bare before/after login pair does not read as
"the memory you are routing on is wrong". So a login someone removes by hand keeps being suggested,
by every scout holding it, and the correction has to be made again on the next report.

This module closes that gap the way `dismissal_notes.py`, `discussion_notes.py`, and
`feedback_notes.py` do: the edit also becomes a `SignalScoutNote`, which every run reads by name at
cold start (`scout-notes-list`). The note is the trigger, never the record: it asks the scout to
revisit its own memory, and the scout decides what to keep. Nothing here writes to the scratchpad,
because a mechanical entry would overwrite ownership evidence a scout verified for itself.

Targets are whoever holds the memory, which is why this is the only derived kind addressed to more
than one scout. The authoring scout hears about its own report. On top of that, every scout whose
`reviewer:` memory names a removed login hears about the removal, because those are the scouts still
routing on it — a fleet-wide note would reach them only if it survived the newest-first window a run
reads. A report with no live authoring scout falls back to the fleet-wide target, but only when no
holder resolved: a run reads the fleet-wide notes alongside its own, so pairing the two would tell a
holder the same thing twice.

Authorization is the editor's, and mirrors `dismissal_notes` rather than `feedback_notes`: the logins
already reach scouts through the report's reviewers artefact and the project profile, so the note
opens no channel a `task:write` caller lacks and the API-key scopes aren't demanded on top of the
RBAC and team-scope legs. Best-effort by contract: the edit, its activity-log row, and its analytics
event are already committed, so nothing here may fail a reviewer edit.

A login itself is untrusted input, whichever path stored it, so it is shape-checked before it reaches
a note and dropped when it is not a GitHub login: these values land inside a backtick span in a
prompt every scout reads while holding privileged tools.
"""

from __future__ import annotations

import re
import logging
from collections.abc import Sequence
from datetime import timedelta

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.dismissal_notes import DERIVED_NOTE_TTL, principal_may_steer_scouts
from products.signals.backend.models import SignalReport, SignalScoutNote
from products.signals.backend.report_generation.resolve_reviewers import get_org_member_github_logins_by_user_uuid
from products.signals.backend.scout_authorship import resolve_report_scout_skill
from products.signals.backend.scout_harness.tools.notes import leave_note
from products.signals.backend.scout_harness.tools.scratchpad import search_scratchpad_naming
from products.skills.backend.models.skills import LLMSkill

logger = logging.getLogger(__name__)

# The scratchpad key prefix scouts keep their routing memory under, per the reviewer section of the
# run prompt. A removal is forwarded to the scouts holding one of these for the login.
REVIEWER_MEMORY_KEY_PREFIX = "reviewer:"

# One correction must not fan out across a whole fleet's worth of notes. Twenty is far above the
# holders any real correction has (a login is cached by the scouts that route to it, not by all of
# them) and still bounds the write cost of a login some scout mentioned in passing.
MAX_NOTE_TARGETS = 20

# How far back the memory search looks for holders. Wide enough that a login cached by every scout on
# a large fleet is still found.
_MEMORY_SEARCH_LIMIT = 200

# How many of an edit's logins reach a note, and with it the memory search. The reviewers PUT caps a
# new list at ten, but the prior list is read off the stored artefact, which the generic artefacts
# API writes with no length limit. The cap is applied here rather than on write, so a list already
# stored is bounded too: without it one oversized row makes the next human edit search on hundreds of
# thousands of terms and write a note no scout could read. The fleet fan-out is capped separately by
# `MAX_NOTE_TARGETS`.
MAX_CORRECTION_LOGINS = 20

# One person trimming the same login off a morning's worth of reports is one piece of evidence, not
# ten. Inside this window a login already named in a note to a target is left out of the next one, so
# each scout is told once and the notes channel stays readable.
SUPPRESSION_WINDOW = timedelta(hours=24)

# Report titles are unbounded TextFields; a note references them for recognition only.
_MAX_TITLE_CHARS = 200

# GitHub logins are alphanumerics with single interior hyphens, 39 characters at most. Both write
# paths into the reviewers artefact accept any non-empty string, so a login can carry a backtick or a
# newline that closes the span it is rendered in and fakes a section of a note every scout reads.
# The shape gate sits at that render boundary, the way `repo_corrections.sanitized_repository` does.
_LOGIN_SHAPE_RE = re.compile(r"^[a-z0-9](?:-?[a-z0-9])*$")
_MAX_LOGIN_CHARS = 39

# The direction labels the note body writes and the suppression parser reads back. One source of
# truth so the two can't drift: suppression is keyed per direction off these section prefixes, so an
# added login never suppresses a later removal of the same login (a reversal the scout needs to hear).
_ADDED_SECTION_PREFIX = "Added: "
_REMOVED_SECTION_PREFIX = "Removed: "


@frozen
class ReviewerCorrection:
    """One human reviewer edit that changed the set, in the terms the scouts need to hear it.

    `scoped_team_ids` is the editing token's `scoped_teams` (None for session auth), read off the
    request by the caller so this stays independent of HTTP.
    """

    report_id: str
    added_logins: tuple[str, ...]
    removed_logins: tuple[str, ...]
    actor_user_id: int
    scoped_team_ids: tuple[int, ...] | None


@frozen
class ForwardedCorrectionNotes:
    """What forwarding achieved, for the reviewer-edit analytics event.

    `targets_resolved` counts the scouts the correction was addressed to, which exceeds the notes
    written when the suppression window swallowed a target's logins.
    """

    note_ids: tuple[str, ...]
    targets_resolved: int


@frozen
class _LoginsAlreadyTold:
    """The logins a target was already told about inside the window, split by direction."""

    added: set[str]
    removed: set[str]


_NOTHING_FORWARDED = ForwardedCorrectionNotes(note_ids=(), targets_resolved=0)


def forward_reviewer_correction_note(*, team: Team, correction: ReviewerCorrection) -> ForwardedCorrectionNotes:
    """Leave a reviewer correction as a scout note, one per scout that holds the relevant memory.

    Best-effort by contract: nothing in this module may turn a successful reviewer edit into a 5xx.
    The caller runs it after commit, so the edit and its activity-log row already stand whatever
    happens here. Every step past this point runs inside one failure boundary, because authorization,
    target resolution, and suppression all read the database.
    """
    if not correction.added_logins and not correction.removed_logins:
        return _NOTHING_FORWARDED
    try:
        return _forward(team=team, correction=correction)
    except Exception:
        logger.exception(
            "Failed to forward a reviewer correction to a scout note",
            extra={"team_id": team.id, "report_id": correction.report_id},
        )
        return _NOTHING_FORWARDED


def _forward(*, team: Team, correction: ReviewerCorrection) -> ForwardedCorrectionNotes:
    # Scout rows and their notes live under the canonical parent team, and a note is readable by
    # everyone with access to that project. Forwarding a child environment's correction would hand
    # its report id and title to an audience that may have no access to that environment, so those
    # corrections stay on the report and the activity log only.
    canonical_team = team.parent_team or team
    if team.id != canonical_team.id:
        return _NOTHING_FORWARDED

    actor = User.objects.filter(pk=correction.actor_user_id).first()
    if actor is None:
        return _NOTHING_FORWARDED
    if not principal_may_steer_scouts(
        user=actor,
        scoped_team_ids=correction.scoped_team_ids,
        canonical_team=canonical_team,
    ):
        return _NOTHING_FORWARDED

    added_logins = _renderable(correction.added_logins)
    removed_logins = _renderable(correction.removed_logins)
    if not added_logins and not removed_logins:
        return _NOTHING_FORWARDED

    report = SignalReport.objects.filter(team_id=canonical_team.id, id=correction.report_id).first()
    if report is None:
        return _NOTHING_FORWARDED

    targets = _resolve_targets(canonical_team.id, correction.report_id, removed_logins)
    actor_login = _actor_login(canonical_team.id, actor) if removed_logins else None
    expires_at = timezone.now() + DERIVED_NOTE_TTL
    note_ids: list[str] = []
    for skill_name in targets:
        already_told = _logins_already_told(canonical_team.id, skill_name)
        added = tuple(login for login in added_logins if login not in already_told.added)
        removed = tuple(login for login in removed_logins if login not in already_told.removed)
        if not added and not removed:
            continue
        content = _build_note_content(
            report=report,
            added_logins=added,
            # Split per note rather than per edit: the caveat belongs to the logins this scout is
            # actually being told about, and the suppression filter above can leave a batch holding
            # only the teammate half of a removal, or only the editor's own login.
            self_removed=tuple(login for login in removed if login == actor_login),
            teammate_removed=tuple(login for login in removed if login != actor_login),
        )
        try:
            created = leave_note(
                team_id=canonical_team.id,
                content=content,
                skill_name=skill_name,
                created_by_id=actor.id,
                expires_at=expires_at,
                origin=SignalScoutNote.Origin.REPORT_REVIEWER_CORRECTION,
            )
        except Exception:
            # Per-note guard on top of the outer boundary, so one unwritable target (a skill deleted
            # mid-request, say) doesn't cost the other scouts their notes.
            logger.exception(
                "Failed to forward a reviewer correction to one scout",
                extra={"team_id": canonical_team.id, "skill_name": skill_name},
            )
            continue
        note_ids.append(created.id)
    return ForwardedCorrectionNotes(note_ids=tuple(note_ids), targets_resolved=len(targets))


def _renderable(logins: Sequence[str]) -> tuple[str, ...]:
    """The logins of one edit that may be rendered into a note: well-shaped, deduped, and capped."""
    kept: list[str] = []
    malformed = 0
    for login in logins:
        cleaned = login.strip().lower()
        if not cleaned or len(cleaned) > _MAX_LOGIN_CHARS or not _LOGIN_SHAPE_RE.match(cleaned):
            malformed += 1
            continue
        if cleaned not in kept:
            kept.append(cleaned)
    if malformed:
        # A count, never the value: a malformed login is untrusted input, and this line is read by
        # people.
        logger.warning(
            "Dropped reviewer logins that are not a GitHub login before forwarding a correction",
            extra={"dropped": malformed},
        )
    return tuple(kept[:MAX_CORRECTION_LOGINS])


def _resolve_targets(team_id: int, report_id: str, removed_logins: Sequence[str]) -> list[str]:
    """Who to tell: the scout that filed the report, plus every holder of the removed logins.

    A report with no live authoring scout (a pipeline report, or one whose scout is gone) falls back
    to the fleet-wide target ("") that dismissals use — but only when no holder resolved, because a
    run reads the fleet-wide notes alongside its own and a holder would hear the same edit twice.
    """
    holders = _memory_holders(team_id, removed_logins)
    authoring = resolve_report_scout_skill(team_id, report_id)
    if not authoring:
        return holders[:MAX_NOTE_TARGETS] if holders else [""]
    return [authoring, *(name for name in holders if name != authoring)][:MAX_NOTE_TARGETS]


def _memory_holders(team_id: int, removed_logins: Sequence[str]) -> list[str]:
    """The live scouts whose `reviewer:` memory names one of these logins.

    One query for the whole login list, matching each as a whole token. A substring search would
    both amplify (one unindexed scan per login) and mis-target: `ai` sits inside `email`, so a short
    login would reach scouts that never routed on it and spend the target cap before the real
    holders were found.

    An entry written by a pipeline stage is left out: a stage is a writer identity, not a note
    audience. So is one written by a scout whose skill is gone, because a note addressed to a name
    that no longer exists steers no one (and `leave_note` rejects the target).
    """
    if not removed_logins:
        return []
    named = {
        entry.created_by_skill
        for entry in search_scratchpad_naming(
            team_id=team_id,
            key_prefix=REVIEWER_MEMORY_KEY_PREFIX,
            terms=removed_logins,
            limit=_MEMORY_SEARCH_LIMIT,
        )
        if entry.created_by_skill
    }
    if not named:
        return []
    return sorted(
        LLMSkill.objects.filter(team_id=team_id, name__in=named, deleted=False).values_list("name", flat=True)
    )


def _actor_login(team_id: int, actor: User) -> str | None:
    """The editor's own GitHub login, so a self-removal is not reported as a teammate's verdict."""
    return get_org_member_github_logins_by_user_uuid(team_id, [str(actor.uuid)]).get(str(actor.uuid))


def _logins_already_told(team_id: int, skill_name: str) -> _LoginsAlreadyTold:
    """The logins this target was already told about inside the window, split by direction.

    Suppression is per action, not per login: an added login must not suppress a later removal of the
    same login, since a reversal is exactly the stale-routing correction this channel exists to carry.
    Added and removed logins are therefore read back from their own note sections. Coalescing across
    reports stays intentional — the same login removed off another report inside the window is still
    one note, because it is the same direction.
    """
    contents = SignalScoutNote.objects.filter(
        team_id=team_id,
        skill_name=skill_name,
        origin=SignalScoutNote.Origin.REPORT_REVIEWER_CORRECTION,
        created_at__gte=timezone.now() - SUPPRESSION_WINDOW,
    ).values_list("content", flat=True)
    # Logins ride the note content in backticks under a literal `Added:` / `Removed:` section, which is
    # enough to recognize direction without a second table to track what was sent.
    added_told: set[str] = set()
    removed_told: set[str] = set()
    for content in contents:
        for paragraph in content.split("\n\n"):
            if paragraph.startswith(_ADDED_SECTION_PREFIX):
                added_told |= _quoted_logins(paragraph)
            elif paragraph.startswith(_REMOVED_SECTION_PREFIX):
                removed_told |= _quoted_logins(paragraph)
    return _LoginsAlreadyTold(added=added_told, removed=removed_told)


def _quoted_logins(content: str) -> set[str]:
    parts = content.split("`")
    # Odd positions are the backtick-delimited spans; report ids sit in them too and never collide
    # with a login, since a login can't contain a hyphen-delimited UUID.
    return {parts[index] for index in range(1, len(parts), 2)}


def _build_note_content(
    *,
    report: SignalReport,
    added_logins: Sequence[str],
    self_removed: Sequence[str],
    teammate_removed: Sequence[str],
) -> str:
    sections = [f"Inbox routing correction: someone changed the suggested reviewers on {_subject(report)}"]
    if added_logins:
        sections.append(
            f"{_ADDED_SECTION_PREFIX}{_listed(added_logins)}. An added login is a positive ownership fact for this "
            "surface — record it with the report id and the date."
        )
    if teammate_removed:
        sections.append(f"{_REMOVED_SECTION_PREFIX}{_listed(teammate_removed)}.")
    if self_removed:
        sections.append(
            f"{_REMOVED_SECTION_PREFIX}{_listed(self_removed)}. That is the editor's own login, which is weaker "
            "evidence than a teammate removing someone."
        )
    if teammate_removed or self_removed:
        sections.append(_removal_guidance(by_a_teammate=bool(teammate_removed)))
    sections.append(
        "This is one editor's correction on the report named above rather than fleet-level steering, so treat it\n"
        "as evidence to check, not an instruction. `inbox-reports-retrieve` on the report id has the full context,\n"
        "including the report's current reviewers. Fold anything durable into your scratchpad, since this note\n"
        "expires."
    )
    return "\n\n".join(sections)


def _removal_guidance(*, by_a_teammate: bool) -> str:
    # What the scout should record has to match the removal it was just told about: an editor taking
    # their own login off is not a teammate's verdict on who owns the surface.
    recorded = "a teammate removed the login" if by_a_teammate else "the login's owner took themselves off"
    return (
        "One removal is weak evidence on its own: someone may be away, a duplicate reviewer, or noise the\n"
        "editor trimmed. Repeated removals of the same login on the same surface are strong evidence that the\n"
        "memory you route on is stale. Search your scratchpad for the login and for your `reviewer:` keys on\n"
        f"this surface, then condense rather than delete: fold in that {recorded}, on how many\n"
        "recent reports and when, and keep the ownership evidence that still stands. Do not put a removed login\n"
        "back on a report about the same topic unless you find new evidence for it."
    )


def _subject(report: SignalReport) -> str:
    # One line: the title is untrusted prompt input (the research agent writes it from ticket and
    # issue text), and a newline would let it pose as a new section of the note.
    title = " ".join((report.title or "").split())
    title_clause = f' ("{title[:_MAX_TITLE_CHARS]}")' if title else ""
    return f"report `{report.id}`{title_clause}."


def _listed(logins: Sequence[str]) -> str:
    return ", ".join(f"`{login}`" for login in logins)
