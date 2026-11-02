"""The person a report routes to when no evidence selected anyone.

A report with no suggested reviewers notifies nobody: no Slack mention, no push, and no "For you"
entry. The default owner gives that report one accountable person. The entry carries
`is_default_owner`, so readers can tell it from an evidence-based pick, and its removal does not
teach routing anything.
"""

from __future__ import annotations

import json

from django.db import transaction

import structlog

from posthog.models import Team, User
from posthog.models.organization import OrganizationMembership

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ReviewerProposal, SuggestedReviewerEntry, SuggestedReviewers
from products.signals.backend.assignment_flags import default_owner_fallback_enabled
from products.signals.backend.github_optional import team_has_code_access
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalScoutConfig,
    SignalSourceConfig,
    SignalTeamConfig,
)
from products.signals.backend.report_access import may_read_reports
from products.signals.backend.reviewer_rules import (
    ReviewerRules,
    ReviewerWriteError,
    StaleReviewerProposal,
    contains_reviewer,
)
from products.signals.backend.scout_authorship import report_is_hidden_from_inbox, resolve_report_scout_skill
from products.signals.backend.scout_harness.skill_loader import resolve_skill_owner_user_uuids

logger = structlog.get_logger(__name__)

DEFAULT_OWNER_REASON = "No reviewer matched the evidence for this report, so it went to the default owner."


def accountable_candidate_ids(team_id: int) -> list[int]:
    """Who answers for signals on this team, most accountable first.

    Restricted at every tier to *active* org members (still in the org and not deactivated),
    because callers act as this user and a departed or disabled account must not:

    1. The members who enabled a ``SignalSourceConfig`` for this team, earliest source first,
       which is who turned signals on.
    2. The organization's owner, then its admins, which is the accountable human for an org that
       is clearly running signals.

    Both tiers are returned, not just the first that matches: sources enabled by a system path
    leave ``created_by`` null, and an enabler can also have lost access to the project since, so a
    caller that rejects a candidate still has somewhere to go.

    Deterministic within each tier so concurrent evaluations pick the same user.
    """
    org_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    if org_id is None:
        return []

    active_member_ids = OrganizationMembership.objects.filter(organization_id=org_id, user__is_active=True).values_list(
        "user_id", flat=True
    )

    enabler_ids = (
        SignalSourceConfig.objects.filter(team_id=team_id, created_by_id__in=active_member_ids)
        .order_by("created_at")
        .values_list("created_by_id", flat=True)
    )
    admin_ids = (
        OrganizationMembership.objects.filter(
            organization_id=org_id,
            user__is_active=True,
            level__gte=OrganizationMembership.Level.ADMIN,
        )
        .order_by("-level", "user_id")
        .values_list("user_id", flat=True)
    )
    return list(dict.fromkeys([*enabler_ids, *admin_ids]))


def resolve_signals_enabler(team_id: int) -> User | None:
    """The human who turned signals on for this team, or the org's accountable admin.

    The first of `accountable_candidate_ids`, for a caller that can only act as one person. A
    caller that can reject a candidate on its own terms walks the whole list instead.
    """
    candidate_id = next(iter(accountable_candidate_ids(team_id)), None)
    if candidate_id is None:
        return None
    return User.objects.filter(id=candidate_id).first()


def _scout_owner_ids(team: Team, report_id: str) -> list[int]:
    skill_name = resolve_report_scout_skill(team.id, report_id)
    if not skill_name:
        return []
    # The configured owners come first: that list is the durable answer to who reviews a scout's
    # reports, while the config only records who switched the scout on.
    owner_uuids = resolve_skill_owner_user_uuids(team, skill_name)
    ids_by_uuid = {
        str(uuid): user_id for uuid, user_id in User.objects.filter(uuid__in=owner_uuids).values_list("uuid", "id")
    }
    owner_ids = [ids_by_uuid[uuid] for uuid in owner_uuids if uuid in ids_by_uuid]
    # Scout rows live under the canonical parent team, while the report can sit in a child environment.
    canonical_team_id = team.parent_team_id or team.id
    row = (
        SignalScoutConfig.objects.for_team(canonical_team_id)
        .filter(skill_name=skill_name)
        .values_list("enabled_by_id", "created_by_id")
        .first()
    )
    return [*owner_ids, *(user_id for user_id in row or () if user_id is not None)]


def _activator_ids(team: Team) -> list[int]:
    team_ids = [team.id] + ([team.parent_team_id] if team.parent_team_id else [])
    onboarding_by_team = dict(
        SignalTeamConfig.objects.filter(team_id__in=team_ids).values_list("team_id", "onboarding")
    )
    ids: list[int] = []
    for team_id in team_ids:
        activated_by = (onboarding_by_team.get(team_id) or {}).get("activated_by")
        if isinstance(activated_by, int):
            ids.append(activated_by)
    return ids


