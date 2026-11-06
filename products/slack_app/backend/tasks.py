"""Celery tasks for the Slack app product."""

from typing import Any

from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models import User
from posthog.models.scoping import with_team_scope
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration
from posthog.scoping_audit import skip_team_scope_audit

from products.slack_app.backend.api import (
    REPO_SNAPSHOT_REFRESH_INTERVAL_SECONDS,
    SLACK_INTEGRATION_KIND,
    does_other_region_claim_workspace,
    send_region_proxy_request,
)
from products.slack_app.backend.logic.interview_recruitment import (
    FrustrationInviteRequest,
    linked_posthog_user,
    offer_frustration_invite,
)
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration, with_teams
from products.slack_app.backend.slack_link_unfurl import add_artifact_image_to_unfurl, start_unfurl_charts
from products.slack_app.backend.temporal.types import SlackUnfurlChartRequest


@shared_task(ignore_result=True)
def mirror_slack_message_event(
    *, slack_team_id: str, incoming_host: str, target_url: str, headers: dict[str, str], body: str
) -> None:
    """Deliver an emit-only mirror of a channel message to the other region.

    Runs out of band so the Slack webhook acks within its budget instead of waiting on the claims
    probe and the cross-region POST. No retries: the receiver rejects Slack timestamps older than
    five minutes, and a lost mirror costs the other region one message, which the caller accepts.
    """
    claimed = does_other_region_claim_workspace(
        slack_team_id=slack_team_id,
        kinds=[SLACK_INTEGRATION_KIND],
        incoming_host=incoming_host,
    )
    if not claimed:
        return
    # The body rides as text because Celery serializes arguments to JSON. Slack signs the raw
    # bytes, and the payload is UTF-8 JSON, so the decode/encode round trip is byte-exact.
    send_region_proxy_request(method="POST", target_url=target_url, headers=headers, body=body.encode("utf-8"))


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
# UserIntegration belongs to a user, not a team, so there is no team scope to apply.
@skip_team_scope_audit
def refresh_user_github_repository_cache(*, user_integration_id: str) -> None:
    """Refresh the repo snapshot that a mention served stale.

    The save in `sync_repository_cache` also clears the per-user repo list cache, so the next
    mention reads the new snapshot. Several mentions can schedule this at once; the refresh
    interval makes all but the first one a no-op.
    """
    record = UserIntegration.objects.filter(id=user_integration_id, kind=UserIntegration.IntegrationKind.GITHUB).first()
    if record is None:
        return
    github = UserGitHubIntegration(record, source="slack_app_repo_selection", priority=Priority.NORMAL)
    github.sync_repository_cache(min_refresh_interval_seconds=REPO_SNAPSHOT_REFRESH_INTERVAL_SECONDS)


def _load_integration(integration_id: int, team_id: int) -> WorkspaceIntegration | None:
    try:
        return with_teams([IntegrationManager.slack.oauth.get(team_id, integration_id)])[0]
    except IntegrationNotFound:
        return None


@shared_task(ignore_result=True)
@with_team_scope()
def start_slack_unfurl_charts(
    *,
    team_id: int,
    integration_id: int,
    user_id: int,
    event: dict[str, Any],
    unfurls: dict[str, Any],
    charts: list[dict[str, Any]],
) -> None:
    integration = _load_integration(integration_id, team_id)
    user = User.objects.filter(id=user_id).first()
    if integration is None or user is None:
        return
    start_unfurl_charts(
        integration=integration,
        user=user,
        event=event,
        unfurls=unfurls,
        charts=[SlackUnfurlChartRequest(**chart) for chart in charts],
    )


@shared_task(ignore_result=True)
@with_team_scope()
def add_slack_unfurl_artifact_image(
    *,
    team_id: int,
    integration_id: int,
    user_id: int,
    event: dict[str, Any],
    unfurls: dict[str, Any],
    url: str,
    title: str,
) -> None:
    integration = _load_integration(integration_id, team_id)
    user = User.objects.filter(id=user_id).first()
    if integration is None or user is None:
        return
    add_artifact_image_to_unfurl(
        integration=integration,
        user=user,
        event=event,
        unfurls=unfurls,
        url=url,
        title=title,
    )


@shared_task(ignore_result=True)
@with_team_scope()
def offer_interview_invite_after_reaction(
    *,
    team_id: int,
    integration_id: int,
    slack_user_id: str,
    channel: str,
    thread_ts: str,
    trace_id: str | None,
) -> None:
    integration = _load_integration(integration_id, team_id)
    if integration is None:
        return
    offer_frustration_invite(
        FrustrationInviteRequest(
            integration=integration,
            slack_user_id=slack_user_id,
            posthog_user=linked_posthog_user(integration, slack_user_id),
            channel=channel,
            thread_ts=thread_ts,
            signal="reaction",
            trace_id=trace_id,
        )
    )
