import re
import math
import statistics
from datetime import date, timedelta

from ..facade.contracts import HighlightDetection

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
BAD_METRIC = re.compile(
    r"(?i)(error|fail|latency|duration|(load|response|build|query|wait) time|time to|p50|p90|p95|p99|cost|spend|churn"
    r"|bounce|cancel|refund|exception|crash|timeout|lost|contraction|downgrade|abort|(?<![a-z])rage)"
)
UNKNOWN_DIRECTION = re.compile(r"(?i)(share|split| vs\.? |(?<![a-z])ratios?(?![a-z])|%|percent|rate by)")
UNCLEAR_LABEL = re.compile(
    r"(?i)^(other|others|series \d+|null|none|unknown|\$.*|(sum|count|avg|unique|total)_.*)$|, series \d+$"
)
MONEY = re.compile(r"(?i)(revenue|\barr\b|\bmrr\b|\bnrr\b|spend|cost|usd|\$(?![a-z_])|invoice)")
MAX_FILLED_DAYS = 120


def complete(points: list[tuple[date, float]], period: str, today: date) -> list[tuple[date, float]]:
    if period == "day":
        return [(d, v) for d, v in points if d < today]
    if period == "week":
        return [(d, v) for d, v in points if d + timedelta(days=7) <= today]
    return [(d, v) for d, v in points if (d.year, d.month) < (today.year, today.month)]


def stale(points: list[tuple[date, float]], period: str, today: date) -> bool:
    usable = complete(points, period, today)
    if not usable:
        return True
    last = usable[-1][0]
    step = {"day": timedelta(days=1), "week": timedelta(days=7)}.get(period)
    after = last + step if step else (last.replace(day=1) + timedelta(days=32)).replace(day=1)
    return bool(complete([(after, 0.0)], period, today))


def fill_days(points: list[tuple[date, float]]) -> list[tuple[date, float]]:
    if not points:
        return points
    known = dict(points)
    end = points[-1][0]
    day, out = max(points[0][0], end - timedelta(days=MAX_FILLED_DAYS)), []
    while day <= end:
        out.append((day, known.get(day, 0.0)))
        day += timedelta(days=1)
    return out


def windows(points: list[tuple[date, float]], period: str, average: bool = False) -> list[float]:
    values = [v for _, v in points]
    if period != "day":
        return values
    count = len(values) // 7
    totals = [sum(values[len(values) - 7 * i : len(values) - 7 * (i - 1)]) for i in range(count, 0, -1)]
    return [total / 7 for total in totals] if average else totals


def zscore(last: float, prior: list[float]) -> float | None:
    if len(prior) < 2:
        return None
    spread, mean = statistics.pstdev(prior), statistics.mean(prior)
    if spread == 0:
        return None if last == mean else math.copysign(9.9, last - mean)
    return (last - mean) / spread


def detect(
    points: list[tuple[date, float]], period: str, today: date, average: bool = False
) -> tuple[list[HighlightDetection], list[float]]:
    usable = complete(points, period, today)
    found: list[HighlightDetection] = []
    if period == "day":
        usable = fill_days(usable)
        daily = [v for _, v in usable]
        if len(daily) >= 17 and all(v == 0 for v in daily[-3:]) and statistics.mean(daily[-17:-3]) >= 100:
            found.append(HighlightDetection(kind="went_quiet", strength=0.7, direction=-1))
        found.extend(_same_weekday(usable))
    values = windows(usable, period, average)
    if len(values) >= 6 and all(v == 0 for v in values[-6:]) and any(v != 0 for v in values[:-6]):
        found.append(HighlightDetection(kind="flatline", strength=0.6, direction=-1))
    if len(values) < 4 or values[-1] == 0:
        return found, values
    last, previous = values[-1], values[-2]
    changes = [values[i] / values[i - 1] - 1 for i in range(max(1, len(values) - 9), len(values)) if values[i - 1]]
    change_z = zscore(changes[-1], changes[:-1]) if len(changes) >= 4 and previous else None
    if change_z is not None and abs(change_z) >= 2 and abs(changes[-1]) >= 0.1:
        found.append(
            HighlightDetection(
                kind="spike",
                strength=min(1.0, 0.6 + 0.1 * (abs(change_z) - 2)),
                direction=1 if changes[-1] > 0 else -1,
            )
        )
    steps = [values[-3] - values[-4], values[-2] - values[-3], values[-1] - values[-2]]
    if (
        (all(s > 0 for s in steps) or all(s < 0 for s in steps))
        and values[-4]
        and abs(values[-1] / values[-4] - 1) >= 0.2
    ):
        direction = 1 if steps[0] > 0 else -1
        history = [values[i] - values[i - 1] for i in range(max(1, len(values) - 9), len(values) - 3)]
        usual = (sum(1 for h in history if h > 0) - sum(1 for h in history if h < 0)) if len(history) >= 3 else 0
        if usual * direction <= 0:
            found.append(HighlightDetection(kind="trend", strength=0.6, direction=direction))
    earlier = statistics.mean(values[:-1][-3:])
    if earlier > 0 and (last / earlier >= 3 or last / earlier <= 1 / 3) and max(last, earlier) >= 100:
        found.append(HighlightDetection(kind="level_shift", strength=0.8, direction=1 if last > earlier else -1))
    return found, values


def _same_weekday(usable: list[tuple[date, float]]) -> list[HighlightDetection]:
    start = next((i for i, (_, v) in enumerate(usable) if v != 0), 0)
    days = usable[start:]
    if len(days) < 8:
        return []
    last_day, last_value = days[-1]
    same = [v for d, v in days[:-1] if d.weekday() == last_day.weekday()]
    use_same = len(same) >= 3
    base = same[-4:] if use_same else [v for _, v in days[-8:-1]]
    score, mean = zscore(last_value, base), statistics.mean(base)
    if score is None or abs(score) < 3 or not mean or abs(last_value / mean - 1) < 0.15:
        return []
    if abs(last_value - mean) < max(5, 3 * math.sqrt(max(mean, 1))):
        return []
    return [
        HighlightDetection(
            kind="same_weekday",
            strength=0.7,
            direction=1 if last_value > mean else -1,
            pct=(last_value / mean - 1) * 100,
            now=last_value,
            usual=mean,
            weekday=WEEKDAYS[last_day.weekday()],
            same_weekday=use_same,
        )
    ]
