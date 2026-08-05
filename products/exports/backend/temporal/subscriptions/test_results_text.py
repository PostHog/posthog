from parameterized import parameterized

from products.exports.backend.temporal.subscriptions.results_text import (
    MAX_COLUMNS,
    MAX_ROWS,
    MAX_TEXT_LENGTH,
    build_results_text,
    build_results_text_for_snapshot,
    query_renders_as_text,
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

    def test_server_capped_table_reports_the_hidden_count_as_a_floor(self) -> None:
        # A SQL insight with no LIMIT returns DEFAULT_RETURNED_ROWS and sets has_more, so the
        # returned length says nothing about the real total. "and 90 more rows" would be a
        # specific wrong number.
        text = build_results_text([[i] for i in range(100)], ["n"], has_more=True)

        assert text is not None
        assert text.splitlines()[-1] == "... and at least 90 more rows"

    @parameterized.expand(
        [
            # A rate under 0.005 rounds to "0.00" at two decimals and reads as no value at all.
            ("small_rate", 0.004, "0.004"),
            ("tiny_rate", 0.0000123, "1.23e-05"),
            ("ordinary_float", 12.345, "12.35"),
            ("whole_float", 3.0, "3"),
            ("large_float", 22000.5, "22,000.50"),
        ]
    )
    def test_float_values_keep_a_distinguishable_magnitude(self, _name, value, expected) -> None:
        assert build_results_text([[value]], ["rate"]) == f"rate: {expected}"

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

    @parameterized.expand(
        [
            ("backticks", "```\nrm -rf", "`"),
            # Slack resolves entity syntax before rendering markdown, so a raw `<!channel>` in
            # a property value would ping the channel from inside the fenced block.
            ("channel_mention", "<!channel>", "<"),
            ("user_mention", "<@U0123456789>", "<"),
            ("spoofed_link", "<https://evil.test|Open ticket>", "<"),
        ]
    )
    def test_mrkdwn_control_characters_in_values_are_neutralized(self, _name, value, forbidden) -> None:
        text = build_results_text([[value, 1]], ["subject", "count"])

        assert text is not None
        assert forbidden not in text

    def test_escaping_does_not_shift_the_columns_it_pads(self) -> None:
        # Slack renders each escaped entity back as one character, so widths have to be
        # measured before escaping or every row carrying `&`/`<`/`>` loses its alignment.
        text = build_results_text([["a&b", 1], ["cccc", 2]], ["name", "count"])

        assert text is not None
        assert text.splitlines() == [
            "name  count",
            "----  -----",
            "a&amp;b   1",
            "cccc  2",
        ]

    def test_short_row_does_not_shift_values_under_the_wrong_column(self) -> None:
        text = build_results_text([["a", 1], ["b"]], ["name", "count"])

        assert text is not None
        assert text.splitlines()[-1].split() == ["b", "-"]

    def test_oversized_text_is_cut_on_line_boundaries(self) -> None:
        # A character-level cut would leave a half-written value looking like a whole one.
        cell = "x" * 90
        text = build_results_text([[cell] * MAX_COLUMNS] * MAX_ROWS, [f"c{i}" for i in range(MAX_COLUMNS)])

        assert text is not None
        assert len(text) <= MAX_TEXT_LENGTH
        lines = text.splitlines()
        assert lines[-1] == "... (truncated)"
        assert all(line.endswith(cell) for line in lines[2:-1])

    def test_hidden_row_footer_survives_truncation(self) -> None:
        # The footer is the one line saying rows are missing, so the length cap must not be
        # able to eat it — a truncated table with no footer reads as the complete result.
        cell = "x" * 90
        rows = [[cell] * MAX_COLUMNS] * (MAX_ROWS + 5)
        text = build_results_text(rows, [f"c{i}" for i in range(MAX_COLUMNS)], has_more=True)

        assert text is not None
        assert len(text) <= MAX_TEXT_LENGTH
        lines = text.splitlines()
        assert lines[-1] == "... and at least 5 more rows"
        assert lines[-2] == "... (truncated)"

    @parameterized.expand(
        [
            # ClickHouse Decimal cells reach the snapshot serialized as strings; a money sum
            # must not render unformatted next to formatted float columns.
            ("decimal_money", "12345.6789", "12,345.68"),
            ("decimal_whole", "3.0", "3"),
            ("decimal_small_rate", "0.004", "0.004"),
            # Non-canonical or non-numeric strings are user data and pass through verbatim.
            ("version_string", "2.5.1", "2.5.1"),
            ("leading_zero", "02139.5", "02139.5"),
            ("phone_number", "5551234567", "5551234567"),
        ]
    )
    def test_decimal_strings_format_like_numbers_and_text_passes_through(self, _name, value, expected) -> None:
        assert build_results_text([[value]], ["v"]) == f"v: {expected}"

    @parameterized.expand(
        [
            ("missing_query_results", {}),
            ("query_failed", {"query_results": None, "query_error": {"type": "cache_miss"}}),
        ]
    )
    def test_snapshot_without_results_renders_nothing(self, _name, snapshot) -> None:
        assert build_results_text_for_snapshot(snapshot) is None

    def test_snapshot_renders_its_query_results(self) -> None:
        snapshot = {
            "results_text_eligible": True,
            "query_results": {"result": [[7]], "columns": ["Open tickets"]},
        }

        assert build_results_text_for_snapshot(snapshot) == "Open tickets: 7"

    def test_snapshot_without_the_eligibility_stamp_renders_nothing(self) -> None:
        # An EventsQuery result is also rows-as-lists, but its snapshot was served from cache
        # (only in-scope shapes calculate fresh), so rendering it would put numbers next to a
        # screenshot they can disagree with. The renderer fails closed on the stamp.
        snapshot = {"query_results": {"result": [[7]], "columns": ["Open tickets"]}}

        assert build_results_text_for_snapshot(snapshot) is None

    @parameterized.expand(
        [
            ("hogql", {"kind": "HogQLQuery", "query": "select 1"}, True),
            (
                "data_visualization_over_hogql",
                {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "select 1"}},
                True,
            ),
            # A chart query can never render as text, so it must not trigger the fresh
            # calculation that only exists to keep text and image agreeing.
            ("trends", {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": []}}, False),
            ("funnel", {"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery", "series": []}}, False),
            (
                "data_visualization_over_chart",
                {"kind": "DataVisualizationNode", "source": {"kind": "TrendsQuery"}},
                False,
            ),
            ("no_source", {"kind": "DataVisualizationNode"}, False),
            ("missing_query", None, False),
            ("not_a_dict", "select 1", False),
        ]
    )
    def test_query_shape_decides_whether_text_is_possible(self, _name, query_json, expected) -> None:
        assert query_renders_as_text(query_json) is expected

    def test_snapshot_passes_its_has_more_flag_through(self) -> None:
        snapshot = {
            "results_text_eligible": True,
            "query_results": {"result": [[i] for i in range(100)], "columns": ["n"], "has_more": True},
        }

        text = build_results_text_for_snapshot(snapshot)

        assert text is not None
        assert text.splitlines()[-1] == "... and at least 90 more rows"
