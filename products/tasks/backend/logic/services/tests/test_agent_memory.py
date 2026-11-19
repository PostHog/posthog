import json
import shlex
import hashlib
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from unittest.mock import patch

from posthog.storage.object_storage import ObjectStorageError, StoredObjectSummary

from products.tasks.backend.logic.services import agent_memory
from products.tasks.backend.logic.services.agent_memory import (
    MAX_FILE_BYTES,
    MAX_SLUGS_PER_USER,
    MAX_STORED_KEYS,
    SANDBOX_BASELINE_PATH,
    SANDBOX_CLAUDE_PROJECTS_DIR,
    SANDBOX_HOME_CLAUDE_PROJECTS_DIR,
    BaselineCheckpointError,
    is_valid_memory_filename,
    is_valid_slug,
    memory_object_key,
    parse_baseline,
    parse_memory_object_key,
    persist_sandbox_memory,
    restore_sandbox_memory,
)
from products.tasks.backend.logic.services.sandbox import ExecutionResult, SandboxDirEntry

TEAM_ID = 3
USER_ID = 7
REPO_SLUG = "-tmp-workspace-repos-posthog-posthog"
WORKSPACE_SLUG = "-tmp-workspace"
OK = ExecutionResult(stdout="", stderr="", exit_code=0, error=None)


def _memory_path(slug: str, filename: str) -> str:
    return f"{SANDBOX_CLAUDE_PROJECTS_DIR}/{slug}/memory/{filename}"


def _key(slug: str, filename: str) -> str:
    return memory_object_key(TEAM_ID, USER_ID, slug, filename)


def _md5(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()


class FakeSandbox:
    id = "sb-1"

    def __init__(
        self,
        files: dict[str, bytes] | None = None,
        *,
        dirs: frozenset[str] = frozenset(),
        symlinks: frozenset[str] = frozenset(),
    ) -> None:
        self.files: dict[str, bytes] = dict(files or {})
        self.mtimes: dict[str, float] = dict.fromkeys(self.files, 1.0)
        self.dirs = set(dirs)
        self.symlinks = symlinks
        self.reads: list[str] = []
        self.clock = 1.0
        self.failing_writes: set[str] = set()
        self.memory_writes = 0
        # Content returned for every read, to model files that grow after the listing.
        self.grown_on_read: bytes | None = None
        self.list_limits: list[int | None] = []

    def _is_dir(self, path: str) -> bool:
        prefix = path + "/"
        return path in self.dirs or any(p.startswith(prefix) for p in [*self.files, *self.dirs])

    def list_dir(self, path: str, *, limit: int | None = None) -> list[SandboxDirEntry] | None:
        self.list_limits.append(limit)
        if not self._is_dir(path):
            return None
        prefix = path + "/"
        entries: dict[str, SandboxDirEntry] = {}
        for child in [*self.files, *self.dirs]:
            if not child.startswith(prefix):
                continue
            name, _, rest = child[len(prefix) :].partition("/")
            if rest or child in self.dirs:
                entries[name] = SandboxDirEntry(name=name, kind="dir", size=0, mtime=0.0)
            else:
                entries[name] = SandboxDirEntry(
                    name=name,
                    kind="symlink" if child in self.symlinks else "file",
                    size=len(self.files[child]),
                    mtime=self.mtimes[child],
                )
        return sorted(entries.values(), key=lambda entry: entry.name)[:limit]

    def read_file(self, path: str, max_bytes: int) -> bytes | None:
        self.reads.append(path)
        if self.grown_on_read is not None and path in self.files:
            return self.grown_on_read
        return self.files.get(path)

    def write_file(self, path: str, payload: bytes, timeout_seconds: int | None = None) -> ExecutionResult:
        if path in self.failing_writes:
            return ExecutionResult(stdout="", stderr="write failed", exit_code=1, error=None)
        if path.startswith(SANDBOX_CLAUDE_PROJECTS_DIR):
            self.memory_writes += 1
        self.clock += 1
        self.files[path] = payload
        self.mtimes[path] = self.clock
        return OK

    def execute(self, command: str, timeout_seconds: int | None = None) -> ExecutionResult:
        argv = shlex.split(command)
        if argv[:2] == ["mkdir", "-p"]:
            self.dirs.add(argv[2])
        if argv[:3] == ["rm", "-f", "--"]:
            for path in argv[3:]:
                self.files.pop(path, None)
        return OK

    def set_baseline(self, baseline: dict) -> None:
        self.files[SANDBOX_BASELINE_PATH] = json.dumps(baseline).encode()
        self.mtimes[SANDBOX_BASELINE_PATH] = 1.0

    def memory(self) -> dict[str, bytes]:
        return {p: c for p, c in self.files.items() if p.startswith(SANDBOX_CLAUDE_PROJECTS_DIR)}


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.list_fails = False
        self.writes: list[str] = []
        self.failing_writes: set[str] = set()
        self.clock = 0.0

    def list_object_summaries(
        self, prefix: str, bucket: str | None = None, *, limit: int | None = None
    ) -> list[StoredObjectSummary]:
        if self.list_fails:
            raise ObjectStorageError("list_objects failed")
        return [
            StoredObjectSummary(key=key, etag=f'"{_md5(content)}"', size=len(content))
            for key, content in sorted(self.objects.items())
            if key.startswith(prefix)
        ][:limit]

    def read_bytes(self, file_name: str, bucket: str | None = None, *, missing_ok: bool = False) -> bytes | None:
        self.clock += 10
        return self.objects.get(file_name)

    def write(self, file_name: str, content: bytes, extras: dict | None = None, bucket: str | None = None) -> None:
        if file_name in self.failing_writes:
            raise ObjectStorageError("write failed")
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
        f"tasks/agent-memory/{TEAM_ID}/8/claude/{REPO_SLUG}/MEMORY.md",
        f"tasks/agent-memory/4/{USER_ID}/claude/{REPO_SLUG}/MEMORY.md",
        f"tasks/agent-memory/{TEAM_ID}/{USER_ID}/claude/../MEMORY.md",
        f"tasks/agent-memory/{TEAM_ID}/{USER_ID}/claude/{REPO_SLUG}/nested/MEMORY.md",
        f"tasks/agent-memory/{TEAM_ID}/{USER_ID}/claude/{REPO_SLUG}/notes.txt",
    ],
)
def test_parse_memory_object_key_rejects_foreign_and_malformed_keys(key: str) -> None:
    assert parse_memory_object_key(TEAM_ID, USER_ID, key) is None


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"[]",
        json.dumps({"../escape": {}}).encode(),
        json.dumps({REPO_SLUG: {"../x.md": {"md5": "0" * 32, "size": 1, "mtime": 1.0}}}).encode(),
        json.dumps({REPO_SLUG: {"MEMORY.md": {"md5": "short", "size": 1, "mtime": 1.0}}}).encode(),
        json.dumps({REPO_SLUG: {"MEMORY.md": {"md5": "0" * 32, "size": True, "mtime": 1.0}}}).encode(),
    ],
)
def test_a_malformed_baseline_reads_as_empty(raw: bytes) -> None:
    assert parse_baseline(raw) == {}


