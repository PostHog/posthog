from __future__ import annotations

import re
from pathlib import Path

import pytest

from products.posthog_ai.scripts.build_skills import SkillRenderer
from products.posthog_ai.scripts.schema_columns import schema_columns

REFERENCES = Path(__file__).resolve().parents[3] / "skills" / "querying-posthog-data" / "references"

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
