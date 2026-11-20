"""Signal emitter for Semrush `site_audit_issue_details` (record kind: search_opportunity).

The table holds one row per page that an issue of the latest Site Audit snapshot affects, and names
the issue only by its numeric id. The issue title lives in the sibling `site_audit_issue_descriptions`
table, so the fetcher joins it and groups the rows by issue, which emits one signal per issue type
instead of one per page. An issue whose title has not synced yet drops out of the join and emits on a
later sync. See `_site_audit.py` for the snapshot dedupe.
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
from products.signals.backend.emission.fetchers.data_warehouse import escape_table_name
from products.signals.backend.emission.fetchers.grouped_warehouse import grouped_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput

logger = get_logger(__name__)

SOURCE_PRODUCT = "semrush"
DESCRIPTIONS_TABLE = "site_audit_issue_descriptions"

SEMRUSH_ISSUE_FIELDS = (
    "project_id",
    "issue_id",
    "issue_title",
    "affected_pages",
    "example_url",
    "audit_snapshot_id",
    OBSERVED_AT,
)
EXTRA_FIELDS = ("project_id", "issue_id", "affected_pages", "example_url", "audit_snapshot_id")

_SELECT_SQL = f"""
    details.project_id AS project_id,
    details.issue_id AS issue_id,
    any(descriptions.description_title) AS issue_title,
    uniqExact(details.source_url) AS affected_pages,
    min(details.source_url) AS example_url,
    any(details.snapshot_id) AS audit_snapshot_id,
    {OBSERVED_AT_SQL}
"""


def descriptions_table_name(table_name: str) -> str:
    """The sibling descriptions table of the same source, which keeps the details table's prefix."""
    head, _, _ = table_name.rpartition(".")
    return f"{head}.{DESCRIPTIONS_TABLE}" if head else DESCRIPTIONS_TABLE


def _from_sql(table_name: str) -> str:
    return f"""{escape_table_name(table_name)} AS details
        INNER JOIN (
            SELECT toString(id) AS description_issue_id, any(title) AS description_title
            FROM {escape_table_name(descriptions_table_name(table_name))}
            GROUP BY description_issue_id
        ) AS descriptions ON toString(details.issue_id) = descriptions.description_issue_id"""


def semrush_issue_source_id(record: dict[str, Any]) -> str:
    return site_audit_source_id("semrush_site_audit_issue", record, ("project_id", "issue_id"))


semrush_site_audit_issue_record_fetcher = grouped_warehouse_record_fetcher(
    select_sql=_SELECT_SQL,
    group_by_sql="details.project_id, details.issue_id",
    order_by_sql="affected_pages DESC",
    source_id_for=semrush_issue_source_id,
    window_days=None,
    from_sql=_from_sql,
)


def semrush_site_audit_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    title = clean_text(record.get("issue_title"))
    affected_pages = to_count(record.get("affected_pages"))
    if not title or not clean_text(record.get("issue_id")) or not affected_pages:
        logger.info(
            "Ignoring Semrush site audit issue without a title, an id, or affected pages",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    noun = "page" if affected_pages == 1 else "pages"
    lines = [
        f"Site audit issue: {title}",
        f"The latest site audit found this issue on {affected_pages} {noun}.",
    ]
    example_url = clean_text(record.get("example_url"))
    if example_url:
        lines.append(f"Example page: {example_url}")
    return SignalEmitterOutput(
        source_product=SOURCE_PRODUCT,
        source_type=SOURCE_TYPE,
        source_id=semrush_issue_source_id(record),
        description="\n".join(lines),
        # Below the report threshold of 1.0, so one issue type alone cannot open a report.
        weight=0.5,
        extra=build_extra(record, EXTRA_FIELDS, ()),
    )


SEMRUSH_SITE_AUDIT_ISSUE_DETAILS_CONFIG = site_audit_config(
    source_product=SOURCE_PRODUCT,
    emitter=semrush_site_audit_issue_emitter,
    record_fetcher=semrush_site_audit_issue_record_fetcher,
    fields=SEMRUSH_ISSUE_FIELDS,
)
