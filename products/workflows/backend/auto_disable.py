import structlog

from posthog.email import EmailMessage, is_email_available
from posthog.exceptions_capture import capture_exception
from posthog.plugins.plugin_server_api import reload_hog_flows_on_workers
from posthog.utils import absolute_uri

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = structlog.get_logger(__name__)

# Human-readable reasons for the terminal Slack errors the CDP hogflow executor reports
# (kept in sync with SLACK_USER_CONFIG_ERRORS in ee/tasks/subscriptions/__init__.py and the
# Node-side classifier in nodejs/src/cdp/services/hogflows/slack-errors.ts).
SLACK_ERROR_DESCRIPTIONS: dict[str, str] = {
    "not_in_channel": "The PostHog Slack app is not a member of the selected channel.",
    "channel_not_found": "The selected Slack channel no longer exists or can't be accessed.",
    "is_archived": "The selected Slack channel has been archived.",
    "account_inactive": "The connected Slack account is inactive.",
    "invalid_auth": "PostHog's Slack authentication is no longer valid.",
    "token_revoked": "PostHog's access to Slack has been revoked.",
    "restricted_action": "A Slack workspace setting is blocking PostHog from posting to this channel.",
    "org_login_required": "PostHog needs to re-authenticate with your Slack organization.",
}

_DEFAULT_SLACK_ERROR_DESCRIPTION = "PostHog can no longer post to the configured Slack channel."


def _slack_error_description(slack_error: str) -> str:
    return SLACK_ERROR_DESCRIPTIONS.get(slack_error, _DEFAULT_SLACK_ERROR_DESCRIPTION)


def disable_hog_flow_for_slack_error(hog_flow: HogFlow, slack_error: str) -> bool:
    """Disable a workflow whose Slack destination hit a terminal user-config error.

    Uses a compare-and-swap on the status so only one of the many invocations failing in the
    same burst performs the disable and sends the owner notification. Returns True when this
    call performed the disable, False when it was already disabled by a concurrent caller.
    """
    # Compare-and-swap: only flip active -> archived once. A 0 rowcount means a racing caller
    # (or the user) already moved it off active, so there's nothing to do and no email to send.
    rowcount = HogFlow.objects.filter(pk=hog_flow.pk, status=HogFlow.State.ACTIVE).update(status=HogFlow.State.ARCHIVED)
    if rowcount == 0:
        logger.info(
            "hog_flow.auto_disable_already_disabled",
            hog_flow_id=str(hog_flow.id),
            team_id=hog_flow.team_id,
            slack_error=slack_error,
        )
        return False

    # .update() bypasses the post_save signal that reloads the CDP workers, so publish the
    # reload explicitly — otherwise workers keep the stale 'active' flow cached and re-fire it.
    reload_hog_flows_on_workers(team_id=hog_flow.team_id, hog_flow_ids=[str(hog_flow.id)])

    logger.warning(
        "hog_flow.auto_disabling",
        hog_flow_id=str(hog_flow.id),
        team_id=hog_flow.team_id,
        slack_error=slack_error,
    )
    # Mirror the UPDATE in memory so callers see the new state without a fresh SELECT.
    hog_flow.status = HogFlow.State.ARCHIVED

    if hog_flow.created_by and hog_flow.created_by.email:
        try:
            send_disabled_notification(hog_flow, slack_error)
        except Exception as e:
            # Disabling is the durable side effect; the email is best-effort. A failure here
            # (SMTP outage, misconfigured self-hosted instance) must not undo the disable.
            capture_exception(e)
            logger.warning(
                "hog_flow.send_disabled_notification_failed",
                hog_flow_id=str(hog_flow.id),
                error=str(e),
                exc_info=True,
            )

    return True


def send_disabled_notification(hog_flow: HogFlow, slack_error: str) -> None:
    if not is_email_available(with_absolute_urls=True):
        return

    display_name = hog_flow.name or "your workflow"
    hog_flow_url = absolute_uri(f"/workflows/{hog_flow.id}/workflow")
    # The compare-and-swap in disable_hog_flow_for_slack_error already guarantees a single send;
    # keying the campaign on updated_at is a belt-and-suspenders dedup against repeat disables.
    campaign_key = f"hog_flow_disabled_{hog_flow.id}_updated_at_{hog_flow.updated_at.timestamp()}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f'PostHog workflow "{display_name}" has been automatically disabled',
        template_name="hog_flow_disabled",
        template_context={
            "hog_flow_name": display_name,
            "hog_flow_url": hog_flow_url,
            "reason": _slack_error_description(slack_error),
        },
    )
    if hog_flow.created_by and hog_flow.created_by.email:
        message.add_recipient(email=hog_flow.created_by.email)
    message.send()
