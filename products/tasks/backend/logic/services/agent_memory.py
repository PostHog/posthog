"""Carry Claude Code auto memory between cloud sandboxes through object storage.

Storage holds one object per memory file at
`tasks/agent-memory/<team_id>/<user_id>/claude/<slug>/<filename>`, so memory never crosses projects.
Everything read from a sandbox is agent-controlled, so slugs and filenames are validated against a
strict shape before they become part of an object key or a sandbox path, and sizes are capped.

Restore records what it wrote in a baseline file inside the sandbox. Persist compares the sandbox
with that baseline and uploads only what the agent changed, so a sandbox that never touched a slug
cannot overwrite or delete newer memory that another sandbox saved for it.
"""

from __future__ import annotations

import re
import json
import time
import shlex
import hashlib
from collections import Counter
from dataclasses import field
from typing import TYPE_CHECKING, Any

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
# Outside the agent-state tree, so the agent's own config directories never contain it.
SANDBOX_BASELINE_DIR = f"{DEFAULT_SANDBOX_WORKING_DIR}/.posthog/agent-memory"
SANDBOX_BASELINE_PATH = f"{SANDBOX_BASELINE_DIR}/baseline.json"
MEMORY_DIR_NAME = "memory"
STORAGE_PREFIX = "tasks/agent-memory"

MAX_FILE_BYTES = 256 * 1024
MAX_SLUG_BYTES = 2 * 1024 * 1024
MAX_FILES_PER_SLUG = 200
MAX_SLUGS_PER_USER = 50
MAX_BASELINE_BYTES = 4 * 1024 * 1024
RESTORE_DEADLINE_SECONDS = 60.0

_SLUG_PATTERN = re.compile(r"-[A-Za-z0-9._-]{1,200}")
_FILENAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,120}\.md")
_MD5_PATTERN = re.compile(r"[0-9a-f]{32}")


def is_valid_slug(slug: str) -> bool:
    return _SLUG_PATTERN.fullmatch(slug) is not None and ".." not in slug


def is_valid_memory_filename(filename: str) -> bool:
    return _FILENAME_PATTERN.fullmatch(filename) is not None and filename not in {".", ".."}


def user_memory_prefix(team_id: int, user_id: int) -> str:
    return f"{STORAGE_PREFIX}/{int(team_id)}/{int(user_id)}/claude/"


def slug_memory_prefix(team_id: int, user_id: int, slug: str) -> str:
    if not is_valid_slug(slug):
        raise ValueError("invalid memory slug")
    return f"{user_memory_prefix(team_id, user_id)}{slug}/"


def memory_object_key(team_id: int, user_id: int, slug: str, filename: str) -> str:
    if not is_valid_memory_filename(filename):
        raise ValueError("invalid memory filename")
    return f"{slug_memory_prefix(team_id, user_id, slug)}{filename}"


def sandbox_slug_dir(slug: str) -> str:
    if not is_valid_slug(slug):
        raise ValueError("invalid memory slug")
    return f"{SANDBOX_CLAUDE_PROJECTS_DIR}/{slug}"


def sandbox_memory_dir(slug: str) -> str:
    return f"{sandbox_slug_dir(slug)}/{MEMORY_DIR_NAME}"


@frozen
class MemoryFileRef:
    slug: str
    filename: str


def parse_memory_object_key(team_id: int, user_id: int, key: str) -> MemoryFileRef | None:
    prefix = user_memory_prefix(team_id, user_id)
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
class BaselineFile:
    md5: str
    size: int
    mtime: float


# slug -> filename -> the state restore or the last persist left the file in.
Baseline = dict[str, dict[str, BaselineFile]]


@frozen
class MemoryRestoreResult:
    counts: MemorySyncCounts
    # True only when the sandbox now mirrors storage for every stored slug. A later persist may
    # delete stored files only after a complete restore, otherwise a failed restore followed by a
    # persist would erase memory the sandbox never received.
    complete: bool


class RestoreDeadlineExceeded(Exception):
    pass


def _md5(content: bytes) -> str:
    return hashlib.md5(content, usedforsecurity=False).hexdigest()


