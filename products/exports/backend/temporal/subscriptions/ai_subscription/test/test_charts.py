from parameterized import parameterized

from products.exports.backend.temporal.subscriptions.ai_subscription.charts import validate_chart
from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import StepChart

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
        # The planner misremembering its own SELECT alias is the failure this exists to catch.
        ("unknown_x_column", _LINE, _response(columns=("date", "signups")), "missing_columns"),
        ("unknown_y_column", _LINE, _response(columns=("day", "count")), "missing_columns"),
        ("columns_missing_entirely", _LINE, {"results": _ROWS}, "missing_columns"),
        # Two points are a slope, not a shape.
        ("line_with_too_few_rows", _LINE, _response(rows=_ROWS[:2]), "too_few_rows"),
        ("bar_over_the_category_cap", _BAR, _response(rows=[[f"c{i}", i] for i in range(26)]), "too_many_categories"),
        ("empty_result", _LINE, _response(rows=[]), "no_results"),
        # The response shape comes from a query runner, not from us; a chart must never break a report.
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
        # A bar chart is about comparing named categories, so few rows is the normal case.
        ("bar_with_two_categories", _BAR, _response(rows=_ROWS[:2])),
        ("line_at_exactly_the_row_floor", _LINE, _response(rows=_ROWS)),
    ]
)
def test_shapes_that_chart_fine(_name, spec, response):
    chart, reason = _validate(spec, response)

    assert reason is None
    assert chart is not None
