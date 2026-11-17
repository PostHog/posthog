"""The Slack card for a firing metrics alert.

The platform's default card opens with the query and a list of raw details. This one leads with what
a reader needs first: which alert, the value against its condition, then the recent trend as a chart,
with the query below as small print.

The trend is read here, as the message goes out, with a short timeout. A history that cannot be read
costs the chart and nothing else, because the card is complete without it.
"""

import json
import math
import time
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
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
# Chart reads per worker process. They never take a slot an evaluation needs, and a full pool costs
# the chart, not the message. Process-local, so no shared store can stall a delivery.
CHART_READS_PER_PROCESS: Final = 2
_chart_reads: Final = threading.BoundedSemaphore(CHART_READS_PER_PROCESS)
# Reads started per second across the fleet. A read is cut off after HISTORY_QUERY_SECONDS, so this
# also bounds how many run at once, whatever the number of workers.
CHART_READS_PER_SECOND: Final = 5
CHART_RATE_KEY: Final = "alerts:platform:metrics:charts:started"
# Delivery's attempt is 15s, so a Redis that accepts and never answers must not hold it for the
# default socket timeout.
CHART_REDIS_SECONDS: Final = 0.5
# Every group and destination of one evaluation renders from the same range query, so it runs once.
_RESULT_CACHE_SIZE: Final = 8
# Twice the most groups a configuration can hold. A range can match far more series than the instant
# that fired, so a bigger history costs the chart rather than worker memory. With the window's 16
# steps, this bounds the cache at 8 x 200 x 16 points.
CHART_MAX_SERIES: Final = 200
# A full CHART_MAX_SERIES result with long label sets fits in well under this. A bigger body is
# dropped while it streams in, before any of it is decoded.
CHART_MAX_BYTES: Final = 1024 * 1024
# The request timeout applies per socket read, so a body that trickles in could outlast it. The whole
# read, headers to last byte, gets this long.
CHART_READ_SECONDS: Final = 2 * HISTORY_QUERY_SECONDS
_results: OrderedDict[tuple[int, str, datetime], list[dict[str, Any]] | None] = OrderedDict()


