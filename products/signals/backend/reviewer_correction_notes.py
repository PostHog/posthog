"""Send scoped reviewer edits and claims to the scouts that produced the report or hold its routing memory.

Notes use the same GitHub logins or PostHog user UUIDs as the correction activity log.
They are searchable by other scouts and research through the existing notes tools.
Forwarding is best effort after commit, with the editor's steering permissions. A note
asks agents to check the source report; it does not establish a standing ownership rule.

A removal is negative routing evidence. A claim is the positive counterpart: a person, or their
agent, took the work, so the scouts can suggest that person for similar reports.
"""

from __future__ import annotations

import re
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from django.utils import timezone

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.dismissal_notes import DERIVED_NOTE_TTL, principal_may_steer_scouts
from products.signals.backend.models import SignalReport, SignalScoutNote
from products.signals.backend.scout_authorship import resolve_touching_scout_skills
from products.signals.backend.scout_harness.tools.notes import leave_note
from products.signals.backend.scout_harness.tools.scratchpad import search_scratchpad_naming
from products.signals.backend.scout_note_actor import actor_github_login, render_actor
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
MAX_CORRECTION_REVIEWERS = 20

# Coalesce repeat delivery on one report, while preserving feedback from other reports.
SUPPRESSION_WINDOW = timedelta(hours=24)

# Report titles are unbounded TextFields; a note references them for recognition only.
_MAX_TITLE_CHARS = 200

# Canonical UUIDs also fit GitHub's login character and length bounds. Both write
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
_CLAIMED_SECTION_PREFIX = "Claimed: "

# Org-keyed kill switch for claim notes. Teams outside the rollout are the comparison group for
# `signals_report_claimed.claimant_was_suggested`.
CLAIM_SCOUT_NOTES_FLAG = "signals-claim-scout-notes"

# The agent name on a claim is caller-supplied text, so it is bounded and kept to one line.
_MAX_AGENT_CHARS = 60


@frozen
class ReviewerCorrection:
    """One human reviewer edit that changed the set, in the terms the scouts need to hear it.

    Reviewers use the activity log's GitHub login or PostHog user UUID labels.
    `scoped_team_ids` is the editing token's `scoped_teams` (None for session auth), read off the
    request by the caller so this stays independent of HTTP.
    """

    report_id: str
    added_reviewers: tuple[str, ...]
    removed_reviewers: tuple[str, ...]
    actor_user_id: int
    scoped_team_ids: tuple[int, ...] | None
    # Why the editor removed reviewers, when they said. Both apply to the removals only.
    removal_reason: str | None = None
    removal_note: str | None = None


@frozen
class ReviewerClaim:
    """One new claim on a report by a person or by their agent.

    `actor_user_id` is the person in both cases. `via_agent` names the agent when the agent made the
    claim for them. Task and system claims are never a `ReviewerClaim`, because no person chose the work.
    """

    report_id: str
    actor_user_id: int
    scoped_team_ids: tuple[int, ...] | None
    claimant_was_suggested: bool
    via_agent: str | None = None


@frozen
class ForwardedCorrectionNotes:
    """What forwarding achieved, for the reviewer-edit analytics event.

    `targets_resolved` counts the scouts the correction was addressed to, which exceeds the notes
    written when the suppression window swallowed a target's logins.
    """

    note_ids: tuple[str, ...]
    targets_resolved: int


@frozen
class _ReviewersAlreadyTold:
    """The reviewer identities a target was already told about inside the window, split by direction."""

    added: set[str]
    removed: set[str]
    claimed: set[str]


@frozen
class _NoteAuthor:
    """The person a note is attributed to, after the steering gate passed, and the report it names."""

    canonical_team: Team
    actor: User
    actor_login: str | None
    report: SignalReport

    @property
    def rendered(self) -> str:
        return render_actor(self.actor, github_login=self.actor_login)

    @property
    def identities(self) -> set[str]:
        identities = {str(self.actor.uuid)}
        if self.actor_login:
            identities.add(self.actor_login)
        return identities


_NOTHING_FORWARDED = ForwardedCorrectionNotes(note_ids=(), targets_resolved=0)


def forward_reviewer_correction_note(*, team: Team, correction: ReviewerCorrection) -> ForwardedCorrectionNotes:
    """Leave a reviewer correction as a scout note, one per scout that holds the relevant memory.

    Best-effort by contract: nothing in this module may turn a successful reviewer edit into a 5xx.
    The caller runs it after commit, so the edit and its activity-log row already stand whatever
    happens here. Every step past this point runs inside one failure boundary, because authorization,
    target resolution, and suppression all read the database.
    """
    if not correction.added_reviewers and not correction.removed_reviewers:
        return _NOTHING_FORWARDED
    try:
        return _forward(team=team, correction=correction)
    except Exception:
        logger.exception(
            "Failed to forward a reviewer correction to a scout note",
            extra={"team_id": team.id, "report_id": correction.report_id},
        )
        return _NOTHING_FORWARDED


