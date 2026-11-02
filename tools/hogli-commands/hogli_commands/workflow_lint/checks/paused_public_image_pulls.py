from __future__ import annotations

import re

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Job, Step, Workflow

PAUSE_VARIABLE = "PUBLIC_IMAGE_PUSH_PAUSED"
PUBLIC_PUSH_INPUTS = ("push-to-ghcr", "push-to-dockerhub")
DOCKER_META_ACTION = "./.github/actions/docker-meta"
PUBLIC_IMAGE_RE = re.compile(r"\b(?:ghcr\.io|docker\.io)/[\w.-]+/[\w.-]+|(?<![\w./-])posthog/[\w.-]+[:@]")
IMAGE_READ_RE = re.compile(
    r"\bdocker\s+(?:image\s+)?(?:pull|run|create)\b|\bimagetools\s+(?:inspect|create)\b|\b(?:crane|skopeo)\s"
)


def _pauses_public_push(step: Step) -> bool:
    if step.uses != DOCKER_META_ACTION or step.with_ is None:
        return False
    return any(PAUSE_VARIABLE in str(step.with_.get(name, "")) for name in PUBLIC_PUSH_INPUTS)


def _step_strings(step: Step) -> list[str]:
    if step.run is None or not IMAGE_READ_RE.search(step.run):
        return []
    env = step.raw.get("env")
    return [step.run, *(str(value) for value in env.values())] if isinstance(env, dict) else [step.run]


def _public_image_refs(step: Step) -> list[str]:
    return sorted({match.group(0) for value in _step_strings(step) for match in PUBLIC_IMAGE_RE.finditer(value)})


def _job_pauses_public_push(job: Job) -> bool:
    return any(_pauses_public_push(step) for step in job.steps)


class PausedPublicImagePullsCheck(WorkflowCheck):
    id = "WF014-paused-public-image-pulls"
    label = "paused public image pulls"
    description = f"jobs that can pause public image pushes ({PAUSE_VARIABLE}) never read images from public registries"

    @property
    def fix_hint(self) -> str | None:
        return (
            f"While {PAUSE_VARIABLE} is set the public tags are never pushed, so this step fails. "
            "Reference the image in ECR by digest instead, e.g. "
            "`${{ steps.docker-meta.outputs.ecr-registry }}/<repository>@<digest>`."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            for job in wf.jobs:
                if not _job_pauses_public_push(job):
                    continue
                for step in job.steps:
                    if step.uses == DOCKER_META_ACTION:
                        continue
                    for ref in _public_image_refs(step):
                        result.issues.append(
                            Issue(
                                workflow=wf.path.name,
                                job=job.name,
                                step=step.ref,
                                message=f"reads public image `{ref}`, which is absent while {PAUSE_VARIABLE} is set",
                                file=str(wf.path),
                            )
                        )
        return result
