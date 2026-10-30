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

from products.stamphog.backend.logic.engine_pregate import run_engine_pregate  # noqa: E402
from products.stamphog.backend.temporal import activities  # noqa: E402
from products.stamphog.backend.temporal.activities import (  # noqa: E402
    PullRequestHeadMovedError,
    _clone_pr,
    _effective_policy_files,
    _prefetch_review_blobs,
    _review_payload_archive,
    _review_payload_command,
)
from products.stamphog.backend.temporal.constants import (  # noqa: E402
    STAMPHOG_POLICY_ENTRYPOINT,
    STAMPHOG_REVIEW_GUIDANCE_PATH,
    STAMPHOG_STEERING_PATH,
)
from products.stamphog.backend.tests.fakes import FakeExecResult  # noqa: E402

_DEFAULT_POLICY = _ENGINE_DIR / "defaults" / "policy.yml"

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


def test_repo_files_pass_through_unmerged() -> None:
    assert _effective_policy_files("acme/widgets", {}) == {}
    effective = _effective_policy_files("acme/widgets", {STAMPHOG_POLICY_ENTRYPOINT: _SIZE_GATE_ONLY})
    assert effective == {STAMPHOG_POLICY_ENTRYPOINT: _SIZE_GATE_ONLY}


@pytest.mark.parametrize(
    "repo_policy",
    [
        pytest.param("size_gate: [unclosed", id="malformed_yaml"),
        pytest.param("- just\n- a\n- list\n", id="non_mapping_root"),
        pytest.param("", id="empty_file"),
    ],
)
def test_overlay_unusable_repo_policy_fails_closed(repo_policy: str) -> None:
    # A repo that declared *something* must not silently review under pure defaults.
    with pytest.raises(RuntimeError):
        _effective_policy_files("acme/widgets", {STAMPHOG_POLICY_ENTRYPOINT: repo_policy})


def _pregate_context(path: str) -> dict:
    return {
        "repo": "example/widgets",
        "pr": {
            "number": 1,
            "title": "chore: update configuration",
            "state": "open",
            "user": {"login": "maintainer", "type": "User"},
        },
        "files": [{"filename": path, "status": "modified", "additions": 1, "deletions": 1, "patch": "+setting"}],
        "folder_policies_known": True,
    }


def test_pregate_reviews_a_repo_with_no_policy_files() -> None:
    outcome = run_engine_pregate(_pregate_context("docs/readme.md"), {}, environment={})
    assert outcome.not_final_reason == "no_failing_gate"


@pytest.mark.parametrize(
    "path, denied_category",
    [
        ("apps/billing/values.yaml", None),
        (".github/workflows/maintenance.yml", None),
        ("apps/billing-ledger/values.yaml", "billing"),
        (".github/workflows/restricted.yml", "new_guard"),
        ("apps/billing/secret.yaml", "crypto_secrets"),
        (".github/CODEOWNERS", "stamphog_policy"),
    ],
)
def test_pregate_merges_the_repo_policy_onto_the_shipped_default(path: str, denied_category: str | None) -> None:
    repo_policy = yaml.safe_dump(
        {
            "deny": {
                "billing": {"match": {"extend_any": ["ledger"]}},
                "new_guard": {"match": {"paths": [r"^\.github/workflows/restricted\.yml$"]}},
            },
            "deny_exceptions": {
                "billing": [
                    {
                        "keyword": "billing",
                        "path_prefixes": ["apps/"],
                        "extensions": [".yaml", ".yml"],
                    }
                ],
                "infra_cicd": [{"path_prefixes": [".github/"]}],
            },
        }
    )
    outcome = run_engine_pregate(_pregate_context(path), {STAMPHOG_POLICY_ENTRYPOINT: repo_policy}, environment={})
    if denied_category is None:
        assert not outcome.final
        assert outcome.not_final_reason == "no_failing_gate"
    else:
        assert outcome.result is not None
        assert outcome.final
        assert outcome.result["final_verdict"] == "REFUSED"
        assert denied_category in outcome.result["classification"]["deny_categories"]