def forward_reviewer_claim_note(*, team: Team, claim: ReviewerClaim) -> ForwardedCorrectionNotes:
    """Leave a claim as a scout note, one per scout that touched the report or holds the claimant's memory.

    Best-effort by the same contract as `forward_reviewer_correction_note`: the claim already stands.
    """
    try:
        return _forward_claim(team=team, claim=claim)
    except Exception:
        logger.exception(
            "Failed to forward a report claim to a scout note",
            extra={"team_id": team.id, "report_id": claim.report_id},
        )
        return _NOTHING_FORWARDED


def claim_scout_notes_enabled(team: Team) -> bool:
    """Whether claims on this team's reports reach the scouts. Fails closed on a flag-read error."""
    try:
        org_id = str(team.organization_id)
        return (
            posthoganalytics.feature_enabled(
                CLAIM_SCOUT_NOTES_FLAG,
                org_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
                send_feature_flag_events=False,
            )
            is True
        )
    except Exception:
        logger.warning("Failed to read the claim scout notes flag", exc_info=True)
        return False


def _note_author(
    *, team: Team, actor_user_id: int, scoped_team_ids: tuple[int, ...] | None, report_id: str
) -> _NoteAuthor | None:
    # Scout rows and their notes live under the canonical parent team, and a note is readable by
    # everyone with access to that project. Forwarding a child environment's correction would hand
    # its report id and title to an audience that may have no access to that environment, so those
    # corrections stay on the report and the activity log only.
    canonical_team = team.parent_team or team
    if team.id != canonical_team.id:
        return None

    actor = User.objects.filter(pk=actor_user_id).first()
    if actor is None:
        return None
    if not principal_may_steer_scouts(
        user=actor,
        scoped_team_ids=scoped_team_ids,
        canonical_team=canonical_team,
    ):
        return None

    report = SignalReport.objects.filter(team_id=canonical_team.id, id=report_id).first()
    if report is None:
        return None
    return _NoteAuthor(
        canonical_team=canonical_team,
        actor=actor,
        actor_login=actor_github_login(canonical_team.id, actor),
        report=report,
    )


def _forward(*, team: Team, correction: ReviewerCorrection) -> ForwardedCorrectionNotes:
    added_reviewers = _renderable(correction.added_reviewers)
    removed_reviewers = _renderable(correction.removed_reviewers)
    if not added_reviewers and not removed_reviewers:
        return _NOTHING_FORWARDED

    author = _note_author(
        team=team,
        actor_user_id=correction.actor_user_id,
        scoped_team_ids=correction.scoped_team_ids,
        report_id=correction.report_id,
    )
    if author is None:
        return _NOTHING_FORWARDED

    team_id = author.canonical_team.id
    targets = _resolve_targets(team_id, correction.report_id, removed_reviewers)
    # One lookup serves the editor's name in every note and the self-removal split below, which keeps
    # an editor taking their own login off from reading as a teammate's verdict.
    editor = author.rendered
    actor_identities = author.identities
    expires_at = timezone.now() + DERIVED_NOTE_TTL
    note_ids: list[str] = []
    for skill_name in targets:
        already_told = _reviewers_already_told(team_id, skill_name, correction.report_id)
        added = tuple(login for login in added_reviewers if login not in already_told.added)
        removed = tuple(login for login in removed_reviewers if login not in already_told.removed)
        if not added and not removed:
            continue
        content = _build_note_content(
            report=author.report,
            editor=editor,
            added_reviewers=added,
            # Split per note rather than per edit: the caveat belongs to the logins this scout is
            # actually being told about, and the suppression filter above can leave a batch holding
            # only the teammate half of a removal, or only the editor's own login.
            self_removed=tuple(login for login in removed if login in actor_identities),
            teammate_removed=tuple(login for login in removed if login not in actor_identities),
            removal_reason=correction.removal_reason,
            removal_note=correction.removal_note,
        )
        note_id = _leave_note(author=author, skill_name=skill_name, content=content, expires_at=expires_at)
        if note_id is not None:
            note_ids.append(note_id)
    return ForwardedCorrectionNotes(note_ids=tuple(note_ids), targets_resolved=len(targets))


