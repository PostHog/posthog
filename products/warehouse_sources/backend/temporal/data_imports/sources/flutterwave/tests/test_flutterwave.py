from datetime import UTC, datetime
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.flutterwave import (
    NOT_ON_V4_ERROR,
    FlutterwaveResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.settings import (
    FLUTTERWAVE_API_V3,
    FLUTTERWAVE_API_V4,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.source import FlutterwaveSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flutterwave import (
    FlutterwaveSourceConfig,
)

TOKEN_PATH = "/realms/flutterwave/protocol/openid-connect/token"


def _driver() -> SourceDriver:
    return SourceDriver(
        FlutterwaveSource(),
        FlutterwaveSourceConfig(secret_key="FLWSECK-test", client_id="client-test", client_secret="secret-test"),
    )


def _run_v3(endpoint: str, script: Any, **inputs: Any) -> DriveResult:
    return _driver().run(endpoint, script, api_version=FLUTTERWAVE_API_V3, **inputs)


def _token() -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "minted-token", "expires_in": 600, "token_type": "Bearer"})


def _cursor_page(key: str, rows: list[dict[str, Any]], next_cursor: str | None, has_more: bool) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "status": "success",
            "message": "fetched",
            "data": {
                "cursor": {"next": next_cursor, "limit": 50, "total": 3, "has_more_items": has_more},
                key: rows,
            },
        }
    )


