from parameterized import parameterized

from products.exports.backend.temporal.subscriptions.results_text import (
    MAX_COLUMNS,
    MAX_ROWS,
    build_results_text,
    build_results_text_for_snapshot,
)


class TestBuildResultsText:
    @parameterized.expand(
        [
            ("no_results", None, None),
            ("empty", [], ["a"]),
            # Trends/funnel/retention rows are dicts of series, not table rows — those stay
            # images, and rendering them as text would put a nonsense block in every report.
            ("trend_series", [{"label": "Pageviews", "data": [1, 2, 3]}], None),
            ("too_many_columns", [list(range(MAX_COLUMNS + 1))], [f"c{i}" for i in range(MAX_COLUMNS + 1)]),
        ]
    )
    def test_returns_none_for_unrenderable_results(self, _name, results, columns) -> None:
        assert build_results_text(results, columns) is None

    def test_long_table_is_previewed_with_the_hidden_row_count(self) -> None:
        text = build_results_text([[i] for i in range(MAX_ROWS + 3)], ["n"])

        assert text is not None
        lines = text.splitlines()
        # Header + separator + MAX_ROWS rows + the "and N more" line.
        assert len(lines) == MAX_ROWS + 3
        assert lines[-1] == "... and 3 more rows"

    def test_single_row_renders_label_value_lines(self) -> None:
        text = build_results_text(
            [[12, 3, "in 2h14m"]],
            ["Tickets in view", "Breached SLAs", "Next SLA breach"],
        )

        assert text is not None
        assert text.splitlines() == [
            "Tickets in view: 12",
            "Breached SLAs:   3",
            "Next SLA breach: in 2h14m",
        ]

    def test_multiple_rows_render_aligned_columns(self) -> None:
        text = build_results_text([["a", 1], ["bbb", 22000]], ["name", "count"])

        assert text is not None
        assert text.splitlines() == [
            "name  count",
            "----  ------",
            "a     1",
            "bbb   22,000",
        ]

    def test_backticks_in_values_cannot_break_out_of_a_fenced_block(self) -> None:
        text = build_results_text([["```\nrm -rf", 1]], ["subject", "count"])

        assert text is not None
        assert "`" not in text

    def test_short_row_does_not_shift_values_under_the_wrong_column(self) -> None:
        text = build_results_text([["a", 1], ["b"]], ["name", "count"])

        assert text is not None
        assert text.splitlines()[-1].split() == ["b", "-"]

    @parameterized.expand(
        [
            ("missing_query_results", {}),
            ("query_failed", {"query_results": None, "query_error": {"type": "cache_miss"}}),
        ]
    )
    def test_snapshot_without_results_renders_nothing(self, _name, snapshot) -> None:
        assert build_results_text_for_snapshot(snapshot) is None

    def test_snapshot_renders_its_query_results(self) -> None:
        snapshot = {"query_results": {"result": [[7]], "columns": ["Open tickets"]}}

        assert build_results_text_for_snapshot(snapshot) == "Open tickets: 7"