def _forward_claim(*, team: Team, claim: ReviewerClaim) -> ForwardedCorrectionNotes:
    author = _note_author(
        team=team,
        actor_user_id=claim.actor_user_id,
        scoped_team_ids=claim.scoped_team_ids,
        report_id=claim.report_id,
    )
    if author is None:
        return _NOTHING_FORWARDED
    # The login is what scouts route on. A member without one is still assignable in the Inbox by
    # their PostHog user UUID.
    claimant = _renderable([author.actor_login or str(author.actor.uuid)])
    if not claimant:
        return _NOTHING_FORWARDED

    team_id = author.canonical_team.id
    targets = _resolve_targets(team_id, claim.report_id, claimant)
    content = _build_claim_note_content(
        report=author.report,
        claimant=author.rendered,
        identity=claimant[0],
        via_agent=claim.via_agent,
        claimant_was_suggested=claim.claimant_was_suggested,
    )
    expires_at = timezone.now() + DERIVED_NOTE_TTL
    note_ids: list[str] = []
    for skill_name in targets:
        # A claim, a release, and a claim again on one report is one piece of evidence.
        if claimant[0] in _reviewers_already_told(team_id, skill_name, claim.report_id).claimed:
            continue
        note_id = _leave_note(author=author, skill_name=skill_name, content=content, expires_at=expires_at)
        if note_id is not None:
            note_ids.append(note_id)
    return ForwardedCorrectionNotes(note_ids=tuple(note_ids), targets_resolved=len(targets))


def _leave_note(*, author: _NoteAuthor, skill_name: str, content: str, expires_at: datetime) -> str | None:
    try:
        created = leave_note(
            team_id=author.canonical_team.id,
            content=content,
            skill_name=skill_name,
            created_by_id=author.actor.id,
            expires_at=expires_at,
            origin=SignalScoutNote.Origin.REPORT_REVIEWER_CORRECTION,
        )
    except Exception:
        # Per-note guard on top of the outer boundary, so one unwritable target (a skill deleted
        # mid-request, say) doesn't cost the other scouts their notes.
        logger.exception(
            "Failed to forward a reviewer note to one scout",
            extra={"team_id": author.canonical_team.id, "skill_name": skill_name},
        )
        return None
    return created.id


def _renderable(logins: Sequence[str]) -> tuple[str, ...]:
    """Bound and sanitize GitHub logins or canonical user UUIDs before prompt rendering."""
    kept: list[str] = []
    malformed = 0
    for login in logins:
        cleaned = login.strip().lower()
        if cleaned.startswith("user:"):
            try:
                cleaned = str(UUID(cleaned.removeprefix("user:")))
            except ValueError:
                malformed += 1
                continue
        if not cleaned or len(cleaned) > _MAX_LOGIN_CHARS or not _LOGIN_SHAPE_RE.match(cleaned):
            malformed += 1
            continue
        if cleaned not in kept:
            kept.append(cleaned)
    if malformed:
        # A count, never the value: a malformed login is untrusted input, and this line is read by
        # people.
        logger.warning(
            "Dropped malformed reviewer identities before forwarding a correction",
            extra={"dropped": malformed},
        )
    return tuple(kept[:MAX_CORRECTION_REVIEWERS])


def _resolve_targets(team_id: int, report_id: str, holder_identities: Sequence[str]) -> list[str]:
    """Who to tell: every scout that touched the report, plus every holder of the given identities.

    The identities are the removed logins for a correction, and the claimant for a claim.

    Touching means emitted or edited, because a scout that set the reviewers through an edit did the
    routing a human has just corrected, and it is better to tell it once too often than to leave it
    routing on a login somebody removed. The touching union keeps deleted skills, so it is filtered
    to live ones the way the holders are.

    A report no live scout touched (a pipeline report, or one whose scouts are gone) falls back to
    the fleet-wide target ("") that dismissals use — but only when no holder resolved, because a run
    reads the fleet-wide notes alongside its own and a holder would hear the same edit twice.
    """
    touching = _live_skills(team_id, resolve_touching_scout_skills(team_id, report_id))
    holders = _memory_holders(team_id, holder_identities)
    targets = [*touching, *(name for name in holders if name not in touching)]
    return targets[:MAX_NOTE_TARGETS] if targets else [""]


