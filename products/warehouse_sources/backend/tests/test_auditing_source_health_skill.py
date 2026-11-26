import re
from pathlib import Path

from posthog.hogql import ast
from posthog.hogql.database.schema.system import source_sync_jobs
from posthog.hogql.parser import parse_select

from products.warehouse_sources.backend.presentation.views.external_data_schema import (
    ExternalDataSchemaCompactSerializer,
    ExternalDataSchemaSerializer,
)

# Agents follow this section to call a `Completed` schema broken, so it must judge staleness by the
# stamp that moves on every successful sync, not by `last_synced_at`, which stays old on a quiet source.
_SKILL_PATH = Path(__file__).parents[2] / "skills" / "auditing-warehouse-source-health" / "SKILL.md"
_STALENESS_SECTION = re.search(
    r'\*\*Stale but "Completed" schemas:\*\*\n(.*?)\n\*\*', _SKILL_PATH.read_text(), re.DOTALL
)


def _section() -> str:
    assert _STALENESS_SECTION is not None
    return _STALENESS_SECTION.group(1)


def test_staleness_fields_need_the_full_schema_rows() -> None:
    assert {"last_checked_at", "sync_frequency"} <= set(ExternalDataSchemaSerializer.Meta.fields)
    assert "sync_frequency" not in ExternalDataSchemaCompactSerializer.Meta.fields


def test_job_history_query_reads_real_columns_without_the_raw_error() -> None:
    [sql] = re.findall(r"```sql\n(.*?)```", _section(), re.DOTALL)
    query = parse_select(sql.replace("<schema id>", "00000000-0000-0000-0000-000000000000"))
    assert isinstance(query, ast.SelectQuery)
    assert query.select_from is not None and isinstance(query.select_from.table, ast.Field)
    assert query.select_from.table.chain == ["system", "source_sync_jobs"]
    assert isinstance(query.where, ast.CompareOperation)
    assert isinstance(query.where.left, ast.Field) and query.where.left.chain == ["schema_id"]

    selected = [field.chain[-1] for field in query.select if isinstance(field, ast.Field)]
    assert len(selected) == len(query.select)
    assert {"status", "created_at"} <= set(selected)
    assert set(selected) <= set(source_sync_jobs.fields)
    # The job table stores the raw error; the schema list returns the redacted one.
    assert "latest_error" not in selected
