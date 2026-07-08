"""Full-depth checkouts should avoid fetching full history plus full blobs."""

from __future__ import annotations

import re
from functools import cache

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Step, Workflow

ALLOW_MARKER = "hogli-lint: allow-full-depth-checkout"
CHECKOUT_USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*[\"']?actions/checkout@", re.IGNORECASE)
STEP_START_RE = re.compile(r"^\s*-\s")


def _is_checkout(step: Step) -> bool:
    return step.uses is not None and step.uses.lower().startswith("actions/checkout@")


def _fetch_depth_is_zero(step: Step) -> bool:
    if step.with_ is None:
        return False
    value = step.with_.get("fetch-depth")
    return value == 0 or value == "0"


def _has_blobless_filter(step: Step) -> bool:
    return step.with_ is not None and step.with_.get("filter") == "blob:none"


def _has_sparse_checkout(step: Step) -> bool:
    if step.with_ is None:
        return False
    value = step.with_.get("sparse-checkout")
    return isinstance(value, str) and value.strip() != ""


def _allow_marker_has_reason(line: str) -> bool:
    _, _, reason = line.partition(ALLOW_MARKER)
    return reason.strip().startswith("--") and bool(reason.strip()[2:].strip())


def _step_start_line(lines: list[str], uses_idx: int) -> int:
    for idx in range(uses_idx, max(-1, uses_idx - 8), -1):
        if STEP_START_RE.search(lines[idx]):
            return idx
    return uses_idx


def _checkout_has_allow_marker(lines: list[str], uses_idx: int) -> bool:
    step_start = _step_start_line(lines, uses_idx)
    for candidate in lines[step_start : uses_idx + 1]:
        if ALLOW_MARKER in candidate and _allow_marker_has_reason(candidate):
            return True

    idx = step_start - 1
    while idx >= 0 and lines[idx].strip().startswith("#"):
        if ALLOW_MARKER in lines[idx] and _allow_marker_has_reason(lines[idx]):
            return True
        idx -= 1

    return False


@cache
def _allowed_checkout_ordinals(path: str) -> frozenset[int]:
    """Return checkout step ordinals with a nearby allow marker.

    PyYAML drops comments, so the parsed model handles workflow semantics while
    this raw scan only maps explicit reviewable bypass comments to checkout
    steps.
    """

    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    allowed: set[int] = set()
    checkout_ordinal = 0

    for idx, line in enumerate(lines):
        if not CHECKOUT_USES_RE.search(line):
            continue
        if _checkout_has_allow_marker(lines, idx):
            allowed.add(checkout_ordinal)
        checkout_ordinal += 1

    return frozenset(allowed)


class CheckoutFullDepthCheck(WorkflowCheck):
    id = "WF005-checkout-full-depth"
    label = "checkout full depth"
    description = "full-depth actions/checkout steps use blobless, sparse, or explicit allow comments"

    @property
    def fix_hint(self) -> str | None:
        return (
            "For `actions/checkout` with `fetch-depth: 0`, add `filter: blob:none`, "
            "use `sparse-checkout`, or add `# hogli-lint: allow-full-depth-checkout -- <reason>`."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            checkout_ordinal = 0
            allowed_ordinals = _allowed_checkout_ordinals(str(wf.path))
            for job in wf.jobs:
                for step in job.steps:
                    if not _is_checkout(step):
                        continue

                    if (
                        _fetch_depth_is_zero(step)
                        and not _has_blobless_filter(step)
                        and not _has_sparse_checkout(step)
                        and checkout_ordinal not in allowed_ordinals
                    ):
                        result.issues.append(
                            Issue(
                                workflow=wf.path.name,
                                job=job.name,
                                step=step.ref,
                                message=(
                                    "fetch-depth: 0 without filter: blob:none, sparse-checkout, "
                                    f"or `{ALLOW_MARKER} -- <reason>`"
                                ),
                                file=str(wf.path),
                            )
                        )

                    checkout_ordinal += 1

        return result
