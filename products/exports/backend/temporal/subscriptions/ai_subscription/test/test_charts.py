import time
from contextlib import ExitStack

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.exports.backend.temporal.subscriptions.ai_subscription.charts import (
    ChartFailureReason,
    ChartRenderFailure,
    ValidatedChart,
    build_export_context,
    render_charts,
    validate_chart,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import StepChart

_CHARTS = "products.exports.backend.temporal.subscriptions.ai_subscription.charts"

_LINE = StepChart(display="ActionsLineGraph", x_column="day", y_columns=["signups"])
_BAR = StepChart(display="ActionsBar", x_column="day", y_columns=["signups"])
_ROWS = [["2026-08-01", 1], ["2026-08-02", 2], ["2026-08-03", 3]]


def _response(rows=None, columns=("day", "signups")):
    return {"results": _ROWS if rows is None else rows, "columns": list(columns)}


def _validate(spec=_LINE, response=None):
    return validate_chart(
        spec,
        _response() if response is None else response,
        hogql="SELECT 1",
        title="signups by day",
        step_index=2,
    )


def test_a_well_formed_chart_validates():
    chart, reason = _validate()

    assert reason is None
    assert chart is not None
    assert chart.hogql == "SELECT 1"
    assert chart.title == "signups by day"
    assert chart.step_index == 2


@parameterized.expand(
    [
        ("unknown_x_column", _LINE, _response(columns=("date", "signups")), "missing_columns"),
        ("unknown_y_column", _LINE, _response(columns=("day", "count")), "missing_columns"),
        ("columns_missing_entirely", _LINE, {"results": _ROWS}, "missing_columns"),
        ("line_with_too_few_rows", _LINE, _response(rows=_ROWS[:2]), "too_few_rows"),
        ("bar_over_the_category_cap", _BAR, _response(rows=[[f"c{i}", i] for i in range(26)]), "too_many_categories"),
        ("empty_result", _LINE, _response(rows=[]), "no_results"),
        (
            "x_and_y_are_the_same_column",
            StepChart(display="ActionsBar", x_column="signups", y_columns=["signups"]),
            _response(),
            "x_and_y_identical",
        ),
        ("bar_over_a_single_row", _BAR, _response(rows=[["a", 1]]), "too_few_rows"),
        (
            "unsupported_display",
            StepChart(display="ActionsPie", x_column="day", y_columns=["signups"]),
            _response(),
            "unsupported_display",
        ),
        (
            "too_many_series",
            StepChart(display="ActionsLineGraph", x_column="day", y_columns=[f"c{i}" for i in range(5)]),
            _response(),
            "unsupported_series_count",
        ),
        (
            "no_series",
            StepChart(display="ActionsLineGraph", x_column="day", y_columns=[]),
            _response(),
            "unsupported_series_count",
        ),
        ("truncated_result", _LINE, {**_response(), "hasMore": True}, "truncated_result"),
        (
            "non_numeric_series",
            _LINE,
            {"results": _ROWS, "columns": ["day", "signups"], "types": [["day", "Date"], ["signups", "String"]]},
            "non_numeric_series",
        ),
        ("malformed_results", _LINE, {"results": "nonsense"}, "no_results"),
        ("response_is_not_a_dict", _LINE, "nonsense", "no_results"),
    ]
)
def test_an_unchartable_result_is_dropped_with_a_reason(_name, spec, response, expected_reason):
    chart, reason = _validate(spec, response)

    assert chart is None
    assert reason == expected_reason


@parameterized.expand(
    [
        ("bar_with_two_categories", _BAR, _response(rows=_ROWS[:2])),
        ("line_at_exactly_the_row_floor", _LINE, _response(rows=_ROWS)),
        (
            "numeric_series_declared",
            _LINE,
            {"results": _ROWS, "columns": ["day", "signups"], "types": [["day", "Date"], ["signups", "UInt64"]]},
        ),
        ("unreadable_types_skips_the_check", _LINE, {"results": _ROWS, "columns": ["day", "signups"], "types": "?"}),
    ]
)
def test_shapes_that_chart_fine(_name, spec, response):
    chart, reason = _validate(spec, response)

    assert reason is None
    assert chart is not None


def _chart(spec=_LINE, hogql="SELECT 1", step_index=0) -> ValidatedChart:
    return ValidatedChart(spec=spec, hogql=hogql, title="signups", step_index=step_index)


def test_the_export_context_pins_the_render_to_the_step_row_limits():
    assert build_export_context(_chart())["limit_context"] == "posthog_ai"


def test_the_export_context_wraps_the_executed_sql_for_the_renderer():
    source = build_export_context(_chart())["source"]

    assert source["kind"] == "DataVisualizationNode"
    assert source["source"] == {"kind": "HogQLQuery", "query": "SELECT 1"}
    assert source["display"] == "ActionsLineGraph"
    assert source["chartSettings"]["xAxis"] == {"column": "day"}
    assert source["chartSettings"]["yAxis"] == [{"column": "signups"}]


@parameterized.expand(
    [
        ("multi_series", ["signups", "activations"], True),
        ("single_series", ["signups"], False),
    ]
)
def test_the_legend_is_on_only_when_there_is_more_than_one_series(_name, y_columns, expected):
    spec = StepChart(display="ActionsLineGraph", x_column="day", y_columns=y_columns)

    settings = build_export_context(_chart(spec))["source"]["chartSettings"]

    assert settings.get("showLegend", False) is expected


async def test_a_rendered_chart_carries_its_asset_id():
    with patch(f"{_CHARTS}.render_png_export", return_value=(MagicMock(id=4321), b"png")):
        rendered, failures = await render_charts([_chart()], team=MagicMock(), user=MagicMock())

    assert failures == []
    assert rendered[0].export_asset_id == 4321
    assert rendered[0].title == "signups"


async def test_a_failed_render_drops_that_chart_and_keeps_the_rest():
    charts = [_chart(hogql="SELECT 1", step_index=0), _chart(hogql="SELECT 2", step_index=1)]

    def _render(**kwargs):
        if kwargs["export_context"]["source"]["source"]["query"] == "SELECT 1":
            return MagicMock(id=1, exception="boom"), None
        return MagicMock(id=2, exception=None), b"png"

    with patch(f"{_CHARTS}.render_png_export", side_effect=_render):
        rendered, failures = await render_charts(charts, team=MagicMock(), user=MagicMock())

    assert [chart.export_asset_id for chart in rendered] == [2]
    assert failures == [ChartRenderFailure(step_index=0, reason=ChartFailureReason.RENDER_FAILED)]


def _hangs(**kwargs):
    time.sleep(5)
    return MagicMock(id=1, exception=None), b"png"


def _raises(**kwargs):
    raise RuntimeError("browserless down")


def _returns_no_png(**kwargs):
    return MagicMock(id=1, exception="boom"), None


@parameterized.expand(
    [
        ("the_renderer_raises", _raises, {}, ChartFailureReason.RENDER_ERROR),
        ("the_export_produced_no_png", _returns_no_png, {}, ChartFailureReason.RENDER_FAILED),
        ("one_render_hangs", _hangs, {"_RENDER_TIMEOUT_SECONDS": 0.2}, ChartFailureReason.RENDER_TIMED_OUT),
        (
            "the_phase_budget_runs_out",
            _hangs,
            {"_CHART_PHASE_BUDGET_SECONDS": 0.1},
            ChartFailureReason.BUDGET_EXHAUSTED,
        ),
    ]
)
async def test_a_chart_that_cannot_render_is_dropped_with_a_reason(_name, side_effect, overrides, expected):
    with ExitStack() as stack:
        stack.enter_context(patch(f"{_CHARTS}.render_png_export", side_effect=side_effect))
        for attribute, value in overrides.items():
            stack.enter_context(patch(f"{_CHARTS}.{attribute}", value))
        rendered, failures = await render_charts([_chart()], team=MagicMock(), user=MagicMock())

    assert rendered == []
    assert failures == [ChartRenderFailure(step_index=0, reason=expected)]


async def test_a_slow_chart_does_not_discard_the_ones_that_rendered():
    charts = [_chart(hogql="FAST", step_index=0), _chart(hogql="SLOW", step_index=1)]

    def _render(**kwargs):
        if kwargs["export_context"]["source"]["source"]["query"] == "SLOW":
            time.sleep(5)
        return MagicMock(id=7, exception=None), b"png"

    with (
        patch(f"{_CHARTS}._CHART_PHASE_BUDGET_SECONDS", 1.5),
        patch(f"{_CHARTS}.render_png_export", side_effect=_render),
    ):
        rendered, failures = await render_charts(charts, team=MagicMock(), user=MagicMock())

    assert [chart.step_index for chart in rendered] == [0]
    assert failures == [ChartRenderFailure(step_index=1, reason=ChartFailureReason.BUDGET_EXHAUSTED)]
