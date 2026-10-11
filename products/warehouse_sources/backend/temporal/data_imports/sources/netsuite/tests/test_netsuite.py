import json
import datetime as dt
from typing import Any

import pytest
from unittest import mock

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.netsuite import (
    NetSuiteAccount,
    NetSuiteClient,
    NetSuiteError,
    NetSuiteOAuth2Credentials,
    NetSuiteResumeConfig,
    NetSuiteTBACredentials,
    NetSuiteTokenError,
    build_query,
    iter_rows,
    normalize_row,
    probe,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.settings import ENDPOINT_CONFIGS

SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.netsuite.make_tracked_session"
)
TBA = NetSuiteTBACredentials(consumer_key="ck", consumer_secret="cs", token_id="tid", token_secret="ts")


def _response(status: int, body: Any, headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    response.url = "https://1234567.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql?limit=1000"
    response.reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden"}.get(status, "Error")
    response.headers.update(headers or {})
    return response


def _pem(key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


def _client(responses: list[Any], credentials: Any = TBA) -> tuple[NetSuiteClient, mock.MagicMock, mock.MagicMock]:
    session = mock.MagicMock()
    session.post.side_effect = responses
    sleep = mock.MagicMock()
    with mock.patch(SESSION_PATCH, return_value=session):
        client = NetSuiteClient("1234567", credentials, sleep=sleep)
    return client, session, sleep


class _Manager:
    def __init__(self, state: NetSuiteResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[NetSuiteResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> NetSuiteResumeConfig | None:
        return self.state

    def save_state(self, data: NetSuiteResumeConfig) -> None:
        self.saved.append(data)


class TestCredentials:
    def test_repr_hides_secrets(self) -> None:
        oauth = NetSuiteOAuth2Credentials(client_id="client", certificate_id="certificate", private_key="private")
        tba = NetSuiteTBACredentials(
            consumer_key="consumer", consumer_secret="consumer-secret", token_id="token", token_secret="token-secret"
        )

        assert "private" not in repr(oauth)
        assert "consumer-secret" not in repr(tba)
        assert "token-secret" not in repr(tba)


class TestNetSuiteAccount:
    @parameterized.expand(
        [
            ("production", "1234567", "1234567", "1234567.suitetalk.api.netsuite.com"),
            ("sandbox_underscore", "1234567_SB1", "1234567_SB1", "1234567-sb1.suitetalk.api.netsuite.com"),
            ("sandbox_dns_form", " 1234567-sb1 ", "1234567_SB1", "1234567-sb1.suitetalk.api.netsuite.com"),
        ]
    )
    def test_parse(self, _name: str, account_id: str, realm: str, host: str) -> None:
        account = NetSuiteAccount.parse(account_id)
        assert (account.realm, account.host) == (realm, host)

    @parameterized.expand([("https://1234567.app.netsuite.com",), ("evil.com/x",), ("1234567.example.com",), ("",)])
    def test_parse_rejects_values_that_change_the_host(self, account_id: str) -> None:
        with pytest.raises(NetSuiteError):
            NetSuiteAccount.parse(account_id)


class TestBuildQuery:
    def test_full_refresh_has_no_watermark_and_keysets_on_the_composite_key(self) -> None:
        query = build_query(ENDPOINT_CONFIGS["transactionline"], None, None, ["42", "3"])

        assert query == (
            "SELECT t.* FROM transactionline t"
            " WHERE ((t.transaction > 42) OR (t.transaction = 42 AND t.id > 3))"
            " ORDER BY t.transaction, t.id"
        )

    def test_incremental_filters_on_the_utc_watermark_and_keysets_on_the_session_timestamp(self) -> None:
        watermark = dt.datetime(2026, 3, 2, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))

        query = build_query(ENDPOINT_CONFIGS["customer"], "lastmodifieddate", watermark, ["2026-03-02 05:00:00", "7"])

        assert "TO_CHAR(SYS_EXTRACT_UTC(t.lastmodifieddate)" in query
        assert "t.lastmodifieddate >= TO_DATE('2026-03-01 10:00:00', 'YYYY-MM-DD HH24:MI:SS')" in query
        assert (
            "SYS_EXTRACT_UTC(t.lastmodifieddate) >= TO_TIMESTAMP('2026-03-02 10:00:00', 'YYYY-MM-DD HH24:MI:SS')"
            in query
        )
        assert (
            "((t.lastmodifieddate > TO_DATE('2026-03-02 05:00:00', 'YYYY-MM-DD HH24:MI:SS'))"
            " OR (t.lastmodifieddate = TO_DATE('2026-03-02 05:00:00', 'YYYY-MM-DD HH24:MI:SS') AND t.id > 7))"
        ) in query
        assert query.endswith("ORDER BY t.lastmodifieddate, t.id")

    def test_full_refresh_still_selects_utc_timestamps_so_column_types_match_incremental(self) -> None:
        query = build_query(ENDPOINT_CONFIGS["customer"], None, None, None)

        assert "AS ph_lastmodifieddate_utc" in query
        assert "WHERE" not in query

    @parameterized.expand(
        [("injection", ["2026-01-01' OR 1=1 --", "1"]), ("non_numeric_key", ["2026-01-01 00:00:00", "1 OR 1=1"])]
    )
    def test_rejects_cursor_values_that_are_not_plain_literals(self, _name: str, cursor: list[str]) -> None:
        with pytest.raises((NetSuiteError, ValueError)):
            build_query(ENDPOINT_CONFIGS["customer"], "lastmodifieddate", None, cursor)


class TestNormalizeRow:
    def test_normalizes_keys_timestamps_and_drops_helper_columns(self) -> None:
        row = normalize_row(
            {
                "links": [],
                "id": "15",
                "companyname": "Example Co",
                "lastmodifieddate": "3/2/2026",
                "ph_lastmodifieddate_utc": "2026-03-02T10:00:00Z",
                "ph_cursor_ts": "2026-03-02 02:00:00",
            },
            ENDPOINT_CONFIGS["customer"],
        )

        assert row == {
            "id": 15,
            "companyname": "Example Co",
            "lastmodifieddate": dt.datetime(2026, 3, 2, 10, 0, tzinfo=dt.UTC),
        }

    def test_missing_timestamp_becomes_none(self) -> None:
        # SuiteQL omits null columns from each item.
        row = normalize_row({"id": "1"}, ENDPOINT_CONFIGS["customer"])
        assert row["lastmodifieddate"] is None


class TestIterRows:
    def _page(self, ids: list[int], has_more: bool, ts: str = "2026-01-01 00:00:00") -> dict[str, Any]:
        return {"items": [{"id": str(i), "ph_cursor_ts": ts} for i in ids], "hasMore": has_more}

    def test_pages_with_keyset_and_saves_state_only_while_more_pages_remain(self) -> None:
        client = mock.MagicMock()
        client.query.side_effect = [self._page(list(range(1, 1001)), True), self._page([1001], False)]
        manager = _Manager()

        pages = list(iter_rows(client, ENDPOINT_CONFIGS["account"], None, None, manager))  # type: ignore[arg-type]

        assert [len(page) for page in pages] == [1000, 1]
        assert "WHERE ((t.id > 1000))" in client.query.call_args_list[1].args[0]
        assert manager.saved == [NetSuiteResumeConfig(cursor=["1000"], incremental_field=None)]

    def test_resumes_from_saved_cursor(self) -> None:
        client = mock.MagicMock()
        client.query.return_value = self._page([501], False)
        manager = _Manager(
            NetSuiteResumeConfig(cursor=["2026-01-01 00:00:00", "500"], incremental_field="lastmodifieddate")
        )

        list(iter_rows(client, ENDPOINT_CONFIGS["customer"], "lastmodifieddate", None, manager))  # type: ignore[arg-type]

        assert "t.id > 500" in client.query.call_args.args[0]

    def test_ignores_saved_cursor_from_a_different_sync_mode(self) -> None:
        client = mock.MagicMock()
        client.query.return_value = self._page([1], False)
        manager = _Manager(
            NetSuiteResumeConfig(cursor=["2026-01-01 00:00:00", "500"], incremental_field="lastmodifieddate")
        )

        list(iter_rows(client, ENDPOINT_CONFIGS["customer"], None, None, manager))  # type: ignore[arg-type]

        assert "WHERE" not in client.query.call_args.args[0]

    def test_raises_when_a_page_does_not_advance_the_cursor(self) -> None:
        client = mock.MagicMock()
        client.query.return_value = self._page([5] * 1000, True)
        manager = _Manager(NetSuiteResumeConfig(cursor=["5"]))

        with pytest.raises(NetSuiteError, match="did not advance"):
            list(iter_rows(client, ENDPOINT_CONFIGS["account"], None, None, manager))  # type: ignore[arg-type]

    def test_does_not_save_state_when_normalizing_a_page_fails(self) -> None:
        client = mock.MagicMock()
        client.query.return_value = self._page(list(range(1, 1001)), True)
        manager = _Manager()

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.netsuite.normalize_row",
                side_effect=ValueError("bad row"),
            ),
            pytest.raises(ValueError, match="bad row"),
        ):
            next(iter_rows(client, ENDPOINT_CONFIGS["account"], None, None, manager))  # type: ignore[arg-type]

        assert manager.saved == []


class TestNetSuiteClient:
    def test_retries_rate_limits_through_the_session_so_each_attempt_is_signed_again(self) -> None:
        client, session, sleep = _client(
            [_response(429, {}, {"Retry-After": "3"}), _response(200, {"items": [], "hasMore": False})]
        )

        assert client.query("SELECT id FROM account") == {"items": [], "hasMore": False}
        assert session.post.call_count == 2
        sleep.assert_called_once_with(3.0)

    def test_appends_netsuite_error_detail_to_client_errors(self) -> None:
        detail = "Invalid search query. Detailed unprocessed description follows. Search error occurred: Record 'customer' was not found."
        client, _, _ = _client([_response(400, {"title": "Bad Request", "o:errorDetails": [{"detail": detail}]})])

        with pytest.raises(
            requests.HTTPError, match="^400 Client Error: Bad Request for url: .*Search error occurred: Record"
        ):
            client.query("SELECT id FROM customer")

    def test_tba_signs_with_the_canonical_account_realm(self) -> None:
        session = mock.MagicMock()
        with mock.patch(SESSION_PATCH, return_value=session):
            NetSuiteClient("1234567-sb1", TBA)

        assert session.auth.client.realm == "1234567_SB1"
        assert session.auth.client.signature_method == "HMAC-SHA256"


class TestProbe:
    @parameterized.expand(
        [
            ("ok", _response(200, {"items": []}), None, False),
            ("bad_credentials", _response(401, {}), "rejected the credentials", False),
            ("no_rest_permission", _response(403, {}), "REST Web Services permission", False),
            (
                "record_denied",
                _response(
                    400, {"o:errorDetails": [{"detail": "Search error occurred: Record 'currency' was not found."}]}
                ),
                "can't read the currency table",
                True,
            ),
        ]
    )
    def test_maps_status_to_result(
        self, _name: str, response: requests.Response, error: str | None, record_denied: bool
    ) -> None:
        client, _, _ = _client([response])

        result = probe(client, "currency")

        assert result.record_denied is record_denied
        if error is None:
            assert result.error is None
        else:
            assert result.error is not None and error in result.error


class TestOAuth2:
    def _credentials(self, key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey) -> NetSuiteOAuth2Credentials:
        return NetSuiteOAuth2Credentials(client_id="client-1", certificate_id="cert-1", private_key=_pem(key))

    @parameterized.expand(
        [
            ("rsa", lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048), "PS256"),
            ("ec_p256", lambda: ec.generate_private_key(ec.SECP256R1()), "ES256"),
        ]
    )
    def test_token_request_carries_a_signed_assertion_and_token_is_reused(
        self, _name: str, make_key: Any, algorithm: str
    ) -> None:
        key = make_key()
        token_session = mock.MagicMock()
        token_session.post.return_value = _response(200, {"access_token": "at-1", "expires_in": 3600})
        query_session = mock.MagicMock()
        with mock.patch(SESSION_PATCH, side_effect=[token_session, query_session]):
            client = NetSuiteClient("1234567_SB1", self._credentials(key))
        auth = query_session.auth

        first = auth(requests.Request("POST", "https://example.com").prepare())
        second = auth(requests.Request("POST", "https://example.com").prepare())

        assert first.headers["Authorization"] == second.headers["Authorization"] == "Bearer at-1"
        assert token_session.post.call_count == 1
        token_url = "https://1234567-sb1.suitetalk.api.netsuite.com/services/rest/auth/oauth2/v1/token"
        assert token_session.post.call_args.args[0] == token_url
        data = token_session.post.call_args.kwargs["data"]
        assert data["grant_type"] == "client_credentials"
        assertion = data["client_assertion"]
        assert jwt.get_unverified_header(assertion) == {"alg": algorithm, "typ": "JWT", "kid": "cert-1"}
        claims = jwt.decode(assertion, key.public_key(), algorithms=[algorithm], audience=token_url)
        assert claims["iss"] == "client-1"
        assert claims["scope"] == ["rest_webservices"]
        assert client.account.realm == "1234567_SB1"

    def test_rejected_token_request_raises_a_token_error_with_the_netsuite_reason(self) -> None:
        token_session = mock.MagicMock()
        token_session.post.return_value = _response(400, {"error": "invalid_grant"})
        query_session = mock.MagicMock()
        with mock.patch(SESSION_PATCH, side_effect=[token_session, query_session]):
            NetSuiteClient("1234567", self._credentials(rsa.generate_private_key(public_exponent=65537, key_size=2048)))

        with pytest.raises(
            NetSuiteTokenError, match=r"^NetSuite rejected the OAuth 2\.0 token request \(invalid_grant\)"
        ):
            query_session.auth(requests.Request("POST", "https://example.com").prepare())

    @parameterized.expand(
        [
            ("not_pem", "not a key"),
            ("unsupported_curve", _pem(ec.generate_private_key(ec.SECP256K1()))),
        ]
    )
    def test_unusable_private_key_fails_before_any_request(self, _name: str, private_key: str) -> None:
        credentials = NetSuiteOAuth2Credentials(client_id="c", certificate_id="k", private_key=private_key)
        with mock.patch(SESSION_PATCH) as make_session, pytest.raises(NetSuiteTokenError):
            NetSuiteClient("1234567", credentials)
        make_session.return_value.post.assert_not_called()
