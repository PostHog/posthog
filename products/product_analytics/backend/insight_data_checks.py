"""Checks the events an insight reads for internal users, local development, bots and events sent twice."""

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.errors import CHQueryErrorTooManyBytes, ExposedCHQueryError
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.access_control.backend.facade.contracts import RestrictedPropertyNames
from products.product_analytics.backend.chart_events import ChartEvents, chart_events
from products.product_analytics.backend.facade.contracts import (
    InsightDataChecks,
    InsightDataChecksCoverage,
    InsightDataChecksSample,
    TeamEmailAccess,
)
from products.product_analytics.backend.facade.enums import (
    InsightDataCheckKey,
    InsightDataCheckSkipReason,
    InsightDataChecksStatus,
)
from products.product_analytics.backend.insight_data_check_days import CheckWindow, days_between, newest_days_within
from products.product_analytics.backend.insight_data_check_results import (
    CRAWLER_TRAFFIC_TYPES,
    LOCAL_HOST_PATTERN,
    CheckedEvents,
    CountedEvents,
    InternalEvents,
    LocalEvents,
    SampledEvents,
    Skipped,
    evaluate_data_checks,
    events_on_checked_days,
    found_no_events,
    not_checked,
    status_of,
)
from products.product_analytics.backend.insight_data_check_team_emails import team_email_pattern, team_emails_of

# The checks read only the newest days of a range, so they stay cheap enough to run on every load.
MAX_CHECKED_DAYS = 7
# The most events the local development check counts, so a busy event checks fewer days.
EVENT_BUDGET = 20_000_000
# A day cannot be split, so the newest day alone is counted up to this size.
MAX_COUNTED_EVENTS = 2 * EVENT_BUDGET
SAMPLE_SIZE = 100_000
SIZING_SAMPLE_ONE_IN = 1_000

# A check that takes longer than this is skipped, so it never holds up the insight it sits next to.
MAX_EXECUTION_SECONDS = 5
# Backstops for a size estimate that is far too low, such as for an event sent under a few distinct IDs.
# ClickHouse applies them to the total across all shards, so this one sits above what a check reads at EVENT_BUDGET.
MAX_BYTES_READ = 10_000_000_000
# The sample reads wide columns and sorts them for the repeat window, so it gets a tighter limit.
MAX_SAMPLE_BYTES_READ = 1_000_000_000

# A person cannot repeat an action this fast, but an app that sends an event twice does.
REPEAT_WINDOW_MILLISECONDS = 100
# A hidden property reads as empty, so the checks cannot run when one of these is hidden.
CHECKED_PROPERTIES = frozenset(
    {"$host", "$raw_user_agent", "$ip", "$current_url", "$screen_name", "$feature_flag", "$event_type"}
)
EMAIL_PROPERTY = "email"
# The fields and functions that classify traffic, which apply a project's own bot rules.
TRAFFIC_TYPE_FIELDS = frozenset(
    {"$virt_is_bot", "$virt_traffic_type", "$virt_traffic_category", "$virt_bot_name", "$virt_bot_operator"}
)
TRAFFIC_TYPE_FUNCTIONS = frozenset(
    {"isLikelyBot", "getTrafficType", "getTrafficCategory", "getBotName", "getBotOperator"}
)

_EVENTS_PER_DAY_QUERY = """
    SELECT toDate(timestamp) AS day, count() AS events
    FROM events
    GROUP BY day
"""

# HogQL has no topKIf, and topK skips NULL, so the list ranks only the events the check found.
_COUNTED_EVENTS_QUERY = """
    SELECT
        count() AS events,
        countIf(NOT {passes_filter}) AS removed_by_filter,
        countIf({passes_filter} AND {is_team_email}) AS missed_by_filter,
        topK(3)(if(NOT {passes_filter} OR {is_team_email}, event, NULL)) AS top_internal_events,
        uniqIf({email}, {passes_filter} AND {is_team_email}) AS distinct_missed_emails,
        topK(3)(if({passes_filter} AND {is_team_email}, {email}, NULL)) AS top_missed_emails,
        groupUniqArrayIf(50)({stored_email}, {passes_filter} AND {is_team_email}) AS missed_emails
    FROM events
"""

