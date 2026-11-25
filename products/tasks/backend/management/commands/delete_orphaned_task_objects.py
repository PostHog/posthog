import re
from collections.abc import Iterator
from itertools import chain, islice
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.dataclasses import frozen
from posthog.models import Organization, Team
from posthog.storage.object_storage import ObjectStorage, object_storage_client

PAGE_SIZE = 1000
LIST_PAGES_MAX = 100_000
FAILED_KEYS_SHOWN_MAX = 10
FOREIGN_ROOTS = ("tasks/billing/", "tasks/autoresearch/")
TEAM_ID_MAX = 2**31 - 1

TEAM_SEGMENT = re.compile(r"team_([1-9][0-9]*)")
TEAM_ID_SEGMENT = re.compile(r"([1-9][0-9]*)")
ORGANIZATION_ID_SEGMENT = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


@frozen
class PrefixKind:
    name: str
    root: str
    segment_pattern: re.Pattern[str]
    owner_model: type[Team] | type[Organization]


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


def prefix_kinds() -> tuple[PrefixKind, ...]:
    tasks_folder = settings.OBJECT_STORAGE_TASKS_FOLDER
    kinds = (
        *(
            PrefixKind(name=name, root=f"{tasks_folder}/{name}/", segment_pattern=TEAM_SEGMENT, owner_model=Team)
            for name in ("logs", "artifacts")
        ),
        PrefixKind(
            name="agent-memory",
            root="tasks/agent-memory/",
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
    for kind in kinds:
        assert kind.root.endswith("/")
        assert not kind.root.startswith(FOREIGN_ROOTS)
    return kinds


def existing_owner_ids(owner_model: type[Team] | type[Organization], owner_ids: list[str]) -> set[str]:
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
    raise CommandError(f"Listing {request['Prefix']!r} exceeded {LIST_PAGES_MAX} pages")


def iter_orphaned_prefixes(
    storage: ObjectStorage, bucket: str, kind: PrefixKind, malformed: list[str]
) -> Iterator[OrphanedPrefix]:
    for page in iter_list_pages(storage, {"Bucket": bucket, "Prefix": kind.root, "Delimiter": "/"}):
        candidates: dict[str, str] = {}
        for common_prefix in page.get("CommonPrefixes") or []:
            prefix = common_prefix["Prefix"]
            assert prefix.startswith(kind.root)
            assert prefix.endswith("/")
            match = kind.segment_pattern.fullmatch(prefix[len(kind.root) : -1])
            if match is None:
                malformed.append(prefix)
            else:
                candidates[match.group(1)] = prefix
        live = existing_owner_ids(kind.owner_model, list(candidates))
        for owner_id, prefix in candidates.items():
            if owner_id not in live:
                yield OrphanedPrefix(kind=kind, owner_id=owner_id, prefix=prefix)


def delete_prefix(storage: ObjectStorage, bucket: str, orphan: OrphanedPrefix, *, execute: bool) -> PrefixOutcome:
    objects = 0
    size_bytes = 0
    failed_keys: list[str] = []
    owner_reappeared = False
    for page in iter_list_pages(storage, {"Bucket": bucket, "Prefix": orphan.prefix}):
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


class Command(BaseCommand):
    help = (
        "Delete tasks product objects in object storage whose team or organization no longer exists. "
        "Dry run by default; pass --execute to delete."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        names = [kind.name for kind in prefix_kinds()]
        parser.add_argument("--execute", action="store_true", help="Delete the objects instead of listing them")
        parser.add_argument("--limit", type=int, metavar="N", help="Stop after N orphaned prefixes")
        parser.add_argument(
            "--kind", action="append", choices=names, dest="kinds", help="Only this prefix kind (repeatable)"
        )
        parser.add_argument("--bucket", default=settings.OBJECT_STORAGE_BUCKET, help="Bucket to clean")

    def handle(self, *args: Any, **options: Any) -> None:
        execute: bool = options["execute"]
        limit: int | None = options["limit"]
        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1")
        storage = object_storage_client()
        if not isinstance(storage, ObjectStorage):
            raise CommandError("Object storage is not enabled")
        bucket: str = options["bucket"]
        kinds = [kind for kind in prefix_kinds() if options["kinds"] is None or kind.name in options["kinds"]]
        verb = "Deleted" if execute else "Would delete"

        prefixes = objects = size_bytes = failed = reappeared = errors = 0
        malformed: list[str] = []
        orphans = chain.from_iterable(iter_orphaned_prefixes(storage, bucket, kind, malformed) for kind in kinds)
        try:
            for orphan in islice(orphans, limit):
                prefixes += 1
                try:
                    outcome = delete_prefix(storage, bucket, orphan, execute=execute)
                except Exception as error:
                    errors += 1
                    self.stderr.write(f"Failed on {orphan.prefix}: {error!r}")
                    continue
                objects += outcome.objects
                size_bytes += outcome.size_bytes
                failed += len(outcome.failed_keys)
                self.stdout.write(f"{verb} {orphan.prefix}: {outcome.objects} objects, {outcome.size_bytes} bytes")
                if outcome.owner_reappeared:
                    reappeared += 1
                    owner_name = orphan.kind.owner_model.__name__
                    self.stderr.write(f"Stopped at {orphan.prefix}: {owner_name} {orphan.owner_id} now exists")
                for key in outcome.failed_keys[:FAILED_KEYS_SHOWN_MAX]:
                    self.stderr.write(f"Failed to delete {key}")
        finally:
            for prefix in malformed:
                self.stderr.write(f"Skipped unrecognized prefix {prefix}")
            self.stdout.write(
                f"{verb} {objects} objects ({size_bytes} bytes) under {prefixes} orphaned prefixes in {bucket}; "
                f"{failed} objects failed, {errors} prefixes errored, {reappeared} owners reappeared, "
                f"{len(malformed)} unrecognized prefixes skipped"
            )
        if failed or errors:
            raise CommandError(f"{failed} objects failed and {errors} prefixes errored; rerun to retry them")
