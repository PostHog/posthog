import logging
from dataclasses import dataclass

from posthog.git import extract_explicit_repo, extract_linked_repo
from posthog.models.team import Team
from posthog.sync import database_sync_to_async

from products.tasks.backend.logic.repo_selection.agent import _list_candidate_repos, resolve_team_github_integration
from products.tasks.backend.models import Task

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CascadeTierResult:
    repository: str
    tier: str  # "single_repo" | "explicit_token" | "linked_url"


def cascade_select_repository(
    team_id: int,
    user_id: int | None,
    message: str,
    *,
    team: Team | None = None,
    single_repo_wins: bool = False,
    allow_refresh: bool = True,
    include_linked: bool = False,
) -> CascadeTierResult | None:
    """Pick a connected repository without the sandbox-backed selection agent.

    Resolves only the trivial cases: with ``single_repo_wins``, a lone connected repo is taken
    directly; otherwise the message has to name a connected ``owner/repo`` explicitly. Anything
    ambiguous returns `None` and the caller starts a repo-less run rather than paying for agentic
    discovery. Selection must never block that run from starting, so this never raises — every
    failure degrades to "no repo".

    ``user_id`` is passed as the requester, so their own connected GitHub stands in when the team
    has no team-level integration (their own credentials, not a cross-account leak), letting them
    reference repos only they have connected. ``allow_refresh=False`` reads only the cached repo
    list, so a caller on the request path never blocks on a live GitHub sync.

    ``include_linked=True`` adds a linked-URL tier after the explicit-token tier: if the message
    embeds exactly one ``github.com/owner/repo…`` URL that matches a connected repo, that repo is
    returned. Two different linked repos is genuine ambiguity and resolves to nothing. This is
    weaker evidence than a bare token, so it is opt-in and only signal-report callers enable it.
    """
    try:
        github = resolve_team_github_integration(team_id, team=team, requester_user_id=user_id)
        if github is None:
            return None
        # Drop archived repos: they accept no pull request, so the single_repo_wins shortcut below
        # must not hand back a lone archived repo as a target the caller can never push to.
        candidates = _list_candidate_repos(github, team_id, allow_refresh=allow_refresh, exclude_archived=True)
        if not candidates:
            return None
        if single_repo_wins and len(candidates) == 1:
            return CascadeTierResult(repository=candidates[0], tier="single_repo")
        explicit = extract_explicit_repo(message, candidates)
        if explicit is not None:
            return CascadeTierResult(repository=explicit, tier="explicit_token")
        if include_linked:
            linked = extract_linked_repo(message, candidates)
            if linked is not None:
                return CascadeTierResult(repository=linked, tier="linked_url")
        return None
    except Exception:
        logger.warning("cascade_select_repository.failed team_id=%s", team_id, exc_info=True)
        return None


async def select_repository_for_message(
    team_id: int,
    user_id: int,
    message: str,
    *,
    origin_product: Task.OriginProduct,
) -> str | None:
    """Pick a connected repository only when the message names it explicitly.

    The sandbox conversation open path must stay fast: it runs before the Run is created, so we
    avoid the repo-selection LLM agent here. A lone connected repo is deliberately *not* assumed —
    an unprompted mention shouldn't pin a sandbox to a repo the user never named.
    """
    result = await database_sync_to_async(cascade_select_repository, thread_sensitive=False)(team_id, user_id, message)
    return result.repository if result else None