# The host match goes in WHERE, and ClickHouse moves it to PREWHERE itself when `$host` has its own column.
# An explicit PREWHERE fails when a hidden property wraps `properties` in the JSONDropKeys UDF, because ClickHouse
# does not resolve executable UDFs in PREWHERE.
_LOCAL_EVENTS_QUERY = """
    SELECT
        count() AS events,
        uniqExact(toString(properties.$host)) AS distinct_hosts,
        topK(3)(toString(properties.$host)) AS top_hosts,
        topK(3)(event) AS top_events,
        groupUniqArray(50)(toString(properties.$host)) AS hosts
    FROM events
"""

_IS_LOCAL_HOST = "match(toString(properties.$host), {local_host_pattern})"

# The suggested rule is a person rule, so the check reads the email from the same person, which is the event's copy
# or the current person depending on the persons-on-events mode.
# An `is_not` rule compares case-sensitively, so the suggested rule names each email as it is stored.
_STORED_EMAIL = "toString(person.properties.email)"
_EMAIL = "lower({stored_email})"
_IS_TEAM_EMAIL = "match({email}, {team_email_pattern})"

_SAMPLED_EVENTS_QUERY = """
    SELECT
        distinct_id,
        event,
        toString(properties.$raw_user_agent) AS user_agent,
        toString(properties.$ip) AS ip,
        dateDiff(
            'millisecond',
            lagInFrame(timestamp) OVER (
                PARTITION BY
                    distinct_id,
                    event,
                    toString(properties.$raw_user_agent),
                    toString(properties.$current_url),
                    toString(properties.$screen_name),
                    toString(properties.$feature_flag),
                    toString(properties.$event_type),
                    elements_chain_texts,
                    elements_chain_href,
                    elements_chain_ids,
                    elements_chain_elements
                ORDER BY timestamp
                ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
            ),
            timestamp
        ) AS milliseconds_since_identical_event
    FROM events
"""

# Each event, user agent and IP is classified once, which costs far less than classifying every event.
_SAMPLE_COUNTS_QUERY = """
    SELECT
        sum(source_events) AS events,
        uniqExactMerge(source_distinct_ids) AS distinct_ids,
        sumIf(source_events, is_bot) AS bot_events,
        sumMapIf([bot_name], [source_events], is_bot) AS bot_events_by_bot,
        sumMapIf([event], [source_events], is_bot) AS bot_events_by_event,
        sum(source_repeated_events) AS repeated_events,
        sumMap([event], [source_repeated_events]) AS repeated_events_by_event
    FROM (
        SELECT
            event,
            getTrafficType(user_agent, ip) IN {crawler_traffic_types} AS is_bot,
            getBotName(user_agent, ip) AS bot_name,
            source_events,
            source_repeated_events,
            source_distinct_ids
        FROM (
            SELECT
                event,
                user_agent,
                ip,
                count() AS source_events,
                countIf(milliseconds_since_identical_event < {repeat_window_milliseconds}) AS source_repeated_events,
                uniqExactState(distinct_id) AS source_distinct_ids
            FROM {sampled_events}
            GROUP BY event, user_agent, ip
        )
    )
"""


@frozen
class _EventReader:
    team: Team
    user: User
    modifiers: HogQLQueryModifiers
    # The database the chart's events were read with, so the checks do not build another.
    database: Database

    def rows_within_limits(
        self, query: ast.SelectQuery, *, query_type: str, max_bytes_read: int
    ) -> list[list[Any]] | Skipped:
        try:
            response = execute_hogql_query(
                query=query,
                team=self.team,
                user=self.user,
                query_type=query_type,
                modifiers=self.modifiers,
                context=HogQLContext(team_id=self.team.pk, user=self.user, database=self.database),
                settings=_query_settings(max_bytes_read),
            )
        except CHQueryErrorTooManyBytes:
            return Skipped(reason=InsightDataCheckSkipReason.READ_LIMIT)
        except (ClickHouseQueryTimeOut, ClickHouseEstimatedQueryExecutionTimeTooLong):
            return Skipped(reason=InsightDataCheckSkipReason.TIME_LIMIT)
        except ClickHouseQueryMemoryLimitExceeded:
            return Skipped(reason=InsightDataCheckSkipReason.MEMORY_LIMIT)
        return [list(row) for row in response.results or []]


