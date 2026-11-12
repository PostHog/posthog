import datetime as dt
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.hogql import ast

from products.signals.backend.emission.ahrefs_site_audit_issues import (
    AHREFS_SITE_AUDIT_ISSUES_CONFIG,
    ahrefs_issue_source_id,
    ahrefs_site_audit_issue_emitter,
)
from products.signals.backend.emission.bing_webmaster_tools_crawl_issues import (
    BING_WEBMASTER_TOOLS_CRAWL_ISSUES_CONFIG,
    bing_crawl_issue_emitter,
    crawl_issue_source_id,
)
from products.signals.backend.emission.registry import SignalSourceTableConfig
from products.signals.backend.emission.semrush_site_audit_issue_details import (
    SEMRUSH_SITE_AUDIT_ISSUE_DETAILS_CONFIG,
    descriptions_table_name,
    semrush_issue_source_id,
    semrush_site_audit_issue_emitter,
)

_MONDAY = dt.datetime(2026, 11, 9, 8, 0, tzinfo=dt.UTC)
_SUNDAY = dt.datetime(2026, 11, 15, 22, 0, tzinfo=dt.UTC)
_NEXT_MONDAY = dt.datetime(2026, 11, 16, 8, 0, tzinfo=dt.UTC)

_BING = {
    "site_url": "https://example.com/",
    "issue_flag": 8,
    "affected_urls": 12,
    "example_url": "https://example.com/checkout",
    "inbound_links": 40,
    "observed_at": _MONDAY,
}
_AHREFS = {
    "project_id": "4821",
    "issue_id": "4xx_page",
    "issue_name": "4XX page",
    "issue_category": "Internal pages",
    "issue_importance": "Error",
    "affected_urls": 7,
    "observed_at": _MONDAY,
}
_SEMRUSH = {
    "project_id": "9917",
    "issue_id": 8,
    "issue_title": "Broken internal links",
    "affected_pages": 1,
    "example_url": "https://example.com/blog",
    "audit_snapshot_id": "snap-1",
    "observed_at": _MONDAY,
}


@pytest.mark.parametrize(
    "emitter,base,overrides,expected_lines",
    [
        (
            bing_crawl_issue_emitter,
            _BING,
            {},
            [
                "Search engine crawl issue on https://example.com/: 12 URLs return an HTTP 5xx server error to Bingbot.",
                "Server errors stop the search engine from crawling and indexing these pages.",
                "Example URL: https://example.com/checkout",
                "Other pages link to the affected URLs 40 times.",
            ],
        ),
        (
            bing_crawl_issue_emitter,
            _BING,
            {"issue_flag": "256", "affected_urls": 1, "example_url": None, "inbound_links": 0},
            [
                "Search engine crawl issue on https://example.com/: 1 URL time out when Bingbot crawls them.",
                "Pages that time out are crawled less often and can drop out of the search index.",
            ],
        ),
        (
            ahrefs_site_audit_issue_emitter,
            _AHREFS,
            {},
            [
                "Site audit error: 4XX page (category: Internal pages)",
                "The latest site audit crawl found this issue on 7 URLs.",
            ],
        ),
        (
            ahrefs_site_audit_issue_emitter,
            _AHREFS,
            {"issue_importance": None, "issue_category": "", "affected_urls": "1"},
            ["Site audit issue: 4XX page", "The latest site audit crawl found this issue on 1 URL."],
        ),
        (
            semrush_site_audit_issue_emitter,
            _SEMRUSH,
            {},
            [
                "Site audit issue: Broken internal links",
                "The latest site audit found this issue on 1 page.",
                "Example page: https://example.com/blog",
            ],
        ),
    ],
)
def test_description(emitter, base, overrides, expected_lines):
    output = emitter(1, {**base, **overrides})

    assert output is not None
    assert output.description.split("\n") == expected_lines
    assert output.weight < 1.0


@pytest.mark.parametrize(
    "emitter,base,overrides",
    [
        # 301 and 302 flags report redirects, which are not faults, and an unknown bit has no text.
        (bing_crawl_issue_emitter, _BING, {"issue_flag": 1}),
        (bing_crawl_issue_emitter, _BING, {"issue_flag": 512}),
        (bing_crawl_issue_emitter, _BING, {"issue_flag": None}),
        (bing_crawl_issue_emitter, _BING, {"site_url": " "}),
        (bing_crawl_issue_emitter, _BING, {"affected_urls": 0}),
        (ahrefs_site_audit_issue_emitter, _AHREFS, {"issue_name": None}),
        (ahrefs_site_audit_issue_emitter, _AHREFS, {"issue_id": ""}),
        (ahrefs_site_audit_issue_emitter, _AHREFS, {"affected_urls": "not a number"}),
        (semrush_site_audit_issue_emitter, _SEMRUSH, {"issue_title": ""}),
        (semrush_site_audit_issue_emitter, _SEMRUSH, {"issue_id": None}),
        (semrush_site_audit_issue_emitter, _SEMRUSH, {"affected_pages": None}),
    ],
)
def test_skips_group_without_usable_issue(emitter, base, overrides):
    assert emitter(1, {**base, **overrides}) is None


