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

The table also lists the milder form, ``sh -c 'tool $ARGS'``. There the INNER
shell expands the value, so a ``#`` in it stays a literal word rather than a
comment — but the split into flags is still the action's to decide, and the
same expansion globs, so ``--include *.py`` reaches the tool as whatever
happened to match in the container. Either way the caller's value does not
arrive as the caller wrote it, which is what the character set below rejects.

``SHELL_SPLIT_INPUTS`` is the source of truth for which (action, input) pairs
carry this hazard, and it is what the check enforces.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

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
# One option token before `-c`, with its value when it takes a separate one.
# `-o pipefail`, `-O extglob`, their `+` forms and `--rcfile <file>` all put the
# value in its own token, so a repetition that accepted only flags stopped at
# that value and left the whole invocation uninspected.
SHELL_OPTION = r"(?:(?:[-+][oO]|--(?:rcfile|init-file))\s+\S+|[-+]\S+)\s+"
# The three segment forms. A shell joins ADJACENT segments into one word, so
# `'tool '"$ARGS"` is a single operand in two segments, each quoted its own way.
DQUOTED = r"\"(?:[^\"\\]|\\.)*\""
SQUOTED = r"'[^']*'"
UNQUOTED = r"[^\s\"']+"
OPERAND_SEGMENT_RE = re.compile(rf"(?P<dquoted>{DQUOTED})|(?P<squoted>{SQUOTED})|(?P<bare>{UNQUOTED})")
SHELL_C_RE = re.compile(
    # The whole operand word. Quoting a segment does not make the value in it
    # safe, and leaving it bare (`sh -c $FLAGS`) is if anything worse -- the
    # operand is then split before the inner shell even sees it.
    rf"\b(?:sh|bash|dash|zsh|ksh)\b\s+(?:{SHELL_OPTION})*-[a-zA-Z]*c\s+"
    rf"(?P<operand>(?:{DQUOTED}|{SQUOTED}|{UNQUOTED})+)",
)
VAR_REF_RE = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_]\w*)[^}]*\}|(?P<plain>[A-Za-z_]\w*))")
EVAL_RE = re.compile(r"\beval\b")
# A nested `-c` parses its argument exactly as `eval` does -- verified against
# `sh`: with ARGS='one ; echo two', `sh -c 'bash -c "$ARGS"'` runs the echo.
# Unlike `eval` this is not required to be the command word, because it usually
# is not one: `docker exec c sh -c`, `timeout 30 sh -c`. That is the same shape
# as the `docker run ... sh -c` the outer matcher exists to find.
NESTED_SHELL_C_RE = re.compile(r"(?<!-)\b(?:sh|bash|dash|zsh|ksh)\b\s+(?:" + SHELL_OPTION + r")*-[a-zA-Z]*c\b")
# What `eval` is the head of ends here, so the next command's arguments are not
# read as eval's.
COMMAND_END_RE = re.compile(r"[;&|\n()]")
# `eval` counts only as a command word. After anything else it is an argument or
# a literal (`tool --eval`), and re-parses nothing.
COMMAND_HEAD_RE = re.compile(r"(?:[;&|\n(){]|\b(?:then|else|do))[ \t]*$")
# Any `${{ ... }}` block, then the input names inside it. Matching only a bare
# `${{ inputs.x }}` missed every transformed form -- `${{ inputs.x || '' }}`,
# `${{ format('{0}', inputs.x) }}` -- which interpolate exactly the same text.
EXPR_BLOCK_RE = re.compile(r"\$\{\{(?P<body>.*?)\}\}", re.DOTALL)
INPUT_REF_RE = re.compile(r"\binputs(?:\.(?P<dot>[\w-]+)|\[\s*['\"](?P<bracket>[\w-]+)['\"]\s*\])")


