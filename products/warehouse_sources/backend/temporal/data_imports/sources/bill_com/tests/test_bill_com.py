from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.bill_com import (
    PAGE_SIZE,
    BillComAuthError,
    BillComClient,
    BillComRedirectError,
    BillComResumeConfig,
    base_url,
    build_params,
    error_message,
    format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.source import BillComSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.billcom import (
    BillComSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(
        BillComSource(),
        BillComSourceConfig(
            username="finance@acme.com",
            password="pw",
            organization_id="org-1",
            dev_key="dev-key",
            environment="production",
        ),
    )


def _client(environment: str = "production") -> BillComClient:
    return BillComClient(
        username="finance@acme.com",
        password="pw",
        organization_id="org-1",
        dev_key="dev-key",
        environment=environment,
        api_version="v3",
    )


def _login() -> ScriptedResponse:
    return ScriptedResponse(json={"sessionId": "sess-1"})


def _response(status: int = 200, body: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status
    response.text = text
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = body
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=response)
    return response


class TestBillCom:
    def test_base_url_rejects_unknown_environment(self) -> None:
        with pytest.raises(ValueError):
            base_url("evil")

    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 1, 12, 30, 15, 250000, tzinfo=UTC), "2026-03-01T12:30:15.250Z"),
            (datetime(2026, 3, 1, 12, 30, 15), "2026-03-01T12:30:15.000Z"),
            (date(2026, 3, 1), "2026-03-01T00:00:00.000Z"),
            ("2026-03-01T00:00:00.000Z", "2026-03-01T00:00:00.000Z"),
        ],
    )
    def test_format_incremental_value(self, value: Any, expected: str) -> None:
        assert format_incremental_value(value) == expected

    @pytest.mark.parametrize(
        "body, text, expected",
        [
            ([{"message": "Invalid credentials", "code": "BDC_1105"}], "", "Invalid credentials"),
            ({"message": "Unauthorized"}, "", "Unauthorized"),
            (ValueError("not json"), "<html>502</html>", "<html>502</html>"),
        ],
    )
    def test_error_message_reads_both_error_envelopes(self, body: Any, text: str, expected: str) -> None:
        assert error_message(_response(body=body, text=text)) == expected

    @pytest.mark.parametrize(
        "should_use_incremental_field, last_value, incremental_field, expected_sort, expected_filters",
        [
            (False, None, None, "createdTime:asc", None),
            # A last value only filters when the sync is actually incremental.
            (False, datetime(2026, 3, 1, tzinfo=UTC), "updatedTime", "createdTime:asc", None),
            (True, None, "updatedTime", "updatedTime:asc", None),
            (
                True,
                datetime(2026, 3, 1, tzinfo=UTC),
                "updatedTime",
                "updatedTime:asc",
                "updatedTime:gte:2026-03-01T00:00:00.000Z",
            ),
            (
                True,
                datetime(2026, 3, 1, tzinfo=UTC),
                "createdTime",
                "createdTime:asc",
                "createdTime:gte:2026-03-01T00:00:00.000Z",
            ),
            # An unsupported cursor field falls back to the one BILL can filter on.
            (
                True,
                datetime(2026, 3, 1, tzinfo=UTC),
                "id",
                "updatedTime:asc",
                "updatedTime:gte:2026-03-01T00:00:00.000Z",
            ),
        ],
    )
    def test_build_params(
        self,
        should_use_incremental_field: bool,
        last_value: Any,
        incremental_field: Optional[str],
        expected_sort: str,
        expected_filters: Optional[str],
    ) -> None:
        params = build_params(should_use_incremental_field, last_value, incremental_field)

        assert params["max"] == PAGE_SIZE
        assert params["sort"] == expected_sort
        assert params.get("filters") == expected_filters

    def test_login_posts_credentials_and_stores_session_id(self) -> None:
        with scripted_network([ScriptedResponse(json={"sessionId": "sess-1", "organizationId": "org-1"})]) as network:
            client = _client()
            assert client.login() == "sess-1"

        assert client.session_id == "sess-1"
        assert network.requests_log[0].method == "POST"
        assert network.requests_log[0].url == "https://gateway.prod.bill.com/connect/v3/login"
        assert network.requests_log[0].json() == {
            "username": "finance@acme.com",
            "password": "pw",
            "organizationId": "org-1",
            "devKey": "dev-key",
        }

    @pytest.mark.parametrize("status", [400, 401, 403])
    def test_login_rejects_bad_credentials_without_retrying(self, status: int) -> None:
        with scripted_network([ScriptedResponse(status=status, json=[{"message": "Invalid credentials"}])]) as network:
            with pytest.raises(BillComAuthError, match="Invalid credentials"):
                _client().login()

        assert len(network.requests_log) == 1

    def test_login_without_session_id_raises(self) -> None:
        with scripted_network([ScriptedResponse(json={"organizationId": "org-1"})]):
            with pytest.raises(BillComAuthError, match="did not return a session ID"):
                _client().login()

    def test_no_bill_traffic_is_ever_sample_captured(self) -> None:
        with scripted_network([_login(), ScriptedResponse(json={"results": [{"id": "00n1"}]})]) as network:
            client = _client()
            client.login()
            client.list_page("/invoices", {})

        # BILL responses carry the freshly minted session ID and raw financial records that no
        # name-based scrubber would recognise, so every session used for BILL traffic must be
        # excluded from capture.
        assert network.session_options, "no tracked session was built"
        assert all(options.get("capture", True) is False for options in network.session_options)

    def test_list_page_signs_in_again_when_the_session_expires(self) -> None:
        with scripted_network(
            [
                _login(),
                ScriptedResponse(status=401, json={"message": "Unauthorized"}),
                _login(),
                ScriptedResponse(json={}),
            ]
        ) as network:
            _client().list_page("/bills", {})

        # One sign-in to start the session, one to replace the expired one.
        assert [request.method for request in network.requests_log] == ["POST", "GET", "POST", "GET"]
        assert [request.path for request in network.requests_log] == [
            "/connect/v3/login",
            "/connect/v3/bills",
            "/connect/v3/login",
            "/connect/v3/bills",
        ]

    def test_list_page_raises_on_other_errors(self) -> None:
        with scripted_network([_login(), ScriptedResponse(status=403, json=[{"message": "Forbidden"}])]) as network:
            with pytest.raises(requests.HTTPError):
                _client().list_page("/bills", {})

        assert [request.method for request in network.requests_log] == ["POST", "GET"]

    def test_get_rows_paginates_and_checkpoints_after_each_page(self) -> None:
        result = _driver().run(
            "bills",
            [
                _login(),
                ScriptedResponse(json={"results": [{"id": "00n1"}], "nextPage": "cursor-2"}),
                ScriptedResponse(json={"results": [{"id": "00n2"}], "nextPage": "cursor-3"}),
                ScriptedResponse(json={"results": [{"id": "00n3"}]}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": "00n1"}], [{"id": "00n2"}], [{"id": "00n3"}]]
        assert result.rows == [{"id": "00n1"}, {"id": "00n2"}, {"id": "00n3"}]
        assert result.params("page") == [None, None, "cursor-2", "cursor-3"]
        assert result.params("max") == [None, "100", "100", "100"]
        assert result.saved_states == [
            BillComResumeConfig(next_page="cursor-2"),
            BillComResumeConfig(next_page="cursor-3"),
        ]
        assert result.final_state is None

    def test_get_rows_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "bills",
            [_login(), ScriptedResponse(json={"results": [{"id": "00n9"}]})],
            resume_state=BillComResumeConfig(next_page="cursor-7"),
        )

        assert result.raised is None
        assert result.items == [[{"id": "00n9"}]]
        assert result.params("page") == [None, "cursor-7"]

    def test_get_rows_stops_on_a_repeated_cursor(self) -> None:
        result = _driver().run(
            "bills",
            [
                _login(),
                ScriptedResponse(json={"results": [{"id": "00n1"}], "nextPage": "cursor-2"}),
                ScriptedResponse(json={"results": [{"id": "00n2"}], "nextPage": "cursor-2"}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": "00n1"}], [{"id": "00n2"}]]
        assert result.params("page") == [None, None, "cursor-2"]
        assert result.final_state is None

    @pytest.mark.parametrize(
        "login_response, expected",
        [
            (_login(), (True, None)),
        ],
    )
    def test_validate_credentials(self, login_response: ScriptedResponse, expected: tuple[bool, Optional[str]]) -> None:
        with scripted_network([login_response]):
            assert validate_credentials("finance@acme.com", "pw", "org-1", "dev-key", "production", "v3") == expected

    def test_validate_credentials_rejects_an_unknown_environment_without_a_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("finance@acme.com", "pw", "org-1", "dev-key", "evil", "v3")

        assert is_valid is False
        assert message is not None and "Invalid BILL environment" in message
        assert network.requests_log == []

    def test_bill_com_source_response_shape(self) -> None:
        result = _driver().run(
            "bills",
            [_login(), ScriptedResponse(json={"results": [{"id": "00n1", "createdTime": "2026-03-01T00:00:00Z"}]})],
            incremental_field="updatedTime",
            db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "bills"
        assert result.response.primary_keys == ["id"]
        assert result.response.sort_mode == "asc"
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["createdTime"]
        assert result.items == [[{"id": "00n1", "createdTime": "2026-03-01T00:00:00Z"}]]
        assert result.requests[1].param("filters") == "updatedTime:gte:2026-03-01T00:00:00.000Z"


class TestRedirectsRefused:
    # `requests` drops `Authorization` on a cross-host redirect but replays custom headers, so
    # `sessionId` and `devKey` would reach the redirect target. The session refuses every 3xx.
    TARGET_URL = "https://www.bill.com/connect/v3/bills"

    @pytest.mark.parametrize("status", [301, 302])
    def test_list_page_refuses_redirect_and_keeps_session_headers_on_api_host(self, status: int) -> None:
        with scripted_network(
            [_login(), ScriptedResponse(status=status, headers={"Location": self.TARGET_URL})]
        ) as network:
            with pytest.raises(BillComRedirectError, match="redirected the API request to www.bill.com"):
                _client().list_page("/bills", {"max": PAGE_SIZE})

        assert [request.origin for request in network.requests_log] == [
            "https://gateway.prod.bill.com",
            "https://gateway.prod.bill.com",
        ]
        list_request = network.requests_log[-1]
        assert list_request.headers["sessionid"] == "sess-1"
        assert list_request.headers["devkey"] == "dev-key"

    def test_login_refuses_redirect_so_the_sign_in_body_is_not_replayed(self) -> None:
        # A 307 keeps the POST body (password and developer key) on the redirected request.
        with scripted_network([ScriptedResponse(status=307, headers={"Location": self.TARGET_URL})]) as network:
            with pytest.raises(BillComRedirectError):
                _client().login()

        assert [request.origin for request in network.requests_log] == ["https://gateway.prod.bill.com"]

    def test_validate_credentials_reports_the_redirect(self) -> None:
        with scripted_network([ScriptedResponse(status=302, headers={"Location": self.TARGET_URL})]):
            is_valid, message = validate_credentials("finance@acme.com", "pw", "org-1", "dev-key", "production", "v3")

        assert is_valid is False
        assert message == "BILL redirected the API request to www.bill.com; refusing to follow"
