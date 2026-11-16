"""The Slack card for a firing metrics alert.

The platform's default card opens with the query and a list of raw details. This one leads with what
a reader needs first: which alert, the value against its condition, then the recent trend as a chart,
with the query below as small print.

The trend is read here, as the message goes out, with a short timeout. A history that cannot be read
costs the chart and nothing else, because the card is complete without it.
"""

from datetime import timedelta
from typing import Any, Final

import structlog

from posthog.slack.channels import (
    MAX_HEADER_CHARS,
    SlackButton,
    actions_block,
    clip_text,
    context_block,
    fields_block,
    header_block,
)
from posthog.slack.formatting import escape_slack_mrkdwn

from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    MessageImage,
    MessageLink,
    SlackMessageContent,
)
from products.metrics.backend.alerts.wording import OPERATOR_SYMBOLS, metrics_url

logger = structlog.get_logger(__name__)

HISTORY_WINDOW: Final = timedelta(minutes=60)
# Sixteen points, under the twenty a Slack chart series holds.
HISTORY_STEP_SECONDS: Final = 240
# The send path has a 10-second budget that the post itself mostly spends.
HISTORY_QUERY_SECONDS: Final = 1
MAX_QUERY_CHARS: Final = 500
CHART_TITLE: Final = "Last 60 min"


def _number(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _matching_series(result: list[dict[str, Any]], labels: dict[str, str]) -> list[Any] | None:
    """The points of the series that is this group, or of the only series when the alert is ungrouped."""
    for series in result:
        metric = {key: value for key, value in (series.get("metric") or {}).items() if key != "__name__"}
        if all(metric.get(key) == value for key, value in labels.items()):
            return series.get("values") or []
    return None


def fetch_history(team_id: int, transition: AnnouncedTransition) -> list[tuple[int, float]]:
    """The group's values over the hour before the alert, oldest first. Empty on any failure."""
    query = str(transition.source_config.get("query", ""))
    if not query:
        return []
    # Imported here because registration runs from ready(), before models and the query layer load.
    from posthog.clickhouse.client.connection import ClickHouseUser  # noqa: PLC0415
    from posthog.models import Team  # noqa: PLC0415

    from products.metrics.backend.promql import snuffle_payload  # noqa: PLC0415

    try:
        team = Team.objects.get(id=team_id)
        end = transition.occurred_at
        payload = snuffle_payload(
            team,
            "POST",
            "/api/v1/query_range",
            data={
                "query": query,
                "start": str((end - HISTORY_WINDOW).timestamp()),
                "end": str(end.timestamp()),
                "step": str(HISTORY_STEP_SECONDS),
                "timeout": f"{HISTORY_QUERY_SECONDS}s",
            },
            timeout=HISTORY_QUERY_SECONDS,
            ch_user=ClickHouseUser.ALERTS_PLATFORM_METRICS,
        )
        data = payload.get("data") or {}
        if data.get("resultType") != "matrix":
            return []
        raw = _matching_series(data.get("result") or [], transition.labels)
    except Exception:
        # A chart is never worth a lost notification.
        logger.warning("metrics_alert_history_failed", team_id=team_id, exc_info=True)
        return []
    points = [(int(float(ts)), value) for ts, raw_value in raw or [] if (value := _number(raw_value)) is not None]
    return points[-20:]


def _condition_text(transition: AnnouncedTransition) -> str | None:
    condition = transition.condition
    if condition.get("kind", "threshold") != "threshold" or "threshold" not in condition:
        return None
    threshold = _number(condition["threshold"])
    if threshold is None:
        return None
    operator = OPERATOR_SYMBOLS.get(str(condition.get("operator")), str(condition.get("operator")))
    return f"{operator} {threshold:g}"


def _label(seconds_before: int) -> str:
    return "Alert" if seconds_before <= 0 else f"{round(seconds_before / 60)}m ago"


def chart_block(history: list[tuple[int, float]], transition: AnnouncedTransition) -> dict[str, Any] | None:
    """A native Slack line chart of the history, with the threshold as a second line."""
    if len(history) < 2:
        return None
    last = history[-1][0]
    labels = [_label(last - ts) for ts, _ in history]
    series: list[dict[str, Any]] = [
        {"name": "Value", "data": [{"label": label, "value": value} for label, (_, value) in zip(labels, history)]}
    ]
    threshold = _number(transition.condition.get("threshold"))
    condition = _condition_text(transition)
    if threshold is not None and condition is not None:
        series.append(
            {"name": f"Threshold ({condition})", "data": [{"label": label, "value": threshold} for label in labels]}
        )
    return {
        "type": "data_visualization",
        "title": CHART_TITLE,
        "chart": {"type": "line", "series": series, "axis_config": {"categories": labels}},
    }


def render_metrics_slack_message(
    *,
    team_id: int,
    transition: AnnouncedTransition,
    alert_name: str,
    alert_url: str,
    project: MessageLink | None,
    image: MessageImage | None,
) -> SlackMessageContent | None:
    # A resolve, a failed check and the rest keep the platform's layout, which already says them well.
    if transition.kind != AlertEventKind.FIRING:
        return None
    name = clip_text(alert_name, MAX_HEADER_CHARS - 2)
    title = f"🔴 {name}"
    group = ", ".join(f"{key}={value}" for key, value in sorted(transition.labels.items()))
    context = ["*FIRING*"]
    if group:
        context.append(escape_slack_mrkdwn(clip_text(group, 300)))
    if project is not None:
        context.append(f"<{project.url}|{escape_slack_mrkdwn(project.label)}>")
    stamp = int(transition.occurred_at.timestamp())
    context.append(f"<!date^{stamp}^{{date_short_pretty}} {{time}}|{transition.occurred_at:%b %d %H:%M} UTC>")

    fields = []
    if transition.value is not None:
        fields.append(f"*Value*\n{transition.value:g}")
    condition = _condition_text(transition)
    if condition is not None:
        fields.append(f"*Fires when*\n{escape_slack_mrkdwn(condition)}")

    blocks: list[dict[str, Any]] = [header_block(title), context_block(" · ".join(context))]
    if fields:
        fields_section = fields_block(fields)
        # Verbatim, so a bare `@here` in text cannot become a broadcast.
        fields_section["fields"] = [{**field, "verbatim": True} for field in fields_section["fields"]]
        blocks.append(fields_section)
    chart = chart_block(fetch_history(team_id, transition), transition)
    if chart is not None:
        blocks.append(chart)
    query = clip_text(str(transition.source_config.get("query", "")), MAX_QUERY_CHARS)
    if query:
        # Inside a code span nothing is parsed, so only the backtick that would end it is changed.
        blocks.append(context_block(f"Query: `{query.replace('`', chr(39))}`"))
    blocks.append(actions_block([SlackButton(text="View metrics", url=metrics_url(team_id))]))
    return SlackMessageContent(text=escape_slack_mrkdwn(f"Metric alert ‘{name}’ is firing"), blocks=blocks)
