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
"""

from __future__ import annotations

import os
import sys
import json
import tempfile
import subprocess
from collections.abc import Mapping
from pathlib import Path

from posthog.dataclasses import frozen

# This file is products/stamphog/backend/logic/engine_pregate.py. The engine is a data directory of
# the product. owners_yaml is a distribution the production venv installs, so it lives under the repo
# root's packages/ rather than beside the engine.
ENGINE_DIR = Path(__file__).resolve().parents[2] / "packages" / "pr-approval-agent"
OWNERS_PACKAGE_DIR = Path(__file__).resolve().parents[4] / "packages" / "owners-yaml" / "owners_yaml"

# The same layout the sandbox checkout uses (STAMPHOG_SANDBOX_ENGINE_DIR, STAMPHOG_SANDBOX_OWNERS_DIR),
# so the engine's repo-root walk and its owners-package lookup behave the same way in both places.
_ENGINE_SUBDIR = Path("tools") / "pr-approval-agent"
_OWNERS_SUBDIR = Path("tools") / "owners" / "owners_yaml"

# A gate-only run imports the engine and evaluates a few regexes. A run that takes longer than this
# is broken, and the caller then falls through to the sandbox review.
PREGATE_TIMEOUT_SECONDS = 30


class EnginePregateError(RuntimeError):
    """The pre-check produced no usable answer. The caller falls through to the full review."""


@frozen
class PregateOutcome:
    # True only when the full sandbox review would also end REFUSED.
    final_deny: bool
    # True when an LLM summary would improve the refusal text. The bot-author refusal has its own.
    needs_summary: bool
    # The engine's reviewer model, so the summary call uses the model the gateway token allows.
    summary_model: str
    # The engine's to_dict() contract, the same shape the sandbox review prints. None when not final.
    result: dict | None


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


def engine_source_files() -> dict[str, str]:
    """The engine's Python modules by file name, without its tests."""
    if not ENGINE_DIR.is_dir():
        raise RuntimeError(f"engine source dir not found: {ENGINE_DIR}")
    return {
        path.name: path.read_text() for path in sorted(ENGINE_DIR.glob("*.py")) if not path.name.startswith("test_")
    }


def owners_package_files() -> dict[str, str]:
    """The owners-yaml resolver modules by file name, which the engine's ownership format imports."""
    if not OWNERS_PACKAGE_DIR.is_dir():
        raise RuntimeError(f"owners package source dir not found: {OWNERS_PACKAGE_DIR}")
    return {path.name: path.read_text() for path in sorted(OWNERS_PACKAGE_DIR.glob("*.py"))}


def _write_tree(root: Path, policy_files: Mapping[str, str]) -> None:
    for relative_path, content in policy_files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    for subdir, files in ((_ENGINE_SUBDIR, engine_source_files()), (_OWNERS_SUBDIR, owners_package_files())):
        (root / subdir).mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (root / subdir / name).write_text(content)


# What the interpreter itself needs to start, and nothing the engine could read as input. A Python
# built with a shared libpython (setup-python, some base images) exits 127 without LD_LIBRARY_PATH.
_INHERITED_ENVIRONMENT = ("PATH", "LD_LIBRARY_PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")


def _child_environment(root: Path, extra: Mapping[str, str]) -> dict[str, str]:
    return {
        **{name: os.environ[name] for name in _INHERITED_ENVIRONMENT if name in os.environ},
        # The engine asks git for the policy commit when it renders the review body. The tree is not a
        # repository, and this stops git from walking up into one that encloses the temp dir.
        "GIT_CEILING_DIRECTORIES": str(root.parent),
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
        final_deny=parsed.get("final_deny") is True and isinstance(result, dict),
        needs_summary=parsed.get("needs_summary") is True,
        summary_model=str(parsed.get("summary_model") or ""),
        result=result if isinstance(result, dict) else None,
    )


def run_engine_pregate(
    context: Mapping[str, object], policy_files: Mapping[str, str], *, environment: Mapping[str, str]
) -> PregateOutcome:
    """Run ``review_local.py --pregate`` on ``context`` under ``policy_files`` and parse its answer.

    ``policy_files`` maps repo-relative paths to the effective trusted policy, the same set the
    sandbox injects. ``environment`` is added to the child's otherwise empty environment: pass the
    analytics keys only on the run whose result is posted, so the engine emits its
    ``stamphog_review_completed`` event once.
    """
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
                    "--pregate",
                ],
                cwd=root,
                env=_child_environment(root, environment),
                capture_output=True,
                text=True,
                timeout=PREGATE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise EnginePregateError("the engine pre-check timed out") from exc
    if completed.returncode != 0:
        # Only the exit code: stderr can quote the PR title or file names, and callers log this text.
        raise EnginePregateError(f"the engine pre-check exited with code {completed.returncode}")
    return _parse_outcome(completed.stdout)
