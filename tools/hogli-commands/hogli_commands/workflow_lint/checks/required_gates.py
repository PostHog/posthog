"""Collate gates must run unconditionally and fail closed on every dependency.

A "collate gate" is the job that emits a required status check by inspecting its
dependencies' ``needs.*.result``. Two properties keep it honest:

1. ``if: always()`` — the gate must run and emit an explicit verdict. Worker jobs
   should use ``!cancelled()`` so they actually stop when a run is superseded, but
   the gate itself is what branch protection reads, so it has to report.

2. Allowlist **per dependency** — assert ``success``/``skipped`` and block
   everything else. One bad dependency is enough, so judging the step as a whole
   would call a mostly-correct gate clean. The trap is a ``changes`` detector
   cleared with a bare ``== 'failure'`` test: ``cancelled`` passes it, the gate
   then reads ``needs.changes.outputs.*``, which is empty on a cancelled job, and
   takes its "nothing to test" exit — green, with zero tests run.

Gates are found two ways, because the "name it ``… Pass``" convention is not
universally followed: by that name, and structurally when a step reads
``needs.<dep>.result`` in its shell or environment. Detection is independent of
the job condition so a gate missing ``always()`` cannot disappear from the rule.
Jobs that inspect results without gating anything opt out with ``ALLOW_MARKER``
plus a reason.

Results reach a fail-closed guard directly or indirectly, by way of a step
``env:`` block or a shared shell function. Both forms are judged the same way:
within each step, every dependency's result is traced through assignments,
``${!var}`` indirection, and helper-call argument positions to a canonical guard.
That guard must allowlist one or both safe states with ``!=`` comparisons joined
by ``&&``, then unconditionally exit nonzero. This keeps comparisons in comments,
logs, other steps, and non-failing branches from certifying a dependency.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Job, Step, Workflow

ALLOW_MARKER = "hogli-lint: not-a-required-gate"

GATE_NAME = re.compile(r"\bpass$", re.IGNORECASE)
ALWAYS = re.compile(r"always\s*\(\s*\)")
READS_RESULT = re.compile(r"needs\.(?P<dep>[A-Za-z0-9_\-]+)\.result")

# `foo() {` / `function foo() {`, whose body ends at the first `}` sitting at or
# left of the definition's own indentation. Brace counting would be the general
# answer, but gate steps embed brace groups and Python heredocs, so the
# conventional shell layout is the more reliable signal.
FUNC_DEF = re.compile(r"^(?P<indent>[ \t]*)(?:function\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)\s*\{\s*$")

OPERAND = r"""\$\{\{[^}]*\}\}|\$\{!?[A-Za-z_0-9]+\}|\$[A-Za-z_0-9]+"""
IF_TEST = re.compile(r"^\s*if\s+\[\[\s*(?P<condition>.*?)\s*\]\]\s*;\s*then\s*(?:#.*)?$")
NOT_SAFE_STATUS = re.compile(rf"""["']?(?P<operand>{OPERAND})["']?\s*!=\s*["']?(?P<literal>success|skipped)["']?""")
NONZERO_EXIT = re.compile(r"exit\s+[1-9][0-9]*\s*(?:#.*)?$")
SIMPLE_LOG = re.compile(r"(?:echo|printf)\s+(?:\"[^\"]*\"|'[^']*')\s*$")
HEREDOC = re.compile(r"<<-?\s*[\"']?(?P<delimiter>[A-Za-z_][A-Za-z0-9_]*)[\"']?")

# `local result="$2"` / `val="${!var}"`, which is how a positional or an env value
# picks up the name that the comparison further down actually tests.
ASSIGNMENT = re.compile(
    rf"""^\s*(?:local\s+|declare\s+|export\s+)?(?P<target>[A-Za-z_][A-Za-z_0-9]*)=["']?(?P<source>{OPERAND})["']?"""
)

# `for var in BUILD DEPLOY; do`, giving the candidate names a later `${!var}` can hold.
FOR_LOOP = re.compile(r"^\s*for\s+(?P<var>[A-Za-z_][A-Za-z_0-9]*)\s+in\s+(?P<names>[^;]+?)\s*;?\s*do\b")

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")
ARGUMENT = re.compile(r"""\"[^\"]*\"|'[^']*'|\S+""")
VAR_OPERAND = re.compile(r"^\$\{?(?P<indirect>!)?(?P<name>[A-Za-z_0-9]+)\}?$")


@dataclass(frozen=True, slots=True)
class _Scope:
    """A shell body with its own positional parameters: one function, or the step itself."""

    name: str  # "" for the step body outside any function
    body: str


def _env(block: object) -> dict[str, str]:
    if not isinstance(block, dict):
        return {}
    return {name: value for name, value in block.items() if isinstance(name, str) and isinstance(value, str)}


def _effective_env(job: Job, step: Step) -> dict[str, str]:
    return _env(job.raw.get("env")) | _env(step.raw.get("env"))


