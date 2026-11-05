"""Carry Claude Code auto memory between cloud sandboxes through object storage.

Storage holds one object per memory file at `tasks/agent-memory/<user_id>/claude/<slug>/<filename>`.
Everything read from a sandbox is agent-controlled, so slugs and filenames are validated against a
strict shape before they become part of an object key or a sandbox path, and sizes are capped.
"""

from __future__ import annotations

import re
import time
import shlex
import hashlib
from collections import Counter
from dataclasses import field
from typing import TYPE_CHECKING

import structlog

from posthog.dataclasses import frozen
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError, StoredObjectSummary

from products.tasks.backend.constants import DEFAULT_SANDBOX_WORKING_DIR

if TYPE_CHECKING:
    from products.tasks.backend.logic.services.sandbox import SandboxBase, SandboxDirEntry

logger = structlog.get_logger(__name__)

# agent-server symlinks ~/.claude/projects here at boot (see persistent-agent-state.ts).
SANDBOX_CLAUDE_PROJECTS_DIR = f"{DEFAULT_SANDBOX_WORKING_DIR}/.posthog/agent-state/claude/projects"
# agent-server moves a populated ~/.claude/projects into the state directory at boot, and refuses
# to boot when the state directory is already populated. A restore must not create that conflict.
SANDBOX_HOME_CLAUDE_PROJECTS_DIR = "/root/.claude/projects"
MEMORY_DIR_NAME = "memory"
STORAGE_PREFIX = "tasks/agent-memory"

MAX_FILE_BYTES = 256 * 1024
MAX_SLUG_BYTES = 2 * 1024 * 1024
MAX_FILES_PER_SLUG = 200
MAX_SLUGS_PER_USER = 50
RESTORE_DEADLINE_SECONDS = 60.0

_SLUG_PATTERN = re.compile(r"-[A-Za-z0-9._-]{1,200}")
_FILENAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,120}\.md")


def is_valid_slug(slug: str) -> bool:
    return _SLUG_PATTERN.fullmatch(slug) is not None and ".." not in slug


def is_valid_memory_filename(filename: str) -> bool:
    return _FILENAME_PATTERN.fullmatch(filename) is not None and filename not in {".", ".."}


def user_memory_prefix(user_id: int) -> str:
    return f"{STORAGE_PREFIX}/{int(user_id)}/claude/"


def slug_memory_prefix(user_id: int, slug: str) -> str:
    if not is_valid_slug(slug):
        raise ValueError("invalid memory slug")
    return f"{user_memory_prefix(user_id)}{slug}/"


def memory_object_key(user_id: int, slug: str, filename: str) -> str:
    if not is_valid_memory_filename(filename):
        raise ValueError("invalid memory filename")
    return f"{slug_memory_prefix(user_id, slug)}{filename}"


def sandbox_memory_dir(slug: str) -> str:
    if not is_valid_slug(slug):
        raise ValueError("invalid memory slug")
    return f"{SANDBOX_CLAUDE_PROJECTS_DIR}/{slug}/{MEMORY_DIR_NAME}"


@frozen
class MemoryFileRef:
    slug: str
    filename: str


def parse_memory_object_key(user_id: int, key: str) -> MemoryFileRef | None:
    prefix = user_memory_prefix(user_id)
    if not key.startswith(prefix):
        return None
    parts = key[len(prefix) :].split("/")
    if len(parts) != 2:
        return None
    slug, filename = parts
    if not is_valid_slug(slug) or not is_valid_memory_filename(filename):
        return None
    return MemoryFileRef(slug=slug, filename=filename)


@frozen(frozen=False)
class MemorySyncCounts:
    slugs: int = 0
    files_written: int = 0
    files_unchanged: int = 0
    files_deleted: int = 0
    errors: int = 0
    skipped: Counter[str] = field(default_factory=Counter)

    def skip(self, reason: str, count: int = 1) -> None:
        self.skipped[reason] += count

    @property
    def files_skipped(self) -> int:
        return sum(self.skipped.values())


@frozen
class SandboxSlugMemory:
    slug: str
    files: dict[str, bytes]
    # Every valid regular-file name the sandbox listed, including files skipped for size or
    # readability. Only a stored name missing from this set may be deleted from storage.
    listed_filenames: frozenset[str]


@frozen
class MemoryRestoreResult:
    counts: MemorySyncCounts
    # True only when the sandbox now mirrors storage for every stored slug. A later persist may
    # delete stored files only after a complete restore, otherwise a failed restore followed by a
    # persist would erase memory the sandbox never received.
    complete: bool


