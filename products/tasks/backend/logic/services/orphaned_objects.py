import re
import dataclasses
from collections.abc import Callable, Iterator, Sequence
from itertools import chain, islice
from typing import Any

from django.conf import settings

import structlog

from posthog.dataclasses import frozen
from posthog.models import Organization, Team
from posthog.storage.object_storage import ObjectStorage, ObjectStorageError, object_storage_client

from products.tasks.backend.logic.services.agent_memory import STORAGE_PREFIX as AGENT_MEMORY_STORAGE_PREFIX

logger = structlog.get_logger(__name__)

PAGE_SIZE = 1000
LIST_PAGES_MAX = 100_000
FAILED_KEYS_LOGGED_MAX = 10
UNRECOGNIZED_PREFIXES_LOGGED_MAX = 10
FOREIGN_ROOTS = ("tasks/billing/", "tasks/autoresearch/")
TEAM_ID_MAX = 2**31 - 1
KIND_LABELS = {
    "logs": "Task run logs",
    "artifacts": "Task artifacts",
    "agent-memory": "Agent memory",
    "task-sessions": "Task sessions",
}
KIND_NAMES = tuple(KIND_LABELS)

TEAM_SEGMENT = re.compile(r"team_([1-9][0-9]*)")
TEAM_ID_SEGMENT = re.compile(r"([1-9][0-9]*)")
ORGANIZATION_ID_SEGMENT = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")

OwnerModel = type[Team] | type[Organization]
Progress = Callable[[], None]


@frozen
class PrefixKind:
    name: str
    root: str
    segment_pattern: re.Pattern[str]
    owner_model: OwnerModel


@frozen
class OrphanedPrefix:
    kind: PrefixKind
    owner_id: str
    prefix: str


@frozen
class PrefixOutcome:
    objects: int
    size_bytes: int
    failed_keys: tuple[str, ...]
    owner_reappeared: bool


@frozen
class OrphanedObjectsTotals:
    prefixes: int = 0
    objects: int = 0
    size_bytes: int = 0
    failed_objects: int = 0
    errored_prefixes: int = 0
    reappeared_owners: int = 0
    unrecognized_prefixes: int = 0

    def failures(self) -> int:
        return self.failed_objects + self.errored_prefixes


def prefix_kinds() -> tuple[PrefixKind, ...]:
    tasks_folder = settings.OBJECT_STORAGE_TASKS_FOLDER
    kinds = (
        *(
            PrefixKind(name=name, root=f"{tasks_folder}/{name}/", segment_pattern=TEAM_SEGMENT, owner_model=Team)
            for name in ("logs", "artifacts")
        ),
        PrefixKind(
            name="agent-memory",
            root=f"{AGENT_MEMORY_STORAGE_PREFIX}/",
            segment_pattern=TEAM_ID_SEGMENT,
            owner_model=Team,
        ),
        PrefixKind(
            name="task-sessions",
            root="task-sessions/",
            segment_pattern=ORGANIZATION_ID_SEGMENT,
            owner_model=Organization,
        ),
    )
    assert tuple(kind.name for kind in kinds) == KIND_NAMES
    for kind in kinds:
        assert kind.root.endswith("/")
        assert not kind.root.startswith(FOREIGN_ROOTS)
    return kinds


def existing_owner_ids(owner_model: OwnerModel, owner_ids: list[str]) -> set[str]:
    assert len(owner_ids) <= PAGE_SIZE
    if owner_model is Team:
        owner_ids = [owner_id for owner_id in owner_ids if int(owner_id) <= TEAM_ID_MAX]
    owners = owner_model.objects.using("default").filter(id__in=owner_ids)
    return {str(owner_id) for owner_id in owners.values_list("id", flat=True)}