def _memory_holders(team_id: int, identities: Sequence[str]) -> list[str]:
    """The live scouts whose `reviewer:` memory names one of these identities.

    One query for the whole login list, matching each as a whole token. A substring search would
    both amplify (one unindexed scan per login) and mis-target: `ai` sits inside `email`, so a short
    login would reach scouts that never routed on it and spend the target cap before the real
    holders were found.

    An entry written by a pipeline stage is left out: a stage is a writer identity, not a note
    audience. So is one written by a scout whose skill is gone, because a note addressed to a name
    that no longer exists steers no one (and `leave_note` rejects the target).
    """
    if not identities:
        return []
    named = {
        entry.created_by_skill
        for entry in search_scratchpad_naming(
            team_id=team_id,
            key_prefix=REVIEWER_MEMORY_KEY_PREFIX,
            terms=identities,
            limit=_MEMORY_SEARCH_LIMIT,
        )
        if entry.created_by_skill
    }
    return _live_skills(team_id, sorted(named))


def _live_skills(team_id: int, names: Sequence[str]) -> list[str]:
    """The given skill names that still exist, in the order they were given.

    One query. A note addressed to a deleted skill steers no one, and `leave_note` rejects it.
    """
    if not names:
        return []
    live = set(LLMSkill.objects.filter(team_id=team_id, name__in=names, deleted=False).values_list("name", flat=True))
    return [name for name in names if name in live]


def _reviewers_already_told(team_id: int, skill_name: str, report_id: str) -> _ReviewersAlreadyTold:
    """The reviewer identities this target was already told about inside the window, split by direction.

    Suppression is per action, not per login: an added login must not suppress a later removal of the
    same reviewer, and a claim must not suppress a later removal. Only notes about the same report can suppress a repeat: another report can
    concern a different area or provide independent evidence of a repeated mistake.
    """
    contents = (
        SignalScoutNote.objects.filter(
            team_id=team_id,
            skill_name=skill_name,
            origin=SignalScoutNote.Origin.REPORT_REVIEWER_CORRECTION,
            created_at__gte=timezone.now() - SUPPRESSION_WINDOW,
            # The first quoted value is the report id; names cannot contain backticks.
            content__regex=rf"^Inbox routing correction: [^`]* on report `{re.escape(report_id)}`",
        )
        .order_by("-created_at", "-id")
        .values_list("content", flat=True)
    )
    # Logins ride the note content in backticks under a literal `Added:` / `Removed:` section, which is
    # enough to recognize direction without a second table to track what was sent.
    added_told: set[str] = set()
    removed_told: set[str] = set()
    claimed_told: set[str] = set()
    for content in contents:
        already_seen = added_told | removed_told | claimed_told
        for paragraph in content.split("\n\n"):
            if paragraph.startswith(_ADDED_SECTION_PREFIX):
                added_told |= _quoted_reviewers(paragraph) - already_seen
            elif paragraph.startswith(_REMOVED_SECTION_PREFIX):
                removed_told |= _quoted_reviewers(paragraph) - already_seen
            elif paragraph.startswith(_CLAIMED_SECTION_PREFIX):
                # Only the first sentence names the claimant. Identities cannot contain a period.
                claimed_told |= _quoted_reviewers(paragraph.split(".", 1)[0]) - already_seen
    return _ReviewersAlreadyTold(added=added_told, removed=removed_told, claimed=claimed_told)


def _quoted_reviewers(content: str) -> set[str]:
    parts = content.split("`")
    return {parts[index] for index in range(1, len(parts), 2)}


def _build_note_content(
    *,
    report: SignalReport,
    editor: str,
    added_reviewers: Sequence[str],
    self_removed: Sequence[str],
    teammate_removed: Sequence[str],
    removal_reason: str | None = None,
    removal_note: str | None = None,
) -> str:
    sections = [f"Inbox routing correction: {editor} changed the suggested reviewers on {_subject(report)}"]
    if added_reviewers:
        sections.append(
            f"{_ADDED_SECTION_PREFIX}{_listed(added_reviewers)}. The editor selected these reviewers for this report. "
            "Check the report context before using this as ownership evidence elsewhere."
        )
    if teammate_removed:
        sections.append(f"{_REMOVED_SECTION_PREFIX}{_listed(teammate_removed)}.")
    if self_removed:
        # The weak-evidence caveat makes a model demote the person rather than drop them, which is right
        # for an unexplained self-removal and wrong when the editor said why.
        caveat = (
            "That is the editor's own identity, removed for the reason stated below."
            if removal_reason in _REASON_GUIDANCE or removal_note
            else "That is the editor's own identity, which is weaker evidence than a teammate removing someone."
        )
        sections.append(f"{_REMOVED_SECTION_PREFIX}{_listed(self_removed)}. {caveat}")
    if teammate_removed or self_removed:
        if removal_reason:
            sections.append(f"Reason the editor gave for the removal: `{removal_reason}`.")
        if removal_note:
            # Quoted line by line, so the editor's text cannot pose as a section of this note.
            quoted_note = "\n".join(f"> {line}" for line in removal_note.splitlines())
            sections.append(f"The editor's note on the removal:\n\n{quoted_note}")
        sections.append(_removal_guidance(by_a_teammate=bool(teammate_removed), reason=removal_reason))
    sections.append(
        f"{_IDENTITY_FOOTER} "
        "This edit is binding on the source report. For another report, check its scope and reason with "
        "`inbox-reports-retrieve` before applying it. Record only supported ownership evidence in your "
        "`reviewer:` memory, with the source report, date, and scope. This note expires."
    )
    return "\n\n".join(sections)


