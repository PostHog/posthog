import datetime as dt

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.tests.test_keyset_pagination import DATE_FROM, DATE_TO, _b64, _TraceSpansTestBase

MS = 1_000_000  # ns per ms

# The query window is DATE_FROM..DATE_TO = 2026-06-02 07:00..09:00 (a 2h "current" period); the prior
# equal-length window is 05:00..07:00 ("previous"). "outside" spans sit on a different day and must be
# excluded from both.
_TS = {
    "current": dt.datetime(2026, 6, 2, 8, 0, 0),
    "previous": dt.datetime(2026, 6, 2, 6, 0, 0),
    "outside": dt.datetime(2026, 6, 1, 8, 0, 0),
}

# (file_path, line, generation, status_code, duration_ms, busy_ns | None, period)
#
# flag_matching.rs models match_flags [459, 826] with a closure [500, 520] nested inside it, plus
# evaluate_flags_in_level [900, 980]:
#   - match_flags has spans in both periods (current is busier + slower → positive pct_change),
#   - the closure is new this period (no previous spans → null pct_change),
#   - evaluate went quiet (previous only, zero current → -100%).
SPANS = [
    ("feature-flags/src/flags/flag_matching.rs", 459, "current", 0, 100, 50000, "current"),
    ("feature-flags/src/flags/flag_matching.rs", 459, "current", 0, 100, 50000, "current"),
    ("feature-flags/src/flags/flag_matching.rs", 459, "current", 0, 100, 50000, "current"),
    ("feature-flags/src/flags/flag_matching.rs", 459, "current", 2, 100, 50000, "current"),
    ("feature-flags/src/flags/flag_matching.rs", 470, "current", 0, 100, 50000, "current"),
    ("feature-flags/src/flags/flag_matching.rs", 470, "current", 0, 100, 50000, "current"),
    # Previous-window match_flags spans use the LEGACY attribute generation, so the prior period is
    # aggregated via code.lineno/code.filepath while the current period uses the stable keys — exercising
    # both generations across the two buckets of one symbol. One is an error (covers prev_error_count).
    ("feature-flags/src/flags/flag_matching.rs", 459, "legacy", 0, 50, 50000, "previous"),
    ("feature-flags/src/flags/flag_matching.rs", 459, "legacy", 0, 50, 50000, "previous"),
    ("feature-flags/src/flags/flag_matching.rs", 459, "legacy", 2, 50, 50000, "previous"),
    ("feature-flags/src/flags/flag_matching.rs", 510, "current", 0, 200, 80000, "current"),
    ("feature-flags/src/flags/flag_matching.rs", 510, "current", 0, 200, 80000, "current"),
    ("feature-flags/src/flags/flag_matching.rs", 510, "current", 0, 200, 80000, "current"),
    ("feature-flags/src/flags/flag_matching.rs", 510, "current", 0, 200, 80000, "current"),
    ("feature-flags/src/flags/flag_matching.rs", 900, "current", 0, 50, 20000, "previous"),
    ("feature-flags/src/flags/flag_matching.rs", 900, "current", 0, 50, 20000, "previous"),
    ("feature-flags/src/flags/flag_matching.rs", 900, "current", 0, 50, 20000, "previous"),
    ("feature-flags/src/flags/flag_matching.rs", 900, "current", 0, 50, 20000, "previous"),
    ("feature-flags/src/flags/flag_matching.rs", 900, "current", 0, 50, 20000, "previous"),
    # Legacy attribute generation, no busy_ns — fn [10, 50], current only.
    ("svc/src/legacy.rs", 10, "legacy", 0, 30, None, "current"),
    ("svc/src/legacy.rs", 10, "legacy", 0, 30, None, "current"),
    ("svc/src/legacy.rs", 20, "legacy", 2, 30, None, "current"),
    # Both generations on one function must merge — fn [1, 100], current.
    ("svc/src/mixed.rs", 5, "legacy", 0, 40, None, "current"),
    ("svc/src/mixed.rs", 5, "legacy", 0, 40, None, "current"),
    ("svc/src/mixed.rs", 6, "current", 0, 40, None, "current"),
    ("svc/src/mixed.rs", 6, "current", 0, 40, None, "current"),
    ("svc/src/mixed.rs", 6, "current", 0, 40, None, "current"),
    # Same basename, different directories — fn [10, 30] in each, current.
    ("crate-a/src/mod.rs", 15, "current", 0, 10, None, "current"),
    ("crate-a/src/mod.rs", 15, "current", 0, 10, None, "current"),
    ("crate-b/src/mod.rs", 15, "current", 0, 10, None, "current"),
    ("crate-b/src/mod.rs", 15, "current", 0, 10, None, "current"),
    ("crate-b/src/mod.rs", 15, "current", 0, 10, None, "current"),
    # fn [1, 50]: two spans in the current window, one in the previous, one outside both (must be dropped).
    ("window/src/file.rs", 5, "current", 0, 10, None, "current"),
    ("window/src/file.rs", 5, "current", 0, 10, None, "current"),
    ("window/src/file.rs", 6, "current", 0, 10, None, "previous"),
    ("window/src/file.rs", 7, "current", 0, 10, None, "outside"),
    # Period-over-period delta fixtures. Each "function" lives on a SINGLE line so the bucket and the five
    # *_pct_change values are identical in line mode (bucket = the line) and in symbol mode (a [L, L] range
    # anchored on L) — letting one parametrized test assert mode parity.
    #   line 10: traffic + errors in BOTH windows → real deltas (count/p50/p95/p99 +100, error_rate -50).
    ("pct/src/deltas.rs", 10, "current", 0, 100, None, "current"),
    ("pct/src/deltas.rs", 10, "current", 0, 100, None, "current"),
    ("pct/src/deltas.rs", 10, "current", 0, 100, None, "current"),
    ("pct/src/deltas.rs", 10, "current", 2, 100, None, "current"),  # 4 current, 1 error → rate 1/4
    ("pct/src/deltas.rs", 10, "current", 0, 50, None, "previous"),
    ("pct/src/deltas.rs", 10, "current", 2, 50, None, "previous"),  # 2 previous, 1 error → rate 1/2
    #   line 20: previous only → every metric (count, p50/p95/p99, error_rate) drops -100%.
    ("pct/src/deltas.rs", 20, "current", 2, 50, None, "previous"),
    ("pct/src/deltas.rs", 20, "current", 0, 50, None, "previous"),
    ("pct/src/deltas.rs", 20, "current", 0, 50, None, "previous"),  # 3 previous, 1 error → rate 1/3
    #   line 30: current only → no baseline for any metric → all five pct_change null.
    ("pct/src/deltas.rs", 30, "current", 0, 100, None, "current"),
    ("pct/src/deltas.rs", 30, "current", 0, 100, None, "current"),
    #   line 40: errors present previous, none current but traffic continues → error_rate -100.
    ("pct/src/deltas.rs", 40, "current", 2, 50, None, "previous"),
    ("pct/src/deltas.rs", 40, "current", 0, 50, None, "previous"),  # 2 previous, 1 error → rate 1/2
    ("pct/src/deltas.rs", 40, "current", 0, 100, None, "current"),
    ("pct/src/deltas.rs", 40, "current", 0, 100, None, "current"),
    ("pct/src/deltas.rs", 40, "current", 0, 100, None, "current"),  # 3 current, 0 errors → rate 0
    #   line 50: no errors previous, errors appear current → error_rate null (0→N spike, prev rate 0).
    ("pct/src/deltas.rs", 50, "current", 0, 50, None, "previous"),
    ("pct/src/deltas.rs", 50, "current", 0, 50, None, "previous"),  # 2 previous, 0 errors → rate 0
    ("pct/src/deltas.rs", 50, "current", 2, 100, None, "current"),
    ("pct/src/deltas.rs", 50, "current", 0, 100, None, "current"),
    ("pct/src/deltas.rs", 50, "current", 0, 100, None, "current"),  # 3 current, 1 error → rate 1/3
]