def _result_sources(job: Job) -> Iterator[str]:
    yield from _env(job.raw.get("env")).values()
    for step in job.steps:
        if step.run:
            yield step.run
        condition = step.raw.get("if")
        if isinstance(condition, str):
            yield condition
        yield from _env(step.raw.get("env")).values()


def _exempt_jobs(path: Path, job_names: frozenset[str]) -> frozenset[str]:
    """Job ids carrying an allow marker, with a reason, in the comments above them."""
    lines = path.read_text(encoding="utf-8").splitlines()
    candidates: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(?P<indent>\s*)(?P<job>[A-Za-z0-9_\-]+):\s*$", line)
        if match is not None and match.group("job") in job_names:
            candidates.append((index, len(match.group("indent")), match.group("job")))
    if not candidates:
        return frozenset()

    exempt: set[str] = set()
    job_indent = min(indent for _, indent, _ in candidates)
    for index, indent, job in candidates:
        if indent != job_indent:
            continue
        for above in reversed(lines[:index]):
            comment = re.match(r"^(?P<indent>\s*)#(?P<body>.*)$", above)
            if comment is None or len(comment.group("indent")) != job_indent:
                break
            _, marker, reason = comment.group("body").partition(ALLOW_MARKER)
            if marker and reason.strip(" -—:"):
                exempt.add(job)
                break
    return frozenset(exempt)


def _is_gate(job: Job) -> bool:
    name = job.raw.get("name")
    display = name if isinstance(name, str) else job.name
    if GATE_NAME.search(display.strip()):
        return True
    return any(READS_RESULT.search(source) for source in _result_sources(job))


def _uses_only_always(condition: object) -> bool:
    if not isinstance(condition, str):
        return False
    normalized = condition.strip()
    if normalized.startswith("${{") or normalized.endswith("}}"):
        if not (normalized.startswith("${{") and normalized.endswith("}}")):
            return False
        normalized = normalized[3:-2].strip()
    return ALWAYS.fullmatch(normalized) is not None


def _without_heredocs(bash: str) -> str:
    lines: list[str] = []
    delimiter: str | None = None
    for line in bash.splitlines():
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            lines.append("")
            continue
        lines.append(line)
        match = HEREDOC.search(line)
        if match is not None:
            delimiter = match.group("delimiter")
    return "\n".join(lines)


def _scopes(bash: str) -> list[_Scope]:
    lines = _without_heredocs(bash).splitlines()
    top: list[str] = []
    scopes: list[_Scope] = []

    idx = 0
    while idx < len(lines):
        match = FUNC_DEF.match(lines[idx])
        if match is None:
            top.append(lines[idx])
            idx += 1
            continue
        indent = len(match.group("indent"))
        body: list[str] = []
        idx += 1
        while idx < len(lines):
            line = lines[idx]
            idx += 1
            if line.strip() == "}" and len(line) - len(line.lstrip()) <= indent:
                break
            body.append(line)
        scopes.append(_Scope(match.group("name"), "\n".join(body)))

    scopes.append(_Scope("", "\n".join(top)))
    return scopes


def _loop_names(body: str) -> dict[str, set[str]]:
    """Loop variable to the identifiers it iterates over, so `${!var}` can be resolved."""
    loops: dict[str, set[str]] = {}
    for line in body.splitlines():
        match = FOR_LOOP.match(line)
        if match is None:
            continue
        names = {word for word in match.group("names").split() if IDENTIFIER.match(word)}
        if names:
            loops.setdefault(match.group("var"), set()).update(names)
    return loops


def _operands(scope: _Scope, token: str, loops: dict[str, set[str]]) -> list[str]:
    """Every operand key a shell token can stand for.

    `${{ needs.x.result }}` is global; `$2` and `$result` are local to their
    scope; `${!var}` stands for whichever names the enclosing loop supplies.
    """
    token = token.strip().strip('"').strip("'")
    if "needs." in token:
        match = READS_RESULT.search(token)
        return [f"needs:{match.group('dep')}"] if match else []

    match = VAR_OPERAND.match(token)
    if match is None:
        return []
    name = match.group("name")
    if match.group("indirect"):
        return [f"{scope.name}|var:{held}" for held in sorted(loops.get(name, ()))]
    kind = "arg" if name.isdigit() else "var"
    return [f"{scope.name}|{kind}:{name}"]


def _guard_operand(lines: list[str], index: int) -> str | None:
    match = IF_TEST.match(lines[index])
    if match is None:
        return None

    comparisons: list[re.Match[str]] = []
    for term in re.split(r"\s*&&\s*", match.group("condition")):
        comparison = NOT_SAFE_STATUS.fullmatch(term.strip())
        if comparison is None:
            return None
        comparisons.append(comparison)

    operands = {comparison.group("operand") for comparison in comparisons}
    if len(operands) != 1:
        return None

    for body_line in lines[index + 1 :]:
        stripped = body_line.strip()
        if not stripped or stripped.startswith("#") or SIMPLE_LOG.fullmatch(stripped):
            continue
        if NONZERO_EXIT.fullmatch(stripped):
            return operands.pop()
        return None
    return None


