import re
import json
import uuid
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any
from urllib.parse import urlencode, urlsplit

from django.db import transaction

import nh3
import structlog
from markdown_it import MarkdownIt
from markdown_to_mrkdwn import SlackMarkdownConverter
from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.email import EmailMessage, raise_if_delivery_rejected
from posthog.exceptions_capture import capture_exception
from posthog.helpers.markdown_safety import strip_external_links_markdown
from posthog.helpers.slack_subscription_explore import build_explore_hint
from posthog.models import Team, User
from posthog.models.integration import Integration
from posthog.sync import database_sync_to_async
from posthog.utils import absolute_uri

from products.exports.backend.facade.api import get_delivery_image_url
from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery, get_unsubscribe_token
from products.exports.backend.models.subscription_context import SubscriptionContext
from products.exports.backend.temporal.subscriptions.ai_subscription.report_context import (
    MAX_REPORT_CONTEXTS,
    ReportContextSelection,
    compute_report_context_fingerprint,
    resolve_report_context,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline import (
    AiReportResult,
    compact_report_context,
    generate_ai_report,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import (
    PromptRejectedError,
    ReportWindow,
    compute_report_window,
)
from products.exports.backend.temporal.subscriptions.types import AI_REPORT_WINDOW_END_KEY, SubscriptionTriggerType

from ee.tasks.subscriptions.slack_subscriptions import (
    UTM_TAGS_BASE,
    SlackDeliveryResult,
    SlackMessage,
    deliver_slack_message_data,
)

logger = structlog.get_logger(__name__)


_MARKDOWN_RENDERER = MarkdownIt("commonmark", {"breaks": True, "html": False}).enable("table")
_SLACK_CONVERTER = SlackMarkdownConverter()

# defense-in-depth on top of html=False: allow only the tags commonmark emits
_ALLOWED_EMAIL_TAGS = {
    "a",
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "b",
    "i",
    "code",
    "pre",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}
_ALLOWED_EMAIL_ATTRS = {"a": {"href", "title"}}
_PULSE_FAILURE_TEXT = {
    "timeout": "Some Pulse work did not finish before the delivery deadline.",
    "finalization_timeout": "Some Pulse work did not finish before the delivery deadline.",
    "action_failed": "One suggested action could not be completed.",
}
_PULSE_OUTCOME_FAILURE_TEXT = {
    "permissions_lost": "Source access was lost.",
    "retry_exhausted": "The measurement was unsuccessful after two attempts.",
    "not_ready_expired": "The comparison was not ready before the measurement window closed.",
    "evidence_unavailable": "Measurement evidence was unavailable.",
    "measurement_inconclusive": "The measurement could not produce a reliable result.",
}
_PULSE_ARTIFACT_LABELS = {
    "draft_pr": "Draft pull request",
    "experiment_draft": "Experiment draft",
}
_TRUSTED_PULL_REQUEST_PATH = re.compile(r"^/[^/\r\n]+/[^/\r\n]+/pull/[1-9][0-9]*$")
_TRUSTED_EXPERIMENT_PATH = re.compile(r"^/project/[1-9][0-9]*/experiments/[1-9][0-9]*$")
_TRUSTED_PULSE_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,255}$")
_PULSE_ENUM_VALUE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@frozen
class PulseDeliveryRender:
    markdown: str
    trusted_links: tuple[tuple[str, str], ...]


@frozen
class _TrustedPulseArtifactLink:
    label: str
    url: str


# Slack's hard limit is 3000 chars per section block; keep margin for safety.
SLACK_MRKDWN_SECTION_LIMIT = 2900
SLACK_IMAGE_TITLE_LIMIT = 2000


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


@frozen
class SubscriptionReportContext:
    team: Team
    user: User | None
    prompt: str | None
    window: ReportWindow
    ai_query_plan: dict | None
    context_selection: ReportContextSelection


def _resolve_subscription_context(subscription: Subscription) -> SubscriptionReportContext:
    # team/created_by are FK relations and the last-delivery lookup hits the DB; resolving the window
    # here keeps all ORM access (and the timezone math) off the event loop in one sync hop. The frozen
    # plan (if any) is read here too so the generation path stays free of ORM access.
    with transaction.atomic():
        current = (
            Subscription.objects.select_for_update()
            .select_related("team", "created_by")
            .get(id=subscription.id, team_id=subscription.team_id)
        )
        context_rows = list(
            SubscriptionContext.objects.for_team(current.team_id)
            .filter(subscription_id=current.id)
            .order_by("created_at", "id")
            .values_list("dashboard_id", "insight_id")[: MAX_REPORT_CONTEXTS + 1]
        )
        selection = ReportContextSelection(
            dashboard_ids=tuple(
                sorted(
                    dashboard_id for dashboard_id, _ in context_rows[:MAX_REPORT_CONTEXTS] if dashboard_id is not None
                )
            ),
            insight_ids=tuple(
                sorted(insight_id for _, insight_id in context_rows[:MAX_REPORT_CONTEXTS] if insight_id is not None)
            ),
            over_limit=len(context_rows) > MAX_REPORT_CONTEXTS,
        )
        last_scheduled_cutoff = (
            _last_scheduled_report_cutoff(current)
            if current.ai_window_mode == Subscription.AIWindowMode.SINCE_LAST_SENT
            else None
        )
        window = compute_report_window(
            team=current.team,
            last_scheduled_cutoff=last_scheduled_cutoff,
            now=datetime.now(tz=UTC),
            window_days=current.ai_report_window_days,
            mode=current.ai_window_mode,
            start_days_ago=current.ai_window_start_days_ago,
            end_days_ago=current.ai_window_end_days_ago,
        )
        return SubscriptionReportContext(
            team=current.team,
            user=current.created_by,
            prompt=current.prompt,
            window=window,
            ai_query_plan=current.ai_query_plan,
            context_selection=selection,
        )


def _persist_ai_query_plan(subscription_id: int, team_id: int, prompt: str | None, plan: dict) -> bool:
    planning_fingerprint = plan.get("context_fingerprint")
    if not isinstance(planning_fingerprint, str):
        return False

    with transaction.atomic():
        current_prompt = (
            Subscription.objects.select_for_update()
            .filter(id=subscription_id, team_id=team_id)
            .values_list("prompt", flat=True)
            .first()
        )
        if current_prompt != prompt:
            return False

        context_rows = list(
            SubscriptionContext.objects.for_team(team_id)
            .filter(subscription_id=subscription_id)
            .order_by("created_at", "id")
            .values_list("dashboard_id", "insight_id")[: MAX_REPORT_CONTEXTS + 1]
        )
        if len(context_rows) > MAX_REPORT_CONTEXTS:
            return False
        dashboard_ids = [dashboard_id for dashboard_id, _ in context_rows if dashboard_id is not None]
        insight_ids = [insight_id for _, insight_id in context_rows if insight_id is not None]
        current_fingerprint = compute_report_context_fingerprint(
            dashboard_ids=dashboard_ids,
            insight_ids=insight_ids,
        )
        if current_fingerprint != planning_fingerprint:
            return False

        return bool(
            Subscription.objects.filter(id=subscription_id, team_id=team_id, prompt=prompt).update(ai_query_plan=plan)
        )


async def build_ai_subscription_report(subscription: Subscription) -> AiReportResult:
    context = await database_sync_to_async(_resolve_subscription_context, thread_sensitive=False)(subscription)
    # created_by is FK SET_NULL; the pipeline requires a non-None user
    if context.user is None:
        raise PromptRejectedError("AI subscription has no creator (created_by deleted); cannot deliver.")

    report_context = await resolve_report_context(subscription, context.context_selection)

    result = await generate_ai_report(
        team=context.team,
        user=context.user,
        prompt=context.prompt,
        window=context.window,
        ai_query_plan=context.ai_query_plan,
        formatted_context=(report_context.formatted_evidence if report_context.has_successful_evidence else ""),
        context_event_names=report_context.event_names,
        context_fingerprint=report_context.fingerprint,
        context_provenance=compact_report_context(report_context),
        trace_correlation_id=subscription.id,
    )

    if result.plan_to_persist is not None:
        try:
            await database_sync_to_async(_persist_ai_query_plan, thread_sensitive=False)(
                subscription.id, subscription.team_id, context.prompt, result.plan_to_persist
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


def render_ai_email_html(markdown: str) -> str:
    rendered = _MARKDOWN_RENDERER.render(strip_external_links_markdown(markdown))
    return nh3.clean(rendered, tags=_ALLOWED_EMAIL_TAGS, attributes=_ALLOWED_EMAIL_ATTRS)


def render_pulse_delivery_appendix(frozen_bundle: bytes) -> PulseDeliveryRender:
    """Render only the allowlisted fields from an immutable Pulse delivery bundle."""
    try:
        payload = json.loads(frozen_bundle)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Pulse delivery bundle is invalid.") from error
    if not isinstance(payload, dict) or payload.get("version") != "pulse_delivery_bundle:v1":
        raise ValueError("Pulse delivery bundle is invalid.")
    base_report = payload.get("base_report")
    readouts = payload.get("readouts", [])
    actions = payload.get("actions")
    failures = payload.get("failures")
    if (
        not isinstance(base_report, str)
        or not isinstance(readouts, list)
        or not isinstance(actions, list)
        or not isinstance(failures, list)
    ):
        raise ValueError("Pulse delivery bundle is invalid.")

    sections: list[str] = [base_report]
    trusted_links: list[tuple[str, str]] = []
    rendered_readouts = [section for readout in readouts[:3] if (section := _render_pulse_readout(readout)) is not None]
    if rendered_readouts:
        sections.extend(["## Outcome readouts", *rendered_readouts])
    for readout in readouts[:3]:
        if isinstance(readout, dict):
            _extend_trusted_pulse_links(trusted_links, readout.get("links"))

    sections.append("## Proactive actions")
    for action in actions[:3]:
        if not isinstance(action, dict):
            continue
        rank, title, why, impact = action.get("rank"), action.get("title"), action.get("why"), action.get("impact")
        if not isinstance(rank, int) or not all(isinstance(value, str) for value in (title, why, impact)):
            continue
        details = [f"- Why: {why}", f"- Expected impact: {impact}"]
        adoption = _pulse_enum_label(action.get("adoption_state"))
        if adoption is not None:
            details.append(f"- Adoption: {adoption}")
        operational_details = action.get("operational_details")
        task_result = action.get("task_result")
        operational_status = operational_details.get("status") if isinstance(operational_details, dict) else None
        if operational_status is None and isinstance(task_result, dict):
            operational_status = task_result.get("status")
        status = _pulse_enum_label(operational_status)
        if status is not None:
            details.append(f"- Status: {status}")
        prepared_artifacts = action.get("prepared_artifacts")
        if prepared_artifacts is None and isinstance(task_result, dict):
            prepared_artifacts = task_result.get("artifacts")
        details.extend(_pulse_artifact_lines(prepared_artifacts))
        provenance = operational_details.get("provenance") if isinstance(operational_details, dict) else None
        if provenance is None:
            provenance = action.get("provenance")
        if isinstance(provenance, list):
            tool_names = [
                item["tool_name"]
                for item in provenance[:20]
                if isinstance(item, dict)
                and isinstance(item.get("tool_name"), str)
                and _TRUSTED_PULSE_TOOL_NAME.fullmatch(item["tool_name"])
            ]
            if tool_names:
                details.append("- Evidence: " + ", ".join(f"`{tool_name}`" for tool_name in tool_names))
        sections.append(f"### {rank}. {title}\n\n" + "\n".join(details))
        _extend_trusted_pulse_links(trusted_links, action.get("links"))
    failure_codes = [failure.get("code") for failure in failures[:3] if isinstance(failure, dict)]
    failure_text = [
        _PULSE_FAILURE_TEXT.get(code, "Some Pulse work could not be completed.")
        for code in failure_codes
        if isinstance(code, str)
    ]
    if failure_text:
        sections.append("### Pulse notes\n\n" + "\n".join(f"- {text}" for text in failure_text))
    return PulseDeliveryRender(markdown="\n\n".join(sections), trusted_links=tuple(trusted_links))


def _render_pulse_readout(readout: object) -> str | None:
    if not isinstance(readout, dict):
        return None
    title = readout.get("recommendation_title")
    baseline_value = readout.get("baseline_value")
    if not isinstance(title, str) or not isinstance(baseline_value, str):
        return None
    details: list[str] = []
    metric_name = readout.get("metric_name")
    metric_unit = _pulse_enum_label(readout.get("metric_unit"))
    if isinstance(metric_name, str) and metric_unit is not None:
        details.append(f"- Measurement: {metric_name} ({metric_unit.lower()})")
    outcome = _pulse_enum_label(readout.get("verdict"))
    if outcome is not None:
        details.append(f"- Outcome: {outcome}")
    details.append(f"- Baseline: {baseline_value}")
    observed_value = readout.get("observed_value")
    if isinstance(observed_value, str):
        details.append(f"- Observed: {observed_value}")
    absolute_delta = readout.get("absolute_delta")
    if isinstance(absolute_delta, str):
        details.append(f"- Absolute movement: {absolute_delta}")
    relative_delta = readout.get("relative_delta")
    if isinstance(relative_delta, str):
        details.append(f"- Relative movement: {relative_delta}%")
    confidence = readout.get("confidence")
    if isinstance(confidence, str):
        details.append(f"- Confidence: {confidence}")
    baseline_from, baseline_to = readout.get("baseline_from"), readout.get("baseline_to")
    if isinstance(baseline_from, str) and isinstance(baseline_to, str):
        details.append(f"- Baseline window: {baseline_from} to {baseline_to}")
    observed_from, observed_to = readout.get("observed_from"), readout.get("observed_to")
    if isinstance(observed_from, str) and isinstance(observed_to, str):
        details.append(f"- Observed window: {observed_from} to {observed_to}")
    details.extend(_pulse_artifact_lines(readout.get("prepared_artifacts")))
    failure_code = readout.get("failure_code")
    if isinstance(failure_code, str):
        details.append(f"- Note: {_PULSE_OUTCOME_FAILURE_TEXT.get(failure_code, 'The outcome could not be measured.')}")
    return f"### {title}\n\n" + "\n".join(details)


def _pulse_artifact_lines(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for artifact in value[:2]:
        if not isinstance(artifact, dict):
            continue
        kind = artifact.get("kind")
        status = _pulse_enum_label(artifact.get("status"))
        if not isinstance(kind, str) or status is None:
            continue
        label = _PULSE_ARTIFACT_LABELS.get(kind)
        if label is not None:
            lines.append(f"- Prepared artifact: {label}: {status}")
    return lines


def _pulse_enum_label(value: object) -> str | None:
    if not isinstance(value, str) or not _PULSE_ENUM_VALUE.fullmatch(value):
        return None
    return value.replace("_", " ").capitalize()


def _extend_trusted_pulse_links(links: list[tuple[str, str]], candidate: object) -> None:
    if not isinstance(candidate, dict):
        return
    for label, url in candidate.items():
        trusted_link = _trusted_pulse_artifact_link(label=label, url=url)
        if trusted_link is not None:
            link = (trusted_link.label, trusted_link.url)
            if link not in links:
                links.append(link)


def _trusted_pulse_artifact_link(*, label: object, url: object) -> _TrustedPulseArtifactLink | None:
    if not isinstance(label, str) or not isinstance(url, str) or url != url.strip() or "\r" in url or "\n" in url:
        return None
    if label == "pull_request":
        parsed = urlsplit(url)
        if (
            parsed.scheme == "https"
            and parsed.netloc == "github.com"
            and not parsed.query
            and not parsed.fragment
            and _TRUSTED_PULL_REQUEST_PATH.fullmatch(parsed.path)
        ):
            return _TrustedPulseArtifactLink(label="Pull Request", url=url)
    if label == "experiment" and _TRUSTED_EXPERIMENT_PATH.fullmatch(url):
        return _TrustedPulseArtifactLink(label="Experiment", url=url)
    return None


def _render_trusted_links_html(links: tuple[tuple[str, str], ...]) -> str:
    if not links:
        return ""
    return (
        "<p>" + "<br>".join(f'<a href="{escape(url, quote=True)}">{escape(label)}</a>' for label, url in links) + "</p>"
    )


def send_email_ai_subscription_report(
    *,
    email: str,
    subscription: Subscription,
    markdown: str,
    delivery_run_id: str,
    delivery_id: uuid.UUID,
    charts: list[dict] | None = None,
    provider_idempotency_key: str | None = None,
    trusted_links: tuple[tuple[str, str], ...] = (),
) -> None:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=email"
    html = render_ai_email_html(markdown) + _render_trusted_links_html(trusted_links)
    title = subscription.title or "Your PostHog AI report"
    subscription_url = subscription.url or absolute_uri(
        f"/project/{subscription.team_id}/subscriptions/{subscription.id}"
    )
    unsubscribe_url = absolute_uri(f"/unsubscribe?token={get_unsubscribe_token(subscription, email)}&{utm_tags}")

    campaign_key = provider_idempotency_key or f"ai_subscription_report_{subscription.id}_{delivery_run_id}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"PostHog AI report - {title}",
        template_name="ai_subscription_report",
        template_context={
            "title": title,
            "rendered_html": html,
            "charts": charts or [],
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
    integration: Integration | None = None,
    charts: list[dict] | None = None,
) -> SlackMessage:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"
    channel = subscription.target_value.split("|")[0]
    sections = _split_text_into_chunks(_SLACK_CONVERTER.convert(strip_external_links_markdown(markdown)))
    title = subscription.title or "Your PostHog AI report"
    first_section = sections[0] if sections else "_No report content was generated._"

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": first_section}},
    ]
    for chart in charts or []:
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
    feedback_positive_url = _build_feedback_url(subscription_url, delivery_id, "positive", "slack")
    feedback_negative_url = _build_feedback_url(subscription_url, delivery_id, "negative", "slack")

    action_elements: list[dict] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Manage subscription"},
            "url": f"{subscription_url}?{utm_tags}",
        }
    ]
    blocks.extend(
        [
            {"type": "divider"},
            {"type": "actions", "elements": action_elements},
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
            },
        ]
    )
    # AI consent is enforced upstream before this report is built, so the hint always shows here.
    if explore_hint := build_explore_hint(integration, utm_tags=utm_tags, ai_enabled=True):
        blocks.append(explore_hint)

    thread_messages = [
        {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": section}}]} for section in sections[1:]
    ]
    # unfurl=False: report content is LLM-generated; never let Slack auto-fetch a link it contains.
    return SlackMessage(channel=channel, blocks=blocks, title=title, thread_messages=thread_messages, unfurl=False)


async def send_slack_ai_subscription_report(
    *,
    subscription: Subscription,
    markdown: str,
    integration: Integration,
    delivery_id: uuid.UUID,
    charts: list[dict] | None = None,
    trusted_links: tuple[tuple[str, str], ...] = (),
) -> SlackDeliveryResult:
    def build(with_charts: list[dict] | None) -> SlackMessage:
        message = _build_ai_slack_message(
            subscription, markdown, delivery_id=delivery_id, integration=integration, charts=with_charts
        )
        if trusted_links:
            message.blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(f"<{url}|{label}>" for label, url in trusted_links)},
                }
            )
        return message

    try:
        return await deliver_slack_message_data(integration, subscription, build(charts))
    except SlackApiError as exc:
        if not charts or exc.response.get("error") != "invalid_blocks":
            raise
        logger.warning(
            "ai_report.slack_charts_rejected_resending_without_them",
            subscription_id=subscription.id,
            chart_count=len(charts),
        )
        return await deliver_slack_message_data(integration, subscription, build(None))


__all__ = [
    "build_ai_subscription_report",
    "build_chart_image_urls",
    "render_ai_email_html",
    "render_pulse_delivery_appendix",
    "send_email_ai_subscription_report",
    "send_slack_ai_subscription_report",
]
