"""Signal emitter for Bing Webmaster Tools `crawl_issues` (record kind: search_opportunity).

The table holds one row per URL with crawl issues, and `issues` is a bit mask of the issue types.
The fetcher splits each mask into its flags and groups the rows by (site, flag), so one issue type
on one site emits one signal instead of one per URL. See `_site_audit.py` for the snapshot dedupe.
The 301 and 302 flags only report redirects, which are not faults, so the query leaves them out.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra
from products.signals.backend.emission._site_audit import (
    OBSERVED_AT,
    OBSERVED_AT_SQL,
    SOURCE_TYPE,
    site_audit_config,
    site_audit_source_id,
    to_count,
)
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.grouped_warehouse import grouped_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput

logger = get_logger(__name__)

SOURCE_PRODUCT = "bing_webmaster_tools"

# Bit flag -> (what the affected URLs do, why it matters), from the GetCrawlIssues documentation.
ISSUE_FLAGS: dict[int, tuple[str, str]] = {
    4: (
        "return an HTTP 4xx client error to Bingbot",
        "Pages that return client errors drop out of the search index, and links to them are broken.",
    ),
    8: (
        "return an HTTP 5xx server error to Bingbot",
        "Server errors stop the search engine from crawling and indexing these pages.",
    ),
    16: (
        "are blocked by robots.txt",
        "Blocked pages cannot be crawled, so they cannot rank in search results.",
    ),
    32: (
        "contain malware",
        "Search engines warn users about or remove pages that contain malware.",
    ),
    64: (
        "are important URLs that robots.txt blocks",
        "Bing considers these URLs important, but robots.txt stops it from crawling them.",
    ),
    128: (
        "fail DNS resolution when Bingbot crawls them",
        "The search engine cannot reach these pages while their host name does not resolve.",
    ),
    256: (
        "time out when Bingbot crawls them",
        "Pages that time out are crawled less often and can drop out of the search index.",
    ),
}

BING_CRAWL_ISSUE_FIELDS = ("site_url", "issue_flag", "affected_urls", "example_url", "inbound_links", OBSERVED_AT)
EXTRA_FIELDS = ("site_url", "issue_flag", "affected_urls", "example_url", "inbound_links")

_FLAGS_SQL = ", ".join(str(flag) for flag in ISSUE_FLAGS)
_SELECT_SQL = f"""
    site_url,
    arrayJoin(arrayFilter(flag -> bitAnd(toInt(issues), flag) > 0, [{_FLAGS_SQL}])) AS issue_flag,
    count() AS affected_urls,
    min(url) AS example_url,
    sum(toInt(in_links)) AS inbound_links,
    {OBSERVED_AT_SQL}
"""


def crawl_issue_source_id(record: dict[str, Any]) -> str:
    return site_audit_source_id("bing_crawl_issue", record, ("site_url", "issue_flag"))


bing_crawl_issue_record_fetcher = grouped_warehouse_record_fetcher(
    select_sql=_SELECT_SQL,
    group_by_sql="site_url, issue_flag",
    order_by_sql="affected_urls DESC",
    source_id_for=crawl_issue_source_id,
    window_days=None,
)


def bing_crawl_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    site_url = clean_text(record.get("site_url"))
    flag = to_count(record.get("issue_flag"))
    issue = ISSUE_FLAGS.get(flag) if flag is not None else None
    affected_urls = to_count(record.get("affected_urls"))
    if not site_url or issue is None or not affected_urls:
        logger.info(
            "Ignoring Bing crawl issue group without a site, a known issue flag, or affected URLs",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    what, why = issue
    noun = "URL" if affected_urls == 1 else "URLs"
    lines = [f"Search engine crawl issue on {site_url}: {affected_urls} {noun} {what}.", why]
    example_url = clean_text(record.get("example_url"))
    if example_url:
        lines.append(f"Example URL: {example_url}")
    inbound_links = to_count(record.get("inbound_links"))
    if inbound_links:
        lines.append(f"Other pages link to the affected URLs {inbound_links} times.")
    return SignalEmitterOutput(
        source_product=SOURCE_PRODUCT,
        source_type=SOURCE_TYPE,
        source_id=crawl_issue_source_id(record),
        description="\n".join(lines),
        # Below the report threshold of 1.0, so one issue type alone cannot open a report.
        weight=0.5,
        extra={**build_extra(record, EXTRA_FIELDS, ()), "issue": what},
    )


BING_WEBMASTER_TOOLS_CRAWL_ISSUES_CONFIG = site_audit_config(
    source_product=SOURCE_PRODUCT,
    emitter=bing_crawl_issue_emitter,
    record_fetcher=bing_crawl_issue_record_fetcher,
    fields=BING_CRAWL_ISSUE_FIELDS,
)
