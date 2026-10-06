"""``ci:preflight`` checks that read the diff itself instead of running one command over it."""

from __future__ import annotations

import os
import re
import json
import time
import shutil
import tempfile
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from hogli.manifest import REPO_ROOT
from hogli.telemetry import is_ci

from hogli_commands.change_detection import matches_globs
from hogli_commands.size_lint import _rename_map

Status = Literal["pass", "fail", "warning", "advisory", "skipped"]
Outcome = tuple[Status, str]


@dataclass(frozen=True, kw_only=True, slots=True)
class Scope:
    """What a push carries.

    ``files`` are the changed paths that match the check's triggers and ``changed`` is the
    whole diff. ``committed_only`` says to read the HEAD copy of a file instead of the working tree.
    """

    files: list[str]
    changed: list[str]
    merge_base: str
    committed_only: bool


def _git(*args: str, timeout: float = 20.0) -> bytes | None:
    try:
        result = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _head_copy(path: str, committed_only: bool, *, timeout: float = 20.0) -> bytes | None:
    if committed_only:
        return _git("show", f"HEAD:{path}", timeout=timeout)
    target = REPO_ROOT / path
    return target.read_bytes() if target.is_file() else None


def _renamed_from(scope: Scope, *, timeout: float | None = None) -> dict[str, str]:
    """New path to old path, for every file the branch renamed."""
    return _rename_map(scope.merge_base, *(["HEAD"] if scope.committed_only else []), timeout=timeout)


SNAPSHOT_MANIFEST = "frontend/snapshots.yml"
STORY_FILES = ["*.stories.*"]
# The Storybook config decides which story files load, so a change there can remove any story.
STORYBOOK_CONFIG = [".storybook/*", "common/storybook/*"]
_STORY_TITLE = re.compile(rb"""^\s*title:\s*(['"`])(.+?)\1""", re.MULTILINE)


def _snapshot_identifiers(manifest: bytes) -> set[str]:
    return set(yaml.load(manifest, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))["snapshots"])


def _story_id_prefixes(scope: Scope) -> set[str] | None:
    """Identifier prefixes of the stories this diff changed. None when one cannot be named.

    Storybook builds an identifier as the story file's title, lowercased with every run of
    other characters turned into a dash, then ``--`` and the export name. A story file
    without a literal title takes its identifier from its path, which is not derived here.
    """
    renames = _renamed_from(scope)
    prefixes: set[str] = set()
    for path in scope.changed:
        if not matches_globs(path, STORY_FILES):
            continue
        copies = (_git("show", f"{scope.merge_base}:{renames.get(path, path)}"), _head_copy(path, scope.committed_only))
        for content in copies:
            if content is None:
                continue
            title = _STORY_TITLE.search(content)
            if title is None:
                return None
            prefixes.add(re.sub(r"[^a-z0-9]+", "-", title.group(2).decode(errors="replace").lower()).strip("-"))
    return prefixes


def check_snapshot_baselines(scope: Scope) -> Outcome:
    before = _git("show", f"{scope.merge_base}:{SNAPSHOT_MANIFEST}")
    after = _head_copy(SNAPSHOT_MANIFEST, scope.committed_only)
    if before is None or after is None:
        return "skipped", f"could not read {SNAPSHOT_MANIFEST} on both sides"
    removed = sorted(_snapshot_identifiers(before) - _snapshot_identifiers(after))
    if not removed:
        return "pass", "no baseline entries removed"
    if any(matches_globs(path, STORYBOOK_CONFIG) for path in scope.changed):
        return "pass", "the Storybook config changed in this diff, so removed entries are expected"
    prefixes = _story_id_prefixes(scope)
    if prefixes is None:
        return "pass", "a story without a literal title changed, so removed entries cannot be attributed"
    removed = [entry for entry in removed if not any(entry.startswith(f"{prefix}--") for prefix in prefixes)]
    if not removed:
        return "pass", "every removed baseline entry belongs to a story this diff changed"
    # An advisory and not a failure, because a branch can remove the entries of a story that
    # an earlier PR deleted, and nothing here can tell that apart from a bad conflict resolution.
    return (
        "advisory",
        f"{len(removed)} baseline {'entry' if len(removed) == 1 else 'entries'} removed "
        f"for stories this diff did not change (e.g. {removed[0]}). "
        "If the stories still render, the merge queue fails the batch that carries this file. "
        f"Compare with `git diff {scope.merge_base[:12]} -- {SNAPSHOT_MANIFEST}` "
        "and restore the entries you did not mean to remove",
    )


