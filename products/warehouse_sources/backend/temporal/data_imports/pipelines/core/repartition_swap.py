"""Object-store work of the repartition swap: list a table folder, copy files with a bound, report progress.

The swap in `repartition.py` owns the order of the steps and the recovery rules. This module holds
the steps that touch many objects, so each of them can stop between groups of files and can say how
far it is.
"""

from __future__ import annotations

import time
import asyncio
import dataclasses
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    is_transient_object_store_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
    DELTA_REPARTITION_SWAP_BYTES_TOTAL,
    DELTA_REPARTITION_SWAP_FILES_TOTAL,
)
from products.warehouse_sources.backend.temporal.data_imports.util import _is_s3_throttling_error, copy_s3_file

DELTA_LOG_PREFIX = "_delta_log/"

# The marker's `phase` once the swap has started to replace the live log. From here live can be
# without a complete log, so a resume takes its row count from temp and never from live.
SWAP_PHASE_SWITCH_LOG = "switch_log"
# The marker's `phase` once live is verified on the new layout. Only deletes are left, and temp can
# already be partly gone, so a resume must not read temp.
SWAP_PHASE_CLEANUP = "cleanup"

# Copies in flight at one time. A copy is one server-side request with no payload, so the bound
# protects the destination prefix from a rate limit and costs no memory.
SWAP_COPY_CONCURRENCY = 32
# Files between two stop checks. A worker shutdown waits for at most one group.
SWAP_GROUP_FILES = 256
SWAP_PROGRESS_INTERVAL_SECONDS = 30.0
# One group is retried as a whole. 5 attempts give 30 seconds of backoff (2+4+8+16).
SWAP_COPY_MAX_ATTEMPTS = 5
# The object store accepts at most this many keys in one delete request.
SWAP_DELETE_BATCH = 1000


@dataclasses.dataclass(frozen=False)
class SwapProgress:
    """Counts for one step of the swap. `files_done` includes files that were already in place."""

    step: str
    files_total: int
    bytes_total: int
    files_done: int = 0
    bytes_done: int = 0
    files_already_in_place: int = 0
    started_at: float = dataclasses.field(default_factory=time.monotonic)

    def fields(self) -> dict[str, Any]:
        elapsed = max(time.monotonic() - self.started_at, 1e-6)
        moved = self.files_done - self.files_already_in_place
        rate = moved / elapsed
        left = max(self.files_total - self.files_done, 0)
        return {
            "step": self.step,
            "files_done": self.files_done,
            "files_total": self.files_total,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
            "files_already_in_place": self.files_already_in_place,
            "percent_complete": round(100 * self.files_done / self.files_total, 1) if self.files_total else 100.0,
            "elapsed_seconds": round(elapsed),
            "files_per_second": round(rate, 1),
            # No rate to project from until this attempt has moved a file.
            "eta_seconds": round(left / rate) if rate else None,
        }


def object_path(uri: str) -> str:
    """The `bucket/key` form that the object-store client returns for `uri`."""
    return uri.split("://", 1)[-1].rstrip("/")


async def list_table_files(s3: Any, table_uri: str) -> dict[str, int]:
    """Map each object under `table_uri` from its path inside the table folder to its size.

    One flat listing, 1000 keys per request. The trailing slash on the key prefix keeps sibling
    folders that share the table's name as a prefix (temp tables, query folders) out of the result.
    """
    parent_uri, _, folder_name = table_uri.rstrip("/").rpartition("/")
    try:
        found = await s3._find(parent_uri, prefix=f"{folder_name}/", detail=True)
    except FileNotFoundError:
        return {}
    entries = found.values() if isinstance(found, dict) else found
    prefix = object_path(table_uri) + "/"
    files: dict[str, int] = {}
    for entry in entries:
        if entry.get("type") == "directory":
            continue
        key = object_path(str(entry.get("Key") or entry["name"]))
        if key.startswith(prefix) and len(key) > len(prefix):
            files[key[len(prefix) :]] = int(entry.get("size") or 0)
    return files


async def copy_files(
    s3: Any,
    *,
    source_uri: str,
    destination_uri: str,
    files: Mapping[str, int],
    progress: SwapProgress,
    between_groups: Callable[[], Awaitable[None]] | None = None,
    concurrency: int | None = None,
    group_files: int | None = None,
) -> None:
    """Copy `files` (path inside the table folder -> size) from one table folder to another.

    At most `concurrency` copies run at one time. `between_groups` runs after each group of
    `group_files` files: it is where the caller checks for a stop, checks its claim and logs. A file
    that has arrived is never copied again by a later call, because the caller passes only the files
    the destination lacks.
    """
    semaphore = asyncio.Semaphore(concurrency or SWAP_COPY_CONCURRENCY)
    group_files = group_files or SWAP_GROUP_FILES
    source_uri = source_uri.rstrip("/")
    destination_uri = destination_uri.rstrip("/")

    async def copy_one(relative: str, size: int) -> None:
        async with semaphore:
            await copy_s3_file(s3, f"{source_uri}/{relative}", f"{destination_uri}/{relative}", size)

    pending = list(files.items())
    for start in range(0, len(pending), group_files):
        group = pending[start : start + group_files]
        attempt = 0
        while True:
            attempt += 1
            results = await asyncio.gather(
                *(copy_one(relative, size) for relative, size in group), return_exceptions=True
            )
            failed: list[tuple[str, int]] = []
            error: BaseException | None = None
            for (relative, size), result in zip(group, results):
                if isinstance(result, BaseException):
                    failed.append((relative, size))
                    error = error or result
                else:
                    progress.files_done += 1
                    progress.bytes_done += size
                    DELTA_REPARTITION_SWAP_BYTES_TOTAL.inc(size)
            DELTA_REPARTITION_SWAP_FILES_TOTAL.labels(action="copied").inc(len(group) - len(failed))
            if error is None:
                break
            retryable = isinstance(error, OSError) and not isinstance(error, FileNotFoundError)
            retryable = retryable and (
                is_transient_object_store_error(error)
                or _is_s3_throttling_error(error)
                or isinstance(error, PermissionError)
            )
            if not retryable or attempt >= SWAP_COPY_MAX_ATTEMPTS:
                raise error
            group = failed
            await asyncio.sleep(2**attempt)
        if between_groups is not None:
            await between_groups()


async def delete_files(s3: Any, table_uri: str, relative_paths: Sequence[str], progress: SwapProgress) -> None:
    """Delete the named objects under `table_uri`, one bulk request per `SWAP_DELETE_BATCH` keys."""
    table_uri = table_uri.rstrip("/")
    for start in range(0, len(relative_paths), SWAP_DELETE_BATCH):
        batch = relative_paths[start : start + SWAP_DELETE_BATCH]
        await s3._rm([f"{table_uri}/{relative}" for relative in batch])
        progress.files_done += len(batch)
        DELTA_REPARTITION_SWAP_FILES_TOTAL.labels(action="deleted").inc(len(batch))
