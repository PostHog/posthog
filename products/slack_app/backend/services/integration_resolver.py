from collections.abc import Iterable
from dataclasses import field
from typing import Literal

from django.db.models import Q

import structlog

from posthog.comment.formatting import escape_slack_mrkdwn
from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.user import User
from posthog.user_permissions import UserPermissions

from products.signals.backend.facade import api as signals_facade
from products.slack_app.backend.helpers import local_dev_slack_email
from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping
from products.slack_app.backend.services.slack_fork_context import get_pending_fork
from products.slack_app.backend.services.slack_scopes import bot_is_ready

logger = structlog.get_logger(__name__)

ResolutionSource = Literal[
    "thread",
    "user_default",
    "workspace_default",
    "sole_candidate",
    "needs_picker",
]

UserResolutionFailure = Literal["user_not_found", "no_team_access"]


def user_resolution_failure_reply(
    failure_reason: UserResolutionFailure | None, *, slack_email: str | None
) -> str | None:
    """Map a ``UserAndIntegrationsResolution.failure_reason`` to the user-facing
    text, mentioning ``slack_email`` when known so the user sees which address
    PostHog tried to match. Returns ``None`` for unknown values so callers can
    no-op safely until a new failure mode is wired up here.

    Wording mirrors the per-integration ``resolve_slack_user`` precedent in
    ``api.py`` — same "Sorry, …" register, same actionable next step.
    """
    if failure_reason == "user_not_found":
        if slack_email:
            return (
                f"Sorry, I couldn't find {slack_email} in any PostHog organization connected to this "
                "Slack workspace. Ask an admin to invite you, then mention me again."
            )
        return (
            "Sorry, I couldn't find your email address in Slack. "
            "Please make sure your email is visible in your Slack profile."
        )
    if failure_reason == "no_team_access":
        # The membership lookup succeeded by email, so it's always known here.
        subject = slack_email or "your account"
        return (
            f"Sorry, {subject} doesn't have access to any PostHog project connected to this Slack "
            "workspace. Ask an admin to grant you access, then try again."
        )
    return None


def _resolved_or_oldest(integration: Integration | None, candidates: list[Integration]) -> Integration | None:
    """The resolved integration, falling back to the oldest install in `candidates`.

    Surfaces that must act on *some* integration rather than prompt for one share this
    tie-break, so a workspace with no saved pick is answered for the same project
    whichever surface handles it. Ordered by id rather than taken off the front of
    `candidates`: the auth filter sorts that list freshest-verdict-first, which
    reshuffles as cache entries expire and would make the fallback drift.
    """
    if integration is not None and integration in candidates:
        return integration
    return min(candidates, key=lambda candidate: candidate.id, default=None)


@frozen
class ResolutionResult:
    integration: Integration | None
    source: ResolutionSource
    candidates: list[Integration] = field(default_factory=list)

    def resolved_or_first(self) -> Integration | None:
        """The resolved integration, falling back to the workspace's oldest install."""
        return _resolved_or_oldest(self.integration, self.candidates)


def project_label(integration: Integration) -> str:
    """One project named the way every Slack surface names it.

    Shared so a prompt that lists candidates and names a default in prose cannot spell
    the two differently, which would break the comparison it asks the model to make.
    """
    return f"{integration.team.organization.name} · {integration.team.name}"


def format_project_candidate_list(candidates: list[Integration], *, first: Integration | None = None) -> str:
    """One line per project, ``first`` at the head of the list.

    The order is otherwise ``check_integrations_auth_and_filter``'s, which sorts by
    freshest auth verdict and so reshuffles as cache entries expire. Leading with the
    project a caller is already on gives the list its one stable landmark.

    Every line carries the project's own name and nothing else. A caller marking one of
    them says so around the list, by id, because a team may be called anything at all —
    including whatever that marker would have been.

    ``first`` outside ``candidates`` is ignored rather than prepended: for the classifier
    this list and the reply schema's enum have to offer the same projects.
    """
    if first is not None and any(c.id == first.id for c in candidates):
        candidates = [first, *(c for c in candidates if c.id != first.id)]
    return "\n".join(f"• `{c.team_id}` — {project_label(c)}" for c in candidates)


