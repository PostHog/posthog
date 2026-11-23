import json
import datetime as dt

from unittest import TestCase

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.self_time import annotate_self_time
from products.tracing.backend.tests.test_keyset_pagination import _b64, _TraceSpansTestBase
from products.tracing.backend.trace_summary import MAX_NAME_CHARS, summarize_trace

BASE = dt.datetime(2026, 6, 2, 8, 0, 0, tzinfo=dt.UTC)
MS = 1_000_000

LONG_NAME = "SELECT " + "column_name, " * 30 + "FROM events"

# A request that does auth, an N+1 loop of five queries, then two parallel calls (a fast cache read
# and a slow downstream call whose ClickHouse query fails), then serializes the response. Root
# self-time is the 50ms not covered by any child.
#   (span_id, parent_id, name, service, start_ms, duration_ms, status_code)
FIXTURE = [
    ("root", "", "GET /insights", "web", 0, 1000, 0),
    ("auth", "root", "auth", "web", 0, 20, 0),
    *[(f"db{i}", "root", "SELECT person", "web", 20 + 20 * i, 20, 0) for i in range(5)],
    ("cache", "root", "cache.get", "web", 120, 80, 0),
    ("call", "root", "http.call", "web", 120, 780, 2),
    ("ch", "call", "clickhouse.query", "query", 130, 760, 2),
    ("serialize", "root", LONG_NAME, "web", 900, 50, 0),
]


def _spans(fixture: list[tuple]) -> list[dict]:
    spans = []
    for span_id, parent, name, service, start_ms, duration_ms, status_code in fixture:
        start = BASE + dt.timedelta(milliseconds=start_ms)
        spans.append(
            {
                "trace_id": "abc123",
                "span_id": span_id,
                "parent_span_id": parent,
                "name": name,
                "service_name": service,
                "status_code": status_code,
                "timestamp": start,
                "end_time": start + dt.timedelta(milliseconds=duration_ms),
                "duration_nano": round(duration_ms * MS),
                "is_root_span": parent == "",
                "attributes": {},
                "events": [],
            }
        )
    annotate_self_time(spans)
    return spans


def _fixture_spans() -> list[dict]:
    spans = _spans(FIXTURE)
    by_id = {span["span_id"]: span for span in spans}
    by_id["ch"]["events"] = [{"name": "exception", "attributes": {"exception.message": "Code: 241. Memory limit"}}]
    by_id["call"]["attributes"] = {"http.response.status_code": "500"}
    return spans


class TestTraceSummary(TestCase):
    def setUp(self):
        self.summary = summarize_trace(_fixture_spans())

    def test_headline_counts(self):
        s = self.summary
        self.assertEqual(
            (s["trace_id"], s["duration_ms"], s["span_count"], s["service_count"], s["error_count"], s["truncated"]),
            ("abc123", 1000.0, 11, 2, 2, False),
        )
        self.assertEqual(s["services"], {"web": 10, "query": 1})
        self.assertEqual(
            s["root"],
            {"span_id": "root", "name": "GET /insights", "service": "web", "duration_ms": 1000.0, "self_ms": 50.0},
        )

    def test_top_self_time_puts_the_slow_leaf_first(self):
        top = [(entry["span_id"], entry["self_ms"]) for entry in self.summary["top_self_time"][:4]]
        self.assertEqual(top, [("ch", 760.0), ("cache", 80.0), ("root", 50.0), ("serialize", 50.0)])
        call = next(e for e in self.summary["errors"] if e["span_id"] == "call")
        self.assertEqual((call["duration_ms"], call["self_ms"], call["error"]), (780.0, 20.0, True))

    def test_critical_path_skips_the_parallel_child_and_collapses_the_loop(self):
        path = [(e["depth"], e["name"], e.get("count"), e["duration_ms"]) for e in self.summary["critical_path"]]
        self.assertEqual(
            path,
            [
                (0, "GET /insights", None, 1000.0),
                (1, "auth", None, 20.0),
                (1, "SELECT person", 5, 100.0),
                (1, "http.call", None, 780.0),
                (2, "clickhouse.query", None, 760.0),
                (1, LONG_NAME[: MAX_NAME_CHARS - 1] + "…", None, 50.0),
            ],
        )
        self.assertFalse(self.summary["critical_path_truncated"])

    def test_critical_path_drops_negligible_spans(self):
        tiny = [(f"t{i}", "root", "cache.get", "web", i, 1, 0) for i in range(0, 10, 2)]
        slow = ("slow", "root", "clickhouse.query", "query", 10, 990, 0)
        summary = summarize_trace(_spans([("root", "", "GET /insights", "web", 0, 1000, 0), *tiny, slow]))
        path = [(e["name"], e.get("service")) for e in summary["critical_path"]]
        self.assertEqual(path, [("GET /insights", None), ("clickhouse.query", "query")])
        self.assertEqual(summary["critical_path_omitted"], 5)

    def test_critical_path_skips_a_sibling_that_overlaps_the_one_after_it(self):
        overlapping = [("a", "root", "a", "web", 0, 800, 0), ("b", "root", "b", "web", 400, 500, 0)]
        summary = summarize_trace(_spans([("root", "", "GET /insights", "web", 0, 900, 0), *overlapping]))
        self.assertEqual([e["name"] for e in summary["critical_path"]], ["GET /insights", "b"])

    def test_critical_path_keeps_a_run_of_sub_rounding_spans(self):
        loop = [(f"q{i}", "root", "SELECT person", "web", 0.04 * i, 0.04, 0) for i in range(100)]
        summary = summarize_trace(_spans([("root", "", "GET /insights", "web", 0, 10, 0), *loop]))
        run = summary["critical_path"][1]
        self.assertEqual((run["name"], run["count"], run["duration_ms"]), ("SELECT person", 100, 4.0))
        self.assertEqual(summary["critical_path_omitted"], 0)

    def test_repeated_spans_surface_the_n_plus_one(self):
        self.assertEqual(
            self.summary["repeated_spans"],
            [{"name": "SELECT person", "count": 5, "total_ms": 100.0, "max_ms": 20.0}],
        )

    def test_errors_carry_their_message(self):
        messages = [(e["span_id"], e["message"]) for e in self.summary["errors"]]
        self.assertEqual(messages, [("call", "http.response.status_code=500"), ("ch", "Code: 241. Memory limit")])

    def test_long_names_are_truncated(self):
        serialize = next(e for e in self.summary["top_self_time"] if e["span_id"] == "serialize")
        self.assertEqual(len(serialize["name"]), MAX_NAME_CHARS)

    def test_long_service_names_are_truncated_everywhere(self):
        spans = _spans(
            [("root", "", "GET /insights", "web", 0, 100, 0)]
            + [(f"q{i}", "root", "query", "s" * 5000, 10 * i, 10, 2) for i in range(2)]
        )
        summary = summarize_trace(spans)
        self.assertLess(len(json.dumps(summary)), 3000)

    def test_limit_caps_every_list(self):
        summary = summarize_trace(_fixture_spans(), limit=1)
        self.assertEqual(
            [len(summary[key]) for key in ("top_self_time", "repeated_spans", "errors", "critical_path")],
            [1, 1, 1, 1],
        )
        self.assertTrue(summary["critical_path_truncated"])

    def test_summary_is_compact(self):
        loop = [(f"q{i}", "root", "SELECT person", "web", 10 * i, 10, 0) for i in range(100)]
        summary = summarize_trace(_spans([("root", "", "GET /insights", "web", 0, 1000, 0), *loop]))
        self.assertEqual(summary["critical_path"][1]["count"], 100)
        self.assertLess(len(json.dumps(summary)), 2500)

    def test_missing_root_falls_back_to_the_longest_orphan(self):
        spans = [span for span in _fixture_spans() if span["span_id"] != "root"]
        summary = summarize_trace(spans, truncated=True)
        self.assertEqual((summary["root"]["span_id"], summary["truncated"]), ("call", True))

    def test_cyclic_parent_links_still_summarize(self):
        spans = _spans([("a", "b", "a", "web", 0, 100, 0), ("b", "a", "b", "web", 10, 50, 0)])
        summary = summarize_trace(spans)
        self.assertEqual(summary["root"]["span_id"], "a")
        self.assertEqual([e["name"] for e in summary["critical_path"]], ["a", "b"])

    def test_empty_trace(self):
        self.assertEqual(summarize_trace([]), {"span_count": 0, "truncated": False})


