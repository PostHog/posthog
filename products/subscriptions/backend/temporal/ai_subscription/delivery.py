import re
import uuid
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from django.db.models import Q

import structlog
from markdown_it import MarkdownIt
from markdown_it.token import Token
from markdown_it.utils import EnvType
from slack_sdk.errors import SlackApiError

from posthog.email import EmailMessage, raise_if_delivery_rejected
from posthog.exceptions_capture import capture_exception
from posthog.helpers.email_formatting import render_ai_email_html
from posthog.helpers.markdown_safety import is_allowed_link_url, strip_external_links_markdown
from posthog.integrations import IntegrationRecord
from posthog.models import Team, User
from posthog.slack.formatting import channel_id_from_target
from posthog.sync import database_sync_to_async
from posthog.utils import absolute_uri

from products.exports.backend.facade.api import get_delivery_image_url
from products.slack_app.backend.facade.api import slack_followup_invite
from products.subscriptions.backend.facade.contracts import PromptRejectedError, SubscriptionTriggerType
from products.subscriptions.backend.logic.slack_subscriptions import (
    UTM_TAGS_BASE,
    SlackDeliveryResult,
    SlackMessage,
    _summary_rich_text,
    deliver_slack_message_data,
)
from products.subscriptions.backend.logic.teams_subscriptions import (
    TEAMS_CARD_TEXT_BUDGET,
    TEAMS_UTM_TAGS,
    fit_to_teams_budget,
    teams_byte_size,
    teams_card_message,
    teams_open_url_action,
    teams_text_block,
)
from products.subscriptions.backend.models.subscription import (
    AIQueryPlanStatus,
    Subscription,
    SubscriptionDelivery,
    get_unsubscribe_token,
)
from products.subscriptions.backend.temporal.ai_subscription.report_pipeline import AiReportResult, generate_ai_report
from products.subscriptions.backend.temporal.ai_subscription.spec_generator import ReportWindow, compute_report_window
from products.subscriptions.backend.temporal.types import AI_REPORT_WINDOW_END_KEY

logger = structlog.get_logger(__name__)


_MARKDOWN_RENDERER = MarkdownIt("commonmark", {"breaks": True, "html": False}).enable("table")

# Slack's hard limit is 3000 chars per section block; keep margin for safety.
SLACK_MRKDWN_SECTION_LIMIT = 2900
SLACK_MARKDOWN_MESSAGE_LIMIT = 12000
SLACK_MESSAGE_BLOCK_LIMIT = 50
SLACK_TABLE_ROW_LIMIT = 100
SLACK_TABLE_COLUMN_LIMIT = 20
SLACK_TABLE_CHARACTER_LIMIT = 10000
SLACK_IMAGE_TITLE_LIMIT = 2000

TEAMS_TEXT_BLOCK_LIMIT = 3000
# Upper bound on report blocks. It only stops the chunker from splitting an unbounded report into
# thousands of pieces; TEAMS_CARD_TEXT_BUDGET is what keeps the payload inside what Teams accepts.
TEAMS_REPORT_BLOCK_COUNT = 10
# Chunking is quadratic in the number of chunks and nothing upstream bounds a report's length, so
# the markdown is cut to what could fill the blocks above before it is chunked at all.
_TEAMS_REPORT_CHUNKING_LIMIT = TEAMS_REPORT_BLOCK_COUNT * TEAMS_TEXT_BLOCK_LIMIT


