import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import PreparedRequest, Response
from requests.structures import CaseInsensitiveDict

from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.back_market import (
    BackMarketPaginator,
    BackMarketResumeConfig,
    BackMarketTokenAuth,
    _build_params,
    _format_timestamp,
    back_market_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.settings import BACK_MARKET_ENDPOINTS

# Both _client_config (main sync) and validate_credentials build their own tracked session
# (capture=False, since orders carry buyer PII) via make_tracked_session in the back_market module.
BACK_MARKET_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.back_market.back_market.make_tracked_session"
)


class TestBackMarketTokenAuth:
    def test_sets_literal_basic_header(self) -> None:
        auth = BackMarketTokenAuth(token="secret-token")
        request = PreparedRequest()
        request.headers = CaseInsensitiveDict()

        auth(request)

        assert request.headers["Authorization"] == "Basic secret-token"

    def test_secret_values_redacts_token(self) -> None:
        assert BackMarketTokenAuth(token="secret-token").secret_values() == ("secret-token",)

    def test_secret_values_empty_when_no_token(self) -> None:
        assert BackMarketTokenAuth(token=None).secret_values() == ()


def _response(next_value: Any, results: list[dict[str, Any]] | None = None) -> Response:
    body: dict[str, Any] = {"next": next_value, "results": results if results is not None else []}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


class TestBackMarketPaginator:
    @parameterized.expand(
        [
            ("url_string", "https://www.backmarket.com/ws/orders?page=2", True),
            ("boolean_true", True, True),
            ("null", None, False),
            ("empty_string", "", False),
            ("false", False, False),
        ]
    )
    def test_has_next_page_from_next_field(self, _name: str, next_value: Any, expected_has_next: bool) -> None:
        paginator = BackMarketPaginator()
        paginator.update_state(_response(next_value))
        assert paginator.has_next_page is expected_has_next

    def test_advances_page_number_when_next_is_truthy(self) -> None:
        paginator = BackMarketPaginator(base_page=1)
        paginator.update_state(_response("more"))
        assert paginator.page == 2
        paginator.update_state(_response(None))
        assert paginator.page == 2  # stops advancing once exhausted
        assert paginator.has_next_page is False

    def test_malformed_response_body_stops_pagination(self) -> None:
        paginator = BackMarketPaginator()
        resp = Response()
        resp.status_code = 200
        resp._content = b"not json"
        paginator.update_state(resp)
        assert paginator.has_next_page is False

    def test_resume_state_round_trips(self) -> None:
        paginator = BackMarketPaginator()
        paginator.update_state(_response("more"))
        state = paginator.get_resume_state()
        assert state == {"page": 2}

        resumed = BackMarketPaginator()
        resumed.set_resume_state(state or {})
        assert resumed.page == 2
        assert resumed.has_next_page is True

    def test_no_resume_state_once_exhausted(self) -> None:
        paginator = BackMarketPaginator()
        paginator.update_state(_response(None))
        assert paginator.get_resume_state() is None


