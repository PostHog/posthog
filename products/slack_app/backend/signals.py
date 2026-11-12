from typing import Any

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.integrations import IntegrationRecord
from posthog.integrations.lifecycle import sdk_runs_hooks
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.services.workspace_integrations import (
    WorkspaceIntegration,
    with_teams,
    workspace_integrations,
)


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


@receiver(post_save, sender="posthog.Integration")
def onboard_slack_inbox_on_install(sender: Any, instance: WorkspaceIntegration, created: bool, **kwargs) -> None:
    """Fresh Slack install -> capture ``slack app installed`` and enqueue the #posthog-inbox onboarding
    Temporal workflow on commit (the enqueue runs inline; the workflow itself runs on a Temporal
    worker), which also starts the installer's onboarding thread. An install without
    ``channels:manage``, and a re-auth (update_or_create, so created=False), start the installer's
    onboarding thread directly. Its stored state keeps it from running twice."""
    # The SDK calls `onboard_slack_inbox_on_saved` itself. This receiver is for the writers that do not
    # use the SDK yet, such as the OAuth callback.
    if instance.kind != "slack" or sdk_runs_hooks():
        return
    _onboard_slack_inbox(instance, created=created)


def onboard_slack_inbox_on_saved(row: IntegrationRecord, *, created: bool, config_changed: bool) -> None:
    # A write that leaves the config alone, such as an `errors` update, is not an install or a re-auth.
    if row.kind != "slack" or not (created or config_changed):
        return
    _onboard_slack_inbox(with_teams([row])[0], created=created)


def _onboard_slack_inbox(instance: WorkspaceIntegration, *, created: bool) -> None:
    if created:
        # Deferred: keep the import lazy since this receiver is wired from AppConfig.ready().
        from products.slack_app.backend.inbox_channel import has_inbox_scopes  # noqa: PLC0415

        inbox_scopes = has_inbox_scopes(instance)
        # Robust, so a failed capture cannot stop the onboarding callback queued after it.
        transaction.on_commit(lambda: _capture_install(instance, has_inbox_scopes=inbox_scopes), robust=True)
        if inbox_scopes:
            team_id, integration_id = instance.team_id, instance.id
            transaction.on_commit(lambda: _start_inbox_onboarding_workflow(team_id, integration_id))
            return

    transaction.on_commit(lambda: _start_installer_onboarding(instance), robust=True)


def _start_installer_onboarding(integration: WorkspaceIntegration) -> None:
    from products.slack_app.backend.logic.onboarding.dispatch import request_onboarding  # noqa: PLC0415
    from products.slack_app.backend.onboarding import installer_slack_user_id  # noqa: PLC0415

    installer = installer_slack_user_id(integration)
    if installer:
        request_onboarding(integration, installer, may_start=True)


def _capture_install(integration: WorkspaceIntegration, *, has_inbox_scopes: bool) -> None:
    from products.slack_app.backend.analytics import capture_slack_event  # noqa: PLC0415
    from products.slack_app.backend.onboarding import installer_slack_user_id  # noqa: PLC0415

    capture_slack_event(
        integration,
        "slack app installed",
        slack_user_id=installer_slack_user_id(integration),
        posthog_user=User.objects.filter(id=integration.created_by_id).first(),
        has_inbox_scopes=has_inbox_scopes,
        # Only a workspace's first project connection is a new workspace adopting the app.
        workspace_already_linked=any(
            row.id != integration.id for row in workspace_integrations(integration.integration_id)
        ),
    )


def _start_inbox_onboarding_workflow(team_id: int, integration_id: int) -> None:
    # Deferred imports keep the Temporal stack off the signals (AppConfig.ready) import path.
    import asyncio

    from django.conf import settings

    import structlog
    from temporalio.common import WorkflowIDReusePolicy

    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415

    from products.slack_app.backend.temporal.posthog_slack_inbox_onboarding import (  # noqa: PLC0415
        PostHogSlackInboxOnboardingWorkflow,
    )
    from products.slack_app.backend.temporal.types import PostHogSlackInboxOnboardingInputs  # noqa: PLC0415

    log = structlog.get_logger(__name__)
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                PostHogSlackInboxOnboardingWorkflow.run,
                PostHogSlackInboxOnboardingInputs(team_id=team_id, integration_id=integration_id),
                id=f"posthog-slack-inbox-onboarding-{integration_id}",
                task_queue=settings.TASKS_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        )
    except Exception:
        log.warning("slack_app_inbox_onboarding_dispatch_failed", integration_id=integration_id, exc_info=True)
