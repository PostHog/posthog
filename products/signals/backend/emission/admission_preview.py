from datetime import datetime
from typing import Any

import structlog

from posthog.hogql.database.database import get_data_warehouse_table_name
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.contracts import ADMISSION_RULES_KEY
from products.signals.backend.emission.fetchers.data_warehouse import (
    data_warehouse_record_fetcher,
    eligibility_conditions,
    escape_table_name,
    partition_expression,
)
from products.signals.backend.emission.registry import (
    SignalSourceTableConfig,
    get_signal_config,
    get_signal_registrations,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSchema

logger = structlog.get_logger(__name__)

ADMISSION_PREVIEW_LIMIT = 20
ADMISSION_PREVIEW_LOOKBACK_DAYS = 30
# A GitHub source has one table per repository. The cap bounds the queries one preview runs.
ADMISSION_PREVIEW_MAX_TABLES = 10


@frozen
class AdmissionPreviewIssue:
    title: str
    url: str | None
    created_at: datetime | None


@frozen
class AdmissionPreview:
    issues: list[AdmissionPreviewIssue]
    truncated: bool
    tables_checked: int
    tables_skipped: int


def _preview_tables(team_id: int, source_product: str, source_type: str) -> list[tuple[str, SignalSourceTableConfig]]:
    """The synced warehouse tables that emit as this source, with the config that reads each one."""
    registrations = {
        warehouse_source_type: config
        for warehouse_source_type, config in get_signal_registrations(source_product, source_type)
        if config.admission_fields
        and config.admission_preview_title_field
        and config.admission_preview_url_field
        and config.record_fetcher is data_warehouse_record_fetcher
    }
    if not registrations:
        return []
    schemas = (
        ExternalDataSchema.objects.filter(
            team_id=team_id, source__source_type__in=list(registrations), table__isnull=False
        )
        .exclude(deleted=True)
        .exclude(source__deleted=True)
        .exclude(table__deleted=True)
        .select_related("source", "table")
        .order_by("created_at")
    )
    tables: list[tuple[str, SignalSourceTableConfig]] = []
    for schema in schemas:
        config = get_signal_config(schema.source.source_type, schema.name)
        if config is None or config is not registrations.get(schema.source.source_type) or schema.table is None:
            continue
        tables.append((get_data_warehouse_table_name(schema.source, schema.table.name), config))
    return tables


def preview_admission(
    *, team: Team, user: User, source_product: str, source_type: str, source_config: Any, admission_rules: Any
) -> AdmissionPreview:
    """The most recent synced issues that the source's next sync would admit with `admission_rules`.

    The query runs as `user`, so warehouse access control applies, and it uses the same static
    exclusions, scope allowlist and rule compiler as emission. It makes no model call and emits nothing.
    The caller validates `admission_rules`. Raises `QueryError` when the user cannot read a table.
    """
    draft_config = {**(source_config if isinstance(source_config, dict) else {}), ADMISSION_RULES_KEY: admission_rules}
    tables = _preview_tables(team.id, source_product, source_type)
    checked = tables[:ADMISSION_PREVIEW_MAX_TABLES]
    issues: list[AdmissionPreviewIssue] = []
    truncated = False
    for table_name, config in checked:
        eligibility = eligibility_conditions(config, draft_config)
        placeholders = eligibility.placeholders
        partition_expr = partition_expression(config)
        where_sql = " AND ".join(
            [f"{partition_expr} > now() - interval {ADMISSION_PREVIEW_LOOKBACK_DAYS} day", *eligibility.where_parts]
        )
        query = f"""
            SELECT {config.admission_preview_title_field} AS title,
                {config.admission_preview_url_field} AS url,
                {partition_expr} AS created_at
            FROM {escape_table_name(table_name)}
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT {ADMISSION_PREVIEW_LIMIT + 1}
        """
        result = execute_hogql_query(
            query=parse_select(query, placeholders=placeholders) if placeholders else parse_select(query),
            team=team,
            user=user,
            query_type="SignalSourceAdmissionPreview",
            workload=Workload.ONLINE,
        )
        rows = result.results or []
        truncated = truncated or len(rows) > ADMISSION_PREVIEW_LIMIT
        issues.extend(
            AdmissionPreviewIssue(title=str(title or ""), url=str(url) if url else None, created_at=created_at)
            for title, url, created_at in rows[:ADMISSION_PREVIEW_LIMIT]
        )
    issues.sort(key=lambda issue: issue.created_at.timestamp() if issue.created_at else 0, reverse=True)
    if len(issues) > ADMISSION_PREVIEW_LIMIT:
        truncated = True
    logger.info(
        "Previewed admission rules",
        team_id=team.id,
        source_product=source_product,
        source_type=source_type,
        tables_checked=len(checked),
        tables_skipped=len(tables) - len(checked),
        matched=len(issues),
        truncated=truncated,
        signals_type="data-import-signals",
    )
    return AdmissionPreview(
        issues=issues[:ADMISSION_PREVIEW_LIMIT],
        truncated=truncated,
        tables_checked=len(checked),
        tables_skipped=len(tables) - len(checked),
    )
