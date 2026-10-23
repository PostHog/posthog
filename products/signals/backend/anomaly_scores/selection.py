"""The order in which a scoring tick picks insights, set by the `anomaly-scoring` flag payload.

`weighted` samples insights in proportion to usage × staleness, so most of the per-tick query budget goes to
insights people look at. Weight grows while an insight waits, so an insight nobody views is picked rarely but
never starves. `uniform` picks the stalest insight first, so every insight gets the same share.
"""

import math
import hashlib
from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from posthog.schema import IntervalType

from posthog.dataclasses import frozen

from products.alerts.backend.facade.api import insight_ids_with_enabled_alerts
from products.product_analytics.backend.facade.api import viewer_counts_by_insight
from products.signals.backend.anomaly_scores.scoring import bucket_end

USAGE_WINDOW = timedelta(days=30)


class Weighting(StrEnum):
    UNIFORM = "uniform"
    WEIGHTED = "weighted"


@frozen
class SelectionConfig:
    weighting: Weighting = Weighting.WEIGHTED
    # Gives insights nobody views a small chance, so we can see how the tail scores. 0 leaves them out.
    usage_floor: float = 1.0
    alert_bonus: float = 5.0


@frozen
class InsightUsage:
    viewers: int
    has_enabled_alert: bool


@frozen
class Candidate:
    insight_id: int
    interval: IntervalType
    # The newest bucket scored for any series of the insight. None when the insight was never scored.
    newest_scored_bucket: datetime | None
    usage: InsightUsage


def _non_negative(value: Any, default: float) -> float:
    # `bool` is an `int` subclass, and `true` is not a number.
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        return default
    return float(value)


def parse_selection_config(payload: Any) -> SelectionConfig:
    """The selection fields of the `anomaly-scoring` payload. An invalid field gets its default."""
    defaults = SelectionConfig()
    if not isinstance(payload, dict):
        return defaults
    weighting = payload.get("weighting")
    return SelectionConfig(
        weighting=Weighting(weighting) if weighting in tuple(Weighting) else defaults.weighting,
        usage_floor=_non_negative(payload.get("usage_floor"), defaults.usage_floor),
        alert_bonus=_non_negative(payload.get("alert_bonus"), defaults.alert_bonus),
    )


def insight_usage(*, team_id: int, insight_ids: Collection[int], now: datetime) -> dict[int, InsightUsage]:
    viewers = viewer_counts_by_insight(team_id=team_id, insight_ids=insight_ids, since=now - USAGE_WINDOW)
    alerted = insight_ids_with_enabled_alerts(team_id=team_id, insight_ids=insight_ids)
    return {
        insight_id: InsightUsage(viewers=viewers.get(insight_id, 0), has_enabled_alert=insight_id in alerted)
        for insight_id in insight_ids
    }


def staleness(candidate: Candidate, *, now: datetime, max_staleness: int) -> int:
    """Completed buckets after the newest scored one, up to ``max_staleness``.

    A never-scored insight counts as ``max_staleness``. Pass the backfill cap: one pick scores at most that
    many buckets, so a longer wait adds nothing to score.
    """
    if candidate.newest_scored_bucket is None:
        return max_staleness
    count = 0
    start = bucket_end(candidate.newest_scored_bucket, candidate.interval)
    while count < max_staleness and bucket_end(start, candidate.interval) <= now:
        count += 1
        start = bucket_end(start, candidate.interval)
    return count


def weight(candidate: Candidate, *, config: SelectionConfig, now: datetime, max_staleness: int) -> float:
    usage = config.usage_floor + candidate.usage.viewers
    if candidate.usage.has_enabled_alert:
        usage += config.alert_bonus
    return usage * staleness(candidate, now=now, max_staleness=max_staleness)


def pick_order(
    candidates: Sequence[Candidate],
    *,
    config: SelectionConfig,
    tick_start: datetime,
    max_staleness: int,
) -> list[int]:
    """Insight ids in the order the tick scores them. Any prefix is a valid pick for a smaller budget.

    Candidates with no completed bucket to score are left out. In weighted mode, so are zero-weight candidates.
    """
    if config.weighting == Weighting.UNIFORM:
        return _stalest_first(candidates, now=tick_start, max_staleness=max_staleness)
    return _weighted_sample(candidates, config=config, tick_start=tick_start, max_staleness=max_staleness)


def _unit_interval(*parts: object) -> float:
    """A uniform number strictly between 0 and 1, fixed by ``parts``."""
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode()).digest()
    # 53 bits fit a float exactly, so the result never rounds to 0 or 1.
    return ((int.from_bytes(digest[:8], "big") >> 11) + 0.5) / 2**53


def _weighted_sample(
    candidates: Sequence[Candidate], *, config: SelectionConfig, tick_start: datetime, max_staleness: int
) -> list[int]:
    # Efraimidis–Spirakis: sorting by u ** (1 / weight) gives a weighted sample without replacement.
    # log(u) / weight sorts the same way and keeps precision when the weight is large.
    keyed: list[tuple[float, int]] = []
    for candidate in candidates:
        candidate_weight = weight(candidate, config=config, now=tick_start, max_staleness=max_staleness)
        if candidate_weight > 0:
            u = _unit_interval(candidate.insight_id, tick_start.isoformat())
            keyed.append((math.log(u) / candidate_weight, candidate.insight_id))
    keyed.sort(key=lambda item: (-item[0], item[1]))
    return [insight_id for _, insight_id in keyed]


def _stalest_first(candidates: Sequence[Candidate], *, now: datetime, max_staleness: int) -> list[int]:
    due = [candidate for candidate in candidates if staleness(candidate, now=now, max_staleness=max_staleness) > 0]
    # A hashed order for never-scored insights, so first coverage does not favor any group of insights.
    never_scored = sorted(
        (candidate.insight_id for candidate in due if candidate.newest_scored_bucket is None),
        key=_unit_interval,
    )
    scored = sorted(
        (candidate for candidate in due if candidate.newest_scored_bucket is not None),
        key=lambda candidate: (candidate.newest_scored_bucket, candidate.insight_id),
    )
    return never_scored + [candidate.insight_id for candidate in scored]