def test_persist_uploads_only_what_changed_since_the_baseline(storage: FakeStorage) -> None:
    storage.objects = {
        _key(WORKSPACE_SLUG, "MEMORY.md"): b"newer, saved by another sandbox",
        _key(REPO_SLUG, "MEMORY.md"): b"index",
        _key(REPO_SLUG, "removed.md"): b"gone from the sandbox",
        _key(REPO_SLUG, "other.md"): b"added by another sandbox",
    }
    symlink = _memory_path(REPO_SLUG, "link.md")
    sandbox = FakeSandbox(
        {
            _memory_path(WORKSPACE_SLUG, "MEMORY.md"): b"restored earlier",
            _memory_path(REPO_SLUG, "MEMORY.md"): b"index",
            _memory_path(REPO_SLUG, "new.md"): b"fresh",
            _memory_path(REPO_SLUG, "big.md"): b"x" * (MAX_FILE_BYTES + 1),
            _memory_path(REPO_SLUG, "notes.txt"): b"not memory",
            symlink: b"target of a symlink",
        },
        symlinks=frozenset({symlink}),
    )
    sandbox.set_baseline(
        {
            WORKSPACE_SLUG: {"MEMORY.md": {"md5": _md5(b"restored earlier"), "size": 16, "mtime": 1.0}},
            REPO_SLUG: {
                "MEMORY.md": {"md5": _md5(b"index"), "size": 5, "mtime": 1.0},
                "removed.md": {"md5": _md5(b"gone from the sandbox"), "size": 21, "mtime": 1.0},
            },
        }
    )

    counts = persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert storage.writes == [_key(REPO_SLUG, "new.md")]
    assert storage.objects[_key(WORKSPACE_SLUG, "MEMORY.md")] == b"newer, saved by another sandbox"
    assert storage.objects[_key(REPO_SLUG, "other.md")] == b"added by another sandbox"
    assert _key(REPO_SLUG, "removed.md") not in storage.objects
    assert sandbox.reads == [SANDBOX_BASELINE_PATH, _memory_path(REPO_SLUG, "new.md")]
    assert counts.skipped["not_file_symlink"] == 1
    assert counts.skipped["file_too_large"] == 1
    assert None not in sandbox.list_limits

    sandbox.reads.clear()
    storage.writes.clear()
    persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert storage.writes == []
    assert sandbox.reads == [SANDBOX_BASELINE_PATH]