def _split_text_into_chunks(text: str, limit: int = SLACK_MRKDWN_SECTION_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text] if text else []

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        # prefer a paragraph break, then any newline, else a hard cut; cut <= 0 guards against
        # carving an empty leading chunk and never progressing
        cut = remaining.rfind("\n\n", 0, limit)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunk = remaining[:cut].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _split_fenced_markdown(content: str, opening: str, closing: str, limit: int) -> list[str]:
    prefix = f"{opening}\n"
    suffix = f"\n{closing}\n"
    budget = limit - len(prefix) - len(suffix)
    if budget <= 0:
        prefix, suffix = "~~~\n", "\n~~~\n"
        budget = limit - len(prefix) - len(suffix)
    chunks = []
    while content:
        cut = len(content)
        if cut > budget:
            cut = content.rfind("\n", 0, budget) + 1 or budget
        chunks.append(f"{prefix}{content[:cut]}{suffix}")
        content = content[cut:]
    return chunks


def _split_slack_markdown(text: str) -> list[str]:
    limit = SLACK_MARKDOWN_MESSAGE_LIMIT
    lines = re.findall(r"[^\n]*\n|[^\n]+$", text)
    pieces: list[str] = []
    table_sizes: dict[str, int] = {}
    standalone_tables: set[str] = set()
    cursor = 0
    for token in _MARKDOWN_RENDERER.parse(text):
        if token.level or token.map is None or token.map[0] < cursor:
            continue
        start, end = token.map
        pieces.extend(_split_text_into_chunks("".join(lines[cursor:start]), limit))
        block = "".join(lines[start:end])
        if token.type == "table_open":
            header = "".join(lines[start : start + 2])
            rows = lines[start + 2 : end]
            table_limit = min(limit, SLACK_TABLE_CHARACTER_LIMIT)
            column_count = sum(child.type == "th_open" for child in _MARKDOWN_RENDERER.parse(header))
            if (
                any(len(header) + len(row) > table_limit for row in rows)
                or len(header) >= table_limit
                or column_count > SLACK_TABLE_COLUMN_LIMIT
            ):
                pieces.extend(_split_fenced_markdown(block, "~~~", "~~~", limit))
            else:
                tables: list[str] = []
                table = header
                row_count = 1
                for row in rows:
                    if len(table) + len(row) > table_limit or row_count == SLACK_TABLE_ROW_LIMIT:
                        tables.append(table)
                        table = header
                        row_count = 1
                    table += row
                    row_count += 1
                tables.append(table)
                pieces.extend(tables)
                table_sizes.update({table: len(table) for table in tables})
                if len(tables) > 1:
                    standalone_tables.update(tables)
        elif len(block) <= limit:
            pieces.append(block)
        elif token.type == "fence":
            pieces.extend(_split_fenced_markdown(token.content, token.markup + token.info, token.markup, limit))
        else:
            pieces.extend(_split_text_into_chunks(block, limit))
        cursor = end
    pieces.extend(_split_text_into_chunks("".join(lines[cursor:]), limit))

    chunks: list[str] = []
    current = ""
    table_characters = 0
    for piece in pieces:
        if piece in standalone_tables:
            if current.strip():
                chunks.append(current)
            chunks.append(piece)
            current = ""
            table_characters = 0
            continue
        piece_table_size = table_sizes.get(piece, 0)
        if len(current) + len(piece) > limit or table_characters + piece_table_size > SLACK_TABLE_CHARACTER_LIMIT:
            if current.strip():
                chunks.append(current)
            current = ""
            table_characters = 0
        current += piece
        table_characters += piece_table_size
    if current.strip():
        chunks.append(current)
    return chunks