@pytest.mark.parametrize(
    "source_id_for,base,overrides,expect_same",
    [
        (crawl_issue_source_id, _BING, {"observed_at": _SUNDAY, "affected_urls": 99}, True),
        (crawl_issue_source_id, _BING, {"observed_at": _NEXT_MONDAY}, False),
        (crawl_issue_source_id, _BING, {"issue_flag": 4}, False),
        (crawl_issue_source_id, _BING, {"site_url": "https://example.org/"}, False),
        (ahrefs_issue_source_id, _AHREFS, {"observed_at": _SUNDAY, "issue_importance": "Warning"}, True),
        (ahrefs_issue_source_id, _AHREFS, {"observed_at": _NEXT_MONDAY}, False),
        (ahrefs_issue_source_id, _AHREFS, {"project_id": "4822"}, False),
        (semrush_issue_source_id, _SEMRUSH, {"observed_at": _SUNDAY, "audit_snapshot_id": "snap-2"}, True),
        (semrush_issue_source_id, _SEMRUSH, {"observed_at": _NEXT_MONDAY}, False),
        (semrush_issue_source_id, _SEMRUSH, {"issue_id": 9}, False),
    ],
)
def test_issue_emits_once_per_week(source_id_for, base, overrides, expect_same):
    assert (source_id_for(base) == source_id_for({**base, **overrides})) is expect_same


@pytest.mark.parametrize(
    "table_name,expected",
    [
        ("semrush.site_audit_issue_details", "semrush.site_audit_issue_descriptions"),
        ("semrush.my_prefix.site_audit_issue_details", "semrush.my_prefix.site_audit_issue_descriptions"),
        ("site_audit_issue_details", "site_audit_issue_descriptions"),
    ],
)
def test_descriptions_table_keeps_the_source_prefix(table_name, expected):
    assert descriptions_table_name(table_name) == expected


def _fetcher_query(config: SignalSourceTableConfig, table_name: str) -> ast.SelectQuery:
    captured: dict[str, Any] = {}

    def fake_execute(query, **kwargs):
        captured["query"] = query
        result = MagicMock()
        result.results = []
        result.columns = []
        return result

    with patch(
        "products.signals.backend.emission.fetchers.grouped_warehouse.execute_hogql_query", side_effect=fake_execute
    ):
        config.record_fetcher(
            MagicMock(), config, {"table_name": table_name, "last_synced_at": "2026-11-12T00:00:00Z", "extra": {}}
        )
    return captured["query"]


@pytest.mark.parametrize(
    "config,table_name,expected_where",
    [
        (BING_WEBMASTER_TOOLS_CRAWL_ISSUES_CONFIG, "bingwebmastertools.crawl_issues", None),
        (
            AHREFS_SITE_AUDIT_ISSUES_CONFIG,
            "ahrefs.site_audit_issues",
            "and(greater(crawled, 0), in(importance, tuple('Error', 'Warning')))",
        ),
        (SEMRUSH_SITE_AUDIT_ISSUE_DETAILS_CONFIG, "semrush.site_audit_issue_details", None),
    ],
)
def test_snapshot_query_reads_the_whole_table(config, table_name, expected_where):
    query = _fetcher_query(config, table_name)

    assert (query.where.to_hogql() if query.where else None) == expected_where


def test_semrush_query_joins_the_titles_of_the_same_source():
    query = _fetcher_query(SEMRUSH_SITE_AUDIT_ISSUE_DETAILS_CONFIG, "semrush.my_prefix.site_audit_issue_details")

    assert query.select_from is not None and query.select_from.next_join is not None
    assert query.select_from.next_join.join_type == "INNER JOIN"
    subquery = query.select_from.next_join.table
    assert isinstance(subquery, ast.SelectQuery) and subquery.select_from is not None
    assert isinstance(subquery.select_from.table, ast.Field)
    assert subquery.select_from.table.chain == ["semrush", "my_prefix", "site_audit_issue_descriptions"]
