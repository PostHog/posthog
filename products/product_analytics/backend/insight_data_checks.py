import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import lru_cache
from typing import Any, cast

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.errors import ExposedCHQueryError
from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import GenericEmails

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.access_control.backend.facade.subject_access_control import restricted_visible_membership_ids
from products.product_analytics.backend.chart_events import ChartEvents, chart_events
from products.product_analytics.backend.facade.contracts import InsightDataCheck, InsightDataChecks
from products.product_analytics.backend.facade.enums import (
    InsightDataCheckAction,
    InsightDataCheckKey,
    InsightDataCheckLevel,
    InsightDataChecksStatus,
)

# Each check is a share of the events, so a sample this large gives the same answer as every event.
MAX_CHECKED_EVENTS = 1_000_000
# The sample is drawn before the chart's filters, because a count after them reads every event. When the filters
# keep fewer of the sampled events than the minimum, one larger sample is drawn that keeps about the second number.
MIN_SAMPLED_EVENTS = 10_000
RESAMPLED_EVENTS = 100_000
# The larger sample reads at most this many times the events of the first, so a filter that keeps almost no
# events does not read every event in the range.
MAX_RESAMPLE_GROWTH = 10
MAX_EXECUTION_SECONDS = 20

LOCAL_HOST_PATTERN = r"(?i)^(localhost|[a-z0-9.-]+\.localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:[0-9]+)?$"
# An event with no user agent has the type "Automation", and server-side SDKs send those, so it is not a crawler.
CRAWLER_TRAFFIC_TYPES = ("Bot", "AI Agent")

# A real person's email can contain one of these words, so only a word that stands alone marks a test account.
TEST_ACCOUNT_WORDS = "test|testing|qa|demo|dummy|fake"
# A member on a company domain is found by the domain, so these limits only bound the size of the query.
MAX_OWN_TEAM_DOMAINS = 20
MAX_OWN_TEAM_EMAILS = 200
# Whether a person is internal comes from the person's properties. They are stored together, which makes them the
# most expensive value these checks read, so the internal users check reads this many events at most.
MAX_INTERNAL_USERS_CHECKED_EVENTS = 50_000
# A few busy people can fill a small sample, so this check needs a larger share than the others to report a finding.
MIN_INTERNAL_USERS_SHARE = 0.02

MIN_FINDING_EVENTS = 50
MIN_FINDING_SHARE = 0.01
MIN_DUPLICATE_EVENTS = 100
MIN_DUPLICATE_SHARE = 0.05
PROBLEM_SHARE = 0.2

_TOTAL_QUERY = "SELECT count() FROM events"

# `uniq` is exact up to 65,536 values and an estimate above that, so one count for each user agent keeps the count of
# distinct events exact for all but the most common user agents.
_COUNTS_BY_USER_AGENT_QUERY = """
    SELECT
        toString(properties.$raw_user_agent) AS user_agent,
        count() AS event_count,
        countIf(match(toString(properties.$host), {local_host_pattern})) AS local_count,
        countIf(`$virt_traffic_type` IN {crawler_traffic_types}) AS bot_count,
        uniq((
            distinct_id,
            event,
            toStartOfSecond(timestamp),
            toString(properties.$current_url),
            toString(properties.$screen_name),
            toString(properties.$feature_flag),
            elements_chain
        )) AS distinct_count
    FROM events
    GROUP BY user_agent
"""

_COUNTS_QUERY = """
    SELECT
        sum(event_count) AS events,
        sum(local_count) AS local_events,
        sum(bot_count) AS bot_events,
        sum(distinct_count) AS distinct_events
    FROM {counts_by_user_agent}
"""

_INTERNAL_USERS_QUERY = """
    SELECT
        count() AS events,
        countIf(NOT ifNull({kept_by_filter}, false)) AS removed_by_filter,
        countIf(
            ifNull({kept_by_filter}, false)
            AND (
                match(lower(toString(person.properties.email)), {own_team_pattern})
                OR match(lower(distinct_id), {own_team_pattern})
            )
        ) AS missed_by_filter
    FROM events
"""