class TestTraceSummaryEndpoint(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()
        trace_id = _b64((1).to_bytes(16, "big"))
        rows: list[str] = []
        ids = {span[0]: _b64((index + 1).to_bytes(8, "big")) for index, span in enumerate(FIXTURE)}
        for n, (span_id, parent, name, service, start_ms, duration_ms, status_code) in enumerate(FIXTURE):
            start = BASE.replace(tzinfo=None) + dt.timedelta(milliseconds=start_ms)
            end = start + dt.timedelta(milliseconds=duration_ms)
            event = (
                json.dumps({"name": "exception", "attributes": {"exception.message": json.dumps("Memory limit")}})
                if span_id == "ch"
                else None
            )
            rows.append(
                f"('019e8759-0000-0000-0001-{n:012d}', {cls.team.id}, '{trace_id}', "
                f"'{ids[span_id]}', '{ids.get(parent, '')}', '{name}', 2, "
                f"'{start.strftime('%Y-%m-%d %H:%M:%S.%f')}', '{end.strftime('%Y-%m-%d %H:%M:%S.%f')}', "
                f"'{start.strftime('%Y-%m-%d %H:%M:%S.%f')}', {status_code}, '{service}', "
                f"[{repr(event) if event else ''}])"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, events) VALUES " + ",".join(rows)
        )

    def _fetch(self, body: dict) -> dict:
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/trace/{(1).to_bytes(16, 'big').hex()}/",
            {"dateRange": {"date_from": "2026-06-02T07:00:00Z", "date_to": "2026-06-02T09:00:00Z"}, **body},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_summary_replaces_the_span_list(self):
        data = self._fetch({"summary": True})
        summary = data["summary"]
        self.assertEqual(data["results"], [])
        self.assertEqual((summary["span_count"], summary["error_count"], summary["truncated"]), (11, 2, False))
        self.assertEqual(summary["root"]["name"], "GET /insights")
        self.assertEqual(summary["top_self_time"][0]["name"], "clickhouse.query")
        self.assertIn(
            {"name": "SELECT person", "count": 5, "total_ms": 100.0, "max_ms": 20.0},
            summary["repeated_spans"],
        )
        self.assertEqual([e["message"] for e in summary["errors"]], [None, "Memory limit"])

    def test_summary_keeps_events_even_when_attributes_are_excluded(self):
        summary = self._fetch({"summary": True, "excludeAttributes": True, "offset": 5})["summary"]
        self.assertEqual((summary["span_count"], summary["errors"][-1]["message"]), (11, "Memory limit"))

    def test_without_summary_the_span_list_is_unchanged(self):
        data = self._fetch({})
        self.assertNotIn("summary", data)
        self.assertEqual(len(data["results"]), 11)

    def test_summary_limit_is_validated(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/trace/{(1).to_bytes(16, 'big').hex()}/",
            {"summary": True, "summaryLimit": 0},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
