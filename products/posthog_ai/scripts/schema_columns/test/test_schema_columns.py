from __future__ import annotations

import pytest

from products.posthog_ai.scripts.schema_columns import schema_columns


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