def pick_a_project_message(
    intro: str,
    candidates: list[Integration],
    *,
    set_command: str,
    home_tab_url: str | None,
) -> str:
    """A "which project?" reply: every project the caller can route to, then the two ways
    to choose one.

    The Home tab leads because it is one click on a dropdown, against a command that asks
    the reader to copy an id out of the list above it. ``home_tab_url`` degrades to plain
    text for an install that carries no app id, which is the one case ``app_home_url``
    cannot build a deep link for.
    """
    # Organization and team names are tenant text, and this reply lands in a channel
    # thread, so an unescaped `<!channel>` in a name broadcasts to everyone reading it and
    # `<url|label>` renders a link they read as the bot's. Escaped on the way out rather
    # than inside `format_project_candidate_list`, because that helper also builds an LLM
    # prompt, which needs the plain name.
    projects = escape_slack_mrkdwn(format_project_candidate_list(candidates))
    home_tab = f"<{home_tab_url}|Home tab>" if home_tab_url else "Home tab"
    return (
        f"{intro}\n"
        f"{projects}\n\n"
        f"Pick one on the app's {home_tab}, or set your default with `{set_command} project <id>`."
    )


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
    if user is None:
        accessible_team_ids: set[int] | None = None
        accessible = candidates
    else:
        accessible = accessible_candidates(candidates, user=user)
        accessible_team_ids = {c.team_id for c in accessible}
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

        for candidate in accessible:
            if get_pending_fork(candidate.id, channel, thread_ts) is not None:
                return ResolutionResult(integration=candidate, source="thread", candidates=accessible)

        report_team_id = signals_facade.report_team_id_for_slack_thread(
            team_ids=[candidate.team_id for candidate in accessible],
            slack_workspace_id=slack_team_id,
            channel=channel,
            thread_ts=thread_ts,
        )
        if report_team_id is not None:
            return ResolutionResult(
                integration=candidates_by_team_id[report_team_id], source="thread", candidates=accessible
            )

    if slack_user_id:
        # One query returns at most two rows: the per-user row and the
        # workspace-wide row. Sorting with NULL-last puts the per-user row first.
        defaults = list(
            SlackSettings.objects.filter(slack_workspace_id=slack_team_id)
            .filter(Q(slack_user_id=slack_user_id) | Q(slack_user_id__isnull=True))
            .exclude(default_integration__isnull=True)
            .select_related(
                "default_integration",
                "default_integration__team",
                "default_integration__team__organization",
            )
        )
        defaults.sort(key=lambda d: d.slack_user_id is None)
        for default in defaults:
            target = default.default_integration
            if target is None:
                continue
            if accessible_team_ids is not None and target.team_id not in accessible_team_ids:
                continue
            # Refuse a stale default whose target is no longer in the candidate
            # set — e.g. the integration's kind was changed away from the one
            # we were asked to resolve, or it was deleted+recreated. The user
            # can overwrite the row at any time with `/posthog project <id>`.
            if target.id not in candidate_ids:
                continue
            source: ResolutionSource = "user_default" if default.slack_user_id else "workspace_default"
            return ResolutionResult(integration=target, source=source, candidates=accessible)

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
    from products.slack_app.backend.services.slack_auth import check_integrations_auth_and_filter

    candidates = list(
        Integration.objects.filter(kind__in=kinds, integration_id=slack_team_id)
        .select_related("team", "team__organization", "created_by")
        .order_by("id")
    )
    candidates = check_integrations_auth_and_filter(candidates, slack_user_id=slack_user_id or None)
    return resolve_from_candidates(
        candidates,
        slack_team_id=slack_team_id,
        slack_user_id=slack_user_id,
        user=user,
        channel=channel,
        thread_ts=thread_ts,
    )


def accessible_candidates(candidates: Iterable[Integration], *, user: User) -> list[Integration]:
    """The candidates whose project this user is a member of.

    Per-team ``effective_membership_level`` rather than ``user.teams``: the latter keys
    its access-control filter off a single arbitrary ``Organization.first()`` row's
    feature flags, so a user whose AC-enabled org isn't the one picked sees private
    projects from that org.
    """
    permissions = UserPermissions(user=user)
    return [c for c in candidates if permissions.team(c.team).effective_membership_level is not None]


def multiple_accessible_projects(*, slack_team_id: str, user: User) -> bool:
    """Whether this user can open more than one of the workspace's projects.

    Membership alone, with no scope or reachability check: a caller asking only whether
    there is anything to tell apart should not pay an ``auth.test`` per candidate.
    ``routable_projects`` asks the stricter question of where a run may actually be sent.
    """
    installs = Integration.objects.filter(kind="slack", integration_id=slack_team_id)
    # Accessible is a subset of installed, so one install settles it without the
    # membership scan — on a count, which reads an index rather than hydrating and
    # decrypting every row.
    if installs.count() < 2:
        return False
    return len(accessible_candidates(installs.select_related("team"), user=user)) > 1


def routable_projects(*, slack_team_id: str, slack_user_id: str, user: User) -> list[Integration]:
    """The projects a message from this user may route itself to, in this workspace.

    Empty when there is nothing to choose between, which is the common answer. Installs
    missing the scopes the mention flow needs are dropped: routing onto one would trade a
    working run for a project the app cannot post into. That is stricter than the saved
    default, which may point anywhere — there is a difference between a project someone
    chose and one we moved them to.

    Callers must already have established that the message opens a thread. Project is
    fixed for the life of a thread, and this does not check that.
    """
    candidates = load_integrations(
        slack_team_id=slack_team_id,
        kinds=["slack"],
        slack_user_id=slack_user_id,
        user=user,
    ).candidates
    reachable = [candidate for candidate in candidates if bot_is_ready(candidate)]
    return reachable if len(reachable) > 1 else []


