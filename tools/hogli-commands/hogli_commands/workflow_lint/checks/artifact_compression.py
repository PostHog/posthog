"""Precompressed artifacts should bypass upload-artifact's outer zlib pass."""

from __future__ import annotations

import re

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Step, Workflow

PRECOMPRESSED_PATH_RE = re.compile(
    r"\.(?:7z|appimage|blockmap|br|bz2|deb|dmg|exe|gz|msi|pkg|rpm|tgz|whl|xz|zip)(?:$|[\s*?}\]])",
    re.IGNORECASE,
)


def _is_artifact_upload(step: Step) -> bool:
    return step.uses is not None and step.uses.lower().startswith("actions/upload-artifact@")


def _includes_precompressed_path(step: Step) -> bool:
    if step.with_ is None:
        return False
    path = step.with_.get("path")
    return isinstance(path, str) and PRECOMPRESSED_PATH_RE.search(path) is not None


def _disables_outer_compression(step: Step) -> bool:
    if step.with_ is None:
        return False
    return step.with_.get("compression-level") in (0, "0")


class ArtifactCompressionCheck(WorkflowCheck):
    id = "WF009-artifact-compression"
    label = "artifact compression"
    description = "precompressed artifact uploads disable redundant outer compression"

    @property
    def fix_hint(self) -> str | None:
        return "Set `compression-level: 0` when an upload-artifact path contains packaged or compressed files."

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for workflow in workflows:
            for job in workflow.jobs:
                for step in job.steps:
                    if (
                        _is_artifact_upload(step)
                        and _includes_precompressed_path(step)
                        and not _disables_outer_compression(step)
                    ):
                        result.issues.append(
                            Issue(
                                workflow=workflow.path.name,
                                job=job.name,
                                step=step.ref,
                                message="precompressed artifact path uses the default zlib compression level",
                                file=str(workflow.path),
                            )
                        )
        return result
