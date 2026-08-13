import logging

from posthog.git import extract_explicit_repo
from posthog.models.team import Team
from posthog.sync import database_sync_to_async

from products.tasks.backend.logic.repo_selection.agent import _list_candidate_repos, resolve_team_github_integration
from products.tasks.backend.models import Task

logger = logging.getLogger(__name__)


def cascade_select_repository(
    team_id: int,
    user_id: int | None,
    message: str,
    *,
    team: Team | None = None,
    single_repo_wins: bool = False,
    allow_refresh: bool = True,
) -> str | None:
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
    """
    try:
        github = resolve_team_github_integration(team_id, team=team, requester_user_id=user_id)
        if github is None:
            return None
        candidates = _list_candidate_repos(github, team_id, allow_refresh=allow_refresh)
        if not candidates:
            return None
        if single_repo_wins and len(candidates) == 1:
            return candidates[0]
        return extract_explicit_repo(message, candidates)
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
    return await database_sync_to_async(cascade_select_repository, thread_sensitive=False)(team_id, user_id, message)
