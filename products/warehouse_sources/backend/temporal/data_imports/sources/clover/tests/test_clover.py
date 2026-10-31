import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from unittest import mock

from django.test import SimpleTestCase

from parameterized import parameterized
from requests import PreparedRequest, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.clover.clover import (
    CloverResumeConfig,
    clover_source,
    endpoint_permissions,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clover.settings import (
    ENDPOINTS,
    FILTER_WINDOW_MS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

MERCHANT_ID = "6MRDFDQMRSSTZ"
NOW_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.clover.clover._now_ms"


def response(rows: list[dict[str, Any]], status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result._content = json.dumps({"elements": rows}).encode()
    result.headers["Content-Type"] = "application/json"
    return result


@contextmanager
def http_responses(responses: list[Response]) -> Iterator[list[PreparedRequest]]:
    requests: list[PreparedRequest] = []
    pending = iter(responses)

    def send(session: Any, request: PreparedRequest, **kwargs: Any) -> Response:
        requests.append(request)
        result = next(pending)
        result.url = request.url or ""
        result.request = request
        return result

    with mock.patch("requests.sessions.Session.send", autospec=True, side_effect=send):
        yield requests


def manager(state: dict[str, Any] | None = None) -> mock.MagicMock:
    result = mock.MagicMock()
    result.can_resume.return_value = state is not None
    result.load_state.return_value = CloverResumeConfig(paginator_state=state) if state is not None else None
    return result


def source(endpoint: str, resume_manager: mock.MagicMock, **kwargs: Any) -> SourceResponse:
    return clover_source(
        region="na",
        merchant_id=MERCHANT_ID,
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=resume_manager,
        auth=BearerTokenAuth("test-token"),
        api_version="v3",
        **kwargs,
    )


def rows(result: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast(Iterator[list[dict[str, Any]]], result.items()) for row in page]


def params(request: PreparedRequest) -> dict[str, list[str]]:
    return parse_qs(urlsplit(request.url or "").query)


class TestCloverTransport(SimpleTestCase):
    @parameterized.expand(ENDPOINTS)
    @mock.patch(NOW_PATCH, return_value=1000)
    def test_each_table_reads_the_collection_and_preserves_fields(self, endpoint: str, now: mock.MagicMock) -> None:
        record = {"id": "row1", "createdTime": 1, "customerSince": 1, "name": "example"}
        pages = (
            [response([{"id": "order1", "createdTime": 1}]), response([record])]
            if endpoint == "line_items"
            else [response([record])]
        )
        with http_responses(pages) as requests:
            result = source(endpoint, manager())
            imported = rows(result)
        self.assertEqual(imported[0]["name"], "example")
        self.assertEqual(imported[0]["id"], "row1")
        self.assertEqual(result.name, endpoint)
        self.assertTrue(all(request.headers["Authorization"] == "Bearer test-token" for request in requests))
        expected_path = (
            f"/v3/merchants/{MERCHANT_ID}/orders/order1/line_items"
            if endpoint == "line_items"
            else f"/v3/merchants/{MERCHANT_ID}/{endpoint}"
        )
        self.assertEqual(urlsplit(requests[-1].url or "").path, expected_path)
        self.assertEqual(params(requests[-1])["limit"], [str(PAGE_SIZE)])
        if result.partition_mode == "datetime":
            self.assertEqual(imported[0]["created_at"], datetime.fromtimestamp(0.001, tz=UTC))
            self.assertEqual(result.partition_keys, ["created_at"])
        if endpoint == "line_items":
            self.assertEqual(imported[0]["order_id"], "order1")
            self.assertEqual(result.primary_keys, ["order_id", "id"])
        else:
            self.assertEqual(result.primary_keys, ["id"])

    def test_full_refresh_paginates_and_checkpoints_after_yield(self) -> None:
        first = [{"id": str(i)} for i in range(PAGE_SIZE)]
        resume_manager = manager()
        with http_responses([response(first), response([{"id": "last"}])]) as requests:
            iterator = iter(cast(Iterator[list[dict[str, Any]]], source("items", resume_manager).items()))
            self.assertEqual(len(next(iterator)), PAGE_SIZE)
            resume_manager.save_state.assert_not_called()
            self.assertEqual(next(iterator), [{"id": "last"}])
            state = resume_manager.save_state.call_args.args[0].paginator_state
            self.assertEqual(state["resource_state"], {"offset": PAGE_SIZE})
            self.assertEqual(list(iterator), [])
        self.assertEqual([params(request)["offset"] for request in requests], [["0"], [str(PAGE_SIZE)]])
        self.assertNotIn("filter", params(requests[0]))
        self.assertTrue(resume_manager.save_state.call_args.args[0].paginator_state["completed"])

    @parameterized.expand([(0,), (PAGE_SIZE,), (3000,)])
    def test_resumes_saved_offset(self, offset: int) -> None:
        with http_responses([response([{"id": "next"}])]) as requests:
            imported = rows(source("items", manager({"resource_state": {"offset": offset}})))
        self.assertEqual(imported, [{"id": "next"}])
        self.assertEqual(params(requests[0])["offset"], [str(offset)])

    @mock.patch(NOW_PATCH, return_value=FILTER_WINDOW_MS * 2 + 1)
    def test_backfill_windows_cover_history_without_overlapping(self, now: mock.MagicMock) -> None:
        records = [{"id": str(i), "createdTime": i * FILTER_WINDOW_MS} for i in range(3)]
        with http_responses([response([record]) for record in records]) as requests:
            imported = rows(source("payments", manager()))
        self.assertEqual([row["id"] for row in imported], ["0", "1", "2"])
        self.assertEqual(
            [params(request)["filter"] for request in requests],
            [
                ["createdTime>=0", f"createdTime<={FILTER_WINDOW_MS - 1}"],
                [f"createdTime>={FILTER_WINDOW_MS}", f"createdTime<={FILTER_WINDOW_MS * 2 - 1}"],
                [f"createdTime>={FILTER_WINDOW_MS * 2}", f"createdTime<={FILTER_WINDOW_MS * 2 + 1}"],
            ],
        )
        self.assertTrue(all(params(request)["offset"] == ["0"] for request in requests))

    @mock.patch(NOW_PATCH, return_value=FILTER_WINDOW_MS * 2)
    def test_resume_keeps_the_original_history_end(self, now: mock.MagicMock) -> None:
        state = {
            "window_start_ms": FILTER_WINDOW_MS,
            "end_ms": FILTER_WINDOW_MS + 10,
            "resource_state": {"offset": PAGE_SIZE},
        }
        with http_responses([response([{"id": "next", "createdTime": FILTER_WINDOW_MS}])]) as requests:
            rows(source("refunds", manager(state)))
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            params(requests[0])["filter"], [f"createdTime>={FILTER_WINDOW_MS}", f"createdTime<={FILTER_WINDOW_MS + 10}"]
        )
        self.assertEqual(params(requests[0])["offset"], [str(PAGE_SIZE)])

    @mock.patch(NOW_PATCH, return_value=1000)
    def test_line_items_page_children_instead_of_expanding_truncated_collections(self, now: mock.MagicMock) -> None:
        first = [{"id": str(i)} for i in range(PAGE_SIZE)]
        parents = [{"id": "order1", "createdTime": 10}, {"id": "order2", "createdTime": 20}]
        with http_responses(
            [response(parents), response(first), response([{"id": "last"}]), response([{"id": "last"}])]
        ) as requests:
            imported = rows(source("line_items", manager()))
        self.assertEqual(len(imported), PAGE_SIZE + 2)
        self.assertEqual([row["order_id"] for row in imported[-2:]], ["order1", "order2"])
        self.assertEqual([params(request)["offset"] for request in requests], [["0"], ["0"], [str(PAGE_SIZE)], ["0"]])
        self.assertTrue(all("expand" not in params(request) for request in requests))

    @mock.patch(NOW_PATCH, return_value=1000)
    def test_fanout_resume_skips_completed_orders_and_resumes_the_child(self, now: mock.MagicMock) -> None:
        path1 = f"/v3/merchants/{MERCHANT_ID}/orders/order1/line_items"
        path2 = f"/v3/merchants/{MERCHANT_ID}/orders/order2/line_items"
        state = {
            "window_start_ms": 0,
            "end_ms": 1000,
            "resource_state": {"completed": [path1], "current": path2, "child_state": {"offset": PAGE_SIZE}},
        }
        parents = [{"id": "order1", "createdTime": 10}, {"id": "order2", "createdTime": 20}]
        with http_responses([response(parents), response([{"id": "last"}])]) as requests:
            imported = rows(source("line_items", manager(state)))
        self.assertEqual(len(requests), 2)
        self.assertEqual(urlsplit(requests[-1].url or "").path, path2)
        self.assertEqual(params(requests[-1])["offset"], [str(PAGE_SIZE)])
        self.assertEqual(imported[0]["order_id"], "order2")

    @parameterized.expand([("missing", None), ("string", "123"), ("boolean", True), ("outside", 1001)])
    @mock.patch(NOW_PATCH, return_value=1000)
    def test_invalid_or_ignored_history_filters_fail_instead_of_losing_data(
        self, name: str, timestamp: Any, now: mock.MagicMock
    ) -> None:
        with http_responses([response([{"id": "row", "createdTime": timestamp}])]):
            with self.assertRaisesRegex(ValueError, "timestamp|outside"):
                rows(source("orders", manager()))

    def test_changed_collection_envelope_fails_instead_of_erasing_a_table(self) -> None:
        bad_response = response([])
        bad_response._content = b'{"unexpected": []}'
        with http_responses([bad_response]):
            with self.assertRaisesRegex(ValueError, "data_selector"):
                rows(source("items", manager()))

    @parameterized.expand([(401,), (403,)])
    def test_auth_errors_propagate_without_source_retries(self, status: int) -> None:
        with http_responses([response([], status)]) as requests:
            with self.assertRaises(HTTPError):
                rows(source("items", manager()))
        self.assertEqual(len(requests), 1)

    def test_incremental_config_is_rejected_until_filters_are_verified(self) -> None:
        with self.assertRaisesRegex(ValueError, "full refresh only"):
            source("items", manager(), should_use_incremental_field=True)

    @parameterized.expand(
        [
            (403, None, True),
            (403, "items", False),
            (404, None, False),
            (302, None, False),
        ]
    )
    def test_credential_status_mapping(self, status: int, schema: str | None, valid: bool) -> None:
        with http_responses([response([], status)]) as requests:
            result = validate_credentials("na", MERCHANT_ID, BearerTokenAuth("test-token"), "v3", schema)
        self.assertEqual(result[0], valid)
        expected_path = f"/v3/merchants/{MERCHANT_ID}" + ("/items" if schema else "")
        self.assertEqual(urlsplit(requests[0].url or "").path, expected_path)
        if schema:
            self.assertIn("Read inventory", result[1] or "")

    def test_permission_probes_name_scopes_and_ignore_transient_failures(self) -> None:
        with http_responses([response([], 403), response([], 500), response([], 200)]) as requests:
            result = endpoint_permissions(
                "na", MERCHANT_ID, ["orders", "items", "line_items"], BearerTokenAuth("test-token"), "v3"
            )
        self.assertIn("Read orders", result["orders"] or "")
        self.assertIsNone(result["items"])
        self.assertIsNone(result["line_items"])
        self.assertTrue(all(params(request)["limit"] == ["1"] for request in requests))
        self.assertTrue((requests[-1].url or "").endswith("/orders?limit=1"))

    @parameterized.expand([("../oauth",), ("",), ("M\n",)])
    def test_invalid_merchant_ids_cannot_change_the_request_path(self, merchant_id: str) -> None:
        with http_responses([]) as requests:
            result = validate_credentials("na", merchant_id, BearerTokenAuth("test-token"), "v3")
        self.assertFalse(result[0])
        self.assertEqual(requests, [])
