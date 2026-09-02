import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.dodopayments import (
    DodoPaymentsPaginator,
    DodoPaymentsResumeConfig,
    base_url_for_mode,
    dodopayments_source,
    to_iso8601,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.settings import (
    DODOPAYMENTS_ENDPOINTS,
    PAGE_SIZE,
    REQUEST_TIMEOUT_SECONDS,
)

SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.dodopayments.make_tracked_session"
)
REST_RESOURCE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.dodopayments.rest_api_resource"
)


def _response(items: list[dict[str, Any]]) -> Response:
    response = Response()
    response.status_code = 200
    response._content = json.dumps({"items": items}).encode()
    return response


def _page(size: int, start: int = 0) -> Response:
    return _response([{"payment_id": f"pay_{start + i}", "created_at": "2024-05-01T00:00:00Z"} for i in range(size)])


def _make_manager(resume_state: DodoPaymentsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
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


def _source(endpoint: str, manager: mock.MagicMock | None = None, mode: str = "live", **kwargs: Any):
    return dodopayments_source(
        "test-api-key",
        mode,
        endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToIso8601:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            # A datetime watermark must not be str()'d: "2024-05-01 10:00:00+00:00" is not
            # ISO-8601 and the date filters reject it.
            (datetime(2024, 5, 1, 10, tzinfo=UTC), "2024-05-01T10:00:00Z"),
            (datetime(2024, 5, 1, 10), "2024-05-01T10:00:00Z"),
            (datetime(2024, 5, 1, 12, tzinfo=UTC).astimezone(UTC), "2024-05-01T12:00:00Z"),
            (date(2024, 5, 1), "2024-05-01T00:00:00Z"),
            ("2024-05-01T10:00:00Z", "2024-05-01T10:00:00Z"),
            ("2024-05-01T12:00:00+02:00", "2024-05-01T10:00:00Z"),
            (1714557600, "2024-05-01T10:00:00Z"),
            ("not-a-date", None),
            (object(), None),
        ],
    )
    def test_values(self, value, expected):
        assert to_iso8601(value) == expected


