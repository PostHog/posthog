import base64
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"

ROOT_SVC = "web"
CHILD_SVC = "flags"
ROOT_NAME = "GET /api"
CHILD_NAME = "match_flags"
FILEPATH = "feature-flags/src/flags/flag_matching.rs"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class TestFlatSpanQuery(ClickhouseTestMixin, APIBaseTest):
    """flatSpans=True returns the matching spans themselves, one row per span. code.filepath lives on a
    non-root (child) span, so the default Traces view (root-filtered) shows nothing; flat mode surfaces
    the child directly, without the whole-trace GROUP BY that OOMs on hot child attributes at volume.
    """

    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        tag_queries(product="tracing", feature="query")
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(
            "ALTER TABLE trace_spans ADD COLUMN IF NOT EXISTS "
            "is_root_span Bool MATERIALIZED (replaceAll(trimRight(parent_span_id, '='), 'A', '')) = ''"
        )
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

        # Three traces 10s apart. Each: a root ("web", no code.filepath) + one child ("flags", carries
        # code.filepath). Child end_time grows with i so duration ordering is distinguishable.
        base = dt.datetime(2026, 6, 2, 8, 0, 0)
        rows = []
        for i in range(1, 4):
            trace = _b64(i.to_bytes(16, "big"))
            root_id = _b64((i * 10 + 1).to_bytes(8, "big"))
            child_id = _b64((i * 10 + 2).to_bytes(8, "big"))
            ts = (base + dt.timedelta(seconds=i * 10)).strftime("%Y-%m-%d %H:%M:%S.%f")
            root_end = (base + dt.timedelta(seconds=i * 10, milliseconds=2)).strftime("%Y-%m-%d %H:%M:%S.%f")
            child_end = (base + dt.timedelta(seconds=i * 10, milliseconds=5 + i)).strftime("%Y-%m-%d %H:%M:%S.%f")
            rows.append(
                f"('019e8754-0000-0000-0000-{2 * i - 1:012d}', {cls.team.id}, '{trace}', '{root_id}', '', "
                f"'{ROOT_NAME}', 2, '{ts}', '{root_end}', '{ts}', 0, '{ROOT_SVC}', map(), map())"
            )
            rows.append(
                f"('019e8754-0000-0000-0000-{2 * i:012d}', {cls.team.id}, '{trace}', '{child_id}', '{root_id}', "
                f"'{CHILD_NAME}', 2, '{ts}', '{child_end}', '{ts}', 0, '{CHILD_SVC}', "
                f"map('code.filepath__str', '{FILEPATH}'), map())"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str, "
            "resource_attributes) VALUES " + ",".join(rows)
        )

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    def _query(self, **overrides) -> dict:
        body = {
            "query": {
                "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                **overrides,
            }
        }
        res = self.client.post(f"/api/projects/{self.team.id}/tracing/spans/query/", body, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    _CODE_FILTER = {"key": "code.filepath", "type": "span_attribute", "operator": "exact", "value": FILEPATH}

    @parameterized.expand(
        [
            # A child-only attribute filter (code.filepath) and the child service filter both select
            # exactly the three child spans directly — one row per span, no roots.
            ("attribute_filter", {"filterGroup": [_CODE_FILTER]}),
            ("service_name_filter", {"serviceNames": [CHILD_SVC]}),
        ]
    )
    def test_flat_respects_filters(self, _name, filter_kwargs):
        data = self._query(flatSpans=True, limit=100, **filter_kwargs)
        results = data["results"]
        self.assertEqual(len(results), 3)
        self.assertEqual({r["name"] for r in results}, {CHILD_NAME})
        self.assertTrue(all(r["is_root_span"] is False for r in results))
        self.assertTrue(all(r["service_name"] == CHILD_SVC for r in results))
        # Every returned row matched the filter.
        self.assertTrue(all(r["matched_filter"] for r in results))

    def test_default_traces_view_hides_child_only_match(self):
        # The bug this fixes: with the default (Traces) view, a child-only attribute filter matches no
        # root, so the table is empty even though the spans exist. flatSpans is the escape hatch.
        data = self._query(filterGroup=[self._CODE_FILTER], limit=100)
        self.assertEqual(data["results"], [])

    def test_flat_without_attribute_filter_returns_all_spans(self):
        data = self._query(flatSpans=True, limit=100)
        results = data["results"]
        self.assertEqual(len(results), 6)
        names = [r["name"] for r in results]
        self.assertEqual(names.count(ROOT_NAME), 3)
        self.assertEqual(names.count(CHILD_NAME), 3)

    @parameterized.expand(
        [
            # timestamp order paginates via the `after` keyset cursor; duration order via `offset`.
            ("timestamp_keyset", "timestamp"),
            ("duration_offset", "duration"),
        ]
    )
    def test_flat_pagination_walks_every_span_once(self, _name, order_by):
        seen_uuids: list[str] = []
        cursor: str | None = None
        offset = 0
        for _ in range(10):  # generous upper bound; 6 spans at limit 2 = 3 pages
            paging = {"after": cursor} if cursor else {"offset": offset}
            page = self._query(flatSpans=True, orderBy=order_by, orderDirection="DESC", limit=2, **paging)
            results = page["results"]
            self.assertLessEqual(len(results), 2)
            seen_uuids.extend(r["uuid"] for r in results)
            if not page["hasMore"]:
                break
            if order_by == "duration":
                offset += 2
            else:
                cursor = page["nextCursor"]
                self.assertIsNotNone(cursor)
        # Every span seen exactly once, no duplicates or drops across the pages.
        self.assertEqual(len(seen_uuids), 6)
        self.assertEqual(len(set(seen_uuids)), 6)
