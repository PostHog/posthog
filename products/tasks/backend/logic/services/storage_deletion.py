import itertools
from collections.abc import Callable, Iterable
from uuid import UUID

from django.conf import settings
from django.db.models import Exists, OuterRef

from posthog.storage import object_storage

from products.tasks.backend.logic.services.agent_memory import team_memory_prefix
from products.tasks.backend.models import (
    Task,
    TaskRun,
    organization_task_sessions_s3_prefix,
    task_sessions_s3_prefix,
    team_task_artifacts_s3_prefix,
    team_task_logs_s3_prefix,
)

DELETE_BATCH_KEYS_MAX = 1000


class TaskStorageDeletionError(Exception):
    pass


def delete_team_storage(team_id: int, *, should_stop: Callable[[], bool]) -> int:
    prefixes = (team_task_logs_s3_prefix(team_id), team_task_artifacts_s3_prefix(team_id), team_memory_prefix(team_id))
    return _delete_prefixes(prefixes, should_stop=should_stop)


def delete_team_task_session_storage_page(
    team_ids: list[int], *, after_task_id: str | None, limit: int, should_stop: Callable[[], bool]
) -> str | None:
    assert limit > 0
    tasks = Task.objects.filter(Exists(TaskRun.objects.filter(task_id=OuterRef("id"))), team_id__in=team_ids)
    if after_task_id is not None:
        tasks = tasks.filter(id__gt=after_task_id)
    rows = list(tasks.values_list("team__organization_id", "id").order_by("id")[:limit])
    if not rows:
        return None
    prefixes = (task_sessions_s3_prefix(organization_id, task_id) for organization_id, task_id in rows)
    _delete_prefixes(prefixes, should_stop=should_stop)
    if should_stop():
        raise TaskStorageDeletionError(f"Stopped before every task session after {after_task_id} was deleted")
    _, last_task_id = rows[-1]
    return str(last_task_id)


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
