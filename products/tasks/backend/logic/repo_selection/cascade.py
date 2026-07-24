import logging

from posthog.git import extract_explicit_repo
from posthog.sync import database_sync_to_async

from products.tasks.backend.logic.repo_selection.agent import _list_candidate_repos, resolve_team_github_integration
from products.tasks.backend.models import Task

logger = logging.getLogger(__name__)


async def select_repository_for_message(
    team_id: int,
    user_id: int,
    message: str,
    *,
    origin_product: Task.OriginProduct,
) -> str | None:
    """Pick a connected repository only when the message names it explicitly.

    The sandbox conversation open path must stay fast: it runs before the Run is created, so we
    avoid the repo-selection LLM agent here. Messages without an explicit connected `owner/repo`
    mention return `None`, which starts a repo-less sandbox. Selection must never block the
    conversation from starting, so this never raises — every failure degrades to "no repo".

    This is the user-initiated path, so we pass `user_id` as the requester: their own connected
    GitHub is a valid source even if they aren't an org owner (it's their own credentials, not a
    cross-account leak), letting them reference repos only they have connected.
    """
    try:
        github = await database_sync_to_async(resolve_team_github_integration, thread_sensitive=False)(
            team_id, requester_user_id=user_id
        )
        if github is None:
            return None
        candidates = await database_sync_to_async(_list_candidate_repos, thread_sensitive=False)(github, team_id)
        if not candidates:
            return None

        return extract_explicit_repo(message, candidates)
    except Exception:
        logger.warning("repo_selection_for_message.failed team_id=%s", team_id, exc_info=True)
        return None


def cascade_select_repository(team_id: int, user_id: int | None, message: str) -> str | None:
    """Cheap synchronous repo pick, mirroring the Slack mention cascade's fast path.

    Resolves the trivial cases without the sandbox-backed selection agent: a single connected repo
    is used directly, otherwise an explicit `owner/repo` named in `message`. Ambiguous multi-repo
    cases with no explicit mention return `None` (the caller starts a repo-less run) rather than
    paying for agentic discovery. Never raises — every failure degrades to "no repo".

    Synchronous so request-path callers (task creation) can use it without an event loop. Passes
    `user_id` as the requester, so their own connected GitHub is a valid source (their credentials,
    not a cross-account leak) when the team has no team-level integration.
    """
    try:
        github = resolve_team_github_integration(team_id, requester_user_id=user_id)
        if github is None:
            return None
        candidates = _list_candidate_repos(github, team_id)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        return extract_explicit_repo(message, candidates)
    except Exception:
        logger.warning("cascade_select_repository.failed team_id=%s", team_id, exc_info=True)
        return None