def _safe_slack_markdown_sections(markdown: str) -> list[str]:
    sections: list[str] = []
    for section in _split_slack_markdown(markdown):
        safe_section = strip_external_links_markdown(section, additional_allowed_origin=absolute_uri("/"))
        if len(safe_section) <= SLACK_MARKDOWN_MESSAGE_LIMIT:
            sections.append(safe_section)
            continue
        for content in _split_text_into_chunks(section, (SLACK_MARKDOWN_MESSAGE_LIMIT - 6) // 3):
            fence = "`" * max(3, max((len(run) + 1 for run in re.findall(r"`+", content)), default=3))
            sections.extend(_split_fenced_markdown(content, fence, fence, SLACK_MARKDOWN_MESSAGE_LIMIT))
    return sections


def _slack_markdown_blocks(markdown: str) -> list[dict[str, Any]]:
    if "<u>" not in markdown:
        return [{"type": "markdown", "text": markdown}]
    lines = re.findall(r"[^\n]*\n|[^\n]+$", markdown)
    blocks: list[dict[str, Any]] = []
    cursor = 0
    tokens = _MARKDOWN_RENDERER.parse(markdown)
    for token in tokens:
        if token.level or token.map is None or token.map[0] < cursor:
            continue
        start, end = token.map
        content = "".join(lines[cursor:end])
        complex_list = token.type in {"bullet_list_open", "ordered_list_open"} and any(
            child.level > token.level
            and child.map is not None
            and start <= child.map[0] < end
            and child.type in {"bullet_list_open", "ordered_list_open", "fence", "code_block"}
            for child in tokens
        )
        if (
            token.type in {"paragraph_open", "bullet_list_open", "ordered_list_open"}
            and "<u>" in content
            and not complex_list
        ):
            content = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"_\1_", content)
            blocks.append(_summary_rich_text(content))
        else:
            if blocks and blocks[-1]["type"] == "markdown":
                blocks[-1]["text"] += content
            else:
                blocks.append({"type": "markdown", "text": content})
        cursor = end
    if remainder := "".join(lines[cursor:]):
        blocks.append({"type": "markdown", "text": remainder})
    return blocks


def _slack_highlight_inline(tokens: list[Token]) -> list[dict[str, Any]] | None:
    elements: list[dict[str, Any]] = []
    styles: list[dict[str, bool]] = [{}]
    link: str | None = None
    style_tokens = {"strong": "bold", "em": "italic", "s": "strike"}
    for token in tokens:
        if token.type in {"strong_open", "em_open", "s_open"}:
            styles.append({**styles[-1], style_tokens[token.type.removesuffix("_open")]: True})
        elif token.type in {"strong_close", "em_close", "s_close"}:
            styles.pop()
        elif token.type == "link_open":
            destination = str(token.attrGet("href") or "")
            link = destination if is_allowed_link_url(destination, absolute_uri("/")) else None
        elif token.type == "link_close":
            link = None
        elif token.type in {"text", "code_inline", "softbreak", "hardbreak"}:
            content = token.content
            if token.type in {"softbreak", "hardbreak"}:
                content = "\n"
            if not content:
                continue
            style = styles[-1]
            if token.type == "code_inline":
                style = {**style, "code": True}
            element: dict[str, Any] = {"type": "text", "text": content}
            if link is not None:
                element = {"type": "link", "url": link, "text": content}
                style = {key: value for key, value in style.items() if key != "code"}
            if style:
                element["style"] = style
            if (
                link is not None
                and elements
                and elements[-1]["type"] == "link"
                and elements[-1]["url"] == link
                and elements[-1].get("style") == element.get("style")
            ):
                elements[-1]["text"] += content
                continue
            elements.append(element)
        else:
            return None
    return elements


def _slack_highlight_content(markdown: str, env: EnvType) -> dict[str, Any] | None:
    if "<u>" in markdown:
        return None
    tokens = MarkdownIt("commonmark", {"html": False}).enable("strikethrough").parse(markdown, env)
    sections: list[dict[str, Any]] = []
    paragraph_count = 0
    for token in tokens:
        if token.type == "bullet_list_open":
            if token.level != 0:
                return None
        elif token.type == "list_item_open":
            paragraph_count = 0
        elif token.type == "paragraph_open":
            paragraph_count += 1
            if paragraph_count > 1:
                return None
        elif token.type == "inline":
            elements = _slack_highlight_inline(token.children or [])
            if not elements:
                return None
            sections.append({"type": "rich_text_section", "elements": elements})
        elif token.type not in {"bullet_list_close", "list_item_close", "paragraph_close"}:
            return None
    if not sections:
        return None
    return {"type": "rich_text", "elements": [{"type": "rich_text_list", "style": "bullet", "elements": sections}]}


