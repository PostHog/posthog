from dataclasses import dataclass, field

import structlog

from posthog.schema import WebStatsBreakdown

from posthog.models import Team

from products.web_analytics.backend.weekly_digest import DigestFilterSpec, _breakdown_from_spec

logger = structlog.get_logger(__name__)

SEGMENTS_PER_DIMENSION = 10


@dataclass(frozen=True)
class _Dimension:
    key: str  # internal/label name, e.g. "channel"
    breakdown: WebStatsBreakdown


# Cheap, precompute-eligible dimensions plus entry page (the most actionable, slightly costlier).
_DIMENSIONS: list[_Dimension] = [
    _Dimension("channel", WebStatsBreakdown.INITIAL_CHANNEL_TYPE),
    _Dimension("entry page", WebStatsBreakdown.INITIAL_PAGE),
    _Dimension("device type", WebStatsBreakdown.DEVICE_TYPE),
    _Dimension("country", WebStatsBreakdown.COUNTRY),
    _Dimension("referrer", WebStatsBreakdown.INITIAL_REFERRING_DOMAIN),
]


@dataclass
class AttributionFinding:
    dimension: str
    segment: str
    current: int
    previous: int | None
    delta: int
    contribution_pct: float | None  # share of the overall metric delta this segment accounts for


@dataclass
class AttributionResult:
    metric: str
    overall_current: float
    overall_previous: float | None
    overall_delta: float
    primary_driver: AttributionFinding | None
    per_dimension: list[AttributionFinding] = field(default_factory=list)


def _top_driver_for_dimension(
    rows: list[dict], dimension: str, *, overall_delta: float, direction: int
) -> AttributionFinding | None:
    """The single segment that moved most in the same direction as the overall change."""
    best: AttributionFinding | None = None
    for r in rows:
        seg_delta = (r["visitors_current"] or 0) - (r["visitors_previous"] or 0)
        if seg_delta * direction <= 0:  # ignore segments moving against (or not with) the overall change
            continue
        if best is None or abs(seg_delta) > abs(best.delta):
            best = AttributionFinding(
                dimension=dimension,
                segment=str(r["value"]),
                current=r["visitors_current"] or 0,
                previous=r["visitors_previous"],
                delta=seg_delta,
                contribution_pct=round(100 * seg_delta / overall_delta, 1),
            )
    return best


def attribute_change(
    team: Team, spec: DigestFilterSpec, digest: dict, metric: str = "visitors"
) -> AttributionResult | None:
    """Decompose a metric's period-over-period delta across dimensions to find the segment driving it.

    Attribution is always in terms of unique visitors (the breakdown metric). Returns None when there's no
    meaningful change to attribute (no previous period, or a flat metric). Never raises.
    """
    try:
        metric_data = digest.get(metric)
        if not isinstance(metric_data, dict):
            return None
        current = metric_data.get("current")
        previous = metric_data.get("previous")
        if current is None or previous is None:
            return None
        overall_delta = current - previous
        if overall_delta == 0:
            return None
        direction = 1 if overall_delta > 0 else -1

        per_dimension: list[AttributionFinding] = []
        for dim in _DIMENSIONS:
            rows = _breakdown_from_spec(team, spec, dim.breakdown, limit=SEGMENTS_PER_DIMENSION)
            finding = _top_driver_for_dimension(rows, dim.key, overall_delta=overall_delta, direction=direction)
            if finding is not None:
                per_dimension.append(finding)

        return AttributionResult(
            metric=metric,
            overall_current=current,
            overall_previous=previous,
            overall_delta=overall_delta,
            primary_driver=max(per_dimension, key=lambda f: abs(f.delta)) if per_dimension else None,
            per_dimension=per_dimension,
        )
    except Exception:
        logger.exception("change attribution failed", team_id=team.pk)
        return None
