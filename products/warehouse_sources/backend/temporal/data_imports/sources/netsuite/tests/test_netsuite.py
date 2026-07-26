import hmac
import json
import base64
import hashlib
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite import netsuite as netsuite_module
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.netsuite import (
    NetSuiteAPIError,
    NetSuiteResumeConfig,
    NetSuiteTBAAuth,
    account_realm,
    account_slug,
    build_query,
    format_timestamp,
    netsuite_source,
    normalize_row,
    run_query,
    suiteql_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.settings import NETSUITE_ENDPOINTS

_ACCOUNT = "1234567_SB1"
_CONSUMER_KEY = "consumer-key"
_CONSUMER_SECRET = "consumer-secret"
_TOKEN_ID = "token-id"
_TOKEN_SECRET = "token-secret"

_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.netsuite.make_tracked_session"
)


def _auth(nonce: str = "nonce123", timestamp: int = 1700000000) -> NetSuiteTBAAuth:
    return NetSuiteTBAAuth(
        _ACCOUNT,
        _CONSUMER_KEY,
        _CONSUMER_SECRET,
        _TOKEN_ID,
        _TOKEN_SECRET,
        nonce_factory=lambda: nonce,
        timestamp_factory=lambda: timestamp,
    )


def _response(body: Any, status: int = 200) -> Response:
    response = Response()
    response.status_code = status
    response.url = suiteql_url(_ACCOUNT)
    response._content = json.dumps(body).encode()
    return response


def _page(rows: list[dict[str, Any]]) -> Response:
    return _response({"items": rows, "hasMore": False, "count": len(rows)})