def _page(rows: list[dict[str, Any]], total_pages: int = 1) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "status": "success",
            "message": "fetched",
            "meta": {"page_info": {"total": len(rows), "current_page": 1, "total_pages": total_pages}},
            "data": rows,
        }
    )


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        result = _run_v3(
            "subaccounts", [_page([{"id": 7}], total_pages=4)], resume_state=FlutterwaveResumeConfig(next_page=4)
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [7]
        assert result.params("page") == ["4"]

    def test_saves_page_after_yielding_and_only_while_pages_remain(self) -> None:
        result = _run_v3(
            "subaccounts",
            [_page([{"id": 1}], total_pages=2), _page([{"id": 2}], total_pages=2)],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert [row["id"] for row in result.rows] == [1, 2]
        # Only page 1 has a page after it, so exactly one checkpoint is written and it points at 2.
        assert result.saved_states == [FlutterwaveResumeConfig(next_page=2)]


def _statement_page(rows: list[dict[str, Any]], total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "status": "success",
            "message": "Wallet statement fetched",
            "data": {
                "page_info": {"total": len(rows), "current_page": 1, "total_pages": total_pages},
                "transactions": rows,
            },
        }
    )


def _balances(*currencies: str) -> ScriptedResponse:
    return ScriptedResponse(
        json={"status": "success", "data": [{"currency": c, "available_balance": 0} for c in currencies]}
    )


class TestFanOut:
    def test_wallet_statement_walks_every_wallet_currency(self) -> None:
        result = _run_v3(
            "wallet_statement",
            route(
                {
                    "/balances": [_balances("USD", "NGN")],
                    "/wallet/statement": [
                        _statement_page([{"reference": "a", "currency": "NGN", "type": "C"}], total_pages=2),
                        _statement_page([{"reference": "b", "currency": "NGN", "type": "C"}], total_pages=2),
                        _statement_page([{"reference": "c", "currency": "NGN", "type": "D"}], total_pages=1),
                        _statement_page([], total_pages=0),
                        _statement_page([], total_pages=0),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["reference"] for row in result.rows] == ["a", "b", "c"]
        statements = [request for request in result.requests if request.path == "/v3/wallet/statement"]
        assert [(r.param("currency"), r.param("type"), r.param("page")) for r in statements] == [
            ("NGN", "C", "1"),
            ("NGN", "C", "2"),
            ("NGN", "D", "1"),
            ("USD", "C", "1"),
            ("USD", "D", "1"),
        ]
        assert {r.param("from") for r in statements} == {"2016-01-01"}
        assert result.saved_states == [
            FlutterwaveResumeConfig(next_page=2, fan_out_value="NGN|C"),
            FlutterwaveResumeConfig(fan_out_value="NGN|D"),
            FlutterwaveResumeConfig(fan_out_value="USD|C"),
            FlutterwaveResumeConfig(fan_out_value="USD|D"),
        ]

    def test_wallet_statement_resumes_at_the_saved_currency_direction_and_page(self) -> None:
        result = _run_v3(
            "wallet_statement",
            route(
                {
                    "/balances": [_balances("NGN", "USD")],
                    "/wallet/statement": [_statement_page([{"reference": "c", "currency": "USD"}], total_pages=3)],
                }
            ),
            resume_state=FlutterwaveResumeConfig(next_page=3, fan_out_value="USD|D"),
        )

        assert result.raised is None
        statements = [request for request in result.requests if request.path == "/v3/wallet/statement"]
        assert [(r.param("currency"), r.param("type"), r.param("page")) for r in statements] == [("USD", "D", "3")]

    def test_banks_reads_each_country_and_stamps_it_on_the_rows(self) -> None:
        result = _run_v3(
            "banks", always(ScriptedResponse(json={"status": "success", "data": [{"id": 1, "code": "044"}]}))
        )

        assert result.raised is None
        assert [request.path for request in result.requests] == [
            f"/v3/banks/{country}" for country in ("NG", "GH", "KE", "UG", "ZA", "TZ")
        ]
        assert {request.param("page") for request in result.requests} == {None}
        assert [row["country"] for row in result.rows] == ["NG", "GH", "KE", "UG", "ZA", "TZ"]

    def test_bill_payments_reads_every_status_and_keeps_the_row_status(self) -> None:
        result = _run_v3(
            "bill_payments",
            route(
                {
                    "/bills/history": [
                        _page([{"id": 1, "status": "Successful"}]),
                        _page([{"id": 2, "status": "Failed"}]),
                        _page([{"id": 3, "status": "Reversed"}]),
                    ]
                }
            ),
        )

        assert result.raised is None
        assert [r.param("status") for r in result.requests] == ["Successful", "Failed", "Reversed"]
        assert [(row["id"], row["status"]) for row in result.rows] == [
            (1, "Successful"),
            (2, "Failed"),
            (3, "Reversed"),
        ]


class TestDateWindow:
    @parameterized.expand(
        [
            ("settlements",),
            ("refunds",),
            ("transfers",),
            ("chargebacks",),
            ("payment_plans",),
        ]
    )
    def test_optional_window_endpoints_send_no_window_on_full_refresh(self, endpoint: str) -> None:
        # A full refresh must pull the whole history; a stray `from` would silently truncate it.
        result = _run_v3(
            endpoint,
            [_page([{"id": 1}])],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 15, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("from") is None
        assert result.requests[0].param("to") is None

    @parameterized.expand([("transactions",), ("bill_payments",)])
    def test_required_window_endpoints_send_the_full_history_window(self, endpoint: str) -> None:
        result = _run_v3(endpoint, always(_page([{"id": 1}])))

        assert result.raised is None
        assert result.requests[0].param("from") == "2016-01-01"
        assert result.requests[0].param("to") is not None

    @parameterized.expand(
        [
            ("subscriptions",),
            ("subaccounts",),
            ("beneficiaries",),
        ]
    )
    def test_endpoints_without_a_window_never_send_one(self, endpoint: str) -> None:
        # These endpoints do not accept `from`/`to`; sending them risks 4xxing the whole run.
        result = _run_v3(endpoint, [_page([{"id": 1}])], should_use_incremental_field=False)

        assert result.raised is None
        assert result.requests[0].param("from") is None
        assert result.requests[0].param("to") is None


class TestNoRecordsResponses:
    @parameterized.expand(
        [
            ("lowercase", {"status": "error", "message": "No settlements found", "data": None}),
            ("capitalized", {"status": "error", "message": "Transaction Not Found", "data": None}),
        ]
    )
    def test_empty_range_400_reads_as_an_empty_table(self, _name: str, body: dict[str, Any]) -> None:
        # v3 answers "no records in this range" with a 400 on some list endpoints; a merchant with an
        # empty table must sync zero rows rather than fail the job.
        result = _run_v3("settlements", [ScriptedResponse(status=400, json=body)])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1

    def test_genuine_parameter_error_still_raises(self) -> None:
        result = _run_v3(
            "settlements",
            [
                ScriptedResponse(
                    status=400,
                    json={"status": "error", "message": "page parameter must be a positive integer", "data": None},
                )
            ],
        )

        assert isinstance(result.raised, requests.HTTPError)


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    def test_credential_errors_surface_the_matchable_message(self, _name: str, status: int, reason: str) -> None:
        # get_non_retryable_errors matches on this exact status text plus host, so it must not be
        # swallowed or retried.
        result = _run_v3("transactions", [ScriptedResponse(status=status, json={"status": "error"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert f"{status} Client Error" in str(result.raised)
        assert reason in str(result.raised)
        assert "https://api.flutterwave.com" in str(result.raised)
        assert len(result.requests) == 1

    @parameterized.expand([("rate_limited", 429, "Too Many Requests"), ("server_error", 503, "Service Unavailable")])
    def test_transient_statuses_are_retried_by_the_transport(self, _name: str, status: int, _reason: str) -> None:
        result = _run_v3("transactions", [ScriptedResponse(status=status, json={}), _page([{"id": 1}])])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert len(result.requests) == 2

    def test_persistent_rate_limit_raises_retryable(self) -> None:
        result = _run_v3("transactions", always(ScriptedResponse(status=429, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)


class TestSourceResponseMetadata:
    @parameterized.expand(
        [
            ("transactions",),
            ("settlements",),
            ("refunds",),
            ("transfers",),
            ("chargebacks",),
            ("payment_plans",),
            ("subscriptions",),
            ("subaccounts",),
            ("beneficiaries",),
        ]
    )
    def test_every_endpoint_partitions_on_created_at(self, endpoint: str) -> None:
        result = _run_v3(endpoint, [_page([])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        # Every endpoint is full-refresh, so the pipeline never consults sort_mode; it is None.
        assert result.response.sort_mode is None
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["created_at"]

    @parameterized.expand(
        [
            ("transactions", "/charges", ["created_datetime"]),
            ("settlements", "/settlements", ["created_datetime"]),
            ("refunds", "/refunds", ["created_datetime"]),
            ("chargebacks", "/chargebacks", ["created_datetime"]),
            ("transfers", "/transfers", ["created_datetime"]),
            ("beneficiaries", "/transfers/recipients", None),
        ]
    )
    def test_v4_endpoints_partition_on_their_v4_timestamp(
        self, endpoint: str, path: str, partition_keys: list[str] | None
    ) -> None:
        empty = _cursor_page(endpoint, [], None, False) if path.startswith("/transfers") else _page([])
        result = _driver().run(endpoint, route({TOKEN_PATH: [_token()], path: [empty]}), api_version=FLUTTERWAVE_API_V4)

        assert result.response is not None
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_keys == partition_keys


class TestValidateCredentials:
    @parameterized.expand(
        [
            # v3 answers "no subaccounts on this account" with a 400; the key was still accepted.
            ("no_records", 400, True),
        ]
    )
    def test_status_maps_to_validity(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, message = validate_credentials("FLWSECK-test", "v3")

        assert valid is expected
        assert (message is None) is expected
        assert {request.path for request in network.requests_log} == {"/v3/subaccounts"}

    @parameterized.expand(
        [
            ("ok", 200, 200, True),
            ("rejected_client", 401, None, False),
            ("token_cannot_read", 200, 401, False),
            ("token_lacks_settlements_access", 200, 403, True),
            ("server_error", 200, 500, False),
        ]
    )
    def test_v4_mints_a_token_then_probes_with_it(
        self, _name: str, token_status: int, probe_status: int | None, expected: bool
    ) -> None:
        token = (
            _token() if token_status == 200 else ScriptedResponse(status=token_status, json={"error": "invalid_client"})
        )
        script: dict[str, list[ScriptedResponse]] = {TOKEN_PATH: [token]}
        if probe_status is not None:
            script["/settlements"] = [ScriptedResponse(status=probe_status, json={"status": "success", "data": []})]

        with scripted_network(route(script)) as network:
            valid, message = validate_credentials(None, FLUTTERWAVE_API_V4, "client-test", "secret-test")

        assert valid is expected
        assert (message is None) is expected
        token_request = network.requests_log[0]
        assert token_request.origin == "https://idp.flutterwave.com"
        assert b"client_id=client-test" in (token_request.body or b"")
        if probe_status is not None:
            probe = network.requests_log[1]
            assert probe.origin == "https://f4bexperience.flutterwave.com"
            assert probe.headers["authorization"] == "Bearer minted-token"

    @parameterized.expand(
        [
            ("v3_without_secret_key", FLUTTERWAVE_API_V3, None, "client-test", "secret-test"),
            ("v4_without_client_secret", FLUTTERWAVE_API_V4, "FLWSECK-test", "client-test", None),
        ]
    )
    def test_missing_credentials_for_the_pin_fail_without_a_request(
        self, _name: str, api_version: str, secret_key: str | None, client_id: str | None, client_secret: str | None
    ) -> None:
        with scripted_network(route({})) as network:
            valid, message = validate_credentials(secret_key, api_version, client_id, client_secret)

        assert valid is False
        assert message
        assert network.requests_log == []


class TestV4:
    def test_cursor_endpoint_follows_next_until_has_more_is_false(self) -> None:
        result = _driver().run(
            "transfers",
            route(
                {
                    TOKEN_PATH: [_token()],
                    "/transfers": [
                        _cursor_page("transfers", [{"id": "trf_1"}], "cursor-2", True),
                        # The last page repeats the cursor; has_more_items ends the list before the
                        # repeat guard sees it.
                        _cursor_page("transfers", [{"id": "trf_2"}], "cursor-2", False),
                    ],
                }
            ),
            api_version=FLUTTERWAVE_API_V4,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["trf_1", "trf_2"]
        listed = [request for request in result.requests if request.path == "/transfers"]
        assert [request.param("next") for request in listed] == [None, "cursor-2"]
        assert {request.param("size") for request in listed} == {"50"}
        assert {request.headers["authorization"] for request in listed} == {"Bearer minted-token"}
        assert result.saved_states == [FlutterwaveResumeConfig(next_cursor="cursor-2")]

    def test_cursor_endpoint_resumes_from_saved_cursor_not_page(self) -> None:
        result = _driver().run(
            "beneficiaries",
            route(
                {
                    TOKEN_PATH: [_token()],
                    "/transfers/recipients": [_cursor_page("recipients", [{"id": "rcp_9"}], None, False)],
                }
            ),
            api_version=FLUTTERWAVE_API_V4,
            resume_state=FlutterwaveResumeConfig(next_page=3, next_cursor="cursor-9"),
        )

        assert result.raised is None
        listed = [request for request in result.requests if request.path == "/transfers/recipients"]
        assert [request.param("next") for request in listed] == ["cursor-9"]
        assert listed[0].param("page") is None

    def test_page_endpoint_reads_v4_host_without_the_v3_window_or_empty_400_workaround(self) -> None:
        result = _driver().run(
            "transactions",
            route(
                {
                    TOKEN_PATH: [_token()],
                    "/charges": [
                        ScriptedResponse(
                            status=400,
                            json={"status": "failed", "error": {"type": "REQUEST_NOT_VALID", "message": "Not found"}},
                        )
                    ],
                }
            ),
            api_version=FLUTTERWAVE_API_V4,
        )

        listed = [request for request in result.requests if request.path == "/charges"]
        assert listed[0].origin == "https://f4bexperience.flutterwave.com"
        assert listed[0].param("from") is None
        assert listed[0].param("to") is None
        assert isinstance(result.raised, requests.HTTPError)

    def test_v3_only_table_under_a_v4_pin_fails_clearly(self) -> None:
        result = _driver().run("payment_plans", route({}), api_version=FLUTTERWAVE_API_V4)

        assert result.raised is not None
        assert NOT_ON_V4_ERROR in str(result.raised)
        assert result.requests == []