SEMGREP_RULES = ".semgrep/rules/devex"
# The `SEMGREP_IMAGE` value in this workflow is the one semgrep version pin in the repository.
SEMGREP_WORKFLOW = ".github/workflows/ci-security.yaml"
# The directories the `semgrep-devex` CI job scans.
SEMGREP_SCOPE = [
    f"{root}/*"
    for root in (
        "bin",
        "common",
        "docs/onboarding",
        "ee",
        "frontend",
        "packages",
        "posthog",
        "products",
        "services",
        "tools",
    )
]
# CI excludes this tree from its blocking pass over ERROR rules, and from no other pass.
SEMGREP_ERROR_EXCLUDED = ["products/desktop/*"]
_SEMGREP_TIMEOUT_SECONDS = 15
_SEMGREP_DOWNLOAD_RETRY_SECONDS = 600

# The rule, the file, and the source text the rule matched.
Finding = tuple[str, str, str]


def _semgrep_spec() -> str | None:
    """The semgrep version CI pins, as a requirement. None when the workflow pins none."""
    try:
        workflow = (REPO_ROOT / SEMGREP_WORKFLOW).read_text()
    except OSError:
        return None
    pin = re.search(r"^\s*SEMGREP_IMAGE:\s*semgrep/semgrep:(\d+\.\d+\.\d+)@", workflow, re.MULTILINE)
    return f"semgrep=={pin.group(1)}" if pin else None


def _semgrep_command(*, offline: bool = True) -> list[str] | None:
    """The command that runs the semgrep version CI pins. None when it cannot be built.

    uv runs that version from its cache, in an environment of its own, so the scan does not
    depend on a semgrep the developer installed. Only preparation downloads the package.
    """
    spec = _semgrep_spec()
    if spec is None or shutil.which("uv") is None:
        return None
    return ["uv", "tool", "run", *(["--offline"] if offline else []), "--from", spec, "semgrep"]


class SemgrepUnavailable(RuntimeError):
    pass


class SemgrepExited(SemgrepUnavailable):
    """The command exited non-zero, which is how a tool missing from the offline cache shows."""


def _semgrep_remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SemgrepUnavailable(
            f"semgrep exceeded the {_SEMGREP_TIMEOUT_SECONDS}s check budget; CI will run the check"
        )
    return remaining


