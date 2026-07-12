import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.maxio import (
    MaxioPaginator,
    MaxioResumeConfig,
    format_start_datetime,
    get_base_url,
    get_resource,
    maxio_source,
    normalize_subdomain,
    to_since_id,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.settings import ENDPOINTS, PAGE_SIZE


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _customer_page(count: int, start_id: int = 1) -> list[dict[str, Any]]:
    return [{"customer": {"id": start_id + i, "created_at": "2024-01-01T00:00:00Z"}} for i in range(count)]


class TestNormalizeSubdomain:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("acme", "acme"),
            (" acme ", "acme"),
            ("acme.chargify.com", "acme"),
            ("ACME.CHARGIFY.COM", "ACME"),
            ("https://acme.chargify.com/", "acme"),
            ("https://acme.ebilling.maxio.com/admin", "acme"),
            ("acme.ebilling.maxio.com", "acme"),
        ],
    )
    def test_normalizes_pasted_values(self, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected


class TestGetBaseUrl:
    @pytest.mark.parametrize(
        ("region", "expected"),
        [
            ("us", "https://acme.chargify.com"),
            ("eu", "https://acme.ebilling.maxio.com"),
            # Unknown regions fall back to US rather than crashing the sync.
            ("mars", "https://acme.chargify.com"),
        ],
    )
    def test_region_hosts(self, region: str, expected: str) -> None:
        assert get_base_url("acme", region) == expected


class TestConverters:
    def test_format_start_datetime_converts_aware_datetime_to_utc(self) -> None:
        value = datetime(2024, 5, 1, 10, 30, 0, tzinfo=timezone(timedelta(hours=-4)))
        assert format_start_datetime(value) == "2024-05-01 14:30:00"

    def test_format_start_datetime_treats_naive_datetime_as_utc(self) -> None:
        assert format_start_datetime(datetime(2024, 5, 1, 10, 30, 0)) == "2024-05-01 10:30:00"

    def test_format_start_datetime_passes_through_initial_string(self) -> None:
        assert format_start_datetime("1970-01-01 00:00:00") == "1970-01-01 00:00:00"

    @pytest.mark.parametrize(("value", "expected"), [(42, 42), ("42", 42)])
    def test_to_since_id(self, value: Any, expected: int) -> None:
        assert to_since_id(value) == expected


class TestMaxioPaginator:
    def test_initial_state_targets_first_page(self) -> None:
        paginator = MaxioPaginator(page_size=2)
        request = Request(method="GET", url="https://acme.chargify.com/customers.json")
        paginator.init_request(request)

        assert request.params["page"] == 1
        assert request.params["per_page"] == 2
        assert paginator.has_next_page is True

    def test_full_page_advances(self) -> None:
        paginator = MaxioPaginator(page_size=2)
        paginator.update_state(MagicMock(), data=[{"id": 1}, {"id": 2}])

        assert paginator.has_next_page is True
        assert paginator.page == 2

    @pytest.mark.parametrize("data", [[], [{"id": 1}], None])
    def test_short_or_empty_page_terminates(self, data: list[Any] | None) -> None:
        paginator = MaxioPaginator(page_size=2)
        paginator.update_state(MagicMock(), data=data)

        assert paginator.has_next_page is False

    def test_get_resume_state_returns_next_page_when_more(self) -> None:
        paginator = MaxioPaginator(page_size=2)
        paginator.update_state(MagicMock(), data=[{"id": 1}, {"id": 2}])

        assert paginator.get_resume_state() == {"page": 2}

    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = MaxioPaginator(page_size=2)
        paginator.update_state(MagicMock(), data=[{"id": 1}])

        assert paginator.get_resume_state() is None

    def test_set_resume_state_seeds_first_request(self) -> None:
        paginator = MaxioPaginator(page_size=2)
        paginator.set_resume_state({"page": 7})

        request = Request(method="GET", url="https://acme.chargify.com/customers.json")
        paginator.init_request(request)

        assert request.params["page"] == 7
        assert paginator.has_next_page is True

    def test_set_resume_state_ignores_missing_page(self) -> None:
        paginator = MaxioPaginator(page_size=2)
        paginator.set_resume_state({})

        assert paginator.page == 1


class TestGetResource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS.keys()))
    def test_full_refresh_has_no_incremental_params(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)
        params = cast(dict[str, Any], resource["endpoint"]["params"])

        assert "date_field" not in params
        assert "start_datetime" not in params
        assert "since_id" not in params
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == ENDPOINTS[endpoint].path
        assert resource["endpoint"]["data_selector"] == ENDPOINTS[endpoint].data_selector

    @pytest.mark.parametrize(
        ("endpoint", "date_field", "sort"),
        [
            ("customers", "created_at", None),
            ("subscriptions", "updated_at", "updated_at"),
            ("invoices", "updated_at", "updated_at"),
        ],
    )
    def test_incremental_datetime_endpoints_set_window_and_sort(
        self, endpoint: str, date_field: str, sort: str | None
    ) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)
        params = cast(dict[str, Any], resource["endpoint"]["params"])

        assert params["date_field"] == date_field
        assert params["start_datetime"]["type"] == "incremental"
        assert params["start_datetime"]["cursor_path"] == date_field
        assert params["direction"] == "asc"
        if sort is not None:
            assert params["sort"] == sort
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    def test_incremental_events_use_since_id(self) -> None:
        resource = get_resource("events", should_use_incremental_field=True)
        params = cast(dict[str, Any], resource["endpoint"]["params"])

        assert params["since_id"]["type"] == "incremental"
        assert params["since_id"]["cursor_path"] == "id"
        assert params["direction"] == "asc"
        assert "date_field" not in params

    @pytest.mark.parametrize(
        "endpoint", ["products", "product_families", "coupons", "components", "payment_profiles", "credit_notes"]
    )
    def test_full_refresh_only_endpoints_never_get_incremental_params(self, endpoint: str) -> None:
        # These endpoints advertise no incremental fields; even if the pipeline asked for
        # incremental, no server-side filter params must be emitted.
        resource = get_resource(endpoint, should_use_incremental_field=True)
        params = cast(dict[str, Any], resource["endpoint"]["params"])

        assert "date_field" not in params
        assert "start_datetime" not in params
        assert "since_id" not in params

    def test_invoices_include_breakdowns(self) -> None:
        params = get_resource("invoices", should_use_incremental_field=False)["endpoint"]["params"]
        for flag in ("line_items", "discounts", "taxes", "credits", "payments", "refunds"):
            assert params[flag] == "true"


