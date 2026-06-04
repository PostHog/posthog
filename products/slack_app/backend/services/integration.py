"""Service layer for narrowing Slack workspace integrations against a PostHog user
at routing time.

The pipeline is two steps:

1. ``resolve_workspace_routing`` — workspace-level, user-agnostic. Loads candidates
   for the Slack workspace and applies thread/user-default/workspace-default
   precedence. Cheap and deterministic; safe to run before knowing the user.
2. ``apply_user_access`` — narrows the result to integrations the resolved
   PostHog user has team access to. Pure Python, no extra queries.

Downstream workflow activities then receive a fully resolved ``(user_id,
integration_ids)`` pair in their inputs and never need to re-run candidate
resolution. The legacy ``integration_resolver`` module stays around to back the
``inputs.user_id is None`` replay branch in the command workflow until the
Temporal history retention window for those workflows has elapsed; new code
should import from this module.
"""

from pydantic import BaseModel, ConfigDict

from posthog.models.integration import Integration
from posthog.models.user import User

from products.slack_app.backend.services.integration_resolver import (
    ResolutionResult,
    ResolutionSource,
    format_project_candidate_list,
    load_integrations,
    resolve_from_candidates,
)

__all__ = [
    "ResolutionResult",
    "ResolutionSource",
    "UserNarrowedResolution",
    "apply_user_access",
    "format_project_candidate_list",
    "load_integrations",
    "resolve_from_candidates",
    "resolve_workspace_routing",
]


class UserNarrowedResolution(BaseModel):
    """Routing result after the mentioning Slack user has been identified and the
    workspace candidate set has been filtered to integrations they can access.

    ``integration`` is the dispatch target — present iff the thread/default
    routing picked one and the user can access it. ``candidates`` is the
    accessible subset that the caller falls back on for picker / sole-candidate
    selection. ``source`` mirrors the upstream ``ResolutionResult.source``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user: User
    integration: Integration | None
    candidates: list[Integration]
    source: ResolutionSource


def resolve_workspace_routing(
    *,
    slack_team_id: str,
    kinds: list[str],
    slack_user_id: str = "",
    channel: str | None = None,
    thread_ts: str | None = None,
) -> ResolutionResult:
    """Workspace-level routing: candidates + thread/default precedence, user-agnostic.

    Wraps ``load_integrations`` with ``user=None``. The result still needs to go
    through ``apply_user_access`` once the mentioning user has been identified.
    """
    return load_integrations(
        slack_team_id=slack_team_id,
        kinds=kinds,
        slack_user_id=slack_user_id,
        user=None,
        channel=channel,
        thread_ts=thread_ts,
    )


def apply_user_access(result: ResolutionResult, user: User) -> ResolutionResult:
    """Narrow a ``ResolutionResult`` to integrations ``user`` has team access to.

    The resolved target is dropped when the user can't access it, so the caller
    falls through to the picker / sole-candidate path against the accessible
    subset rather than auto-redirecting to a default the thread didn't imply.
    """
    accessible_team_ids = set(user.teams.values_list("id", flat=True))
    accessible_candidates = [c for c in result.candidates if c.team_id in accessible_team_ids]
    target = (
        result.integration
        if result.integration is not None and result.integration.team_id in accessible_team_ids
        else None
    )
    return ResolutionResult(
        integration=target,
        source=result.source if target is not None else "needs_picker",
        candidates=accessible_candidates,
    )