class TestFormatTimestamp:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04 02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04 02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04 00:00:00"),
            ("string_passthrough", "2026-03-04 02:58:14", "2026-03-04 02:58:14"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_timestamp(value) == expected


class TestBuildParams:
    def test_incremental_endpoint_with_cursor_adds_chosen_field(self) -> None:
        params = _build_params(
            BACK_MARKET_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            incremental_field="date_modification",
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params == {"date_modification": "2026-03-04 02:58:14"}

    def test_incremental_endpoint_honors_the_other_chosen_field(self) -> None:
        params = _build_params(
            BACK_MARKET_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            incremental_field="date_creation",
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"date_creation": "2026-03-04 00:00:00"}

    def test_incremental_endpoint_without_cursor_omits_filter(self) -> None:
        params = _build_params(
            BACK_MARKET_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            incremental_field="date_modification",
            db_incremental_field_last_value=None,
        )
        assert params == {}

    def test_full_refresh_endpoint_never_filters(self) -> None:
        params = _build_params(
            BACK_MARKET_ENDPOINTS["listings"],
            should_use_incremental_field=True,
            incremental_field="date_modification",
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {}


def _make_manager(resume_state: BackMarketResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestBackMarketSourceOrders:
    @mock.patch(BACK_MARKET_SESSION_PATCH)
    def test_paginates_until_next_is_falsy(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response("more", [{"order_id": "1"}, {"order_id": "2"}]),
                _response(None, [{"order_id": "3"}]),
            ],
        )

        rows = _rows(back_market_source("token", "orders", 1, "job", _make_manager()))

        assert [r["order_id"] for r in rows] == ["1", "2", "3"]
        assert session.send.call_count == 2

    @mock.patch(BACK_MARKET_SESSION_PATCH)
    def test_auth_is_framework_token_auth_carrying_raw_token(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response(None, [{"order_id": "1"}])])

        _rows(back_market_source("secret", "orders", 1, "job", _make_manager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, BackMarketTokenAuth)
        assert auth.token == "secret"

    @mock.patch(BACK_MARKET_SESSION_PATCH)
    def test_incremental_field_selection_sets_matching_query_param(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response(None, [{"order_id": "1"}])])

        _rows(
            back_market_source(
                "token",
                "orders",
                1,
                "job",
                _make_manager(),
                should_use_incremental_field=True,
                incremental_field="date_creation",
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["date_creation"] == "2026-01-01 00:00:00"
        assert "date_modification" not in snapshots[0]["params"]

    @mock.patch(BACK_MARKET_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response(None, [{"order_id": "3"}])])

        _rows(back_market_source("token", "orders", 1, "job", _make_manager(BackMarketResumeConfig(next_page=3))))

        assert snapshots[0]["params"]["page"] == 3

    @mock.patch(BACK_MARKET_SESSION_PATCH)
    def test_saves_state_after_yielding_a_page_with_more_remaining(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("more", [{"order_id": "1"}]), _response(None, [{"order_id": "2"}])])
        manager = _make_manager()

        _rows(back_market_source("token", "orders", 1, "job", manager))

        manager.save_state.assert_called_once_with(BackMarketResumeConfig(next_page=2))

    @mock.patch(BACK_MARKET_SESSION_PATCH)
    def test_no_state_saved_once_exhausted(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, [{"order_id": "1"}])])
        manager = _make_manager()

        _rows(back_market_source("token", "orders", 1, "job", manager))

        manager.save_state.assert_not_called()


class TestBackMarketSourceListings:
    @mock.patch(BACK_MARKET_SESSION_PATCH)
    def test_full_refresh_ignores_incremental_flag(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response(None, [{"listing_id": "1"}])])

        rows = _rows(
            back_market_source(
                "token",
                "listings",
                1,
                "job",
                _make_manager(),
                should_use_incremental_field=True,
                incremental_field="date_modification",
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert [r["listing_id"] for r in rows] == ["1"]
        assert "date_modification" not in snapshots[0]["params"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True, 200),
            ("unauthorized", 401, False, 401),
            ("forbidden", 403, False, 403),
        ]
    )
    @mock.patch(BACK_MARKET_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status_code: int, expected_ok: bool, expected_status: int, MockSession
    ) -> None:
        session = MockSession.return_value
        response = mock.MagicMock()
        response.status_code = status_code
        session.get.return_value = response

        ok, status = validate_credentials("token")

        assert ok is expected_ok
        assert status == expected_status

    @mock.patch(BACK_MARKET_SESSION_PATCH)
    def test_transport_error_maps_to_not_validated(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.side_effect = ConnectionError("boom")

        ok, status = validate_credentials("token")

        assert ok is False
        assert status is None

    @mock.patch(BACK_MARKET_SESSION_PATCH)
    def test_sends_raw_token_in_basic_header(self, MockSession) -> None:
        session = MockSession.return_value
        response = mock.MagicMock()
        response.status_code = 200
        session.get.return_value = response

        validate_credentials("secret-token")

        _, kwargs = session.get.call_args
        assert kwargs["headers"]["Authorization"] == "Basic secret-token"


@pytest.mark.parametrize("endpoint_name", ["orders", "listings"])
def test_every_declared_endpoint_has_a_resource(endpoint_name: str) -> None:
    assert endpoint_name in BACK_MARKET_ENDPOINTS