def _slack_report_blocks(markdown: str, env: EnvType) -> list[dict[str, Any]]:
    tokens = _MARKDOWN_RENDERER.parse(markdown, env)
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.level != 0 or token.tag != "h2":
            continue
        heading = tokens[index + 1].content
        if len(heading) > 150:
            break
        following = tokens[index + 3 :]
        if not following or following[0].type != "bullet_list_open":
            break
        findings = following[0]
        assert token.map is not None and findings.map is not None
        lines = re.findall(r"[^\n]*\n|[^\n]+$", markdown)
        before = "".join(lines[: token.map[0]]).rstrip()
        content = "".join(lines[findings.map[0] : findings.map[1]])
        after = "".join(lines[findings.map[1] :]).lstrip()
        highlight = _slack_highlight_content(content, env)
        if highlight is None:
            return _slack_markdown_blocks(markdown)
        blocks = _slack_markdown_blocks(before) if before else []
        blocks.append(
            {
                "type": "container",
                "title": {"type": "plain_text", "text": heading, "emoji": False},
                "has_header_divider": True,
                "width": "full",
                "child_blocks": [highlight],
            }
        )
        if after:
            blocks.extend(_slack_markdown_blocks(after))
        return blocks
    return _slack_markdown_blocks(markdown)


def _last_scheduled_report_cutoff(subscription: Subscription) -> datetime | None:
    try:
        row = (
            SubscriptionDelivery.objects.filter(
                subscription_id=subscription.id,
                status=SubscriptionDelivery.Status.COMPLETED,
                # Only real scheduled sends move the anchor: a manual "Test delivery" (or an immediate
                # target-change confirmation) right before a run would otherwise shrink its window to
                # near-empty — a test is a preview, not a send.
                trigger_type=SubscriptionTriggerType.SCHEDULED,
                finished_at__isnull=False,
            )
            .order_by("-finished_at")
            .values_list("finished_at", "content_snapshot")
            .first()
        )
        if row is None:
            return None
        finished_at, snapshot = row
        # Prefer the run's persisted window end: anchoring on finished_at leaves the run's own
        # generation+send time uncovered. Rows written before the key existed fall back.
        window_end = (snapshot or {}).get(AI_REPORT_WINDOW_END_KEY)
        if isinstance(window_end, str):
            try:
                return datetime.fromisoformat(window_end)
            except ValueError:
                pass
        return finished_at
    except Exception as exc:
        # A transient DB error on this one lookup shouldn't fail the whole delivery — None falls
        # back to the cadence window (which may re-cover already-sent data, never drop any).
        logger.warning(
            "ai_report.last_delivery_lookup_failed",
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            exc_info=True,
        )
        capture_exception(exc, {"subscription_id": subscription.id, "feature": "ai_subscription"})
        return None


def _resolve_subscription_context(
    subscription: Subscription,
) -> tuple[Team, User | None, ReportWindow, dict | None]:
    # team/created_by are FK relations and the last-delivery lookup hits the DB; resolving the window
    # here keeps all ORM access (and the timezone math) off the event loop in one sync hop. The frozen
    # plan (if any) is read here too so the generation path stays free of ORM access.
    team = subscription.team
    # Day-based window modes don't anchor to delivery history — skip the lookup for them.
    last_scheduled_cutoff = (
        _last_scheduled_report_cutoff(subscription)
        if subscription.ai_window_mode == Subscription.AIWindowMode.SINCE_LAST_SENT
        else None
    )
    window = compute_report_window(
        team=team,
        last_scheduled_cutoff=last_scheduled_cutoff,
        now=datetime.now(tz=UTC),
        window_days=subscription.ai_report_window_days,
        mode=subscription.ai_window_mode,
        start_days_ago=subscription.ai_window_start_days_ago,
        end_days_ago=subscription.ai_window_end_days_ago,
    )
    return team, subscription.created_by, window, subscription.ai_query_plan


