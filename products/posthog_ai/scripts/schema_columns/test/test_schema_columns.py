from __future__ import annotations

import re
from pathlib import Path

import pytest

from products.posthog_ai.scripts.build_skills import SkillRenderer
from products.posthog_ai.scripts.schema_columns import schema_columns

REPO_ROOT = Path(__file__).resolve().parents[5]
REFERENCES = Path(__file__).resolve().parents[3] / "skills" / "querying-posthog-data" / "references"

# Every doc that teaches the `execute-sql` schema-discovery path. The guidelines file is copied
# verbatim into the MCP bundle and the section file is spliced into the `execute-sql` tool
# description, so a wrong field name here reaches every agent that reads one of them.
SCHEMA_DISCOVERY_DOCS = (
    REFERENCES / "guidelines.md",
    REPO_ROOT / "services" / "mcp" / "src" / "templates" / "sections" / "schema-discovery.md",
    REPO_ROOT / "products" / "customer_analytics" / "skills" / "SKILL.md",
)

# `- `tables` — one row per table. Fields: table_catalog, table_schema, …`
DOCUMENTED_FIELDS = re.compile(r"^- `(\w+)` — .*?Fields: ([^.]+)\.", re.MULTILINE)

# A `SELECT … FROM system.information_schema.<surface>`, fenced or inline. The select list may
# span lines but must not swallow an intervening `FROM`, or a query over another table pairs up
# with the next information_schema one.
DOCUMENTED_QUERY = re.compile(
    r"SELECT\s+((?:(?!\bFROM\b)[\s\S])+?)\s+FROM\s+system\.information_schema\.(\w+)", re.IGNORECASE
)


def _live_fields(surface: str) -> list[str]:
    from posthog.hogql.database.models import Table
    from posthog.hogql.database.schema.information_schema import information_schema_node

    table = information_schema_node().children[surface].table
    assert isinstance(table, Table)
    return list(table.fields)


def _projected_names(select_list: str) -> list[str]:
    names = []
    for item in select_list.split(","):
        # Strip an alias, then keep the projection only when it is a bare column reference —
        # `count()` and other expressions are not fields and have nothing to check against.
        expression = re.split(r"\s+AS\s+", item.strip(), flags=re.IGNORECASE)[0].strip()
        if re.fullmatch(r"\w+", expression):
            names.append(expression)
    return names


# A four-column row (`col` | type | nullable | description) is a schema table. The two-column
# `field` | description tables in these docs describe nested JSON, not columns.
HAND_WRITTEN_COLUMN_ROW = re.compile(r"^`[^`]+`\s*\|.*\|.*\|")


def test_model_references_render_without_hand_written_columns() -> None:
    renderer = SkillRenderer()
    paths = sorted(REFERENCES.glob("models-*.md.j2"))
    assert paths, f"no model reference templates found in {REFERENCES}"

    for path in paths:
        renderer.render(path)  # raises if a referenced table no longer exists in the catalog
        offenders = [line for line in path.read_text().splitlines() if HAND_WRITTEN_COLUMN_ROW.match(line)]
        assert not offenders, (
            f"{path.name} hand-writes column rows instead of calling schema_columns(): {offenders[:3]}. "
            "Columns drift out of sync with HogQL when copied from the Django models."
        )


def test_unknown_table_raises() -> None:
    with pytest.raises(ValueError, match="system.not_a_table"):
        schema_columns("system.not_a_table")


def test_renders_only_columns_hogql_exposes() -> None:
    rendered = schema_columns("system.insights")

    assert "`team_id` | Integer | NOT NULL" in rendered
    # `deleted` is an expression column over the hidden `_deleted`; the alias is what resolves.
    assert "`deleted` | Integer | NOT NULL" in rendered
    assert "`_deleted`" not in rendered
    # Django-model fields HogQL does not expose, which the docs used to advertise.
    for absent in ("is_sample", "derived_name", "filters_hash", "refreshing"):
        assert absent not in rendered


def test_renders_session_recording_nullability() -> None:
    rendered = schema_columns("system.session_recordings")

    for column in (
        "distinct_id",
        "duration",
        "active_seconds",
        "inactive_seconds",
        "start_time",
        "end_time",
        "click_count",
        "keypress_count",
        "mouse_activity_count",
        "console_log_count",
        "console_warn_count",
        "console_error_count",
        "start_url",
        "deleted",
        "created_at",
        "retention_period_days",
        "storage_version",
    ):
        assert f"`{column}` | " in rendered
        assert (
            next(line for line in rendered.splitlines() if line.startswith(f"`{column}` | ")).split(" | ")[2]
            == "NOT NULL"
        )


def test_renders_usage_metric_contract() -> None:
    rendered = schema_columns("system.usage_metrics")

    assert (
        "`group_type_index` | Integer | NOT NULL | Legacy; the query runner ignores it and evaluates every metric regardless. Don't filter on it."
        in rendered
    )
    assert "`format` | String | NOT NULL | Display format: 'numeric' or 'currency'." in rendered
    assert "`math` | String | NOT NULL | Aggregation: 'count' or 'sum'; 'sum' aggregates math_property." in rendered


def test_documented_information_schema_fields_match_the_catalog() -> None:
    documented = DOCUMENTED_FIELDS.findall((REFERENCES / "guidelines.md").read_text())
    assert {surface for surface, _ in documented} == {"tables", "columns", "relationships", "data_types"}

    for surface, field_list in documented:
        fields = [field.strip() for field in field_list.split(",")]
        assert fields == _live_fields(surface), (
            f"guidelines.md documents the wrong fields for system.information_schema.{surface}. "
            "Agents project what this list says, so a stale entry fails their query."
        )


def test_documented_information_schema_queries_project_real_fields() -> None:
    for path in SCHEMA_DISCOVERY_DOCS:
        text = path.read_text()
        queries = DOCUMENTED_QUERY.findall(text)
        assert queries, f"{path.name} documents no information_schema query"

        for select_list, surface in queries:
            live = _live_fields(surface)
            for name in _projected_names(select_list):
                assert name in live, (
                    f"{path.name} projects `{name}` from system.information_schema.{surface}, "
                    f"which only exposes {live}."
                )

        # The namespace is only reachable under `system.`; querying an unqualified
        # `information_schema.*` fails on an unknown table.
        assert not re.search(r"\bFROM\s+information_schema\.", text, re.IGNORECASE)
