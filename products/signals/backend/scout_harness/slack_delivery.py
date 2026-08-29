from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

from django.conf import settings

import structlog
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse, WebClient

from posthog.dataclasses import frozen
from posthog.models.integration import Integration, SlackIntegration
from posthog.redis import get_client

from products.signals.backend.models import SignalReport, SignalScoutEmission, SignalScoutRun
from products.signals.backend.scout_harness.slack_charts import (
    ChartRenderBudget,
    build_scout_report_chart_blocks,
    has_chart_blocks,
    new_chart_render_budget,
    strip_chart_blocks,
)
from products.signals.backend.slack_formatting import (
    chunk_slack_mrkdwn,
    escape_slack_mrkdwn,
    markdown_to_slack_mrkdwn,
    slack_channel_id_from_target,
    split_markdown_by_headings,
    strip_chart_references,
    truncate_slack_section,
)

logger = structlog.get_logger(__name__)

_PERMANENT_SLACK_ERROR_CODES = frozenset(
    {
        "account_inactive",
        "channel_not_found",
        "ekm_access_denied",
        "invalid_auth",
        "is_archived",
        "missing_scope",
        "not_authed",
        "not_in_channel",
        "org_login_required",
        "restricted_action",
        "token_revoked",
    }
)

# Slack fetches every `image_url` itself while it renders the message, and rejects the whole message
# with one of these when it cannot reach one. Neither code is permanent, so a chart Slack cannot
# fetch would otherwise retry and then drop a report that used to post as text.
_BLOCK_REJECTION_ERROR_CODES = frozenset({"invalid_blocks", "invalid_blocks_format"})

ScoutSlackOutputType = Literal["finding", "report"]

# A report only reaches Slack while it is surfaced. Checked both before enqueue and again just
# before posting, since chart rendering can hold the worker long enough for the report to change.
DELIVERABLE_REPORT_STATUSES = frozenset((SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT))

# Bound on the note snapshot a note-only edit carries through the Celery payload. Slack shows at
# most SLACK_SECTION_TEXT_MAX_LEN characters after conversion, so anything past this headroom is
# never rendered; the report keeps the full note either way.
MAX_SLACK_NOTE_SNAPSHOT_LEN = 6000

# Posted as an in-thread reply under every scout Slack message, inviting @PostHog follow-ups.
_SCOUT_SLACK_REPLY_TEXT = "💬 If you have questions, reply in this thread and mention *`@PostHog`*!"


@dataclass(frozen=True)
class ScoutSlackDestination:
    integration_id: int
    channel: str
    thread_reports: bool = False


class ScoutSlackPermanentDeliveryError(RuntimeError):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def get_scout_slack_destination(output_destinations: object) -> ScoutSlackDestination | None:
    """Return an active Slack destination from persisted config, tolerating malformed legacy data."""
    if not isinstance(output_destinations, dict):
        return None
    slack = output_destinations.get("slack")
    if not isinstance(slack, dict):
        return None
    integration_id = slack.get("integration_id")
    channel = slack.get("channel")
    if not isinstance(integration_id, int) or isinstance(integration_id, bool) or integration_id < 1:
        return None
    if not isinstance(channel, str) or not channel.strip():
        return None
    return ScoutSlackDestination(
        integration_id=integration_id,
        channel=channel.strip(),
        thread_reports=slack.get("thread_reports") is True,
    )


def slack_api_error_code(exc: SlackApiError) -> str | None:
    error_code = exc.response.get("error") if exc.response else None
    return error_code if isinstance(error_code, str) else None


