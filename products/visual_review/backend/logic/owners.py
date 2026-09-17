"""The team that owns each snapshot, read from the story index and the repository's ownership files."""

from collections.abc import Iterable, Mapping

import structlog

from products.engineering_analytics.backend.facade.api import resolve_path_owners
from products.engineering_analytics.backend.facade.contracts import UNOWNED_TEAM

from ..facade.enums import RunType
from ..models import Repo, Run
from . import story_index
from .run_queries import SnapshotKey

logger = structlog.get_logger(__name__)

# Each distinct story file adds the ownership files of its parent directories to one batch of GitHub
# reads. A snapshot set that names more story files than a real Storybook build has is left without
# owners, so a crafted story index cannot turn one page load into thousands of fetches.
_MAX_OWNED_PATHS = 2_000


def owner_teams(
    repo: Repo, keys: Iterable[SnapshotKey], newest_run_by_type: Mapping[str, Run]
) -> dict[SnapshotKey, str]:
    """The owning team of each Storybook snapshot whose story file is known.

    A key is left out when there is no team to name: the run type has no story index, the newest
    default-branch run sent none, the story is not in it, or the ownership files could not be read.
    `UNOWNED_TEAM` means the file is known and no ownership entry covers it.
    """
    storybook_keys = [key for key in keys if key.run_type == RunType.STORYBOOK]
    if not storybook_keys:
        return {}

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

    paths = sorted(set(path_by_key.values()))
    if len(paths) > _MAX_OWNED_PATHS:
        logger.warning("visual_review.owner_teams_too_many_paths", repo_id=str(repo.id), paths=len(paths))
        return {}

    ownership = resolve_path_owners(repo.repo_full_name, paths)
    if not ownership.resolved:
        logger.info("visual_review.owner_teams_unresolved", repo_id=str(repo.id))
        return {}
    return {key: ownership.team_by_path.get(path, UNOWNED_TEAM) for key, path in path_by_key.items()}