def _memory_dir_entries(sandbox: SandboxBase, slug: str, counts: MemorySyncCounts) -> list[SandboxDirEntry]:
    slug_entries = {entry.name: entry for entry in sandbox.list_dir(f"{SANDBOX_CLAUDE_PROJECTS_DIR}/{slug}")}
    memory_entry = slug_entries.get(MEMORY_DIR_NAME)
    if memory_entry is None:
        return []
    if memory_entry.kind != "dir":
        counts.skip(f"memory_dir_{memory_entry.kind}")
        return []
    return sandbox.list_dir(sandbox_memory_dir(slug))


def _read_sandbox_slug(sandbox: SandboxBase, slug: str, counts: MemorySyncCounts) -> SandboxSlugMemory | None:
    entries = _memory_dir_entries(sandbox, slug, counts)
    if not entries:
        return None
    candidates: list[SandboxDirEntry] = []
    for entry in sorted(entries, key=lambda e: e.name):
        if not is_valid_memory_filename(entry.name):
            counts.skip("invalid_filename")
        elif entry.kind != "file":
            counts.skip(f"not_file_{entry.kind}")
        else:
            candidates.append(entry)
    if not candidates:
        return None
    if len(candidates) > MAX_FILES_PER_SLUG:
        counts.skip("slug_file_limit")
        return None

    files: dict[str, bytes] = {}
    total_bytes = 0
    for entry in candidates:
        # Modal reads whole files, so the listed size is the only bound before the read.
        if entry.size > MAX_FILE_BYTES:
            counts.skip("file_too_large")
            continue
        content = sandbox.read_file(f"{sandbox_memory_dir(slug)}/{entry.name}", MAX_FILE_BYTES)
        if content is None:
            counts.skip("unreadable")
            continue
        if len(content) > MAX_FILE_BYTES:
            counts.skip("file_too_large")
            continue
        total_bytes += len(content)
        if total_bytes > MAX_SLUG_BYTES:
            counts.skip("slug_too_large")
            return None
        files[entry.name] = content
    return SandboxSlugMemory(slug=slug, files=files, listed_filenames=frozenset(entry.name for entry in candidates))


def read_sandbox_memory(sandbox: SandboxBase, counts: MemorySyncCounts) -> list[SandboxSlugMemory]:
    slugs: list[str] = []
    for entry in sorted(sandbox.list_dir(SANDBOX_CLAUDE_PROJECTS_DIR), key=lambda e: e.name):
        if not is_valid_slug(entry.name):
            counts.skip("invalid_slug")
        elif entry.kind != "dir":
            counts.skip(f"slug_{entry.kind}")
        else:
            slugs.append(entry.name)
    if len(slugs) > MAX_SLUGS_PER_USER:
        counts.skip("slug_limit", len(slugs) - MAX_SLUGS_PER_USER)
        slugs = slugs[:MAX_SLUGS_PER_USER]
    result: list[SandboxSlugMemory] = []
    for slug in slugs:
        slug_memory = _read_sandbox_slug(sandbox, slug, counts)
        if slug_memory is not None:
            result.append(slug_memory)
    return result


def _stored_files(user_id: int, prefix: str) -> dict[MemoryFileRef, StoredObjectSummary]:
    stored: dict[MemoryFileRef, StoredObjectSummary] = {}
    for summary in object_storage.list_object_summaries(prefix):
        ref = parse_memory_object_key(user_id, summary.key)
        if ref is not None:
            stored[ref] = summary
    return stored


def _matches_stored(content: bytes, summary: StoredObjectSummary | None) -> bool:
    # A single-part PUT stores the MD5 of the body as the ETag. A multipart ETag contains "-" and is
    # not a content hash, so those files are rewritten.
    if summary is None or not summary.etag or "-" in summary.etag:
        return False
    return summary.etag.strip('"') == hashlib.md5(content, usedforsecurity=False).hexdigest()


def _persist_slug(
    user_id: int, slug_memory: SandboxSlugMemory, *, allow_deletes: bool, counts: MemorySyncCounts
) -> None:
    stored = {
        ref.filename: summary
        for ref, summary in _stored_files(user_id, slug_memory_prefix(user_id, slug_memory.slug)).items()
        if ref.slug == slug_memory.slug
    }
    for filename, content in slug_memory.files.items():
        if _matches_stored(content, stored.get(filename)):
            counts.files_unchanged += 1
            continue
        try:
            object_storage.write(memory_object_key(user_id, slug_memory.slug, filename), content)
        except ObjectStorageError:
            counts.errors += 1
            continue
        counts.files_written += 1

    if not allow_deletes:
        return
    stale_keys = [
        memory_object_key(user_id, slug_memory.slug, filename)
        for filename in sorted(stored.keys() - slug_memory.listed_filenames)
    ]
    if not stale_keys:
        return
    failed = object_storage.delete_objects(stale_keys)
    counts.files_deleted += len(stale_keys) - len(failed)
    counts.errors += len(failed)