def _post_scout_slack_reply(
    client: object,
    *,
    channel_id: str,
    thread_ts: object,
    scout_team_id: int,
    integration_team_id: int,
) -> None:
    """Invite @PostHog follow-ups when the Slack connection uses the scout's environment.

    Best-effort and non-blocking: the scout message itself has already been delivered, so a failed
    or missing follow-up never fails the delivery (and so never re-posts the parent on retry).
    """
    if integration_team_id != scout_team_id:
        logger.info(
            "scout_slack_followup_reply_skipped_environment_mismatch",
            scout_team_id=scout_team_id,
            integration_team_id=integration_team_id,
            channel=channel_id,
        )
        return
    if not isinstance(thread_ts, str) or not thread_ts:
        return
    try:
        client.chat_postMessage(  # type: ignore[attr-defined]
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=[{"type": "context", "elements": [{"type": "mrkdwn", "text": _SCOUT_SLACK_REPLY_TEXT}]}],
            text=_SCOUT_SLACK_REPLY_TEXT,
            unfurl_links=False,
            unfurl_media=False,
        )
    except Exception:
        # Swallow everything (not just SlackApiError): a transport-level failure here must never
        # fail the task and retry the already-delivered parent message.
        logger.warning("scout_slack_followup_reply_failed", channel=channel_id, exc_info=True)


def _prettify_scout_name(skill_name: str) -> str:
    cleaned = skill_name.removeprefix("signals-scout-").replace("-", " ").replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Scout"


def _slack_integration_for_project(*, integration_id: int, project_id: int) -> Integration:
    integration = Integration.objects.filter(
        id=integration_id,
        team__project_id=project_id,
        kind=Integration.IntegrationKind.SLACK,
    ).first()
    if integration is None:
        raise ScoutSlackPermanentDeliveryError(
            "The configured Slack integration no longer exists on this project",
            error_code="integration_not_found",
        )
    return integration


def _slack_channel_id(channel: str) -> str:
    channel_id = slack_channel_id_from_target(channel)
    if not channel_id:
        raise ScoutSlackPermanentDeliveryError(
            "The configured Slack channel is empty",
            error_code="channel_missing",
        )
    return channel_id


def build_scout_slack_message(emission: SignalScoutEmission) -> tuple[list[dict], str]:
    """Render a direct scout finding with the same safe Markdown conversion as inbox signals."""
    scout_name = _prettify_scout_name(emission.scout_run.skill_name)
    blocks: list[dict] = [
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*Scout · {escape_slack_mrkdwn(scout_name)}*"}],
        }
    ]

    rendered_description = truncate_slack_section(markdown_to_slack_mrkdwn(emission.description.strip()))
    if rendered_description:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": rendered_description}})

    details: list[str] = []
    if emission.severity:
        details.append(escape_slack_mrkdwn(emission.severity))
    details.append(f"{round(emission.confidence * 100)}% confidence")
    if emission.tags:
        safe_tags = [escape_slack_mrkdwn(str(tag)).replace("`", "'") for tag in emission.tags[:5]]
        details.append(" ".join(f"`{tag}`" for tag in safe_tags))
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(details)}]})

    skill_segment = quote(emission.scout_run.skill_name, safe="")
    finding_segment = quote(emission.finding_id, safe="")
    finding_url = (
        f"{settings.SITE_URL.rstrip('/')}/project/{emission.team_id}/inbox/scouts/{skill_segment}/{finding_segment}"
    )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View signal in PostHog"},
                    "url": finding_url,
                }
            ],
        }
    )

    first_line = emission.description.strip().splitlines()[0] if emission.description.strip() else "New signal"
    fallback = f"Scout · {escape_slack_mrkdwn(scout_name)}: {escape_slack_mrkdwn(first_line[:200])}"
    return blocks, fallback


def post_scout_emission_to_slack(
    emission: SignalScoutEmission,
    *,
    integration_id: int,
    channel: str,
) -> None:
    integration = _slack_integration_for_project(
        integration_id=integration_id,
        project_id=emission.team.project_id,
    )
    channel_id = _slack_channel_id(channel)

    blocks, fallback = build_scout_slack_message(emission)
    client = SlackIntegration(integration).client
    try:
        response = client.chat_postMessage(
            channel=channel_id,
            blocks=blocks,
            text=fallback,
            client_msg_id=str(emission.id),
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError as exc:
        error_code = slack_api_error_code(exc)
        if error_code in _PERMANENT_SLACK_ERROR_CODES:
            raise ScoutSlackPermanentDeliveryError(
                f"Slack rejected the scout finding with {error_code}",
                error_code=error_code,
            ) from exc
        raise

    _post_scout_slack_reply(
        client,
        channel_id=channel_id,
        thread_ts=response.get("ts"),
        scout_team_id=emission.team_id,
        integration_team_id=integration.team_id,
    )


def _report_header(report: SignalReport) -> str:
    title = " ".join((report.title or "").split()) or "New scout report"
    return title if len(title) <= 150 else title[:147].rstrip() + "..."


def _report_link_block(report: SignalReport) -> dict:
    report_url = f"{settings.SITE_URL.rstrip('/')}/project/{report.team_id}/inbox/reports/{report.id}"
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View report in PostHog"},
                "url": report_url,
            }
        ],
    }


