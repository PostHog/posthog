import shlex
import hashlib
from collections.abc import Iterator

import pytest
from unittest.mock import patch

from posthog.storage.object_storage import ObjectStorageError, StoredObjectSummary

from products.tasks.backend.logic.services import agent_memory
from products.tasks.backend.logic.services.agent_memory import (
    MAX_FILE_BYTES,
    SANDBOX_CLAUDE_PROJECTS_DIR,
    SANDBOX_HOME_CLAUDE_PROJECTS_DIR,
    is_valid_memory_filename,
    is_valid_slug,
    memory_object_key,
    parse_memory_object_key,
    persist_sandbox_memory,
    restore_sandbox_memory,
)
from products.tasks.backend.logic.services.sandbox import ExecutionResult, SandboxDirEntry

USER_ID = 7
REPO_SLUG = "-tmp-workspace-repos-posthog-posthog"
WORKSPACE_SLUG = "-tmp-workspace"


def _memory_path(slug: str, filename: str) -> str:
    return f"{SANDBOX_CLAUDE_PROJECTS_DIR}/{slug}/memory/{filename}"


class FakeSandbox:
    id = "sb-1"

    def __init__(self, files: dict[str, bytes] | None = None, symlinks: frozenset[str] = frozenset()) -> None:
        self.files: dict[str, bytes] = dict(files or {})
        self.symlinks = symlinks
        self.reads: list[str] = []

    def list_dir(self, path: str) -> list[SandboxDirEntry]:
        prefix = path.rstrip("/") + "/"
        entries: dict[str, SandboxDirEntry] = {}
        for file_path, content in self.files.items():
            if not file_path.startswith(prefix):
                continue
            name, _, rest = file_path[len(prefix) :].partition("/")
            if rest:
                entries[name] = SandboxDirEntry(name=name, kind="dir", size=0)
            else:
                entries[name] = SandboxDirEntry(
                    name=name, kind="symlink" if file_path in self.symlinks else "file", size=len(content)
                )
        return list(entries.values())

    def read_file(self, path: str, max_bytes: int) -> bytes | None:
        self.reads.append(path)
        return self.files.get(path)

    def write_file(self, path: str, payload: bytes, timeout_seconds: int | None = None) -> ExecutionResult:
        self.files[path] = payload
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def execute(self, command: str, timeout_seconds: int | None = None) -> ExecutionResult:
        argv = shlex.split(command)
        if argv[:3] == ["rm", "-f", "--"]:
            for path in argv[3:]:
                self.files.pop(path, None)
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.etags: dict[str, str] = {}
        self.list_fails = False
        self.writes: list[str] = []

    def list_object_summaries(self, prefix: str, bucket: str | None = None) -> list[StoredObjectSummary]:
        if self.list_fails:
            raise ObjectStorageError("list_objects failed")
        return [
            StoredObjectSummary(
                key=key,
                etag=self.etags.get(key, f'"{hashlib.md5(content).hexdigest()}"'),
                size=len(content),
            )
            for key, content in sorted(self.objects.items())
            if key.startswith(prefix)
        ]

    def read_bytes(self, file_name: str, bucket: str | None = None, *, missing_ok: bool = False) -> bytes | None:
        return self.objects.get(file_name)

    def write(self, file_name: str, content: bytes, extras: dict | None = None, bucket: str | None = None) -> None:
        self.writes.append(file_name)
        self.objects[file_name] = content

    def delete_objects(self, file_names: list[str], bucket: str | None = None) -> list[str]:
        for name in file_names:
            self.objects.pop(name, None)
        return []


@pytest.fixture
def storage() -> Iterator[FakeStorage]:
    fake = FakeStorage()
    with patch.object(agent_memory, "object_storage", fake):
        yield fake


@pytest.mark.parametrize(
    "slug, expected",
    [
        (WORKSPACE_SLUG, True),
        (REPO_SLUG, True),
        ("..", False),
        ("-..", False),
        ("-a/b", False),
        ("/tmp/workspace", False),
        ("tmp-workspace", False),
        ("-tmp-workspace\n", False),
        ("", False),
    ],
)
def test_slug_validation(slug: str, expected: bool) -> None:
    assert is_valid_slug(slug) is expected


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("MEMORY.md", True),
        ("debugging_notes.md", True),
        ("../MEMORY.md", False),
        ("a/b.md", False),
        ("/etc/passwd.md", False),
        ("notes.txt", False),
        (".md", False),
        ("MEMORY.md\n", False),
    ],
)
def test_filename_validation(filename: str, expected: bool) -> None:
    assert is_valid_memory_filename(filename) is expected


@pytest.mark.parametrize(
    "key",
    [
        f"tasks/agent-memory/8/claude/{REPO_SLUG}/MEMORY.md",
        f"tasks/agent-memory/{USER_ID}/claude/../MEMORY.md",
        f"tasks/agent-memory/{USER_ID}/claude/{REPO_SLUG}/nested/MEMORY.md",
        f"tasks/agent-memory/{USER_ID}/claude/{REPO_SLUG}/notes.txt",
    ],
)
def test_parse_memory_object_key_rejects_foreign_and_malformed_keys(key: str) -> None:
    assert parse_memory_object_key(USER_ID, key) is None


