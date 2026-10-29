"""Run the review engine's gate-only pre-check on the worker.

A PR that fails a deterministic gate gets the same refusal whatever the LLM says, so the server
checks the gates before it waits for other reviewer bots or makes a sandbox. It does not mirror the
gate logic. It runs the engine's own ``review_local.py --pregate`` (see ``pregate()`` there), so the
gates, the tier, the finality rules and the rendered review body are the sandbox's own code.

The engine is a directory of plain scripts that import each other by bare name (``policy``,
``gates``, ``github``) and load the trusted policy at import time from the repo root they find above
their own file. Importing them into the worker would put those names on the worker's
``sys.path`` and bind the policy to the worker's own checkout. So each check runs in a child Python
process, inside a temporary tree laid out like the sandbox checkout: the run's trusted policy files
under ``.stamphog/``, the engine under ``tools/pr-approval-agent``, the owners resolver beside it.
The child gets a clean environment with no ``PYTHONPATH``, so the engine resolves its bare imports
from its own directory and never from the worker's modules.

The sandbox checkout also carries the PR head's AGENT_APPROVALS.md files, which can raise or lower a
folder's size ceiling. The server reads every one that governs a changed file from GitHub at the
reviewed head and writes it into the same tree, so the pre-check budgets the size gate like the
sandbox does.
"""

from __future__ import annotations

import os
import sys
import json
import time
import tempfile
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.ownership.github_files import GitHubFilesFetcher, is_absent

from products.stamphog.backend.logic.github_client import StamphogGitHubClient

logger = structlog.get_logger(__name__)

# This file is products/stamphog/backend/logic/engine_pregate.py. The engine is a data directory of
# the product. owners_yaml is a distribution the production venv installs, so it lives under the repo
# root's packages/ rather than beside the engine.
ENGINE_DIR = Path(__file__).resolve().parents[2] / "packages" / "pr-approval-agent"
# The default policy files ship inside the engine directory, so the engine merges a repository's files onto them.
_ENGINE_DEFAULTS_SUBDIR = "defaults"
OWNERS_PACKAGE_DIR = Path(__file__).resolve().parents[4] / "packages" / "owners-yaml" / "owners_yaml"

# The same layout the sandbox checkout uses (STAMPHOG_SANDBOX_ENGINE_DIR, STAMPHOG_SANDBOX_OWNERS_DIR),
# so the engine's repo-root walk and its owners-package lookup behave the same way in both places.
_ENGINE_SUBDIR = Path("tools") / "pr-approval-agent"
_OWNERS_SUBDIR = Path("tools") / "owners" / "owners_yaml"

# Mirrors _FOLDER_POLICY_FILENAME in the engine's policy.py, which the backend cannot import.
FOLDER_POLICY_FILENAME = "AGENT_APPROVALS.md"
_FOLDER_POLICY_BUDGET_SECONDS = 10
# post_verdict reads the manifests before it posts, so the reads share one budget well inside its timeout.
_MANIFEST_BUDGET_SECONDS = 20
# Well past the ancestor directories of any real PR, and small enough to stay one or two probes.
_MAX_FOLDER_POLICY_CANDIDATES = 300
# The files ride in run.output. A real folder file is a few hundred bytes of frontmatter and prose.
_MAX_FOLDER_POLICY_BYTES = 256 * 1024

# A gate-only run imports the engine and evaluates a few regexes. A run that takes longer than this
# is broken, and the caller then falls through to the sandbox review.
PREGATE_TIMEOUT_SECONDS = 30


class EnginePregateError(RuntimeError):
    """The pre-check produced no usable answer. The caller falls through to the full review."""


@frozen
class PregateOutcome:
    # True only when the full sandbox review would end with the same verdict as ``result``.
    final: bool
    # True when an LLM summary would improve the refusal text. The bot-author refusal has its own.
    needs_summary: bool
    # The engine's reviewer model, so the summary call uses the model the gateway token allows.
    summary_model: str
    # The engine's to_dict() contract, the same shape the sandbox review prints. None when not final.
    result: dict | None
    # Why a non-final outcome needs the sandbox, for telemetry. Empty when final.
    not_final_reason: str = ""