def build_scout_report_slack_message(
    report: SignalReport,
    run: SignalScoutRun,
    *,
    delivery_id: str | None = None,
    render_budget: ChartRenderBudget | None = None,
) -> tuple[list[dict], str]:
    scout_name = _prettify_scout_name(run.skill_name)
    header = _report_header(report)
    blocks: list[dict] = [
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*Scout · {escape_slack_mrkdwn(scout_name)}*"}],
        },
        {"type": "header", "text": {"type": "plain_text", "text": header}},
    ]

    # Chart links in the prose still reduce to their label; the charts themselves follow the prose
    # as image blocks, the way the inbox places charts the summary doesn't reference inline.
    summary_text = strip_chart_references((report.summary or "").strip())
    rendered_summary = truncate_slack_section(markdown_to_slack_mrkdwn(summary_text))
    if rendered_summary:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": rendered_summary}})

    # `render_budget` shares one render allowance across a delivery's initial build and any rebuild.
    blocks.extend(build_scout_report_chart_blocks(report, run, delivery_id=delivery_id, budget=render_budget))
    blocks.append(_report_link_block(report))
    fallback = f"Scout · {escape_slack_mrkdwn(scout_name)}: {escape_slack_mrkdwn(header[:200])}"
    return blocks, fallback


def _report_summary_chunks(report: SignalReport) -> list[str]:
    """Convert the report summary to mrkdwn and split it into one chunk per heading section.

    Called only for a threaded delivery. The first chunk leads the channel and each later one
    becomes a reply, so the thread mirrors the report's outline at any length. Length is not the
    test: a typical digest fits inside one Slack section, so a length test leaves it as one wall of
    text. A summary with no headings has no seam and stays one chunk. A section too long for one
    Slack section is hard-chunked on its line ends. The split runs after `strip_chart_references`
    so a chart link never straddles two messages."""
    summary_text = strip_chart_references((report.summary or "").strip())
    chunks: list[str] = []
    for segment in split_markdown_by_headings(summary_text):
        rendered_segment = markdown_to_slack_mrkdwn(segment.strip())
        if not rendered_segment:
            continue
        chunks.extend(chunk_slack_mrkdwn(rendered_segment))
    return chunks


# A content edit made through the scout's edit tool enqueues a fresh full delivery of the report.
# The latest such delivery is recorded so an older one can yield to it, instead of both posting the
# same edited report. Scoped to the destination as well as the report: two scouts editing one report
# into different channels are not competing, and a report-only marker would let either silence the
# other's channel entirely.
_LATEST_REPORT_DELIVERY_TTL_SECONDS = 24 * 60 * 60


def _latest_report_delivery_key(report_id: str, integration_id: int, channel: str) -> str:
    # The resolved channel id, so two configs naming one channel differently share a marker.
    channel_id = slack_channel_id_from_target(channel)
    return f"signals_scout:slack_report_latest_delivery:{report_id}:{integration_id}:{channel_id}"


def _decoded_marker(latest: object) -> str | None:
    if latest is None:
        return None
    return latest.decode() if isinstance(latest, bytes) else str(latest)


def mark_latest_scout_report_delivery(report_id: str, delivery_id: str, integration_id: int, channel: str) -> None:
    try:
        get_client().set(
            _latest_report_delivery_key(report_id, integration_id, channel),
            delivery_id,
            ex=_LATEST_REPORT_DELIVERY_TTL_SECONDS,
        )
    except Exception:
        logger.warning("signals_scout.slack_report_latest_delivery_mark_failed", report_id=report_id, exc_info=True)


