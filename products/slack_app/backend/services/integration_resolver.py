from dataclasses import dataclass, field
from typing import Literal

from django.db.models import Q

from posthog.models.integration import Integration
from posthog.models.user import User

from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping

ResolutionSource = Literal[
    "thread",
    "user_default",
    "workspace_default",
    "sole_candidate",
    "needs_picker",
]


@dataclass
class ResolutionResult:
    integration: Integration | None
    source: ResolutionSource
    candidates: list[Integration] = field(default_factory=list)


def format_project_candidate_list(candidates: list[Integration]) -> str:
    return "\n".join(f"• `{c.team_id}` — {c.team.organization.name} · {c.team.name}" for c in candidates)


def resolve_from_candidates(
    candidates: list[Integration],
    *,
    slack_team_id: str,
    slack_user_id: str = "",
    user: User | None = None,
    channel: str | None = None,
    thread_ts: str | None = None,
) -> ResolutionResult:
    """Run the routing resolver over a pre-loaded candidate list.

    Precedence: ``thread`` > ``user_default`` > ``workspace_default`` >
    ``sole_candidate`` > ``needs_picker``.

    When ``user`` is provided, defaults whose target is no longer accessible
    silently fall through. When ``user is None`` the resolver trusts saved
    defaults as-is and treats every workspace integration as a candidate.

    Callers that don't need routing (e.g. link_shared / unfurl) can pass
    ``slack_user_id=""``; the SlackSettings lookup is skipped and the result
    falls through to ``sole_candidate`` / ``needs_picker``.
    """
    accessible_team_ids: set[int] | None = set(user.teams.values_list("id", flat=True)) if user is not None else None
    accessible = (
        candidates if accessible_team_ids is None else [i for i in candidates if i.team_id in accessible_team_ids]
    )
    candidate_ids = {c.id for c in candidates}
    candidates_by_team_id = {c.team_id: c for c in candidates}

    if channel and thread_ts and slack_team_id:
        thread_match = (
            SlackThreadTaskMapping.objects.filter(
                slack_workspace_id=slack_team_id, channel=channel, thread_ts=thread_ts
            )
            .select_related("integration")
            .first()
        )
        if thread_match is not None:
            # If the mapped row is out of the current candidate set (kind drift),
            # route through the canonical candidate for the same team in this
            # workspace so the mapping's ``task_run`` linkage stays intact.
            mapped = thread_match.integration
            target: Integration | None = (
                mapped if mapped.id in candidate_ids else candidates_by_team_id.get(mapped.team_id)
            )
            # Access check on the resolved target so a user whose access was
            # revoked can't ride the thread mapping past the gate.
            if target is not None and (accessible_team_ids is None or target.team_id in accessible_team_ids):
                return ResolutionResult(integration=target, source="thread", candidates=accessible)

    if slack_user_id:
        # One query returns at most two rows: the per-user row and the
        # workspace-wide row. Sorting with NULL-last puts the per-user row first.
        defaults = list(
            SlackSettings.objects.filter(slack_workspace_id=slack_team_id)
            .filter(Q(slack_user_id=slack_user_id) | Q(slack_user_id__isnull=True))
            .select_related(
                "default_integration",
                "default_integration__team",
                "default_integration__team__organization",
            )
        )
        defaults.sort(key=lambda d: d.slack_user_id is None)
        for default in defaults:
            if accessible_team_ids is not None and default.default_integration.team_id not in accessible_team_ids:
                continue
            # Refuse a stale default whose target is no longer in the candidate
            # set — e.g. the integration's kind was changed away from the one
            # we were asked to resolve, or it was deleted+recreated. The user
            # can overwrite the row at any time with `@PostHog project <id>`.
            if default.default_integration.id not in candidate_ids:
                continue
            source: ResolutionSource = "user_default" if default.slack_user_id else "workspace_default"
            return ResolutionResult(integration=default.default_integration, source=source, candidates=accessible)

    if len(accessible) == 1:
        return ResolutionResult(integration=accessible[0], source="sole_candidate", candidates=accessible)
    return ResolutionResult(integration=None, source="needs_picker", candidates=accessible)


def load_integrations(
    *,
    slack_team_id: str,
    kinds: list[str],
    slack_user_id: str = "",
    user: User | None = None,
    channel: str | None = None,
    thread_ts: str | None = None,
) -> ResolutionResult:
    """Load Slack integrations of the given ``kinds`` for a workspace, then run
    the routing resolver against them. Thin wrapper around
    ``resolve_from_candidates`` that owns the candidate query.
    """
    candidates = list(
        Integration.objects.filter(kind__in=kinds, integration_id=slack_team_id)
        .select_related("team", "team__organization", "created_by")
        .order_by("id")
    )
    return resolve_from_candidates(
        candidates,
        slack_team_id=slack_team_id,
        slack_user_id=slack_user_id,
        user=user,
        channel=channel,
        thread_ts=thread_ts,
    )