@frozen
class InternalUserCounts:
    # The internal users check reads its own, smaller sample of the insight's events.
    events: int
    removed_by_filter: int
    missed_by_filter: int
    is_sample: bool = False

    @property
    def internal_events(self) -> int:
        return self.removed_by_filter + self.missed_by_filter


@frozen
class DataCheckCounts:
    events: int
    local_events: int
    bot_events: int
    distinct_events: int
    internal_users: InternalUserCounts | None = None
    sample_rate: float = 1.0


@frozen
class OwnTeamEmails:
    # Company domains, the one with the most members first.
    domains: tuple[str, ...]
    # Members on a public email provider, where the domain says nothing about the team.
    addresses: tuple[str, ...]


@frozen
class _EventReader:
    team: Team
    user: User
    modifiers: HogQLQueryModifiers
    # The database the chart's events were read with, so the checks do not build another.
    database: Database

    def first_row(
        self, query: ast.SelectQuery, *, query_type: str, modifiers: HogQLQueryModifiers | None = None
    ) -> list[Any]:
        response = execute_hogql_query(
            query=query,
            team=self.team,
            user=self.user,
            query_type=query_type,
            modifiers=modifiers or self.modifiers,
            context=HogQLContext(team_id=self.team.pk, user=self.user, database=self.database),
            settings=_query_settings(),
        )
        return list(response.results[0]) if response.results else []


def run_insight_data_checks(
    query: Mapping[str, Any], team: Team, user: User, *, can_read_members: bool
) -> InsightDataChecks:
    """Check the events an insight reads for the common ways they mislead.

    Runs three ClickHouse queries: a cheap count that sets the samples, the checks on a large sample, and the
    internal users check on a small one. A chart whose filters keep few of its events runs the checks a second
    time on a larger sample.
    """
    with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.INSIGHT, name="insight_data_checks"):
        events = chart_events(query, team, user)
        if events is None:
            return _not_checked(InsightDataChecksStatus.UNSUPPORTED)
        # A property that is hidden from `user` reads as empty, so a check would count none of what it looks for.
        if get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk):
            return _not_checked(InsightDataChecksStatus.UNSUPPORTED)
        has_internal_users_filter = bool(team.test_account_filters)
        own_team = _own_team_emails(team, user, can_read_members=can_read_members)
        # With `debug` on, a failed query returns an error and no rows, which would read as no events.
        modifiers = events.modifiers.model_copy(update={"debug": False})
        reader = _EventReader(
            team=team,
            user=user,
            modifiers=modifiers,
            database=events.database,
        )
        total = _count_events_in_range(events, reader)
        if total == 0:
            return _not_checked(InsightDataChecksStatus.NO_EVENTS)
        counts = _count_events(
            events, reader, total=total, has_internal_users_filter=has_internal_users_filter, own_team=own_team
        )
    if counts.events == 0:
        return _not_checked(InsightDataChecksStatus.NO_EVENTS)
    checks = evaluate_data_checks(
        counts,
        filters_internal_users=events.filters_internal_users,
        has_internal_users_filter=has_internal_users_filter,
        own_team_domain=own_team.domains[0] if own_team.domains else None,
    )
    return InsightDataChecks(
        status=_status_of(checks), checks=checks, events_checked=counts.events, sample_rate=counts.sample_rate
    )


def evaluate_data_checks(
    counts: DataCheckCounts,
    *,
    filters_internal_users: bool,
    has_internal_users_filter: bool,
    own_team_domain: str | None = None,
) -> list[InsightDataCheck]:
    """Every check, in a fixed order, so the list shows what was checked whatever the result."""
    return [
        _internal_users_check(
            counts,
            filters_internal_users=filters_internal_users,
            has_internal_users_filter=has_internal_users_filter,
            own_team_domain=own_team_domain,
        ),
        _local_development_check(counts, filters_internal_users=filters_internal_users),
        _bot_traffic_check(counts, filters_internal_users=filters_internal_users),
        _duplicate_events_check(counts),
    ]