def clear_latest_scout_report_delivery(report_id: str, delivery_id: str, integration_id: int, channel: str) -> None:
    """Drop this delivery's claim on the report, for an enqueue that never reached the broker.

    A marker naming a task that will never run would silence every later delivery of the report for
    the marker's whole TTL. Only clears a marker still holding this delivery's id, so a newer claim
    written in between survives; losing that race costs a duplicate message, never the report."""
    try:
        client = get_client()
        key = _latest_report_delivery_key(report_id, integration_id, channel)
        if _decoded_marker(client.get(key)) == delivery_id:
            client.delete(key)
    except Exception:
        logger.warning("signals_scout.slack_report_latest_delivery_clear_failed", report_id=report_id, exc_info=True)


def _newer_report_delivery_queued(report_id: str, delivery_id: str, integration_id: int, channel: str) -> bool:
    """Fails open: an unreadable marker means post, since a duplicate message beats a lost report.

    The decode is inside the guard on purpose: a marker holding bytes that are not UTF-8 must read as
    absent, not raise into the delivery task, which would retry and then drop the report."""
    try:
        latest_id = _decoded_marker(get_client().get(_latest_report_delivery_key(report_id, integration_id, channel)))
    except Exception:
        logger.warning("signals_scout.slack_report_latest_delivery_read_failed", report_id=report_id, exc_info=True)
        return False
    if latest_id is None:
        return False
    return latest_id != delivery_id


@frozen
class ScoutReportThreadMessages:
    """A report delivery's Slack messages: the channel lead plus its ordered thread replies.

    An unthreaded delivery has no replies."""

    lead_blocks: list[dict]
    fallback: str
    reply_blocks: list[list[dict]]


def build_scout_report_thread_slack_messages(
    report: SignalReport,
    run: SignalScoutRun,
    *,
    delivery_id: str | None = None,
    render_budget: ChartRenderBudget | None = None,
) -> ScoutReportThreadMessages:
    """Render a report as a channel lead plus one reply per remaining summary chunk.

    The lead carries the scout name, the report title, the first summary chunk, the charts, and the
    report link. Every later chunk becomes a threaded reply, so the channel shows a short lead and
    the thread holds the report's sections in order, with nothing clipped at the section cap. A
    summary that opens with a heading puts that first section in the lead, so the channel never
    shows a title-only stub."""
    scout_name = _prettify_scout_name(run.skill_name)
    header = _report_header(report)
    lead_blocks: list[dict] = [
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*Scout · {escape_slack_mrkdwn(scout_name)}*"}],
        },
        {"type": "header", "text": {"type": "plain_text", "text": header}},
    ]

    chunks = _report_summary_chunks(report)
    if chunks:
        lead_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunks[0]}})
    # Charts ride the lead rather than a reply: the lead is the message the channel sees, and the
    # replies only carry the summary's tail for anyone who opens the thread.
    lead_blocks.extend(build_scout_report_chart_blocks(report, run, delivery_id=delivery_id, budget=render_budget))
    lead_blocks.append(_report_link_block(report))

    reply_blocks = [[{"type": "section", "text": {"type": "mrkdwn", "text": chunk}}] for chunk in chunks[1:]]
    fallback = f"Scout · {escape_slack_mrkdwn(scout_name)}: {escape_slack_mrkdwn(header[:200])}"
    return ScoutReportThreadMessages(lead_blocks=lead_blocks, fallback=fallback, reply_blocks=reply_blocks)


