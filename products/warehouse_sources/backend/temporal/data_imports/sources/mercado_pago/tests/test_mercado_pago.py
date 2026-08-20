import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.mercado_pago import (
    MISSING_ACCESS_TOKEN_ERROR,
    MercadoPagoResumeConfig,
    MercadoPagoSearchPaginator,
    build_auth,
    build_request_params,
    format_search_datetime,
    mercado_pago_source,
    resolve_cursor_field,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.settings import (
    MERCADO_PAGO_ENDPOINTS,
    PAGE_SIZE,
)

# RESTClient builds its pipeline session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# The credential probe builds its own session directly in the source module.
PROBE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.mercado_pago.make_tracked_session"
)

ACCESS_TOKEN = "APP_USR-secret-token"


def _payment(payment_id: int) -> dict[str, Any]:
    return {"id": payment_id, "status": "approved", "date_created": "2026-01-01T00:00:00.000-03:00"}


def _search_body(rows: list[dict[str, Any]], *, total: Optional[int] = None, offset: Optional[int] = None) -> Any:
    paging: dict[str, Any] = {"limit": PAGE_SIZE}
    if total is not None:
        paging["total"] = total
    if offset is not None:
        paging["offset"] = offset
    return {"paging": paging, "results": rows}


def _json_response(body: Any, *, status_code: int = 200) -> requests.Response:
    """A real requests.Response so the framework's status/parse handling behaves as in prod."""
    response = requests.Response()
    response.status_code = status_code
    response.url = "https://api.mercadopago.com/v1/payments/search"
    response.reason = "OK" if status_code < 400 else "Error"
    response._content = json.dumps(body).encode()
    return response


