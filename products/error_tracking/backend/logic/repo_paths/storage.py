"""Object storage layout of release file lists.

cymbal-path-resolution reads these objects, so the key and the body format are a contract with
``rust/cymbal/src/modes/path_resolution/list_store.rs``. Change both sides together.
"""

from collections.abc import Sequence

from django.conf import settings

import zstd

from posthog.storage import object_storage

from products.error_tracking.backend.logic.repo_paths.slug import RepoSlug

_ZSTD_LEVEL = 10


def repo_paths_prefix(team_id: int, slug: RepoSlug) -> str:
    # The trailing slash keeps "acme/shop" from matching the lists of "acme/shop-web".
    return f"{settings.OBJECT_STORAGE_ERROR_TRACKING_REPO_PATHS_FOLDER}/v1/{team_id}/{slug}/"


def repo_paths_key(team_id: int, slug: RepoSlug, commit: str) -> str:
    return f"{repo_paths_prefix(team_id, slug)}{commit}.zst"


def encode_file_list(paths: Sequence[str]) -> bytes:
    return zstd.compress("\n".join(paths).encode("utf-8"), _ZSTD_LEVEL)


def file_list_exists(key: str) -> bool:
    # The strict call raises on a storage error, so an outage retries the job instead of fetching again.
    return object_storage.head_object_strict(file_key=key) is not None


def write_file_list(key: str, paths: Sequence[str]) -> None:
    object_storage.write(key, encode_file_list(paths))


def remove_old_file_lists(team_id: int, slug: RepoSlug, *, keep: int) -> list[str]:
    """Delete all but the ``keep`` newest lists of one repo. Returns the deleted keys."""
    keys = object_storage.list_objects(repo_paths_prefix(team_id, slug)) or []
    if len(keys) <= keep:
        return []
    modified = []
    for key in keys:
        head = object_storage.head_object(file_key=key)
        if head is not None and head.get("LastModified") is not None:
            modified.append((head["LastModified"], key))
    modified.sort(reverse=True)
    stale = [key for _, key in modified[keep:]]
    if stale:
        object_storage.delete_objects(stale)
    return stale
