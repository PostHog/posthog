import logging
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import TaskNotFoundError
from products.tasks.backend.temporal.oauth import create_oauth_access_token
from products.tasks.backend.temporal.process_task.utils import get_github_token

logger = logging.getLogger(__name__)


@dataclass
class ProvisionSandboxInput:
    run_id: str
    task_id: str
    repository: str
    github_integration_id: Optional[int] = None
    snapshot_id: Optional[str] = None


@dataclass
class ProvisionSandboxOutput:
    sandbox_id: str


@activity.defn
@asyncify
def provision_sandbox(input: ProvisionSandboxInput) -> ProvisionSandboxOutput:
    logger.info(f"Provisioning sandbox for cloud session {input.run_id}")

    try:
        task = Task.objects.select_related("created_by", "team").get(id=input.task_id)
    except Task.DoesNotExist as e:
        raise TaskNotFoundError(f"Task {input.task_id} not found", {"task_id": input.task_id}, cause=e)

    github_token = ""
    if input.github_integration_id:
        try:
            github_token = get_github_token(input.github_integration_id) or ""
        except Exception as e:
            logger.warning(f"Failed to get GitHub token: {e}")

    try:
        access_token = create_oauth_access_token(task)
    except Exception as e:
        logger.warning(f"Failed to create OAuth access token: {e}")
        access_token = ""

    config = SandboxConfig(
        name=f"cloud-session-{input.run_id[:8]}",
        template=SandboxTemplate.DEFAULT_BASE,
        snapshot_id=input.snapshot_id,
        ttl_seconds=60 * 30,  # 30 minutes max
        metadata={
            "run_id": input.run_id,
            "task_id": input.task_id,
            "repository": input.repository,
            "type": "cloud_session",
        },
        environment_variables={
            "REDIS_URL": settings.REDIS_URL,
            "POSTHOG_API_URL": settings.SITE_URL,
            "POSTHOG_PERSONAL_API_KEY": access_token,
            "POSTHOG_PROJECT_ID": str(task.team_id),
            "GITHUB_TOKEN": github_token,
            # LLM gateway URL - hardcoded for local dev (TODO: make configurable)
            "LLM_GATEWAY_URL": "http://host.docker.internal:3308/array",
            # Direct Anthropic API key for local dev (bypasses gateway auth)
            "ANTHROPIC_API_KEY": getattr(settings, "ANTHROPIC_API_KEY", ""),
        },
    )

    sandbox = Sandbox.create(config)
    logger.info(f"Sandbox provisioned: {sandbox.id}")

    if input.repository:
        logger.info(f"Cloning repository {input.repository}")
        sandbox.clone_repository(input.repository, github_token)

    return ProvisionSandboxOutput(sandbox_id=sandbox.id)