def _persist_ai_query_plan(
    subscription_id: int,
    team_id: int,
    prompt: str | None,
    plan: dict,
    *,
    expected_include_images: bool,
) -> bool:
    image_state = Q(delivery_config__include_images=expected_include_images)
    if expected_include_images:
        # Existing subscriptions omit this key and default to including images.
        image_state |= ~Q(delivery_config__has_key="include_images")

    # Targeted update, never a full save() — that would re-emit the activity-log/analytics signals.
    # Matching both planning inputs prevents a concurrent edit from restoring an invalidated plan.
    return bool(
        Subscription.objects.filter(id=subscription_id, team_id=team_id, prompt=prompt)
        .filter(image_state)
        .update(ai_query_plan=plan)
    )


async def build_ai_subscription_report(subscription: Subscription) -> AiReportResult:
    team, user, window, ai_query_plan = await database_sync_to_async(
        _resolve_subscription_context, thread_sensitive=False
    )(subscription)
    # created_by is FK SET_NULL; the pipeline requires a non-None user
    if user is None:
        raise PromptRejectedError("AI subscription has no creator (created_by deleted); cannot deliver.")

    include_images = subscription.includes_delivery_part("include_images")
    result = await generate_ai_report(
        team=team,
        user=user,
        prompt=subscription.prompt,
        window=window,
        ai_query_plan=ai_query_plan,
        trace_correlation_id=subscription.id,
        include_charts=include_images,
        include_manage_link=subscription.includes_delivery_part("include_manage_link"),
    )

    if result.plan_to_persist is not None:
        plan_persisted = False
        try:
            plan_persisted = await database_sync_to_async(_persist_ai_query_plan, thread_sensitive=False)(
                subscription.id,
                subscription.team_id,
                subscription.prompt,
                result.plan_to_persist,
                expected_include_images=include_images,
            )
        except Exception as exc:
            # The frozen plan is an optimization — losing this write must not abort the delivery (the
            # report is already generated; failing here would burn the LLM run and retry from scratch).
            logger.warning(
                "ai_report.query_plan_persist_failed",
                subscription_id=subscription.id,
                team_id=subscription.team_id,
                exc_info=True,
            )
            capture_exception(exc, {"subscription_id": subscription.id, "feature": "ai_subscription"})
        if not plan_persisted:
            # This delivery cannot claim the plan is frozen unless the conditional write succeeded.
            # In particular, a mid-run prompt edit intentionally makes that write a no-op.
            result = dataclasses.replace(result, query_plan_status=AIQueryPlanStatus.NOT_FROZEN)

    return result


CHART_IMAGE_URL_TTL = timedelta(days=180)


def build_chart_image_urls(charts: Any, *, team_id: int) -> list[dict]:
    if not isinstance(charts, list):
        return []
    urls: list[dict] = []
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        asset_id = chart.get("export_asset_id")
        if not isinstance(asset_id, int) or isinstance(asset_id, bool):
            continue
        image_url = get_delivery_image_url(team_id=team_id, asset_id=asset_id, expiry_delta=CHART_IMAGE_URL_TTL)
        if image_url:
            urls.append({"title": str(chart.get("title") or ""), "image_url": image_url})
    return urls


def _build_feedback_url(subscription_url: str, delivery_id: uuid.UUID, feedback: str, source: str) -> str:
    # Lands on the authenticated subscription page; the frontend reads these exact params
    # (feedback_delivery, feedback, feedback_source) and captures an `ai_report_feedback` event.
    params = urlencode({"feedback_delivery": str(delivery_id), "feedback": feedback, "feedback_source": source})
    return f"{subscription_url}?{params}"


