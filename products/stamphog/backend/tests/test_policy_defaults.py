import sys
import time
from pathlib import Path

import pytest

import yaml

# The review engine (packages/pr-approval-agent) is a set of plain modules, and not an importable
# package, so its directory must be on sys.path to import its policy loader by bare name. Its own
# tests do the same.
_ENGINE_DIR = Path(__file__).resolve().parents[2] / "packages" / "pr-approval-agent"
sys.path.insert(0, str(_ENGINE_DIR))

import gates  # noqa: E402
import policy  # noqa: E402

from products.stamphog.backend.temporal.activities import (  # noqa: E402
    _blame_paths,
    _clone_pr,
    _effective_policy_files,
    _inject_policy_files,
    _prefetch_review_blobs,
)
from products.stamphog.backend.temporal.constants import (  # noqa: E402
    STAMPHOG_POLICY_ENTRYPOINT,
    STAMPHOG_REVIEW_GUIDANCE_PATH,
    STAMPHOG_STEERING_PATH,
)
from products.stamphog.backend.tests.fakes import FakeExecResult  # noqa: E402

_DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "logic" / "policy_defaults" / "policy.yml"

_SIZE_GATE_ONLY = "size_gate:\n    max_lines: 123\n    max_files: 7\n"


def _load_engine_policy(path: Path) -> policy.Policy:
    # The REAL registries, exactly as review_local.py loads them. Hand-faked stand-ins here once let
    # the engine drop an ownership format on master while this suite stayed green — every hosted
    # zero-config review then crashed at policy load.
    return policy.load_policy(
        path,
        lockfile_names=gates._ALL_LOCKFILE_NAMES,
        ownership_formats=gates.OWNERSHIP_FORMAT_LOCATORS,
    )


def test_shipped_default_policy_loads_through_engine_loader() -> None:
    # The hosted default policy.yml must satisfy the engine's own loader (all required sections,
    # self-governance deny, valid regexes) — otherwise every zero-config repo crashes at review time.
    loaded = _load_engine_policy(_DEFAULT_POLICY)
    assert loaded.version == 1


def test_overlay_absent_repo_policy_keeps_default_text_verbatim() -> None:
    effective = _effective_policy_files("acme/widgets", {})
    assert effective[STAMPHOG_POLICY_ENTRYPOINT] == _DEFAULT_POLICY.read_text()
    assert STAMPHOG_STEERING_PATH not in effective


def test_overlay_partial_repo_policy_replaces_only_declared_sections() -> None:
    effective = _effective_policy_files("acme/widgets", {STAMPHOG_POLICY_ENTRYPOINT: _SIZE_GATE_ONLY})
    merged = yaml.safe_load(effective[STAMPHOG_POLICY_ENTRYPOINT])
    default = yaml.safe_load(_DEFAULT_POLICY.read_text())
    assert merged["size_gate"] == {"max_lines": 123, "max_files": 7}
    assert merged["deny"] == default["deny"]
    assert merged["familiarity"] == default["familiarity"]


def test_overlay_full_schema_repo_policy_is_itself() -> None:
    full = _DEFAULT_POLICY.read_text()
    effective = _effective_policy_files("acme/widgets", {STAMPHOG_POLICY_ENTRYPOINT: full})
    assert yaml.safe_load(effective[STAMPHOG_POLICY_ENTRYPOINT]) == yaml.safe_load(full)


@pytest.mark.parametrize(
    "repo_policy",
    [
        pytest.param("size_gate: [unclosed", id="malformed_yaml"),
        pytest.param("- just\n- a\n- list\n", id="non_mapping_root"),
    ],
)
def test_overlay_unusable_repo_policy_fails_closed(repo_policy: str) -> None:
    # A repo that declared *something* must not silently review under pure defaults.
    with pytest.raises(RuntimeError):
        _effective_policy_files("acme/widgets", {STAMPHOG_POLICY_ENTRYPOINT: repo_policy})


def test_overlay_of_partial_repo_policy_validates_through_engine_loader(tmp_path: Path) -> None:
    # Partial repo files must never yield an invalid effective policy: the merged doc has to satisfy
    # the engine's strict loader (required sections, self-governance) exactly like a hand-written one.
    effective = _effective_policy_files("acme/widgets", {STAMPHOG_POLICY_ENTRYPOINT: _SIZE_GATE_ONLY})
    merged_path = tmp_path / "policy.yml"
    merged_path.write_text(effective[STAMPHOG_POLICY_ENTRYPOINT])
    loaded = _load_engine_policy(merged_path)
    assert loaded.size_gate.max_lines == 123
    assert loaded.size_gate.max_files == 7


