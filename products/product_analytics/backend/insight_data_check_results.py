"""Turns the counts the data checks read into a level for each check."""

from posthog.dataclasses import frozen

from products.product_analytics.backend.facade.contracts import InsightDataCheck, InsightDataCheckFilter
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

# An event with no user agent has the type "Automation", and server-side SDKs send those, so it is not a crawler.
CRAWLER_TRAFFIC_TYPES = ("Bot", "AI Agent")

_SKIP_REASONS_WITH_NOTHING_TO_CHECK = frozenset(
    {InsightDataCheckSkipReason.FILTERED_BY_TRAFFIC_TYPE, InsightDataCheckSkipReason.TOO_FEW_SAMPLED_EVENTS}
)

LOCAL_HOST_PATTERN = r"(?i)^(localhost|[a-z0-9.-]+\.localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:[0-9]+)?$"


@frozen
class Skipped:
    reason: InsightDataCheckSkipReason


@frozen
class LocalEvents:
    # The events from a local host that the project's internal and test users filter keeps.
    count: int
    distinct_hosts: int
    top_hosts: list[str]
    top_events: list[str]
    # Every host the check found, up to a limit, so the rule to add names only what the person saw.
    hosts: list[str]


@frozen
class InternalEvents:
    # Events the project's internal and test users filter removes, when the insight does not apply that filter.
    removed_by_filter: int
    # Events from the team's own emails or test accounts that the filter keeps.
    missed_by_filter: int
    top_events: list[str]
    distinct_missed_emails: int
    top_missed_emails: list[str]
    missed_emails: list[str]

    @property
    def count(self) -> int:
        return self.removed_by_filter + self.missed_by_filter


@frozen
class CountedEvents:
    # Every event the insight reads on the days checked, so a counted check needs no sample for its share.
    events: int
    internal: InternalEvents | Skipped


@frozen
class SampledEvents:
    rate: float
    events: int
    distinct_ids: int
    bot_events: int
    distinct_bots: int
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
    local: LocalEvents | Skipped
    sample: SampledEvents | Skipped
    insight_filters_traffic_type: bool = False


def events_on_checked_days(checked: CheckedEvents) -> int | None:
    if isinstance(checked.counted, CountedEvents):
        return checked.counted.events
    if isinstance(checked.sample, SampledEvents):
        return round(checked.sample.events / checked.sample.rate)
    return None


def _excluding(key: str, property_type: str, values: list[str]) -> InsightDataCheckFilter:
    # Names only the values the check found, because a broader rule could remove real users the person never saw.
    return InsightDataCheckFilter(key=key, type=property_type, operator="is_not", value=sorted(values))


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
        removed_by_filter=internal.removed_by_filter,
        missed_by_filter=internal.missed_by_filter,
        top_emails=internal.top_missed_emails,
        distinct_emails=internal.distinct_missed_emails,
        filter_to_add=_excluding("email", "person", internal.missed_emails) if internal.missed_emails else None,
    )


def _local_development_check(checked: CheckedEvents) -> InsightDataCheck:
    key = InsightDataCheckKey.LOCAL_DEVELOPMENT
    local = checked.local
    if isinstance(local, Skipped):
        return not_checked(key, local.reason)

    events = events_on_checked_days(checked)
    share = _share(local.count, events) if events is not None else None
    # No minimum share: a local session also creates test persons and flag exposures, whatever its share.
    is_finding = local.count >= MIN_FINDING_EVENTS
    return InsightDataCheck(
        key=key,
        # Never a problem: a project can serve real users from a local host, such as an app in a native wrapper,
        # so the person who owns the project decides whether to keep these events.
        level=InsightDataCheckLevel.WARNING if is_finding else InsightDataCheckLevel.PASSED,
        method=InsightDataCheckMethod.COUNTED,
        events=local.count,
        share=share,
        action=InsightDataCheckAction.OPEN_FILTER_SETTINGS if is_finding else None,
        top_events=local.top_events,
        top_hosts=local.top_hosts,
        distinct_hosts=local.distinct_hosts,
        filter_to_add=_excluding("$host", "event", local.hosts) if is_finding else None,
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
        distinct_bots=sample.distinct_bots,
        filter_to_add=_excluding("$virt_traffic_type", "event", list(CRAWLER_TRAFFIC_TYPES)) if is_finding else None,
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
    if any(
        check.level == InsightDataCheckLevel.SKIPPED and check.skip_reason not in _SKIP_REASONS_WITH_NOTHING_TO_CHECK
        for check in checks
    ):
        return InsightDataChecksStatus.PARTIAL
    return InsightDataChecksStatus.PASSED
