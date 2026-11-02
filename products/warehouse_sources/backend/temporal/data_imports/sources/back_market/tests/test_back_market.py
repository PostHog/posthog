import json
from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized
from requests import PreparedRequest, Response
from requests.structures import CaseInsensitiveDict

from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.back_market import (
    BackMarketPaginator,
    BackMarketResumeConfig,
    BackMarketTokenAuth,
    _build_params,
    _format_timestamp,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.settings import BACK_MARKET_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.source import BackMarketSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.backmarket import (
    BackMarketSourceConfig,
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

    def test_malformed_response_body_stops_pagination(self) -> None:
        paginator = BackMarketPaginator()
        resp = Response()
        resp.status_code = 200
        resp._content = b"not json"
        paginator.update_state(resp)
        assert paginator.has_next_page is False


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
    def test_full_refresh_endpoint_never_filters(self) -> None:
        params = _build_params(
            BACK_MARKET_ENDPOINTS["listings"],
            should_use_incremental_field=True,
            incremental_field="date_modification",
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {}


def _driver() -> SourceDriver:
    return SourceDriver(BackMarketSource(), BackMarketSourceConfig(api_token="token"))


def _page(next_value: Any, results: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"next": next_value, "results": results})


class TestBackMarketSourceOrders:
    def test_paginates_until_next_is_falsy(self) -> None:
        result = _driver().run(
            "orders",
            [
                _page("more", [{"order_id": "1"}, {"order_id": "2"}]),
                _page(None, [{"order_id": "3"}]),
            ],
        )

        assert result.raised is None
        assert [row["order_id"] for row in result.rows] == ["1", "2", "3"]
        assert result.params("page") == ["1", "2"]
        assert result.paths == ["/ws/orders", "/ws/orders"]

    def test_incremental_field_selection_sets_matching_query_param(self) -> None:
        result = _driver().run(
            "orders",
            [_page(None, [{"order_id": "1"}])],
            incremental_field="date_creation",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("date_creation") == "2026-01-01 00:00:00"
        assert result.requests[0].param("date_modification") is None

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "orders", [_page(None, [{"order_id": "3"}])], resume_state=BackMarketResumeConfig(next_page=3)
        )

        assert result.raised is None
        assert result.params("page") == ["3"]

    def test_saves_state_after_yielding_a_page_with_more_remaining(self) -> None:
        result = _driver().run("orders", [_page("more", [{"order_id": "1"}]), _page(None, [{"order_id": "2"}])])

        assert result.raised is None
        assert result.saved_states == [BackMarketResumeConfig(next_page=2)]
        assert result.committed_states == [BackMarketResumeConfig(next_page=2)]


class TestBackMarketSourceListings:
    def test_full_refresh_ignores_incremental_flag(self) -> None:
        result = _driver().run(
            "listings",
            [_page(None, [{"listing_id": "1"}])],
            incremental_field="date_modification",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["listing_id"] for row in result.rows] == ["1"]
        assert result.requests[0].param("date_modification") is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True, 200),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool, expected_status: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            ok, status = validate_credentials("token")

        assert ok is expected_ok
        assert status == expected_status
        assert network.requests_log[0].path == "/ws/orders"
        assert network.requests_log[0].headers["authorization"] == "Basic token"