def _parse_baseline_file(value: Any) -> BaselineFile | None:
    if not isinstance(value, dict):
        return None
    md5, size, mtime = value.get("md5"), value.get("size"), value.get("mtime")
    if not isinstance(md5, str) or _MD5_PATTERN.fullmatch(md5) is None:
        return None
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return None
    if not isinstance(mtime, (int, float)) or isinstance(mtime, bool):
        return None
    return BaselineFile(md5=md5, size=size, mtime=float(mtime))


def parse_baseline(raw: bytes | None) -> Baseline:
    """The baseline the sandbox holds, or an empty one when it is missing or malformed in any part.

    An empty baseline makes the next persist write every file and delete nothing.
    """
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict) or len(data) > MAX_SLUGS_PER_USER:
        return {}
    baseline: Baseline = {}
    for slug, files in data.items():
        if not is_valid_slug(slug) or not isinstance(files, dict) or len(files) > MAX_FILES_PER_SLUG:
            return {}
        parsed: dict[str, BaselineFile] = {}
        for filename, value in files.items():
            baseline_file = _parse_baseline_file(value)
            if not is_valid_memory_filename(filename) or baseline_file is None:
                return {}
            parsed[filename] = baseline_file
        baseline[slug] = parsed
    return baseline


def _serialize_baseline(baseline: Baseline) -> bytes:
    return json.dumps(
        {
            slug: {name: {"md5": f.md5, "size": f.size, "mtime": f.mtime} for name, f in sorted(files.items())}
            for slug, files in sorted(baseline.items())
        }
    ).encode()


def read_baseline(sandbox: SandboxBase) -> Baseline:
    return parse_baseline(sandbox.read_file(SANDBOX_BASELINE_PATH, MAX_BASELINE_BYTES))


def write_baseline(sandbox: SandboxBase, baseline: Baseline) -> bool:
    """Best-effort: a lost baseline only makes the next persist write more and delete nothing."""
    try:
        if sandbox.execute(f"mkdir -p {shlex.quote(SANDBOX_BASELINE_DIR)}").exit_code != 0:
            return False
        return sandbox.write_file(SANDBOX_BASELINE_PATH, _serialize_baseline(baseline)).exit_code == 0
    except Exception:
        logger.warning("agent_memory_baseline_write_failed", sandbox_id=sandbox.id, exc_info=True)
        return False


def _list_sandbox_slugs(sandbox: SandboxBase, counts: MemorySyncCounts) -> list[str]:
    slugs: list[str] = []
    for entry in sorted(sandbox.list_dir(SANDBOX_CLAUDE_PROJECTS_DIR) or [], key=lambda e: e.name):
        if not is_valid_slug(entry.name):
            counts.skip("invalid_slug")
        elif entry.kind != "dir":
            counts.skip(f"slug_{entry.kind}")
        else:
            slugs.append(entry.name)
    if len(slugs) > MAX_SLUGS_PER_USER:
        counts.skip("slug_limit", len(slugs) - MAX_SLUGS_PER_USER)
        slugs = slugs[:MAX_SLUGS_PER_USER]
    return slugs


def _memory_file_entries(
    sandbox: SandboxBase, slug: str, *, in_sandbox: bool, counts: MemorySyncCounts
) -> list[SandboxDirEntry] | None:
    """The slug's memory files; an empty list when the directory is gone, None to leave the slug alone."""
    if not in_sandbox:
        return []
    slug_entries = {entry.name: entry for entry in sandbox.list_dir(sandbox_slug_dir(slug)) or []}
    memory_entry = slug_entries.get(MEMORY_DIR_NAME)
    if memory_entry is None:
        return []
    if memory_entry.kind != "dir":
        counts.skip(f"memory_dir_{memory_entry.kind}")
        return None
    files: list[SandboxDirEntry] = []
    for entry in sorted(sandbox.list_dir(sandbox_memory_dir(slug)) or [], key=lambda e: e.name):
        if not is_valid_memory_filename(entry.name):
            counts.skip("invalid_filename")
        elif entry.kind != "file":
            counts.skip(f"not_file_{entry.kind}")
        else:
            files.append(entry)
    return files


def _stored_summaries(team_id: int, user_id: int, slug: str) -> dict[str, StoredObjectSummary]:
    stored: dict[str, StoredObjectSummary] = {}
    for summary in object_storage.list_object_summaries(slug_memory_prefix(team_id, user_id, slug)):
        ref = parse_memory_object_key(team_id, user_id, summary.key)
        if ref is not None and ref.slug == slug:
            stored[ref.filename] = summary
    return stored


