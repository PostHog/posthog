"""An action input that reaches an inner shell must not contain ``#``.

``.github/actions/semgrep-ci`` builds its command as
``sh -c "git config ... && exec semgrep ci ... $SEMGREP_ARGS"``. The outer bash
expands ``$SEMGREP_ARGS`` inside those double quotes, so the container's ``sh``
receives one long string and re-parses it as a script. That re-parse is what
performs the whitespace split into flags the input documents — and the same
tokenizer treats ``#`` as the start of a comment.

A caller writes the input as a YAML folded scalar (``args: >-``), which keeps
``#`` as data and collapses the block onto one line. A ``#`` note written inside
that block therefore comments out every flag after it. Semgrep loads fewer
configs, finds fewer things, and the job still exits 0 — the failure has no
symptom. Measured on a real PR: three jobs silently dropped configs and the
pre-existing ``--exclude-rule`` and ``--include`` scopes went with them.

Quoting is not the fix. ``$SEMGREP_ARGS`` already sits inside double quotes;
quoting it again would collapse every flag into a single argument.

``SHELL_SPLIT_INPUTS`` is the source of truth for which (action, input) pairs
carry this hazard, and it is what the check enforces.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import yaml
from hogli.manifest import REPO_ROOT

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

# Source of truth. Enforcement reads only this table; see `_drift_issues`.
REPO_PREFIX = "PostHog/posthog/"

# Actions that splice a caller's input into a command string an inner shell
# re-parses. EMPTY IS THE HEALTHY STATE: semgrep-ci used to be here, and the fix
# was to stop splicing (it splits the value and passes `"$@"`), not to police the
# value. An entry here means an action still has the hazard and its callers need
# checking until it does the same. `derive_shell_split_inputs` alarms in both
# directions, so neither adding nor removing an entry can go unnoticed.
SHELL_SPLIT_INPUTS: dict[str, frozenset[str]] = {}

ACTIONS_DIR = ".github/actions"

# Scoped to the `-c` operand: a var elsewhere in the run body (`"$SEMGREP_IMAGE"`)
# is its own quoted argument, never re-parsed, so it carries no hazard.
UNSAFE_ARG_RE = re.compile(r"[^ A-Za-z0-9._/@:=+-]")
SHELL_C_RE = re.compile(
    # Both quotings: Actions substitutes `${{ }}` before the shell parses, so a
    # single-quoted script splices an input just as a double-quoted one does.
    r"\b(?:sh|bash|dash|zsh|ksh)\b\s+(?:-\S+\s+)*-c\s+"
    r"(?:\"(?P<dquoted>(?:[^\"\\]|\\.)*)\"|'(?P<squoted>[^']*)')",
)
VAR_REF_RE = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_]\w*)[^}]*\}|(?P<plain>[A-Za-z_]\w*))")
INPUT_EXPR_RE = re.compile(
    r"\$\{\{\s*inputs(?:\.(?P<dot>[\w-]+)|\[\s*['\"](?P<bracket>[\w-]+)['\"]\s*\])\s*\}\}",
)


def _input_name(match: re.Match[str]) -> str:
    return match.group("dot") or match.group("bracket")


def _action_key(uses: str | None) -> str | None:
    """Normalize a step's ``uses:`` to a repo-relative action path, or None.

    Covers the local form (``./.github/actions/semgrep-ci``) and the
    repo-qualified one (``PostHog/posthog/.github/actions/semgrep-ci@sha``).
    """
    if not uses:
        return None
    path = uses.split("@", 1)[0].strip()
    # Anchored, never a substring search: `OtherOrg/repo/.github/actions/semgrep-ci`
    # is a different action that happens to share our layout, and matching it would
    # fail a workflow over semantics that action does not have.
    if path.startswith("./"):
        path = path[2:]
    elif path.startswith(REPO_PREFIX):
        path = path[len(REPO_PREFIX) :]
    if not path.startswith(ACTIONS_DIR):
        return None
    return path.rstrip("/")


def _load_action(action_dir: Path) -> dict[str, object] | None:
    """Parse ``<action_dir>/action.y[a]ml``. Returns None when there is no action there."""
    for name in ("action.yml", "action.yaml"):
        path = action_dir / name
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            return None
        return data if isinstance(data, dict) else None
    return None


def unparseable_actions(repo_root: Path) -> list[str]:
    """Actions whose metadata exists but does not parse.

    These must be REPORTED, never skipped. `_load_action` returns None for an
    unreadable action exactly as it does for an absent one, so without this a
    malformed `action.yml` makes `derive_shell_split_inputs` find nothing and the
    whole check passes clean -- the check silently doing nothing, which is the
    failure mode it exists to catch.
    """
    broken: list[str] = []
    actions_root = repo_root / ACTIONS_DIR
    if not actions_root.is_dir():
        return broken
    for directory in sorted(p for p in actions_root.iterdir() if p.is_dir()):
        for name in ("action.yml", "action.yaml"):
            path = directory / name
            if not path.is_file():
                continue
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except (yaml.YAMLError, OSError):
                broken.append(f"{ACTIONS_DIR}/{directory.name}")
            break
    return broken


def _declared_inputs(action_dir: Path) -> frozenset[str] | None:
    """Input names an action declares, or None when the action is not there."""
    data = _load_action(action_dir)
    if data is None:
        return None
    inputs = data.get("inputs")
    return frozenset(str(name) for name in inputs) if isinstance(inputs, dict) else frozenset()


def _composite_steps(data: dict[str, object]) -> Iterator[dict[str, object]]:
    runs = data.get("runs")
    if not isinstance(runs, dict):
        return
    steps = runs.get("steps")
    if not isinstance(steps, list):
        return
    for step in steps:
        if isinstance(step, dict):
            yield step


def _quoted_spans(script: str) -> list[tuple[int, int]]:
    """Index ranges the inner shell would treat as quoted.

    A quoted reference is ONE argument: the shell expands it without splitting
    it, so a `#` inside cannot start a comment and nothing after it is dropped.
    Both quotings count -- `"$ARGS"` and `'${{ inputs.flags }}'` are each safe --
    and a quote of one kind makes the other literal until it closes, which is why
    this tracks them together rather than one pass each.
    """
    spans: list[tuple[int, int]] = []
    index = 0
    length = len(script)
    while index < length:
        char = script[index]
        if char == "\\":
            index += 2
            continue
        if char in "\"'":
            quote = char
            start = index + 1
            cursor = start
            while cursor < length:
                # a backslash escapes only inside double quotes, never inside single
                if quote == '"' and script[cursor] == "\\":
                    cursor += 2
                    continue
                if script[cursor] == quote:
                    break
                cursor += 1
            spans.append((start, min(cursor, length)))
            index = cursor + 1
            continue
        index += 1
    return spans


def _spliced_inputs(step: dict[str, object]) -> Iterator[str]:
    """Input names this composite step splices into an inner shell command string."""
    run = step.get("run")
    if not isinstance(run, str):
        return
    env = step.get("env")
    by_var: dict[str, str] = {}
    if isinstance(env, dict):
        for var, value in env.items():
            if not isinstance(value, str):
                continue
            match = INPUT_EXPR_RE.fullmatch(value.strip())
            if match is not None:
                by_var[str(var)] = _input_name(match)
    for shell_c in SHELL_C_RE.finditer(run):
        script = shell_c.group("dquoted") or shell_c.group("squoted") or ""
        quoted = _quoted_spans(script)
        for ref in VAR_REF_RE.finditer(script):
            if any(lo <= ref.start() < hi for lo, hi in quoted):
                continue
            name = by_var.get(ref.group("braced") or ref.group("plain") or "")
            if name is not None:
                yield name
        # an input interpolated straight into the script, with no env hop
        for direct in INPUT_EXPR_RE.finditer(script):
            if any(lo <= direct.start() < hi for lo, hi in quoted):
                continue
            yield _input_name(direct)


def derive_shell_split_inputs(repo_root: Path) -> dict[str, frozenset[str]]:
    """Re-derive the ``SHELL_SPLIT_INPUTS`` shape from ``.github/actions/**``.

    Deliberately NOT authoritative — it only feeds the drift alarm below.
    This pattern matching is the fragile half: rewrite the semgrep step to
    build its command some other way and the regex matches nothing, the
    derivation returns an empty mapping, and every caller passes. That is the
    exact silent-failure mode this check exists to stop, so it must never be
    the thing that decides whether a caller is checked. The table decides;
    this only says the table looks out of date.
    """
    actions_dir = repo_root / ACTIONS_DIR
    if not actions_dir.is_dir():
        return {}
    derived: dict[str, frozenset[str]] = {}
    for path in sorted(actions_dir.rglob("action.y*ml")):
        data = _load_action(path.parent)
        if data is None:
            continue
        names = {name for step in _composite_steps(data) for name in _spliced_inputs(step)}
        if names:
            derived[f"{ACTIONS_DIR}/{path.parent.relative_to(actions_dir).as_posix()}"] = frozenset(names)
    return derived


class ShellSplitActionArgsCheck(WorkflowCheck):
    id = "WF012-shell-split-action-args"
    label = "shell-split action args"
    description = "action inputs re-parsed by an inner shell carry no '#', which would comment out the rest"

    def __init__(self, repo_root: Path | None = None) -> None:
        # Injected so tests can point at a fixture tree without monkeypatching env vars.
        self._repo_root = repo_root or REPO_ROOT

    @property
    def fix_hint(self) -> str | None:
        return (
            "Delete the '#' or move the note to a YAML comment ABOVE the input key, outside the block scalar — "
            "YAML strips a comment there, while inside a block scalar '#' is data that reaches the shell. "
            "Do not add quotes: the value is already spliced inside double quotes, so quoting it again would "
            "collapse every flag into one argument. If a drift line fired instead, update SHELL_SPLIT_INPUTS in "
            "workflow_lint/checks/shell_split_action_args.py."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            for job in wf.jobs:
                for step in job.steps:
                    action = _action_key(step.uses)
                    if action is None:
                        continue
                    for name in sorted(SHELL_SPLIT_INPUTS.get(action, frozenset())):
                        value = (step.with_ or {}).get(name)
                        if not isinstance(value, str):
                            continue
                        offenders = sorted(set(UNSAFE_ARG_RE.findall(value)))
                        if not offenders:
                            continue
                        result.issues.append(
                            Issue(
                                workflow=wf.path.name,
                                job=job.name,
                                step=step.ref,
                                message=(
                                    f"with.{name} passed to {action} contains {offenders!r}; the action splices "
                                    "this input into an inner shell command string, which re-parses it as a script, "
                                    "so a '#', newline, ';' or similar silently drops every flag after it"
                                ),
                                file=str(wf.path),
                            )
                        )
        result.issues.extend(self._drift_issues())
        return result

    def _drift_issues(self) -> list[Issue]:
        """Report the table drifting from ``.github/actions/**``. Never gates a caller.

        The two halves rot differently, and only one of them can go quiet:

        - "renamed away" reads the action file, so it keeps firing however the
          command is written. Rename or delete the action and it says so.
        - "missing from the table" depends on ``SHELL_SPLIT_INPUTS`` matching
          what the derivation regex finds, so a rewritten command makes it
          silent. That asymmetry is why the table, not the derivation, is what
          ``run`` enforces.

        Lives in the check rather than only in a test because
        ``ci-lint-workflows.yml`` triggers on ``.github/actions/**`` while the
        ``hogli`` path filter that runs this test suite does not — an action
        edited on its own would otherwise reach master unexamined.
        """
        issues: list[Issue] = []
        for action, names in sorted(SHELL_SPLIT_INPUTS.items()):
            declared = _declared_inputs(self._repo_root / action)
            if declared is None:
                issues.append(
                    Issue(
                        workflow=action,
                        message=(
                            "listed in SHELL_SPLIT_INPUTS but there is no action there; the action was renamed or "
                            "deleted, so callers of its replacement are unchecked — update the table"
                        ),
                        file=str(self._repo_root / action),
                    )
                )
                continue
            for name in sorted(names - declared):
                issues.append(
                    Issue(
                        workflow=action,
                        message=(
                            f"SHELL_SPLIT_INPUTS lists input '{name}', which the action no longer declares — "
                            "update the table to the input that now carries the value"
                        ),
                        file=str(self._repo_root / action),
                    )
                )
        for action in unparseable_actions(self._repo_root):
            issues.append(
                Issue(
                    workflow=action,
                    message=(
                        f"{action}/action.yml does not parse, so this check cannot tell whether it splices an "
                        "input into an inner shell — fix the file; an unreadable action reads exactly like a "
                        "safe one here"
                    ),
                    file=str(self._repo_root / action),
                )
            )
        derived = derive_shell_split_inputs(self._repo_root)
        for action in sorted(set(SHELL_SPLIT_INPUTS) - set(derived)):
            # A missing action is already reported above, and more precisely;
            # this alarm is for one that still exists and has stopped splicing.
            if _load_action(self._repo_root / action) is None:
                continue
            issues.append(
                Issue(
                    workflow=action,
                    message=(
                        f"SHELL_SPLIT_INPUTS lists {action}, but nothing there splices an input into an inner "
                        "shell any more — drop the entry, or callers keep being checked against a hazard that "
                        "is gone"
                    ),
                    file=str(self._repo_root / action),
                )
            )
        for action, names in sorted(derived.items()):
            for name in sorted(names - SHELL_SPLIT_INPUTS.get(action, frozenset())):
                issues.append(
                    Issue(
                        workflow=action,
                        message=(
                            f"input '{name}' is spliced into an inner shell command string but is missing from "
                            "SHELL_SPLIT_INPUTS, so callers passing it are unchecked — add it to the table"
                        ),
                        file=str(self._repo_root / action),
                    )
                )
        return issues


__all__ = ["SHELL_SPLIT_INPUTS", "ShellSplitActionArgsCheck", "derive_shell_split_inputs", "unparseable_actions"]