@frozen
class GateAttestation:
    # True only when the worker's own gate run allows the sandbox's approval to stand.
    attested: bool
    # The first condition that failed, or empty when attested.
    reason: str
    gates: list[dict]
    # The manifests whose texts the engine needs for the scripts scan, when the reason is
    # ``dependency_manifest``.
    manifests: tuple[str, ...] = ()


def pregate_skip_reason(pr: Mapping[str, object], files: list[dict], head_sha: str) -> str | None:
    """Why the stored context cannot stand in for the sandbox's own file list, or None when it can.

    The sandbox reads the changed files from ``git diff`` at the run's head. The pre-check reads the
    files API, which answers for whatever head is live, stops at a page cap, and reports a rename as
    one new path where git can report the old path too. A final deny is only safe on a file list the
    sandbox would see as the same or larger, because a larger list can only add gate failures.
    """
    head = pr.get("head")
    if not isinstance(head, dict) or head.get("sha") != head_sha:
        return "head_moved"
    changed_files = pr.get("changed_files")
    if not isinstance(changed_files, int) or changed_files != len(files):
        return "file_list_incomplete"
    if any(file.get("status") in ("renamed", "copied") for file in files):
        return "renamed_files"
    return None


def folder_policy_candidates(files: list[dict]) -> list[str] | None:
    """Every AGENT_APPROVALS.md path that could govern a changed file: one per ancestor directory.

    The engine walks the same chain from each changed file's directory up to the repo root. The PR
    controls the paths, so past _MAX_FOLDER_POLICY_CANDIDATES the answer is None rather than a
    truncated list, which the pre-check must never treat as complete.
    """
    directories: set[PurePosixPath] = set()
    for entry in files:
        directories.update(PurePosixPath(entry.get("filename") or "").parents)
        if len(directories) > _MAX_FOLDER_POLICY_CANDIDATES:
            return None
    return sorted((directory / FOLDER_POLICY_FILENAME).as_posix() for directory in directories)


def fetch_folder_policy_files(
    client: StamphogGitHubClient, repo: str, head_sha: str, files: list[dict]
) -> dict[str, str] | None:
    """The PR head's AGENT_APPROVALS.md files that govern ``files``, or None when they are unknown.

    None keeps the pre-check on its conservative size rule, so a failure here only makes a fast path
    less likely. Never raises.

    One batched probe finds which candidates exist. GraphQL shows a symlink as a plain blob of its
    target path, so each file that exists is then read from the contents API, which resolves a link
    to an in-repo file the way the sandbox checkout does. Any other kind of entry means unknown.
    """
    candidates = folder_policy_candidates(files)
    if candidates is None:
        logger.info("stamphog_folder_policy_candidates_capped", repo=repo)
        return None
    deadline = time.monotonic() + _FOLDER_POLICY_BUDGET_SECONDS
    try:
        fetcher = GitHubFilesFetcher.from_token(
            client.installation_token(),
            installation_id=client.installation_id,
            refresh=client.refresh_installation_token,
            priority=Priority.NORMAL,
        )
        exists = fetcher.files_exist(repo, head_sha, candidates, deadline)
        found: dict[str, str] = {}
        for path in sorted(path for path, present in exists.items() if present):
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                logger.info("stamphog_folder_policy_budget_exhausted", repo=repo)
                return None
            entry = client.get_file_at_ref(repo, path, head_sha, timeout=remaining)
            # The probe just saw this path, so a miss here is a disagreement, not an absence.
            if entry is None:
                logger.info("stamphog_folder_policy_vanished", repo=repo)
                return None
            if entry.kind != "file":
                logger.info("stamphog_folder_policy_not_a_file", repo=repo, kind=entry.kind)
                return None
            found[path] = entry.text
            if sum(len(text) for text in found.values()) > _MAX_FOLDER_POLICY_BYTES:
                logger.info("stamphog_folder_policy_bytes_capped", repo=repo)
                return None
        return found
    except Exception:
        logger.warning("stamphog_folder_policy_fetch_failed", repo=repo, exc_info=True)
        return None