def _matches_stored(content: bytes, summary: StoredObjectSummary | None) -> bool:
    # A single-part PUT stores the MD5 of the body as the ETag. A multipart ETag contains "-" and is
    # not a content hash, so those files are rewritten.
    if summary is None or not summary.etag or "-" in summary.etag:
        return False
    return summary.etag.strip('"') == _md5(content)


def _persist_slug(
    sandbox: SandboxBase,
    *,
    team_id: int,
    user_id: int,
    slug: str,
    entries: list[SandboxDirEntry],
    base: dict[str, BaselineFile],
    allow_deletes: bool,
    counts: MemorySyncCounts,
) -> dict[str, BaselineFile] | None:
    """Upload what changed in one slug since the baseline. Returns the slug's new baseline."""
    if len(entries) > MAX_FILES_PER_SLUG:
        counts.skip("slug_file_limit")
        return None
    if sum(entry.size for entry in entries) > MAX_SLUG_BYTES:
        counts.skip("slug_too_large")
        return None

    new_base: dict[str, BaselineFile] = {}
    changed: dict[str, bytes] = {}
    for entry in entries:
        old = base.get(entry.name)
        if old is not None and old.size == entry.size and old.mtime == entry.mtime:
            new_base[entry.name] = old
            counts.files_unchanged += 1
            continue
        content = None
        if entry.size <= MAX_FILE_BYTES:
            content = sandbox.read_file(f"{sandbox_memory_dir(slug)}/{entry.name}", MAX_FILE_BYTES)
            if content is None:
                counts.skip("unreadable")
        if content is None or len(content) > MAX_FILE_BYTES:
            if entry.size > MAX_FILE_BYTES or content is not None:
                counts.skip("file_too_large")
            # Keeping the old entry stops a skipped file from reading as removed.
            if old is not None:
                new_base[entry.name] = old
            continue
        digest = _md5(content)
        new_base[entry.name] = BaselineFile(md5=digest, size=len(content), mtime=entry.mtime)
        if old is not None and old.md5 == digest:
            counts.files_unchanged += 1
        else:
            changed[entry.name] = content
    listed = {entry.name for entry in entries}
    removed = sorted(name for name in base if name not in listed)
    if not changed and not removed:
        return new_base

    stored = _stored_summaries(team_id, user_id, slug)
    for filename, content in changed.items():
        if _matches_stored(content, stored.get(filename)):
            continue
        object_storage.write(memory_object_key(team_id, user_id, slug, filename), content)
        counts.files_written += 1
    if not removed:
        return new_base
    if not allow_deletes:
        counts.skip("delete_not_allowed", len(removed))
        return new_base
    stale_keys = [memory_object_key(team_id, user_id, slug, name) for name in removed if name in stored]
    if stale_keys:
        failed = object_storage.delete_objects(stale_keys)
        if failed:
            raise ObjectStorageError(f"failed to delete {len(failed)} memory files")
        counts.files_deleted += len(stale_keys)
    return new_base


def persist_sandbox_memory(
    sandbox: SandboxBase, *, team_id: int, user_id: int, allow_deletes: bool
) -> MemorySyncCounts:
    """Upload the memory the agent changed since the baseline.

    A slug with no change against the baseline is not touched in storage. A stored file is deleted
    only when the baseline had it, the sandbox no longer lists it, and `allow_deletes` is set.
    Storage failures raise so the caller can retry.
    """
    counts = MemorySyncCounts()
    baseline = read_baseline(sandbox)
    sandbox_slugs = set(_list_sandbox_slugs(sandbox, counts))
    updated: Baseline = dict(baseline)
    dirty = False
    try:
        for slug in sorted(sandbox_slugs | baseline.keys()):
            entries = _memory_file_entries(sandbox, slug, in_sandbox=slug in sandbox_slugs, counts=counts)
            if entries is None:
                continue
            counts.slugs += 1
            new_base = _persist_slug(
                sandbox,
                team_id=team_id,
                user_id=user_id,
                slug=slug,
                entries=entries,
                base=baseline.get(slug, {}),
                allow_deletes=allow_deletes,
                counts=counts,
            )
            if new_base is not None and new_base != baseline.get(slug):
                updated[slug] = new_base
                dirty = True
    finally:
        if dirty:
            write_baseline(sandbox, updated)
    return counts


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise RestoreDeadlineExceeded


