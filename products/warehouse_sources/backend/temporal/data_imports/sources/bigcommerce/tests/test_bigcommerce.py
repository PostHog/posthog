import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.bigcommerce.bigcommerce import (
    BigCommerceResumeConfig,
    _to_v2_timestamp,
    _to_v3_timestamp,
    bigcommerce_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestGetResource:
    @parameterized.expand(
        [
            ("products", "/v3/catalog/products", "data", True),
            ("categories", "/v3/catalog/categories", "data", True),
            ("brands", "/v3/catalog/brands", "data", True),
            ("customers", "/v3/customers", "data", True),
            ("orders", "/v2/orders", None, False),
        ]
    )
    def test_path_and_envelope_per_endpoint(
        self, name: str, expected_path: str, expected_data_selector: str | None, expects_total_path: bool
    ) -> None:
        resource = get_resource(name, should_use_incremental_field=False)
        endpoint = cast(Endpoint, resource["endpoint"])

        assert endpoint["path"] == expected_path
        assert endpoint["data_selector"] == expected_data_selector
        assert resource["table_name"] == name
        assert resource["table_format"] == "delta"

        paginator = cast(PageNumberPaginator, endpoint["paginator"])
        assert paginator.page_param == "page"
        assert paginator.base_page == 1
        assert (paginator.total_path is not None) is expects_total_path

    @parameterized.expand(
        [
            ("products", False),
            ("categories", False),
            ("brands", False),
            ("customers", False),
            ("orders", False),
            ("products", True),
            ("categories", True),  # categories has no date_modified field: stays full refresh
            ("brands", True),  # same for brands
            ("customers", True),
            ("orders", True),
        ]
    )
    def test_write_disposition_and_incremental_param(self, name: str, should_use_incremental_field: bool) -> None:
        resource = get_resource(name, should_use_incremental_field)
        endpoint = cast(Endpoint, resource["endpoint"])
        params = cast(dict[str, Any], endpoint["params"])

        incremental_capable = name in ("products", "customers", "orders")
        use_incremental = should_use_incremental_field and incremental_capable

        if use_incremental:
            assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        else:
            assert resource["write_disposition"] == "replace"

        incremental_key = "min_date_modified" if name == "orders" else "date_modified:min"
        if use_incremental:
            assert incremental_key in params
            assert params[incremental_key]["type"] == "incremental"
        else:
            assert incremental_key not in params

    def test_limit_is_set_for_every_endpoint(self) -> None:
        for name in ("products", "categories", "brands", "customers", "orders"):
            resource = get_resource(name, should_use_incremental_field=False)
            endpoint = cast(Endpoint, resource["endpoint"])
            assert cast(dict[str, Any], endpoint["params"])["limit"] == 250


class TestTimestampConverters:
    @parameterized.expand(
        [
            ("naive", datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            ("aware_utc", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
        ]
    )
    def test_to_v3_timestamp_formats_datetime(self, _label: str, value: datetime, expected: str) -> None:
        assert _to_v3_timestamp(value) == expected

    def test_to_v3_timestamp_passes_through_non_datetime(self) -> None:
        assert _to_v3_timestamp("already-a-string") == "already-a-string"

    @parameterized.expand(
        [
            ("naive", datetime(2024, 1, 2, 3, 4, 5), "Tue, 02 Jan 2024 03:04:05 +0000"),
            ("aware_utc", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "Tue, 02 Jan 2024 03:04:05 +0000"),
        ]
    )
    def test_to_v2_timestamp_formats_datetime(self, _label: str, value: datetime, expected: str) -> None:
        assert _to_v2_timestamp(value) == expected

    def test_to_v2_timestamp_passes_through_non_datetime(self) -> None:
        assert _to_v2_timestamp("already-a-string") == "already-a-string"


def _make_http_response(body: Any, status_code: int = 200, headers: dict[str, str] | None = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    for key, value in (headers or {}).items():
        resp.headers[key] = value
    return resp


def _v3_page(items: list[dict[str, Any]], current_page: int, total_pages: int) -> dict[str, Any]:
    return {
        "data": items,
        "meta": {"pagination": {"current_page": current_page, "total_pages": total_pages}},
    }


class TestBigCommerceSourceResumeBehavior:
    """End-to-end resume behaviour of ``bigcommerce_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response], should_use_incremental_field: bool = False
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        """Drive ``bigcommerce_source`` with a mocked HTTP session.

        Returns ``(mock_session, sent_params)`` — shallow copies of ``request.params``
        captured at send-time, since the paginator mutates the Request object in place
        between pages.
        """
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = bigcommerce_source(
                store_hash="store123",
                access_token="test-token",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                should_use_incremental_field=should_use_incremental_field,
            )
            list(cast(Iterable[Any], resource))
            return mock_session, sent_params

    def test_v3_fresh_run_pages_until_total_pages_reached(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_v3_page([{"id": 1}], current_page=1, total_pages=3)),
            _make_http_response(_v3_page([{"id": 2}], current_page=2, total_pages=3)),
            _make_http_response(_v3_page([{"id": 3}], current_page=3, total_pages=3)),
        ]
        _, sent_params = self._drive("products", manager, responses)

        pages_sent = [p.get("page") for p in sent_params]
        assert pages_sent == [1, 2, 3]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            BigCommerceResumeConfig(page=2),
            BigCommerceResumeConfig(page=3),
        ]

    def test_v2_orders_stops_on_empty_page_with_no_pagination_envelope(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response([{"id": 1}]),
            _make_http_response([{"id": 2}]),
            _make_http_response([]),
        ]
        _, sent_params = self._drive("orders", manager, responses)

        assert [p.get("page") for p in sent_params] == [1, 2, 3]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = BigCommerceResumeConfig(page=5)

        responses = [_make_http_response(_v3_page([{"id": 9}], current_page=5, total_pages=5))]
        _, sent_params = self._drive("customers", manager, responses)

        assert [p.get("page") for p in sent_params] == [5]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response(_v3_page([{"id": 1}], current_page=1, total_pages=1))]
        self._drive("brands", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response(_v3_page([{"id": 1}], current_page=1, total_pages=1))]
        self._drive("categories", manager, responses)

        manager.load_state.assert_not_called()

    def test_v3_incremental_param_carries_converted_timestamp(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        last_value = datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC)

        sent_params: list[dict[str, Any]] = []

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return _make_http_response(_v3_page([], current_page=1, total_pages=1))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = bigcommerce_source(
                store_hash="store123",
                access_token="test-token",
                endpoint="products",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=last_value,
                should_use_incremental_field=True,
            )
            list(cast(Iterable[Any], resource))

        assert sent_params[0]["date_modified:min"] == "2024-05-06T07:08:09Z"

    def test_v2_incremental_param_carries_rfc2822_timestamp(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        last_value = datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC)

        sent_params: list[dict[str, Any]] = []

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return _make_http_response([])

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = bigcommerce_source(
                store_hash="store123",
                access_token="test-token",
                endpoint="orders",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=last_value,
                should_use_incremental_field=True,
            )
            list(cast(Iterable[Any], resource))

        assert sent_params[0]["min_date_modified"] == "Mon, 06 May 2024 07:08:09 +0000"


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 404])
    def test_returns_status_code(self, status_code: int) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigcommerce.bigcommerce.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = MagicMock(status_code=status_code)
            assert validate_credentials("store123", "token") == status_code

    def test_returns_none_on_connection_error(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigcommerce.bigcommerce.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.side_effect = ConnectionError("boom")
            assert validate_credentials("store123", "token") is None
