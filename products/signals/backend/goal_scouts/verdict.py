import math
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFindingCode,
    ExperimentMetricEffects,
    ExperimentResults,
    ExperimentVariantEffect,
)

from ..models import SignalScoutGoalIdea

Outcome = SignalScoutGoalIdea.Outcome

MIN_SAMPLES_PER_VARIANT = 50
HARM_CONFIRM = timedelta(hours=12)
SPLIT_FINDINGS = frozenset({ExperimentHealthFindingCode.SRM})
MIXED_FINDINGS = frozenset(
    {ExperimentHealthFindingCode.MULTIPLE_VARIANTS_SHARE, ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED}
)
CONCLUSIONS = {
    Outcome.WON: "won",
    Outcome.LOST: "lost",
    Outcome.FLAT: "inconclusive",
    Outcome.HARMED: "stopped_early",
    Outcome.BROKEN: "stopped_early",
    Outcome.DROPPED: "stopped_early",
}


@frozen
class Verdict:
    outcome: str | None
    variant: str
    note: str
    facts: dict[str, Any]


def _waiting(note: str, facts: dict[str, Any]) -> Verdict:
    return Verdict(outcome=None, variant="", note=note, facts=facts)


def _decided(outcome: str, variant: str, note: str, facts: dict[str, Any]) -> Verdict:
    return Verdict(outcome=outcome, variant=variant, note=note, facts=facts)


def _matches(name: str, wanted: str) -> bool:
    ordinal, separator, rest = name.partition(". ")
    return name == wanted or bool(separator and ordinal.isdecimal() and rest == wanted)


def _interval(variant: ExperimentVariantEffect) -> tuple[float, float] | None:
    return (variant.low, variant.high) if variant.low is not None and variant.high is not None else None


def _harmed(secondary: tuple[ExperimentMetricEffects, ...], guardrails: list[dict[str, Any]]) -> list[str]:
    harmed: set[str] = set()
    for guard in guardrails:
        effects = next((item for item in secondary if _matches(item.name, guard["name"])), None)
        limit = float(guard.get("max_regression", 0.05))
        for variant in effects.variants if effects else ():
            if variant.key == "control" or variant.low is None or variant.high is None:
                continue
            if guard.get("direction", "increase") == "decrease" and variant.low > limit:
                harmed.add(guard["name"])
            if guard.get("direction", "increase") == "increase" and variant.high < -limit:
                harmed.add(guard["name"])
    return sorted(harmed)


def verdict(
    results: ExperimentResults,
    *,
    direction: str,
    guardrails: list[dict[str, Any]],
    run_days: int,
    exposed_at: datetime | None,
    now: datetime,
) -> Verdict:
    exposures = {key: float(value) for key, value in results.exposures.items() if not key.startswith("$")}
    tests = sorted(key for key in set(results.variants or exposures) - {"control"} if not key.startswith("$"))
    facts: dict[str, Any] = {
        "exposures": {key: int(value) for key, value in exposures.items()},
        "start_date": results.start_date.isoformat() if results.start_date else None,
    }
    if results.start_date is None:
        return _waiting("The experiment has not started.", facts)
    if not sum(exposures.values()):
        return _waiting("Waiting for the first people to see it.", facts)
    smallest = int(min((exposures.get(key, 0) for key in ["control", *tests]), default=0))
    facts["smallest_sample"] = smallest
    rows = {variant.key: variant for variant in (results.primary[0].variants if results.primary else ())}
    facts["primary"] = {
        key: [rows[key].low, rows[key].high] if key in rows and rows[key].low is not None else None for key in tests
    }
    harmed = _harmed(results.secondary, guardrails)
    facts["harmed_guardrails"] = harmed
    if smallest < MIN_SAMPLES_PER_VARIANT:
        return _waiting(
            f"Collecting data: {smallest} of {MIN_SAMPLES_PER_VARIANT} people in the smallest group.", facts
        )
    if SPLIT_FINDINGS & set(results.finding_codes):
        split = ", ".join(f"{key} {int(exposures.get(key, 0))}" for key in ["control", *tests])
        return _decided(
            Outcome.BROKEN,
            "control",
            f"The variants got uneven traffic ({split}). The change may be broken. Check the build before you try it again.",
            facts,
        )
    if MIXED_FINDINGS & set(results.finding_codes):
        return _decided(
            Outcome.BROKEN,
            "control",
            "Many people saw more than one variant, so the result is not reliable. The flag code may read the variant too early. Check the build before you try it again.",
            facts,
        )
    if harmed:
        return _decided(Outcome.HARMED, "control", f"{', '.join(harmed)} got worse.", facts)
    left = timedelta(days=run_days) - (now - (exposed_at or results.start_date))
    if left > timedelta(0):
        days_left = math.ceil(left.total_seconds() / 86400)
        return _waiting(f"About {days_left} more {'day' if days_left == 1 else 'days'} before a verdict.", facts)
    decreasing = direction == "decrease"
    intervals = {
        key: bounds for key in tests if key in rows and rows[key].significant and (bounds := _interval(rows[key]))
    }
    better = [key for key, (low, high) in intervals.items() if (high < 0 if decreasing else low > 0)]
    worse = [key for key, (low, high) in intervals.items() if (low > 0 if decreasing else high < 0)]
    if better:
        best = max(better, key=lambda key: abs(sum(intervals[key])))
        return _decided(Outcome.WON, best, f"The {best} variant improved the primary metric.", facts)
    if tests and len(worse) == len(tests):
        return _decided(Outcome.LOST, "control", "Every test variant made the primary metric worse.", facts)
    return _decided(Outcome.FLAT, "control", f"No clear effect after {run_days} days.", facts)


def confirm_harm(previous: dict[str, Any], result: Verdict, now: datetime) -> Verdict:
    seen = previous.get("harm_seen_at")
    if result.outcome != Outcome.HARMED:
        return replace(result, facts={**result.facts, "harm_seen_at": None}) if seen else result
    if seen and now - datetime.fromisoformat(seen) >= HARM_CONFIRM:
        return result
    hours = int(HARM_CONFIRM.total_seconds() // 3600)
    return Verdict(
        outcome=None,
        variant="",
        note=f"{result.note} The scout checks again within {hours} hours before it stops the experiment.",
        facts={**result.facts, "harm_seen_at": seen or now.isoformat()},
    )