def build_scout_report_note_slack_message(
    report: SignalReport, run: SignalScoutRun, note: str
) -> tuple[list[dict], str]:
    """Render a note-only report edit as the note itself, framed as an update.

    A note-only edit leaves the title and summary the report message shows unchanged, so re-sending
    `build_scout_report_slack_message` would post a message identical to the one already in the
    channel. The note is what's new, so that's what gets delivered."""
    scout_name = _prettify_scout_name(run.skill_name)
    header = _report_header(report)
    blocks: list[dict] = [
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*Scout · {escape_slack_mrkdwn(scout_name)}* added a note to an existing report",
                }
            ],
        },
        {"type": "header", "text": {"type": "plain_text", "text": header}},
    ]

    note_text = strip_chart_references(note.strip())
    rendered_note = truncate_slack_section(markdown_to_slack_mrkdwn(note_text))
    if rendered_note:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": rendered_note}})

    blocks.append(_report_link_block(report))
    fallback = f"Scout · {escape_slack_mrkdwn(scout_name)} added a note to: {escape_slack_mrkdwn(header[:200])}"
    return blocks, fallback


def _post_scout_report_thread_replies(
    client: object,
    *,
    channel_id: str,
    thread_ts: object,
    delivery_id: str,
    reply_blocks: list[list[dict]],
    fallback: str,
) -> None:
    """Post the remaining summary chunks as threaded replies under an already-delivered lead.

    Best-effort per reply: the lead already carries the report link, so a failed chunk logs and the
    delivery still succeeds rather than re-posting the lead on retry."""
    if not isinstance(thread_ts, str) or not thread_ts:
        return
    for index, blocks in enumerate(reply_blocks):
        try:
            client.chat_postMessage(  # type: ignore[attr-defined]
                channel=channel_id,
                thread_ts=thread_ts,
                blocks=blocks,
                text=fallback,
                client_msg_id=f"{delivery_id}:{index}",
                unfurl_links=False,
                unfurl_media=False,
            )
        except Exception:
            logger.warning(
                "scout_slack_report_thread_reply_failed",
                channel=channel_id,
                delivery_id=delivery_id,
                chunk_index=index,
                exc_info=True,
            )


def _post_scout_report_lead_message(
    client: WebClient,
    *,
    channel_id: str,
    delivery_id: str,
    blocks: list[dict],
    fallback: str,
) -> SlackResponse:
    """Post the report's channel message, and post it again without the charts if Slack refuses them.

    A chart Slack cannot fetch takes the whole message down, so on any deployment Slack cannot reach
    a chart-bearing report would never arrive. The prose and the report link are the message; the
    charts are the extra, and the report still draws every one of them in the inbox."""

    def _post(message_blocks: list[dict]) -> SlackResponse:
        return client.chat_postMessage(
            channel=channel_id,
            blocks=message_blocks,
            text=fallback,
            client_msg_id=delivery_id,
            unfurl_links=False,
            unfurl_media=False,
        )

    try:
        return _post(blocks)
    except SlackApiError as exc:
        error_code = slack_api_error_code(exc)
        if error_code not in _BLOCK_REJECTION_ERROR_CODES or not has_chart_blocks(blocks):
            raise
        logger.warning(
            "signals_scout.slack_report_charts_rejected",
            channel=channel_id,
            delivery_id=delivery_id,
            error_code=error_code,
        )
        return _post(strip_chart_blocks(blocks))


