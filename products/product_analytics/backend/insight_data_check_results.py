"""Turns the counts the data checks read into a result for each check."""

from posthog.dataclasses import frozen

from products.product_analytics.backend.facade.contracts import InsightDataCheck
from products.product_analytics.backend.facade.enums import (
    InsightDataCheckAction,
    InsightDataCheckKey,
    InsightDataCheckLevel,
    InsightDataCheckMethod,
    InsightDataChecksStatus,
)

# A person cannot repeat an action this fast, but an app that sends an event twice does.
REPEAT_WINDOW_MILLISECONDS = 100
MIN_SAMPLED_EVENTS = 1_000
MIN_FINDING_EVENTS = 50
MIN_FINDING_SHARE = 0.01
MIN_DUPLICATE_EVENTS = 100
# Higher than the other share floors, because events that differ only in custom properties count as repeats.
MIN_DUPLICATE_SHARE = 0.05
PROBLEM_SHARE = 0.2

FILTER_FIX_FOR_LOCAL_EVENTS = (
    "Send local traffic to a separate project, or exclude localhost in the internal and test users filter "
    "and turn that filter on for this insight."
)
FILTER_FIX_FOR_BOTS = (
    'In the internal and test users filter, add "Traffic type is not Bot or AI Agent", '
    "and turn that filter on for this insight."
)
FIX_FOR_DUPLICATES = "Start PostHog once in your app, and send each event from one place only."


@frozen
class SampledEvents:
    rate: float
    events: int
    bot_events: int
    repeated_events: int
    distinct_ids: int

    @property
    def read_every_event(self) -> bool:
        return self.rate >= 1


@frozen
class CheckedEvents:
    # Counted on every checked day, or None when the days hold too many events to count.
    local_events: int | None
    # None when the sample was too large to read.
    sample: SampledEvents | None
    range_scale: float = 1.0

    @property
    def checked_whole_range(self) -> bool:
        return self.range_scale == 1

    @property
    def counted_every_event(self) -> bool:
        return self.checked_whole_range and self.sample is not None and self.sample.read_every_event


def _check(
    key: InsightDataCheckKey,
    level: InsightDataCheckLevel,
    result: str,
    *,
    fix: str | None = None,
    action: InsightDataCheckAction | None = None,
    method: InsightDataCheckMethod | None = None,
    events: float | None = None,
    share: float | None = None,
    scaled: bool = False,
) -> InsightDataCheck:
    return InsightDataCheck(
        key=key,
        level=level,
        name=key.label,
        result=result,
        fix=fix,
        action=action,
        method=method,
        events=None if events is None else round(events),
        share=share,
        scaled=scaled,
    )


def not_checked(key: InsightDataCheckKey, reason: str | None = None) -> InsightDataCheck:
    return _check(key, InsightDataCheckLevel.SKIPPED, reason or key.label)


def _finding_level(share: float | None) -> InsightDataCheckLevel:
    if share is not None and share >= PROBLEM_SHARE:
        return InsightDataCheckLevel.PROBLEM
    return InsightDataCheckLevel.WARNING


def _is_finding(estimate: float, share: float) -> bool:
    return estimate >= MIN_FINDING_EVENTS and share >= MIN_FINDING_SHARE


def _capitalized(text: str) -> str:
    return f"{text[0].upper()}{text[1:]}"


def _share_text(share: float, *, exact: bool) -> str:
    percent = f"{round(share * 100)}%"
    return percent if exact else f"about {percent}"


def _count_text(count: float, *, exact: bool) -> str:
    """The count in full, or rounded to two significant figures after "about" when it is an estimate."""
    rounded = round(count)
    if exact:
        return f"{rounded:,}"
    magnitude = 10 ** max(len(str(rounded)) - 2, 0)
    return f"about {round(rounded / magnitude) * magnitude:,}"


def _passed_result(things: str, found: int, estimate: float, *, scope: str) -> str:
    """A pass says where it looked, so a pass on part of the events never reads as a pass on all of them."""
    if not found:
        return f"No {things} found{scope}"
    if scope:
        return f"Almost no {things} found{scope}"
    return f"Almost no {things} found ({_count_text(estimate, exact=True)} events)"


def _in_range(count: int, checked: CheckedEvents, *, sample_rate: float = 1.0) -> float:
    return count / sample_rate * checked.range_scale


def _local_share(local_events: int, sample: SampledEvents | None) -> float | None:
    if sample is None:
        return None
    # The local count is exact and the sample is an estimate, so the share is capped at all of the events.
    events_on_checked_days = max(sample.events / sample.rate, local_events)
    return local_events / events_on_checked_days if events_on_checked_days else 0.0