def _run_semgrep(command: list[str], *, cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as state:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env={
                    **os.environ,
                    "UV_TOOL_DIR": str(REPO_ROOT / ".flox/cache/uv-tools"),
                    "SEMGREP_LOG_FILE": str(Path(state) / "semgrep.log"),
                    "SEMGREP_SETTINGS_FILE": str(Path(state) / "settings.yml"),
                    "SEMGREP_ENABLE_VERSION_CHECK": "false",
                },
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise SemgrepUnavailable("semgrep timed out; CI will run the check") from error
        except OSError as error:
            raise SemgrepUnavailable(f"semgrep could not start: {error}") from error
    if result.returncode != 0:
        lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
        raise SemgrepExited(" · ".join(lines[-2:])[:240].rstrip(".") or f"exit {result.returncode}")
    return result


def _download_missing_semgrep(command: list[str], *, deadline: float) -> str | None:
    """Start caching the pinned semgrep when it is absent, without waiting for the download.

    Returns the reason the scan is skipped, or None when the tool is already cached.
    """
    try:
        _run_semgrep([*command, "--version"], cwd=REPO_ROOT, timeout=min(5, _semgrep_remaining(deadline)))
        return None
    except SemgrepExited:
        pass
    except SemgrepUnavailable:
        return None
    spec = _semgrep_spec()
    manual = f"{spec} is not cached. Run `hogli ci:preflight --prepare-semgrep` to cache it"
    # A cloud task or CI job starts with an empty cache, so it would download on every session.
    if is_ci() or os.environ.get("POSTHOG_TASK_RUN_ID"):
        return manual
    hogli = shutil.which("hogli")
    marker = _git("rev-parse", "--git-path", f"hogli-preflight-{spec}")
    if hogli is None or marker is None:
        return manual
    started = REPO_ROOT / marker.decode().strip()
    # The marker stops a machine that cannot download from starting one on every run.
    if started.exists() and time.time() - started.stat().st_mtime < _SEMGREP_DOWNLOAD_RETRY_SECONDS:
        return f"{manual} if the background download that started recently does not finish"
    try:
        # A child that holds the hook's output or its session keeps `git push` waiting.
        subprocess.Popen(
            [hogli, "ci:preflight", "--prepare-semgrep"],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        started.touch()
    except OSError:
        return manual
    return f"{spec} is not cached, so its download started in the background and the next run scans"


def prepare_semgrep() -> Outcome:
    command = _semgrep_command(offline=False)
    if command is None:
        return "skipped", f"uv is not on PATH, or {SEMGREP_WORKFLOW} pins no semgrep version"
    try:
        result = _run_semgrep([*command, "--version"], cwd=REPO_ROOT, timeout=120)
    except SemgrepUnavailable as error:
        return "skipped", str(error)
    return "pass", f"semgrep {result.stdout.strip()} is cached for offline preflight checks"


def _semgrep_findings(contents: dict[str, bytes], command: list[str], *, deadline: float) -> dict[Finding, list[int]]:
    """Findings in *contents* (path to file content), each with the lines it starts on.

    Raises SemgrepUnavailable when the scan did not complete. The scan targets a temporary
    directory containing the files. Semgrep applies its default ignore list
    (``tests/``, ``node_modules/``, minified files) to a directory it walks, which is how
    CI scans, and skips that list for a file named on the command line.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for path, content in contents.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        result = _run_semgrep(
            [
                *command,
                "--config",
                str(REPO_ROOT / SEMGREP_RULES),
                "--severity=WARNING",
                "--severity=ERROR",
                "--metrics=off",
                "--quiet",
                "--json",
                ".",
            ],
            cwd=root,
            timeout=_semgrep_remaining(deadline),
        )
    report = json.loads(result.stdout)
    # Semgrep can exit zero and still list a failure. A file it parsed only in part is listed
    # at "warn" level on ordinary TypeScript, and its other findings are still valid.
    if any(error.get("level") == "error" for error in report.get("errors", [])):
        raise SemgrepUnavailable("semgrep reported an incomplete scan; CI will run the check")
    findings: dict[Finding, list[int]] = {}
    for item in report["results"]:
        path = item["path"]
        if item["extra"]["severity"] == "ERROR" and matches_globs(path, SEMGREP_ERROR_EXCLUDED):
            continue
        start, end = item["start"]["line"], item["end"]["line"]
        lines = contents[path].decode(errors="replace").splitlines()[start - 1 : end]
        # The id prefix encodes the rule file's path relative to the working directory.
        # The last segment is the rule's own id.
        rule = item["check_id"].rsplit(".", 1)[-1]
        findings.setdefault((rule, path, "\n".join(line.strip() for line in lines)), []).append(start)
    return findings


def _check_semgrep_devex(scope: Scope, command: list[str], *, deadline: float) -> Outcome:
    # Semgrep cannot scan a binary, and a snapshot update can carry hundreds of them.
    after_contents = {
        path: content
        for path in scope.files
        if (content := _head_copy(path, scope.committed_only, timeout=_semgrep_remaining(deadline))) is not None
        and b"\0" not in content[:8000]
    }
    _semgrep_remaining(deadline)
    if not after_contents:
        return "skipped", "no file to scan"
    after = _semgrep_findings(after_contents, command, deadline=deadline)
    _semgrep_remaining(deadline)
    if not after:
        return "pass", "no new findings"

    # CI blocks only on findings the branch introduced, and gets them from `--baseline-commit`.
    # That flag is not usable here: on a clean checkout semgrep runs `git reset --hard` to the
    # baseline and back, and otherwise it checks the whole repository out again. Scanning the
    # merge-base copies of the flagged files gives the same comparison without touching the checkout.
    renames = _renamed_from(scope, timeout=_semgrep_remaining(deadline))
    before_contents = {
        path: content
        for path in {path for _, path, _ in after}
        if (
            content := _git(
                "show", f"{scope.merge_base}:{renames.get(path, path)}", timeout=_semgrep_remaining(deadline)
            )
        )
        is not None
    }
    _semgrep_remaining(deadline)
    before = _semgrep_findings(before_contents, command, deadline=deadline) if before_contents else {}
    _semgrep_remaining(deadline)

    introduced = [
        f"{rule} at {path}:{line}"
        for (rule, path, matched), lines in sorted(after.items())
        for line in lines[len(before.get((rule, path, matched), [])) :]
    ]
    if not introduced:
        return "pass", "no new findings"
    more = f" (+{len(introduced) - 3} more)" if len(introduced) > 3 else ""
    # An advisory and not a failure: this comparison is a reconstruction of CI's baseline scan,
    # so a mismatch between the two must not block a push.
    return (
        "advisory",
        f"{len(introduced)} new finding(s) that the semgrep-devex CI job blocks on: "
        f"{' · '.join(introduced[:3])}{more}. "
        f"Run `{' '.join(command)} --config {SEMGREP_RULES} <file>` to read the rule",
    )


def check_semgrep_devex(scope: Scope) -> Outcome:
    command = _semgrep_command()
    if command is None:
        return "skipped", f"uv is not on PATH, or {SEMGREP_WORKFLOW} pins no semgrep version"
    deadline = time.monotonic() + _SEMGREP_TIMEOUT_SECONDS
    try:
        return _check_semgrep_devex(scope, command, deadline=deadline)
    except SemgrepExited as error:
        reason = _download_missing_semgrep(command, deadline=deadline)
        return "skipped", reason or f"{error}; CI will run the check"
    except SemgrepUnavailable as error:
        return "skipped", str(error)
    except subprocess.TimeoutExpired:
        return "skipped", f"semgrep exceeded the {_SEMGREP_TIMEOUT_SECONDS}s check budget; CI will run the check"


LANE_TARGETS_SCRIPT = ".github/scripts/trunk-impacted-targets.js"
LANE_SUMMARY_SCRIPT = ".github/scripts/trunk-lane-telemetry.js"
_LANE_TIMEOUT_SECONDS = 120


def _node(script: str, files: list[str], env: dict[str, str]) -> object:
    result = subprocess.run(
        ["node", script],
        cwd=REPO_ROOT,
        env=env,
        input="\n".join(files),
        capture_output=True,
        text=True,
        timeout=_LANE_TIMEOUT_SECONDS,
    )
    return json.loads(result.stdout)


def check_merge_queue_lane(scope: Scope) -> Outcome:
    if shutil.which("node") is None:
        return "skipped", "node not found"
    # CI lists a rename as its old path and its new one, and the old path can widen the lane.
    changed = sorted({*scope.changed, *_renamed_from(scope).values()})
    env = {**os.environ, "LANE_MERGE_BASE": scope.merge_base}
    targets = _node(LANE_TARGETS_SCRIPT, changed, env)
    lane = _node(LANE_SUMMARY_SCRIPT, changed, {**env, "IMPACTED_TARGETS": json.dumps({"impactedTargets": targets})})
    if not isinstance(lane, dict) or not isinstance(targets, list):
        return "skipped", "could not compute the merge queue lane"
    if not lane.get("is_all"):
        return "pass", f"claims {len(targets)} merge queue lane target(s)"

    unsplittable: Outcome = ("pass", "claims every merge queue lane, and a split would not narrow it much")
    # The summary names the files that some widening rule matched, which is not proof of cause.
    # Recomputing the lane without the whole set shows what a split would gain. The summary cuts
    # its file list off, and its per-domain counts say how many files the full list holds.
    suspects = sorted(lane.get("tripwire_files") or [])
    rest = [path for path in changed if path not in suspects]
    if not suspects or not rest or len(suspects) != sum((lane.get("tripwire_domains") or {}).values()):
        return unsplittable
    narrowed = _node(LANE_TARGETS_SCRIPT, rest, env)
    # A split that still claims most lanes leaves the queue as serial as before.
    if not isinstance(narrowed, list) or len(narrowed) * 2 > len(targets):
        return unsplittable
    more = f" (+{len(suspects) - 3} more)" if len(suspects) > 3 else ""
    return (
        "warning",
        "claims every merge queue lane, so the whole queue merges in series behind this PR. "
        f"Without these {len(suspects)} file(s) the other changes claim {len(narrowed)} of {len(targets)} "
        f"lane targets: {', '.join(suspects[:3])}{more}",
    )