class TestBaseUrlForMode:
    @pytest.mark.parametrize(
        "mode, expected",
        [
            ("live", "https://live.dodopayments.com"),
            ("test", "https://test.dodopayments.com"),
            ("nonsense", "https://live.dodopayments.com"),
        ],
    )
    def test_mode_selects_host(self, mode, expected):
        assert base_url_for_mode(mode) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [(200, True), (401, False), (403, False), (429, False), (500, False)],
    )
    @mock.patch(SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected_valid):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        is_valid, status = validate_credentials("key", "live")

        assert is_valid is expected_valid
        assert status == status_code

    @pytest.mark.parametrize(
        "mode, expected_url",
        [
            ("live", "https://live.dodopayments.com/customers?page_size=1"),
            ("test", "https://test.dodopayments.com/customers?page_size=1"),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_probe_targets_the_host_for_the_mode(self, mock_session, mode, expected_url):
        # A live key probed against the test host (or vice versa) always 401s, so the mode has to
        # reach the probe URL.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key", mode)

        call = mock_session.return_value.get.call_args
        assert call.args[0] == expected_url
        assert call.kwargs["headers"]["Authorization"] == "Bearer key"

    @mock.patch(SESSION_PATCH)
    def test_transport_failure_is_not_valid(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")

        assert validate_credentials("key", "live") == (False, None)


class TestPagination:
    @mock.patch(SESSION_PATCH)
    def test_walks_zero_based_pages_and_stops_on_short_page(self, MockSession):
        requests_seen = _wire(MockSession.return_value, [_page(PAGE_SIZE), _page(3, start=PAGE_SIZE)])
        manager = _make_manager()

        rows = _rows(_source("payments", manager))

        assert len(rows) == PAGE_SIZE + 3
        # Page numbers are 0-based; starting at 1 would silently skip the newest page.
        assert [snapshot["params"]["page_number"] for snapshot in requests_seen] == [0, 1]
        assert requests_seen[0]["params"]["page_size"] == PAGE_SIZE
        # A short page terminates without paying for the extra empty-page request.
        assert len(requests_seen) == 2
        assert manager.save_state.call_args_list == [mock.call(DodoPaymentsResumeConfig(page_number=1))]

    @mock.patch(SESSION_PATCH)
    def test_full_page_then_empty_page_terminates(self, MockSession):
        requests_seen = _wire(MockSession.return_value, [_page(PAGE_SIZE), _page(0)])

        rows = _rows(_source("payments"))

        assert len(rows) == PAGE_SIZE
        assert len(requests_seen) == 2

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession):
        requests_seen = _wire(MockSession.return_value, [_page(2, start=400)])

        rows = _rows(_source("payments", _make_manager(DodoPaymentsResumeConfig(page_number=4))))

        assert [row["payment_id"] for row in rows] == ["pay_400", "pay_401"]
        assert requests_seen[0]["params"]["page_number"] == 4

    @mock.patch(SESSION_PATCH)
    def test_unpaginated_endpoint_makes_one_request_without_page_params(self, MockSession):
        # `/brands` accepts no query parameters at all.
        requests_seen = _wire(MockSession.return_value, [_response([{"brand_id": "brand_1"}])])

        rows = _rows(_source("brands"))

        assert [row["brand_id"] for row in rows] == ["brand_1"]
        assert len(requests_seen) == 1
        assert requests_seen[0]["params"] == {}

    def test_paginator_resume_state_is_none_once_exhausted(self):
        paginator = DodoPaymentsPaginator()
        paginator.update_state(_response([]), [])

        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None


class TestRequestParams:
    @pytest.mark.parametrize(
        "endpoint, expected_param",
        [
            ("payments", "created_at_gte"),
            ("subscriptions", "created_at_gte"),
            ("balance_ledger_entries", "created_at_gte"),
            # Usage events filter on `start`, not `created_at_gte`.
            ("events", "start"),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_incremental_sync_sends_the_endpoints_date_filter(self, MockSession, endpoint, expected_param):
        requests_seen = _wire(MockSession.return_value, [_page(1)])

        _rows(
            _source(
                endpoint,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 5, 1, 10, tzinfo=UTC),
            )
        )

        assert requests_seen[0]["params"][expected_param] == "2024-05-01T10:00:00Z"

    @mock.patch(SESSION_PATCH)
    def test_full_refresh_sends_no_date_filter(self, MockSession):
        requests_seen = _wire(MockSession.return_value, [_page(1)])

        _rows(_source("payments", db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC)))

        assert "created_at_gte" not in requests_seen[0]["params"]

    @mock.patch(SESSION_PATCH)
    def test_unparseable_watermark_drops_the_filter(self, MockSession):
        # Sending a value the API rejects would fail the whole sync; a full walk is the safe fallback.
        requests_seen = _wire(MockSession.return_value, [_page(1)])

        _rows(_source("payments", should_use_incremental_field=True, db_incremental_field_last_value="garbage"))

        assert "created_at_gte" not in requests_seen[0]["params"]

    @mock.patch(SESSION_PATCH)
    def test_catalog_endpoint_never_gets_a_date_filter(self, MockSession):
        # `/products` exposes no date filter; sending one would be rejected.
        requests_seen = _wire(MockSession.return_value, [_response([{"product_id": "prod_1"}])])

        _rows(
            _source(
                "products",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
            )
        )

        assert set(requests_seen[0]["params"]) == {"page_size", "page_number"}


class TestSourceResponseMetadata:
    @pytest.mark.parametrize("endpoint", list(DODOPAYMENTS_ENDPOINTS))
    @mock.patch(SESSION_PATCH)
    def test_metadata_matches_the_endpoint_catalog(self, MockSession, endpoint):
        config = DODOPAYMENTS_ENDPOINTS[endpoint]

        response = _source(endpoint)

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Dodo documents no ordering guarantee, so the watermark must only finalize at the end
        # of a successful sync.
        assert response.sort_mode == "desc"
        if config.partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]

    @pytest.mark.parametrize(
        "endpoint, should_use_incremental_field, expected_disposition",
        [
            ("payments", True, {"disposition": "merge", "strategy": "upsert"}),
            ("payments", False, "replace"),
            ("products", False, "replace"),
        ],
    )
    @mock.patch(REST_RESOURCE_PATCH)
    def test_write_disposition_follows_incremental_mode(
        self, mock_rest_api_resource, endpoint, should_use_incremental_field, expected_disposition
    ):
        _source(endpoint, should_use_incremental_field=should_use_incremental_field)

        resource = mock_rest_api_resource.call_args.args[0]["resources"][0]
        assert resource["write_disposition"] == expected_disposition
        assert resource["primary_key"] == DODOPAYMENTS_ENDPOINTS[endpoint].primary_keys

    @mock.patch(REST_RESOURCE_PATCH)
    def test_base_url_follows_the_mode(self, mock_rest_api_resource):
        _source("payments", mode="test")

        assert mock_rest_api_resource.call_args.args[0]["client"]["base_url"] == "https://test.dodopayments.com"

    @mock.patch(REST_RESOURCE_PATCH)
    def test_client_bounds_every_request_with_a_timeout(self, mock_rest_api_resource):
        # Without this a stalled connect or hung read would pin an import worker indefinitely.
        _source("payments")

        assert mock_rest_api_resource.call_args.args[0]["client"]["request_timeout"] == REQUEST_TIMEOUT_SECONDS

    @mock.patch(REST_RESOURCE_PATCH)
    def test_framework_incremental_injection_is_not_used(self, mock_rest_api_resource):
        # The date filter is baked into the request params, so letting the framework inject its own
        # incremental param too would send a second, differently named filter.
        _source(
            "payments",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
        )

        assert mock_rest_api_resource.call_args.kwargs["db_incremental_field_last_value"] is None


class TestEndpointCatalog:
    def test_every_incremental_endpoint_declares_a_server_side_filter(self):
        # Without a server-side filter an "incremental" sync would still fetch every page.
        for name, config in DODOPAYMENTS_ENDPOINTS.items():
            assert bool(config.incremental_fields) == (config.start_param is not None), name

    def test_incremental_cursor_matches_the_partition_key(self):
        # The cursor and the partition key must both be creation timestamps that never change.
        for name, config in DODOPAYMENTS_ENDPOINTS.items():
            if not config.incremental_fields:
                continue
            assert [f["field"] for f in config.incremental_fields] == [config.partition_key], name