def _query_settings(max_bytes_read: int) -> HogQLGlobalSettings:
    # Without "throw", a query that reaches a limit can return the events it counted so far as the answer.
    return HogQLGlobalSettings(
        max_execution_time=MAX_EXECUTION_SECONDS,
        timeout_overflow_mode="throw",
        max_bytes_to_read=max_bytes_read,
        read_overflow_mode="throw",
    )


class _TrafficTypeFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        self.found = self.found or any(part in TRAFFIC_TYPE_FIELDS for part in node.chain)

    def visit_call(self, node: ast.Call) -> None:
        self.found = self.found or node.name in TRAFFIC_TYPE_FUNCTIONS
        super().visit_call(node)


def _filters_on_traffic_type(where: ast.Expr) -> bool:
    finder = _TrafficTypeFinder()
    finder.visit(where)
    return finder.found


def _check_modifiers(chart_modifiers: HogQLQueryModifiers, *, keep_project_bot_rules: bool) -> HogQLQueryModifiers:
    # With `debug` on, a failed query returns an error and no rows, which would read as no events.
    # Without the pushdown, a persons join reads the latest version of every person in the project, however few
    # events the check reads.
    update: dict[str, Any] = {"debug": False, "personIdPushdown": True}
    if not keep_project_bot_rules:
        # The bot check uses PostHog's definition of a bot, so a project's own bot rules do not apply.
        update["customBotDefinitions"] = []
    return chart_modifiers.model_copy(update=update)


def _hidden_properties(team: Team, user: User) -> RestrictedPropertyNames:
    return split_restricted_property_names(
        get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk)
    )


def _start_of(day: date, timezone: ZoneInfo) -> ast.Constant:
    return ast.Constant(value=datetime.combine(day, time.min, tzinfo=timezone))


def _between_days(events: ChartEvents, first: date, last: date, timezone: ZoneInfo) -> ast.Expr:
    """The events from the start of `first` to the end of `last`, as a timestamp range ClickHouse can skip by."""
    return ast.And(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq, left=events.timestamp(), right=_start_of(first, timezone)
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=events.timestamp(),
                right=_start_of(last + timedelta(days=1), timezone),
            ),
        ]
    )


def _sample_of(count: int, total: int) -> ast.SampleExpr:
    if total <= count:
        return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=1)))
    return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=count), right=ast.Constant(value=total)))


def _top_three(values_by_key: tuple[list[str], list[int]] | None) -> list[str]:
    """The three keys with the highest values, highest first, from the key and value arrays that sumMap returns."""
    if not values_by_key:
        return []
    keys, values = values_by_key
    ranked = sorted(zip(keys, values), key=lambda key_and_value: key_and_value[1], reverse=True)
    return [key for key, value in ranked if key and value > 0][:3]


def _distinct_keys(values_by_key: tuple[list[str], list[int]] | None) -> int:
    if not values_by_key:
        return 0
    keys, values = values_by_key
    return sum(1 for key, value in zip(keys, values) if key and value > 0)


def _count_events_per_day(
    events: ChartEvents, reader: _EventReader, days: list[date], timezone: ZoneInfo
) -> dict[date, int] | Skipped:
    """Each day's events before the chart's filters, estimated from a sample of distinct IDs."""
    query = events.select(
        _EVENTS_PER_DAY_QUERY,
        where=ast.And(exprs=[events.sort_key_where, _between_days(events, days[0], days[-1], timezone)]),
        sample=_sample_of(1, SIZING_SAMPLE_ONE_IN),
    )
    rows = reader.rows_within_limits(query, query_type="insight_data_checks_sizing", max_bytes_read=MAX_BYTES_READ)
    if isinstance(rows, Skipped):
        return rows

    sampled = {day: int(count) for day, count in rows}
    return {day: sampled.get(day, 0) * SIZING_SAMPLE_ONE_IN for day in days}


def _choose_window(events: ChartEvents, reader: _EventReader, timezone: ZoneInfo) -> CheckWindow | Skipped:
    days_in_range = days_between(
        events.date_from.astimezone(timezone).date(), events.date_to.astimezone(timezone).date()
    )
    events_per_day = _count_events_per_day(events, reader, days_in_range[-MAX_CHECKED_DAYS:], timezone)
    if isinstance(events_per_day, Skipped):
        return events_per_day

    return CheckWindow(
        days_in_range=days_in_range,
        days_to_check=newest_days_within(events_per_day, EVENT_BUDGET),
        events_per_day=events_per_day,
    )