@pytest.mark.parametrize(
    "sandbox_dirs, baseline_valid, expected_deleted",
    [
        (frozenset({f"{SANDBOX_CLAUDE_PROJECTS_DIR}/{REPO_SLUG}/memory"}), True, True),
        (frozenset({SANDBOX_CLAUDE_PROJECTS_DIR}), True, True),
        (frozenset({f"{SANDBOX_CLAUDE_PROJECTS_DIR}/{REPO_SLUG}/memory"}), False, False),
    ],
)
def test_deleting_the_last_memory_file_propagates_only_against_a_valid_baseline(
    storage: FakeStorage, sandbox_dirs: frozenset[str], baseline_valid: bool, expected_deleted: bool
) -> None:
    storage.objects = {_key(REPO_SLUG, "MEMORY.md"): b"index"}
    sandbox = FakeSandbox(dirs=sandbox_dirs)
    if baseline_valid:
        sandbox.set_baseline({REPO_SLUG: {"MEMORY.md": {"md5": _md5(b"index"), "size": 5, "mtime": 1.0}}})
    else:
        sandbox.files[SANDBOX_BASELINE_PATH] = b"{truncated"

    persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert (_key(REPO_SLUG, "MEMORY.md") not in storage.objects) is expected_deleted


def _fifty_restored_slugs(storage: FakeStorage) -> tuple[FakeSandbox, list[str]]:
    slugs = [f"-s{index:02d}" for index in range(MAX_SLUGS_PER_USER)]
    sandbox = FakeSandbox({_memory_path(slug, "MEMORY.md"): b"index" for slug in slugs})
    sandbox.set_baseline({slug: {"MEMORY.md": {"md5": _md5(b"index"), "size": 5, "mtime": 1.0}} for slug in slugs})
    storage.objects = {_key(slug, "MEMORY.md"): b"index" for slug in slugs}
    return sandbox, slugs


@pytest.mark.parametrize(
    "agent_cleared_the_sandbox, new_slugs",
    [
        (False, ["-a"]),
        (True, ["-a"]),
        # The sandbox listing stops at 51 entries, so a tracked slug still on disk is left out of it.
        (False, ["-a", "-b"]),
    ],
)
def test_a_new_slug_beyond_the_slug_capacity_is_neither_uploaded_nor_treated_as_a_deletion(
    storage: FakeStorage, agent_cleared_the_sandbox: bool, new_slugs: list[str]
) -> None:
    sandbox, slugs = _fifty_restored_slugs(storage)
    if agent_cleared_the_sandbox:
        sandbox = FakeSandbox()
    for slug in new_slugs:
        sandbox.files[_memory_path(slug, "MEMORY.md")] = b"new checkout"
        sandbox.mtimes[_memory_path(slug, "MEMORY.md")] = 1.0

    counts = persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert storage.writes == []
    assert set(storage.objects) == {_key(slug, "MEMORY.md") for slug in slugs}
    assert counts.skipped["slug_limit"] >= 1
    expected_baseline = set() if agent_cleared_the_sandbox else set(slugs)
    assert set(parse_baseline(sandbox.files.get(SANDBOX_BASELINE_PATH))) == expected_baseline


def test_replacing_one_of_fifty_slugs_keeps_a_valid_baseline(storage: FakeStorage) -> None:
    sandbox, slugs = _fifty_restored_slugs(storage)
    del sandbox.files[_memory_path(slugs[0], "MEMORY.md")]
    sandbox.files[_memory_path("-a", "MEMORY.md")] = b"new checkout"
    sandbox.mtimes[_memory_path("-a", "MEMORY.md")] = 1.0

    persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert _key(slugs[0], "MEMORY.md") not in storage.objects
    assert _key("-a", "MEMORY.md") not in storage.objects

    # The slot the deletion freed is counted from storage on the next persist.
    persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert storage.objects[_key("-a", "MEMORY.md")] == b"new checkout"
    assert len(parse_baseline(sandbox.files[SANDBOX_BASELINE_PATH])) == MAX_SLUGS_PER_USER

    storage.writes.clear()
    sandbox.reads.clear()
    persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert storage.writes == []
    assert sandbox.reads == [SANDBOX_BASELINE_PATH]


