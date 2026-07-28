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
universally followed: by that name, and structurally (``always()`` plus a step
that reads ``needs.<dep>.result``). Jobs that inspect results without gating
anything opt out with ``ALLOW_MARKER`` plus a reason.

Results reach their comparison directly (a literal beside ``needs.<dep>.result``)
or indirectly, by way of a step ``env:`` block or a shared shell function. Both
forms are judged the same way: each dependency's result is traced through
assignments, ``${!var}`` indirection, and helper-call argument positions to the
comparisons it actually reaches. A dependency that reaches no ``success``/
``skipped`` comparison is reported. Anything weaker means trusting that those
words appear *somewhere* in the step, which a comment or an ``echo`` satisfies
without gating a thing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Job, Workflow

ALLOW_MARKER = "hogli-lint: not-a-required-gate"

GATE_NAME = re.compile(r"\bpass$", re.IGNORECASE)
ALWAYS = re.compile(r"\balways\s*\(\s*\)")
READS_RESULT = re.compile(r"needs\.(?P<dep>[A-Za-z0-9_\-]+)\.result")

SAFE_LITERALS = frozenset({"success", "skipped"})

# `foo() {` / `function foo() {`, whose body ends at the first `}` sitting at or
# left of the definition's own indentation. Brace counting would be the general
# answer, but gate steps embed brace groups and Python heredocs, so the
# conventional shell layout is the more reliable signal.
FUNC_DEF = re.compile(r"^(?P<indent>[ \t]*)(?:function\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)\s*\{\s*$")

# One side of a `[[ … ]]` test: the operand, then the literal it is measured
# against. Quote-agnostic, so `"$result" == "success"` and `[[ $r == success ]]`
# read the same.
OPERAND = r"""\$\{\{[^}]*\}\}|\$\{!?[A-Za-z_0-9]+\}|\$[A-Za-z_0-9]+"""
COMPARISON = re.compile(rf"""(?P<operand>{OPERAND})["']?\s*(?:==|!=)\s*["']?(?P<literal>[A-Za-z_][A-Za-z_0-9]*)""")

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


def _bash(job: Job) -> str:
    return "\n".join(step.run for step in job.steps if step.run)


def _env_pairs(job: Job) -> Iterator[tuple[str, str]]:
    for block in (job.raw.get("env"), *(step.raw.get("env") for step in job.steps)):
        if isinstance(block, dict):
            for name, value in block.items():
                if isinstance(name, str) and isinstance(value, str):
                    yield name, value


def _exempt_jobs(path: Path, job_names: frozenset[str]) -> frozenset[str]:
    """Job ids carrying an allow marker, with a reason, in the comments above them.

    Keyed off the parsed job names rather than indentation depth, so it doesn't
    care how the file is formatted and can't be fooled by a nested mapping key.
    """
    lines = path.read_text(encoding="utf-8").splitlines()

    exempt: set[str] = set()
    for idx, line in enumerate(lines):
        match = re.match(r"^\s*(?P<job>[A-Za-z0-9_\-]+):\s*$", line)
        if match is None or match.group("job") not in job_names:
            continue
        # Walk up through the contiguous comment block directly above the job key.
        for above in reversed(lines[:idx]):
            if not above.strip().startswith("#"):
                break
            _, marker, reason = above.partition(ALLOW_MARKER)
            if marker and reason.strip(" -—:"):
                exempt.add(match.group("job"))
                break
    return frozenset(exempt)


def _is_gate(job: Job) -> bool:
    name = job.raw.get("name")
    display = name if isinstance(name, str) else job.name
    if GATE_NAME.search(display.strip()):
        return True
    return bool(ALWAYS.search(str(job.raw.get("if") or "")) and READS_RESULT.search(_bash(job)))


def _scopes(bash: str) -> list[_Scope]:
    lines = bash.splitlines()
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


def _trace(job: Job) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Resolve the gate's shell into (literals per operand, alias edges between operands).

    An edge ``a -> b`` means a result held by ``a`` also flows into ``b``, so a
    comparison on ``b`` gates ``a``.
    """
    scopes = _scopes(_bash(job))
    functions = {scope.name for scope in scopes if scope.name}

    literals: dict[str, set[str]] = {}
    edges: dict[str, set[str]] = {}

    # A result routed through `env:` is named by that variable in the step body.
    for name, value in _env_pairs(job):
        for source in _operands(_Scope("", ""), value, {}):
            edges.setdefault(source, set()).add(f"|var:{name}")

    for scope in scopes:
        loops = _loop_names(scope.body)

        for match in COMPARISON.finditer(scope.body):
            for operand in _operands(scope, match.group("operand"), loops):
                literals.setdefault(operand, set()).add(match.group("literal"))

        for line in scope.body.splitlines():
            assignment = ASSIGNMENT.match(line)
            if assignment is not None:
                target = f"{scope.name}|var:{assignment.group('target')}"
                for source in _operands(scope, assignment.group("source"), loops):
                    edges.setdefault(source, set()).add(target)

            # A helper call binds each argument to that function's positional parameter.
            call = line.strip()
            if "()" in call:
                continue
            name, _, rest = call.partition(" ")
            if name not in functions or not rest.strip():
                continue
            for position, argument in enumerate(ARGUMENT.findall(rest), start=1):
                for source in _operands(scope, argument, loops):
                    edges.setdefault(source, set()).add(f"{name}|arg:{position}")

    return literals, edges


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


def _problems(job: Job) -> Iterator[str]:
    if not ALWAYS.search(str(job.raw.get("if") or "")):
        yield "required-check gate must use `if: always()` so it always emits a verdict"

    literals, edges = _trace(job)

    for dep in sorted(set(READS_RESULT.findall(_bash(job)))):
        compared: set[str] = set()
        for operand in _reachable(f"needs:{dep}", edges):
            compared |= literals.get(operand, set())

        if compared & SAFE_LITERALS:
            continue
        if compared:
            yield (
                f"dependency '{dep}' is only compared against {'/'.join(sorted(compared))}; "
                f'a cancelled \'{dep}\' would pass. Test `!= "success" && != "skipped"` instead'
            )
        else:
            yield (
                f"dependency '{dep}' result never reaches a `success`/`skipped` comparison, so "
                f"nothing blocks a cancelled '{dep}'. Test it inline, or pass it to a helper that "
                f'tests `!= "success" && != "skipped"`'
            )


class RequiredGateCheck(WorkflowCheck):
    id = "WF007-required-check-gates"
    label = "required-check gates"
    description = "collate gates use always() and allowlist each dependency's result"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Keep `if: always()` on the gate, and test every dependency as "
            '`!= "success" && != "skipped"` rather than `== "failure"`. Inline tests, an `env:` '
            "block and a shared shell helper all work, so long as each result reaches such a "
            "test. A job that reads results without gating anything opts out with "
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
