import logging
from typing import Literal

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users

logger = logging.getLogger(__name__)

# Pipeline suggestions are capped at MAX_SUGGESTED_REVIEWERS, but scout assignee lists are
# model-proposed and unbounded, so cap what reaches event properties.
_MAX_LOGINS_PER_EVENT = 10

ReviewerSuggestionSource = Literal["pipeline", "scout"]


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
            logger.info(
                "suggested reviewers for report %s (team %d) include %d login(s) with no PostHog user: %s",
                report_id,
                team_id,
                len(linkability.unlinkable_logins),
                ", ".join(linkability.unlinkable_logins),
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
