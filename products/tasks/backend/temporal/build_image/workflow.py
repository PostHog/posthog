import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import (
    ImageBuildActivityInput,
    MarkImageBuildFailedInput,
    build_and_publish_image,
    mark_image_build_failed,
    scan_image_spec,
)


@dataclass
class BuildSandboxImageInput:
    image_id: str
    team_id: int


@dataclass
class BuildSandboxImageOutput:
    success: bool
    modal_image_name: Optional[str] = None
    error: Optional[str] = None


@workflow.defn(name="build-sandbox-image")
class BuildSandboxImageWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> BuildSandboxImageInput:
        loaded = json.loads(inputs[0])
        return BuildSandboxImageInput(image_id=loaded["image_id"], team_id=loaded["team_id"])

    @workflow.run
    async def run(self, input: BuildSandboxImageInput) -> BuildSandboxImageOutput:
        activity_input = ImageBuildActivityInput(image_id=input.image_id, team_id=input.team_id)

        try:
            scan = await workflow.execute_activity(
                scan_image_spec,
                activity_input,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if not scan.passed:
                return BuildSandboxImageOutput(success=False, error="Security scan failed")

            modal_image_name = await workflow.execute_activity(
                build_and_publish_image,
                activity_input,
                start_to_close_timeout=timedelta(minutes=45),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            return BuildSandboxImageOutput(success=True, modal_image_name=modal_image_name)

        except Exception as e:
            await workflow.execute_activity(
                mark_image_build_failed,
                MarkImageBuildFailedInput(image_id=input.image_id, team_id=input.team_id, error=str(e)),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return BuildSandboxImageOutput(success=False, error=str(e))