def _read_stored_slug(
    team_id: int,
    user_id: int,
    summaries: list[StoredObjectSummary],
    counts: MemorySyncCounts,
    deadline: float,
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
        ref = parse_memory_object_key(team_id, user_id, summary.key)
        assert ref is not None
        _check_deadline(deadline)
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


def _write_sandbox_slug(
    sandbox: SandboxBase, slug: str, files: dict[str, bytes], counts: MemorySyncCounts, deadline: float
) -> dict[str, BaselineFile] | None:
    """Make the sandbox slug match `files`. Returns the slug's baseline, or None when a write failed."""
    memory_dir = sandbox_memory_dir(slug)
    _check_deadline(deadline)
    if sandbox.execute(f"mkdir -p {shlex.quote(memory_dir)}").exit_code != 0:
        counts.errors += 1
        return None
    ok = True
    for filename, content in files.items():
        _check_deadline(deadline)
        if sandbox.write_file(f"{memory_dir}/{filename}", content).exit_code != 0:
            counts.errors += 1
            ok = False
            continue
        counts.files_written += 1
    _check_deadline(deadline)
    stale = sorted(
        entry.name
        for entry in sandbox.list_dir(memory_dir) or []
        if entry.kind in ("file", "symlink") and is_valid_memory_filename(entry.name) and entry.name not in files
    )
    if stale:
        _check_deadline(deadline)
        paths = " ".join(shlex.quote(f"{memory_dir}/{name}") for name in stale)
        if sandbox.execute(f"rm -f -- {paths}").exit_code != 0:
            counts.errors += 1
            return None
        counts.files_deleted += len(stale)
    if not ok:
        return None
    _check_deadline(deadline)
    base: dict[str, BaselineFile] = {}
    for entry in sandbox.list_dir(memory_dir) or []:
        written = files.get(entry.name)
        if entry.kind == "file" and written is not None and entry.size == len(written):
            base[entry.name] = BaselineFile(md5=_md5(written), size=entry.size, mtime=entry.mtime)
    return base


def restore_sandbox_memory(
    sandbox: SandboxBase, *, team_id: int, user_id: int, deadline: float | None = None
) -> MemoryRestoreResult:
    """Write the user's stored memory into the sandbox, replacing each slug storage has.

    Must run before agent-server boots, while the agent cannot yet race the writes. `deadline` is a
    `time.monotonic()` timestamp. Raises ObjectStorageError when storage cannot be listed, because an
    empty result must mean an empty prefix.
    """
    deadline = time.monotonic() + RESTORE_DEADLINE_SECONDS if deadline is None else deadline
    counts = MemorySyncCounts()
    # A snapshot can carry an older sandbox's baseline. Clear it first so a failed restore leaves
    # the next persist with nothing to compare against, which means writes only and no deletes.
    if not write_baseline(sandbox, {}):
        counts.errors += 1
        return MemoryRestoreResult(counts=counts, complete=False)

    summaries = object_storage.list_object_summaries(user_memory_prefix(team_id, user_id))

    if sandbox.list_dir(SANDBOX_HOME_CLAUDE_PROJECTS_DIR) and not sandbox.list_dir(SANDBOX_CLAUDE_PROJECTS_DIR):
        counts.skip("home_projects_unmigrated")
        return MemoryRestoreResult(counts=counts, complete=False)

    by_slug: dict[str, list[StoredObjectSummary]] = {}
    for summary in summaries:
        ref = parse_memory_object_key(team_id, user_id, summary.key)
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

    baseline: Baseline = {}
    try:
        for slug in slugs:
            counts.slugs += 1
            files = _read_stored_slug(team_id, user_id, by_slug[slug], counts, deadline)
            if files is None:
                complete = False
                continue
            slug_base = _write_sandbox_slug(sandbox, slug, files, counts, deadline)
            if slug_base is None:
                complete = False
                continue
            baseline[slug] = slug_base
    except RestoreDeadlineExceeded:
        counts.skip("deadline")
        complete = False
    finally:
        # Written even past the deadline: it is one call, and without it every restored slug would
        # look newly added to the next persist.
        if baseline and not write_baseline(sandbox, baseline):
            complete = False
    return MemoryRestoreResult(counts=counts, complete=complete)