def send_email_ai_subscription_report(
    *,
    email: str,
    subscription: Subscription,
    markdown: str,
    delivery_run_id: str,
    delivery_id: uuid.UUID,
    charts: list[dict] | None = None,
) -> None:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=email"
    html = render_ai_email_html(markdown)
    title = subscription.title or "Your PostHog AI report"
    subscription_url = subscription.url or absolute_uri(
        f"/project/{subscription.team_id}/subscriptions/{subscription.id}"
    )
    unsubscribe_url = absolute_uri(f"/unsubscribe?token={get_unsubscribe_token(subscription, email)}&{utm_tags}")

    campaign_key = f"ai_subscription_report_{subscription.id}_{delivery_run_id}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"PostHog AI report - {title}",
        template_name="ai_subscription_report",
        template_context={
            "title": title,
            "rendered_html": html,
            "charts": (charts or []) if subscription.includes_delivery_part("include_images") else [],
            "include_feedback": subscription.includes_delivery_part("include_feedback"),
            "include_manage_link": subscription.includes_delivery_part("include_manage_link"),
            # `delivery` lets the frontend capture `ai_report_clicked` on landing — the
            # click-through signal for whether delivered reports actually get read.
            "subscription_url": f"{subscription_url}?{utm_tags}&delivery={delivery_id}",
            "unsubscribe_url": unsubscribe_url,
            "feedback_positive_url": _build_feedback_url(subscription_url, delivery_id, "positive", "email"),
            "feedback_negative_url": _build_feedback_url(subscription_url, delivery_id, "negative", "email"),
        },
    )
    message.add_recipient(email=email)
    message.send(send_async=False)

    raise_if_delivery_rejected(campaign_key, email)


def send_email_ai_subscription_credit_limited(
    *,
    email: str,
    subscription: Subscription,
    resume_date: datetime,
    billing_period_key: str,
) -> None:
    """Notify the owner that a scheduled AI report was skipped for lack of AI credits.
    `billing_period_key` keys the campaign so MessagingRecord dedups to one notice per
    credit-reset cycle even if the skip path runs more than once."""
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=email"
    title = subscription.title or "Your PostHog AI report"
    subscription_url = subscription.url or absolute_uri(
        f"/project/{subscription.team_id}/subscriptions/{subscription.id}"
    )
    billing_url = absolute_uri("/organization/billing")

    message = EmailMessage(
        campaign_key=f"ai_subscription_credit_limited_{subscription.id}_{billing_period_key}",
        subject=f"PostHog AI report skipped - {title}",
        template_name="ai_subscription_credit_limited",
        template_context={
            "title": title,
            "resume_date": resume_date,
            "subscription_url": f"{subscription_url}?{utm_tags}",
            "billing_url": f"{billing_url}?{utm_tags}",
        },
    )
    message.add_recipient(email=email)
    message.send(send_async=False)


