import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.fourthwall import (
    FourthwallResumeConfig,
    _format_datetime,
    create_webhook,
    delete_webhook,
    fourthwall_source,
    get_external_webhook_info,
    get_resource,
    sync_webhook_events,
    validate_credentials,
    webhook_table_transformer,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.settings import (
    ALL_WEBHOOK_EVENTS,
    ENDPOINTS,
    FOURTHWALL_ENDPOINTS,
    PAGE_SIZE,
)

SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.fourthwall.make_tracked_session"
)
REST_RESOURCE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.fourthwall.rest_api_resource"
)
API_ROOT = "https://api.fourthwall.com/open-api/v1.0"


def _page(results: list[dict[str, Any]], total_pages: int) -> Response:
    response = Response()
    response.status_code = 200
    response._content = json.dumps(
        {"results": results, "total": len(results), "page": 0, "size": PAGE_SIZE, "totalPages": total_pages}
    ).encode()
    return response


def _bare(items: list[dict[str, Any]]) -> Response:
    response = Response()
    response.status_code = 200
    response._content = json.dumps(items).encode()
    return response


def _make_manager(resume_state: FourthwallResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session, snapshotting each request at prepare time (params mutate per page)."""
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return fourthwall_source(
        "api-user",
        "api-secret",
        endpoint,
        team_id=1,
        job_id="job-1",
        api_version="v1.0",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _order(order_id: str, updated_at: str = "2026-05-01T10:00:00.000Z") -> dict[str, Any]:
    return {"id": order_id, "status": "CONFIRMED", "createdAt": "2026-04-01T10:00:00.000Z", "updatedAt": updated_at}


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 5, 1, 10, 30, 15, 123456, tzinfo=UTC), "2026-05-01T10:30:15Z"),
            # Naive values are treated as UTC, matching the rest of the pipeline.
            (datetime(2026, 5, 1, 10, 30, 15), "2026-05-01T10:30:15Z"),
        ],
    )
    def test_truncates_to_whole_seconds_in_utc(self, value, expected):
        # Rounding the lower bound down re-reads a few boundary orders (merge dedupes them)
        # instead of skipping an order whose updatedAt equals the watermark.
        assert _format_datetime(value) == expected

    def test_non_datetime_passes_through_as_string(self):
        assert _format_datetime("2026-05-01T10:30:15Z") == "2026-05-01T10:30:15Z"


def _endpoint_config(endpoint: str, should_use_incremental_field: bool = False) -> dict[str, Any]:
    return cast("dict[str, Any]", get_resource(endpoint, should_use_incremental_field)["endpoint"])


class TestGetResource:
    @pytest.mark.parametrize(
        "endpoint",
        [
            name
            for name in ENDPOINTS
            if FOURTHWALL_ENDPOINTS[name].paginated and not FOURTHWALL_ENDPOINTS[name].page_in_path
        ],
    )
    def test_paginated_endpoints_select_the_results_envelope(self, endpoint):
        endpoint_config = _endpoint_config(endpoint)

        assert endpoint_config["data_selector"] == "results"
        assert endpoint_config["params"]["size"] == PAGE_SIZE
        assert endpoint_config["path"] == FOURTHWALL_ENDPOINTS[endpoint].path

    @pytest.mark.parametrize("endpoint", [name for name in ENDPOINTS if not FOURTHWALL_ENDPOINTS[name].paginated])
    def test_bare_array_endpoints_take_no_selector_and_a_single_page(self, endpoint):
        # A `results` selector here would match nothing and sync zero rows.
        endpoint_config = _endpoint_config(endpoint)

        assert "data_selector" not in endpoint_config
        assert endpoint_config["paginator"] == "single_page"

    @pytest.mark.parametrize(
        "endpoint, should_use_incremental_field, expected_disposition",
        [
            ("orders", True, {"disposition": "merge", "strategy": "upsert"}),
            ("orders", False, "replace"),
            # products has no server-side timestamp filter, so it stays a full replace even
            # when the pipeline asks for an incremental run.
            ("products", True, "replace"),
        ],
    )
    def test_write_disposition_follows_real_incremental_support(
        self, endpoint, should_use_incremental_field, expected_disposition
    ):
        resource = get_resource(endpoint, should_use_incremental_field=should_use_incremental_field)
        assert resource["write_disposition"] == expected_disposition

    def test_only_orders_declares_a_server_side_incremental_filter(self):
        # Declaring an incremental param an endpoint doesn't support would send a filter the
        # API ignores, turning every "incremental" sync back into a full scan.
        with_param = {name for name, config in FOURTHWALL_ENDPOINTS.items() if config.incremental_param}
        assert with_param == {"orders"}
        assert FOURTHWALL_ENDPOINTS["orders"].incremental_param == "updatedAt[gt]"


class TestPagination:
    @mock.patch(SESSION_PATCH)
    def test_walks_pages_until_total_pages(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_page([_order("1")], 2), _page([_order("2")], 2)])

        manager = _make_manager()
        rows = _rows(_source("orders", manager))

        assert [row["id"] for row in rows] == ["1", "2"]
        assert [request["params"]["page"] for request in requests_seen] == [0, 1]
        assert all(request["params"]["size"] == PAGE_SIZE for request in requests_seen)
        # Checkpointed only while a next page remains, after the page was yielded.
        assert manager.save_state.call_count == 1
        assert manager.save_state.call_args.args[0] == FourthwallResumeConfig(paginator_state={"page": 1})

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_page([_order("9")], 4)])

        rows = _rows(_source("orders", _make_manager(FourthwallResumeConfig(paginator_state={"page": 3}))))

        assert [row["id"] for row in rows] == ["9"]
        assert requests_seen[0]["params"]["page"] == 3

    @mock.patch(SESSION_PATCH)
    def test_bare_array_endpoint_yields_body_rows_without_pagination(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_bare([{"id": "tier_1", "name": "Gold"}])])

        rows = _rows(_source("membership_tiers", _make_manager()))

        assert rows == [{"id": "tier_1", "name": "Gold"}]
        assert len(requests_seen) == 1


def _templates_page(results: list[dict[str, Any]]) -> Response:
    response = Response()
    response.status_code = 200
    response._content = json.dumps({"results": results, "total": 3}).encode()
    return response


class TestProductTemplatePagination:
    @mock.patch(SESSION_PATCH)
    def test_walks_pages_by_path_until_empty(self, MockSession):
        # product-templates pages by a 1-based path segment with no `totalPages`, so it must
        # walk `/page/1`, `/page/2`, ... and stop only when a page returns no rows.
        session = MockSession.return_value
        requests_seen = _wire(
            session,
            [
                _templates_page([{"productId": "pt_1"}, {"productId": "pt_2"}]),
                _templates_page([{"productId": "pt_3"}]),
                _templates_page([]),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("product_templates", manager))

        assert [row["productId"] for row in rows] == ["pt_1", "pt_2", "pt_3"]
        assert [request["url"] for request in requests_seen] == [
            f"{API_ROOT}/product-templates/page/1",
            f"{API_ROOT}/product-templates/page/2",
            f"{API_ROOT}/product-templates/page/3",
        ]
        # Checkpointed after each non-empty page while a next page remained; the empty page saves nothing.
        assert manager.save_state.call_count == 2
        assert manager.save_state.call_args.args[0] == FourthwallResumeConfig(paginator_state={"page": 3})

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_templates_page([{"productId": "pt_9"}]), _templates_page([])])

        rows = _rows(_source("product_templates", _make_manager(FourthwallResumeConfig(paginator_state={"page": 4}))))

        assert [row["productId"] for row in rows] == ["pt_9"]
        assert requests_seen[0]["url"] == f"{API_ROOT}/product-templates/page/4"


class TestIncrementalRequests:
    @mock.patch(SESSION_PATCH)
    def test_incremental_sync_sends_the_watermark_on_every_page(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_page([_order("1")], 2), _page([_order("2")], 2)])

        _rows(
            _source(
                "orders",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC),
            )
        )

        # The filter has to ride every page, otherwise later pages walk the full history.
        assert [request["params"].get("updatedAt[gt]") for request in requests_seen] == [
            "2026-05-01T10:00:00Z",
            "2026-05-01T10:00:00Z",
        ]

    @mock.patch(SESSION_PATCH)
    def test_first_incremental_sync_starts_from_the_epoch(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_page([_order("1")], 1)])

        _rows(_source("orders", _make_manager(), should_use_incremental_field=True))

        assert requests_seen[0]["params"]["updatedAt[gt]"] == "1970-01-01T00:00:00Z"

    @mock.patch(SESSION_PATCH)
    def test_full_refresh_sends_no_timestamp_filter(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_page([_order("1")], 1)])

        _rows(_source("orders", _make_manager()))

        assert "updatedAt[gt]" not in requests_seen[0]["params"]


class TestSourceResponseMetadata:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(REST_RESOURCE_PATCH)
    def test_metadata_matches_the_endpoint_catalog(self, mock_rest_api_resource, endpoint):
        config = FOURTHWALL_ENDPOINTS[endpoint]

        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        # Every table is a top-level list endpoint keyed by a globally unique id, so the
        # endpoint's primary key stays unique table-wide.
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == config.sort_mode
        assert response.partition_keys == ([config.partition_key] if config.partition_key else None)
        assert response.partition_mode == ("datetime" if config.partition_key else None)

    def test_orders_finalize_the_watermark_only_after_a_full_sync(self):
        # Fourthwall documents no ordering for the orders list and takes no sort parameter, so
        # `asc` would checkpoint the watermark to whatever the first page happened to contain.
        assert FOURTHWALL_ENDPOINTS["orders"].sort_mode == "desc"

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_partition_keys_never_move(self, endpoint):
        # A partition key that changes rewrites partitions on every sync.
        assert FOURTHWALL_ENDPOINTS[endpoint].partition_key in (None, "createdAt")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [(200, True), (401, False), (403, False), (404, False), (429, False), (500, False)],
    )
    @mock.patch(SESSION_PATCH)
    def test_status_mapping(self, MockSession, status_code, expected_valid):
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        is_valid, error = validate_credentials("api-user", "api-secret", "v1.0")

        assert is_valid is expected_valid
        assert (error is None) is expected_valid

    @mock.patch(SESSION_PATCH)
    def test_probes_the_shop_endpoint_on_the_pinned_version(self, MockSession):
        session = MockSession.return_value
        session.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("api-user", "api-secret", "v1.0")

        assert session.get.call_args.args[0] == f"{API_ROOT}/shops/current"
        assert session.auth == ("api-user", "api-secret")


class TestWebhookTableTransformer:
    def _table(self, events: list[dict[str, Any]]):
        return table_from_py_list(events)

    def test_lifts_the_resource_out_of_the_event_envelope(self):
        table = self._table(
            [
                {
                    "id": "weve_1",
                    "type": "ORDER_PLACED",
                    "createdAt": "2026-05-01T10:00:00+00:00",
                    "data": _order("order_1"),
                }
            ]
        )

        rows = webhook_table_transformer(table).to_pylist()

        assert [row["id"] for row in rows] == ["order_1"]
        assert rows[0]["status"] == "CONFIRMED"

    def test_unwraps_the_nested_order_on_order_updated(self):
        # ORDER_UPDATED nests the order under `data.order`; without unwrapping, the row would
        # carry the wrapper's shape and never merge onto the orders table.
        table = self._table(
            [
                {
                    "id": "weve_1",
                    "type": "ORDER_UPDATED",
                    "createdAt": "2026-05-01T10:00:00+00:00",
                    "data": {"order": _order("order_1"), "update": {"type": "STATUS"}},
                }
            ]
        )

        rows = webhook_table_transformer(table).to_pylist()

        assert [row["id"] for row in rows] == ["order_1"]

    def test_keeps_only_the_newest_event_per_object(self):
        # Delta merge dedupes across syncs but not within one batch, so a placed-then-updated
        # pair for the same order has to collapse here.
        table = self._table(
            [
                {
                    "id": "weve_1",
                    "type": "ORDER_PLACED",
                    "createdAt": "2026-05-01T10:00:00+00:00",
                    "data": _order("order_1", updated_at="2026-05-01T10:00:00.000Z"),
                },
                {
                    "id": "weve_2",
                    "type": "ORDER_UPDATED",
                    "createdAt": "2026-05-02T10:00:00+00:00",
                    "data": {"order": _order("order_1", updated_at="2026-05-02T10:00:00.000Z")},
                },
            ]
        )

        rows = webhook_table_transformer(table).to_pylist()

        assert len(rows) == 1
        assert rows[0]["updatedAt"] == "2026-05-02T10:00:00.000Z"

    def test_out_of_order_delivery_still_keeps_the_newest(self):
        table = self._table(
            [
                {
                    "id": "weve_2",
                    "type": "ORDER_UPDATED",
                    "createdAt": "2026-05-02T10:00:00+00:00",
                    "data": {"order": _order("order_1", updated_at="2026-05-02T10:00:00.000Z")},
                },
                {
                    "id": "weve_1",
                    "type": "ORDER_PLACED",
                    "createdAt": "2026-05-01T10:00:00+00:00",
                    "data": _order("order_1", updated_at="2026-05-01T10:00:00.000Z"),
                },
            ]
        )

        rows = webhook_table_transformer(table).to_pylist()

        assert len(rows) == 1
        assert rows[0]["updatedAt"] == "2026-05-02T10:00:00.000Z"

    @pytest.mark.parametrize(
        "event",
        [
            {"id": "weve_1", "type": "ORDER_PLACED", "createdAt": "2026-05-01T10:00:00+00:00", "data": {}},
            {"id": "weve_1", "type": "ORDER_UPDATED", "createdAt": "2026-05-01T10:00:00+00:00", "data": {}},
        ],
    )
    def test_drops_payloads_with_no_object_id(self, event):
        # A row with no primary key would break the merge, so it must never reach the table.
        assert webhook_table_transformer(self._table([event])).num_rows == 0

    def test_empty_delivery_batch_yields_no_rows(self):
        assert webhook_table_transformer(table_from_py_list([{"unexpected": 1}])).num_rows == 0


class TestWebhookManagement:
    def _session(self, MockSession) -> mock.MagicMock:
        return MockSession.return_value

    def _webhook_page(self, results: list[dict[str, Any]], total_pages: int = 1) -> mock.MagicMock:
        response = mock.MagicMock(status_code=200)
        response.json.return_value = {"results": results, "totalPages": total_pages}
        return response

    @mock.patch(SESSION_PATCH)
    def test_create_webhook_stores_the_returned_secret(self, MockSession):
        session = self._session(MockSession)
        session.post.return_value = mock.MagicMock(status_code=200)
        session.post.return_value.json.return_value = {"id": "wcon_1", "secret": "shhh"}

        result = create_webhook("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1")

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "shhh"}
        assert session.post.call_args.args[0] == f"{API_ROOT}/webhooks"
        assert session.post.call_args.kwargs["json"] == {
            "url": "https://us.posthog.com/w/1",
            "allowedTypes": ALL_WEBHOOK_EVENTS,
        }

    @mock.patch(SESSION_PATCH)
    def test_create_webhook_asks_for_the_secret_when_the_response_omits_it(self, MockSession):
        # The published webhook schema does not list `secret`, so the user has to paste it;
        # silently succeeding without it would leave every delivery failing the signature check.
        session = self._session(MockSession)
        session.post.return_value = mock.MagicMock(status_code=200)
        session.post.return_value.json.return_value = {"id": "wcon_1"}

        result = create_webhook("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1")

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]
        assert result.extra_inputs == {}

    @pytest.mark.parametrize("status_code", [400, 401, 429])
    @mock.patch(SESSION_PATCH)
    def test_create_webhook_reports_a_rejected_registration(self, MockSession, status_code):
        session = self._session(MockSession)
        session.post.return_value = mock.MagicMock(status_code=status_code)

        result = create_webhook("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1")

        assert result.success is False
        assert result.error is not None

    @mock.patch(SESSION_PATCH)
    def test_sync_webhook_events_merges_instead_of_replacing(self, MockSession):
        # Replacing would wipe events a user added by hand in the Fourthwall dashboard.
        session = self._session(MockSession)
        session.get.return_value = self._webhook_page(
            [{"id": "wcon_1", "url": "https://us.posthog.com/w/1", "allowedTypes": ["THANK_YOU_SENT"]}]
        )

        result = sync_webhook_events("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1", ["ORDER_PLACED"])

        assert result.success is True
        assert session.put.call_args.kwargs["json"] == {
            "url": "https://us.posthog.com/w/1",
            "allowedTypes": ["ORDER_PLACED", "THANK_YOU_SENT"],
        }

    @mock.patch(SESSION_PATCH)
    def test_sync_webhook_events_skips_an_already_correct_webhook(self, MockSession):
        session = self._session(MockSession)
        session.get.return_value = self._webhook_page(
            [{"id": "wcon_1", "url": "https://us.posthog.com/w/1", "allowedTypes": ["ORDER_PLACED"]}]
        )

        sync_webhook_events("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1", ["ORDER_PLACED"])

        session.put.assert_not_called()

    @mock.patch(SESSION_PATCH)
    def test_webhook_lookup_walks_every_page(self, MockSession):
        # Stopping after page one would silently skip a shop's webhook and leave a stale
        # registration behind on delete.
        session = self._session(MockSession)
        session.get.side_effect = [
            self._webhook_page([{"id": "wcon_1", "url": "https://other", "allowedTypes": []}], total_pages=2),
            self._webhook_page(
                [{"id": "wcon_2", "url": "https://us.posthog.com/w/1", "allowedTypes": []}], total_pages=2
            ),
        ]
        session.delete.return_value = mock.MagicMock(status_code=200)

        result = delete_webhook("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1")

        assert result.success is True
        assert session.delete.call_args.args[0] == f"{API_ROOT}/webhooks/wcon_2"

    @mock.patch(SESSION_PATCH)
    def test_delete_webhook_reports_a_failed_deletion(self, MockSession):
        session = self._session(MockSession)
        session.get.return_value = self._webhook_page(
            [{"id": "wcon_1", "url": "https://us.posthog.com/w/1", "allowedTypes": []}]
        )
        session.delete.return_value = mock.MagicMock(status_code=500)

        result = delete_webhook("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1")

        assert result.success is False

    @mock.patch(SESSION_PATCH)
    def test_external_webhook_info_matches_on_url(self, MockSession):
        session = self._session(MockSession)
        session.get.return_value = self._webhook_page(
            [
                {"id": "wcon_1", "url": "https://elsewhere", "allowedTypes": ["DONATION"]},
                {"id": "wcon_2", "url": "https://us.posthog.com/w/1", "allowedTypes": ["ORDER_PLACED"]},
            ]
        )

        info = get_external_webhook_info("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1")

        assert info.exists is True
        assert info.enabled_events == ["ORDER_PLACED"]

    @mock.patch(SESSION_PATCH)
    def test_external_webhook_info_when_absent(self, MockSession):
        self._session(MockSession).get.return_value = self._webhook_page([])

        assert get_external_webhook_info("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1").exists is False

    @mock.patch(SESSION_PATCH)
    def test_webhook_helpers_surface_transport_failures(self, MockSession):
        self._session(MockSession).get.side_effect = Exception("boom")

        assert get_external_webhook_info("api-user", "api-secret", "v1.0", "https://u/1").error == "boom"
        assert sync_webhook_events("api-user", "api-secret", "v1.0", "https://u/1", []).success is False
        assert delete_webhook("api-user", "api-secret", "v1.0", "https://u/1").success is False
