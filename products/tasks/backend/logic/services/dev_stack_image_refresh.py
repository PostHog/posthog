import re
import uuid
import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Literal

from django.conf import settings
from django.utils import timezone

from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.egress.github.transport import github_request
from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.temporal.common.client import sync_connect

from products.tasks.backend.dev_stack_image_models import DevStackImageTarget
from products.tasks.backend.logic.services.dev_stack_image_state import DevStackImageState
from products.tasks.backend.logic.services.sandbox import SandboxTemplate

logger = logging.getLogger(__name__)


def resolve_repository_sha() -> str:
    installation = GitHubIntegrationBase.app_request("repos/PostHog/posthog/installation", timeout=5)
    installation.raise_for_status()
    installation_id = str(installation.json()["id"])
    token = GitHubIntegrationBase.client_request(
        f"installations/{installation_id}/access_tokens",
        method="POST",
        timeout=5,
        json_body={"repositories": ["posthog"], "permissions": {"contents": "read"}},
    )
    token.raise_for_status()
    response = github_request(
        "GET",
        "https://api.github.com/repos/PostHog/posthog/commits/master",
        source="tasks_dev_stack_image",
        priority=Priority.BATCH,
        installation_id=installation_id,
        headers={"Authorization": f"Bearer {token.json()['token']}"},
        timeout=5,
    )
    response.raise_for_status()
    sha = response.json()["sha"]
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError("Invalid repository revision")
    return sha


def reconcile_dev_stack_image(
    target: DevStackImageTarget, *, trigger: Literal["nightly", "base_changed", "manual"], request_key: str = ""
) -> bool:
    from products.tasks.backend.logic.services.modal_sandbox import resolve_template_base_image_reference

    if not target.enabled:
        return False
    state = DevStackImageState(target.pk)
    if target.auto_refresh:
        if trigger == "nightly":
            request_key = f"nightly:{timezone.now().date().isoformat()}"
        elif trigger == "manual":
            request_key = request_key or f"manual:{uuid.uuid4()}"
        revision = state.begin_observation(request_key)
        try:
            base = resolve_template_base_image_reference(SandboxTemplate.VM_BASE, use_cache=False)
            if not base or re.fullmatch(r"ghcr.io/posthog/posthog-sandbox-vm@sha256:[0-9a-f]{64}", base) is None:
                raise ValueError("The VM base must resolve to an immutable registry digest")
            target.refresh_from_db(using="default")
            recipe_sha = hashlib.sha256(
                (
                    Path(settings.BASE_DIR) / "products/tasks/backend/sandbox/images/bake-posthog-dev-stack.sh"
                ).read_bytes()
            ).hexdigest()
            needs_inputs = (
                target.base_reference != base or target.recipe_sha != recipe_sha or bool(target.pending_request_key)
            )
            repository_sha = resolve_repository_sha() if needs_inputs else target.repository_sha
            state.observe(revision, base, repository_sha, recipe_sha)
        except Exception:
            DevStackImageTarget.objects.using("default").filter(pk=target.pk, observation_revision=revision).update(
                observation_error="Target refresh failed. Retrying the last known target; inspect the server logs."
            )
            logger.exception("dev_stack_image_target_observation_failed")
            if trigger != "base_changed":
                raise
    attempt = state.reconcile()
    if attempt is None:
        return False
    client = sync_connect()
    try:
        handle = asyncio.run(
            client.start_workflow(
                "activate-dev-stack-image",
                str(attempt.id),
                id=f"activate-dev-stack-image-{attempt.id}",
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                task_queue=settings.TASKS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        )
        type(attempt).objects.filter(pk=attempt.id, workflow_run_id="").update(
            workflow_run_id=handle.first_execution_run_id or ""
        )
    except WorkflowAlreadyStartedError:
        pass
    return True