FM_SYMBOLS = [
    {"name": "match_flags", "startLine": 459, "endLine": 826},
    {"name": "closure", "startLine": 500, "endLine": 520},
    {"name": "evaluate_flags_in_level", "startLine": 900, "endLine": 980},
]

# Single-line ranges over the pct/src/deltas.rs fixture: each anchors on its own line, so symbol mode
# buckets exactly as line mode does.
DELTA_SYMBOLS = [
    {"name": "ten", "startLine": 10, "endLine": 10},
    {"name": "twenty", "startLine": 20, "endLine": 20},
    {"name": "thirty", "startLine": 30, "endLine": 30},
    {"name": "forty", "startLine": 40, "endLine": 40},
    {"name": "fifty", "startLine": 50, "endLine": 50},
]

# The five server-computed deltas every row carries, in both line and symbol mode.
PCT_CHANGE_FIELDS = [
    "count_pct_change",
    "p50_duration_pct_change",
    "p95_duration_pct_change",
    "p99_duration_pct_change",
    "error_rate_pct_change",
]


def _attr_map(path: str, line: int, generation: str, busy: int | None) -> str:
    if generation == "current":
        pairs = [("code.file.path__str", path), ("code.line.number__str", str(line))]
    else:
        pairs = [("code.filepath__str", path), ("code.lineno__str", str(line))]
    if busy is not None:
        pairs.append(("busy_ns__str", str(busy)))
    return "map(" + ", ".join(f"'{k}', '{v}'" for k, v in pairs) + ")"


