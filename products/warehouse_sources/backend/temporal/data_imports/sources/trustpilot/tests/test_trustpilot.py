import base64
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trustpilot import (
    TrustPilotSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.settings import MAX_PAGES, TOKEN_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.source import TrustPilotSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.trustpilot import (
    TrustpilotAuthError,
    TrustpilotBusinessUnitError,
    TrustpilotPaginator,
    TrustpilotResumeConfig,
    _build_auth,
    _format_start_datetime,
    mint_access_token,
    normalize_business_unit,
    resolve_business_unit_id,
    validate_credentials,
)

RESOLVE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.trustpilot.resolve_business_unit_id"
)

BUSINESS_UNIT_ID = "507f191e810c19729de860ea"


def _json(payload: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=payload)


def _reviews_response(items: list[dict[str, Any]], key: str = "reviews") -> dict[str, Any]:
    return {key: items, "links": []}


def _serve(*review_pages: dict[str, Any]) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer the business unit lookup and the token mint, then each review page in order."""
    pages = list(review_pages)

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/business-units/find"):
            return _json({"id": BUSINESS_UNIT_ID})
        if request.path.endswith("/accesstoken"):
            return _json({"access_token": "tok", "expires_in": 3600})
        if not pages:
            raise UnexpectedRequest(f"no page left for {request.url}")
        return _json(pages.pop(0))

    return respond


def _run(
    script: Callable[[RecordedRequest], ScriptedResponse],
    endpoint: str = "service_reviews",
    resume_state: TrustpilotResumeConfig | None = None,
    **kwargs: Any,
) -> DriveResult:
    config = TrustPilotSourceConfig(api_key="key", api_secret="secret", business_unit="example.com")
    return SourceDriver(TrustPilotSource(), config).run(endpoint, script, resume_state=resume_state, **kwargs)


def _review_requests(result: DriveResult) -> list[RecordedRequest]:
    return [request for request in result.requests if request.path.endswith(("/reviews", f"/{BUSINESS_UNIT_ID}"))]


class TestNormalizeBusinessUnit:
    @parameterized.expand(
        [
            ("bare_domain", "example.com", "example.com"),
            ("https_url", "https://example.com/", "example.com"),
            ("url_with_path", "https://example.com/some/page", "example.com"),
            ("www_kept", "www.example.com", "www.example.com"),
            ("uppercase_lowered", "Example.COM", "example.com"),
            ("whitespace", "  example.com  ", "example.com"),
            ("review_page_url", "https://www.trustpilot.com/review/example.com", "example.com"),
            ("review_page_url_with_query", "https://trustpilot.com/review/example.com?languages=all", "example.com"),
            ("raw_business_unit_id", BUSINESS_UNIT_ID, BUSINESS_UNIT_ID),
        ]
    )
    def test_valid_values(self, _name: str, value: str, expected: str) -> None:
        assert normalize_business_unit(value) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("space_inside", "exa mple.com"),
            ("userinfo_injection", "example.com@evil.com"),
            ("query_injection", "example.com?apikey=x"),
            ("leading_hyphen", "-example.com"),
            ("underscore", "exa_mple.com"),
        ]
    )
    def test_invalid_values_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_business_unit(value)


class TestFormatStartDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            (
                "non_utc_datetime",
                datetime(2026, 3, 4, 3, 58, 14, tzinfo=timezone(timedelta(hours=1))),
                "2026-03-04T02:58:14",
            ),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
            ("string_passthrough", "2026-03-04T02:58:14", "2026-03-04T02:58:14"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_start_datetime(value)
        assert result == expected
        assert "+00:00" not in result
        assert not result.endswith("Z")


class TestBuildAuth:
    def test_public_endpoint_uses_apikey_header(self) -> None:
        auth = _build_auth("key", "secret", requires_oauth=False)
        assert auth == {"type": "api_key", "name": "apikey", "location": "header", "api_key": "key"}

    def test_private_endpoint_uses_client_credentials_with_basic_auth(self) -> None:
        auth = _build_auth("key", "secret", requires_oauth=True)
        # client_auth_method must stay "basic": Trustpilot's token endpoint takes the key/secret
        # as HTTP Basic.
        assert auth == {
            "type": "oauth2",
            "token_url": TOKEN_URL,
            "client_id": "key",
            "client_secret": "secret",
            "grant_type": "client_credentials",
            "client_auth_method": "basic",
        }


class TestResolveBusinessUnit:
    def test_www_domain_falls_back_to_bare_domain(self) -> None:
        with scripted_network(
            [_json({"details": "not found"}, status=404), _json({"id": BUSINESS_UNIT_ID})]
        ) as network:
            assert resolve_business_unit_id("key", "www.example.com") == BUSINESS_UNIT_ID

        assert [request.param("name") for request in network.requests_log] == ["www.example.com", "example.com"]

    def test_unknown_domain_raises_business_unit_error(self) -> None:
        with scripted_network([_json({"details": "not found"}, status=404)]):
            with pytest.raises(TrustpilotBusinessUnitError):
                resolve_business_unit_id("key", "example.com")

    def test_lookup_response_without_id_fails_loud(self) -> None:
        # A 200 without an id is a broken response contract; it must not read as "not found",
        # which would tell the user to fix a business unit value that is actually fine.
        with scripted_network([_json({"displayName": "Example"})]):
            with pytest.raises(TrustpilotBusinessUnitError, match="unexpected"):
                resolve_business_unit_id("key", "example.com")

    def test_rejected_api_key_raises_auth_error(self) -> None:
        with scripted_network([_json({"details": "unauthorized"}, status=401)]):
            with pytest.raises(TrustpilotAuthError):
                resolve_business_unit_id("key", "example.com")

    def test_raw_id_verified_via_business_unit_endpoint(self) -> None:
        with scripted_network([_json({"id": BUSINESS_UNIT_ID})]) as network:
            assert resolve_business_unit_id("key", BUSINESS_UNIT_ID) == BUSINESS_UNIT_ID

        assert network.requests_log[0].path.endswith(f"/business-units/{BUSINESS_UNIT_ID}")

    def test_unknown_raw_id_raises_business_unit_error(self) -> None:
        with scripted_network([_json({"details": "not found"}, status=404)]):
            with pytest.raises(TrustpilotBusinessUnitError):
                resolve_business_unit_id("key", BUSINESS_UNIT_ID)


class TestMintAccessToken:
    def test_returns_token_on_success(self) -> None:
        with scripted_network([_json({"access_token": "tok", "expires_in": "359999"})]) as network:
            assert mint_access_token("key", "secret") == "tok"

        request = network.requests_log[0]
        assert request.origin + request.path == TOKEN_URL
        assert request.headers["authorization"] == "Basic " + base64.b64encode(b"key:secret").decode()
        assert request.body == b"grant_type=client_credentials"

    @parameterized.expand(
        [
            ("rejected", _json({"reason": "unauthorized"}, status=401)),
            ("no_token_in_body", _json({"unexpected": "shape"})),
        ]
    )
    def test_failures_raise_auth_error(self, _name: str, response: ScriptedResponse) -> None:
        with scripted_network([response]):
            with pytest.raises(TrustpilotAuthError):
                mint_access_token("key", "secret")


class TestValidateCredentials:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.trustpilot.mint_access_token"
    )
    @mock.patch(RESOLVE_PATCH)
    def test_valid_credentials(self, mock_resolve, mock_mint) -> None:
        mock_resolve.return_value = BUSINESS_UNIT_ID
        mock_mint.return_value = "tok"

        assert validate_credentials("key", "secret", "example.com") == (True, None)

    @parameterized.expand(
        [
            ("bad_business_unit", TrustpilotBusinessUnitError("No Trustpilot business unit found for 'example.com'.")),
            ("malformed_input", ValueError("Invalid Trustpilot business unit: 'exa mple'.")),
            ("bad_key", TrustpilotAuthError("Trustpilot rejected the API key (HTTP 401).")),
        ]
    )
    @mock.patch(RESOLVE_PATCH)
    def test_resolution_failures_surface_message(self, _name: str, error: Exception, mock_resolve) -> None:
        mock_resolve.side_effect = error

        ok, message = validate_credentials("key", "secret", "example.com")
        assert ok is False
        assert str(error) in (message or "")

    @mock.patch(RESOLVE_PATCH)
    def test_transport_errors_never_raise(self, mock_resolve) -> None:
        mock_resolve.side_effect = ConnectionError("boom")

        ok, message = validate_credentials("key", "secret", "example.com")
        assert ok is False
        assert "Could not connect to Trustpilot" in (message or "")


class TestPagination:
    def test_checkpoints_next_page_with_query_window(self) -> None:
        result = _run(
            _serve(_reviews_response([{"id": "r1"}]), _reviews_response([])),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert result.saved_states == [TrustpilotResumeConfig(page=2, start_date_time="2026-02-01T00:00:00")]

    def test_resume_reissues_saved_query_window(self) -> None:
        # A resumed run must re-issue the interrupted run's startDateTime: the watermark advanced
        # per batch mid-run, so re-deriving it would shift the query window and page 5 would point
        # at different rows.
        result = _run(
            _serve(_reviews_response([{"id": "r9"}]), _reviews_response([])),
            resume_state=TrustpilotResumeConfig(page=5, start_date_time="2026-01-01T00:00:00"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert [r["id"] for r in result.rows] == ["r9"]
        first = _review_requests(result)[0]
        assert first.param("page") == "5"
        assert first.param("startDateTime") == "2026-01-01T00:00:00"

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # product_reviews has no server-side time filter; a cursor value must not leak into the request.
        result = _run(
            _serve(
                _reviews_response([{"id": "p1"}], key="productReviews"),
                _reviews_response([], key="productReviews"),
            ),
            endpoint="product_reviews",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert [r["id"] for r in result.rows] == ["p1"]
        first = _review_requests(result)[0]
        assert first.param("startDateTime") is None
        assert first.param("orderBy") is None

    @parameterized.expand(
        [
            (
                "product_review_summaries",
                f"/v1/private/product-reviews/business-units/{BUSINESS_UNIT_ID}/summaries",
                "summaries",
                "sku",
                "100",
                {},
            ),
            (
                "catalog_products",
                f"/v1/private/business-units/{BUSINESS_UNIT_ID}/catalog/products",
                "products",
                "productId",
                "1000",
                {
                    "sortBy": "createdAt",
                    "sortOrder": "asc",
                    "returnAllLocales": "true",
                    "returnAllMarkets": "true",
                    "includeMatchingProductCount": "false",
                },
            ),
            # The locations endpoint documents only `page`, so no perPage is sent.
            ("locations", f"/v1/private/business-units/{BUSINESS_UNIT_ID}/locations", "locations", "id", None, {}),
        ]
    )
    def test_list_endpoint_walks_pages_with_documented_params(
        self,
        endpoint: str,
        expected_path: str,
        key: str,
        id_field: str,
        expected_per_page: str | None,
        expected_params: dict[str, str],
    ) -> None:
        result = _run(
            _serve(
                _reviews_response([{id_field: "a"}], key=key),
                _reviews_response([{id_field: "b"}], key=key),
                _reviews_response([], key=key),
            ),
            endpoint=endpoint,
        )

        assert [r[id_field] for r in result.rows] == ["a", "b"]
        requests = [r for r in result.requests if r.path == expected_path]
        assert [r.param("page") for r in requests] == ["1", "2", "3"]
        assert requests[0].param("perPage") == expected_per_page
        for name, value in expected_params.items():
            assert requests[0].param(name) == value


class TestProductReviewConversations:
    def test_fetches_only_referenced_conversations_and_skips_missing_ones(self) -> None:
        reviews: list[dict[str, Any]] = [
            {"id": "r1", "conversationId": "c1"},
            {"id": "r2", "conversationId": None},
            {"id": "r3"},
            {"id": "r4", "conversationId": "c-gone"},
        ]

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/business-units/find"):
                return _json({"id": BUSINESS_UNIT_ID})
            if request.path.endswith("/accesstoken"):
                return _json({"access_token": "tok", "expires_in": 3600})
            if request.path.endswith("/reviews"):
                page = request.param("page")
                return _json(_reviews_response(reviews if page == "1" else [], key="productReviews"))
            if request.path.endswith("/conversations/c1"):
                return _json({"id": "c1", "sourceId": "r1", "comments": [{"commentId": "m1", "content": "Thanks"}]})
            if request.path.endswith("/conversations/c-gone"):
                return _json({"details": "not found"}, status=404)
            raise UnexpectedRequest(f"unexpected request {request.url}")

        result = _run(respond, endpoint="product_review_conversations")

        assert [r["id"] for r in result.rows] == ["c1"]
        conversation_paths = [r.path for r in result.requests if "/conversations/" in r.path]
        assert conversation_paths == ["/v1/private/conversations/c1", "/v1/private/conversations/c-gone"]
        review_request = next(r for r in result.requests if r.path.endswith("/reviews"))
        assert review_request.path == f"/v1/private/product-reviews/business-units/{BUSINESS_UNIT_ID}/reviews"
        assert review_request.param("perPage") == "100"


class TestPaginatorQueryCap:
    @pytest.mark.parametrize(
        "maximum_page, expect_next",
        [
            pytest.param(MAX_PAGES, False, id="review_endpoint_capped"),
            # Catalog, locations and summaries document no record cap, so they page past it.
            pytest.param(None, True, id="uncapped_endpoint"),
        ],
    )
    def test_query_cap(self, maximum_page: int | None, expect_next: bool, caplog: pytest.LogCaptureFixture) -> None:
        paginator = TrustpilotPaginator(maximum_page)
        paginator.page = MAX_PAGES

        with caplog.at_level(logging.WARNING):
            paginator.update_state(mock.MagicMock(), data=[{"id": "r1"}])

        assert paginator.has_next_page is expect_next
        assert any("query cap" in record.message for record in caplog.records) is not expect_next
