"""The person's recent inbox activity: what they did with inbox reports, as one block of the ranking prompt.

The block reads the rows of the activity summary (`user_inbox`) and applies its rules (`inbox_facts`), but
each build reads them again, so a claim or a dismissal from this morning reaches the next build. A line about
a candidate carries the candidate's ref.

Only facts of strength `RATED` or stronger go into the input hash, with no ages. An open or a Slack
discussion shows in the next build, but it does not start one.
"""

import datetime
from collections import Counter
from collections.abc import Sequence
from typing import Any

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.activity_summary.inputs import user_inbox
from products.signals.backend.activity_summary.render import InboxActivity, InboxStrength, clean_text, inbox_facts
from products.signals.backend.models import SignalReviewerExclusion
from products.signals.backend.personal_ranking.candidates import Candidate
from products.signals.backend.personal_ranking.config import PersonalRankingConfig

HASHED_MIN_STRENGTH = InboxStrength.RATED
_AREA_CHARS = 200


@frozen
class InboxActivityLine:
    # The ref of the candidate that the line is about, or None for another report or a bulk triage.
    ref: str | None
    report_ids: frozenset[str]
    # None for a bulk triage.
    title: str | None
    # The facts at or above the minimum strength, strongest first, then newest.
    facts: tuple[str, ...]
    strength: InboxStrength
    # The latest shown fact.
    at: datetime.datetime
    # The facts that go into the input hash.
    hashed_facts: tuple[str, ...]


@frozen
class ReviewerExclusionArea:
    # Empty for every repository.
    repository: str
    path_prefix: str


@frozen
class InboxActivityBlock:
    lines: tuple[InboxActivityLine, ...] = ()
    exclusions: tuple[ReviewerExclusionArea, ...] = ()

    def hash_part(self) -> dict[str, Any]:
        return {
            "facts": sorted(
                [sorted(line.report_ids), sorted(line.hashed_facts)] for line in self.lines if line.hashed_facts
            ),
            "exclusions": sorted([area.repository, area.path_prefix] for area in self.exclusions),
        }

    def properties(self) -> dict[str, Any]:
        strengths = Counter(line.strength.name.lower() for line in self.lines)
        return {
            "inbox_activity_lines": len(self.lines),
            "inbox_activity_candidate_lines": sum(1 for line in self.lines if line.ref is not None),
            "inbox_activity_strength_counts": dict(strengths),
            "inbox_activity_exclusion_lines": len(self.exclusions),
        }


def _exclusions(team: Team, user: User, limit: int) -> tuple[ReviewerExclusionArea, ...]:
    rows = (
        SignalReviewerExclusion.objects.for_team(team.id)
        .filter(subject_user_uuid=user.uuid, status=SignalReviewerExclusion.Status.ACTIVE)
        .order_by("-updated_at", "-id")
        .values_list("repository", "path_prefix")[:limit]
    )
    return tuple(
        ReviewerExclusionArea(
            repository=clean_text(repository, _AREA_CHARS), path_prefix=clean_text(path_prefix, _AREA_CHARS)
        )
        for repository, path_prefix in rows
    )


def inbox_activity_block(
    inbox: InboxActivity,
    config: PersonalRankingConfig,
    *,
    candidates: Sequence[Candidate] = (),
    exclusions: tuple[ReviewerExclusionArea, ...] = (),
) -> InboxActivityBlock:
    """At most `inbox_activity_lines` lines, the strongest fact first, then the newest, with the facts at or above
    `inbox_activity_min_strength`."""
    refs = {candidate.report_id: candidate.ref for candidate in candidates}
    ranked: list[tuple[tuple[float, float, str], InboxActivityLine]] = []
    for entry in inbox_facts(inbox, Counter()):
        shown = [fact for fact in entry.facts if fact.strength >= config.inbox_activity_min_strength]
        if not shown:
            continue
        line = InboxActivityLine(
            ref=refs.get(next(iter(entry.report_ids))) if entry.title is not None else None,
            report_ids=entry.report_ids,
            title=entry.title,
            facts=tuple(dict.fromkeys(fact.text for fact in shown)),
            strength=shown[0].strength,
            at=max(fact.at for fact in shown),
            hashed_facts=tuple(dict.fromkeys(fact.text for fact in shown if fact.strength >= HASHED_MIN_STRENGTH)),
        )
        # The strongest fact orders the lines, so a newer open never moves a hashed line past the cap.
        ranked.append(((-shown[0].strength, -shown[0].at.timestamp(), entry.title or ""), line))
    ranked.sort(key=lambda item: item[0])
    return InboxActivityBlock(
        lines=tuple(line for _, line in ranked[: config.inbox_activity_lines]), exclusions=exclusions
    )


def read_inbox_activity(
    team: Team,
    user: User,
    config: PersonalRankingConfig,
    *,
    now: datetime.datetime,
    candidates: Sequence[Candidate] = (),
) -> InboxActivityBlock | None:
    """The block, or None when `inbox_activity_lines` is 0. Three queries, each filtered on the person."""
    if config.inbox_activity_lines <= 0:
        return None
    start = now - datetime.timedelta(days=config.inbox_activity_days)
    return inbox_activity_block(
        user_inbox(team.id, user.id, start, now),
        config,
        candidates=candidates,
        exclusions=_exclusions(team, user, config.inbox_activity_exclusion_lines),
    )