def _query_settings() -> HogQLGlobalSettings:
    # Without "throw", a query that reaches the time limit can return the events it counted so far as the answer.
    return HogQLGlobalSettings(max_execution_time=MAX_EXECUTION_SECONDS, timeout_overflow_mode="throw")


@lru_cache(maxsize=1)
def _generic_emails() -> GenericEmails:
    return GenericEmails()


def _own_team_emails(team: Team, user: User, *, can_read_members: bool) -> OwnTeamEmails:
    """The emails of the people who work on this project: the members of its organization, and its verified domains.

    Without `can_read_members`, only the verified domains, because a match would tell the caller who is a member.
    """
    memberships = OrganizationMembership.objects.filter(organization_id=team.organization_id)
    if not can_read_members:
        memberships = memberships.none()
    # A match on the email of a member that `user` may not see would tell `user` that the address is a member's.
    visible_membership_ids = restricted_visible_membership_ids(team.organization, user)
    if visible_membership_ids is not None:
        memberships = memberships.filter(id__in=visible_membership_ids)
    member_emails = memberships.values_list("user__email", flat=True)
    domains: Counter[str] = Counter()
    addresses: set[str] = set()
    for member_email in member_emails:
        email = member_email.strip().lower()
        if "@" not in email:
            continue
        if _generic_emails().is_generic(email):
            addresses.add(email)
        else:
            domains[email.rpartition("@")[2]] += 1
    verified_domains = OrganizationDomain.objects.verified_domains().filter(organization_id=team.organization_id)
    for domain in verified_domains.values_list("domain", flat=True):
        domains.setdefault(domain.strip().lower(), 0)
    return OwnTeamEmails(
        domains=tuple(domain for domain, _ in sorted(domains.items(), key=lambda item: (-item[1], item[0])))[
            :MAX_OWN_TEAM_DOMAINS
        ],
        addresses=tuple(sorted(addresses))[:MAX_OWN_TEAM_EMAILS],
    )


def own_team_email_pattern(domains: Sequence[str], addresses: Sequence[str]) -> str:
    """A pattern for a lowercase email that belongs to the project's own team or to a test account."""
    alternatives = [
        rf"^(?:{TEST_ACCOUNT_WORDS})(?:[._+0-9-][^@]*)?@",
        rf"\+(?:{TEST_ACCOUNT_WORDS})(?:[._0-9-][^@]*)?@",
    ]
    if domains:
        # A subdomain of a company domain is the same company. The end anchor keeps acme.com.br out.
        alternatives.append(rf"@(?:[a-z0-9-]+\.)*(?:{'|'.join(re.escape(domain) for domain in domains)})$")
    if addresses:
        alternatives.append(rf"^(?:{'|'.join(re.escape(address) for address in addresses)})$")
    return "|".join(f"(?:{alternative})" for alternative in alternatives)


def _count_events_in_range(events: ChartEvents, reader: _EventReader) -> int:
    """Every event with the insight's event names in its date range, before any property filter."""
    row = reader.first_row(
        events.select(_TOTAL_QUERY, where=events.sort_key_where), query_type="insight_data_checks_total"
    )
    return int(row[0] or 0) if row else 0


