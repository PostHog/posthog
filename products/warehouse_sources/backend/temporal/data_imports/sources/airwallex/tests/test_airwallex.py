import json
from datetime import UTC, datetime, timedelta
from typing import Any

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
    base_url_for,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.airwallex.source import AirwallexSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airwallex import (
    AirwallexSourceConfig,
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


def _login_response(token: str = "tok", expires_at: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"token": token}
    if expires_at is not None:
        body["expires_at"] = expires_at
    return ScriptedResponse(status=201, json=body)


def _page(
    items: list[dict[str, Any]], *, has_more: bool | None = None, page_after: str | None = None
) -> ScriptedResponse:
    body: dict[str, Any] = {"items": items}
    if has_more is not None:
        body["has_more"] = has_more
    if page_after is not None:
        body["page_after"] = page_after
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(AirwallexSource(), AirwallexSourceConfig(client_id="cid", api_key="key", environment="live"))


class TestAirwallexAuth:
    def test_login_sends_the_credential_headers_and_sets_a_bearer(self) -> None:
        auth = AirwallexAuth("cid", "key", AIRWALLEX_LIVE_BASE_URL)

        request = PreparedRequest()
        request.headers = CaseInsensitiveDict()
        with scripted_network([_login_response("minted")]) as network:
            auth(request)

        headers = network.requests_log[0].headers
        assert headers["x-client-id"] == "cid"
        assert headers["x-api-key"] == "key"
        assert network.requests_log[0].method == "POST"
        assert request.headers["Authorization"] == "Bearer minted"

    def test_login_never_follows_a_redirect(self) -> None:
        # The login call carries the API key in a custom header, which requests would replay to a
        # redirect target.
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://example.com/redirect"})]
        ) as network:
            try:
                AirwallexAuth("cid", "key", AIRWALLEX_LIVE_BASE_URL)._get_token()
            except (AirwallexAuthError, ValueError):
                pass

        assert len(network.requests_log) == 1

    def test_token_is_reused_until_it_nears_expiry(self) -> None:
        far_future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        auth = AirwallexAuth("cid", "key", AIRWALLEX_LIVE_BASE_URL)

        with scripted_network([_login_response("minted", far_future)]) as network:
            auth._get_token()
            auth._get_token()

        assert len(network.requests_log) == 1

    def test_missing_token_in_a_successful_login_raises(self) -> None:
        with scripted_network([_login_response(token="")]):
            try:
                AirwallexAuth("cid", "key", AIRWALLEX_LIVE_BASE_URL)._get_token()
            except AirwallexAuthError:
                return
            raise AssertionError("expected AirwallexAuthError")

    def test_secret_values_cover_the_key_and_the_minted_token(self) -> None:
        # Both must be redacted from logged URLs, headers, sampled bodies, and raised errors.
        auth = AirwallexAuth("cid", "key", AIRWALLEX_LIVE_BASE_URL)

        assert auth.secret_values() == ("key",)
        with scripted_network([_login_response("minted")]) as network:
            auth._get_token()
        assert set(auth.secret_values()) == {"key", "minted"}
        assert network.session_options[0]["redact_values"] == ("key",)
        assert network.session_options[0]["capture"] is False

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
            ("FinancialTransactions", "created_at", "from_created_at"),
            ("Settlements", "settled_at", "from_settled_at"),
            ("Beneficiaries", "created_at", "from_date"),
            ("Invoices", "created_at", "from_created_at"),
            ("PaymentDisputes", "updated_at", "from_updated_at"),
        ]
    )
    def test_incremental_uses_the_endpoints_own_filter_name(self, endpoint: str, field: str, param: str) -> None:
        # Airwallex names this filter differently per endpoint, and sends 200 while ignoring a name
        # it does not know, so a wrong name silently full-scans every run.
        result = _driver().run(
            endpoint,
            [_login_response(), _page([{"id": "1"}], has_more=False)],
            incremental_field=field,
            db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[1].param(param) == "2021-01-01T00:00:00Z"

    @parameterized.expand([("PaymentIntents",), ("Customers",)])
    def test_drops_client_secret(self, endpoint: str) -> None:
        # A still-valid client_secret authorizes a browser/app against Airwallex; it must never be
        # persisted to the warehouse.
        result = _driver().run(
            endpoint, [_login_response(), _page([{"id": "1", "client_secret": "live_secret"}], has_more=False)]
        )

        assert result.raised is None
        assert result.rows == [{"id": "1"}]

    def test_cursor_walk_sends_page_after_as_page(self) -> None:
        result = _driver().run(
            "Transfers",
            [
                _login_response(),
                _page([{"id": "1"}], page_after="cur1"),
                _page([{"id": "2"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert result.params("page") == [None, None, "cur1"]

    @parameterized.expand([("PaymentDisputes", "size", "page_size"), ("CreditNotes", "page_size", "size")])
    def test_page_size_rides_the_endpoints_own_param(self, endpoint: str, param: str, unused: str) -> None:
        # An unknown size param is ignored, so disputes would fall back to 10 rows per page.
        result = _driver().run(endpoint, [_login_response(), _page([{"id": "1"}])])

        assert result.raised is None
        assert result.requests[1].param(param) == "500"
        assert result.requests[1].param(unused) is None

    def test_subscription_items_fan_out_over_every_subscription(self) -> None:
        result = _driver().run(
            "SubscriptionItems",
            [
                _login_response(),
                _page([{"id": "sub_1"}, {"id": "sub_2"}]),
                _page([{"id": "si_1", "subscription_id": "sub_1"}], page_after="cur1"),
                _page([{"id": "si_2", "subscription_id": "sub_1"}]),
                _page([{"id": "si_1", "subscription_id": "sub_2"}]),
            ],
        )

        assert result.raised is None
        assert result.paths[1:] == [
            "/api/v1/billing/subscriptions",
            "/api/v1/billing/subscriptions/sub_1/items",
            "/api/v1/billing/subscriptions/sub_1/items",
            "/api/v1/billing/subscriptions/sub_2/items",
        ]
        assert result.params("page")[2:] == [None, "cur1", None]
        assert [(row["subscription_id"], row["id"]) for row in result.rows] == [
            ("sub_1", "si_1"),
            ("sub_1", "si_2"),
            ("sub_2", "si_1"),
        ]
        assert result.response is not None
        # Item ids are only documented as unique within a subscription.
        assert result.response.primary_keys == ["subscription_id", "id"]

    def test_subscription_items_resume_skips_finished_subscriptions(self) -> None:
        result = _driver().run(
            "SubscriptionItems",
            [
                _login_response(),
                _page([{"id": "sub_1"}, {"id": "sub_2"}]),
                _page([{"id": "si_1", "subscription_id": "sub_2"}]),
            ],
            resume_state=AirwallexResumeConfig(
                fanout_state={
                    "completed": ["/api/v1/billing/subscriptions/sub_1/items"],
                    "current": None,
                    "child_state": None,
                }
            ),
        )

        assert result.raised is None
        assert result.paths[1:] == ["/api/v1/billing/subscriptions", "/api/v1/billing/subscriptions/sub_2/items"]

    def test_page_number_paginator_stops_at_the_api_cap(self) -> None:
        # page_num is capped at 2000; walking past it would request pages the API rejects.
        paginator = AirwallexPageNumberPaginator(page_num=MAX_PAGE_NUM, endpoint="FinancialTransactions")

        paginator.update_state(_response([{"id": "1"}], has_more=True), data=[{"id": "1"}])

        assert paginator.has_next_page is False

    def test_page_number_paginator_stops_on_an_empty_page(self) -> None:
        paginator = AirwallexPageNumberPaginator()

        paginator.update_state(_response([], has_more=True), data=[])

        assert paginator.has_next_page is False

    def test_page_number_resume_seeds_the_page(self) -> None:
        result = _driver().run(
            "FinancialTransactions",
            [_login_response(), _page([{"id": "1"}], has_more=False)],
            resume_state=AirwallexResumeConfig(page_num=7),
        )

        assert result.raised is None
        assert result.params("page_num") == [None, "7"]

    def test_cursor_resume_seeds_the_cursor(self) -> None:
        result = _driver().run(
            "Transfers", [_login_response(), _page([{"id": "1"}])], resume_state=AirwallexResumeConfig(cursor="saved")
        )

        assert result.raised is None
        assert result.params("page") == [None, "saved"]

    def test_checkpoints_save_the_field_matching_the_pagination_style(self) -> None:
        result = _driver().run(
            "FinancialTransactions",
            [
                _login_response(),
                _page([{"id": "1"}], has_more=True),
                _page([{"id": "2"}], has_more=False),
            ],
        )

        assert result.raised is None
        assert result.saved_states == [AirwallexResumeConfig(page_num=1)]

    @parameterized.expand(
        [
            ("Settlements", ["settlement_id"], "created_at"),
            ("FinancialTransactions", ["id"], "created_at"),
            ("Invoices", ["id"], "created_at"),
        ]
    )
    def test_primary_key_and_partition_key(self, endpoint: str, keys: list[str], partition: str) -> None:
        # Settlements is the one endpoint with no `id` field. A wrong key seeds duplicate rows that
        # every later merge multi-matches.
        result = _driver().run(endpoint, [_login_response(), _page([], has_more=False)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == keys
        assert result.response.partition_keys == [partition]


class TestValidateCredentials:
    def test_valid_credentials_mint_a_token(self) -> None:
        with scripted_network([_login_response("minted")]) as network:
            assert validate_credentials("cid", "key", "live") == (True, None)
        assert network.requests_log[0].path == "/api/v1/authentication/login"