@pytest.mark.parametrize("allow_deletes", [True, False])
def test_persist_replaces_only_the_slugs_the_sandbox_has(storage: FakeStorage, allow_deletes: bool) -> None:
    unchanged_key = memory_object_key(USER_ID, REPO_SLUG, "MEMORY.md")
    multipart_key = memory_object_key(USER_ID, REPO_SLUG, "multipart.md")
    removed_key = memory_object_key(USER_ID, REPO_SLUG, "removed.md")
    oversize_key = memory_object_key(USER_ID, REPO_SLUG, "big.md")
    other_slug_key = memory_object_key(USER_ID, WORKSPACE_SLUG, "MEMORY.md")
    storage.objects = {
        unchanged_key: b"index",
        multipart_key: b"same bytes",
        removed_key: b"gone from the sandbox",
        oversize_key: b"last version under the cap",
        other_slug_key: b"another checkout",
    }
    storage.etags[multipart_key] = '"0123abcd-2"'
    symlink = _memory_path(REPO_SLUG, "link.md")
    sandbox = FakeSandbox(
        {
            _memory_path(REPO_SLUG, "MEMORY.md"): b"index",
            _memory_path(REPO_SLUG, "multipart.md"): b"same bytes",
            _memory_path(REPO_SLUG, "new.md"): b"fresh",
            _memory_path(REPO_SLUG, "big.md"): b"x" * (MAX_FILE_BYTES + 1),
            _memory_path(REPO_SLUG, "notes.txt"): b"not memory",
            symlink: b"target of a symlink",
        },
        symlinks=frozenset({symlink}),
    )

    counts = persist_sandbox_memory(sandbox, user_id=USER_ID, allow_deletes=allow_deletes)  # type: ignore[arg-type]

    assert storage.writes == [multipart_key, memory_object_key(USER_ID, REPO_SLUG, "new.md")]
    assert storage.objects[oversize_key] == b"last version under the cap"
    assert storage.objects[other_slug_key] == b"another checkout"
    assert (removed_key in storage.objects) is not allow_deletes
    assert symlink not in sandbox.reads
    assert _memory_path(REPO_SLUG, "big.md") not in sandbox.reads
    assert counts.files_unchanged == 1
    assert counts.skipped == {"file_too_large": 1, "invalid_filename": 1, "not_file_symlink": 1}


def test_restore_replaces_stored_slugs_and_ignores_malformed_keys(storage: FakeStorage) -> None:
    storage.objects = {
        memory_object_key(USER_ID, REPO_SLUG, "MEMORY.md"): b"stored index",
        memory_object_key(USER_ID, REPO_SLUG, "topic.md"): b"stored topic",
        f"tasks/agent-memory/{USER_ID}/claude/{REPO_SLUG}/nested/evil.md": b"nested",
        f"tasks/agent-memory/{USER_ID}/claude/-..x/escape.md": b"escape",
    }
    untouched = _memory_path(WORKSPACE_SLUG, "keep.md")
    sandbox = FakeSandbox(
        {
            _memory_path(REPO_SLUG, "MEMORY.md"): b"old index",
            _memory_path(REPO_SLUG, "stale.md"): b"not in storage",
            untouched: b"slug storage does not have",
        }
    )

    result = restore_sandbox_memory(sandbox, user_id=USER_ID)  # type: ignore[arg-type]

    assert sandbox.files == {
        _memory_path(REPO_SLUG, "MEMORY.md"): b"stored index",
        _memory_path(REPO_SLUG, "topic.md"): b"stored topic",
        untouched: b"slug storage does not have",
    }
    assert result.complete is True
    assert result.counts.skipped == {"invalid_key": 2}


@pytest.mark.parametrize(
    "stored, sandbox_files, expected_complete",
    [
        ({}, {}, True),
        (
            {memory_object_key(USER_ID, REPO_SLUG, "MEMORY.md"): b"stored index"},
            {f"{SANDBOX_HOME_CLAUDE_PROJECTS_DIR}/{REPO_SLUG}/session.jsonl": b"{}"},
            False,
        ),
    ],
)
def test_restore_is_complete_only_when_the_sandbox_mirrors_storage(
    storage: FakeStorage, stored: dict[str, bytes], sandbox_files: dict[str, bytes], expected_complete: bool
) -> None:
    storage.objects = dict(stored)
    sandbox = FakeSandbox(sandbox_files)

    result = restore_sandbox_memory(sandbox, user_id=USER_ID)  # type: ignore[arg-type]

    assert result.complete is expected_complete
    assert sandbox.files == sandbox_files


def test_restore_raises_when_storage_cannot_be_listed(storage: FakeStorage) -> None:
    storage.list_fails = True

    with pytest.raises(ObjectStorageError):
        restore_sandbox_memory(FakeSandbox(), user_id=USER_ID)  # type: ignore[arg-type]
