"""Turns the counts the data checks read into a level for each check."""

from posthog.dataclasses import frozen

from products.product_analytics.backend.facade.contracts import InsightDataCheck
from products.product_analytics.backend.facade.enums import (
    InsightDataCheckAction,
    InsightDataCheckKey,
    InsightDataCheckLevel,
    InsightDataCheckMethod,
    InsightDataCheckSkipReason,
    InsightDataChecksStatus,
)

MIN_SAMPLED_EVENTS = 1_000
MIN_FINDING_EVENTS = 50
MIN_FINDING_SHARE = 0.01
MIN_DUPLICATE_EVENTS = 100
# Higher than the other share floors, because events that differ only in custom properties count as repeats.
MIN_DUPLICATE_SHARE = 0.05
PROBLEM_SHARE = 0.2


@frozen
class Skipped:
    reason: InsightDataCheckSkipReason


@frozen
class LocalEvents:
    count: int
    top_hosts: list[str]
    top_events: list[str]


@frozen
class SampledEvents:
    rate: float
    events: int
    distinct_ids: int
    bot_events: int
    top_bots: list[str]
    top_bot_events: list[str]
    repeated_events: int
    top_repeated_events: list[str]

    @property
    def read_every_event(self) -> bool:
        return self.rate >= 1


@frozen
class CheckedEvents:
    local: LocalEvents | Skipped
    sample: SampledEvents | Skipped
    insight_filters_traffic_type: bool = False


def not_checked(key: InsightDataCheckKey, reason: InsightDataCheckSkipReason | None = None) -> InsightDataCheck:
    return InsightDataCheck(key=key, level=InsightDataCheckLevel.SKIPPED, skip_reason=reason)


def _finding_level(share: float | None) -> InsightDataCheckLevel:
    if share is not None and share >= PROBLEM_SHARE:
        return InsightDataCheckLevel.PROBLEM
    return InsightDataCheckLevel.WARNING


def _usable_sample(sample: SampledEvents | Skipped) -> SampledEvents | Skipped:
    if isinstance(sample, Skipped):
        return sample
    if not sample.events or (not sample.read_every_event and sample.events < MIN_SAMPLED_EVENTS):
        return Skipped(reason=InsightDataCheckSkipReason.TOO_FEW_SAMPLED_EVENTS)
    return sample


def _local_share(local_events: int, sample: SampledEvents | Skipped) -> float | None:
    """The share of local events, or None when the sample is too small to estimate the events checked."""
    usable = _usable_sample(sample)
    if isinstance(usable, Skipped):
        return None
    # The local count is exact and the sample is an estimate, so the share is capped at all of the events.
    events_checked = max(usable.events / usable.rate, local_events)
    return local_events / events_checked


def _local_development_check(checked: CheckedEvents) -> InsightDataCheck:
    key = InsightDataCheckKey.LOCAL_DEVELOPMENT
    local = checked.local
    if isinstance(local, Skipped):
        return not_checked(key, local.reason)

    share = _local_share(local.count, checked.sample)
    # No minimum share: a local session also creates test persons and flag exposures, whatever its share.
    is_finding = local.count >= MIN_FINDING_EVENTS
    return InsightDataCheck(
        key=key,
        level=_finding_level(share) if is_finding else InsightDataCheckLevel.PASSED,
        method=InsightDataCheckMethod.COUNTED,
        events=local.count,
        share=share,
        action=InsightDataCheckAction.OPEN_FILTER_SETTINGS if is_finding else None,
        top_events=local.top_events,
        top_hosts=local.top_hosts,
    )


def _bot_traffic_check(checked: CheckedEvents) -> InsightDataCheck:
    key = InsightDataCheckKey.BOT_TRAFFIC
    # The insight's own traffic type filter already decides which bots it keeps, so a bot check adds nothing.
    if checked.insight_filters_traffic_type:
        return not_checked(key, InsightDataCheckSkipReason.FILTERED_BY_TRAFFIC_TYPE)

    sample = _usable_sample(checked.sample)
    if isinstance(sample, Skipped):
        return not_checked(key, sample.reason)

    share = sample.bot_events / sample.events
    estimate = sample.bot_events / sample.rate
    is_finding = estimate >= MIN_FINDING_EVENTS and share >= MIN_FINDING_SHARE
    return InsightDataCheck(
        key=key,
        level=_finding_level(share) if is_finding else InsightDataCheckLevel.PASSED,
        method=InsightDataCheckMethod.SAMPLED,
        events=round(estimate),
        share=share,
        scaled=not sample.read_every_event,
        action=InsightDataCheckAction.OPEN_FILTER_SETTINGS if is_finding else None,
        top_events=sample.top_bot_events,
        top_bots=sample.top_bots,
    )


def _duplicate_events_check(checked: CheckedEvents) -> InsightDataCheck:
    key = InsightDataCheckKey.DUPLICATE_EVENTS
    sample = _usable_sample(checked.sample)
    if isinstance(sample, Skipped):
        return not_checked(key, sample.reason)

    share = sample.repeated_events / sample.events
    estimate = sample.repeated_events / sample.rate
    is_finding = estimate >= MIN_DUPLICATE_EVENTS and share >= MIN_DUPLICATE_SHARE
    return InsightDataCheck(
        key=key,
        level=_finding_level(share) if is_finding else InsightDataCheckLevel.PASSED,
        method=InsightDataCheckMethod.SAMPLED,
        events=round(estimate),
        share=share,
        scaled=not sample.read_every_event,
        top_events=sample.top_repeated_events,
    )


def found_no_events(checked: CheckedEvents) -> bool:
    sample = checked.sample
    return isinstance(sample, SampledEvents) and sample.read_every_event and sample.events == 0


def evaluate_data_checks(checked: CheckedEvents) -> list[InsightDataCheck]:
    """Every check, in a fixed order, so the list shows what was checked whatever the result."""
    return [
        _local_development_check(checked),
        _bot_traffic_check(checked),
        _duplicate_events_check(checked),
    ]


def status_of(checks: list[InsightDataCheck]) -> InsightDataChecksStatus:
    levels = {check.level for check in checks}
    if levels == {InsightDataCheckLevel.SKIPPED}:
        return InsightDataChecksStatus.INCONCLUSIVE
    if InsightDataCheckLevel.PROBLEM in levels:
        return InsightDataChecksStatus.PROBLEM
    if InsightDataCheckLevel.WARNING in levels:
        return InsightDataChecksStatus.WARNING
    return InsightDataChecksStatus.PASSED
