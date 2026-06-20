import logging

from posthog.git import extract_explicit_repo
from posthog.sync import database_sync_to_async

from products.tasks.backend.models import Task
from products.tasks.backend.logic.repo_selection.agent import (
    RepoSelectionRejectedError,
    RepoSelectionUnavailableError,
    _list_candidate_repos,
    resolve_team_github_integration,
    select_repository,
)

logger = logging.getLogger(__name__)


async def select_repository_for_message(
    team_id: int,
    user_id: int,
    message: str,
    *,
    origin_product: Task.OriginProduct,
) -> str | None:
    """Pick the repository a free-form chat message is most likely about, cheapest strategy first.

    1. An explicit `owner/repo` token in the message that matches a connected repo.
    2. Delegated to `select_repository`, which returns the team's single eligible repo instantly,
       or runs the sandbox LLM agent when there are several candidates.

    Returns `None` when nothing connects (no integration, no candidates, the agent finds no
    plausible subject, or selection fails for any reason). Selection must never block the
    conversation from starting, so this never raises — every failure degrades to "no repo".
    """
    try:
        github = await database_sync_to_async(resolve_team_github_integration, thread_sensitive=False)(team_id)
        if github is None:
            return None
        candidates = await database_sync_to_async(_list_candidate_repos, thread_sensitive=False)(github, team_id)
        if not candidates:
            return None

        explicit = extract_explicit_repo(message, candidates)
        if explicit:
            return explicit

        result = await select_repository(team_id, user_id, context=message, origin_product=origin_product)
        return result.repository
    except (RepoSelectionRejectedError, RepoSelectionUnavailableError) as e:
        logger.info("repo_selection_for_message.no_selection team_id=%s reason=%s", team_id, e)
        return None
    except Exception:
        logger.warning("repo_selection_for_message.failed team_id=%s", team_id, exc_info=True)
        return None