@pytest.mark.parametrize(
    "stored_files, sandbox_files, tracked",
    [
        ([f"stored-{index}.md" for index in range(150)], [f"new-{index}.md" for index in range(100)], []),
        # The sandbox listing stops at 201 entries and leaves out the tracked zz.md.
        (["zz.md"], [*(f"new-{index}.md" for index in range(201)), "zz.md"], ["zz.md"]),
    ],
)
def test_a_slug_cannot_grow_past_the_file_cap_by_dropping_the_baseline(
    storage: FakeStorage, stored_files: list[str], sandbox_files: list[str], tracked: list[str]
) -> None:
    storage.objects = {_key(REPO_SLUG, name): b"note" for name in stored_files}
    sandbox = FakeSandbox({_memory_path(REPO_SLUG, name): b"note" for name in sandbox_files})
    sandbox.set_baseline({REPO_SLUG: {name: {"md5": _md5(b"note"), "size": 4, "mtime": 1.0} for name in tracked}})
    stored_before = dict(storage.objects)

    counts = persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert storage.writes == []
    assert storage.objects == stored_before
    assert counts.skipped["slug_file_limit"] == 1


def test_a_retry_after_a_failed_upload_does_not_resend_the_files_already_saved(storage: FakeStorage) -> None:
    sandbox = FakeSandbox({_memory_path(REPO_SLUG, "a.md"): b"a v1", _memory_path(REPO_SLUG, "b.md"): b"b v1"})
    sandbox.set_baseline({})
    storage.failing_writes.add(_key(REPO_SLUG, "b.md"))

    with pytest.raises(ObjectStorageError):
        persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert storage.writes == [_key(REPO_SLUG, "a.md")]
    assert set(parse_baseline(sandbox.files[SANDBOX_BASELINE_PATH])[REPO_SLUG]) == {"a.md"}
    storage.objects[_key(REPO_SLUG, "a.md")] = b"a v2, saved by another sandbox meanwhile"
    storage.failing_writes.clear()

    persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert storage.writes == [_key(REPO_SLUG, "a.md"), _key(REPO_SLUG, "b.md")]
    assert storage.objects[_key(REPO_SLUG, "a.md")] == b"a v2, saved by another sandbox meanwhile"


def test_files_that_grow_after_the_listing_cannot_exceed_the_slug_byte_budget(storage: FakeStorage) -> None:
    names = [f"n{i}.md" for i in range(10)]
    sandbox = FakeSandbox({_memory_path(REPO_SLUG, name): b"" for name in names})
    sandbox.set_baseline({})
    sandbox.grown_on_read = b"x" * MAX_FILE_BYTES

    counts = persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert counts.skipped == {"slug_too_large": 1}
    assert storage.writes == []


def test_a_refused_baseline_checkpoint_fails_the_persist(storage: FakeStorage) -> None:
    sandbox = FakeSandbox({_memory_path(REPO_SLUG, "MEMORY.md"): b"new note"})
    sandbox.failing_writes.add(SANDBOX_BASELINE_PATH)

    with pytest.raises(BaselineCheckpointError):
        persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]


def test_a_partial_restore_does_not_later_overwrite_newer_stored_memory(storage: FakeStorage) -> None:
    storage.objects = {_key(REPO_SLUG, "MEMORY.md"): b"index", _key(REPO_SLUG, "topic.md"): b"topic"}
    sandbox = FakeSandbox()
    sandbox.failing_writes.add(_memory_path(REPO_SLUG, "topic.md"))

    result = restore_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]
    storage.objects[_key(REPO_SLUG, "MEMORY.md")] = b"newer, saved by another sandbox"
    storage.writes.clear()
    persist_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert result.complete is False
    assert storage.writes == []
    assert storage.objects[_key(REPO_SLUG, "MEMORY.md")] == b"newer, saved by another sandbox"


def test_a_restore_cut_by_the_deadline_tracks_the_files_it_wrote(storage: FakeStorage) -> None:
    storage.objects = {_key(REPO_SLUG, f"topic-{index}.md"): b"note" for index in range(3)}
    sandbox = FakeSandbox()

    with patch.object(agent_memory, "time", SimpleNamespace(monotonic=lambda: sandbox.memory_writes * 10.0)):
        result = restore_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID, deadline=5.0)  # type: ignore[arg-type]

    assert result.complete is False
    assert list(sandbox.memory()) == [_memory_path(REPO_SLUG, "topic-0.md")]
    assert set(parse_baseline(sandbox.files[SANDBOX_BASELINE_PATH])[REPO_SLUG]) == {"topic-0.md"}