def _build_ai_slack_message(
    subscription: Subscription,
    markdown: str,
    *,
    delivery_id: uuid.UUID,
    integration: IntegrationRecord | None = None,
    charts: list[dict] | None = None,
) -> SlackMessage:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"
    channel = channel_id_from_target(subscription.target_value)
    markdown = strip_external_links_markdown(markdown, additional_allowed_origin=absolute_uri("/"))
    env: EnvType = {}
    tokens = _MARKDOWN_RENDERER.parse(markdown, env)
    if tokens and tokens[0].type == "heading_open" and tokens[0].tag == "h1" and tokens[0].map:
        markdown = "".join(markdown.splitlines(keepends=True)[tokens[0].map[1] :]).lstrip("\r\n")
    sections = _safe_slack_markdown_sections(markdown)
    title = subscription.title or "Your PostHog AI report"
    first_section = sections[0] if sections else "_No report content was generated._"
    heading = f'Your report "{title}" is ready! 🎉'

    blocks: list[dict] = [
        {"type": "divider"},
        {"type": "header", "text": {"type": "plain_text", "text": heading[:150]}},
        *_slack_report_blocks(first_section, env),
    ]
    for chart in (charts or []) if subscription.includes_delivery_part("include_images") else []:
        caption = chart.get("title") or "Chart"
        image_block: dict = {
            "type": "image",
            "image_url": chart["image_url"],
            "alt_text": caption[:SLACK_IMAGE_TITLE_LIMIT],
        }
        if chart.get("title"):
            image_block["title"] = {"type": "plain_text", "text": caption[:SLACK_IMAGE_TITLE_LIMIT]}
        blocks.append(image_block)
    if len(sections) > 1:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "_See thread for the rest of the report._"}}
        )

    subscription_url = subscription.url or absolute_uri(
        f"/project/{subscription.team_id}/subscriptions/{subscription.id}"
    )
    footer_blocks: list[dict] = []
    if subscription.includes_delivery_part("include_manage_link"):
        footer_blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Manage subscription"},
                        "url": f"{subscription_url}?{utm_tags}",
                    }
                ],
            }
        )
    if subscription.includes_delivery_part("include_feedback"):
        feedback_positive_url = _build_feedback_url(subscription_url, delivery_id, "positive", "slack")
        feedback_negative_url = _build_feedback_url(subscription_url, delivery_id, "negative", "slack")
        footer_blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "Was this report useful? "
                            f"<{feedback_positive_url}|👍 Yes> · <{feedback_negative_url}|👎 No>"
                        ),
                    }
                ],
            }
        )
    # AI consent is enforced before report generation, so this renderer only applies the delivery option.
    if subscription.includes_delivery_part("include_posthog_hint"):
        if explore_hint := slack_followup_invite(integration, utm_tags=utm_tags, ai_enabled=True):
            footer_blocks.append(explore_hint)
    if footer_blocks:
        blocks.append({"type": "divider"})
        blocks.extend(footer_blocks)

    thread_messages: list[dict[str, Any]] = []
    if len(blocks) > SLACK_MESSAGE_BLOCK_LIMIT:
        overflow = blocks[SLACK_MESSAGE_BLOCK_LIMIT - 1 :]
        blocks = blocks[: SLACK_MESSAGE_BLOCK_LIMIT - 1]
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "_See thread for the rest of the report._"}}
        )
        thread_messages.extend(
            {"blocks": overflow[start : start + SLACK_MESSAGE_BLOCK_LIMIT]}
            for start in range(0, len(overflow), SLACK_MESSAGE_BLOCK_LIMIT)
        )
    for section in sections[1:]:
        section_blocks = _slack_report_blocks(section, env)
        thread_messages.extend(
            {"blocks": section_blocks[start : start + SLACK_MESSAGE_BLOCK_LIMIT]}
            for start in range(0, len(section_blocks), SLACK_MESSAGE_BLOCK_LIMIT)
        )
    # unfurl=False: report content is LLM-generated; never let Slack auto-fetch a link it contains.
    return SlackMessage(channel=channel, blocks=blocks, title=title, thread_messages=thread_messages, unfurl=False)


async def send_slack_ai_subscription_report(
    *,
    subscription: Subscription,
    markdown: str,
    integration: IntegrationRecord,
    delivery_id: uuid.UUID,
    charts: list[dict] | None = None,
) -> SlackDeliveryResult:
    # Resolve the charts the message will really carry, so the retry-without-charts decision
    # cannot promise a different payload than the first send: a report that hides its charts
    # would otherwise resend an identical message and double the posts Slack rate-limits.
    effective_charts = charts if subscription.includes_delivery_part("include_images") else None

    def build(with_charts: list[dict] | None) -> SlackMessage:
        return _build_ai_slack_message(
            subscription, markdown, delivery_id=delivery_id, integration=integration, charts=with_charts
        )

    try:
        return await deliver_slack_message_data(integration, subscription, build(effective_charts))
    except SlackApiError as exc:
        if not effective_charts or exc.response.get("error") != "invalid_blocks":
            raise
        logger.warning(
            "ai_report.slack_charts_rejected_resending_without_them",
            subscription_id=subscription.id,
            chart_count=len(effective_charts),
        )
        return await deliver_slack_message_data(integration, subscription, build(None))


