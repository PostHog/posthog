import os
import sys
import time
import subprocess
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

from products.stamphog.backend.temporal import activities  # noqa: E402
from products.stamphog.backend.temporal.activities import (  # noqa: E402
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


def test_clone_and_prefetch_carry_the_credential_on_every_github_fetch() -> None:
    executed: list[str] = []

    class _RecordingSandbox:
        def execute(self, command: str, timeout_seconds: int | None = None) -> FakeExecResult:
            executed.append(command)
            return FakeExecResult(stdout="", stderr="", exit_code=0)

    deadline = time.monotonic() + 600
    sandbox = _RecordingSandbox()
    _clone_pr(sandbox, "acme/widgets", "mergebase", "headsha", 7, "tok", deadline)  # type: ignore[arg-type]
    _prefetch_review_blobs(sandbox, "mergebase", "tok", deadline)  # type: ignore[arg-type]

    # A fetch without the header is anonymous, which a private repository refuses. The token rides
    # in the header only, so the remote URL git writes to .git/config stays clean.
    fetches = [part for command in executed for part in command.split(" && ") if " fetch " in part]
    assert len(fetches) == 3
    assert all("git -c http.extraheader=" in fetch.split(" fetch ")[0] for fetch in fetches)
    assert "remote add origin https://github.com/acme/widgets.git" in executed[0]

    prefetch = executed[-1]
    # The enumeration must not fetch the objects it is reporting as missing.
    assert "GIT_NO_LAZY_FETCH=1" in prefetch
    # The diff reads the old side of every changed file, so the diff set comes from git rather
    # than the API file list, which pages out on a large PR.
    assert "diff --raw --no-renames" in prefetch
    # A submodule's commit belongs to another repository; batching it makes origin reject the lot.
    assert "grep -v '^:160000'" in prefetch


class _LocalGitSandbox:
    def __init__(self, env: dict[str, str]) -> None:
        self.env = env

    def execute(self, command: str, timeout_seconds: int | None = None) -> FakeExecResult:
        result = subprocess.run(["bash", "-c", command], capture_output=True, text=True, env=self.env, timeout=60)
        return FakeExecResult(stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.mark.parametrize("head_moved", [False, True])
def test_shallow_clone_holds_every_object_the_pr_diff_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, head_moved: bool
) -> None:
    # A local origin stands in for GitHub. The engine's git runs without the credential, so the
    # diff below runs with lazy fetches off: anything the clone and prefetch missed fails it here,
    # as it would on a private repository.
    origin = tmp_path / "origin"
    _git(tmp_path, "init", "--quiet", "-b", "main", str(origin))
    for key, value in [
        ("user.name", "t"),
        ("user.email", "t@example.com"),
        ("uploadpack.allowFilter", "true"),
        ("uploadpack.allowAnySHA1InWant", "true"),
    ]:
        _git(origin, "config", key, value)
    (origin / "kept.py").write_text("old\n")
    (origin / "gone.py").write_text("bye\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "--quiet", "-m", "root")
    merge_base = _git(origin, "rev-parse", "HEAD")
    _git(origin, "checkout", "--quiet", "-b", "feature")
    (origin / "kept.py").write_text("new\n")
    (origin / "gone.py").unlink()
    (origin / "added.py").write_text("hi\n")
    _git(origin, "add", "--all")
    _git(origin, "commit", "--quiet", "-m", "feature")
    head = _git(origin, "rev-parse", "HEAD")
    _git(origin, "update-ref", "refs/pull/7/head", head)
    _git(origin, "checkout", "--quiet", "main")
    (origin / "base_only.py").write_text("drift\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "--quiet", "-m", "base drift")
    base_tip = _git(origin, "rev-parse", "HEAD")

    target = tmp_path / "target"
    monkeypatch.setattr(activities, "STAMPHOG_SANDBOX_REPO_DIR", str(target))
    env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.file://{origin}.insteadOf",
        "GIT_CONFIG_VALUE_0": "https://github.com/acme/widgets.git",
    }
    sandbox = _LocalGitSandbox(env)
    deadline = time.monotonic() + 600

    if head_moved:
        # The pull ref now names a newer commit than the one this run was queued for.
        with pytest.raises(RuntimeError, match="the PR head is now"):
            _clone_pr(sandbox, "acme/widgets", merge_base, base_tip, 7, "tok", deadline)  # type: ignore[arg-type]
        return

    _clone_pr(sandbox, "acme/widgets", merge_base, head, 7, "tok", deadline)  # type: ignore[arg-type]
    _prefetch_review_blobs(sandbox, merge_base, "tok", deadline)  # type: ignore[arg-type]

    assert _git(target, "rev-parse", "HEAD") == head
    assert _git(target, "rev-parse", "--is-shallow-repository") == "true"
    no_lazy = {**env, "GIT_NO_LAZY_FETCH": "1"}
    diff = subprocess.run(
        ["git", "diff", "--numstat", f"{merge_base}..{head}"], cwd=target, capture_output=True, text=True, env=no_lazy
    )
    assert diff.returncode == 0, diff.stderr
    assert diff.stdout.splitlines() == ["1\t0\tadded.py", "0\t1\tgone.py", "1\t1\tkept.py"]
