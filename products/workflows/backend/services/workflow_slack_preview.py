import re
from collections.abc import Sequence
from urllib.parse import parse_qs, urlparse

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.integration import Integration, SlackIntegration
from posthog.slack.formatting import escape_slack_mrkdwn
from posthog.utils import absolute_uri

from products.workflows.backend.facade.contracts import WorkflowRef

SLACK_REQUEST_TIMEOUT_SECONDS = 15
_PERMALINK_PATH = re.compile(r"/archives/(?P<channel>[A-Z0-9]+)/p(?P<ts>\d{7,})")


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
    match = _PERMALINK_PATH.search(parsed.path)
    if not parsed.netloc.endswith("slack.com") or not match:
        return None
    reply_parent_ts = parse_qs(parsed.query).get("thread_ts", [None])[0]
    raw_ts = match.group("ts")
    return SlackDestination(channel=match.group("channel"), thread_ts=reply_parent_ts or f"{raw_ts[:-6]}.{raw_ts[-6:]}")


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
    client = SlackIntegration(integration, source="workflows_preview").client
    client.timeout = SLACK_REQUEST_TIMEOUT_SECONDS
    try:
        _ensure_sharer_may_post_to(client, integration, shared_by, destination.channel)
        _post_preview(client, destination, _preview_message(workflow, shared_by, preview), preview.emails)
    except SlackApiError as error:
        slack_error = (error.response.get("error") if error.response else None) or "unknown error"
        raise WorkflowPreviewShareError(f"Slack did not accept the preview ({slack_error})") from error


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