def _trace_step(job: Job, step: Step) -> tuple[set[str], dict[str, set[str]]]:
    """Resolve one shell step into guarded operands and alias edges.

    An edge ``a -> b`` means a result held by ``a`` also flows into ``b``, so a
    fail-closed guard on ``b`` gates ``a``. Steps stay isolated because their
    shells and step-level environments do not persist into later steps.
    """
    scopes = _scopes(step.run or "")
    functions = {scope.name for scope in scopes if scope.name}

    guarded: set[str] = set()
    edges: dict[str, set[str]] = {}

    for name, value in _effective_env(job, step).items():
        for source in _operands(_Scope("", ""), value, {}):
            edges.setdefault(source, set()).add(f"|var:{name}")

    for scope in scopes:
        loops = _loop_names(scope.body)
        lines = scope.body.splitlines()

        if step.raw.get("if") is None or _uses_only_always(step.raw.get("if")):
            for index in range(len(lines)):
                guard_operand = _guard_operand(lines, index)
                if guard_operand is not None:
                    guarded.update(_operands(scope, guard_operand, loops))

        for line in lines:
            assignment = ASSIGNMENT.match(line)
            if assignment is not None:
                target = f"{scope.name}|var:{assignment.group('target')}"
                for source in _operands(scope, assignment.group("source"), loops):
                    edges.setdefault(source, set()).add(target)

            # A helper call binds each argument to that function's positional parameter.
            # Only a nested definition is skipped here, matched as such rather than by
            # looking for `()` anywhere, which also discards real calls whose arguments
            # or trailing comment happen to contain those two characters.
            call = line.strip()
            if FUNC_DEF.match(call):
                continue
            name, _, rest = call.partition(" ")
            if name not in functions or not rest.strip():
                continue
            for position, argument in enumerate(ARGUMENT.findall(rest), start=1):
                for source in _operands(scope, argument, loops):
                    edges.setdefault(source, set()).add(f"{name}|arg:{position}")

    return guarded, edges


def _reachable(start: str, edges: dict[str, set[str]]) -> Iterable[str]:
    seen = {start}
    queue = [start]
    while queue:
        node = queue.pop()
        yield node
        for nxt in edges.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)


def _dependencies(job: Job) -> set[str]:
    """Every dependency the gate is answerable for.

    Taken from ``needs:`` as well as the step body, because a job wired into
    ``needs:`` and then never tested is the drift this check exists to catch:
    reading only the body would judge the assertions that were written and stay
    silent about the one that was forgotten.
    """
    declared = job.raw.get("needs") or []
    declared = [declared] if isinstance(declared, str) else declared
    named = {dep for dep in declared if isinstance(dep, str)}
    referenced = {dep for source in _result_sources(job) for dep in READS_RESULT.findall(source)}
    return named | referenced


def _problems(job: Job) -> Iterator[str]:
    if not _uses_only_always(job.raw.get("if")):
        yield "required-check gate must use unconditional `if: always()` so it always emits a verdict"

    step_traces = [_trace_step(job, step) for step in job.steps]
    for dep in sorted(_dependencies(job)):
        if not any(
            any(operand in guarded for operand in _reachable(f"needs:{dep}", edges)) for guarded, edges in step_traces
        ):
            yield (
                f"dependency '{dep}' result never reaches a fail-closed guard, so nothing blocks a "
                f'cancelled \'{dep}\'. Test `!= "success" && != "skipped"`, then exit nonzero'
            )


class RequiredGateCheck(WorkflowCheck):
    id = "WF007-required-check-gates"
    label = "required-check gates"
    description = "collate gates use always() and allowlist each dependency's result"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Use only `if: always()` on the gate, and test every dependency as "
            '`!= "success" && != "skipped"` rather than `== "failure"`. Inline tests, an `env:` '
            "block and a shared shell helper all work, so long as the failing branch exits nonzero. "
            "A job that reads results without gating anything opts out with "
            f"`# {ALLOW_MARKER} — <reason>`. See .agents/skills/authoring-ci-workflows/SKILL.md."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            gates = [job for job in wf.jobs if not job.is_reusable_call and _is_gate(job)]
            if not gates:
                continue
            # Only worth re-reading the file once we know there's a gate to exempt.
            exempt = _exempt_jobs(wf.path, frozenset(job.name for job in wf.jobs))
            for job in gates:
                if job.name in exempt:
                    continue
                for message in _problems(job):
                    result.issues.append(Issue(workflow=wf.path.name, job=job.name, message=message, file=str(wf.path)))
        return result
