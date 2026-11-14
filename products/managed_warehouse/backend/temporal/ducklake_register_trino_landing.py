"""Manifests and the sweep for the files that a Trino registration copies into the landing folder.

A Parquet file in an `m` execution folder can be in a catalog row only if a manifest in its attempt folder lists it,
because the execution writes each batch's manifest before it runs that add_files. DuckLake cleans only files it
recorded and Trino cannot list the files a table references, so PostHog records them itself.

This module must not import the workflow module: the workflow imports it.
"""

from __future__ import annotations

import re
import json
import uuid
import datetime as dt
from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol

from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen

from products.managed_warehouse.backend.temporal.ducklake_register_data_imports_trino import (
    STAGING_TABLE_PREFIX,
    staging_table_minted_at,
)

# Prefix of the folders that hold a Trino registration's copy of the files, below the DuckLake data path.
LANDING_ROOT = "_ph_imports"
MANIFEST_FOLDER = "_ph_add_files"
# Only executions that write manifests carry the `m` prefix. A folder without it came from code that wrote none.
_MANIFEST_EXECUTION_PATTERN = re.compile(r"^m[0-9a-f]{16}$")


class LandingFilesystem(Protocol):
    def invalidate_cache(self, path: str | None = None, /) -> None: ...

    def find(self, path: str, /) -> list[str]: ...

    def cat_file(self, path: str, /) -> bytes: ...

    def pipe_file(self, path: str, value: bytes, /) -> None: ...

    def rm(self, path: list[str], /) -> None: ...


@frozen
class LandingSweepResult:
    deleted: tuple[str, ...]
    kept: tuple[str, ...]
    unmanifested_executions: tuple[str, ...]
    undeletable: tuple[str, ...]


def new_execution_folder_name() -> str:
    return f"m{uuid.uuid4().hex[:16]}"


def write_batch_manifest(filesystem: LandingFilesystem, execution_uri: str, index: int, paths: Sequence[str]) -> None:
    folder = execution_uri.removeprefix("s3://").rstrip("/")
    filesystem.pipe_file(f"{folder}/{MANIFEST_FOLDER}/{index:05d}.json", json.dumps({"files": list(paths)}).encode())


def sweep_unregistered_landing_files(
    filesystem: LandingFilesystem, attempt_uri: str, *, now: dt.datetime, min_age: dt.timedelta
) -> LandingSweepResult:
    token = attempt_uri.rstrip("/").rsplit("/", 1)[-1]
    minted_at = staging_table_minted_at(STAGING_TABLE_PREFIX + token)
    if minted_at is None:
        raise ApplicationError(f"'{attempt_uri}' does not end in an attempt token", non_retryable=True)
    if f"/{LANDING_ROOT}/" not in attempt_uri:
        raise ApplicationError(f"'{attempt_uri}' is not a Trino landing folder", non_retryable=True)
    if now - minted_at < min_age:
        raise ApplicationError(f"An execution of attempt '{token}' may still be running", non_retryable=False)

    prefix = attempt_uri.removeprefix("s3://").rstrip("/") + "/"
    filesystem.invalidate_cache(prefix)
    keys_by_execution: dict[str, list[str]] = defaultdict(list)
    for key in filesystem.find(prefix):
        execution, separator, _ = key.removeprefix(prefix).partition("/")
        if separator:
            keys_by_execution[execution].append(key)

    unmanifested = sorted(name for name in keys_by_execution if not _MANIFEST_EXECUTION_PATTERN.fullmatch(name))
    manifested = {name: keys for name, keys in keys_by_execution.items() if name not in unmanifested}

    # Every manifest is read before any delete, and a failed read raises, so a file is never deleted on partial knowledge.
    listed: set[str] = set()
    for name, keys in manifested.items():
        manifest_prefix = f"{prefix}{name}/{MANIFEST_FOLDER}/"
        for key in keys:
            if key.startswith(manifest_prefix) and key.endswith(".json"):
                entries = [path.removeprefix("s3://") for path in json.loads(filesystem.cat_file(key))["files"]]
                # A path the sweep cannot match to a key must stop it, because an unmatched registered file would
                # look unregistered.
                if not all(entry.startswith(f"{prefix}{name}/") for entry in entries):
                    raise ApplicationError(
                        f"Manifest '{key}' lists a file outside its execution folder", non_retryable=True
                    )
                listed.update(entries)

    candidates: list[str] = []
    undeletable: list[str] = []
    kept: list[str] = []
    for name, keys in manifested.items():
        manifest_prefix = f"{prefix}{name}/{MANIFEST_FOLDER}/"
        for key in keys:
            if key.startswith(manifest_prefix) or not key.lower().endswith(".parquet"):
                continue
            if key in listed:
                kept.append(key)
            # fsspec's rm expands a glob in any entry, so the pattern could delete a different, registered file.
            elif any(character in key for character in "*?["):
                undeletable.append(key)
            else:
                candidates.append(key)

    if candidates:
        filesystem.rm(candidates)
        filesystem.invalidate_cache(prefix)
        remaining = set(candidates) & set(filesystem.find(prefix))
        if remaining:
            raise RuntimeError(f"{len(remaining)} files remain after the delete")
    return LandingSweepResult(
        deleted=tuple(sorted(candidates)),
        kept=tuple(sorted(kept)),
        unmanifested_executions=tuple(unmanifested),
        undeletable=tuple(sorted(undeletable)),
    )