@frozen
class _InternalUsersMatch:
    passes_filter: ast.Expr
    email: ast.Expr
    stored_email: ast.Expr
    is_team_email: ast.Expr
    # The person fields the match reads from the current person join, or None when it needs no join.
    person_fields: frozenset[str] | None = None
    names_emails: bool = False


_NO_INTERNAL_USERS = _InternalUsersMatch(
    passes_filter=ast.Constant(value=True),
    email=ast.Constant(value=None),
    stored_email=ast.Constant(value=None),
    is_team_email=ast.Constant(value=False),
)


# The lookup's columns sit next to the event's columns, so they take names the events table does not use.
_CURRENT_PERSON = "current_person"

# The latest person of each distinct ID, as the persons join finds it. Each table reads only the rows of the
# checked events' distinct IDs, so the lookup does not read the whole project.
_CURRENT_PERSON_QUERY = """
    SELECT person_ids.distinct_id AS current_person_distinct_id, person_ids.person_id AS current_person_id
    FROM (
        SELECT distinct_id, argMax(person_id, version) AS person_id
        FROM raw_person_distinct_ids
        WHERE distinct_id IN {checked_distinct_ids}
        GROUP BY distinct_id
        HAVING argMax(is_deleted, version) = 0
    ) AS person_ids
    LEFT JOIN (
        SELECT id
        FROM raw_persons
        WHERE id IN (SELECT person_id FROM raw_person_distinct_ids WHERE distinct_id IN {checked_distinct_ids_again})
        GROUP BY id
        HAVING argMax(is_deleted, version) = 0
    ) AS current_persons ON current_persons.id = person_ids.person_id
"""


class _PersonFromLeftJoin(CloningVisitor):
    def __init__(self) -> None:
        super().__init__()
        # None while the filter reads no person.
        self.person_fields: set[str] | None = None

    # A field in a subquery belongs to that subquery's own tables.
    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        return clone_expr(node)

    def visit_field(self, node: ast.Field) -> ast.Field:
        if node.chain[:1] == ["person"] and len(node.chain) > 1:
            self.person_fields = {*(self.person_fields or ()), str(node.chain[1])}
            return ast.Field(chain=[_CURRENT_PERSON, f"{_CURRENT_PERSON}_{node.chain[1]}", *node.chain[2:]])
        if node.chain == ["person_id"]:
            self.person_fields = self.person_fields or set()
            return ast.Field(chain=[_CURRENT_PERSON, "current_person_id"])
        return super().visit_field(node)


def _read_person_keeping_personless_events(
    events: ChartEvents, expr: ast.Expr
) -> tuple[ast.Expr, frozenset[str] | None]:
    # Without persons on events, the person comes from an inner join that drops the events with no person, which
    # the insight counts. A left join on the same table reads the same person and keeps those events.
    if events.modifiers.personsOnEventsMode != PersonsOnEventsMode.DISABLED:
        return expr, None
    person_from_left_join = _PersonFromLeftJoin()
    expr = person_from_left_join.visit(expr)
    if person_from_left_join.person_fields is None:
        return expr, None
    return expr, frozenset(person_from_left_join.person_fields)


def _passes_internal_users_filter(events: ChartEvents, team: Team) -> tuple[ast.Expr, frozenset[str] | None]:
    # An insight that applies the filter has already dropped the events it removes.
    if events.filters_test_accounts or not team.test_account_filters:
        return ast.Constant(value=True), None
    project_filter, person_fields = _read_person_keeping_personless_events(
        events, property_to_expr(team.test_account_filters, team)
    )
    # The insight's own WHERE drops an event whose filter is NULL, so NULL counts as removed.
    return ast.Call(name="ifNull", args=[project_filter, ast.Constant(value=False)]), person_fields


