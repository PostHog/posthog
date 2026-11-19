"""Signal emitter for Ahrefs `site_audit_issues` (record kind: search_opportunity).

The table already holds one row per issue type of the project's latest crawl, with the number of URLs
the issue affects in `crawled`. Ahrefs lists issue types that affect no URL too, so the query keeps
only rows with affected URLs, and only the Error and Warning importance levels: Notices are
informational. See `_site_audit.py` for the snapshot dedupe.
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

SOURCE_PRODUCT = "ahrefs"

AHREFS_SITE_AUDIT_ISSUE_FIELDS = (
    "project_id",
    "issue_id",
    "issue_name",
    "issue_category",
    "issue_importance",
    "affected_urls",
    OBSERVED_AT,
)
EXTRA_FIELDS = ("project_id", "issue_id", "issue_category", "issue_importance", "affected_urls")

# One row per (project, issue type) already, so the grouping only collapses a repeated row.
_SELECT_SQL = f"""
    project_id,
    issue_id,
    any(name) AS issue_name,
    any(category) AS issue_category,
    any(importance) AS issue_importance,
    max(crawled) AS affected_urls,
    {OBSERVED_AT_SQL}
"""

_WEIGHT_BY_IMPORTANCE = {"error": 0.7, "warning": 0.5}


def ahrefs_issue_source_id(record: dict[str, Any]) -> str:
    return site_audit_source_id("ahrefs_site_audit_issue", record, ("project_id", "issue_id"))


ahrefs_site_audit_issue_record_fetcher = grouped_warehouse_record_fetcher(
    select_sql=_SELECT_SQL,
    group_by_sql="project_id, issue_id",
    order_by_sql="affected_urls DESC",
    source_id_for=ahrefs_issue_source_id,
    window_days=None,
)


def ahrefs_site_audit_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    name = clean_text(record.get("issue_name"))
    affected_urls = to_count(record.get("affected_urls"))
    if not name or not clean_text(record.get("issue_id")) or not affected_urls:
        logger.info(
            "Ignoring Ahrefs site audit issue without a name, an id, or affected URLs",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    importance = clean_text(record.get("issue_importance"))
    category = clean_text(record.get("issue_category"))
    noun = "URL" if affected_urls == 1 else "URLs"
    summary = f"Site audit {importance.lower() or 'issue'}: {name}"
    if category:
        summary += f" (category: {category})"
    lines = [summary, f"The latest site audit crawl found this issue on {affected_urls} {noun}."]
    return SignalEmitterOutput(
        source_product=SOURCE_PRODUCT,
        source_type=SOURCE_TYPE,
        source_id=ahrefs_issue_source_id(record),
        description="\n".join(lines),
        # Below the report threshold of 1.0, so one issue type alone cannot open a report.
        weight=_WEIGHT_BY_IMPORTANCE.get(importance.lower(), 0.5),
        extra=build_extra(record, EXTRA_FIELDS, ()),
    )


AHREFS_SITE_AUDIT_ISSUES_CONFIG = site_audit_config(
    source_product=SOURCE_PRODUCT,
    emitter=ahrefs_site_audit_issue_emitter,
    record_fetcher=ahrefs_site_audit_issue_record_fetcher,
    fields=AHREFS_SITE_AUDIT_ISSUE_FIELDS,
    where_clause="crawled > 0 AND importance IN ('Error', 'Warning')",
)