def resolve_default_owner(team: Team, report_id: str) -> User | None:
    """The first eligible person among the authoring scout's owners, the Self-Driving activator, and the enablers.

    The scout owners come first because those people asked for this kind of report. Every candidate
    must be an active member who can read the project's reports when the fallback runs, not only
    when the candidate was recorded, so each tier offers everyone it has rather than only its best
    pick. Report access is checked as well as project access, because the entry puts the report in
    front of whoever it names: a Slack card, a push, and a "For you" row.
    """
    candidate_ids = [
        *_scout_owner_ids(team, report_id),
        *_activator_ids(team),
        *accountable_candidate_ids(team.id),
    ]
    candidate_ids = list(dict.fromkeys(candidate_ids))
    if not candidate_ids:
        return None
    candidates = {user.id: user for user in User.objects.filter(id__in=candidate_ids, is_active=True)}
    if not candidates:
        return None
    eligible = {
        user.id for user in team.all_users_with_access(user_uuids={str(user.uuid) for user in candidates.values()})
    }
    # Lazily, so a report whose first candidate is eligible costs one access-control resolution.
    return next(
        (
            candidates[user_id]
            for user_id in candidate_ids
            if user_id in eligible and may_read_reports(user=candidates[user_id], team=team)
        ),
        None,
    )


def _reviewers_were_curated(team_id: int, report_id: str) -> bool:
    """Whether a person already edited this report's reviewers, or the default owner was already assigned once.

    Either way the fallback must stay out. Without this check, a person who removes the default
    owner would get them back on the next notification settle.
    """
    rows = SignalReportArtefact.objects.filter(
        team_id=team_id, report_id=report_id, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
    ).values_list("actor_kind", "created_by_id", "content")
    for actor_kind, created_by_id, content in rows:
        if actor_kind == "user" or (actor_kind is None and created_by_id is not None):
            return True
        try:
            entries = json.loads(content)
        except (TypeError, ValueError):
            continue
        if isinstance(entries, list) and any(isinstance(e, dict) and e.get("is_default_owner") for e in entries):
            return True
    return False


def assign_default_owner(team: Team, report_id: str) -> bool:
    """Route a report that has no reviewers to its default owner. Returns whether it wrote one."""
    if not default_owner_fallback_enabled(team.id):
        return False
    # Where a repository is in reach, commit history names a relevant reviewer often enough that
    # leaving the occasional report unassigned is better than sending it to whoever switched the
    # scout on.
    if team_has_code_access(team.id):
        return False
    # The authoring scout sends these reports to another audience, so nobody in the project owns them.
    if report_is_hidden_from_inbox(team.id, report_id):
        return False
    try:
        # `expected_state` only guards the write once the assignment writer is enrolled, so on the
        # legacy path the checks below are the whole guard. They hold until the write lands only
        # while this transaction holds the report row, which is the same row `append_status` locks
        # and so costs nothing extra. Without it a person's edit that commits in between is lost.
        with transaction.atomic():
            SignalReport.objects.select_for_update().get(team_id=team.id, id=report_id)
            snapshot = ReviewerRules.read_for_report(team_id=team.id, report_id=report_id)
            if snapshot.reviewers or snapshot.invalid_reviewers:
                return False
            if _reviewers_were_curated(team.id, report_id):
                return False
            owner = resolve_default_owner(team, report_id)
            if owner is None:
                return False
            entry = SuggestedReviewerEntry(
                user_uuid=str(owner.uuid),
                reason=DEFAULT_OWNER_REASON,
                is_default_owner=True,
            )
            if contains_reviewer(snapshot.corrections.excluded, entry):
                return False
            artefact = SignalReportArtefact.append_status(
                team_id=team.id,
                report_id=report_id,
                content=SuggestedReviewers(root=[entry]),
                attribution=ArtefactAttribution.system(),
                # Autostart never runs as a default owner, so this write cannot change its decision.
                reevaluate_autostart=False,
                reviewer_proposal=ReviewerProposal(expected_state=snapshot.state, source="default_owner"),
            )
    except (StaleReviewerProposal, ReviewerWriteError):
        logger.info("signals.default_owner.skipped_concurrent_write", team_id=team.id, report_id=report_id)
        return False
    wrote = artefact.id != snapshot.state.reviewers_id and bool(json.loads(artefact.content))
    if wrote:
        logger.info("signals.default_owner.assigned", team_id=team.id, report_id=report_id)
    return wrote
