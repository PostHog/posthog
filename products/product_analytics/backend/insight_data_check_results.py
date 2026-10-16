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
class InternalEvents:
    # Events the project's internal and test users filter removes, when the insight does not apply that filter.
    removed_by_filter: int
    # Events from the team's own emails or test accounts that the filter keeps.
    missed_by_filter: int
    top_events: list[str]

    @property
    def count(self) -> int:
        return self.removed_by_filter + self.missed_by_filter


@frozen
class CountedEvents:
    # Every event the insight reads on the days checked, so a counted check needs no sample for its share.
    events: int
    local: LocalEvents
    internal: InternalEvents | Skipped


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
    counted: CountedEvents | Skipped
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


def _share(count: int, events: int) -> float | None:
    return count / events if events else None


def _is_finding(count: int, events: int) -> bool:
    return count >= MIN_FINDING_EVENTS and count >= MIN_FINDING_SHARE * events


def _internal_users_check(checked: CheckedEvents) -> InsightDataCheck:
    key = InsightDataCheckKey.INTERNAL_USERS
    counted = checked.counted
    if isinstance(counted, Skipped):
        return not_checked(key, counted.reason)
    internal = counted.internal
    if isinstance(internal, Skipped):
        return not_checked(key, internal.reason)

    share = _share(internal.count, counted.events)
    is_finding = _is_finding(internal.count, counted.events)
    # Turning the filter on for the insight is enough, unless the filter keeps the team's own emails.
    action = InsightDataCheckAction.FILTER_INTERNAL_USERS
    if _is_finding(internal.missed_by_filter, counted.events):
        action = InsightDataCheckAction.OPEN_FILTER_SETTINGS
    return InsightDataCheck(
        key=key,
        level=_finding_level(share) if is_finding else InsightDataCheckLevel.PASSED,
        method=InsightDataCheckMethod.COUNTED,
        events=internal.count,
        share=share,
        action=action if is_finding else None,
        top_events=internal.top_events,
    )


def _local_development_check(checked: CheckedEvents) -> InsightDataCheck:
    key = InsightDataCheckKey.LOCAL_DEVELOPMENT
    counted = checked.counted
    if isinstance(counted, Skipped):
        return not_checked(key, counted.reason)

    local = counted.local
    share = _share(local.count, counted.events)
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
    if isinstance(checked.counted, CountedEvents):
        return checked.counted.events == 0
    sample = checked.sample
    return isinstance(sample, SampledEvents) and sample.read_every_event and sample.events == 0


def evaluate_data_checks(checked: CheckedEvents) -> list[InsightDataCheck]:
    """Every check, in a fixed order, so the list shows what was checked whatever the result."""
    return [
        _internal_users_check(checked),
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
