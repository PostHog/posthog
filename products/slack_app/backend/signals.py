from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration


@receiver(post_save, sender=UserIntegration)
@receiver(post_delete, sender=UserIntegration)
def invalidate_repo_list_on_user_github_change(sender: Any, instance: UserIntegration, **kwargs) -> None:
    if instance.kind != UserIntegration.IntegrationKind.GITHUB:
        return
    # Deferred: api.py imports the temporal.ai workflows (the whole ee.hogai core) at module scope.
    # This receiver is wired from AppConfig.ready(), so a module-level import would drag that onto
    # every process's startup path.
    from products.slack_app.backend.api import _invalidate_user_repo_list_cache  # noqa: PLC0415

    _invalidate_user_repo_list_cache(instance.user_id)


@receiver(post_save, sender=UserIntegration)
def record_onboarding_github_step_on_personal_connect(
    sender: Any, instance: UserIntegration, created: bool, **kwargs
) -> None:
    """A user's first personal GitHub can finish the GitHub step of the Slack installs they made."""
    if created and instance.kind == UserIntegration.IntegrationKind.GITHUB:
        _dispatch_onboarding_github_step_if_first(
            other_github_connections=UserIntegration.objects.filter(
                user_id=instance.user_id, kind=UserIntegration.IntegrationKind.GITHUB
            ).exclude(id=instance.id),
            slack_installs=Integration.objects.filter(kind="slack", created_by_id=instance.user_id),
        )


@receiver(post_save, sender=Integration)
def record_onboarding_github_step_on_team_connect(sender: Any, instance: Integration, created: bool, **kwargs) -> None:
    """A team's first GitHub installation can finish the GitHub step of the team's Slack installs."""
    if created and instance.kind == "github":
        _dispatch_onboarding_github_step_if_first(
            other_github_connections=Integration.objects.filter(team_id=instance.team_id, kind="github").exclude(
                id=instance.id
            ),
            slack_installs=Integration.objects.filter(kind="slack", team_id=instance.team_id),
        )


def _dispatch_onboarding_github_step_if_first(
    *, other_github_connections: QuerySet, slack_installs: QuerySet[Integration]
) -> None:
    # A later connection of the same kind cannot change the step's outcome, so only the first dispatches.
    if other_github_connections.exists():
        return
    integration_ids = list(slack_installs.values_list("id", flat=True))
    if not integration_ids:
        return
    # Deferred: tasks.py imports api.py, which a module-level import would load from AppConfig.ready().
    from products.slack_app.backend.tasks import record_onboarding_github_step  # noqa: PLC0415

    transaction.on_commit(lambda: record_onboarding_github_step.delay(integration_ids=integration_ids), robust=True)


@receiver(post_save, sender=Integration)
def onboard_slack_inbox_on_install(sender: Any, instance: Integration, created: bool, **kwargs) -> None:
    """Fresh Slack install -> capture ``slack app installed`` and enqueue the #posthog-inbox onboarding
    Temporal workflow on commit (the enqueue runs inline; the workflow itself runs on a Temporal
    worker). Onboarding is gated on ``channels:manage``. Re-auth uses update_or_create
    (created=False), so only first installs are captured and onboard."""
    if not created or instance.kind != "slack":
        return

    # Deferred: keep the import lazy since this receiver is wired from AppConfig.ready().
    from products.slack_app.backend.inbox_channel import has_inbox_scopes  # noqa: PLC0415

    inbox_scopes = has_inbox_scopes(instance)
    # Robust, so a failed capture cannot stop the onboarding callback queued after it.
    transaction.on_commit(lambda: _capture_install(instance, has_inbox_scopes=inbox_scopes), robust=True)
    if not inbox_scopes:
        return

    integration_id = instance.id
    transaction.on_commit(lambda: _start_inbox_onboarding_workflow(integration_id))


def _capture_install(integration: Integration, *, has_inbox_scopes: bool) -> None:
    from products.slack_app.backend.analytics import capture_slack_event  # noqa: PLC0415
    from products.slack_app.backend.onboarding import installer_slack_user_id  # noqa: PLC0415

    capture_slack_event(
        integration,
        "slack app installed",
        slack_user_id=installer_slack_user_id(integration),
        posthog_user=integration.created_by,
        has_inbox_scopes=has_inbox_scopes,
        # Only a workspace's first project connection is a new workspace adopting the app.
        workspace_already_linked=Integration.objects.filter(kind="slack", integration_id=integration.integration_id)
        .exclude(id=integration.id)
        .exists(),
    )


def _start_inbox_onboarding_workflow(integration_id: int) -> None:
    # Deferred imports keep the Temporal stack off the signals (AppConfig.ready) import path.
    import asyncio

    from django.conf import settings

    import structlog
    from temporalio.common import WorkflowIDReusePolicy

    from posthog.temporal.ai.slack_app.posthog_slack_inbox_onboarding import (  # noqa: PLC0415
        PostHogSlackInboxOnboardingWorkflow,
    )
    from posthog.temporal.ai.slack_app.types import PostHogSlackInboxOnboardingInputs  # noqa: PLC0415
    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415

    log = structlog.get_logger(__name__)
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                PostHogSlackInboxOnboardingWorkflow.run,
                PostHogSlackInboxOnboardingInputs(integration_id=integration_id),
                id=f"posthog-slack-inbox-onboarding-{integration_id}",
                task_queue=settings.TASKS_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        )
    except Exception:
        log.warning("slack_app_inbox_onboarding_dispatch_failed", integration_id=integration_id, exc_info=True)