def _expression_inputs(text: str) -> Iterator[str]:
    """Every input named inside a `${{ ... }}` block in `text`."""
    for block in EXPR_BLOCK_RE.finditer(text):
        for ref in INPUT_REF_RE.finditer(block.group("body")):
            yield _input_name(ref)


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
        except (yaml.YAMLError, OSError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None
    return None


def unparseable_actions(repo_root: Path) -> list[str]:
    """Repo-relative paths of action metadata files that exist but do not parse.

    The path, not the directory that holds it: an action may be spelled
    ``action.yml`` or ``action.yaml``, and only the real one can be named in the
    message or annotated by GitHub.

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
    # rglob, matching `derive_shell_split_inputs`: a nested action it would scan
    # must not be invisible to the alarm that says the scan could not read one.
    for path in sorted(actions_root.rglob("action.y*ml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError, UnicodeDecodeError):
            broken.append(path.relative_to(repo_root).as_posix())
            continue
        # Parsing is not the bar; being usable is. An empty file, a list or a
        # scalar parses fine and `_load_action` discards it exactly as it
        # discards an absent action, so it would read here as an action with no
        # hazard rather than one nothing could inspect.
        if not isinstance(data, dict):
            broken.append(path.relative_to(repo_root).as_posix())
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


class _Span(NamedTuple):
    """A half-open index range. Named because `start` and `end` share a type and a
    bare `tuple[int, int]` lets a call site swap them silently."""

    start: int
    end: int


def _quoted_spans(script: str) -> list[_Span]:
    """Index ranges the inner shell would treat as quoted.

    A quoted reference is ONE argument: the shell expands it without splitting
    it, so a `#` inside cannot start a comment and nothing after it is dropped.
    Both quotings count -- `"$ARGS"` and `'${{ inputs.flags }}'` are each safe --
    and a quote of one kind makes the other literal until it closes, which is why
    this tracks them together rather than one pass each.
    """
    spans: list[_Span] = []
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
            spans.append(_Span(start, min(cursor, length)))
            index = cursor + 1
            continue
        index += 1
    return spans


def _operand_segments(operand: str) -> Iterator[tuple[str, bool]]:
    """Each segment of the `-c` operand word, with whether the OUTER shell expands it.

    A single-quoted segment reaches the inner shell verbatim, so the inner shell
    is what expands anything in it. Every other segment is expanded by the outer
    shell first, before the inner shell sees the text at all.
    """
    for segment in OPERAND_SEGMENT_RE.finditer(operand):
        if (squoted := segment.group("squoted")) is not None:
            yield squoted[1:-1], False
        elif (dquoted := segment.group("dquoted")) is not None:
            yield dquoted[1:-1], True
        else:
            yield segment.group("bare"), True


def _in_any(spans: list[_Span], index: int) -> bool:
    return any(span.start <= index < span.end for span in spans)


def _reparsed_argument_spans(script: str, quoted: list[_Span]) -> list[_Span]:
    """Index ranges a second parse reads, after the shell expands them.

    A quoted reference is one argument, which is why `_spliced_inputs` skips it.
    `eval` and a nested `-c` are the exception the skip cannot survive: both take
    the expanded text and parse it as a command, so a `#`, `;` or newline in the
    value still truncates or splits what runs. `ssh host "$X"` has the same
    shape and is not matched -- it hands the value to a shell somewhere else.

    `eval` counts only as a command word, because `--eval` and a bare mention of
    it are ordinary text.
    """
    heads = [(match, True) for match in EVAL_RE.finditer(script)]
    heads += [(match, False) for match in NESTED_SHELL_C_RE.finditer(script)]
    spans: list[_Span] = []
    for match, command_word_only in sorted(heads, key=lambda head: head[0].start()):
        before = script[: match.start()]
        if _in_any(quoted, match.start()):
            continue
        if command_word_only and before.strip() and not COMMAND_HEAD_RE.search(before):
            continue
        end = len(script)
        for terminator in COMMAND_END_RE.finditer(script, match.end()):
            if not _in_any(quoted, terminator.start()):
                end = terminator.start()
                break
        spans.append(_Span(match.end(), end))
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
            for name in _expression_inputs(value):
                by_var[str(var)] = name
    for shell_c in SHELL_C_RE.finditer(run):
        for script, outer_expanded in _operand_segments(shell_c.group("operand")):
            # Inner quotes protect a variable ONLY inside a single-quoted segment.
            # There the outer shell passes the text through untouched and the inner
            # shell expands `"$ARGS"` itself, giving one argument. In a
            # double-quoted or bare segment the OUTER shell expands the variable into
            # the script text first, so a quote in the value closes the quote around
            # it -- the same pre-substitution problem GitHub expressions have.
            # `eval` and a nested `-c` are where "one argument" stops being
            # enough; see `_reparsed_argument_spans`.
            quoted = [] if outer_expanded else _quoted_spans(script)
            reparsed = _reparsed_argument_spans(script, quoted)
            for ref in VAR_REF_RE.finditer(script):
                if _in_any(quoted, ref.start()) and not _in_any(reparsed, ref.start()):
                    continue
                name = by_var.get(ref.group("braced") or ref.group("plain") or "")
                if name is not None:
                    yield name
            # an input interpolated straight into the script, with no env hop
            # NO quote check here, unlike the variable references above, and the
            # difference is the whole point. A shell variable is expanded AFTER the
            # shell parses quotes, so `"$ARGS"` is one argument whatever it holds.
            # A GitHub expression is substituted into the script text BEFORE any
            # shell runs, so a quote inside the value closes the quote around it and
            # the rest is re-parsed as script. Quoting cannot protect it; only
            # passing it through `env:` and referencing the variable can.
            yield from _expression_inputs(script)


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
                                    f"with.{name} passed to {action} contains {offenders!r}; the action hands "
                                    "this value to a shell rather than passing it as arguments, so a '#', newline "
                                    "or ';' can silently drop every flag after it and a '*' can expand against the "
                                    "container's filesystem"
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
        for metadata in unparseable_actions(self._repo_root):
            issues.append(
                Issue(
                    workflow=metadata,
                    message=(
                        "does not parse, so this check cannot tell whether the action splices an "
                        "input into an inner shell — fix the file; an unreadable action reads exactly like a "
                        "safe one here"
                    ),
                    file=str(self._repo_root / metadata),
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
