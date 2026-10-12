import re
from collections.abc import Sequence
from urllib.parse import parse_qs, urlparse

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError, SlackClientError

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.integration import Integration, SlackIntegration
from posthog.slack.formatting import escape_slack_mrkdwn
from posthog.utils import absolute_uri

from products.workflows.backend.facade.contracts import WorkflowRef

SLACK_REQUEST_TIMEOUT_SECONDS = 15
FILE_UPLOAD_SCOPE = "files:write"
SLACK_ERROR_MESSAGES = {
    "not_in_channel": "PostHog is not in this Slack channel. Add it with /invite @PostHog, then share again.",
    "channel_not_found": (
        "PostHog cannot see this Slack channel. If it is private, add PostHog with /invite @PostHog, then share again."
    ),
}
_PERMALINK_PATH = re.compile(r"/archives/(?P<channel>[A-Z0-9]+)/p(?P<ts>\d{7,})/?")
_THREAD_TS = re.compile(r"\d+\.\d+")


class WorkflowPreviewShareError(Exception):
    pass


@frozen
class SlackDestination:
    channel: str
    thread_ts: str | None = None


@frozen
class EmailPreviewImage:
    title: str
    png: bytes


@frozen
class WorkflowPreview:
    note: str
    outline: Sequence[str]
    emails: Sequence[EmailPreviewImage]


def parse_slack_thread_link(link: str) -> SlackDestination | None:
    try:
        parsed = urlparse(link.strip())
    except ValueError:
        return None
    match = _PERMALINK_PATH.fullmatch(parsed.path)
    if not match or not _is_slack_host(parsed.scheme, parsed.hostname):
        return None
    raw_ts = match.group("ts")
    thread_ts = parse_qs(parsed.query).get("thread_ts", [f"{raw_ts[:-6]}.{raw_ts[-6:]}"])[0]
    if not _THREAD_TS.fullmatch(thread_ts):
        return None
    return SlackDestination(channel=match.group("channel"), thread_ts=thread_ts)


def _is_slack_host(scheme: str, hostname: str | None) -> bool:
    return scheme == "https" and hostname is not None and (hostname == "slack.com" or hostname.endswith(".slack.com"))


def find_team_slack_integration(team: Team, integration_id: int) -> Integration | None:
    return Integration.objects.filter(team=team, id=integration_id, kind="slack").first()


def share_workflow_preview_to_slack(
    *,
    integration: Integration,
    workflow: WorkflowRef,
    shared_by: User,
    destination: SlackDestination,
    preview: WorkflowPreview,
) -> None:
    slack = SlackIntegration(integration, source="workflows_preview")
    if preview.emails and slack.missing_scopes({FILE_UPLOAD_SCOPE}):
        raise WorkflowPreviewShareError(
            "This Slack connection cannot upload images. Reconnect Slack to share the emails, or deselect them."
        )
    client = slack.client
    client.timeout = SLACK_REQUEST_TIMEOUT_SECONDS
    try:
        _ensure_sharer_may_post_to(client, integration, shared_by, destination.channel)
        _post_preview(client, destination, _preview_message(workflow, shared_by, preview), preview.emails)
    except SlackApiError as error:
        slack_error = (error.response.get("error") if error.response else None) or "unknown error"
        raise WorkflowPreviewShareError(
            SLACK_ERROR_MESSAGES.get(slack_error, f"Slack did not accept the preview ({slack_error}).")
        ) from error
    except (SlackClientError, OSError) as error:
        raise WorkflowPreviewShareError("Couldn't reach Slack. Try again in a moment.") from error


def _ensure_sharer_may_post_to(client: WebClient, integration: Integration, user: User, channel_id: str) -> None:
    channel = client.conversations_info(channel=channel_id)["channel"]
    if channel.get("is_im") or channel.get("is_mpim"):
        raise WorkflowPreviewShareError("Previews can only be shared to Slack channels, not a direct message")
    if channel.get("is_private") and integration.created_by_id != user.id:
        raise WorkflowPreviewShareError(
            "Only the person who connected this Slack workspace can share to a private channel"
        )


def _post_preview(
    client: WebClient, destination: SlackDestination, message: str, emails: Sequence[EmailPreviewImage]
) -> None:
    if not emails:
        client.chat_postMessage(
            channel=destination.channel,
            thread_ts=destination.thread_ts,
            text=message,
            unfurl_links=False,
            unfurl_media=False,
        )
        return
    client.files_upload_v2(
        channel=destination.channel,
        thread_ts=destination.thread_ts,
        initial_comment=message,
        file_uploads=[
            {"content": email.png, "filename": f"email-{position}.png", "title": email.title}
            for position, email in enumerate(emails, start=1)
        ],
    )


def _preview_message(workflow: WorkflowRef, shared_by: User, preview: WorkflowPreview) -> str:
    workflow_url = absolute_uri(f"/project/{workflow.team_id}/workflows/{workflow.id}/workflow")
    sharer = escape_slack_mrkdwn(shared_by.first_name or shared_by.email)
    sections = [f"{sharer} shared a preview of the workflow *{escape_slack_mrkdwn(workflow.name or 'Untitled')}*"]
    if workflow.description:
        sections.append(f"> {escape_slack_mrkdwn(workflow.description)}")
    if preview.note.strip():
        sections.append(escape_slack_mrkdwn(preview.note.strip()))
    if preview.outline:
        steps = "\n".join(escape_slack_mrkdwn(line) for line in preview.outline)
        sections.append(f"*Steps*\n{steps}")
    if preview.emails:
        sections.append(f"_{_email_count(len(preview.emails))} attached below as rendered previews._")
    sections.append(f"<{workflow_url}|Open the workflow in PostHog>")
    return "\n\n".join(sections)


def _email_count(count: int) -> str:
    return "1 email" if count == 1 else f"{count} emails"
