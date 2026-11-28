"""Per-case seeders for the web analytics MCP question evals.

Every seeder computes the case's oracle answer against the case team at run time, using the
same query runners the MCP tools wrap, and returns it under ``oracle`` so the answer judge can
compare the agent's final message with a number that moves with the seeded data. The web vitals
case also writes a designed set of ``$web_vitals`` events, because the Hedgebox simulation does
not capture them.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.schema import (
    CompareFilter,
    CustomEventConversionGoal,
    DateRange,
    ProductKey,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    WebOverviewQuery,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.event.new_events_schema import use_new_events_schema
from posthog.models.event.sql import EVENTS_JSON_DATA_TABLE, INSERT_EVENT_SQL
from posthog.models.event.util import _json_dumps_for_clickhouse
from posthog.models.person.sql import INSERT_PERSON_DISTINCT_ID2, INSERT_PERSON_SQL
from posthog.models.utils import uuid7

from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner
from products.web_analytics.backend.weekly_digest import build_team_digest

Seeder = Callable[[CustomPromptSandboxContext], dict[str, Any]]

SIGNUP_EVENT = "signed_up"
MIN_LANDING_PAGE_VISITORS = 20

WEB_VITALS_PATH_CLEANING_RULE = {"regex": "/files/[0-9a-f]+/", "alias": "/files/<id>/"}


@frozen
class WebVitalsPage:
    path: str
    lcp_ms: float
    samples: int
    raw_paths: tuple[str, ...] = ()


# A busy page with a real problem, a cleaned family of file pages that only look bad once the
# team's path cleaning rolls them up, two healthy pages, and a one-sample trap that an agent
# must not report as the slowest page.
WEB_VITALS_PAGES: tuple[WebVitalsPage, ...] = (
    WebVitalsPage(path="/account/billing/", lcp_ms=5200, samples=30),
    WebVitalsPage(
        path="/files/<id>/",
        lcp_ms=4600,
        samples=50,
        raw_paths=tuple(f"/files/{n:06x}/" for n in range(0x3F9A2C, 0x3F9A2C + 25)),
    ),
    WebVitalsPage(path="/pricing/", lcp_ms=3200, samples=40),
    WebVitalsPage(path="/", lcp_ms=1400, samples=80),
    WebVitalsPage(path="/invite/9c1e7a/", lcp_ms=12000, samples=1),
)
WEB_VITALS_TRAP_PATH = WEB_VITALS_PAGES[-1].path
_WEB_VITALS_PERSON_NAMESPACE = uuid.UUID("7d2b5f0e-6c1a-4e3b-9a8f-0c1d2e3f4a5b")
_ZERO_CLICKHOUSE_TIMESTAMP = "1970-01-01 00:00:00.000000"


def _team(context: CustomPromptSandboxContext) -> Team:
    team = Team.objects.get(pk=context.team_id)
    tag_queries(product=ProductKey.WEB_ANALYTICS, team_id=team.pk, name="web_analytics_mcp_eval_oracle")
    return team


def _overview(team: Team, **kwargs: Any) -> dict[str, dict[str, float | None]]:
    query = WebOverviewQuery(properties=[], **kwargs)
    response = WebOverviewQueryRunner(team=team, query=query).calculate()
    return {
        item.key: {"value": item.value, "previous": item.previous, "change_pct": item.changeFromPreviousPct}
        for item in response.results
    }


def _stats_rows(team: Team, breakdown: WebStatsBreakdown, limit: int, **kwargs: Any) -> list[dict[str, Any]]:
    query = WebStatsTableQuery(
        breakdownBy=breakdown,
        dateRange=DateRange(date_from="-7d"),
        limit=limit,
        orderBy=[WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.DESC],
        properties=[],
        **kwargs,
    )
    response = WebStatsTableQueryRunner(team=team, query=query).calculate()
    columns = [column.removeprefix("context.columns.") for column in response.columns or []]
    rows = []
    for row in response.results:
        cells = dict(zip(columns, row))
        # Every metric cell is a `[current, previous]` pair.
        rows.append({name: value[0] if isinstance(value, list | tuple) else value for name, value in cells.items()})
    return rows


def _rounded(value: float | None, digits: int = 0) -> float | int | None:
    if value is None:
        return None
    return round(value, digits) if digits else round(value)


def seed_unique_visitors(context: CustomPromptSandboxContext) -> dict[str, Any]:
    overview = _overview(_team(context), dateRange=DateRange(date_from="-7d"))
    visitors = _rounded(overview["visitors"]["value"])
    return {
        "oracle": {
            "answer": f"About {visitors} unique visitors in the last 7 days "
            f"(sessions {_rounded(overview['sessions']['value'])}, pageviews {_rounded(overview['views']['value'])}).",
            "tolerance": "Visitor count within 5% of the oracle.",
        }
    }


def seed_top_pages(context: CustomPromptSandboxContext) -> dict[str, Any]:
    rows = _stats_rows(_team(context), WebStatsBreakdown.PAGE, limit=5)
    ranked = ", ".join(f"{row['breakdown_value']} ({_rounded(row['visitors'])} visitors)" for row in rows)
    return {
        "oracle": {
            "answer": f"Top 5 pages by visitors, in order: {ranked}.",
            "tolerance": "Same five paths in the same order; visitor counts within 5%.",
        }
    }


def seed_highest_bounce_landing_page(context: CustomPromptSandboxContext) -> dict[str, Any]:
    rows = _stats_rows(_team(context), WebStatsBreakdown.INITIAL_PAGE, limit=200, includeBounceRate=True)
    eligible = [row for row in rows if (row["visitors"] or 0) >= MIN_LANDING_PAGE_VISITORS]
    worst = max(eligible, key=lambda row: row["bounce_rate"] or 0)
    return {
        "oracle": {
            "answer": (
                f"{worst['breakdown_value']} with a bounce rate of {_rounded((worst['bounce_rate'] or 0) * 100, 1)}% "
                f"({_rounded(worst['visitors'])} visitors). Only landing pages with at least "
                f"{MIN_LANDING_PAGE_VISITORS} visitors qualify."
            ),
            "tolerance": (
                "The named landing page must match. A different page is wrong even if its bounce rate is higher, "
                "unless the answer states that it has fewer visitors than the threshold and still names the oracle's page."
            ),
        }
    }


def seed_week_over_week(context: CustomPromptSandboxContext) -> dict[str, Any]:
    overview = _overview(
        _team(context),
        dateRange=DateRange(date_from="-7d", excludeIncompletePeriods=True),
        compareFilter=CompareFilter(compare=True),
    )
    visitors, views = overview["visitors"], overview["views"]
    return {
        "oracle": {
            "answer": (
                f"Over the last 7 complete days visitors were {_rounded(visitors['value'])} against "
                f"{_rounded(visitors['previous'])} in the 7 days before ({_rounded(visitors['change_pct'], 1)}%), "
                f"pageviews {_rounded(views['value'])} against {_rounded(views['previous'])} "
                f"({_rounded(views['change_pct'], 1)}%). The window ends yesterday; today's partial day is left out."
            ),
            "tolerance": (
                "Direction of each change must match and the percentage must be within 3 points. The answer must "
                "say which days each period covers or that today is excluded."
            ),
        }
    }


def seed_top_channel(context: CustomPromptSandboxContext) -> dict[str, Any]:
    rows = _stats_rows(_team(context), WebStatsBreakdown.INITIAL_CHANNEL_TYPE, limit=10)
    ranked = ", ".join(f"{row['breakdown_value']} ({_rounded(row['visitors'])})" for row in rows[:3])
    return {
        "oracle": {
            "answer": f"{rows[0]['breakdown_value']} brought the most traffic. Top channels by visitors: {ranked}.",
            "tolerance": "The leading channel must match; the tool reports visitors rather than sessions, which is fine.",
        }
    }


def seed_signups_by_channel(context: CustomPromptSandboxContext) -> dict[str, Any]:
    rows = _stats_rows(
        _team(context),
        WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
        limit=10,
        conversionGoal=CustomEventConversionGoal(customEventName=SIGNUP_EVENT),
    )
    rows.sort(key=lambda row: row["total_conversions"] or 0, reverse=True)
    top = rows[0]
    return {
        "oracle": {
            "answer": (
                f"{top['breakdown_value']} brought the most sign-ups: {_rounded(top['total_conversions'])} "
                f"'{SIGNUP_EVENT}' conversions from {_rounded(top['visitors'])} visitors."
            ),
            "tolerance": "Channel must match and the sign-up count must be within 5%.",
        }
    }


def seed_top_countries(context: CustomPromptSandboxContext) -> dict[str, Any]:
    rows = _stats_rows(_team(context), WebStatsBreakdown.COUNTRY, limit=10)
    ranked = ", ".join(f"{row['breakdown_value']} ({_rounded(row['visitors'])})" for row in rows[:5])
    return {
        "oracle": {
            "answer": f"Top countries by visitors: {ranked}.",
            "tolerance": "The top three countries must appear in the same order.",
        }
    }


def seed_top_referrers(context: CustomPromptSandboxContext) -> dict[str, Any]:
    rows = _stats_rows(_team(context), WebStatsBreakdown.INITIAL_REFERRING_DOMAIN, limit=10)
    ranked = ", ".join(f"{row['breakdown_value']} ({_rounded(row['visitors'])})" for row in rows[:5])
    return {
        "oracle": {
            "answer": f"Top referring domains by visitors: {ranked}.",
            "tolerance": "The top three referrers must appear in the same order; '$direct' may be reported as direct traffic.",
        }
    }


def seed_signup_conversion_rate(context: CustomPromptSandboxContext) -> dict[str, Any]:
    overview = _overview(
        _team(context),
        dateRange=DateRange(date_from="-7d"),
        conversionGoal=CustomEventConversionGoal(customEventName=SIGNUP_EVENT),
    )
    return {
        "oracle": {
            "answer": (
                f"{_rounded(overview['conversion rate']['value'], 1)}% of visitors signed up: "
                f"{_rounded(overview['unique conversions']['value'])} of {_rounded(overview['visitors']['value'])}."
            ),
            "tolerance": "Conversion rate within one percentage point.",
        }
    }


def seed_yesterday_vs_last_week(context: CustomPromptSandboxContext) -> dict[str, Any]:
    overview = _overview(
        _team(context),
        dateRange=DateRange(date_from="-1dStart", date_to="-1dEnd"),
        compareFilter=CompareFilter(compare=True, compare_to="-7d"),
    )
    sessions, duration = overview["sessions"], overview["session duration"]
    return {
        "oracle": {
            "answer": (
                f"Yesterday: {_rounded(sessions['value'])} sessions against {_rounded(sessions['previous'])} on the "
                f"same day last week ({_rounded(sessions['change_pct'], 1)}%); average session duration "
                f"{_rounded(duration['value'])}s against {_rounded(duration['previous'])}s."
            ),
            "tolerance": "Session counts within 5% and durations within 10%, compared with the same weekday a week earlier.",
        }
    }


def seed_daily_visitors(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team = _team(context)
    now = datetime.now(team.timezone_info)
    response = execute_hogql_query(
        query_type="web_analytics_mcp_eval_oracle",
        query=parse_select(
            "SELECT toDate(timestamp) AS day, uniq(person_id) AS visitors FROM events "
            "WHERE event = '$pageview' AND timestamp >= {date_from} AND timestamp < {date_to} "
            "GROUP BY day ORDER BY day",
            placeholders={
                "date_from": ast.Constant(
                    value=(now - timedelta(days=14)).replace(hour=0, minute=0, second=0, microsecond=0)
                ),
                "date_to": ast.Constant(value=now),
            },
        ),
        team=team,
    )
    series = ", ".join(f"{day}: {visitors}" for day, visitors in response.results)
    return {
        "oracle": {
            "answer": f"Daily unique visitors over the last 14 days, last day partial: {series}.",
            "tolerance": "One value per day within 5%; the last day must be flagged as partial.",
        }
    }


def seed_weekly_digest(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team = _team(context)
    digest = build_team_digest(team)
    visitors = digest["visitors"]
    change = visitors["change"]
    change_text = f"{change['direction']} {change['percent']}%" if change else "about flat"
    top_pages = ", ".join(page["path"] for page in digest["top_pages"][:3])
    return {
        "oracle": {
            "answer": (
                f"Last 7 complete days ({digest['metadata']['date_from']:%Y-%m-%d} to "
                f"{digest['metadata']['date_to']:%Y-%m-%d}): {visitors['current']} visitors, {change_text} versus the "
                f"7 days before; {digest['pageviews']['current']} pageviews; bounce rate "
                f"{digest['bounce_rate']['current']}%. Top pages: {top_pages}. Test accounts "
                f"{'excluded' if digest['metadata']['filter_test_accounts'] else 'included'}."
            ),
            "tolerance": (
                "Visitor count within 5%, change direction must match, and the answer must name the period it covers."
            ),
        }
    }


def _person_id(distinct_id: str) -> str:
    return str(uuid.uuid5(_WEB_VITALS_PERSON_NAMESPACE, distinct_id))


def _insert_person(team: Team, distinct_id: str, created_at: datetime) -> None:
    stamp = created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    sync_execute(
        INSERT_PERSON_SQL,
        {
            "id": _person_id(distinct_id),
            "created_at": stamp,
            "team_id": team.pk,
            "properties": json.dumps({"email": f"{distinct_id}@example.com"}),
            "is_identified": 1,
            "_timestamp": created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            "is_deleted": 0,
            "version": 1,
            "last_seen_at": stamp,
        },
    )
    sync_execute(
        INSERT_PERSON_DISTINCT_ID2,
        {
            "distinct_id": distinct_id,
            "person_id": _person_id(distinct_id),
            "team_id": team.pk,
            "is_deleted": 0,
            "version": 1,
        },
    )


def _insert_web_vitals_event(team: Team, distinct_id: str, timestamp: datetime, properties: dict[str, Any]) -> None:
    stamp = timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    native_schema = use_new_events_schema(team.pk)
    sync_execute(
        INSERT_EVENT_SQL(table_name=EVENTS_JSON_DATA_TABLE if native_schema else None),
        {
            "uuid": str(uuid7(timestamp.isoformat())),
            "event": "$web_vitals",
            "properties": _json_dumps_for_clickhouse(properties) if native_schema else json.dumps(properties),
            "timestamp": stamp,
            "team_id": team.pk,
            "distinct_id": distinct_id,
            "elements_chain": "",
            "created_at": stamp,
            "person_id": _person_id(distinct_id),
            "person_properties": "{}",
            "person_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            **{f"group{i}_properties": "{}" for i in range(5)},
            **{f"group{i}_created_at": _ZERO_CLICKHOUSE_TIMESTAMP for i in range(5)},
            "person_mode": "full",
        },
    )


def _web_vitals_samples(page: WebVitalsPage) -> list[tuple[str, float]]:
    # Values step 20ms around the page's level so p75 lands just above it, with no randomness.
    raw_paths = page.raw_paths or (page.path,)
    return [
        (raw_paths[index % len(raw_paths)], page.lcp_ms + (index - page.samples // 2) * 20)
        for index in range(page.samples)
    ]


def seed_web_vitals(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team = _team(context)
    team.path_cleaning_filters = [*(team.path_cleaning_filters or []), WEB_VITALS_PATH_CLEANING_RULE]
    team.save(update_fields=["path_cleaning_filters"])

    now = datetime.now(UTC)
    distinct_ids = [f"web-vitals-visitor-{n}" for n in range(8)]
    for distinct_id in distinct_ids:
        _insert_person(team, distinct_id, now - timedelta(days=10))
    sample_index = 0
    for page in WEB_VITALS_PAGES:
        for raw_path, value in _web_vitals_samples(page):
            # Spread samples over the last six days so any "this week" window sees all of them.
            timestamp = now - timedelta(days=1 + sample_index % 6, hours=sample_index % 17)
            _insert_web_vitals_event(
                team,
                distinct_ids[sample_index % len(distinct_ids)],
                timestamp,
                {
                    "$pathname": raw_path,
                    "$current_url": f"https://hedgebox.net{raw_path}",
                    "$host": "hedgebox.net",
                    "$session_id": str(uuid7(timestamp.isoformat())),
                    "$web_vitals_LCP_value": value,
                },
            )
            sample_index += 1

    ranked = sorted((page for page in WEB_VITALS_PAGES if page.samples > 1), key=lambda page: page.lcp_ms, reverse=True)
    ranking = ", ".join(f"{page.path} (p75 about {page.lcp_ms:.0f}ms, {page.samples} samples)" for page in ranked)
    return {
        "pages": [{"path": page.path, "lcp_ms": page.lcp_ms, "samples": page.samples} for page in WEB_VITALS_PAGES],
        "oracle": {
            "answer": (
                f"Worst p75 LCP pages this week, worst first: {ranking}. {WEB_VITALS_TRAP_PATH} has a single "
                f"12000ms sample and is noise, not the slowest page. The file pages should appear as the cleaned "
                f"path /files/<id>/, not as individual /files/<hex>/ paths."
            ),
            "tolerance": (
                "The first two pages named must be /account/billing/ and /files/<id>/ in that order, each with a "
                "sample count. Naming the one-sample page as the slowest page without calling it out as a single "
                "sample is wrong."
            ),
        },
    }
