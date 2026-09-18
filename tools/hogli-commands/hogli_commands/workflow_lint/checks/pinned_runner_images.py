"""Runner labels must name an OS version, never a floating ``-latest`` alias.

GitHub moves ``ubuntu-latest`` (and the macOS/Windows aliases, and Depot's
``depot-*-latest`` mirrors) to a new image on its own schedule. When it does,
every job on the alias changes toolchain, system packages and default Python
at once, with no diff in this repo to bisect. Pinning to ``ubuntu-24.04`` keeps
the image change an explicit PR.

The check reads ``runs-on`` and, for each ``matrix.<key>`` or
``matrix['<key>']`` that ``runs-on`` references, that key's values in
``strategy.matrix`` (including ``include`` and ``exclude`` entries). A label
picked through ``${{ matrix.runner }}`` or an inline ``&&``/``||`` expression
is covered as well as a plain string, while a matrix dimension that is not a
runner never fires the check.

A runner matrix built by an expression (``fromJSON(needs.plan.outputs.val)``)
cannot be inspected here, so it fails closed: the job needs ``ALLOW_MARKER``
with a reason naming where those labels are pinned.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..check import CheckResult, Issue, WorkflowCheck
from ..markers import exempt_jobs
from ..model import Job, Workflow

FLOATING_LABEL_RE = re.compile(r"(?<![\w-])((?:depot-)?(?:ubuntu|macos|windows)-latest(?:-[A-Za-z0-9.]+)*)(?![\w-])")
MATRIX_REF_RE = re.compile(r"\bmatrix(?:\.(?P<dot>[A-Za-z_][\w-]*)|\[['\"](?P<bracket>[A-Za-z_][\w-]*)['\"]\])")
ALLOW_MARKER = "hogli-lint: allow-generated-runner-matrix"


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _strings(nested)


def _matrix_values_for(matrix: object, key: str) -> Iterator[object]:
    if not isinstance(matrix, dict):
        yield matrix
        return
    if key in matrix:
        yield matrix[key]
    for combination_list in ("include", "exclude"):
        combinations = matrix.get(combination_list)
        if not isinstance(combinations, list):
            continue
        for combination in combinations:
            if isinstance(combination, dict) and key in combination:
                yield combination[key]


def _is_comparison_operand(text: str, match: re.Match[str]) -> bool:
    before = text[: match.start()].rstrip()
    after = text[match.end() :].lstrip()
    return before.endswith(("==", "!=")) or after.startswith(("==", "!="))


def _label_bearing_matrix_keys(runs_on: object) -> set[str]:
    """Matrix keys whose value can become the runner label.

    A reference that only feeds a comparison (``matrix.browser == 'webkit'``)
    yields a boolean, and the labels are the literals around it, which the
    ``runs-on`` text scan already covers.
    """
    return {
        match.group("dot") or match.group("bracket")
        for text in _strings(runs_on)
        for match in MATRIX_REF_RE.finditer(text)
        if not _is_comparison_operand(text, match)
    }


def _runner_sources(job: Job) -> Iterator[tuple[str, object]]:
    runs_on = job.raw.get("runs-on")
    if runs_on is None:
        return
    yield "runs-on", runs_on
    referenced_keys = _label_bearing_matrix_keys(runs_on)
    strategy = job.raw.get("strategy")
    if not referenced_keys or not isinstance(strategy, dict) or not isinstance(strategy.get("matrix"), dict):
        return
    for key in sorted(referenced_keys):
        yield f"strategy.matrix.{key}", list(_matrix_values_for(strategy["matrix"], key))


def _has_generated_runner_matrix(job: Job) -> bool:
    if not _label_bearing_matrix_keys(job.raw.get("runs-on")):
        return False
    strategy = job.raw.get("strategy")
    return isinstance(strategy, dict) and isinstance(strategy.get("matrix"), str)


def floating_labels(value: object) -> list[str]:
    found: list[str] = []
    for text in _strings(value):
        for match in FLOATING_LABEL_RE.finditer(text):
            if match.group(1) not in found:
                found.append(match.group(1))
    return found


class PinnedRunnerImagesCheck(WorkflowCheck):
    id = "WF011-pinned-runner-images"
    label = "pinned runner images"
    description = "runs-on and matrix runner labels name an OS version, not a floating -latest alias"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Replace `ubuntu-latest` with `ubuntu-24.04` (or `depot-ubuntu-24.04` on Depot), and pin the "
            "macOS/Windows aliases the same way, so an image change is a reviewed PR rather than a GitHub rollout. "
            f"A runner matrix built by an expression needs `# {ALLOW_MARKER} -- <where the labels are pinned>` "
            "above the job key."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            exempt = exempt_jobs(wf.path, frozenset(job.name for job in wf.jobs), ALLOW_MARKER)
            for job in wf.jobs:
                if _has_generated_runner_matrix(job) and job.name not in exempt:
                    result.issues.append(
                        Issue(
                            workflow=wf.path.name,
                            job=job.name,
                            message=(
                                "runs-on takes its label from a matrix built by an expression, which the linter "
                                f"cannot inspect; pin the labels at their source and add `# {ALLOW_MARKER} -- <reason>`"
                            ),
                            file=str(wf.path),
                        )
                    )
                for source, value in _runner_sources(job):
                    labels = floating_labels(value)
                    if not labels:
                        continue
                    result.issues.append(
                        Issue(
                            workflow=wf.path.name,
                            job=job.name,
                            message=f"{source} uses floating runner label(s) {', '.join(labels)}; pin the OS version",
                            file=str(wf.path),
                        )
                    )
        return result
