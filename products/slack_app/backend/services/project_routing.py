"""Which PostHog projects a Slack message is allowed to route itself to.

A workspace connected to several projects answers every mention from one saved default
(see `integration_resolver`). This module answers the narrower question the default
cannot: given the mentioner and the message, which projects may the message name instead.

It decides eligibility only. Reading a project out of the text is the classifier's job,
in `posthog/temporal/ai/slack_app/activities/classifiers.py`.
"""

from __future__ import annotations

import structlog

from posthog.dataclasses import frozen
from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES, has_scopes
from posthog.models.integration import Integration
from posthog.models.user import User

from products.slack_app.backend.feature_flags import is_slack_app_project_routing_enabled

logger = structlog.get_logger(__name__)

SLACK_INTEGRATION_KIND = "slack"


@frozen
class ProjectChoice:
    """A project a message may route itself to.

    `team_id` is the id offered to the classifier and named in its reply, because it is
    also the id a person types into `@PostHog project <id>`, so both surfaces agree on
    what identifies a project. `integration_id` is what the run is rebound to.
    """

    team_id: int
    integration_id: int
    label: str


def routable_projects(
    *,
    slack_team_id: str,
    slack_user_id: str,
    user: User,
    default: Integration,
) -> tuple[ProjectChoice, ...]:
    """The projects this mentioner may route a message to, or empty when none may be.

    Empty when the workspace has not opted in, or when only one project is reachable.

    Candidates are bounded by the mentioner's per-team access, which `load_integrations`
    applies. Installs missing the scopes the mention flow needs are dropped too, because
    routing onto one would trade a working run for a project the app cannot post into.

    Callers must already have established that the message opens a thread. Project is
    fixed for the life of a thread, and this function does not check that.
    """
    from products.slack_app.backend.services.integration_resolver import load_integrations

    if not is_slack_app_project_routing_enabled(default, distinct_id=user.distinct_id):
        return ()

    candidates = load_integrations(
        slack_team_id=slack_team_id,
        kinds=[SLACK_INTEGRATION_KIND],
        slack_user_id=slack_user_id,
        user=user,
    ).candidates
    reachable = [candidate for candidate in candidates if has_scopes(candidate, REQUIRED_SLACK_SCOPES)]
    if len(reachable) < 2:
        return ()
    return tuple(
        ProjectChoice(
            team_id=candidate.team_id,
            integration_id=candidate.id,
            label=f"{candidate.team.organization.name} · {candidate.team.name}",
        )
        for candidate in reachable
    )


def render_project_candidates(projects: tuple[ProjectChoice, ...]) -> str:
    """The projects on offer, one per line, in the same shape the pick-a-project hint
    posts into Slack so a person reading both sees the same list."""
    return "\n".join(f"- {project.team_id} — {project.label}" for project in projects)
