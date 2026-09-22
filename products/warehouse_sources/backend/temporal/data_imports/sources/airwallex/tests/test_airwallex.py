import json
from datetime import UTC, datetime, timedelta
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import PreparedRequest, Response
from requests.structures import CaseInsensitiveDict

from products.warehouse_sources.backend.temporal.data_imports.sources.airwallex.airwallex import (
    AIRWALLEX_DEMO_BASE_URL,
    AIRWALLEX_LIVE_BASE_URL,
    DEFAULT_TOKEN_LIFETIME_SECONDS,
    MAX_PAGE_NUM,
    AirwallexAuth,
    AirwallexAuthError,
    AirwallexPageNumberPaginator,
    AirwallexResumeConfig,
    _to_iso8601,
    _token_lifetime_seconds,
    airwallex_source,
    base_url_for,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.airwallex.settings import AIRWALLEX_ENDPOINTS

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
AIRWALLEX_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.airwallex.airwallex.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None,
    *,
    has_more: bool | None = None,
    page_after: str | None = None,
    drop_items: bool = False,
) -> Response:
    body: dict[str, Any] = {}
    if not drop_items:
        body["items"] = items or []
    if has_more is not None:
        body["has_more"] = has_more
    if page_after is not None:
        body["page_after"] = page_after
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _login_response(token: str = "tok", expires_at: str | None = None) -> Response:
    resp = Response()
    resp.status_code = 201
    body: dict[str, Any] = {"token": token}
    if expires_at is not None:
        body["expires_at"] = expires_at
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: AirwallexResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return airwallex_source(
        client_id="cid",
        api_key="key",
        environment="live",
        api_version="2026-07-17",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestAirwallexAuth:
    @mock.patch(AIRWALLEX_SESSION_PATCH)
    def test_login_sends_the_credential_headers_and_sets_a_bearer(self, MockSession) -> None:
        session = MockSession.return_value
        session.post.return_value = _login_response("minted")
        auth = AirwallexAuth("cid", "key", AIRWALLEX_LIVE_BASE_URL)

        request = PreparedRequest()
        request.headers = CaseInsensitiveDict()
        auth(request)

        headers = session.post.call_args.kwargs["headers"]
        assert headers["x-client-id"] == "cid"
        assert headers["x-api-key"] == "key"
        assert request.headers["Authorization"] == "Bearer minted"

    @mock.patch(AIRWALLEX_SESSION_PATCH)
    def test_login_never_follows_a_redirect(self, MockSession) -> None:
        # The login call carries the API key in a custom header, which requests would replay to a
        # redirect target.
        session = MockSession.return_value
        session.post.return_value = _login_response()

        AirwallexAuth("cid", "key", AIRWALLEX_LIVE_BASE_URL)._get_token()

        assert session.post.call_args.kwargs["allow_redirects"] is False

    @mock.patch(AIRWALLEX_SESSION_PATCH)
    def test_token_is_reused_until_it_nears_expiry(self, MockSession) -> None:
        session = MockSession.return_value
        far_future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        session.post.return_value = _login_response("minted", far_future)
        auth = AirwallexAuth("cid", "key", AIRWALLEX_LIVE_BASE_URL)

        auth._get_token()
        auth._get_token()

        assert session.post.call_count == 1

    @mock.patch(AIRWALLEX_SESSION_PATCH)
    def test_missing_token_in_a_successful_login_raises(self, MockSession) -> None:
        session = MockSession.return_value
        session.post.return_value = _login_response(token="")

        try:
            AirwallexAuth("cid", "key", AIRWALLEX_LIVE_BASE_URL)._get_token()
        except AirwallexAuthError:
            return
        raise AssertionError("expected AirwallexAuthError")

    @mock.patch(AIRWALLEX_SESSION_PATCH)
    def test_secret_values_cover_the_key_and_the_minted_token(self, MockSession) -> None:
        # Both must be redacted from logged URLs, headers, sampled bodies, and raised errors.
        session = MockSession.return_value
        session.post.return_value = _login_response("minted")
        auth = AirwallexAuth("cid", "key", AIRWALLEX_LIVE_BASE_URL)

        assert auth.secret_values() == ("key",)
        auth._get_token()
        assert set(auth.secret_values()) == {"key", "minted"}

    @parameterized.expand(
        [
            ("missing", None, DEFAULT_TOKEN_LIFETIME_SECONDS),
            ("unparseable", "not-a-date", DEFAULT_TOKEN_LIFETIME_SECONDS),
            ("already_expired", "2020-01-01T00:00:00+0000", DEFAULT_TOKEN_LIFETIME_SECONDS),
        ]
    )
    def test_token_lifetime_falls_back_rather_than_going_negative(
        self, _name: str, expires_at: Any, expected: float
    ) -> None:
        # A negative lifetime would re-mint a token on every single request.
        assert _token_lifetime_seconds(expires_at) == expected

    def test_token_lifetime_reads_the_airwallex_offset_format(self) -> None:
        # Airwallex stamps the offset without a colon (+0000).
        expires_at = (datetime.now(UTC) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S+0000")

        assert 25 * 60 < _token_lifetime_seconds(expires_at) <= 30 * 60


class TestAirwallexTransport:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 1, 1, 12, 30, 0, tzinfo=UTC), "2021-01-01T12:30:00Z"),
            ("naive_datetime", datetime(2021, 1, 1, 12, 30, 0), "2021-01-01T12:30:00Z"),
            ("iso_string_z", "2021-01-01T12:30:00Z", "2021-01-01T12:30:00Z"),
            ("epoch_seconds", 1609504200, "2021-01-01T12:30:00Z"),
            ("none", None, None),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_to_iso8601(self, _name: str, value: Any, expected: str | None) -> None:
        # The from_* filters take an ISO8601 instant; another shape is rejected or ignored.
        assert _to_iso8601(value) == expected

    @parameterized.expand([("live", AIRWALLEX_LIVE_BASE_URL), ("demo", AIRWALLEX_DEMO_BASE_URL)])
    def test_base_url_for_environment(self, environment: str, expected: str) -> None:
        assert base_url_for(environment) == expected

    @parameterized.expand(
        [
            ("FinancialTransactions", "from_created_at"),
            ("Settlements", "from_settled_at"),
            ("Beneficiaries", "from_date"),
            ("Invoices", "from_created_at"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_uses_the_endpoints_own_filter_name(self, endpoint: str, param: str, MockSession) -> None:
        # Airwallex names this filter differently per endpoint, and sends 200 while ignoring a name
        # it does not know, so a wrong name silently full-scans every run.
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}], has_more=False)])

        _rows(
            _source(
                endpoint,
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
            )
        )

        assert params[0][param] == "2021-01-01T00:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sends_no_time_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}], has_more=False)])

        _rows(
            _source(
                "FinancialTransactions",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
            )
        )

        assert "from_created_at" not in params[0]

    @parameterized.expand([("PaymentIntents",), ("Customers",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_drops_client_secret(self, endpoint: str, MockSession) -> None:
        # A still-valid client_secret authorizes a browser/app against Airwallex; it must never be
        # persisted to the warehouse.
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1", "client_secret": "live_secret"}], has_more=False)])

        rows = _rows(_source(endpoint, _make_manager()))

        assert rows == [{"id": "1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_page_number_walk_stops_on_has_more_false(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": "1"}], has_more=True),
                _response([{"id": "2"}], has_more=False),
            ],
        )

        rows = _rows(_source("FinancialTransactions", _make_manager()))

        assert [row["id"] for row in rows] == ["1", "2"]
        # Zero-based, and stops without paying for a third request.
        assert [p["page_num"] for p in params] == [0, 1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_walk_sends_page_after_as_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": "1"}], page_after="cur1"),
                _response([{"id": "2"}]),
            ],
        )

        rows = _rows(_source("Transfers", _make_manager()))

        assert [row["id"] for row in rows] == ["1", "2"]
        assert "page" not in params[0]
        assert params[1]["page"] == "cur1"

    def test_page_number_paginator_stops_at_the_api_cap(self) -> None:
        # page_num is capped at 2000; walking past it would request pages the API rejects.
        paginator = AirwallexPageNumberPaginator(page_num=MAX_PAGE_NUM, endpoint="FinancialTransactions")

        paginator.update_state(_response([{"id": "1"}], has_more=True), data=[{"id": "1"}])

        assert paginator.has_next_page is False

    def test_page_number_paginator_keeps_walking_when_has_more_is_absent(self) -> None:
        # Not every endpoint documents has_more; a full page with no flag must not end the walk.
        paginator = AirwallexPageNumberPaginator()

        paginator.update_state(_response([{"id": "1"}]), data=[{"id": "1"}])

        assert paginator.has_next_page is True
        assert paginator.page_num == 1

    def test_page_number_paginator_stops_on_an_empty_page(self) -> None:
        paginator = AirwallexPageNumberPaginator()

        paginator.update_state(_response([], has_more=True), data=[])

        assert paginator.has_next_page is False

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_page_number_resume_seeds_the_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}], has_more=False)])

        _rows(_source("FinancialTransactions", _make_manager(AirwallexResumeConfig(page_num=7))))

        assert params[0]["page_num"] == 7

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_resume_seeds_the_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}])])

        _rows(_source("Transfers", _make_manager(AirwallexResumeConfig(cursor="saved"))))

        assert params[0]["page"] == "saved"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_a_page_number_resume_state_is_ignored_by_a_cursor_endpoint(self, MockSession) -> None:
        # One resume dataclass serves both styles; crossing them would restart at the wrong place.
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}])])

        _rows(_source("Transfers", _make_manager(AirwallexResumeConfig(page_num=7))))

        assert "page" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_save_the_field_matching_the_pagination_style(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "1"}], has_more=True),
                _response([{"id": "2"}], has_more=False),
            ],
        )
        manager = _make_manager()

        _rows(_source("FinancialTransactions", manager))

        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert [s.page_num for s in saved] == [1]
        assert all(s.cursor is None for s in saved)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_every_table_declares_desc_so_the_watermark_lands_at_job_end(self, MockSession) -> None:
        # Airwallex documents an order for one endpoint only, and it is descending. "desc" makes the
        # pipeline write the watermark once the run finishes, so an endpoint that returns
        # newest-first cannot strand older rows.
        session = MockSession.return_value
        _wire(session, [_response([], has_more=False)] * len(AIRWALLEX_ENDPOINTS))

        for endpoint in AIRWALLEX_ENDPOINTS:
            assert _source(endpoint, _make_manager()).sort_mode == "desc"

    @parameterized.expand(
        [
            ("Settlements", ["settlement_id"], "created_at"),
            ("FinancialTransactions", ["id"], "created_at"),
            ("Invoices", ["id"], "created_at"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_key_and_partition_key(self, endpoint: str, keys: list[str], partition: str, MockSession) -> None:
        # Settlements is the one endpoint with no `id` field. A wrong key seeds duplicate rows that
        # every later merge multi-matches.
        session = MockSession.return_value
        _wire(session, [_response([], has_more=False)])

        result = _source(endpoint, _make_manager())

        assert result.primary_keys == keys
        assert result.partition_keys == [partition]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_version_header_is_sent(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], has_more=False)])

        _rows(_source("FinancialTransactions", _make_manager()))

        assert session.headers["x-api-version"] == "2026-07-17"


class TestValidateCredentials:
    @mock.patch(AIRWALLEX_SESSION_PATCH)
    def test_valid_credentials_mint_a_token(self, MockSession) -> None:
        MockSession.return_value.post.return_value = _login_response("minted")

        assert validate_credentials("cid", "key", "live") == (True, None)

    @mock.patch(AIRWALLEX_SESSION_PATCH)
    def test_a_rejected_login_returns_a_message_rather_than_raising(self, MockSession) -> None:
        resp = Response()
        resp.status_code = 401
        MockSession.return_value.post.return_value = resp

        ok, message = validate_credentials("cid", "key", "live")

        assert ok is False
        assert message is not None

    @mock.patch(AIRWALLEX_SESSION_PATCH)
    def test_a_transport_error_returns_a_message_rather_than_raising(self, MockSession) -> None:
        MockSession.side_effect = OSError("boom")

        ok, _message = validate_credentials("cid", "key", "live")

        assert ok is False
