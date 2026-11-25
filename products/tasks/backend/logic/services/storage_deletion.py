import itertools
from collections.abc import Callable, Iterable
from uuid import UUID

from django.conf import settings

from posthog.storage import object_storage

from products.tasks.backend.logic.services.agent_memory import team_memory_prefix
from products.tasks.backend.models import (
    organization_task_sessions_s3_prefix,
    team_task_artifacts_s3_prefix,
    team_task_logs_s3_prefix,
)

DELETE_BATCH_KEYS_MAX = 1000


class TaskStorageDeletionError(Exception):
    pass


def delete_team_storage(team_id: int, *, should_stop: Callable[[], bool]) -> int:
    prefixes = (team_task_logs_s3_prefix(team_id), team_task_artifacts_s3_prefix(team_id), team_memory_prefix(team_id))
    return _delete_prefixes(prefixes, should_stop=should_stop)


def delete_organization_storage(organization_id: UUID | str, *, should_stop: Callable[[], bool]) -> int:
    return _delete_prefixes((organization_task_sessions_s3_prefix(organization_id),), should_stop=should_stop)


def _delete_prefixes(prefixes: Iterable[str], *, should_stop: Callable[[], bool]) -> int:
    assert DELETE_BATCH_KEYS_MAX > 0
    assert DELETE_BATCH_KEYS_MAX <= 1000
    if not settings.OBJECT_STORAGE_ENABLED:
        return 0

    deleted_count = 0
    for prefix in prefixes:
        assert prefix.endswith("/")
        keys = object_storage.iter_keys(prefix, page_size=DELETE_BATCH_KEYS_MAX)
        for batch in itertools.batched(keys, DELETE_BATCH_KEYS_MAX, strict=False):
            if should_stop():
                return deleted_count
            assert all(key.startswith(prefix) for key in batch)
            failed_keys = object_storage.delete_objects(list(batch))
            if failed_keys:
                raise TaskStorageDeletionError(
                    f"{len(failed_keys)} of {len(batch)} objects under {prefix} could not be deleted"
                )
            deleted_count += len(batch)
    return deleted_count
