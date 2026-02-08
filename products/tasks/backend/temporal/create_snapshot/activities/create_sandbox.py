from dataclasses import dataclass

from django.conf import settings

from temporalio import activity

from posthog.models import Integration
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.oauth import create_oauth_access_token_for_user
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.utils import get_github_token

from ..utils import get_sandbox_name_for_snapshot
from .get_snapshot_context import SnapshotContext


@dataclass
class CreateSandboxInput:
    context: SnapshotContext


@dataclass
class CreateSandboxOutput:
    sandbox_id: str


@activity.defn
@asyncify
def create_sandbox(input: CreateSandboxInput) -> CreateSandboxOutput:
    ctx = input.context

    with log_activity_execution(
        "create_sandbox",
        **ctx.to_log_context(),
    ):
        github_token = get_github_token(ctx.github_integration_id) or ""

        integration = Integration.objects.select_related("created_by").get(id=ctx.github_integration_id)
        access_token = create_oauth_access_token_for_user(integration.created_by, ctx.team_id)

        environment_variables = {
            "GITHUB_TOKEN": github_token,
            "POSTHOG_PERSONAL_API_KEY": access_token,
            "POSTHOG_API_URL": settings.SITE_URL,
            "POSTHOG_PROJECT_ID": str(ctx.team_id),
        }

        config = SandboxConfig(
            name=get_sandbox_name_for_snapshot(ctx.github_integration_id, ctx.repository),
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables=environment_variables,
            snapshot_id=None,
            metadata={"purpose": "snapshot_creation"},
        )

        sandbox = Sandbox.create(config)

        activity.logger.info(f"Created sandbox {sandbox.id} for snapshot creation")

        return CreateSandboxOutput(sandbox_id=sandbox.id)