class TestMaxioSourceDrive:
    """End-to-end behaviour of ``maxio_source`` via ``rest_api_resource`` with a mocked session."""

    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict[str, Any]], list[list[Any]]]:
        """Returns ``(sent_params, yielded_pages)``; params are copied at send-time because
        the paginator mutates the Request in place between pages."""
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

            resource = maxio_source(
                api_key="test-key",
                subdomain="acme",
                region="us",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
            )
            pages = list(cast(Iterable[Any], resource))
            return sent_params, pages

    def test_paginates_and_saves_state_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_customer_page(PAGE_SIZE)),
            _make_http_response(_customer_page(1, start_id=PAGE_SIZE + 1)),
        ]
        sent_params, pages = self._drive("customers", manager, responses)

        assert [p["page"] for p in sent_params] == [1, 2]
        assert all(p["per_page"] == PAGE_SIZE for p in sent_params)
        # Rows are unwrapped from the `{"customer": {...}}` envelope by the data selector.
        assert pages[0][0] == {"id": 1, "created_at": "2024-01-01T00:00:00Z"}

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [MaxioResumeConfig(endpoint="customers", next_page=2)]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        self._drive("customers", manager, [_make_http_response(_customer_page(3))])

        manager.save_state.assert_not_called()

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = MaxioResumeConfig(endpoint="customers", next_page=5)

        sent_params, _ = self._drive("customers", manager, [_make_http_response(_customer_page(1))])

        assert [p["page"] for p in sent_params] == [5]

    def test_resume_state_for_other_endpoint_is_ignored(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = MaxioResumeConfig(endpoint="invoices", next_page=5)

        sent_params, _ = self._drive("customers", manager, [_make_http_response(_customer_page(1))])

        assert [p["page"] for p in sent_params] == [1]

    def test_incremental_run_sends_formatted_watermark(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        sent_params, _ = self._drive(
            "subscriptions",
            manager,
            [_make_http_response([{"subscription": {"id": 1, "created_at": "2024-01-01T00:00:00Z"}}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, 10, 30, 0, tzinfo=UTC),
        )

        assert sent_params[0]["date_field"] == "updated_at"
        assert sent_params[0]["start_datetime"] == "2024-05-01 10:30:00"
        assert sent_params[0]["sort"] == "updated_at"
        assert sent_params[0]["direction"] == "asc"

    def test_incremental_events_run_sends_since_id(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        sent_params, pages = self._drive(
            "events",
            manager,
            [_make_http_response([{"event": {"id": 101, "key": "signup_success"}}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=100,
        )

        assert sent_params[0]["since_id"] == 100
        assert pages[0][0]["id"] == 101

    def test_invoices_rows_are_extracted_from_wrapped_response(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        _, pages = self._drive(
            "invoices",
            manager,
            [_make_http_response({"invoices": [{"uid": "inv_1", "created_at": "2024-01-01T00:00:00Z"}]})],
        )

        assert pages[0] == [{"uid": "inv_1", "created_at": "2024-01-01T00:00:00Z"}]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_error_fragment"),
        [
            (200, True, None),
            (401, False, "rejected the API key"),
            (404, False, "site not found"),
            (500, False, "HTTP 500"),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_error_fragment: str | None) -> None:
        response = MagicMock()
        response.status_code = status_code

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.maxio.maxio.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = response
            valid, error = validate_credentials("key", "acme", "us")

        assert valid is expected_valid
        if expected_error_fragment is None:
            assert error is None
        else:
            assert error is not None
            assert expected_error_fragment in error

    def test_probe_targets_region_host_with_basic_auth(self) -> None:
        response = MagicMock()
        response.status_code = 200

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.maxio.maxio.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = response
            validate_credentials("key", "acme", "eu")

        call = MockSession.return_value.get.call_args
        assert call.args[0] == "https://acme.ebilling.maxio.com/customers.json"
        assert call.kwargs["auth"] == ("key", "x")
        assert call.kwargs["params"] == {"page": 1, "per_page": 1}
