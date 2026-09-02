import logging
import dataclasses
from typing import Literal

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.report_generation.resolve_reviewers import (
    ReviewerResolutionDiagnostics,
    resolve_org_github_login_to_users,
)

logger = logging.getLogger(__name__)

# Pipeline suggestions are capped at MAX_SUGGESTED_REVIEWERS, but scout assignee lists are
# model-proposed and unbounded, so cap what reaches event properties.
_MAX_LOGINS_PER_EVENT = 10

ReviewerSuggestionSource = Literal["pipeline", "scout", "scout_edit", "custom_agent", "user_edit", "api"]


@frozen
class ReviewerLinkability:
    linkable_logins: list[str]
    unlinkable_logins: list[str]


def split_reviewer_linkability(team_id: int, github_logins: list[str]) -> ReviewerLinkability:
    """Split suggested-reviewer GitHub logins by whether they resolve to an org member."""
    normalized = list(dict.fromkeys(login.strip().lower() for login in github_logins if login and login.strip()))
    login_to_user = resolve_org_github_login_to_users(team_id, normalized)
    return ReviewerLinkability(
        linkable_logins=[login for login in normalized if login in login_to_user],
        unlinkable_logins=[login for login in normalized if login not in login_to_user],
    )


def capture_suggested_reviewers_resolved(
    *,
    team_id: int,
    report_id: str,
    github_logins: list[str],
    source: ReviewerSuggestionSource,
) -> None:
    """Emit `signals_suggested_reviewers_resolved` when a report's suggested reviewers are persisted.

    Suggested reviewers are stored as bare GitHub logins; the login -> PostHog user mapping only
    happens downstream (Slack routing, autostart, API read), where an unmapped login falls through
    silently. A report whose logins map to nobody cannot be routed to a person, yet still counts as
    "assigned" in `suggested_reviewers`-based metrics. This event records the linkable/unlinkable
    split at suggestion time so that bucket is measurable.

    Best-effort: never raises, so analytics can't break report generation.
    """
    try:
        linkability = split_reviewer_linkability(team_id, github_logins)
        if linkability.unlinkable_logins:
            # GitHub logins are member PII, so logs carry counts only; the logins themselves go in
            # the event properties, the same internal-analytics surface the artefact already feeds.
            logger.info(
                "suggested reviewers for report %s (team %d): %d of %d login(s) have no PostHog user",
                report_id,
                team_id,
                len(linkability.unlinkable_logins),
                len(linkability.linkable_logins) + len(linkability.unlinkable_logins),
            )
        team = Team.objects.select_related("organization").get(id=team_id)
        posthoganalytics.capture(
            event="signals_suggested_reviewers_resolved",
            distinct_id=str(team.uuid),
            properties={
                "team_id": team_id,
                "report_id": report_id,
                "source": source,
                "suggested_count": len(linkability.linkable_logins) + len(linkability.unlinkable_logins),
                "linkable_count": len(linkability.linkable_logins),
                "unlinkable_count": len(linkability.unlinkable_logins),
                "linkable_logins": linkability.linkable_logins[:_MAX_LOGINS_PER_EVENT],
                "unlinkable_logins": linkability.unlinkable_logins[:_MAX_LOGINS_PER_EVENT],
                "all_unlinkable": bool(linkability.unlinkable_logins) and not linkability.linkable_logins,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception("Failed to capture signals_suggested_reviewers_resolved for report %s", report_id)


def capture_suggested_reviewers_unresolved(
    *,
    team_id: int,
    report_id: str,
    diagnostics: ReviewerResolutionDiagnostics,
    finding_count: int,
    has_new_finding: bool,
) -> None:
    """Emit `signals_suggested_reviewers_unresolved` when a pipeline run yields no reviewers.

    Nothing is persisted for an empty list, so this is the only record of *why* a report ended
    up with no one to route to: no repository, findings without commits, no reachable GitHub
    integration, or lookups that came back without an attributable author. Fires per run;
    read it as the latest event per `report_id`.

    Best-effort: never raises, so analytics can't break report generation.
    """
    try:
        logger.info(
            "no suggested reviewers for report %s (team %d): %s (%d commit hash(es), %d/%d lookups resolved)",
            report_id,
            team_id,
            diagnostics.outcome,
            diagnostics.commit_hash_count,
            diagnostics.lookups_resolved,
            diagnostics.lookups_attempted,
        )
        team = Team.objects.select_related("organization").get(id=team_id)
        posthoganalytics.capture(
            event="signals_suggested_reviewers_unresolved",
            distinct_id=str(team.uuid),
            properties={
                "team_id": team_id,
                "report_id": report_id,
                "source": "pipeline",
                "finding_count": finding_count,
                "has_new_finding": has_new_finding,
                **dataclasses.asdict(diagnostics),
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception("Failed to capture signals_suggested_reviewers_unresolved for report %s", report_id)