def iter_list_pages(storage: ObjectStorage, request: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for _ in range(LIST_PAGES_MAX):
        response = storage.aws_client.list_objects_v2(**request, MaxKeys=PAGE_SIZE)
        yield response
        if not response.get("IsTruncated"):
            return
        request = {**request, "ContinuationToken": response["NextContinuationToken"]}
    raise ObjectStorageError(f"Listing {request['Prefix']!r} exceeded {LIST_PAGES_MAX} pages")


def iter_orphaned_prefixes(
    storage: ObjectStorage, bucket: str, kind: PrefixKind, unrecognized: list[str], progress: Progress
) -> Iterator[OrphanedPrefix]:
    for page in iter_list_pages(storage, {"Bucket": bucket, "Prefix": kind.root, "Delimiter": "/"}):
        progress()
        candidates: dict[str, str] = {}
        for common_prefix in page.get("CommonPrefixes") or []:
            prefix = common_prefix["Prefix"]
            assert prefix.startswith(kind.root)
            assert prefix.endswith("/")
            match = kind.segment_pattern.fullmatch(prefix[len(kind.root) : -1])
            if match is None:
                unrecognized.append(prefix)
            else:
                candidates[match.group(1)] = prefix
        live = existing_owner_ids(kind.owner_model, list(candidates))
        for owner_id, prefix in candidates.items():
            if owner_id not in live:
                yield OrphanedPrefix(kind=kind, owner_id=owner_id, prefix=prefix)


def delete_prefix(
    storage: ObjectStorage, bucket: str, orphan: OrphanedPrefix, *, execute: bool, progress: Progress
) -> PrefixOutcome:
    objects = 0
    size_bytes = 0
    failed_keys: list[str] = []
    owner_reappeared = False
    for page in iter_list_pages(storage, {"Bucket": bucket, "Prefix": orphan.prefix}):
        progress()
        contents = page.get("Contents") or []
        keys = [item["Key"] for item in contents]
        assert all(key.startswith(orphan.prefix) for key in keys)
        page_failed_keys: set[str] = set()
        if execute and keys:
            if existing_owner_ids(orphan.kind.owner_model, [orphan.owner_id]):
                owner_reappeared = True
                break
            page_failed_keys = set(storage.delete_objects(bucket, keys))
            failed_keys.extend(page_failed_keys)
        handled = [item for item in contents if item["Key"] not in page_failed_keys]
        objects += len(handled)
        size_bytes += sum(int(item.get("Size", 0)) for item in handled)
    return PrefixOutcome(
        objects=objects, size_bytes=size_bytes, failed_keys=tuple(failed_keys), owner_reappeared=owner_reappeared
    )


def add_outcome(totals: OrphanedObjectsTotals, outcome: PrefixOutcome) -> OrphanedObjectsTotals:
    return dataclasses.replace(
        totals,
        prefixes=totals.prefixes + 1,
        objects=totals.objects + outcome.objects,
        size_bytes=totals.size_bytes + outcome.size_bytes,
        failed_objects=totals.failed_objects + len(outcome.failed_keys),
        reappeared_owners=totals.reappeared_owners + int(outcome.owner_reappeared),
    )


def clean_orphaned_prefixes(
    *,
    bucket: str,
    kind_names: Sequence[str],
    max_prefixes: int,
    execute: bool,
    start: OrphanedObjectsTotals,
    checkpoint: Callable[[OrphanedObjectsTotals], None],
) -> OrphanedObjectsTotals:
    assert max_prefixes >= 1
    assert start.prefixes <= max_prefixes
    storage = object_storage_client()
    if not isinstance(storage, ObjectStorage):
        raise ObjectStorageError("Object storage is not enabled")
    kinds = [kind for kind in prefix_kinds() if kind.name in kind_names]
    assert len(kinds) == len(set(kind_names))

    totals = start
    unrecognized: list[str] = []

    def progress() -> None:
        checkpoint(totals)

    orphans = chain.from_iterable(
        iter_orphaned_prefixes(storage, bucket, kind, unrecognized, progress) for kind in kinds
    )
    for orphan in islice(orphans, max_prefixes - start.prefixes):
        try:
            outcome = delete_prefix(storage, bucket, orphan, execute=execute, progress=progress)
        except Exception:
            logger.exception("orphaned_task_objects.prefix_failed", prefix=orphan.prefix, execute=execute)
            totals = dataclasses.replace(
                totals, prefixes=totals.prefixes + 1, errored_prefixes=totals.errored_prefixes + 1
            )
        else:
            totals = add_outcome(totals, outcome)
            logger.info(
                "orphaned_task_objects.prefix_done",
                prefix=orphan.prefix,
                execute=execute,
                objects=outcome.objects,
                size_bytes=outcome.size_bytes,
                failed_keys=outcome.failed_keys[:FAILED_KEYS_LOGGED_MAX],
                failed_objects=len(outcome.failed_keys),
                owner_reappeared=outcome.owner_reappeared,
            )
        checkpoint(totals)

    if unrecognized:
        sample = unrecognized[:UNRECOGNIZED_PREFIXES_LOGGED_MAX]
        logger.warning("orphaned_task_objects.unrecognized_prefixes", prefixes=sample, count=len(unrecognized))
    return dataclasses.replace(totals, unrecognized_prefixes=len(unrecognized))