def test_restore_replaces_stored_slugs_for_this_project_only(storage: FakeStorage) -> None:
    storage.objects = {
        _key(REPO_SLUG, "MEMORY.md"): b"stored index",
        _key(REPO_SLUG, "topic.md"): b"stored topic",
        memory_object_key(TEAM_ID + 1, USER_ID, REPO_SLUG, "other-project.md"): b"another project",
        f"tasks/agent-memory/{TEAM_ID}/{USER_ID}/claude/{REPO_SLUG}/nested/evil.md": b"nested",
        f"tasks/agent-memory/{TEAM_ID}/{USER_ID}/claude/-..x/escape.md": b"escape",
    }
    untouched = _memory_path(WORKSPACE_SLUG, "keep.md")
    sandbox = FakeSandbox(
        {
            _memory_path(REPO_SLUG, "MEMORY.md"): b"old index",
            _memory_path(REPO_SLUG, "stale.md"): b"not in storage",
            untouched: b"slug storage does not have",
        }
    )

    result = restore_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert sandbox.memory() == {
        _memory_path(REPO_SLUG, "MEMORY.md"): b"stored index",
        _memory_path(REPO_SLUG, "topic.md"): b"stored topic",
        untouched: b"slug storage does not have",
    }
    assert result.complete is True
    assert result.counts.skipped == {"invalid_key": 2}
    assert set(json.loads(sandbox.files[SANDBOX_BASELINE_PATH])) == {REPO_SLUG}


def test_restore_into_a_memory_directory_over_the_file_cap_deletes_nothing(storage: FakeStorage) -> None:
    storage.objects = {_key(REPO_SLUG, "MEMORY.md"): b"stored index"}
    stale = {_memory_path(REPO_SLUG, f"stale-{index}.md"): b"note" for index in range(201)}
    sandbox = FakeSandbox(stale)

    result = restore_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert result.complete is False
    assert result.counts.errors == 1
    assert stale.items() <= sandbox.memory().items()


@pytest.mark.parametrize(
    "stored, sandbox_files, expected_complete",
    [
        ({}, {}, True),
        (
            {memory_object_key(TEAM_ID, USER_ID, REPO_SLUG, "MEMORY.md"): b"stored index"},
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

    result = restore_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert result.complete is expected_complete
    assert sandbox.memory() == {}


def test_restore_lists_a_bounded_number_of_keys(storage: FakeStorage) -> None:
    storage.objects = {_key(REPO_SLUG, f"topic-{index}.md"): b"note" for index in range(MAX_STORED_KEYS + 1)}
    sandbox = FakeSandbox()

    result = restore_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert result.complete is False
    assert result.counts.skipped["listing_truncated"] == 1
    assert sandbox.memory() == {}


def test_restore_raises_and_leaves_no_baseline_when_storage_cannot_be_listed(storage: FakeStorage) -> None:
    storage.list_fails = True
    sandbox = FakeSandbox()

    with pytest.raises(ObjectStorageError):
        restore_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert SANDBOX_BASELINE_PATH not in sandbox.files


def test_restore_keeps_a_snapshot_that_carries_its_own_baseline(storage: FakeStorage) -> None:
    storage.objects = {
        _key(REPO_SLUG, "MEMORY.md"): b"older stored index",
        _key(REPO_SLUG, "deleted-locally.md"): b"removed in the snapshot",
    }
    sandbox = FakeSandbox({_memory_path(REPO_SLUG, "MEMORY.md"): b"unsaved local edit"})
    sandbox.set_baseline({REPO_SLUG: {"MEMORY.md": {"md5": _md5(b"index"), "size": 5, "mtime": 0.5}}})
    before = dict(sandbox.files)

    result = restore_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID)  # type: ignore[arg-type]

    assert result.snapshot_baseline_kept is True
    assert sandbox.files == before


def test_restore_stops_inside_a_slug_once_the_deadline_passes(storage: FakeStorage) -> None:
    storage.objects = {_key(REPO_SLUG, f"topic-{index}.md"): b"note" for index in range(3)}
    sandbox = FakeSandbox()

    with patch.object(agent_memory, "time", SimpleNamespace(monotonic=lambda: storage.clock)):
        result = restore_sandbox_memory(sandbox, team_id=TEAM_ID, user_id=USER_ID, deadline=15.0)  # type: ignore[arg-type]

    assert result.complete is False
    assert result.counts.skipped["deadline"] == 1
    assert sandbox.memory() == {}