def _number(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    # NaN and infinity have no JSON form, and Slack refuses the whole message for one.
    return value if math.isfinite(value) else None


def _points(raw: list[Any]) -> list[tuple[int, float]]:
    return [(int(float(ts)), value) for ts, raw_value in raw if (value := _number(raw_value)) is not None]


def _matching_series(result: list[dict[str, Any]], transition: AnnouncedTransition) -> list[Any] | None:
    """The points of the series that is this group, or of the only series when the alert is ungrouped.

    Several series can share the group's labels. The one whose latest value is the one the alert
    reported is the one that fired, and when none or several match, no chart beats a wrong one.
    """
    labels = transition.labels
    matches = [
        series.get("values") or []
        for series in result
        if all((series.get("metric") or {}).get(key, "") == value for key, value in labels.items())
    ]
    if len(matches) <= 1:
        return matches[0] if matches else None
    if transition.value is None:
        return None
    fired = [raw for raw in matches if (points := _points(raw)) and math.isclose(points[-1][1], transition.value)]
    return fired[0] if len(fired) == 1 else None


def _query_range(team_id: int, query: str, end: datetime) -> list[dict[str, Any]] | None:
    """The range query's series, or None when it could not be read. Failures are cached too."""
    cache_key = (team_id, query, end)
    if cache_key in _results:
        _results.move_to_end(cache_key)
        return _results[cache_key]
    result = _read_range(team_id, query, end)
    _results[cache_key] = result
    if len(_results) > _RESULT_CACHE_SIZE:
        _results.popitem(last=False)
    return result


def _bounded_json(response: Any, *, deadline: float) -> dict[str, Any] | None:
    """The success body, or None for a failed response, one over CHART_MAX_BYTES, or one still arriving
    at `deadline` (a `time.monotonic()` value), read no further."""
    try:
        if response.status_code != 200:
            return None
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > CHART_MAX_BYTES or time.monotonic() > deadline:
                return None
        payload = json.loads(body)
    finally:
        response.close()
    return payload if isinstance(payload, dict) and payload.get("status") == "success" else None


def _fleet_admits() -> bool:
    """Whether the fleet has started fewer than its per-second chart reads. False when Redis cannot say."""
    from posthog import redis  # noqa: PLC0415

    key = f"{CHART_RATE_KEY}:{int(time.time())}"
    try:
        client = redis.get_client(socket_timeout=CHART_REDIS_SECONDS, socket_connect_timeout=CHART_REDIS_SECONDS)
        pipeline = client.pipeline()
        pipeline.incr(key)
        pipeline.expire(key, 2)
        started, _ = pipeline.execute()
    except Exception:
        logger.warning("metrics_alert_history_rate_unavailable", exc_info=True)
        return False
    return int(started) <= CHART_READS_PER_SECOND


def _read_range(team_id: int, query: str, end: datetime) -> list[dict[str, Any]] | None:
    # Imported here because registration runs from ready(), before models and the query layer load.
    from posthog.api.snuffle_proxy import snuffle_request  # noqa: PLC0415
    from posthog.clickhouse.client.connection import ClickHouseUser, Workload  # noqa: PLC0415

    if not _chart_reads.acquire(blocking=False):
        logger.info("metrics_alert_history_skipped_pool_full", team_id=team_id)
        return None
    if not _fleet_admits():
        _chart_reads.release()
        logger.info("metrics_alert_history_skipped_fleet_rate", team_id=team_id)
        return None
    try:
        started = time.monotonic()
        response = snuffle_request(
            team_id,
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
            workload=Workload.METRICS,
            stream=True,
        )
        payload = _bounded_json(response, deadline=started + CHART_READ_SECONDS)
        if payload is None:
            logger.info("metrics_alert_history_skipped_response", team_id=team_id, status=response.status_code)
            return None
        data = payload.get("data") or {}
        if data.get("resultType") != "matrix":
            return None
        result = data.get("result") or []
        if len(result) > CHART_MAX_SERIES:
            logger.info("metrics_alert_history_skipped_too_many_series", team_id=team_id, series=len(result))
            return None
        return result
    except Exception:
        # A chart is never worth a lost notification.
        logger.warning("metrics_alert_history_failed", team_id=team_id, exc_info=True)
        return None
    finally:
        _chart_reads.release()


def fetch_history(team_id: int, transition: AnnouncedTransition) -> list[tuple[int, float]]:
    """The group's values over the hour before the alert, oldest first. Empty on any failure."""
    query = str(transition.source_config.get("query", ""))
    if not query:
        return []
    result = _query_range(team_id, query, transition.occurred_at)
    raw = _matching_series(result, transition) if result else None
    points = _points(raw or [])[-20:]
    fired = _number(transition.value)
    if points and fired is not None:
        # Evaluation reads at the ingestion reach, which can trail the cutoff the range ends at, so
        # the point labelled "Alert" is the value that fired rather than whatever the range read last.
        points[-1] = (points[-1][0], fired)
    return points


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
    if threshold is not None and _condition_text(transition) is not None:
        # Slack caps a series name at 20 characters. The condition is in the fields above the chart.
        series.append({"name": "Threshold", "data": [{"label": label, "value": threshold} for label in labels]})
    return {
        "type": "data_visualization",
        "title": CHART_TITLE,
        "chart": {"type": "line", "series": series, "axis_config": {"categories": labels}},
    }


def _verbatim(block: dict[str, Any]) -> dict[str, Any]:
    block["elements"] = [{**element, "verbatim": True} for element in block["elements"]]
    return block


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

    # Verbatim, so a bare `@channel` in an ingested label value cannot become a broadcast.
    blocks: list[dict[str, Any]] = [header_block(title), _verbatim(context_block(" · ".join(context)))]
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
        # The backtick that would end the code span is changed, and the rest escaped and verbatim, so a
        # multi-line query that breaks the span still cannot ping, broadcast or disguise a link.
        blocks.append(_verbatim(context_block(f"Query: `{escape_slack_mrkdwn(query.replace('`', chr(39)))}`")))
    blocks.append(actions_block([SlackButton(text="View metrics", url=metrics_url(team_id))]))
    return SlackMessageContent(text=escape_slack_mrkdwn(f"Metric alert ‘{name}’ is firing"), blocks=blocks)
