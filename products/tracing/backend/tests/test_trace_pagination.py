import datetime as dt

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.presentation.views import TRACE_SPANS_PAGE_SIZE
from products.tracing.backend.tests.test_keyset_pagination import _b64, _TraceSpansTestBase

BASE = dt.datetime(2026, 6, 2, 8, 0, 0)
SPAN_COUNT = TRACE_SPANS_PAGE_SIZE + 3  # spills past one page so paging actually kicks in


class TestTracePagination(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        trace_id = _b64((1).to_bytes(16, "big"))
        rows: list[str] = []
        # span_no 1 is the root; the rest are children. Start time strictly increases with span_no so
        # "first N by start time" is span_no 1..N — a deterministic ordering to assert against.
        for span_no in range(1, SPAN_COUNT + 1):
            span_id = _b64((100 + span_no).to_bytes(8, "big"))
            parent = "" if span_no == 1 else _b64((101).to_bytes(8, "big"))
            start = BASE + dt.timedelta(milliseconds=span_no)
            end = start + dt.timedelta(milliseconds=1)
            rows.append(
                f"('019e8759-0000-0000-0001-{span_no:012d}', {cls.team.id}, '{trace_id}', "
                f"'{span_id}', '{parent}', 'op-{span_no}', 2, "
                f"'{start.strftime('%Y-%m-%d %H:%M:%S.%f')}', '{end.strftime('%Y-%m-%d %H:%M:%S.%f')}', "
                f"'{start.strftime('%Y-%m-%d %H:%M:%S.%f')}', 0, 'web')"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    def _fetch_page(self, offset: int = 0) -> dict:
        trace_hex = (1).to_bytes(16, "big").hex()
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/trace/{trace_hex}/",
            {
                "dateRange": {"date_from": "2026-06-02T07:00:00Z", "date_to": "2026-06-02T09:00:00Z"},
                "offset": offset,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_first_page_is_the_earliest_spans_by_start_time(self):
        page = self._fetch_page()
        names = [span["name"] for span in page["results"]]
        self.assertEqual(len(names), TRACE_SPANS_PAGE_SIZE)
        # The first page is exactly the earliest-starting spans (span_no 1..PAGE_SIZE), in order.
        self.assertEqual(set(names), {f"op-{n}" for n in range(1, TRACE_SPANS_PAGE_SIZE + 1)})
        self.assertTrue(page["hasMore"])
        self.assertEqual(page["nextOffset"], TRACE_SPANS_PAGE_SIZE)

    def test_second_page_returns_the_remainder_and_ends(self):
        page = self._fetch_page(offset=TRACE_SPANS_PAGE_SIZE)
        names = {span["name"] for span in page["results"]}
        self.assertEqual(names, {f"op-{n}" for n in range(TRACE_SPANS_PAGE_SIZE + 1, SPAN_COUNT + 1)})
        self.assertFalse(page["hasMore"])
        self.assertIsNone(page["nextOffset"])

    def test_pages_do_not_overlap(self):
        first = {span["span_id"] for span in self._fetch_page()["results"]}
        second = {span["span_id"] for span in self._fetch_page(offset=TRACE_SPANS_PAGE_SIZE)["results"]}
        self.assertEqual(first & second, set())
        self.assertEqual(len(first | second), SPAN_COUNT)