def _current_person_join(events: ChartEvents, where: ast.Expr, person_fields: frozenset[str]) -> ast.JoinExpr:
    def checked_distinct_ids() -> ast.SelectQuery:
        return events.select("SELECT distinct_id FROM events", where=clone_expr(where))

    lookup = cast(
        ast.SelectQuery,
        parse_select(
            _CURRENT_PERSON_QUERY,
            placeholders={
                "checked_distinct_ids": checked_distinct_ids(),
                "checked_distinct_ids_again": checked_distinct_ids(),
            },
        ),
    )
    person_ids = cast(ast.JoinExpr, lookup.select_from)
    persons = cast(ast.JoinExpr, person_ids.next_join)
    if not person_fields:
        person_ids.next_join = None
    for field in sorted(person_fields):
        latest_value = parse_expr("argMax({field}, version)", placeholders={"field": ast.Field(chain=[field])})
        cast(ast.SelectQuery, persons.table).select.append(ast.Alias(alias=field, expr=latest_value))
        lookup.select.append(
            ast.Alias(alias=f"{_CURRENT_PERSON}_{field}", expr=ast.Field(chain=["current_persons", field]))
        )
    return ast.JoinExpr(
        join_type="LEFT JOIN",
        table=lookup,
        alias=_CURRENT_PERSON,
        constraint=ast.JoinConstraint(
            expr=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[_CURRENT_PERSON, "current_person_distinct_id"]),
                right=ast.Field(chain=[events.alias or "events", "distinct_id"]),
            ),
            constraint_type="ON",
        ),
    )


def _internal_users_match(
    events: ChartEvents,
    reader: _EventReader,
    *,
    email_access: TeamEmailAccess,
    hidden_properties: RestrictedPropertyNames,
) -> _InternalUsersMatch | Skipped:
    # A hidden email reads as empty, so the check would miss every member found by email.
    if EMAIL_PROPERTY in hidden_properties.person:
        return Skipped(reason=InsightDataCheckSkipReason.HIDDEN_PROPERTY)

    team_emails = team_emails_of(reader.team, reader.user, email_access)
    passes_filter, filter_person_fields = _passes_internal_users_filter(events, reader.team)
    stored_email, email_person_fields = _read_person_keeping_personless_events(events, parse_expr(_STORED_EMAIL))
    person_fields: frozenset[str] | None = None
    if filter_person_fields is not None or email_person_fields is not None:
        person_fields = (filter_person_fields or frozenset()) | (email_person_fields or frozenset())

    email = parse_expr(_EMAIL, placeholders={"stored_email": stored_email})
    return _InternalUsersMatch(
        passes_filter=passes_filter,
        person_fields=person_fields,
        names_emails=email_access.person_emails,
        email=email,
        stored_email=stored_email,
        is_team_email=parse_expr(
            _IS_TEAM_EMAIL,
            placeholders={"email": email, "team_email_pattern": ast.Constant(value=team_email_pattern(team_emails))},
        ),
    )


def _count_every_event(
    events: ChartEvents, reader: _EventReader, where: ast.Expr, internal_users: _InternalUsersMatch | Skipped
) -> CountedEvents | Skipped:
    match = _NO_INTERNAL_USERS if isinstance(internal_users, Skipped) else internal_users
    query = events.select(
        _COUNTED_EVENTS_QUERY,
        where=where,
        passes_filter=match.passes_filter,
        email=match.email,
        stored_email=match.stored_email,
        is_team_email=match.is_team_email,
    )
    if match.person_fields is not None:
        cast(ast.JoinExpr, query.select_from).next_join = _current_person_join(events, where, match.person_fields)
    rows = reader.rows_within_limits(query, query_type="insight_data_checks_counted", max_bytes_read=MAX_BYTES_READ)
    if isinstance(rows, Skipped):
        return rows

    row: list[Any] = rows[0] if rows else [0, 0, 0, [], 0, [], []]
    count, removed, missed, top_internal_events, distinct_missed_emails, top_missed_emails, missed_emails = row
    internal: InternalEvents | Skipped
    if isinstance(internal_users, Skipped):
        internal = internal_users
    else:
        internal = InternalEvents(
            removed_by_filter=int(removed or 0),
            missed_by_filter=int(missed or 0),
            top_events=list(top_internal_events),
            distinct_missed_emails=int(distinct_missed_emails or 0),
            top_missed_emails=list(top_missed_emails) if internal_users.names_emails else [],
            missed_emails=[email for email in missed_emails if email] if internal_users.names_emails else [],
        )
    return CountedEvents(events=int(count or 0), internal=internal)


