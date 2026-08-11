import json
import logging
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.settings import (
    MAX_PAGES,
    PER_PAGE,
    TOKEN_URL,
)
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
    trustpilot_source,
    validate_credentials,
)

# resolve_business_unit_id, mint_access_token and the sync client all build their tracked
# session in the trustpilot module.
TRUSTPILOT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.trustpilot.make_tracked_session"
)
RESOLVE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.trustpilot.resolve_business_unit_id"
)

BUSINESS_UNIT_ID = "507f191e810c19729de860ea"


def _response(payload: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(payload).encode()
    return resp


def _reviews_response(items: list[dict[str, Any]], key: str = "reviews") -> Response:
    return _response({key: items, "links": []})


def _make_manager(resume_state: TrustpilotResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    # request.params is one dict mutated in place across pages, so snapshot a copy at send time.
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "service_reviews", **kwargs: Any):
    return trustpilot_source(
        api_key="key",
        api_secret="secret",
        business_unit="example.com",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


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
    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_domain_resolves_via_find(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.return_value = _response({"id": BUSINESS_UNIT_ID, "displayName": "Example"})

        assert resolve_business_unit_id("key", "example.com") == BUSINESS_UNIT_ID
        args, kwargs = session.get.call_args
        assert args[0].endswith("/business-units/find")
        assert kwargs["params"] == {"name": "example.com"}
        assert kwargs["headers"] == {"apikey": "key"}

    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_www_domain_falls_back_to_bare_domain(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.side_effect = [
            _response({"details": "not found"}, status_code=404),
            _response({"id": BUSINESS_UNIT_ID}),
        ]

        assert resolve_business_unit_id("key", "www.example.com") == BUSINESS_UNIT_ID
        names = [call.kwargs["params"]["name"] for call in session.get.call_args_list]
        assert names == ["www.example.com", "example.com"]

    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_unknown_domain_raises_business_unit_error(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.return_value = _response({"details": "not found"}, status_code=404)

        with pytest.raises(TrustpilotBusinessUnitError):
            resolve_business_unit_id("key", "example.com")

    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_lookup_response_without_id_fails_loud(self, MockSession) -> None:
        # A 200 without an id is a broken response contract; it must not read as "not found",
        # which would tell the user to fix a business unit value that is actually fine.
        session = MockSession.return_value
        session.get.return_value = _response({"displayName": "Example"})

        with pytest.raises(TrustpilotBusinessUnitError, match="unexpected"):
            resolve_business_unit_id("key", "example.com")

    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_rejected_api_key_raises_auth_error(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.return_value = _response({"details": "unauthorized"}, status_code=401)

        with pytest.raises(TrustpilotAuthError):
            resolve_business_unit_id("key", "example.com")

    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_raw_id_verified_via_business_unit_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.return_value = _response({"id": BUSINESS_UNIT_ID})

        assert resolve_business_unit_id("key", BUSINESS_UNIT_ID) == BUSINESS_UNIT_ID
        args, _kwargs = session.get.call_args
        assert args[0].endswith(f"/business-units/{BUSINESS_UNIT_ID}")

    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_unknown_raw_id_raises_business_unit_error(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.return_value = _response({"details": "not found"}, status_code=404)

        with pytest.raises(TrustpilotBusinessUnitError):
            resolve_business_unit_id("key", BUSINESS_UNIT_ID)


class TestMintAccessToken:
    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_returns_token_on_success(self, MockSession) -> None:
        session = MockSession.return_value
        session.post.return_value = _response({"access_token": "tok", "expires_in": "359999"})

        assert mint_access_token("key", "secret") == "tok"
        _args, kwargs = session.post.call_args
        assert kwargs["auth"] == ("key", "secret")
        assert kwargs["data"] == {"grant_type": "client_credentials"}

    @parameterized.expand(
        [
            ("rejected", _response({"reason": "unauthorized"}, status_code=401)),
            ("no_token_in_body", _response({"unexpected": "shape"})),
        ]
    )
    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_failures_raise_auth_error(self, _name: str, response: Response, MockSession) -> None:
        session = MockSession.return_value
        session.post.return_value = response

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
    @mock.patch(RESOLVE_PATCH, return_value=BUSINESS_UNIT_ID)
    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_pages_until_empty_page(self, MockSession, _mock_resolve) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _reviews_response([{"id": "r1"}, {"id": "r2"}]),
                _reviews_response([{"id": "r3"}]),
                _reviews_response([]),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["id"] for r in rows] == ["r1", "r2", "r3"]
        assert params[0]["page"] == 1
        assert params[0]["perPage"] == PER_PAGE
        assert params[0]["orderBy"] == "createdat.asc"
        assert params[1]["page"] == 2
        assert params[2]["page"] == 3

    @mock.patch(RESOLVE_PATCH, return_value=BUSINESS_UNIT_ID)
    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_checkpoints_next_page_with_query_window(self, MockSession, _mock_resolve) -> None:
        session = MockSession.return_value
        _wire(session, [_reviews_response([{"id": "r1"}]), _reviews_response([])])

        manager = _make_manager()
        _rows(
            _source(
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 2, 1, tzinfo=UTC),
            )
        )

        manager.save_state.assert_called_once_with(
            TrustpilotResumeConfig(page=2, start_date_time="2026-02-01T00:00:00")
        )

    @mock.patch(RESOLVE_PATCH, return_value=BUSINESS_UNIT_ID)
    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_resume_reissues_saved_query_window(self, MockSession, _mock_resolve) -> None:
        # A resumed run must re-issue the interrupted run's startDateTime: the watermark advanced
        # per batch mid-run, so re-deriving it would shift the query window and page 5 would point
        # at different rows.
        session = MockSession.return_value
        params = _wire(session, [_reviews_response([{"id": "r9"}]), _reviews_response([])])

        manager = _make_manager(TrustpilotResumeConfig(page=5, start_date_time="2026-01-01T00:00:00"))
        rows = _rows(
            _source(
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 2, 1, tzinfo=UTC),
            )
        )

        assert [r["id"] for r in rows] == ["r9"]
        assert params[0]["page"] == 5
        assert params[0]["startDateTime"] == "2026-01-01T00:00:00"

    @mock.patch(RESOLVE_PATCH, return_value=BUSINESS_UNIT_ID)
    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_incremental_filter_added_to_request(self, MockSession, _mock_resolve) -> None:
        session = MockSession.return_value
        params = _wire(session, [_reviews_response([{"id": "r1"}]), _reviews_response([])])

        _rows(
            _source(
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )
        assert params[0]["startDateTime"] == "2026-03-04T02:58:14"

    @mock.patch(RESOLVE_PATCH, return_value=BUSINESS_UNIT_ID)
    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_full_refresh_endpoint_never_filters(self, MockSession, _mock_resolve) -> None:
        # product_reviews has no server-side time filter; a cursor value must not leak into the request.
        session = MockSession.return_value
        params = _wire(
            session,
            [_reviews_response([{"id": "p1"}], key="productReviews"), _reviews_response([], key="productReviews")],
        )

        rows = _rows(
            _source(
                _make_manager(),
                endpoint="product_reviews",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )
        assert [r["id"] for r in rows] == ["p1"]
        assert "startDateTime" not in params[0]
        assert "orderBy" not in params[0]

    @mock.patch(RESOLVE_PATCH, return_value=BUSINESS_UNIT_ID)
    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_business_unit_returns_single_row(self, MockSession, _mock_resolve) -> None:
        session = MockSession.return_value
        params = _wire(
            session, [_response({"id": BUSINESS_UNIT_ID, "displayName": "Example", "score": {"trustScore": 4.6}})]
        )

        manager = _make_manager()
        rows = _rows(_source(manager, endpoint="business_unit"))

        assert len(rows) == 1
        assert rows[0]["id"] == BUSINESS_UNIT_ID
        assert "perPage" not in params[0]
        assert "page" not in params[0]
        manager.save_state.assert_not_called()

    @mock.patch(RESOLVE_PATCH, return_value=BUSINESS_UNIT_ID)
    @mock.patch(TRUSTPILOT_SESSION_PATCH)
    def test_no_checkpoint_after_final_page(self, MockSession, _mock_resolve) -> None:
        session = MockSession.return_value
        _wire(session, [_reviews_response([])])

        manager = _make_manager()
        assert _rows(_source(manager)) == []
        manager.save_state.assert_not_called()


class TestPaginatorQueryCap:
    def test_stops_and_warns_at_query_cap(self, caplog: pytest.LogCaptureFixture) -> None:
        paginator = TrustpilotPaginator()
        paginator.page = MAX_PAGES

        with caplog.at_level(logging.WARNING):
            paginator.update_state(mock.MagicMock(), data=[{"id": "r1"}])

        assert paginator.has_next_page is False
        assert any("query cap" in record.message for record in caplog.records)

    def test_empty_page_stop_does_not_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        paginator = TrustpilotPaginator()

        with caplog.at_level(logging.WARNING):
            paginator.update_state(mock.MagicMock(), data=[])

        assert paginator.has_next_page is False
        assert not caplog.records
