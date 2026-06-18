from typing import Any

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration


@receiver(post_save, sender=UserIntegration)
@receiver(post_delete, sender=UserIntegration)
def invalidate_repo_list_on_user_github_change(sender: Any, instance: UserIntegration, **kwargs) -> None:
    if instance.kind != UserIntegration.IntegrationKind.GITHUB:
        return
    # Deferred: products.slack_app.backend.api imports posthog.temporal.ai workflows at module
    # scope, which pulls the whole ee.hogai chat-agent core. This receiver is wired from
    # AppConfig.ready(), so a module-level import would drag the AI core into every process's
    # startup. The cache helper is only needed when a GitHub integration actually changes.
    from products.slack_app.backend.api import _invalidate_user_repo_list_cache  # noqa: PLC0415

    _invalidate_user_repo_list_cache(instance.user_id)


@receiver(post_save, sender=Integration)
def onboard_slack_inbox_on_install(sender: Any, instance: Integration, created: bool, **kwargs) -> None:
    """Fresh Slack install -> start the #posthog-inbox onboarding Temporal workflow, off the request
    thread. Gated on the install having ``channels:manage`` (the scope the onboarding needs), so it's
    on for every scoped install. Re-auth uses update_or_create (created=False), so only first installs
    onboard."""
    if not created or instance.kind != "slack":
        return

    # Deferred: inbox_channel is light, but keep the import lazy since this receiver is wired from
    # AppConfig.ready(). The scope check is a cheap in-memory read of the granted scopes (no I/O).
    from products.slack_app.backend.inbox_channel import has_inbox_scopes  # noqa: PLC0415

    if not has_inbox_scopes(instance):
        return

    integration_id = instance.id
    transaction.on_commit(lambda: _start_inbox_onboarding_workflow(integration_id))


def _start_inbox_onboarding_workflow(integration_id: int) -> None:
    # Deferred imports keep the Temporal stack off the signals (AppConfig.ready) import path.
    import asyncio

    from django.conf import settings

    import structlog
    from temporalio.common import WorkflowIDReusePolicy

    from posthog.temporal.ai.posthog_slack_inbox_onboarding import (  # noqa: PLC0415
        PostHogSlackInboxOnboardingInputs,
        PostHogSlackInboxOnboardingWorkflow,
    )
    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415

    log = structlog.get_logger(__name__)
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                PostHogSlackInboxOnboardingWorkflow.run,
                PostHogSlackInboxOnboardingInputs(integration_id=integration_id),
                id=f"posthog-slack-inbox-onboarding-{integration_id}",
                task_queue=settings.MAX_AI_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        )
    except Exception:
        log.warning("slack_inbox_onboarding_dispatch_failed", integration_id=integration_id, exc_info=True)