def _count_events(
    events: ChartEvents,
    reader: _EventReader,
    *,
    total: int,
    has_internal_users_filter: bool,
    own_team: OwnTeamEmails,
) -> DataCheckCounts:
    sampled = min(total, MAX_CHECKED_EVENTS)
    counts = _query_counts(events, reader, sampled=sampled, total=total)
    if sampled < total and counts.events < MIN_SAMPLED_EVENTS:
        sampled = min(total, sampled * MAX_RESAMPLE_GROWTH, sampled * RESAMPLED_EVENTS // max(counts.events, 1))
        counts = _query_counts(events, reader, sampled=sampled, total=total)
    if not counts.events:
        return counts
    try:
        internal_users = _count_internal_user_events(
            events,
            reader,
            total=total,
            chart_events=round(counts.events / counts.sample_rate),
            has_internal_users_filter=has_internal_users_filter,
            own_team=own_team,
        )
    except (
        ExposedHogQLError,
        ExposedCHQueryError,
        ResolutionError,
        ClickHouseQueryTimeOut,
        ClickHouseEstimatedQueryExecutionTimeTooLong,
        ClickHouseQueryMemoryLimitExceeded,
        ClickHouseAtCapacity,
    ) as error:
        # This query alone reads the project's filter and person properties, so it can fail when the others pass.
        capture_exception(error)
        return counts
    return replace(counts, internal_users=internal_users)


def _query_counts(events: ChartEvents, reader: _EventReader, *, sampled: int, total: int) -> DataCheckCounts:
    """The counts on a sample that holds `sampled` of the `total` events in the insight's date range."""
    counts_by_user_agent = events.select(
        _COUNTS_BY_USER_AGENT_QUERY,
        where=events.where,
        # The events table samples by distinct ID, so a sampled ID keeps all its events and no duplicate pair is split.
        sample=ast.SampleExpr(sample_value=_sample(sampled, total)),
        crawler_traffic_types=ast.Tuple(exprs=[ast.Constant(value=name) for name in CRAWLER_TRAFFIC_TYPES]),
        local_host_pattern=ast.Constant(value=LOCAL_HOST_PATTERN),
    )
    row = reader.first_row(
        cast(ast.SelectQuery, parse_select(_COUNTS_QUERY, placeholders={"counts_by_user_agent": counts_by_user_agent})),
        query_type="insight_data_checks",
    )
    event_count, local_events, bot_events, distinct_events = (int(value or 0) for value in row or [0] * 4)
    return DataCheckCounts(
        events=event_count,
        local_events=local_events,
        bot_events=bot_events,
        distinct_events=distinct_events,
        sample_rate=sampled / total,
    )


def _sample(limit: int, total: int) -> ast.RatioExpr:
    if total > limit:
        return ast.RatioExpr(left=ast.Constant(value=limit), right=ast.Constant(value=total))
    return ast.RatioExpr(left=ast.Constant(value=1))


def _count_internal_user_events(
    events: ChartEvents,
    reader: _EventReader,
    *,
    total: int,
    chart_events: int,
    has_internal_users_filter: bool,
    own_team: OwnTeamEmails,
) -> InternalUserCounts:
    """`total` is the events in the range before the chart's filters, and `chart_events` the events it keeps."""
    # When the insight applies the filter, the events it would remove are gone before this count.
    counts_filtered_events = has_internal_users_filter and not events.filters_internal_users
    # Without this, a project that joins person properties at query time reads every person to get the emails.
    modifiers = reader.modifiers
    if modifiers.personIdPushdown is None:
        modifiers = modifiers.model_copy(update={"personIdPushdown": True})
    # The sample is drawn before the chart's filters. It keeps about the events this check needs, and reads no more
    # events than the first sample of the other checks.
    sampled = min(total, MAX_CHECKED_EVENTS, MAX_INTERNAL_USERS_CHECKED_EVENTS * total // max(chart_events, 1))
    query = events.select(
        _INTERNAL_USERS_QUERY,
        # The persons join reads only the people of the events that match a condition on the events alone.
        where=ast.And(exprs=[events.sort_key_where, events.where]),
        sample=ast.SampleExpr(sample_value=_sample(sampled, total)),
        kept_by_filter=(
            property_to_expr(reader.team.test_account_filters, reader.team)
            if counts_filtered_events
            else ast.Constant(value=True)
        ),
        own_team_pattern=ast.Constant(value=own_team_email_pattern(own_team.domains, own_team.addresses)),
    )
    row = reader.first_row(query, query_type="insight_data_checks_internal_users", modifiers=modifiers)
    events_count, removed_by_filter, missed_by_filter = (int(value or 0) for value in row or [0] * 3)
    return InternalUserCounts(
        events=events_count,
        removed_by_filter=removed_by_filter,
        missed_by_filter=missed_by_filter,
        is_sample=sampled < total,
    )


def _check(
    key: InsightDataCheckKey,
    level: InsightDataCheckLevel,
    result: str,
    *,
    fix: str | None = None,
    action: InsightDataCheckAction | None = None,
    events: int | None = None,
    share: float | None = None,
) -> InsightDataCheck:
    return InsightDataCheck(
        key=key, level=level, name=key.label, result=result, fix=fix, action=action, events=events, share=share
    )


def _not_checked(status: InsightDataChecksStatus) -> InsightDataChecks:
    checks = [_check(key, InsightDataCheckLevel.SKIPPED, key.label) for key in InsightDataCheckKey]
    return InsightDataChecks(status=status, checks=checks, events_checked=0, sample_rate=1.0)


def _status_of(checks: list[InsightDataCheck]) -> InsightDataChecksStatus:
    levels = {check.level for check in checks}
    if InsightDataCheckLevel.PROBLEM in levels:
        return InsightDataChecksStatus.PROBLEM
    return (
        InsightDataChecksStatus.WARNING if InsightDataCheckLevel.WARNING in levels else InsightDataChecksStatus.PASSED
    )


def _finding_level(share: float) -> InsightDataCheckLevel:
    return InsightDataCheckLevel.PROBLEM if share >= PROBLEM_SHARE else InsightDataCheckLevel.WARNING


def _is_finding(count: float, share: float) -> bool:
    return count >= MIN_FINDING_EVENTS and share >= MIN_FINDING_SHARE


def _percent(share: float) -> str:
    return f"{round(share * 100)}%"


def _estimate(count: int, counts: DataCheckCounts) -> float:
    """A count from the sample, scaled up to every event of the insight."""
    return count / counts.sample_rate


def _event_count(count: int, counts: DataCheckCounts) -> str:
    """A count of the insight's events. From a sample it is an estimate, so it is scaled up and rounded."""
    if counts.sample_rate >= 1:
        return f"{count:,}"
    estimate = round(_estimate(count, counts))
    magnitude = 10 ** max(len(str(estimate)) - 2, 0)
    return f"about {round(estimate / magnitude) * magnitude:,}"


def _passed(key: InsightDataCheckKey, things: str, count: int, counts: DataCheckCounts) -> InsightDataCheck:
    """`things` is what the check looks for, as it reads after "No": "bots or crawlers"."""
    result = f"Almost no {things} found ({_event_count(count, counts)} events)" if count else f"No {things} found"
    return _check(key, InsightDataCheckLevel.PASSED, result, events=count, share=count / counts.events)


def _is_internal_users_finding(count: int, internal_users: InternalUserCounts) -> bool:
    return count >= MIN_FINDING_EVENTS and count >= MIN_INTERNAL_USERS_SHARE * internal_users.events


def _internal_users_check(
    counts: DataCheckCounts,
    *,
    filters_internal_users: bool,
    has_internal_users_filter: bool,
    own_team_domain: str | None,
) -> InsightDataCheck:
    key = InsightDataCheckKey.INTERNAL_USERS
    internal_users = counts.internal_users
    # The sample is drawn by user, so it can hold no event when a few users sent most of the insight's events.
    is_checked = internal_users is not None and internal_users.events > 0
    if internal_users is None or not is_checked:
        internal_users = InternalUserCounts(events=1, removed_by_filter=0, missed_by_filter=0)
    share = internal_users.internal_events / internal_users.events
    # The other checks count the larger sample, so this count is given on the same scale.
    events = round(share * counts.events)
    if _is_internal_users_finding(internal_users.internal_events, internal_users):
        example = f", such as emails that end in @{own_team_domain}" if own_team_domain else ""
        action = InsightDataCheckAction.OPEN_FILTER_SETTINGS
        if not has_internal_users_filter:
            fix = f"Set up the internal and test users filter so that it removes your team's emails{example}."
        elif _is_internal_users_finding(internal_users.missed_by_filter, internal_users):
            fix = (
                "The internal and test users filter does not remove all of them. "
                f"Change the filter so that it also removes your team's emails{example}."
            )
        else:
            fix = "Turn on the internal and test users filter for this insight."
            action = InsightDataCheckAction.FILTER_INTERNAL_USERS
        if action == InsightDataCheckAction.OPEN_FILTER_SETTINGS and not filters_internal_users:
            fix += " Then turn the filter on for this insight."
        # A sample of people can hold more or fewer internal users than the whole insight does.
        amount = f"About {_percent(share)}" if internal_users.is_sample else _percent(share)
        return _check(
            key,
            _finding_level(share),
            f"{amount} of these events came from internal and test users",
            fix=fix,
            action=action,
            events=events,
            share=share,
        )
    if not has_internal_users_filter:
        return _check(
            key,
            InsightDataCheckLevel.SKIPPED,
            "This project has no filter for internal and test users",
            fix="Set up the filter so PostHog knows which users are your own team.",
            action=InsightDataCheckAction.OPEN_FILTER_SETTINGS,
        )
    if not is_checked:
        return _check(
            key,
            InsightDataCheckLevel.SKIPPED,
            "Not checked, because this check could not finish"
            if counts.internal_users is None
            else "Not checked, because too few users sent these events to take a sample of them",
        )
    if filters_internal_users:
        return _check(key, InsightDataCheckLevel.PASSED, "Internal and test users are filtered out")
    return _passed(key, "internal or test users", events, counts)


def _fix_in_the_filter(change: str, *, filters_internal_users: bool) -> str:
    return f"{change}." if filters_internal_users else f"{change}, and turn that filter on for this insight."


def _local_development_check(counts: DataCheckCounts, *, filters_internal_users: bool) -> InsightDataCheck:
    key = InsightDataCheckKey.LOCAL_DEVELOPMENT
    share = counts.local_events / counts.events
    # No minimum share: a local session also creates test persons and flag exposures, whatever its share.
    if _estimate(counts.local_events, counts) < MIN_FINDING_EVENTS:
        return _passed(key, "local development events", counts.local_events, counts)
    amount = _percent(share) if share >= MIN_FINDING_SHARE else _event_count(counts.local_events, counts)
    return _check(
        key,
        _finding_level(share),
        f"{amount[0].upper()}{amount[1:]} of these events came from local development",
        fix=_fix_in_the_filter(
            "Send local traffic to a separate project, or exclude localhost in the internal and test users filter",
            filters_internal_users=filters_internal_users,
        ),
        action=InsightDataCheckAction.OPEN_FILTER_SETTINGS,
        events=counts.local_events,
        share=share,
    )


def _bot_traffic_check(counts: DataCheckCounts, *, filters_internal_users: bool) -> InsightDataCheck:
    key = InsightDataCheckKey.BOT_TRAFFIC
    share = counts.bot_events / counts.events
    if not _is_finding(_estimate(counts.bot_events, counts), share):
        return _passed(key, "bots or crawlers", counts.bot_events, counts)
    return _check(
        key,
        _finding_level(share),
        f"{_percent(share)} of these events came from bots and crawlers",
        fix=_fix_in_the_filter(
            'In the internal and test users filter, add "Traffic type is not Bot or AI Agent"',
            filters_internal_users=filters_internal_users,
        ),
        action=InsightDataCheckAction.OPEN_FILTER_SETTINGS,
        events=counts.bot_events,
        share=share,
    )


def _duplicate_events_check(counts: DataCheckCounts) -> InsightDataCheck:
    key = InsightDataCheckKey.DUPLICATE_EVENTS
    duplicates = max(counts.events - counts.distinct_events, 0)
    share = duplicates / counts.events
    if duplicates < MIN_DUPLICATE_EVENTS or share < MIN_DUPLICATE_SHARE:
        # The count is an estimate, so a small one can be an error of the estimate and not a real event.
        result = (
            "No events sent twice" if share < MIN_FINDING_SHARE else f"Few events sent twice (about {_percent(share)})"
        )
        return _check(key, InsightDataCheckLevel.PASSED, result, events=duplicates, share=share)
    return _check(
        key,
        _finding_level(share),
        f"About {_percent(share)} of these events were sent twice within one second",
        fix="Start PostHog once in your app, and send each event from one place only.",
        events=duplicates,
        share=share,
    )
