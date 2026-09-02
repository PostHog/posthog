from __future__ import annotations

from products.posthog_ai.scripts.hogql_functions import hogql_functions


def test_returns_sorted_list() -> None:
    result = hogql_functions()
    assert isinstance(result, list)
    assert len(result) > 100
    assert result == sorted(result, key=str.lower)


def test_excludes_underscore_prefixed() -> None:
    result = hogql_functions()
    assert all(not name.startswith("_") for name in result)


def test_excludes_udfs() -> None:
    from posthog.hogql.functions.udfs import UDFS

    result = set(hogql_functions())
    for udf_name in UDFS:
        assert udf_name not in result


def test_excludes_if_combinators() -> None:
    result = set(hogql_functions())
    assert "countIf" not in result
    assert "sumIf" not in result
    assert "avgIf" not in result


def test_keeps_standalone_if_functions() -> None:
    result = set(hogql_functions())
    assert "if" in result
    assert "multiIf" in result


def test_includes_common_functions() -> None:
    result = set(hogql_functions())
    assert "count" in result
    assert "sum" in result
    assert "concat" in result
    assert "toDateTime" in result