def _count_local_events_the_filter_keeps(
    events: ChartEvents,
    reader: _EventReader,
    where: ast.Expr,
    passes_filter: ast.Expr,
    person_fields: frozenset[str] | None,
) -> LocalEvents | Skipped:
    is_local_host = parse_expr(
        _IS_LOCAL_HOST, placeholders={"local_host_pattern": ast.Constant(value=LOCAL_HOST_PATTERN)}
    )
    query = events.select(
        _LOCAL_EVENTS_QUERY,
        where=ast.And(exprs=[clone_expr(is_local_host), where, passes_filter]),
    )
    if person_fields is not None:
        local_events = ast.And(exprs=[clone_expr(where), clone_expr(is_local_host)])
        cast(ast.JoinExpr, query.select_from).next_join = _current_person_join(events, local_events, person_fields)
    rows = reader.rows_within_limits(query, query_type="insight_data_checks_local", max_bytes_read=MAX_BYTES_READ)
    if isinstance(rows, Skipped):
        return rows

    row: list[Any] = rows[0] if rows else [0, 0, [], [], []]
    count, distinct_hosts, top_hosts, top_events, hosts = row
    return LocalEvents(
        count=int(count or 0),
        distinct_hosts=int(distinct_hosts or 0),
        top_hosts=list(top_hosts),
        top_events=list(top_events),
        hosts=list(hosts),
    )


def _count_local_events(events: ChartEvents, reader: _EventReader, where: ast.Expr) -> LocalEvents | Skipped:
    try:
        passes_filter, person_fields = _passes_internal_users_filter(events, reader.team)
        return _count_local_events_the_filter_keeps(events, reader, where, passes_filter, person_fields)
    except (ExposedHogQLError, ResolutionError, ExposedCHQueryError) as error:
        # The internal users check reports the broken filter, so this check counts every local event.
        capture_exception(error)
        return _count_local_events_the_filter_keeps(events, reader, where, ast.Constant(value=True), None)


def _count_events_on_checked_days(
    events: ChartEvents,
    reader: _EventReader,
    where: ast.Expr,
    *,
    email_access: TeamEmailAccess,
    hidden_properties: RestrictedPropertyNames,
) -> CountedEvents | Skipped:
    try:
        internal_users = _internal_users_match(
            events, reader, email_access=email_access, hidden_properties=hidden_properties
        )
        return _count_every_event(events, reader, where, internal_users)
    except (ExposedHogQLError, ResolutionError, ExposedCHQueryError) as error:
        # The project's filter, such as one on a deleted cohort, is the likely cause, so count again without it.
        capture_exception(error)
        return _count_every_event(events, reader, where, Skipped(reason=InsightDataCheckSkipReason.INVALID_FILTER))


def _sample_events(
    events: ChartEvents, reader: _EventReader, where: ast.Expr, *, events_before_filters: int
) -> SampledEvents | Skipped:
    sampled_events = events.select(
        _SAMPLED_EVENTS_QUERY,
        where=where,
        # The events table samples by distinct ID, so a sampled ID keeps all its events and no repeat is split.
        sample=_sample_of(SAMPLE_SIZE, events_before_filters),
    )
    query = parse_select(
        _SAMPLE_COUNTS_QUERY,
        placeholders={
            "sampled_events": sampled_events,
            "crawler_traffic_types": ast.Tuple(exprs=[ast.Constant(value=name) for name in CRAWLER_TRAFFIC_TYPES]),
            "repeat_window_milliseconds": ast.Constant(value=REPEAT_WINDOW_MILLISECONDS),
        },
    )
    rows = reader.rows_within_limits(
        cast(ast.SelectQuery, query),
        query_type="insight_data_checks_sample",
        max_bytes_read=MAX_SAMPLE_BYTES_READ,
    )
    if isinstance(rows, Skipped):
        return rows

    row: list[Any] = rows[0] if rows else [0] * 7
    sampled, distinct_ids, bot_events, by_bot, bots_by_event, repeated_events, repeats_by_event = row
    return SampledEvents(
        rate=min(1.0, SAMPLE_SIZE / events_before_filters) if events_before_filters else 1.0,
        events=int(sampled or 0),
        distinct_ids=int(distinct_ids or 0),
        bot_events=int(bot_events or 0),
        distinct_bots=_distinct_keys(by_bot),
        top_bots=_top_three(by_bot),
        top_bot_events=_top_three(bots_by_event),
        repeated_events=int(repeated_events or 0),
        top_repeated_events=_top_three(repeats_by_event),
    )