def post_scout_report_to_slack(
    report: SignalReport,
    run: SignalScoutRun,
    *,
    delivery_id: str,
    integration_id: int,
    channel: str,
    edit_note: str | None = None,
    thread_reports: bool = False,
) -> None:
    if report.team_id != run.team_id:
        raise ScoutSlackPermanentDeliveryError(
            "The scout run does not own the configured report",
            error_code="output_team_mismatch",
        )

    integration = _slack_integration_for_project(
        integration_id=integration_id,
        project_id=report.team.project_id,
    )
    channel_id = _slack_channel_id(channel)

    # Threading applies to a full report only: a note edit is short and posts as a single update.
    threaded = thread_reports and edit_note is None

    # Shared across the initial build and any rebuild so both draw from one render allowance, rather
    # than the rebuild getting a fresh one (which would let one delivery spend two budgets).
    render_budget = new_chart_render_budget()

    def _build_report_message() -> ScoutReportThreadMessages:
        # A note-only edit renders the passed-in note; every other delivery renders live report content.
        if edit_note is not None:
            note_blocks, note_fallback = build_scout_report_note_slack_message(report, run, edit_note)
            return ScoutReportThreadMessages(lead_blocks=note_blocks, fallback=note_fallback, reply_blocks=[])
        if threaded:
            return build_scout_report_thread_slack_messages(
                report, run, delivery_id=delivery_id, render_budget=render_budget
            )
        report_blocks, report_fallback = build_scout_report_slack_message(
            report, run, delivery_id=delivery_id, render_budget=render_budget
        )
        return ScoutReportThreadMessages(lead_blocks=report_blocks, fallback=report_fallback, reply_blocks=[])

    # Building the message renders the report's charts, which can hold the worker for the render
    # budget. Re-read the report after every build and before posting, since an edit in that window
    # can unsurface it (must not post at all) or change its content (the built blocks no longer match
    # the report). On a content change, rebuild from the current report and re-check again — not
    # every edit path enqueues a replacement delivery (the inbox PATCH,
    # `SignalReportViewSet.partial_update`, doesn't), so dropping the message would lose it. The
    # loop is bounded to one rebuild: a further edit racing the rebuild is ordinary last-writer
    # timing, and unchanged charts are reused from the render cache, so a rebuild only re-renders
    # charts the edit actually changed. A note-only message renders the passed-in note, not live
    # content, so it has no revision to guard and never rebuilds.
    messages = ScoutReportThreadMessages(lead_blocks=[], fallback="", reply_blocks=[])
    for _ in range(2):
        content_revision = None if edit_note is not None else report.updated_at
        messages = _build_report_message()
        try:
            report.refresh_from_db()
        except SignalReport.DoesNotExist:
            logger.info("signals_scout.slack_delivery_report_deleted_after_render", report_id=str(report.id))
            return
        if report.status not in DELIVERABLE_REPORT_STATUSES:
            logger.info(
                "signals_scout.slack_delivery_report_not_surfaced_after_render",
                report_id=str(report.id),
                report_status=report.status,
            )
            return
        if content_revision is None or report.updated_at == content_revision:
            break
        logger.info("signals_scout.slack_delivery_report_rebuilt_after_content_change", report_id=str(report.id))

    # An edit path that enqueued a replacement delivery marked it as the report's latest, so yield to
    # it and let that one post. Checked for every full delivery, not only one that rebuilt: an edit
    # landing before this delivery starts leaves nothing to rebuild, so the content is already
    # current and a rebuild-only check would post it here and again under the replacement. A
    # note-only delivery carries its own note rather than report content, and is never marked as a
    # latest delivery, so it has no claim to yield and must always post.
    if edit_note is None and _newer_report_delivery_queued(str(report.id), delivery_id, integration_id, channel):
        logger.info(
            "signals_scout.slack_delivery_yielded_to_newer_delivery",
            report_id=str(report.id),
            delivery_id=delivery_id,
        )
        return

    # The build can hold the worker for the whole render budget, long enough for the workspace to be
    # reconnected, which writes a new token to the same row and revokes the one loaded above. Posting
    # with the stale token fails as permanent, so resolve the row again before the post.
    integration = _slack_integration_for_project(
        integration_id=integration_id,
        project_id=report.team.project_id,
    )
    client = SlackIntegration(integration).client
    try:
        response = _post_scout_report_lead_message(
            client,
            channel_id=channel_id,
            delivery_id=delivery_id,
            blocks=messages.lead_blocks,
            fallback=messages.fallback,
        )
    except SlackApiError as exc:
        error_code = slack_api_error_code(exc)
        if error_code in _PERMANENT_SLACK_ERROR_CODES:
            raise ScoutSlackPermanentDeliveryError(
                f"Slack rejected the scout report with {error_code}",
                error_code=error_code,
            ) from exc
        raise

    thread_ts = response.get("ts")
    if threaded:
        _post_scout_report_thread_replies(
            client,
            channel_id=channel_id,
            thread_ts=thread_ts,
            delivery_id=delivery_id,
            reply_blocks=messages.reply_blocks,
            fallback=messages.fallback,
        )

    _post_scout_slack_reply(
        client,
        channel_id=channel_id,
        thread_ts=thread_ts,
        scout_team_id=run.team_id,
        integration_team_id=integration.team_id,
    )