@frozen
class UserAndIntegrationsResolution:
    """Outcome of the user identification + access-filter step.

    ``user`` is ``None`` when no PostHog user resolved or none had access — both
    cases are silently logged inside ``resolve_user_for_workspace`` under
    ``posthog_code_no_integration_found``, and the specific case is exposed via
    ``failure_reason`` so the caller can post an actionable reply in-thread.
    ``integration`` and ``candidates`` are only populated on the happy path;
    ``source`` mirrors ``ResolutionResult.source`` (or ``needs_picker`` if the
    resolved target was inaccessible and got dropped).
    """

    user: User | None = None
    integration: Integration | None = None
    candidates: list[Integration] = field(default_factory=list)
    source: ResolutionSource = "needs_picker"
    failure_reason: UserResolutionFailure | None = None
    slack_email: str | None = None

    def resolved_or_first(self) -> Integration | None:
        """The integration this resolution picked, falling back to the oldest one the user can reach."""
        return _resolved_or_oldest(self.integration, self.candidates)


def resolve_user_for_workspace(
    *,
    workspace_result: ResolutionResult,
    slack_team_id: str,
    slack_user_id: str,
    event_id: str | None = None,
) -> UserAndIntegrationsResolution:
    """Given a pre-loaded workspace ``ResolutionResult``, identify the acting
    Slack user and filter the workspace candidates down to ones they can
    access. Split from ``resolve_user_and_integrations`` so the caller can
    decide region routing (proxy / drop) before paying for the Slack API hit
    and the membership query.
    """
    # The user resolver lives in api.py alongside the Slack-API helpers it
    # depends on (``get_slack_user_info`` etc). Inline-imported to break the
    # cycle until those helpers are factored out into a shared module.
    from products.slack_app.backend.api import get_slack_email_for_user, resolve_posthog_user_from_event

    if not slack_user_id:
        logger.warning(
            "slack_app_no_integration_found",
            reason="user_not_found",
            slack_team_id=slack_team_id,
            slack_user_id=None,
            event_id=event_id,
        )
        return UserAndIntegrationsResolution(failure_reason="user_not_found")

    probe = workspace_result.candidates[0]

    # In local dev, match the seeded user the single-integration resolver also
    # uses. Keep this at the resolver layer so lower-level callers like channel
    # approval can still exercise real or stubbed Slack emails under DEBUG.
    slack_email = local_dev_slack_email()

    # Pass slack_email=None outside local dev so the linked-user path
    # short-circuits before users.info; the resolver fetches lazily on the
    # email-fallback branch. Re-fetch on the failure branches below is a cache
    # hit.
    posthog_user = resolve_posthog_user_from_event(
        slack_user_id=slack_user_id,
        probe_integration=probe,
        candidate_integrations=workspace_result.candidates,
        slack_email=slack_email,
    )
    if posthog_user is None:
        slack_email = get_slack_email_for_user(probe, slack_user_id)
        logger.warning(
            "slack_app_no_integration_found",
            reason="user_not_found",
            slack_team_id=slack_team_id,
            slack_user_id=slack_user_id,
            event_id=event_id,
        )
        return UserAndIntegrationsResolution(failure_reason="user_not_found", slack_email=slack_email)

    # A resolved target the user can't reach is dropped so the caller falls through to
    # the picker / sole-candidate path rather than auto-redirecting to a default the
    # thread didn't imply.
    reachable_candidates = accessible_candidates(workspace_result.candidates, user=posthog_user)
    accessible_team_ids = {c.team_id for c in reachable_candidates}
    if not reachable_candidates:
        # Fetch slack_email lazily for the failure reply (cached after the
        # earlier resolve_posthog_user_from_event call, so this is free).
        slack_email = get_slack_email_for_user(probe, slack_user_id)
        logger.warning(
            "slack_app_no_integration_found",
            reason="no_team_access",
            slack_team_id=slack_team_id,
            slack_user_id=slack_user_id,
            user_id=posthog_user.id,
            event_id=event_id,
        )
        return UserAndIntegrationsResolution(failure_reason="no_team_access", slack_email=slack_email)

    target = (
        workspace_result.integration
        if workspace_result.integration is not None and workspace_result.integration.team_id in accessible_team_ids
        else None
    )
    return UserAndIntegrationsResolution(
        user=posthog_user,
        integration=target,
        candidates=reachable_candidates,
        source=workspace_result.source if target is not None else "needs_picker",
    )