def _read_checked_days(
    events: ChartEvents,
    reader: _EventReader,
    window: CheckWindow,
    timezone: ZoneInfo,
    *,
    hidden_properties: RestrictedPropertyNames,
    filters_traffic_type: bool,
    email_access: TeamEmailAccess,
) -> CheckedEvents:
    # The bounds apply to a whole range too, because a lifecycle chart also reads the interval before its range.
    first, last = window.days_to_check[0], window.days_to_check[-1]
    where = ast.And(exprs=[events.where, _between_days(events, first, last, timezone)])

    counted: CountedEvents | Skipped = Skipped(reason=InsightDataCheckSkipReason.TOO_MANY_EVENTS)
    if window.events_on_days_to_check <= MAX_COUNTED_EVENTS:
        counted = _count_events_on_checked_days(
            events, reader, where, email_access=email_access, hidden_properties=hidden_properties
        )
    local = _count_local_events(events, reader, where)
    sample = _sample_events(events, reader, where, events_before_filters=window.events_on_days_to_check)
    return CheckedEvents(counted=counted, local=local, sample=sample, insight_filters_traffic_type=filters_traffic_type)


def _sample_summary(sample: SampledEvents | Skipped) -> InsightDataChecksSample | None:
    if isinstance(sample, Skipped):
        return None
    return InsightDataChecksSample(rate=sample.rate, events=sample.events, distinct_ids=sample.distinct_ids)


def _coverage(events: ChartEvents, window: CheckWindow, checked: CheckedEvents) -> InsightDataChecksCoverage:
    return InsightDataChecksCoverage(
        date_from=window.days_in_range[0],
        date_to=window.days_in_range[-1],
        days_in_range=len(window.days_in_range),
        checked_date_from=window.days_to_check[0],
        checked_date_to=window.days_to_check[-1],
        days_checked=len(window.days_to_check),
        filters_test_accounts=events.filters_test_accounts,
        events_checked=events_on_checked_days(checked),
        sample=_sample_summary(checked.sample),
    )


def _nothing_checked(
    status: InsightDataChecksStatus,
    coverage: InsightDataChecksCoverage | None = None,
    reason: InsightDataCheckSkipReason | None = None,
) -> InsightDataChecks:
    checks = [not_checked(key, reason) for key in InsightDataCheckKey]
    return InsightDataChecks(status=status, checks=checks, coverage=coverage)


def run_insight_data_checks(
    query: Mapping[str, Any], team: Team, user: User, *, email_access: TeamEmailAccess
) -> InsightDataChecks:
    with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.INSIGHT, name="insight_data_checks"):
        events = chart_events(query, team, user)
        if events is None:
            return _nothing_checked(InsightDataChecksStatus.UNSUPPORTED)
        hidden_properties = _hidden_properties(team, user)
        if hidden_properties.event & CHECKED_PROPERTIES:
            return _nothing_checked(InsightDataChecksStatus.UNSUPPORTED)

        # A chart that filters on traffic type reads the project's bot rules, so the checks keep them to read its events.
        filters_traffic_type = _filters_on_traffic_type(events.where)
        reader = _EventReader(
            team=team,
            user=user,
            modifiers=_check_modifiers(events.modifiers, keep_project_bot_rules=filters_traffic_type),
            database=events.database,
        )
        timezone = ZoneInfo(team.timezone)
        window = _choose_window(events, reader, timezone)
        if isinstance(window, Skipped):
            return _nothing_checked(InsightDataChecksStatus.INCONCLUSIVE, reason=window.reason)
        checked = _read_checked_days(
            events,
            reader,
            window,
            timezone,
            hidden_properties=hidden_properties,
            filters_traffic_type=filters_traffic_type,
            email_access=email_access,
        )

    coverage = _coverage(events, window, checked)
    if found_no_events(checked):
        return _nothing_checked(InsightDataChecksStatus.NO_EVENTS, coverage)
    checks = evaluate_data_checks(checked)
    return InsightDataChecks(status=status_of(checks), checks=checks, coverage=coverage)