def test_repo_guidance_and_steering_pass_through() -> None:
    files = {
        STAMPHOG_REVIEW_GUIDANCE_PATH: "repo norms\n",
        STAMPHOG_STEERING_PATH: "steer this way\n",
    }
    effective = _effective_policy_files("acme/widgets", files)
    assert effective[STAMPHOG_REVIEW_GUIDANCE_PATH] == "repo norms\n"
    assert effective[STAMPHOG_STEERING_PATH] == "steer this way\n"


def test_inject_policy_files_wipes_optional_paths_from_pr_head() -> None:
    # steering.md is injected only when the repo's default branch has it — so the wipe must cover it
    # regardless, or a PR head could plant a steering.md the reviewer would trust as maintainer prose.
    executed: list[str] = []

    class _RecordingSandbox:
        def execute(self, command: str, timeout_seconds: int | None = None) -> None:
            executed.append(command)

        def write_file(self, path: str, payload: bytes) -> None:
            return None

    _inject_policy_files(_RecordingSandbox(), {})  # type: ignore[arg-type]

    wipes = [cmd for cmd in executed if cmd.startswith("rm -f")]
    assert any(".stamphog/steering.md" in cmd for cmd in wipes)
    assert any(".stamphog/policy.yml" in cmd for cmd in wipes)


def test_clone_is_blobless_and_blame_blobs_are_prefetched_in_one_fetch() -> None:
    executed: list[str] = []

    class _RecordingSandbox:
        def execute(self, command: str, timeout_seconds: int | None = None) -> FakeExecResult:
            executed.append(command)
            return FakeExecResult(stdout="", stderr="", exit_code=0)

    deadline = time.monotonic() + 600
    sandbox = _RecordingSandbox()
    _clone_pr(sandbox, "acme/widgets", "basesha", "headsha", 7, "tok", deadline)  # type: ignore[arg-type]
    _prefetch_review_blobs(sandbox, "basesha", "headsha", "tok", ["src/old_name.py"], deadline)  # type: ignore[arg-type]

    clone = next(cmd for cmd in executed if " clone " in cmd)
    assert "--filter=blob:none" in clone
    assert "--depth" not in clone

    # The checkout materializes the head tree, so its promisor fetch needs the credential that
    # every other GitHub-facing command in the clone carries.
    checkout = next(cmd for cmd in executed if " checkout " in cmd)
    assert "http.extraheader" in checkout.split(" checkout ")[0]

    prefetch = next(cmd for cmd in executed if "rev-list" in cmd)
    assert "--missing=print" in prefetch
    assert "src/old_name.py" in prefetch
    # One fetch for the whole set, driven by the enumerated object ids.
    assert "fetch origin" in prefetch and "--stdin" in prefetch
    # The enumeration must not fetch the objects it is reporting as missing.
    assert "GIT_NO_LAZY_FETCH=1" in prefetch
    # The diff reads the old side of every changed file, so the diff set comes from git rather
    # than the API file list, which pages out on a large PR.
    assert "diff --raw --no-renames" in prefetch
    # A submodule's commit belongs to another repository; batching it makes origin reject the lot.
    assert "grep -v '^:160000'" in prefetch


def test_blame_paths_uses_the_base_side_path_and_skips_binaries() -> None:
    files = [
        {"filename": "src/new_name.py", "previous_filename": "src/old_name.py", "patch": "@@", "changes": 4},
        {"filename": "src/plain.py", "patch": "@@", "changes": 2},
        # GitHub reports a binary as zero added and zero deleted, and renders no patch for it.
        {"filename": "static/logo.png", "additions": 0, "deletions": 0, "changes": 0},
    ]
    assert _blame_paths(files) == ["src/old_name.py", "src/plain.py"]

    # The engine blames the largest files, so the bounded list has to be ordered the same way: a
    # large file late in the API order must not be blamed with nothing prefetched for it.
    ordered = _blame_paths(
        [
            {"filename": "src/small.py", "patch": "@@", "changes": 3},
            {"filename": "src/large.py", "patch": "@@", "changes": 900},
        ]
    )
    assert ordered == ["src/large.py", "src/small.py"]

    # GitHub omits the patch of a large text file too, but reports its real line counts. The engine
    # parses the local diff and blames it, so it has to be prefetched.
    assert _blame_paths([{"filename": "src/huge.py", "changes": 1800}]) == ["src/huge.py"]