def _manager(resume: NetSuiteResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _session(responses: list[Response]) -> MagicMock:
    session = MagicMock()
    session.post.side_effect = responses
    return session


def _collect(response_items: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in cast(Iterable[Any], response_items):
        rows.extend(page)
    return rows


def _queries(session: MagicMock) -> list[str]:
    return [str(call.kwargs["json"]["q"]) for call in session.post.call_args_list]


class TestNetSuiteTransport:
    @parameterized.expand(
        [
            ("production", "1234567", "1234567", "1234567"),
            ("sandbox_underscore", "1234567_SB1", "1234567-sb1", "1234567_SB1"),
            ("sandbox_lowercase", "1234567-sb1", "1234567-sb1", "1234567_SB1"),
            ("padded", "  1234567_SB2  ", "1234567-sb2", "1234567_SB2"),
        ]
    )
    def test_account_id_host_and_realm_spellings(
        self, _name: str, account_id: str, expected_slug: str, expected_realm: str
    ) -> None:
        # The host wants hyphens/lowercase and the OAuth realm wants underscores/uppercase; getting
        # either wrong makes NetSuite reject every request.
        assert account_slug(account_id) == expected_slug
        assert account_realm(account_id) == expected_realm

    def test_suiteql_url_uses_account_host(self) -> None:
        assert suiteql_url(_ACCOUNT) == (
            "https://1234567-sb1.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql"
        )

    def test_signature_base_string_merges_query_and_oauth_params(self) -> None:
        url = f"{suiteql_url(_ACCOUNT)}?limit=1000&offset=2000"
        oauth_params = {
            "oauth_consumer_key": _CONSUMER_KEY,
            "oauth_nonce": "nonce123",
            "oauth_signature_method": "HMAC-SHA256",
            "oauth_timestamp": "1700000000",
            "oauth_token": _TOKEN_ID,
            "oauth_version": "1.0",
        }

        method, encoded_uri, encoded_params = _auth().signature_base_string("POST", url, oauth_params).split("&")

        assert method == "POST"
        # The query string must be stripped from the signed URI and folded into the param list.
        assert unquote(encoded_uri) == suiteql_url(_ACCOUNT)
        assert unquote(encoded_params) == (
            "limit=1000"
            "&oauth_consumer_key=consumer-key"
            "&oauth_nonce=nonce123"
            "&oauth_signature_method=HMAC-SHA256"
            "&oauth_timestamp=1700000000"
            "&oauth_token=token-id"
            "&oauth_version=1.0"
            "&offset=2000"
        )

    def test_authorization_header_signs_with_both_secrets(self) -> None:
        url = f"{suiteql_url(_ACCOUNT)}?limit=1000&offset=0"
        auth = _auth()

        header = auth.authorization_header("POST", url)

        assert header.startswith('OAuth realm="1234567_SB1", ')
        assert 'oauth_signature_method="HMAC-SHA256"' in header
        assert 'oauth_version="1.0"' in header

        base_string = auth.signature_base_string(
            "POST",
            url,
            {
                "oauth_consumer_key": _CONSUMER_KEY,
                "oauth_nonce": "nonce123",
                "oauth_signature_method": "HMAC-SHA256",
                "oauth_timestamp": "1700000000",
                "oauth_token": _TOKEN_ID,
                "oauth_version": "1.0",
            },
        )
        # The signing key is `consumer_secret&token_secret`, not the consumer secret alone.
        expected = base64.b64encode(
            hmac.new(f"{_CONSUMER_SECRET}&{_TOKEN_SECRET}".encode(), base_string.encode(), hashlib.sha256).digest()
        ).decode()
        assert f'oauth_signature="{expected.replace("+", "%2B").replace("/", "%2F").replace("=", "%3D")}"' in header

    def test_auth_sets_authorization_header_on_request(self) -> None:
        request = MagicMock()
        request.headers = {}
        request.method = "POST"
        request.url = f"{suiteql_url(_ACCOUNT)}?limit=1000&offset=0"

        _auth()(request)

        assert request.headers["Authorization"].startswith('OAuth realm="1234567_SB1"')

    def test_nonce_is_unique_per_request(self) -> None:
        auth = NetSuiteTBAAuth(_ACCOUNT, _CONSUMER_KEY, _CONSUMER_SECRET, _TOKEN_ID, _TOKEN_SECRET)
        url = f"{suiteql_url(_ACCOUNT)}?limit=1000&offset=0"

        # A replayed nonce is rejected by NetSuite, so each signing must draw a fresh one.
        assert auth.authorization_header("POST", url) != auth.authorization_header("POST", url)

    @parameterized.expand(
        [
            ("datetime_utc", datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC), "2026-03-04 05:06:07"),
            ("datetime_naive", datetime(2026, 3, 4, 5, 6, 7), "2026-03-04 05:06:07"),
            ("date", date(2026, 3, 4), "2026-03-04 00:00:00"),
            ("iso_string", "2026-03-04T05:06:07+00:00", "2026-03-04 05:06:07"),
            ("iso_string_z", "2026-03-04T05:06:07Z", "2026-03-04 05:06:07"),
            ("garbage", "not-a-date", None),
            ("none", None, None),
            ("int", 12345, None),
        ]
    )
    def test_format_timestamp(self, _name: str, value: Any, expected: str | None) -> None:
        assert format_timestamp(value) == expected

    def test_build_query_full_refresh_orders_by_keyset(self) -> None:
        query = build_query(NETSUITE_ENDPOINTS["customers"])
        assert query == "SELECT * FROM customer ORDER BY id ASC"

    def test_build_query_keyset_predicate(self) -> None:
        query = build_query(NETSUITE_ENDPOINTS["customers"], last_key=500)
        assert query == "SELECT * FROM customer WHERE id > 500 ORDER BY id ASC"

    def test_build_query_combines_incremental_and_keyset(self) -> None:
        query = build_query(
            NETSUITE_ENDPOINTS["transactions"],
            last_key=42,
            incremental_field="lastmodifieddate",
            incremental_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        assert query == (
            "SELECT * FROM transaction "
            "WHERE lastmodifieddate >= TO_TIMESTAMP('2026-01-02 03:04:05', 'YYYY-MM-DD HH24:MI:SS') "
            "AND id > 42 ORDER BY id ASC"
        )

    def test_build_query_uses_line_keyset_for_transaction_lines(self) -> None:
        query = build_query(
            NETSUITE_ENDPOINTS["transaction_lines"],
            last_key=7,
            incremental_field="linelastmodifieddate",
            incremental_value=date(2026, 1, 1),
        )
        assert query == (
            "SELECT * FROM transactionline "
            "WHERE linelastmodifieddate >= TO_TIMESTAMP('2026-01-01 00:00:00', 'YYYY-MM-DD HH24:MI:SS') "
            "AND uniquekey > 7 ORDER BY uniquekey ASC"
        )

    @parameterized.expand(
        [
            # A cursor field the endpoint doesn't advertise, or a value we can't parse as a timestamp,
            # must be dropped rather than spliced into the statement.
            ("unknown_field", "'; DROP TABLE customer; --", datetime(2026, 1, 1, tzinfo=UTC)),
            ("unparseable_value", "lastmodifieddate", "'; DROP TABLE customer; --"),
            ("no_value", "lastmodifieddate", None),
        ]
    )
    def test_build_query_rejects_unusable_incremental_input(
        self, _name: str, incremental_field: str, incremental_value: Any
    ) -> None:
        query = build_query(
            NETSUITE_ENDPOINTS["customers"],
            incremental_field=incremental_field,
            incremental_value=incremental_value,
        )
        assert query == "SELECT * FROM customer ORDER BY id ASC"

    def test_build_query_coerces_keyset_to_int(self) -> None:
        query = build_query(NETSUITE_ENDPOINTS["customers"], last_key=cast(int, "12"))
        assert query == "SELECT * FROM customer WHERE id > 12 ORDER BY id ASC"

    def test_normalize_row_drops_hateoas_links(self) -> None:
        assert normalize_row({"id": "1", "links": [{"rel": "self"}], "entityid": "Acme"}) == {
            "id": "1",
            "entityid": "Acme",
        }

    def test_run_query_posts_statement_with_paging_params(self) -> None:
        session = _session([_page([{"id": "1"}])])

        body = run_query(session, _auth(), _ACCOUNT, "SELECT * FROM customer", limit=1000, offset=2000)

        assert body["items"] == [{"id": "1"}]
        url = session.post.call_args.args[0]
        assert parse_qs(urlsplit(url).query) == {"limit": ["1000"], "offset": ["2000"]}
        assert session.post.call_args.kwargs["json"] == {"q": "SELECT * FROM customer"}

    @parameterized.expand([(401,), (403,), (404,), (429,), (500,)])
    def test_run_query_raises_with_status_in_message(self, status: int) -> None:
        session = _session([_response({"detail": "nope"}, status=status)])

        with pytest.raises(NetSuiteAPIError) as excinfo:
            run_query(session, _auth(), _ACCOUNT, "SELECT 1 AS probe FROM dual", limit=1)

        # `get_non_retryable_errors` matches on this exact prefix.
        assert f"NetSuite SuiteQL request returned {status}" in str(excinfo.value)

    def test_run_query_rejects_non_object_body(self) -> None:
        session = _session([_response([1, 2, 3])])

        with pytest.raises(NetSuiteAPIError):
            run_query(session, _auth(), _ACCOUNT, "SELECT * FROM customer", limit=1)


class TestNetSuitePagination:
    def _source(self, endpoint: str = "customers", manager: MagicMock | None = None, **kwargs: Any) -> Any:
        return netsuite_source(
            account_id=_ACCOUNT,
            consumer_key=_CONSUMER_KEY,
            consumer_secret=_CONSUMER_SECRET,
            token_id=_TOKEN_ID,
            token_secret=_TOKEN_SECRET,
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager or _manager(),
            **kwargs,
        )

    def test_single_short_page_ends_the_sync(self) -> None:
        session = _session([_page([{"id": "1", "links": []}, {"id": "2"}])])

        with patch(_SESSION_PATCH, return_value=session):
            rows = _collect(self._source().items())

        assert rows == [{"id": "1"}, {"id": "2"}]
        assert session.post.call_count == 1

    def test_keyset_advances_across_full_pages(self) -> None:
        session = _session(
            [
                _page([{"id": "1"}, {"id": "2"}]),
                _page([{"id": "5"}, {"id": "9"}]),
                _page([{"id": "11"}]),
            ]
        )
        manager = _manager()

        with patch(_SESSION_PATCH, return_value=session), patch.object(netsuite_module, "PAGE_SIZE", 2):
            rows = _collect(self._source(manager=manager).items())

        assert [row["id"] for row in rows] == ["1", "2", "5", "9", "11"]
        # Each page must ask for rows strictly beyond the previous page's highest key.
        assert _queries(session) == [
            "SELECT * FROM customer ORDER BY id ASC",
            "SELECT * FROM customer WHERE id > 2 ORDER BY id ASC",
            "SELECT * FROM customer WHERE id > 9 ORDER BY id ASC",
        ]

    def test_state_is_saved_after_each_full_page_and_cleared_at_the_end(self) -> None:
        session = _session([_page([{"id": "1"}, {"id": "4"}]), _page([{"id": "6"}])])
        manager = _manager()

        with patch(_SESSION_PATCH, return_value=session), patch.object(netsuite_module, "PAGE_SIZE", 2):
            _collect(self._source(manager=manager).items())

        # Only the page that had a successor is checkpointed; the terminal short page is not.
        assert [call.args[0] for call in manager.save_state.call_args_list] == [NetSuiteResumeConfig(last_key=4)]
        manager.clear_state.assert_called_once()

    def test_resume_starts_after_the_saved_key(self) -> None:
        session = _session([_page([{"id": "900"}])])
        manager = _manager(NetSuiteResumeConfig(last_key=800))

        with patch(_SESSION_PATCH, return_value=session):
            rows = _collect(self._source(manager=manager).items())

        assert _queries(session) == ["SELECT * FROM customer WHERE id > 800 ORDER BY id ASC"]
        assert rows == [{"id": "900"}]

    def test_incremental_filter_is_sent_on_every_page(self) -> None:
        session = _session([_page([{"id": "1"}, {"id": "2"}]), _page([{"id": "3"}])])

        with patch(_SESSION_PATCH, return_value=session), patch.object(netsuite_module, "PAGE_SIZE", 2):
            _collect(
                self._source(
                    endpoint="transactions",
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                    incremental_field="lastmodifieddate",
                ).items()
            )

        cursor = "lastmodifieddate >= TO_TIMESTAMP('2026-01-01 00:00:00', 'YYYY-MM-DD HH24:MI:SS')"
        assert all(cursor in query for query in _queries(session))

    def test_cursor_is_ignored_on_full_refresh(self) -> None:
        session = _session([_page([{"id": "1"}])])

        with patch(_SESSION_PATCH, return_value=session):
            _collect(
                self._source(
                    endpoint="transactions",
                    should_use_incremental_field=False,
                    db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                    incremental_field="lastmodifieddate",
                ).items()
            )

        assert _queries(session) == ["SELECT * FROM transaction ORDER BY id ASC"]

    @parameterized.expand(
        [
            # A full page whose keyset column can't move the cursor forward would otherwise be
            # re-requested forever.
            ("non_numeric_keys", [{"id": "abc"}, {"id": None}]),
            ("keys_not_greater_than_previous", [{"id": "1"}, {"id": "1"}]),
        ]
    )
    def test_stalled_keyset_stops_instead_of_looping(self, _name: str, second_page: list[dict[str, Any]]) -> None:
        session = _session([_page([{"id": "1"}, {"id": "1"}]), _page(second_page), _page([{"id": "2"}])])

        with patch(_SESSION_PATCH, return_value=session), patch.object(netsuite_module, "PAGE_SIZE", 2):
            rows = _collect(self._source().items())

        assert session.post.call_count <= 2
        assert len(rows) >= 2

    def test_page_cap_keeps_the_checkpoint(self) -> None:
        session = _session([_page([{"id": "1"}, {"id": "2"}]), _page([{"id": "3"}])])
        manager = _manager()

        with (
            patch(_SESSION_PATCH, return_value=session),
            patch.object(netsuite_module, "PAGE_SIZE", 2),
            patch.object(netsuite_module, "MAX_PAGES", 1),
        ):
            rows = _collect(self._source(manager=manager).items())

        # Stopping short must leave the resume state behind so the next attempt continues the table.
        assert [row["id"] for row in rows] == ["1", "2"]
        manager.save_state.assert_called_once_with(NetSuiteResumeConfig(last_key=2))
        manager.clear_state.assert_not_called()

    def test_empty_first_page_yields_nothing(self) -> None:
        session = _session([_page([])])

        with patch(_SESSION_PATCH, return_value=session):
            rows = _collect(self._source().items())

        assert rows == []
        assert session.post.call_count == 1

    @parameterized.expand([(name,) for name in NETSUITE_ENDPOINTS])
    def test_source_response_shape_per_endpoint(self, endpoint: str) -> None:
        config = NETSUITE_ENDPOINTS[endpoint]

        response = self._source(endpoint=endpoint)

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Rows arrive in keyset order, not cursor order, so the watermark must only finalize at
        # job end — which is what `desc` buys us.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestNetSuiteValidateCredentials:
    def _validate(self, account_id: str = _ACCOUNT) -> tuple[bool, str | None]:
        return validate_credentials(account_id, _CONSUMER_KEY, _CONSUMER_SECRET, _TOKEN_ID, _TOKEN_SECRET)

    def test_success(self) -> None:
        session = _session([_page([{"probe": "1"}])])

        with patch(_SESSION_PATCH, return_value=session):
            assert self._validate() == (True, None)

        assert session.post.call_args.kwargs["json"] == {"q": "SELECT 1 AS probe FROM dual"}

    @parameterized.expand([(401,), (403,), (404,), (500,)])
    def test_failure_statuses_return_a_message(self, status: int) -> None:
        session = _session([_response({"detail": "no"}, status=status)])

        with patch(_SESSION_PATCH, return_value=session):
            ok, error = self._validate()

        assert ok is False
        assert error

    def test_transport_failure_is_not_raised(self) -> None:
        session = MagicMock()
        session.post.side_effect = OSError("connection refused")

        with patch(_SESSION_PATCH, return_value=session):
            ok, error = self._validate()

        assert ok is False
        assert error == "Could not reach the NetSuite SuiteQL API. Check the account ID."

    def test_blank_account_id_fails_before_any_request(self) -> None:
        with patch(_SESSION_PATCH) as make_session:
            ok, error = self._validate(account_id="   ")

        assert (ok, error) == (False, "A NetSuite account ID is required")
        make_session.assert_not_called()
