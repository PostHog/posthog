"""Normalize an archived Harmonic GraphQL company payload into the REST shape score_v05 consumes.

The fetch archive (OrganizationEnrichmentFetch.payload) holds GraphQL
`enrichCompanyByIdentifiers.company` responses verbatim: camelCase keys and raw
tractionMetrics time series. Harmonic's REST API — which the V0.5 rules were validated
against — precomputes horizon blocks (`90d_ago.percent_change` etc.) that the GraphQL
schema does not expose, so this module derives them from the archived series instead.

Kept separate from the scorer so the scorer stays a line-for-line port of the validated
reference, and separate from transform.py because the scorer needs payload fields
(description, per-tag types, the series) that deliberately never became EnrichmentFields.

As-of semantics for growth, matching the validated backtest derivation: the value at a
horizon is the last observation at or before that point — no interpolation, no peeking
forward — and growth is percent change from that value to the latest observation. A
series too sparse to cover the horizon yields None (unknown), never 0.
"""

import datetime as dt
from typing import Any, Optional

WEB_TRAFFIC_GROWTH_DAYS = 90
HEADCOUNT_GROWTH_DAYS = 180


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _parse_series(metric_block: dict[str, Any]) -> list[tuple[dt.datetime, float]]:
    """Parse a GraphQL tractionMetrics series into sorted (timestamp, value) pairs."""
    points = []
    for point in _list(metric_block.get("metrics")):
        point = _dict(point)
        timestamp, value = point.get("timestamp"), point.get("metricValue")
        if not isinstance(timestamp, str) or not isinstance(value, (int, float)):
            continue
        try:
            parsed = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        points.append((parsed, float(value)))
    points.sort(key=lambda pair: pair[0])
    return points


def _value_asof(points: list[tuple[dt.datetime, float]], when: Optional[dt.datetime]) -> Optional[float]:
    """Last observation at or before `when` (no interpolation, no peeking forward)."""
    if not points:
        return None
    if when is None:
        return points[-1][1]
    eligible = [value for timestamp, value in points if timestamp <= when]
    return eligible[-1] if eligible else None


def _growth(points: list[tuple[dt.datetime, float]], days: int) -> tuple[Optional[float], Optional[int]]:
    """(percent_change, absolute change) over the `days` window ending at the latest observation."""
    if not points:
        return None, None
    end_at = points[-1][0]
    end = _value_asof(points, end_at)
    start = _value_asof(points, end_at - dt.timedelta(days=days))
    if end is None or start is None or start <= 0:
        return None, None
    return round((end - start) / start * 100.0, 1), int(end - start)


def _latest(metric_block: dict[str, Any]) -> Optional[int]:
    value = metric_block.get("latestMetricValue")
    return int(value) if isinstance(value, (int, float)) else None


def _traction_metric(traction: dict[str, Any], graphql_name: str, growth_days: Optional[int]) -> dict[str, Any]:
    block = _dict(traction.get(graphql_name))
    normalized: dict[str, Any] = {"latest_metric_value": _latest(block)}
    if growth_days is not None:
        percent_change, change = _growth(_parse_series(block), growth_days)
        normalized[f"{growth_days}d_ago"] = {"percent_change": percent_change, "change": change}
    return normalized


def _investors(investors: Any) -> list[dict[str, Any]]:
    # Company entries carry `name`, Person (angel) entries carry `fullName`; fold to `name`,
    # which is the key the scorer reads.
    return [
        {"name": name}
        for investor in _list(investors)
        if isinstance(investor, dict) and isinstance(name := investor.get("name") or investor.get("fullName"), str)
    ]


def _tags_v2(tags_v2: Any) -> list[dict[str, Any]]:
    return [
        {"display_value": tag.get("displayValue"), "type": tag.get("type")}
        for tag in _list(tags_v2)
        if isinstance(tag, dict)
    ]


def normalize_graphql_company(payload: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Map an archived GraphQL company payload to the scorer's REST-ish shape.

    Returns None for anything that is not a matched company — a missing payload, the
    archived miss sentinel ({"companyFound": False}), or an empty dict — so callers can
    hand the result straight to score_company, which reads None as not_found.
    """
    if not payload or not isinstance(payload, dict) or payload.get("companyFound") is False:
        return None

    funding = _dict(payload.get("funding"))
    traction = _dict(payload.get("tractionMetrics"))
    headcount = payload.get("headcount")

    return {
        "company_type": payload.get("companyType"),
        "headcount": int(headcount) if isinstance(headcount, (int, float)) else None,
        "description": payload.get("description"),
        "funding": {
            "funding_total": funding.get("fundingTotal"),
            "investors": _investors(funding.get("investors")),
        },
        "funding_attribute_null_status": payload.get("fundingAttributeNullStatus"),
        "tags_v2": _tags_v2(payload.get("tagsV2")),
        "traction_metrics": {
            "web_traffic": _traction_metric(traction, "webTraffic", WEB_TRAFFIC_GROWTH_DAYS),
            "headcount": _traction_metric(traction, "headcount", HEADCOUNT_GROWTH_DAYS),
            "headcount_engineering": _traction_metric(traction, "headcountEngineering", None),
        },
    }
