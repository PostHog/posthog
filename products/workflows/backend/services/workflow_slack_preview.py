import re
from collections.abc import Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError, SlackClientError

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.integration import Integration, SlackIntegration
from posthog.slack.formatting import escape_slack_mrkdwn
from posthog.utils import absolute_uri

from products.workflows.backend.facade.contracts import Workflow
from products.workflows.backend.services.workflow_outline import WorkflowOutline, outline_workflow

SLACK_REQUEST_TIMEOUT_SECONDS = 15
MAX_OUTLINE_LINES = 100
FILE_UPLOAD_SCOPE = "files:write"
SLACK_ERROR_MESSAGES = {
    "not_in_channel": "PostHog is not in this Slack channel. Add it with /invite @PostHog, then share again.",
    "channel_not_found": (
        "PostHog cannot see this Slack channel. If it is private, add PostHog with /invite @PostHog, then share again."
    ),
}
IMAGE_EXTENSIONS_BY_SIGNATURE = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg"}
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
    content: bytes


@frozen
class EmailStepImage:
    action_id: str
    content: bytes


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


def image_extension(content: bytes) -> str | None:
    return next(
        (extension for signature, extension in IMAGE_EXTENSIONS_BY_SIGNATURE.items() if content.startswith(signature)),
        None,
    )


def find_team_slack_integration(team: Team, integration_id: int) -> Integration | None:
    return Integration.objects.filter(team=team, id=integration_id, kind="slack").first()


def share_workflow_preview_to_slack(
    *,
    integration: Integration,
    workflow: Workflow,
    shared_by: User,
    destination: SlackDestination,
    note: str,
    email_images: Sequence[EmailStepImage],
) -> None:
    """Post the workflow's outline, as the editor shows it, with the given rendered emails.

    The message text comes from the stored workflow, so a caller only adds its note and an image
    for each of the workflow's own email steps."""
    outline = _outline_of(workflow)
    emails = _attach_to_email_steps(outline, email_images)
    slack = SlackIntegration(integration, source="workflows_preview")
    if emails and slack.missing_scopes({FILE_UPLOAD_SCOPE}):
        raise WorkflowPreviewShareError(
            "This Slack connection cannot upload images. Reconnect Slack to share the emails, or deselect them."
        )
    client = slack.client
    client.timeout = SLACK_REQUEST_TIMEOUT_SECONDS
    try:
        _ensure_sharer_may_post_to(client, integration, shared_by, destination.channel)
        _post_preview(client, destination, _preview_message(workflow, shared_by, note, outline, len(emails)), emails)
    except SlackApiError as error:
        slack_error = (error.response.get("error") if error.response else None) or "unknown error"
        raise WorkflowPreviewShareError(
            SLACK_ERROR_MESSAGES.get(slack_error, f"Slack did not accept the preview ({slack_error}).")
        ) from error
    except (SlackClientError, OSError) as error:
        raise WorkflowPreviewShareError("Couldn't reach Slack. Try again in a moment.") from error


def _outline_of(workflow: Workflow) -> WorkflowOutline:
    staged = workflow.draft or {}
    return outline_workflow(staged.get("actions", workflow.actions), staged.get("edges", workflow.edges))


def _attach_to_email_steps(outline: WorkflowOutline, email_images: Sequence[EmailStepImage]) -> list[EmailPreviewImage]:
    images_by_step: Mapping[str, bytes] = {image.action_id: image.content for image in email_images}
    if not images_by_step.keys() <= {step.action_id for step in outline.email_steps}:
        raise WorkflowPreviewShareError(
            "One of the shared images is not an email of this workflow. Reload the workflow, then share again."
        )
    return [
        EmailPreviewImage(title=step.title, content=images_by_step[step.action_id])
        for step in outline.email_steps
        if step.action_id in images_by_step
    ]


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
            {
                "content": email.content,
                "filename": f"email-{position}.{image_extension(email.content)}",
                "title": email.title,
            }
            for position, email in enumerate(emails, start=1)
        ],
    )


def _preview_message(workflow: Workflow, shared_by: User, note: str, outline: WorkflowOutline, email_count: int) -> str:
    workflow_url = absolute_uri(f"/project/{workflow.team_id}/workflows/{workflow.id}/workflow")
    sharer = escape_slack_mrkdwn(shared_by.first_name or shared_by.email)
    sections = [f"{sharer} shared a preview of the workflow *{escape_slack_mrkdwn(workflow.name or 'Untitled')}*"]
    if workflow.description:
        sections.append(f"> {escape_slack_mrkdwn(workflow.description)}")
    if note.strip():
        sections.append(escape_slack_mrkdwn(note.strip()))
    if outline.lines:
        sections.append(f"*Steps*\n{_steps(outline.lines)}")
    if email_count:
        sections.append(f"_{_email_count(email_count)} attached below as rendered previews._")
    sections.append(f"<{workflow_url}|Open the workflow in PostHog>")
    return "\n\n".join(sections)


def _steps(lines: Sequence[str]) -> str:
    shown = [escape_slack_mrkdwn(line) for line in lines[:MAX_OUTLINE_LINES]]
    hidden = len(lines) - len(shown)
    if hidden:
        shown.append(f"• …and {hidden} more {'step' if hidden == 1 else 'steps'}")
    return "\n".join(shown)


def _email_count(count: int) -> str:
    return "1 email" if count == 1 else f"{count} emails"