def _mock_response(status_code: int, json_data: Any = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data if json_data is not None else {}
    return response


def _make_manager(resume_state: Optional[MercadoPagoResumeConfig] = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: MagicMock, responses: list[requests.Response]) -> list[dict[str, Any]]:
    """Wire a mock session, snapshotting each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — copy it as each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: SourceResponse) -> list[dict[str, Any]]:
    pages = cast("Iterable[list[dict[str, Any]]]", source_response.items())
    return [row for page in pages for row in page]


def _source(
    manager: MagicMock,
    endpoint: str,
    *,
    access_token: str = ACCESS_TOKEN,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    return mercado_pago_source(
        access_token=access_token,
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        incremental_field=incremental_field,
    )


class TestFormatSearchDatetime:
    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5, 123000), "2026-01-02T03:04:05.123Z"),
            (
                "aware_datetime",
                datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                "2026-01-02T03:04:05.000Z",
            ),
            ("date", date(2026, 1, 2), "2026-01-02T00:00:00.000Z"),
            ("iso_string", "2026-01-02T03:04:05Z", "2026-01-02T03:04:05.000Z"),
            ("offset_string", "2026-01-02T00:04:05.000-03:00", "2026-01-02T03:04:05.000Z"),
        ]
    )
    def test_formats_watermarks_as_utc_iso(self, _name: str, value: Any, expected: str) -> None:
        assert format_search_datetime(value) == expected

    def test_unparseable_value_passes_through(self) -> None:
        assert format_search_datetime("not-a-date") == "not-a-date"


class TestBuildAuth:
    def test_access_token_uses_bearer_auth(self) -> None:
        auth = build_auth(ACCESS_TOKEN)
        assert isinstance(auth, BearerTokenAuth)
        assert auth.token == ACCESS_TOKEN
        # The token must be redacted from logs and captured samples.
        assert auth.secret_values() == (ACCESS_TOKEN,)

    @parameterized.expand([("none", None), ("empty", "")])
    def test_missing_access_token_raises(self, _name: str, access_token: Optional[str]) -> None:
        with pytest.raises(ValueError, match=MISSING_ACCESS_TOKEN_ERROR):
            build_auth(access_token)


class TestResolveCursorField:
    @parameterized.expand(
        [
            ("user_choice_honored", "payments", "date_created", "date_created"),
            ("user_choice_honored_alt", "payments", "date_last_updated", "date_last_updated"),
            ("unknown_choice_falls_back", "payments", "nonsense", "date_last_updated"),
            ("no_choice_falls_back", "payments", None, "date_last_updated"),
            ("endpoint_without_date_range", "merchant_orders", "date_created", None),
        ]
    )
    def test_resolves_cursor(self, _name: str, endpoint: str, chosen: Optional[str], expected: Optional[str]) -> None:
        assert resolve_cursor_field(MERCADO_PAGO_ENDPOINTS[endpoint], chosen) == expected


class TestBuildRequestParams:
    def test_full_refresh_sorts_ascending_without_a_date_window(self) -> None:
        params = build_request_params(MERCADO_PAGO_ENDPOINTS["payments"], False, None, None)
        assert params == {"sort": "date_created", "criteria": "asc"}

    def test_incremental_sends_the_server_side_date_window(self) -> None:
        params = build_request_params(
            MERCADO_PAGO_ENDPOINTS["payments"], True, "date_last_updated", datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
        )
        assert params == {
            "sort": "date_last_updated",
            "criteria": "asc",
            "range": "date_last_updated",
            "begin_date": "2026-03-04T05:06:07.000Z",
            # `range` needs both bounds, so the open end is Mercado Pago's own "now" anchor.
            "end_date": "NOW",
        }

    def test_first_incremental_sync_has_no_window_but_sorts_on_the_cursor(self) -> None:
        params = build_request_params(MERCADO_PAGO_ENDPOINTS["payments"], True, "date_created", None)
        assert params == {"sort": "date_created", "criteria": "asc"}

    def test_full_refresh_endpoint_never_sends_a_window(self) -> None:
        params = build_request_params(
            MERCADO_PAGO_ENDPOINTS["merchant_orders"], True, "date_created", datetime(2026, 3, 4, tzinfo=UTC)
        )
        assert params == {}


class TestMercadoPagoSearchPaginator:
    def test_advances_by_rows_returned_and_stops_at_total(self) -> None:
        paginator = MercadoPagoSearchPaginator(limit=PAGE_SIZE, total_path="paging.total", offset_path="paging.offset")
        rows = [_payment(i) for i in range(PAGE_SIZE)]
        paginator.update_state(_json_response(_search_body(rows, total=60, offset=0)), data=rows)
        assert paginator.has_next_page is True
        assert paginator.offset == PAGE_SIZE

        tail = [_payment(i) for i in range(10)]
        paginator.update_state(_json_response(_search_body(tail, total=60, offset=PAGE_SIZE)), data=tail)
        assert paginator.has_next_page is False

    def test_short_page_from_a_server_side_limit_cap_keeps_paginating(self) -> None:
        # Asking for 50 and getting 30 back means the server capped the page, not that the walk is
        # over — stopping on a short page here would silently truncate the table.
        paginator = MercadoPagoSearchPaginator(limit=PAGE_SIZE, total_path="paging.total", offset_path="paging.offset")
        rows = [_payment(i) for i in range(30)]
        paginator.update_state(_json_response(_search_body(rows, total=45, offset=0)), data=rows)
        assert paginator.has_next_page is True
        assert paginator.offset == 30

    def test_server_reported_offset_wins_over_local_tracking(self) -> None:
        paginator = MercadoPagoSearchPaginator(limit=PAGE_SIZE, total_path="paging.total", offset_path="paging.offset")
        rows = [_payment(i) for i in range(5)]
        paginator.update_state(_json_response(_search_body(rows, total=999, offset=200)), data=rows)
        assert paginator.offset == 205

    def test_empty_page_stops(self) -> None:
        paginator = MercadoPagoSearchPaginator(limit=PAGE_SIZE, total_path="paging.total")
        paginator.update_state(_json_response(_search_body([], total=0, offset=0)), data=[])
        assert paginator.has_next_page is False

    def test_missing_total_keeps_walking(self) -> None:
        paginator = MercadoPagoSearchPaginator(limit=PAGE_SIZE, total_path="paging.total")
        rows = [_payment(i) for i in range(3)]
        paginator.update_state(_json_response(_search_body(rows)), data=rows)
        assert paginator.has_next_page is True
        assert paginator.offset == 3

    def test_resume_state_round_trip(self) -> None:
        paginator = MercadoPagoSearchPaginator(limit=PAGE_SIZE, total_path="paging.total", offset_path="paging.offset")
        rows = [_payment(i) for i in range(PAGE_SIZE)]
        paginator.update_state(_json_response(_search_body(rows, total=200, offset=0)), data=rows)
        state = paginator.get_resume_state()
        assert state == {"offset": PAGE_SIZE}

        resumed = MercadoPagoSearchPaginator(limit=PAGE_SIZE)
        assert state is not None
        resumed.set_resume_state(state)
        assert resumed.offset == PAGE_SIZE
        assert resumed.has_next_page is True

    def test_exhausted_paginator_has_no_resume_state(self) -> None:
        paginator = MercadoPagoSearchPaginator(limit=PAGE_SIZE, total_path="paging.total")
        paginator.update_state(_json_response(_search_body([], total=0)), data=[])
        assert paginator.get_resume_state() is None


class TestPipelineTransport:
    @patch(CLIENT_SESSION_PATCH)
    def test_payments_paginates_until_the_declared_total(self, MockSession: Any) -> None:
        session = MockSession.return_value
        page1 = [_payment(i) for i in range(PAGE_SIZE)]
        page2 = [_payment(i) for i in range(PAGE_SIZE, PAGE_SIZE + 10)]
        params = _wire(
            session,
            [
                _json_response(_search_body(page1, total=PAGE_SIZE + 10, offset=0)),
                _json_response(_search_body(page2, total=PAGE_SIZE + 10, offset=PAGE_SIZE)),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager, "payments"))

        assert rows == page1 + page2
        assert [(p["offset"], p["limit"]) for p in params] == [(0, PAGE_SIZE), (PAGE_SIZE, PAGE_SIZE)]
        assert params[0]["sort"] == "date_created"
        assert params[0]["criteria"] == "asc"
        # Checkpointed once, after the first page was yielded; the final page has nothing to resume into.
        manager.save_state.assert_called_once_with(MercadoPagoResumeConfig(offset=PAGE_SIZE))

    @patch(CLIENT_SESSION_PATCH)
    def test_payments_incremental_sends_the_date_window(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_json_response(_search_body([_payment(1)], total=1, offset=0))])

        rows = _rows(
            _source(
                _make_manager(),
                "payments",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 5, 6, 7, 8, 9, tzinfo=UTC),
                incremental_field="date_last_updated",
            )
        )

        assert rows == [_payment(1)]
        assert params[0]["range"] == "date_last_updated"
        assert params[0]["begin_date"] == "2026-05-06T07:08:09.000Z"
        assert params[0]["end_date"] == "NOW"

    @patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_the_saved_offset(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_json_response(_search_body([_payment(9)], total=101, offset=100))])

        rows = _rows(_source(_make_manager(MercadoPagoResumeConfig(offset=100)), "payments"))

        assert rows == [_payment(9)]
        assert params[0]["offset"] == 100

    @patch(CLIENT_SESSION_PATCH)
    def test_merchant_orders_read_elements_and_a_flat_total(self, MockSession: Any) -> None:
        session = MockSession.return_value
        orders = [{"id": 1}, {"id": 2}]
        params = _wire(session, [_json_response({"elements": orders, "total": 2, "next_offset": 2})])

        rows = _rows(_source(_make_manager(), "merchant_orders"))

        assert rows == orders
        assert session.send.call_count == 1
        # No incremental cursor and no documented sort enum, so nothing beyond paging is sent.
        assert params[0] == {"offset": 0, "limit": PAGE_SIZE}

    @patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_and_saves_no_state(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response(_search_body([], total=0, offset=0))])

        manager = _make_manager()
        assert _rows(_source(manager, "subscriptions")) == []
        manager.save_state.assert_not_called()

    @patch(CLIENT_SESSION_PATCH)
    def test_bearer_token_is_sent_on_every_page(self, MockSession: Any) -> None:
        session = MockSession.return_value
        session.headers = {}
        captured_auth: list[Any] = []

        def _prepare(request: Any) -> MagicMock:
            captured_auth.append(request.auth)
            prepared = MagicMock()
            prepared.url = request.url
            return prepared

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_json_response(_search_body([_payment(1)], total=1, offset=0))]

        _rows(_source(_make_manager(), "payments"))

        prepared = requests.Request(method="GET", url="https://api.mercadopago.com").prepare()
        captured_auth[0](prepared)
        assert prepared.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"

    @patch(CLIENT_SESSION_PATCH)
    def test_missing_access_token_fails_before_any_request(self, MockSession: Any) -> None:
        with pytest.raises(ValueError, match=MISSING_ACCESS_TOKEN_ERROR):
            _source(_make_manager(), "payments", access_token="")
        MockSession.return_value.send.assert_not_called()

    @parameterized.expand(
        [
            ("payments", ["id"], "date_created"),
            ("merchant_orders", ["id"], "date_created"),
            ("subscriptions", ["id"], "date_created"),
            ("subscription_plans", ["id"], "date_created"),
            ("authorized_payments", ["id"], "date_created"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str) -> None:
        response = _source(_make_manager(), endpoint)
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        # Every request sorts ascending, so the pipeline's watermark advances with the pages.
        assert response.sort_mode == "asc"


class TestValidateCredentials:
    @patch(PROBE_SESSION_PATCH)
    def test_valid_token(self, MockSession: Any) -> None:
        MockSession.return_value.get.return_value = _mock_response(200, _search_body([], total=0, offset=0))
        assert validate_credentials(ACCESS_TOKEN) == (True, None)

    @patch(PROBE_SESSION_PATCH)
    def test_unauthorized_reports_the_api_message(self, MockSession: Any) -> None:
        MockSession.return_value.get.return_value = _mock_response(401, {"message": "invalid access token"})
        assert validate_credentials(ACCESS_TOKEN) == (
            False,
            "invalid access token",
        )

    @patch(PROBE_SESSION_PATCH)
    def test_forbidden_is_accepted_at_source_create(self, MockSession: Any) -> None:
        # A restricted token may legitimately cover only some resources, so a scope failure must
        # not block connecting the source.
        MockSession.return_value.get.return_value = _mock_response(403, {"message": "forbidden"})
        assert validate_credentials(ACCESS_TOKEN) == (True, None)

    @patch(PROBE_SESSION_PATCH)
    def test_forbidden_fails_for_a_specific_schema(self, MockSession: Any) -> None:
        MockSession.return_value.get.return_value = _mock_response(403, {})
        is_valid, message = validate_credentials(ACCESS_TOKEN, schema_name="payments")
        assert is_valid is False
        assert message is not None and "payments" in message

    @parameterized.expand([(400,), (429,), (500,)])
    @patch(PROBE_SESSION_PATCH)
    def test_other_statuses_are_reported(self, status_code: int, MockSession: Any) -> None:
        MockSession.return_value.get.return_value = _mock_response(status_code, {})
        is_valid, message = validate_credentials(ACCESS_TOKEN)
        assert is_valid is False
        assert message == f"Mercado Pago returned HTTP {status_code}"

    @patch(PROBE_SESSION_PATCH)
    def test_connection_error_is_reported(self, MockSession: Any) -> None:
        MockSession.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        is_valid, message = validate_credentials(ACCESS_TOKEN)
        assert is_valid is False
        assert message is not None and message.startswith("Could not connect to Mercado Pago")

    def test_missing_access_token_is_rejected_without_a_probe(self) -> None:
        assert validate_credentials(None) == (False, MISSING_ACCESS_TOKEN_ERROR)