def persist_sandbox_memory(sandbox: SandboxBase, *, user_id: int, allow_deletes: bool) -> MemorySyncCounts:
    """Copy the sandbox's memory into storage, replacing each slug the sandbox has.

    Slugs the sandbox lacks stay untouched in storage. Deletes happen only when `allow_deletes`
    is set, which the caller grants once a complete restore has run into this sandbox.
    """
    counts = MemorySyncCounts()
    for slug_memory in read_sandbox_memory(sandbox, counts):
        counts.slugs += 1
        try:
            _persist_slug(user_id, slug_memory, allow_deletes=allow_deletes, counts=counts)
        except ObjectStorageError:
            counts.errors += 1
    return counts


def _read_stored_slug(
    user_id: int, slug: str, summaries: list[StoredObjectSummary], counts: MemorySyncCounts
) -> dict[str, bytes] | None:
    if len(summaries) > MAX_FILES_PER_SLUG:
        counts.skip("slug_file_limit")
        return None
    if any(summary.size > MAX_FILE_BYTES for summary in summaries):
        counts.skip("file_too_large")
        return None
    files: dict[str, bytes] = {}
    total_bytes = 0
    for summary in sorted(summaries, key=lambda s: s.key):
        ref = parse_memory_object_key(user_id, summary.key)
        assert ref is not None
        try:
            content = object_storage.read_bytes(summary.key, missing_ok=True)
        except ObjectStorageError:
            counts.errors += 1
            return None
        if content is None:
            counts.skip("missing")
            return None
        if len(content) > MAX_FILE_BYTES:
            counts.skip("file_too_large")
            return None
        total_bytes += len(content)
        if total_bytes > MAX_SLUG_BYTES:
            counts.skip("slug_too_large")
            return None
        files[ref.filename] = content
    return files


def _write_sandbox_slug(sandbox: SandboxBase, slug: str, files: dict[str, bytes], counts: MemorySyncCounts) -> bool:
    memory_dir = sandbox_memory_dir(slug)
    if sandbox.execute(f"mkdir -p {shlex.quote(memory_dir)}").exit_code != 0:
        counts.errors += 1
        return False
    ok = True
    for filename, content in files.items():
        if sandbox.write_file(f"{memory_dir}/{filename}", content).exit_code != 0:
            counts.errors += 1
            ok = False
            continue
        counts.files_written += 1
    stale = sorted(
        entry.name
        for entry in sandbox.list_dir(memory_dir)
        if entry.kind in ("file", "symlink") and is_valid_memory_filename(entry.name) and entry.name not in files
    )
    if stale:
        paths = " ".join(shlex.quote(f"{memory_dir}/{name}") for name in stale)
        if sandbox.execute(f"rm -f -- {paths}").exit_code != 0:
            counts.errors += 1
            return False
        counts.files_deleted += len(stale)
    return ok


def restore_sandbox_memory(
    sandbox: SandboxBase, *, user_id: int, deadline_seconds: float = RESTORE_DEADLINE_SECONDS
) -> MemoryRestoreResult:
    """Write the user's stored memory into the sandbox, replacing each slug storage has.

    Must run before agent-server boots, while the agent cannot yet race the writes. Raises
    ObjectStorageError when storage cannot be listed, because an empty result must mean an empty prefix.
    """
    counts = MemorySyncCounts()
    summaries = object_storage.list_object_summaries(user_memory_prefix(user_id))

    if sandbox.list_dir(SANDBOX_HOME_CLAUDE_PROJECTS_DIR) and not sandbox.list_dir(SANDBOX_CLAUDE_PROJECTS_DIR):
        counts.skip("home_projects_unmigrated")
        return MemoryRestoreResult(counts=counts, complete=False)

    by_slug: dict[str, list[StoredObjectSummary]] = {}
    for summary in summaries:
        ref = parse_memory_object_key(user_id, summary.key)
        if ref is None:
            counts.skip("invalid_key")
            continue
        by_slug.setdefault(ref.slug, []).append(summary)
    slugs = sorted(by_slug)
    complete = True
    if len(slugs) > MAX_SLUGS_PER_USER:
        counts.skip("slug_limit", len(slugs) - MAX_SLUGS_PER_USER)
        slugs = slugs[:MAX_SLUGS_PER_USER]
        complete = False

    started_at = time.monotonic()
    for slug in slugs:
        if time.monotonic() - started_at > deadline_seconds:
            counts.skip("deadline", len(slugs) - counts.slugs)
            complete = False
            break
        counts.slugs += 1
        files = _read_stored_slug(user_id, slug, by_slug[slug], counts)
        if files is None:
            complete = False
            continue
        if not _write_sandbox_slug(sandbox, slug, files, counts):
            complete = False
    return MemoryRestoreResult(counts=counts, complete=complete)