def _local_development_check(checked: CheckedEvents) -> InsightDataCheck:
    key = InsightDataCheckKey.LOCAL_DEVELOPMENT
    local_events = checked.local_events
    if local_events is None:
        return not_checked(key, "Not checked because the days in this range hold too many events to count")

    estimate = _in_range(local_events, checked)
    share = _local_share(local_events, checked.sample)
    scaled = not checked.checked_whole_range
    # No minimum share: a local session also creates test persons and flag exposures, whatever its share.
    if estimate < MIN_FINDING_EVENTS:
        scope = "" if checked.checked_whole_range else " on the days checked"
        return _check(
            key,
            InsightDataCheckLevel.PASSED,
            _passed_result("local development events", local_events, estimate, scope=scope),
            method=InsightDataCheckMethod.COUNTED,
            events=estimate,
            share=share,
            scaled=scaled,
        )

    if share is not None and share >= MIN_FINDING_SHARE:
        amount = _share_text(share, exact=checked.counted_every_event)
    else:
        amount = _count_text(estimate, exact=not scaled)
    return _check(
        key,
        _finding_level(share),
        f"{_capitalized(amount)} of these events came from local development",
        fix=FILTER_FIX_FOR_LOCAL_EVENTS,
        action=InsightDataCheckAction.OPEN_FILTER_SETTINGS,
        method=InsightDataCheckMethod.COUNTED,
        events=estimate,
        share=share,
        scaled=scaled,
    )


def _sample_problem(sample: SampledEvents | None) -> str | None:
    if sample is None:
        return "Not checked because a sample of these events was too large to read"
    if not sample.events or (not sample.read_every_event and sample.events < MIN_SAMPLED_EVENTS):
        return f"Not checked because the sample has fewer than {MIN_SAMPLED_EVENTS:,} of these events"
    return None


def _sample_scope(checked: CheckedEvents, sample: SampledEvents) -> str:
    return "" if checked.counted_every_event else f" in a sample of {sample.events:,} events"


def _bot_traffic_check(checked: CheckedEvents) -> InsightDataCheck:
    key = InsightDataCheckKey.BOT_TRAFFIC
    sample = checked.sample
    problem = _sample_problem(sample)
    if sample is None or problem:
        return not_checked(key, problem)

    share = sample.bot_events / sample.events
    estimate = _in_range(sample.bot_events, checked, sample_rate=sample.rate)
    scaled = not checked.counted_every_event
    if not _is_finding(estimate, share):
        return _check(
            key,
            InsightDataCheckLevel.PASSED,
            _passed_result("bots or crawlers", sample.bot_events, estimate, scope=_sample_scope(checked, sample)),
            method=InsightDataCheckMethod.SAMPLED,
            events=estimate,
            share=share,
            scaled=scaled,
        )

    return _check(
        key,
        _finding_level(share),
        f"{_capitalized(_share_text(share, exact=not scaled))} of these events came from bots and crawlers",
        fix=FILTER_FIX_FOR_BOTS,
        action=InsightDataCheckAction.OPEN_FILTER_SETTINGS,
        method=InsightDataCheckMethod.SAMPLED,
        events=estimate,
        share=share,
        scaled=scaled,
    )


def _duplicate_events_check(checked: CheckedEvents) -> InsightDataCheck:
    key = InsightDataCheckKey.DUPLICATE_EVENTS
    sample = checked.sample
    problem = _sample_problem(sample)
    if sample is None or problem:
        return not_checked(key, problem)

    share = sample.repeated_events / sample.events
    estimate = _in_range(sample.repeated_events, checked, sample_rate=sample.rate)
    scaled = not checked.counted_every_event
    if estimate < MIN_DUPLICATE_EVENTS or share < MIN_DUPLICATE_SHARE:
        if share < MIN_FINDING_SHARE:
            result = f"No events sent twice{_sample_scope(checked, sample)}"
        else:
            result = f"Few events sent twice ({_share_text(share, exact=not scaled)})"
        return _check(
            key,
            InsightDataCheckLevel.PASSED,
            result,
            method=InsightDataCheckMethod.SAMPLED,
            events=estimate,
            share=share,
            scaled=scaled,
        )

    return _check(
        key,
        _finding_level(share),
        f"{_capitalized(_share_text(share, exact=not scaled))} of these events were sent twice "
        f"within {REPEAT_WINDOW_MILLISECONDS} ms",
        fix=FIX_FOR_DUPLICATES,
        method=InsightDataCheckMethod.SAMPLED,
        events=estimate,
        share=share,
        scaled=scaled,
    )


def evaluate_data_checks(checked: CheckedEvents) -> list[InsightDataCheck]:
    """Every check, in a fixed order, so the list shows what was checked whatever the result."""
    return [
        _local_development_check(checked),
        _bot_traffic_check(checked),
        _duplicate_events_check(checked),
    ]


def status_of(checks: list[InsightDataCheck]) -> InsightDataChecksStatus:
    levels = {check.level for check in checks}
    if InsightDataCheckLevel.PROBLEM in levels:
        return InsightDataChecksStatus.PROBLEM
    if InsightDataCheckLevel.WARNING in levels:
        return InsightDataChecksStatus.WARNING
    return InsightDataChecksStatus.PASSED