class TestTraceSpansSymbolStats(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        rows: list[str] = []
        for i, (path, line, generation, status_code, duration_ms, busy, period) in enumerate(SPANS):
            base = _TS[period]
            end = base + dt.timedelta(milliseconds=duration_ms)
            trace_id = _b64(i.to_bytes(16, "big"))
            span_id = _b64((1000 + i).to_bytes(8, "big"))
            ts_str = base.strftime("%Y-%m-%d %H:%M:%S.%f")
            end_str = end.strftime("%Y-%m-%d %H:%M:%S.%f")
            rows.append(
                f"('019e8758-0000-0000-0000-{i:012d}', {cls.team.id}, '{trace_id}', '{span_id}', '', "
                f"'GET', 3, '{ts_str}', '{end_str}', '{ts_str}', {status_code}, 'svc', "
                f"{_attr_map(path, line, generation, busy)}, map())"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str, "
            "resource_attributes) VALUES " + ",".join(rows)
        )

    def _post(self, file_path: str, symbols: list[dict] | None = None) -> dict:
        query: dict = {"filePath": file_path, "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO}}
        if symbols is not None:
            query["symbols"] = symbols
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/symbol-stats/",
            {"query": query},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def _symbol_stats(self, file_path: str, symbols: list[dict]) -> list[dict]:
        return self._post(file_path, symbols)["results"]

    def test_buckets_into_smallest_enclosing_range(self):
        # Suffix match: request the repo-relative path; recorded path carries a `feature-flags/` prefix.
        rows = self._symbol_stats("src/flags/flag_matching.rs", FM_SYMBOLS)
        by_line = {r["line"]: r for r in rows}

        # match_flags gets its declaration-line (459 ×4) + in-body (470 ×2) spans, but NOT the closure's
        # spans — line 510 lands in the closure, the innermost enclosing range.
        self.assertEqual(by_line[459]["count"], 6)
        self.assertEqual(by_line[459]["error_count"], 1)
        self.assertEqual(by_line[459]["name"], "match_flags")
        self.assertEqual(by_line[500]["count"], 4)
        self.assertEqual(by_line[500]["name"], "closure")
        # evaluate is current-empty but surfaces because it had spans in the previous period.
        self.assertEqual(by_line[900]["count"], 0)
        self.assertEqual([r["line"] for r in rows], [459, 500, 900])

    def test_duration_and_busy_metrics(self):
        by_line = {r["line"]: r for r in self._symbol_stats("src/flags/flag_matching.rs", FM_SYMBOLS)}
        # match_flags current: 6 spans all 100ms, busy 50000.
        self.assertEqual(by_line[459]["p95_duration_nano"], 100 * MS)
        self.assertEqual(by_line[459]["sum_duration_nano"], 6 * 100 * MS)
        self.assertEqual(by_line[459]["busy_count"], 6)
        self.assertEqual(by_line[459]["p50_busy_nano"], 50000)
        # closure current: 4 spans all 200ms.
        self.assertEqual(by_line[500]["p50_duration_nano"], 200 * MS)

    def test_compares_against_previous_period(self):
        by_line = {r["line"]: r for r in self._symbol_stats("src/flags/flag_matching.rs", FM_SYMBOLS)}

        # match_flags: current 6 spans @100ms vs previous 3 spans @50ms (recorded via legacy keys) → +100%.
        # The previous block exercises every prev_* aggregate, incl. the negated-condition error/sum/busy.
        previous = by_line[459]["previous"]
        self.assertEqual(previous["count"], 3)
        self.assertEqual(previous["error_count"], 1)
        self.assertEqual(previous["sum_duration_nano"], 3 * 50 * MS)
        self.assertEqual(previous["p95_duration_nano"], 50 * MS)
        self.assertEqual(previous["busy_count"], 3)
        self.assertEqual(previous["p50_busy_nano"], 50000)
        self.assertEqual(by_line[459]["count_pct_change"], 100.0)
        self.assertEqual(by_line[459]["p95_duration_pct_change"], 100.0)

        # closure: new this period (no previous spans) → pct_change is null, not a fake +inf.
        self.assertEqual(by_line[500]["previous"]["count"], 0)
        self.assertIsNone(by_line[500]["count_pct_change"])
        self.assertIsNone(by_line[500]["p95_duration_pct_change"])

        # evaluate: went quiet (previous only) → surfaces with -100%.
        self.assertEqual(by_line[900]["previous"]["count"], 5)
        self.assertEqual(by_line[900]["count_pct_change"], -100.0)
        self.assertEqual(by_line[900]["p95_duration_pct_change"], -100.0)

    @parameterized.expand([("line_mode", None), ("symbol_mode", DELTA_SYMBOLS)])
    def test_all_five_pct_changes(self, _name, symbols):
        # Single-line buckets make every delta identical across granularities, so the same assertions hold
        # whether we bucket by line (no symbols) or by a [L, L] symbol range.
        by_line = {r["line"]: r for r in self._post("pct/src/deltas.rs", symbols)["results"]}
        self.assertEqual(sorted(by_line), [10, 20, 30, 40, 50])

        # Mode parity: line and symbol mode return the same five server-computed deltas on every row.
        for row in by_line.values():
            for field in PCT_CHANGE_FIELDS:
                self.assertIn(field, row)

        # line 10 — traffic in both windows: positive count/duration delta, real (negative) error-rate delta.
        # count 2→4 = +100; p50/p95/p99 50ms→100ms = +100; error_rate 1/2→1/4 = -50.
        ten = by_line[10]
        self.assertEqual(ten["count_pct_change"], 100.0)
        self.assertEqual(ten["p50_duration_pct_change"], 100.0)
        self.assertEqual(ten["p95_duration_pct_change"], 100.0)
        self.assertEqual(ten["p99_duration_pct_change"], 100.0)
        self.assertEqual(ten["error_rate_pct_change"], -50.0)

        # line 20 — previous only: every metric drops -100% (incl. error_rate, errors present previously).
        twenty = by_line[20]
        self.assertEqual(twenty["count_pct_change"], -100.0)
        self.assertEqual(twenty["p50_duration_pct_change"], -100.0)
        self.assertEqual(twenty["p95_duration_pct_change"], -100.0)
        self.assertEqual(twenty["p99_duration_pct_change"], -100.0)
        self.assertEqual(twenty["error_rate_pct_change"], -100.0)

        # line 30 — current only: no baseline → null for each of the five.
        for field in PCT_CHANGE_FIELDS:
            self.assertIsNone(by_line[30][field])

        # line 40 — errors vanish (present previous, none current though traffic continues) → error_rate -100.
        self.assertEqual(by_line[40]["error_rate_pct_change"], -100.0)

        # line 50 — new errors (none previous, appear current) → null, preserving 0→N-spike semantics.
        self.assertIsNone(by_line[50]["error_rate_pct_change"])

    def test_busy_absent_yields_zero_count_and_no_name(self):
        rows = self._symbol_stats("svc/src/legacy.rs", [{"startLine": 10, "endLine": 50}])
        by_line = {r["line"]: r for r in rows}
        # Legacy attribute generation still buckets (lines 10 and 20 fall in [10, 50]).
        self.assertEqual(by_line[10]["count"], 3)
        self.assertEqual(by_line[10]["error_count"], 1)
        # No busy_ns on these spans → busy family is not meaningful.
        self.assertEqual(by_line[10]["busy_count"], 0)
        self.assertEqual(by_line[10]["p50_busy_nano"], 0)
        # No name supplied, no prior-period spans.
        self.assertIsNone(by_line[10]["name"])
        self.assertEqual(by_line[10]["previous"]["count"], 0)
        self.assertIsNone(by_line[10]["count_pct_change"])

    def test_merges_both_attribute_generations(self):
        rows = self._symbol_stats("svc/src/mixed.rs", [{"startLine": 1, "endLine": 100}])
        self.assertEqual([(r["line"], r["count"]) for r in rows], [(1, 5)])

    @parameterized.expand([("crate-a/src/mod.rs", 2), ("crate-b/src/mod.rs", 3)])
    def test_same_basename_not_cross_attributed(self, file_path, expected_count):
        rows = self._symbol_stats(file_path, [{"startLine": 10, "endLine": 30}])
        self.assertEqual([(r["line"], r["count"]) for r in rows], [(10, expected_count)])

    # The recorded path is `feature-flags/src/flags/flag_matching.rs`. Many editor/repo conventions
    # produce a different spelling for the same source file — each must resolve to it and aggregate
    # byte-identical spans:
    #   - request is a segment-suffix of recorded (editor sends a shorter, repo-relative path, down to
    #     the bare basename),
    #   - recorded is a segment-suffix of request (a monorepo editor prepends one or more workspace
    #     segments the service never recorded — the bug this fixes),
    #   - and request paths that only differ after normalization (leading `./`, leading `/`, Windows
    #     separators).
    @parameterized.expand(
        [
            ("exact", "feature-flags/src/flags/flag_matching.rs"),
            ("suffix_drop_one_segment", "src/flags/flag_matching.rs"),
            ("suffix_drop_two_segments", "flags/flag_matching.rs"),
            ("suffix_basename_only", "flag_matching.rs"),
            ("monorepo_one_prefix", "rust/feature-flags/src/flags/flag_matching.rs"),
            ("monorepo_two_prefixes", "services/rust/feature-flags/src/flags/flag_matching.rs"),
            ("leading_dot_slash", "./feature-flags/src/flags/flag_matching.rs"),
            ("leading_slash", "/feature-flags/src/flags/flag_matching.rs"),
            ("windows_separators", "rust\\feature-flags\\src\\flags\\flag_matching.rs"),
        ]
    )
    def test_segment_suffix_match_across_path_conventions(self, _name, file_path):
        expected = self._symbol_stats("feature-flags/src/flags/flag_matching.rs", FM_SYMBOLS)
        self.assertEqual([r["line"] for r in expected], [459, 500, 900])  # baseline actually matched
        self.assertEqual(self._symbol_stats(file_path, FM_SYMBOLS), expected)

    # Paths that share only a partial segment or divergent leading segments must NOT match — the
    # leading '/' anchors the suffix test on a segment boundary.
    @parameterized.expand(
        [
            # Partial-segment overlap with `flag_matching.rs`: without the '/' anchor these would
            # spuriously match (e.g. `flag_matching.rs` endsWith `lag_matching.rs`).
            ("partial_basename_prefix", "lag_matching.rs", FM_SYMBOLS),
            ("partial_basename_infix", "_matching.rs", FM_SYMBOLS),
            ("divergent_middle_segment", "other/flag_matching.rs", FM_SYMBOLS),
            # Divergent leading segment: `crate-c` shares only the unsent `src/mod.rs` tail with the
            # recorded `crate-a`/`crate-b` files.
            ("divergent_leading_segment", "crate-c/src/mod.rs", [{"startLine": 10, "endLine": 30}]),
        ]
    )
    def test_non_segment_aligned_paths_do_not_match(self, _name, file_path, symbols):
        self.assertEqual(self._symbol_stats(file_path, symbols), [])

    def test_monorepo_match_identical_in_line_and_symbol_mode(self):
        # Matching happens in the WHERE before bucketing, so a workspace-prefixed request aggregates
        # the same spans as the exact path in BOTH line mode (no symbols) and symbol mode.
        prefixed = "rust/feature-flags/src/flags/flag_matching.rs"
        exact = "feature-flags/src/flags/flag_matching.rs"

        line_exact = self._post(exact)["results"]
        self.assertNotEqual(line_exact, [])
        self.assertEqual(self._post(prefixed)["results"], line_exact)

        symbol_exact = self._symbol_stats(exact, FM_SYMBOLS)
        self.assertNotEqual(symbol_exact, [])
        self.assertEqual(self._symbol_stats(prefixed, FM_SYMBOLS), symbol_exact)

    def test_each_period_window_is_respected(self):
        rows = self._symbol_stats("window/src/file.rs", [{"startLine": 1, "endLine": 50}])
        by_line = {r["line"]: r for r in rows}
        # Two spans in the current window, one in the previous, one outside both. The outside span would
        # push current to 3 (or previous to 2) if it leaked, so the exact counts prove it was excluded.
        self.assertEqual(by_line[1]["count"], 2)
        self.assertEqual(by_line[1]["previous"]["count"], 1)
        self.assertEqual(by_line[1]["p95_duration_nano"], 10 * MS)
        self.assertEqual(by_line[1]["count_pct_change"], 100.0)

    def test_symbol_enclosing_no_spans_returns_empty(self):
        self.assertEqual(self._symbol_stats("src/flags/flag_matching.rs", [{"startLine": 1, "endLine": 5}]), [])

    def test_untraced_file_returns_empty(self):
        self.assertEqual(self._symbol_stats("does/not/exist.rs", [{"startLine": 1, "endLine": 100}]), [])

    def test_omitting_symbols_aggregates_per_line(self):
        # No symbols → one row per actual source line; lines are NOT collapsed into ranges.
        payload = self._post("src/flags/flag_matching.rs")
        self.assertEqual(payload["granularity"], "line")
        by_line = {r["line"]: r for r in payload["results"]}
        # 459, 470, 510 stay distinct (in symbol mode 470 folds into match_flags and 510 into the closure).
        self.assertEqual(sorted(by_line), [459, 470, 510, 900])
        self.assertEqual(by_line[459]["count"], 4)
        self.assertEqual(by_line[459]["previous"]["count"], 3)
        self.assertEqual(by_line[470]["count"], 2)
        self.assertEqual(by_line[510]["count"], 4)
        self.assertEqual(by_line[900]["count"], 0)
        self.assertEqual(by_line[900]["previous"]["count"], 5)
        # Line mode echoes no symbol identity.
        self.assertIsNone(by_line[459]["name"])
        self.assertIsNone(by_line[459]["end_line"])

    def test_single_whole_file_range_gives_file_total(self):
        payload = self._post("src/flags/flag_matching.rs", [{"name": "whole", "startLine": 1, "endLine": 100000}])
        self.assertEqual(payload["granularity"], "symbol")
        self.assertEqual(len(payload["results"]), 1)
        row = payload["results"][0]
        self.assertEqual(row["line"], 1)
        self.assertEqual(row["name"], "whole")
        self.assertEqual(row["end_line"], 100000)
        # Every current span in the file (459×4 + 470×2 + 510×4) folds into one bucket; previous = 459×3 + 900×5.
        self.assertEqual(row["count"], 10)
        self.assertEqual(row["previous"]["count"], 8)

    def test_symbol_mode_reports_symbol_granularity(self):
        self.assertEqual(self._post("src/flags/flag_matching.rs", FM_SYMBOLS)["granularity"], "symbol")

    def test_missing_file_path_returns_400(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/symbol-stats/",
            {"query": {"symbols": FM_SYMBOLS, "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO}}},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    @parameterized.expand(
        [
            ("inverted_range", [{"startLine": 50, "endLine": 10}]),
            ("zero_start_line", [{"startLine": 0, "endLine": 5}]),
            ("duplicate_start_line", [{"startLine": 10, "endLine": 20}, {"startLine": 10, "endLine": 30}]),
            ("too_many_symbols", [{"startLine": i, "endLine": i} for i in range(1, 1002)]),
        ]
    )
    def test_invalid_symbols_return_400(self, _name, symbols):
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/symbol-stats/",
            {
                "query": {
                    "filePath": "src/flags/flag_matching.rs",
                    "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                    "symbols": symbols,
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