def _build_claim_note_content(
    *,
    report: SignalReport,
    claimant: str,
    identity: str,
    via_agent: str | None,
    claimant_was_suggested: bool,
) -> str:
    agent = " ".join((via_agent or "").replace("`", "").split())[:_MAX_AGENT_CHARS]
    by = f"Their agent ({agent}) claimed it for them." if agent else "They claimed it themselves."
    # Positive evidence is weaker than a removal reason: a person can pick up work outside their
    # area. The guidance asks for a scoped memory entry, not a routing rule.
    fit = (
        "They were already a suggested reviewer, so the claim confirms that routing."
        if claimant_was_suggested
        else "They were not a suggested reviewer. Consider them for similar work in the same area."
    )
    return "\n\n".join(
        [
            f"Inbox routing correction: {claimant} claimed the work on {_subject(report)}",
            f"{_CLAIMED_SECTION_PREFIX}`{identity}`. {by} {fit}",
            "A claim is positive evidence that this person works in this area. It is not proof of ownership, "
            "and one claim is not a standing rule. Search your `reviewer:` memory for this identity and area. "
            "Record that they claimed the work, with the source report and date. Several claims in one area "
            "are stronger evidence than one. Do not extend this to unrelated areas.",
            f"{_IDENTITY_FOOTER} For another report, check its scope with `inbox-reports-retrieve` before "
            "applying this. This note expires.",
        ]
    )


_IDENTITY_FOOTER = (
    "Reviewers are identified by GitHub login or PostHog user UUID. Check current project membership "
    "with `scout-members-list`; a GitHub account is not required for Inbox assignment."
)


# A stated reason replaces the generic caution: it tells the scout which of the meanings a removal
# can have applies, and each leads to a different memory update.
_REASON_GUIDANCE = {
    "wrong_area": (
        "The removed identity is not the right reviewer for this work, because it is outside their area, they moved "
        "off it, or someone else owns it. Responsibility for it and similar work moves away from them, and their "
        "older commits and ownership entries here are stale evidence. Do not select them for that work on the "
        "strength of that history. Look for the current owner, and keep routing unrelated areas to them."
    ),
    "already_covered": (
        "Another reviewer already covers this report. This is not ownership evidence against the removed identity, "
        "so do not record an exclusion. Avoid adding them as an extra reviewer when others already cover the work."
    ),
    "unavailable": (
        "The removed identity does not have bandwidth right now, for example because they are away or have too "
        "many reports. This is not ownership evidence, so do not record an exclusion or an ownership change."
    ),
}
_GENERIC_GUIDANCE = (
    "A removal can mean absence, duplicate coverage, or an unsuitable assignment. Self-removal alone "
    "does not establish an ownership change or a standing exclusion."
)


def _removal_guidance(*, by_a_teammate: bool, reason: str | None = None) -> str:
    # What the scout should record has to match the removal it was just told about: an editor taking
    # their own login off is not a teammate's verdict on who owns the surface.
    recorded = "a teammate removed the reviewer" if by_a_teammate else "the reviewer took themselves off"
    meaning = _REASON_GUIDANCE.get(reason or "", _GENERIC_GUIDANCE)
    return (
        f"{meaning} Search your `reviewer:` memory "
        f"for this identity and area. Record that {recorded}, with the source report and date, "
        "and retain ownership evidence that still applies. Check repeated mistakes on related reports, "
        "but do not extend this correction to unrelated areas."
    )


def _subject(report: SignalReport) -> str:
    # One line: the title is untrusted prompt input (the research agent writes it from ticket and
    # issue text), and a newline would let it pose as a new section of the note.
    title = " ".join((report.title or "").split())
    title_clause = f' ("{title[:_MAX_TITLE_CHARS]}")' if title else ""
    return f"report `{report.id}`{title_clause}."


def _listed(logins: Sequence[str]) -> str:
    return ", ".join(f"`{login}`" for login in logins)