def fetch_manifest_contents(
    client: StamphogGitHubClient, repo: str, base_sha: str, head_sha: str, paths: tuple[str, ...]
) -> dict[str, dict[str, str]] | None:
    """Each manifest's text at the merge base and at the head, or None when they are unknown.

    It reads git blobs over GraphQL, one batch per commit, so a symlink reads as its link text, the
    same text `git show` gives the sandbox's scan. The contents API would follow the link instead.
    A path absent at one commit reads as empty, as in that scan. Never raises.
    """
    deadline = time.monotonic() + _MANIFEST_BUDGET_SECONDS
    try:
        fetcher = GitHubFilesFetcher.from_token(
            client.installation_token(),
            installation_id=client.installation_id,
            refresh=client.refresh_installation_token,
            priority=Priority.NORMAL,
        )
        base_texts = fetcher.read_files(repo, base_sha, paths, deadline)
        head_texts = fetcher.read_files(repo, head_sha, paths, deadline)
    except Exception:
        logger.warning("stamphog_manifest_fetch_failed", repo=repo, exc_info=True)
        return None

    def text(value: str) -> str:
        return "" if is_absent(value) else value

    return {
        path: {"base": text(base_texts[path]), "head": text(head_texts[path])}
        for path in paths
        if path in base_texts and path in head_texts
    }


def engine_source_files() -> dict[str, str]:
    """The engine's Python modules and its shipped default policy files, by path under the engine directory."""
    if not ENGINE_DIR.is_dir():
        raise RuntimeError(f"engine source dir not found: {ENGINE_DIR}")
    modules = {
        path.name: path.read_text() for path in sorted(ENGINE_DIR.glob("*.py")) if not path.name.startswith("test_")
    }
    defaults = {
        f"{_ENGINE_DEFAULTS_SUBDIR}/{path.name}": path.read_text()
        for path in sorted((ENGINE_DIR / _ENGINE_DEFAULTS_SUBDIR).iterdir())
        if path.is_file()
    }
    if f"{_ENGINE_DEFAULTS_SUBDIR}/policy.yml" not in defaults:
        raise RuntimeError(f"engine source dir {ENGINE_DIR} is missing its default policy")
    return {**modules, **defaults}


def owners_package_files() -> dict[str, str]:
    """The owners-yaml resolver modules by file name, which the engine's ownership format imports."""
    if not OWNERS_PACKAGE_DIR.is_dir():
        raise RuntimeError(f"owners package source dir not found: {OWNERS_PACKAGE_DIR}")
    return {path.name: path.read_text() for path in sorted(OWNERS_PACKAGE_DIR.glob("*.py"))}


def _write_tree(root: Path, policy_files: Mapping[str, str]) -> None:
    # The engine finds the repo root by its `.stamphog/` directory, and a repository with no policy
    # files of its own writes nothing there.
    (root / ".stamphog").mkdir(parents=True, exist_ok=True)
    for relative_path, content in policy_files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    for subdir, files in ((_ENGINE_SUBDIR, engine_source_files()), (_OWNERS_SUBDIR, owners_package_files())):
        for name, content in files.items():
            target = root / subdir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)


# What the interpreter itself needs to start, and nothing the engine could read as input. A Python
# built with a shared libpython (setup-python, some base images) exits 127 without LD_LIBRARY_PATH.
_INHERITED_ENVIRONMENT = ("PATH", "LD_LIBRARY_PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")