def test_repo_guidance_and_steering_pass_through() -> None:
    files = {
        STAMPHOG_REVIEW_GUIDANCE_PATH: "repo norms\n",
        STAMPHOG_STEERING_PATH: "steer this way\n",
    }
    effective = _effective_policy_files("acme/widgets", files)
    assert effective[STAMPHOG_REVIEW_GUIDANCE_PATH] == "repo norms\n"
    assert effective[STAMPHOG_STEERING_PATH] == "steer this way\n"


def test_review_payload_command_wipes_optional_paths_from_pr_head() -> None:
    # steering.md is injected only when the repo's default branch has it — so the wipe must cover it
    # regardless, or a PR head could plant a steering.md the reviewer would trust as maintainer prose.
    command = _review_payload_command()

    wipe, _, extract = command.partition("tar -xzf")
    assert ".stamphog/steering.md" in wipe
    assert ".stamphog/policy.yml" in wipe
    assert "rm -rf tools/pr-approval-agent tools/owners" in wipe
    assert extract


@pytest.mark.parametrize("tools_is_symlink", [False, True])
def test_review_payload_lands_only_in_a_real_tools_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tools_is_symlink: bool
) -> None:
    checkout = tmp_path / "checkout"
    planted_dir = checkout / "a" / "b" / "c"
    planted_dir.mkdir(parents=True)
    if tools_is_symlink:
        (checkout / "tools").symlink_to("a/b/c")
    payload = tmp_path / "payload.tar.gz"
    payload.write_bytes(_review_payload_archive({}, "{}"))
    monkeypatch.setattr(activities, "STAMPHOG_SANDBOX_REPO_DIR", str(checkout))
    monkeypatch.setattr(activities, "STAMPHOG_SANDBOX_PAYLOAD_PATH", str(payload))

    result = subprocess.run(["bash", "-c", _review_payload_command()], capture_output=True, text=True)

    assert (result.returncode == 0) is not tools_is_symlink
    assert not (planted_dir / "pr-approval-agent").exists()
    assert (checkout / "tools" / "pr-approval-agent" / "review_local.py").is_file() is not tools_is_symlink


def test_clone_and_prefetch_carry_the_credential_on_every_github_fetch() -> None:
    executed: list[str] = []

    class _RecordingSandbox:
        def execute(self, command: str, timeout_seconds: int | None = None) -> FakeExecResult:
            executed.append(command)
            return FakeExecResult(stdout="", stderr="", exit_code=0)

    deadline = time.monotonic() + 600
    sandbox = _RecordingSandbox()
    for step in ("head", "checkout"):
        _clone_pr(sandbox, "acme/widgets", "mergebase", "headsha", 7, "tok", deadline, step=step)  # type: ignore[arg-type]
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
        with pytest.raises(PullRequestHeadMovedError, match="the PR head is now"):
            _clone_pr(sandbox, "acme/widgets", "", base_tip, 7, "tok", deadline, step="head")  # type: ignore[arg-type]
        return

    for step in ("head", "checkout"):
        _clone_pr(sandbox, "acme/widgets", merge_base, head, 7, "tok", deadline, step=step)  # type: ignore[arg-type]
    _prefetch_review_blobs(sandbox, merge_base, "tok", deadline)  # type: ignore[arg-type]

    assert _git(target, "rev-parse", "HEAD") == head
    assert _git(target, "rev-parse", "--is-shallow-repository") == "true"
    no_lazy = {**env, "GIT_NO_LAZY_FETCH": "1"}
    diff = subprocess.run(
        ["git", "diff", "--numstat", f"{merge_base}..{head}"], cwd=target, capture_output=True, text=True, env=no_lazy
    )
    assert diff.returncode == 0, diff.stderr
    assert diff.stdout.splitlines() == ["1\t0\tadded.py", "0\t1\tgone.py", "1\t1\tkept.py"]
