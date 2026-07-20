import json
import datetime as dt
from decimal import Decimal

import pytest

from posthog.caching.fetch_from_cache import InsightResult

from products.exports.backend.temporal.subscriptions.insight_snapshot import (
    _has_comparison_enabled,
    _serialize_insight_result,
)


def _build_insight_result(**overrides) -> InsightResult:
    base: dict = {
        "result": [],
        "columns": [],
        "types": [],
        "last_refresh": dt.datetime(2026, 4, 20, tzinfo=dt.UTC),
        "is_cached": False,
        "timezone": "UTC",
        "has_more": False,
        "resolved_date_range": None,
        "query_status": None,
        "cache_key": None,
        "cache_target_age": None,
        "next_allowed_client_refresh": None,
        "hogql": None,
    }
    base.update(overrides)
    return InsightResult(**base)


@pytest.mark.parametrize(
    "query_json,expected",
    [
        (None, False),
        ("not a dict", False),
        ({}, False),
        ({"source": {"kind": "TrendsQuery"}}, False),
        ({"source": {"kind": "TrendsQuery", "compareFilter": None}}, False),
        ({"source": {"kind": "TrendsQuery", "compareFilter": {}}}, False),
        ({"source": {"kind": "TrendsQuery", "compareFilter": {"compare": False}}}, False),
        ({"source": {"kind": "TrendsQuery", "compareFilter": {"compare": True}}}, True),
        ({"source": {"kind": "TrendsQuery", "compareFilter": {"compare": True, "compare_to": "-7d"}}}, True),
        # bare query object (no DataVisualizationNode wrapper)
        ({"kind": "TrendsQuery", "compareFilter": {"compare": True}}, True),
        ({"kind": "TrendsQuery", "compareFilter": {"compare": False}}, False),
        # non-dict compareFilter should not crash
        ({"source": {"kind": "TrendsQuery", "compareFilter": "broken"}}, False),
    ],
)
def test_has_comparison_enabled(query_json, expected):
    assert _has_comparison_enabled(query_json) is expected


def test_serialize_insight_result_non_finite_floats_become_null():
    result = _build_insight_result(
        result=[
            [float("nan"), 1.0, float("inf")],
            ["Final: $pageview", 0, 0.0, float("nan")],
        ],
        columns=["a", "b", "c", "d"],
        types=["float", "float", "float", "float"],
    )

    serialized = _serialize_insight_result(result)

    reparsed = json.loads(json.dumps(serialized))
    assert reparsed["result"] == [
        [None, 1.0, None],
        ["Final: $pageview", 0, 0.0, None],
    ]


def test_serialize_insight_result_strips_null_bytes():
    # Regression witness: ClickHouse result strings can carry NUL (\x00). Django's JSONField
    # serializes it to a unicode escape that Postgres text/jsonb reject, failing the whole
    # subscription delivery write. The NUL must be stripped while the rest of the string survives.
    result = _build_insight_result(
        # A Map(String, …) column deserializes to a dict, so NUL can land in a key too.
        result=[["Success?\x00 Yes: Env", {"la\x00bel": "val\x00ue"}], ["\x00leading", "trailing\x00"]],
        columns=["label\x00", "value"],
        types=["String", "String"],
    )

    serialized = _serialize_insight_result(result)

    # Round-trip through stdlib json (what JSONField uses) must not raise and must be NUL-free.
    reparsed = json.loads(json.dumps(serialized))
    assert reparsed["result"] == [["Success? Yes: Env", {"label": "value"}], ["leading", "trailing"]]
    assert reparsed["columns"] == ["label", "value"]
    assert "\x00" not in json.dumps(serialized)


def test_serialize_insight_result_handles_decimal_and_date():
    # Regression witness: orjson raises on Decimal without a default= hook, and stdlib json
    # raises on bare date. Both used to live on the ClickHouse result path for revenue /
    # analytics queries.
    result = _build_insight_result(
        result=[[Decimal("1.5"), dt.date(2026, 4, 20)]],
        columns=["revenue", "day"],
        types=["Decimal(10,2)", "Date"],
    )

    serialized = _serialize_insight_result(result)

    reparsed = json.loads(json.dumps(serialized))
    assert reparsed["result"] == [["1.5", "2026-04-20"]]