def build_ai_teams_card(
    subscription: Subscription,
    markdown: str,
    *,
    delivery_id: uuid.UUID,
    charts: list[dict] | None = None,
) -> dict[str, Any]:
    """Adaptive Card for an AI report. Adaptive Cards render a restricted markdown subset in a
    TextBlock, so the report goes through mostly as written and a table degrades to plain text."""
    title = strip_external_links_markdown(subscription.title or "Your PostHog AI report")
    subscription_url = subscription.url or absolute_uri(
        f"/project/{subscription.team_id}/subscriptions/{subscription.id}"
    )

    report = strip_external_links_markdown(markdown)
    sections = _split_text_into_chunks(report[:_TEAMS_REPORT_CHUNKING_LIMIT], TEAMS_TEXT_BLOCK_LIMIT)

    heading = f"**{title}**"
    include_manage_link = subscription.includes_delivery_part("include_manage_link")
    include_feedback = subscription.includes_delivery_part("include_feedback")
    shortened_notice = "This report was shortened to fit."
    if include_manage_link:
        shortened_notice += f" [Read all of it in PostHog]({subscription_url}?{TEAMS_UTM_TAGS})"
    feedback_positive_url = _build_feedback_url(subscription_url, delivery_id, "positive", "teams")
    feedback_negative_url = _build_feedback_url(subscription_url, delivery_id, "negative", "teams")
    feedback = f"Was this report useful? [👍 Yes]({feedback_positive_url}) · [👎 No]({feedback_negative_url})"

    # Chunking is by character and Teams measures the payload in UTF-8 bytes, so CJK or emoji text
    # is several times the size the chunker accounted for. The report gets whatever the fixed blocks
    # around it leave, which is what keeps such a report from being rejected on every scheduled run.
    remaining = (
        TEAMS_CARD_TEXT_BUDGET
        - teams_byte_size(heading)
        - teams_byte_size(shortened_notice)
        - (teams_byte_size(feedback) if include_feedback else 0)
    )

    kept: list[str] = []
    over_budget = False
    for section in sections[:TEAMS_REPORT_BLOCK_COUNT]:
        size = teams_byte_size(section)
        if size > remaining:
            fitted = fit_to_teams_budget(section, remaining)
            if teams_byte_size(fitted) <= remaining:
                kept.append(fitted)
            over_budget = True
            break
        kept.append(section)
        remaining -= size

    body: list[dict[str, Any]] = [teams_text_block(heading)]
    if kept:
        body.extend(teams_text_block(section) for section in kept)
    else:
        body.append(teams_text_block("_No report content was generated._"))
    for chart in (charts or []) if subscription.includes_delivery_part("include_images") else []:
        body.append(
            {
                "type": "Image",
                "url": chart["image_url"],
                "size": "Stretch",
                "altText": chart.get("title") or "Chart",
            }
        )
    if over_budget or len(kept) < len(sections) or len(report) > _TEAMS_REPORT_CHUNKING_LIMIT:
        body.append(teams_text_block(shortened_notice, is_subtle=True))
    if include_feedback:
        body.append(teams_text_block(feedback, is_subtle=True))

    actions = (
        [teams_open_url_action("Manage subscription", f"{subscription_url}?{TEAMS_UTM_TAGS}")]
        if include_manage_link
        else []
    )
    return teams_card_message(body, actions)


__all__ = [
    "build_ai_subscription_report",
    "build_ai_teams_card",
    "build_chart_image_urls",
    "render_ai_email_html",
    "send_email_ai_subscription_report",
    "send_slack_ai_subscription_report",
]