def _child_environment(root: Path, extra: Mapping[str, str]) -> dict[str, str]:
    return {
        **{name: os.environ[name] for name in _INHERITED_ENVIRONMENT if name in os.environ},
        # The engine asks git for the policy commit when it renders the review body. The tree is not a
        # repository, and this stops git from walking up into one that encloses the temp dir.
        "GIT_CEILING_DIRECTORIES": str(root.parent),
        # The tree holds the PR head's folder files, so a `.stamphog/` among them must not become the root.
        "STAMPHOG_REPO_ROOT": str(root),
        **extra,
    }


def _parse_outcome(stdout: str) -> PregateOutcome:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise EnginePregateError("the engine pre-check printed nothing")
    try:
        parsed = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise EnginePregateError("the engine pre-check printed no JSON result") from exc
    if not isinstance(parsed, dict):
        raise EnginePregateError("the engine pre-check result is not an object")
    result = parsed.get("result")
    return PregateOutcome(
        final=parsed.get("final") is True and isinstance(result, dict),
        needs_summary=parsed.get("needs_summary") is True,
        summary_model=str(parsed.get("summary_model") or ""),
        result=result if isinstance(result, dict) else None,
        not_final_reason=str(parsed.get("not_final_reason") or ""),
    )


def _run_engine_gates_only(
    context: Mapping[str, object], policy_files: Mapping[str, str], mode_flag: str, environment: Mapping[str, str]
) -> str:
    with tempfile.TemporaryDirectory(prefix="stamphog-pregate-") as temp_dir:
        root = Path(temp_dir)
        _write_tree(root, policy_files)
        context_path = root / "context.json"
        context_path.write_text(json.dumps(context, ensure_ascii=False))
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(root / _ENGINE_SUBDIR / "review_local.py"),
                    "--context",
                    str(context_path),
                    mode_flag,
                ],
                cwd=root,
                env=_child_environment(root, environment),
                capture_output=True,
                text=True,
                timeout=PREGATE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise EnginePregateError(f"the engine {mode_flag} run timed out") from exc
    if completed.returncode != 0:
        # Only the exit code: stderr can quote the PR title or file names, and callers log this text.
        raise EnginePregateError(f"the engine {mode_flag} run exited with code {completed.returncode}")
    return completed.stdout


def run_engine_pregate(
    context: Mapping[str, object], policy_files: Mapping[str, str], *, environment: Mapping[str, str]
) -> PregateOutcome:
    """Run ``review_local.py --pregate`` on ``context`` under ``policy_files`` and parse its answer.

    ``policy_files`` maps repo-relative paths to the effective trusted policy, the same set the
    sandbox injects, plus any folder files from ``fetch_folder_policy_files``. ``environment`` is added to the child's otherwise empty environment: pass the
    analytics keys only on the run whose result is posted, so the engine emits its
    ``stamphog_review_completed`` event once.
    """
    return _parse_outcome(_run_engine_gates_only(context, policy_files, "--pregate", environment))


def run_engine_attest(context: Mapping[str, object], policy_files: Mapping[str, str]) -> GateAttestation:
    """Run ``review_local.py --attest`` on ``context`` under ``policy_files`` and parse its answer.

    It takes the same inputs as ``run_engine_pregate``. It emits no analytics event.
    """
    stdout = _run_engine_gates_only(context, policy_files, "--attest", {})
    lines = [line for line in stdout.splitlines() if line.strip()]
    try:
        parsed = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError as exc:
        raise EnginePregateError("the engine attestation printed no JSON result") from exc
    if not isinstance(parsed, dict):
        raise EnginePregateError("the engine attestation result is not an object")
    gates = parsed.get("gates")
    manifests = parsed.get("manifests")
    return GateAttestation(
        attested=parsed.get("attested") is True,
        reason=str(parsed.get("reason") or ""),
        gates=[gate for gate in gates if isinstance(gate, dict)] if isinstance(gates, list) else [],
        manifests=tuple(str(path) for path in manifests) if isinstance(manifests, list) else (),
    )
