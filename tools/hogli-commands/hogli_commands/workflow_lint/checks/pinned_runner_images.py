"""Runner labels must name an OS version, never a floating ``-latest`` alias.

GitHub moves ``ubuntu-latest`` (and the macOS/Windows aliases, and Depot's
``depot-*-latest`` mirrors) to a new image on its own schedule. When it does,
every job on the alias changes toolchain, system packages and default Python
at once, with no diff in this repo to bisect. Pinning to ``ubuntu-24.04`` keeps
the image change an explicit PR.

The check reads ``runs-on`` and, for each ``matrix.<key>`` that ``runs-on``
references, that key's values in ``strategy.matrix`` (including ``include``
and ``exclude`` entries). A label picked through ``${{ matrix.runner }}`` or
an inline ``&&``/``||`` expression is covered as well as a plain string, while
a matrix dimension that is not a runner never fires the check.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Job, Workflow

FLOATING_LABEL_RE = re.compile(r"(?<![\w-])((?:depot-)?(?:ubuntu|macos|windows)-latest(?:-[A-Za-z0-9.]+)*)(?![\w-])")
MATRIX_REF_RE = re.compile(r"\bmatrix\.([A-Za-z_][\w-]*)")


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


def _runner_sources(job: Job) -> Iterator[tuple[str, object]]:
    runs_on = job.raw.get("runs-on")
    if runs_on is None:
        return
    yield "runs-on", runs_on
    referenced_keys = {match.group(1) for text in _strings(runs_on) for match in MATRIX_REF_RE.finditer(text)}
    strategy = job.raw.get("strategy")
    if not referenced_keys or not isinstance(strategy, dict) or "matrix" not in strategy:
        return
    for key in sorted(referenced_keys):
        yield f"strategy.matrix.{key}", list(_matrix_values_for(strategy["matrix"], key))


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
            "macOS/Windows aliases the same way, so an image change is a reviewed PR rather than a GitHub rollout."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            for job in wf.jobs:
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
