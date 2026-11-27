import json
from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized
from requests import PreparedRequest, Response
from requests.structures import CaseInsensitiveDict

from products.warehouse_sources.sources.back_market._config import BackMarketSourceConfig
from products.warehouse_sources.sources.back_market.back_market import (
    BackMarketPaginator,
    BackMarketResumeConfig,
    BackMarketTokenAuth,
    _build_params,
    _format_timestamp,
    validate_credentials,
)
from products.warehouse_sources.sources.back_market.settings import BACK_MARKET_ENDPOINTS
from products.warehouse_sources.sources.back_market.source import BackMarketSource
from products.warehouse_sources.sources.sdk.testing import (
    RunStopped,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
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
    @parameterized.expand(
        [
            ("orders", "/ws/orders", "order_id"),
            ("care_folders", "/ws/sav", "id"),
            ("returns", "/ws/shipping/v1/returns", "shipmentId"),
            ("buyback_orders", "/ws/buyback/v1/orders", "orderPublicId"),
        ]
    )
    def test_paginates_until_next_is_falsy(self, endpoint: str, path: str, key: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _page("more", [{key: "1"}, {key: "2"}]),
                _page(None, [{key: "3"}]),
            ],
        )

        assert result.raised is None
        assert [row[key] for row in result.rows] == ["1", "2", "3"]
        assert result.params("page") == ["1", "2"]
        assert result.paths == [path, path]

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


class TestBackMarketAddedTables:
    @parameterized.expand(
        [
            (endpoint, field, param, watermark, expected, mode)
            for endpoint, field, param, watermark, expected in [
                (
                    "care_folders",
                    "date_modification",
                    "last_modification_date",
                    "2026-01-02T03:04:59.123+02:00",
                    "2026-01-02-01-03",
                ),
                (
                    "care_folders",
                    "date_modification",
                    "last_modification_date",
                    "2026-01-02T03:04:00+02:00",
                    "2026-01-02-01-03",
                ),
                (
                    "care_folders",
                    "date_modification",
                    "last_modification_date",
                    "2026-01-01T00:00:00Z",
                    "2025-12-31-23-59",
                ),
                ("returns", "dateCreation", "start_date", "2026-01-02T03:04:59.123+02:00", "2026-01-02T01:04:59+00:00"),
                (
                    "buyback_orders",
                    "modificationDate",
                    "modificationDate",
                    "2026-01-02T03:04:59.123+02:00",
                    "2026-01-02",
                ),
            ]
            for mode in ("incremental", "full_refresh", "first_sync")
        ]
    )
    def test_filters_every_page(
        self, endpoint: str, field: str, param: str, watermark: str, expected: str, mode: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [_page("more", [{field: "2026-01-02T01:05:00Z"}]), _page(None, [])],
            incremental_field=field,
            should_use_incremental_field=mode != "full_refresh",
            db_incremental_field_last_value=None if mode == "first_sync" else watermark,
        )

        assert result.raised is None
        assert len(result.rows) == 1
        assert result.params(param) == [expected if mode == "incremental" else None] * 2
        assert result.params("page") == ["1", "2"]
        assert result.response is not None
        assert result.response.sort_mode is None

    def test_competitors_use_listing_uuid_and_keep_each_market(self) -> None:
        listing_ids = [f"00000000-0000-4000-8000-{index:012d}" for index in range(1, 5)]
        competitors = [{"listing_id": "competitor-1", "market": market, "min_price": None} for market in ("FR", "DE")]
        result = _driver().run(
            "backbox_competitors",
            route(
                {
                    "/ws/listings": [
                        _page("more", [{"id": listing_ids[0], "listing_id": 101}, {"id": listing_ids[1]}]),
                        _page(None, [{"id": listing_ids[2]}, {"id": listing_ids[3]}]),
                    ],
                    f"/ws/backbox/v1/competitors/{listing_ids[0]}": [ScriptedResponse(json=competitors)],
                    f"/ws/backbox/v1/competitors/{listing_ids[1]}": [ScriptedResponse(json=[])],
                    f"/ws/backbox/v1/competitors/{listing_ids[2]}": [ScriptedResponse(status=404)],
                    f"/ws/backbox/v1/competitors/{listing_ids[3]}": [ScriptedResponse(json=competitors)],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {**competitor, "_listings_id": listing_id}
            for listing_id in (listing_ids[0], listing_ids[3])
            for competitor in competitors
        ]
        assert [request.param("page") for request in result.requests if request.path == "/ws/listings"] == ["1", "2"]
        assert all(request.param("page") is None for request in result.requests if "competitors" in request.path)
        assert result.response is not None
        assert result.response.primary_keys is not None
        assert len({tuple(row[key] for key in result.response.primary_keys) for row in result.rows}) == 4
        assert result.committed_states

    def test_competitors_resume_without_repeating_completed_children(self) -> None:
        listings = [{"id": f"00000000-0000-4000-8000-{index:012d}"} for index in (1, 2)]
        first_path = f"/ws/backbox/v1/competitors/{listings[0]['id']}"
        second_path = f"/ws/backbox/v1/competitors/{listings[1]['id']}"
        first = _driver().run(
            "backbox_competitors",
            route(
                {
                    "/ws/listings": [_page(None, listings)],
                    first_path: [ScriptedResponse(json=[{"listing_id": "competitor-1", "market": "FR"}])],
                    second_path: [ScriptedResponse(status=403)],
                }
            ),
        )
        assert first.raised is not None
        assert len(first.rows) == 1
        assert first.final_state is not None

        resumed = _driver().run(
            "backbox_competitors",
            route(
                {
                    "/ws/listings": [_page(None, listings)],
                    second_path: [ScriptedResponse(json=[{"listing_id": "competitor-2", "market": "FR"}])],
                }
            ),
            resume_state=first.final_state,
        )
        assert resumed.raised is None
        assert [row["listing_id"] for row in resumed.rows] == ["competitor-2"]
        assert resumed.paths == ["/ws/listings", second_path]

    @parameterized.expand([(404,), (200,)])
    def test_empty_competitors_commit_progress_before_parent_page_finishes(self, status: int) -> None:
        listings = [{"id": f"00000000-0000-4000-8000-{index:012d}"} for index in range(1, 9)]
        paths = [f"/ws/backbox/v1/competitors/{listing['id']}" for listing in listings]
        first = _driver().run(
            "backbox_competitors",
            [
                _page(None, listings),
                *[ScriptedResponse(status=status, json=[]) for _ in range(3)],
                RunStopped("worker shutdown"),
            ],
        )

        assert isinstance(first.raised, RunStopped)
        assert first.rows == []
        assert first.final_state is not None
        assert first.final_state.fanout_state["completed"] == [path.removeprefix("/ws") for path in paths[:3]]
        assert len(first.committed_states) == 3

        resumed = _driver().run(
            "backbox_competitors",
            [_page(None, listings), *[ScriptedResponse(status=status, json=[]) for _ in range(5)]],
            resume_state=first.final_state,
        )

        assert resumed.raised is None
        assert resumed.rows == []
        assert resumed.paths == ["/ws/listings", *paths[3:]]


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
