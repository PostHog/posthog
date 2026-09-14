"""The team that owns each snapshot, read from the story index and the repository's ownership files."""

from collections.abc import Iterable

import structlog

from products.engineering_analytics.backend.facade.api import resolve_path_owners
from products.engineering_analytics.backend.facade.contracts import UNOWNED_TEAM

from ..facade.enums import RunType
from ..models import Repo
from . import run_queries, story_index
from .run_queries import SnapshotKey

logger = structlog.get_logger(__name__)


def owner_teams(repo: Repo, keys: Iterable[SnapshotKey]) -> dict[SnapshotKey, str]:
    """The owning team of each Storybook snapshot whose story file is known.

    A key is left out when there is no team to name: the run type has no story index, the newest
    default-branch run sent none, the story is not in it, or the ownership files could not be read.
    `UNOWNED_TEAM` means the file is known and no ownership entry covers it.
    """
    storybook_keys = [key for key in keys if key.run_type == RunType.STORYBOOK]
    if not storybook_keys:
        return {}

    newest_run_by_type = run_queries.newest_run_by_run_type(run_queries.latest_default_branch_runs(repo.id))
    index = story_index.latest_story_index(repo, newest_run_by_type)
    if isinstance(index, str):
        return {}

    path_by_key: dict[SnapshotKey, str] = {}
    for key in storybook_keys:
        path = story_index.story_path(index, key.identifier)
        if path is not None:
            path_by_key[key] = path
    if not path_by_key:
        return {}

    ownership = resolve_path_owners(repo.repo_full_name, sorted(set(path_by_key.values())))
    if not ownership.resolved:
        logger.info("visual_review.owner_teams_unresolved", repo_id=str(repo.id))
        return {}
    return {key: ownership.team_by_path.get(path, UNOWNED_TEAM) for key, path in path_by_key.items()}
