import base64
from datetime import UTC, datetime
from typing import Any, Optional, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.cisco_duo import (
    CiscoDuoHostNotAllowedError,
    CiscoDuoResumeConfig,
    CiscoDuoRetryableError,
    _canonicalize_params,
    _fetch_json_once,
    _normalize_next_offset,
    _to_epoch_ms,
    _to_epoch_seconds,
    cisco_duo_source,
    get_rows,
    is_allowed_hostname,
    normalize_hostname,
    sign_request,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.settings import CISCO_DUO_ENDPOINTS

HOST = "api-xxxxxxxx.duosecurity.com"
IKEY = "DIWJ8X6AEYOR5OMC6TQ1"
SKEY = "Zh5eGmUq9zpfQnyUIu5OL9iWoMMv5ZNmk3zLJ4Ep"

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.cisco_duo"


def _response(*, status_code: int = 200, json_data: Any = None, headers: Optional[dict] = None) -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = ""
    response.json.return_value = json_data
    response.headers = headers or {}
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Client Error", response=response)
    return response


class _FakeSession:
    """Returns canned responses in order and records every requested URL."""

    def __init__(self, responses: list[mock.MagicMock]) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> mock.MagicMock:
        self.urls.append(url)
        return self._responses.pop(0)


def _manager(resume: CiscoDuoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


@pytest.fixture(autouse=True)
def _safe_host():
    with mock.patch(f"{MODULE}._is_host_safe", return_value=(True, None)):
        yield


def _run(endpoint: str, session: _FakeSession, manager: mock.MagicMock, **kwargs: Any) -> list[list[dict]]:
    with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
        return list(
            get_rows(
                api_hostname=kwargs.pop("api_hostname", HOST),
                integration_key=IKEY,
                secret_key=SKEY,
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                team_id=1,
                **kwargs,
            )
        )


class TestHostnameValidation:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("api-xxxxxxxx.duosecurity.com", "api-xxxxxxxx.duosecurity.com"),
            ("https://api-xxxxxxxx.duosecurity.com/", "api-xxxxxxxx.duosecurity.com"),
            ("API-XXXXXXXX.DUOSECURITY.COM", "api-xxxxxxxx.duosecurity.com"),
            ("  api-xxxxxxxx.duosecurity.com/admin/v1  ", "api-xxxxxxxx.duosecurity.com"),
        ],
    )
    def test_normalize_hostname(self, raw, expected):
        assert normalize_hostname(raw) == expected

    @pytest.mark.parametrize(
        "hostname, allowed",
        [
            ("api-xxxxxxxx.duosecurity.com", True),
            ("api-xxxxxxxx.duofederal.com", True),
            ("api-xxxxxxxx.evil.com", False),
            ("duosecurity.com.evil.com", False),
            ("api-xxxxxxxx.duosecurity.com@evil.com", False),
            ("", False),
        ],
    )
    def test_is_allowed_hostname(self, hostname, allowed):
        assert is_allowed_hostname(hostname) is allowed

    def test_get_rows_rejects_disallowed_hostname(self):
        with pytest.raises(CiscoDuoHostNotAllowedError):
            _run("users", _FakeSession([]), _manager(), api_hostname="api.evil.com")


class TestSigning:
    def test_canonicalize_sorts_and_percent_encodes(self):
        # Duo signs the RFC 3986-encoded, key-sorted param string; urlencode's default
        # '+'-for-space or unsorted params would produce an invalid signature.
        canon = _canonicalize_params({"realname": "First Last", "username": "root", "limit": "10/20"})
        assert canon == "limit=10%2F20&realname=First%20Last&username=root"

    def test_sign_request_builds_basic_auth_over_canonical_string(self):
        date_str = "Tue, 21 Aug 2012 17:29:18 -0000"
        headers = sign_request("GET", HOST, "/admin/v1/users", {"limit": "1"}, IKEY, SKEY, date_str)

        assert headers["Date"] == date_str
        decoded = base64.b64decode(headers["Authorization"].removeprefix("Basic ")).decode()
        username, _, signature = decoded.partition(":")
        assert username == IKEY
        assert len(signature) == 40
        int(signature, 16)  # HMAC-SHA1 hex digest

    def test_signature_changes_with_params(self):
        date_str = "Tue, 21 Aug 2012 17:29:18 -0000"
        one = sign_request("GET", HOST, "/admin/v1/users", {"limit": "1"}, IKEY, SKEY, date_str)
        two = sign_request("GET", HOST, "/admin/v1/users", {"limit": "2"}, IKEY, SKEY, date_str)
        assert one["Authorization"] != two["Authorization"]


class TestFetchJson:
    def _fetch_once(self, response: mock.MagicMock) -> dict[str, Any]:
        session = cast(requests.Session, _FakeSession([response]))
        return _fetch_json_once(session, HOST, "/admin/v1/users", {}, IKEY, SKEY, mock.MagicMock())

    def test_429_raises_retryable_with_retry_after(self):
        with pytest.raises(CiscoDuoRetryableError) as exc:
            self._fetch_once(_response(status_code=429, headers={"Retry-After": "7"}))
        assert exc.value.retry_after == 7.0

    @pytest.mark.parametrize("status_code", [500, 502, 503])
    def test_5xx_raises_retryable(self, status_code):
        with pytest.raises(CiscoDuoRetryableError):
            self._fetch_once(_response(status_code=status_code))

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_4xx_raises_http_error(self, status_code):
        with pytest.raises(requests.HTTPError):
            self._fetch_once(_response(status_code=status_code))

    def test_redirect_is_rejected_not_followed(self):
        with pytest.raises(CiscoDuoHostNotAllowedError):
            self._fetch_once(_response(status_code=302))


class TestIncrementalValueConversion:
    @pytest.mark.parametrize(
        "value, expected_seconds",
        [
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            ("2023-11-14T22:13:20Z", 1700000000),
        ],
    )
    def test_to_epoch(self, value, expected_seconds):
        assert _to_epoch_seconds(value) == expected_seconds
        assert _to_epoch_ms(value) == expected_seconds * 1000

    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, None),
            ("", None),
            ([], None),
            ("abc123", "abc123"),
            (["1532951895000", "af0ba235"], "1532951895000,af0ba235"),
        ],
    )
    def test_normalize_next_offset(self, raw, expected):
        assert _normalize_next_offset(raw) == expected


class TestLogV2Rows:
    def _page(self, items: list[dict], next_offset: Any = None) -> mock.MagicMock:
        return _response(
            json_data={
                "stat": "OK",
                "response": {"authlogs": items, "metadata": {"next_offset": next_offset} if next_offset else {}},
            }
        )

    def test_paginates_with_fixed_window_and_saves_state_after_yield(self):
        first = [{"txid": "a", "timestamp": 1700000001}]
        second = [{"txid": "b", "timestamp": 1700000002}]
        session = _FakeSession([self._page(first, next_offset=["1700000001000", "a"]), self._page(second)])
        manager = _manager()

        batches = _run(
            "authentication_logs",
            session,
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert batches == [first, second]

        first_params = _query(session.urls[0])
        assert first_params["mintime"] == "1700000000000"
        assert first_params["sort"] == "ts:asc"
        assert first_params["limit"] == "1000"
        assert "next_offset" not in first_params

        second_params = _query(session.urls[1])
        assert second_params["next_offset"] == "1700000001000,a"
        # The window must stay pinned across pages, or pagination is non-deterministic.
        assert second_params["mintime"] == first_params["mintime"]
        assert second_params["maxtime"] == first_params["maxtime"]

        manager.save_state.assert_called_once_with(
            CiscoDuoResumeConfig(
                next_offset="1700000001000,a", mintime=1700000000000, maxtime=int(first_params["maxtime"])
            )
        )

    def test_first_sync_uses_lookback_window(self):
        session = _FakeSession([self._page([])])
        _run("authentication_logs", session, _manager())

        params = _query(session.urls[0])
        window_days = (int(params["maxtime"]) - int(params["mintime"])) / (24 * 60 * 60 * 1000)
        assert window_days == 180

    def test_resume_restores_window_and_cursor(self):
        session = _FakeSession([self._page([{"txid": "c", "timestamp": 3}])])
        resume = CiscoDuoResumeConfig(next_offset="cursor123", mintime=1000, maxtime=2000)

        batches = _run("authentication_logs", session, _manager(resume))

        assert len(batches) == 1
        params = _query(session.urls[0])
        assert params == {
            "mintime": "1000",
            "maxtime": "2000",
            "limit": "1000",
            "sort": "ts:asc",
            "next_offset": "cursor123",
        }

    def test_future_watermark_clamped_to_window_end(self):
        session = _FakeSession([self._page([])])
        _run(
            "authentication_logs",
            session,
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=99999999999,  # far future
        )
        params = _query(session.urls[0])
        assert int(params["mintime"]) <= int(params["maxtime"])

    def test_telephony_uses_items_data_key_and_iso_watermark(self):
        items = [{"telephony_id": "t1", "ts": "2024-01-01T00:00:05+00:00"}]
        session = _FakeSession([_response(json_data={"stat": "OK", "response": {"items": items, "metadata": {}}})])

        batches = _run(
            "telephony_logs",
            session,
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00+00:00",
        )

        assert batches == [items]
        assert _query(session.urls[0])["mintime"] == str(1704067200 * 1000)


class TestLogV1Rows:
    def _page(self, items: list[dict]) -> mock.MagicMock:
        return _response(json_data={"stat": "OK", "response": items})

    def test_advances_mintime_and_stops_on_short_page(self):
        with mock.patch(f"{MODULE}.LOG_V1_PAGE_SIZE", 3):
            page_one = [{"timestamp": ts, "action": "a"} for ts in (1, 2, 3)]
            page_two = [{"timestamp": 4, "action": "b"}]
            session = _FakeSession([self._page(page_one), self._page(page_two)])
            manager = _manager()

            batches = _run("administrator_logs", session, manager)

        # Page one is full, so its trailing row (timestamp 3) is held back and re-fetched.
        assert batches == [[{"timestamp": 1, "action": "a"}, {"timestamp": 2, "action": "a"}], page_two]
        assert _query(session.urls[0])["mintime"] == "0"
        assert _query(session.urls[1])["mintime"] == "2"
        manager.save_state.assert_any_call(CiscoDuoResumeConfig(mintime=2))

    def test_watermark_rows_are_dropped_client_side(self):
        # Duo's docs are ambiguous on mintime inclusivity; boundary rows already synced in
        # append mode must not be yielded again or they'd be duplicated.
        items = [{"timestamp": 100}, {"timestamp": 101}]
        session = _FakeSession([self._page(items)])

        batches = _run(
            "administrator_logs",
            session,
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=100,
        )

        assert batches == [[{"timestamp": 101}]]
        assert _query(session.urls[0])["mintime"] == "100"

    def test_full_page_sharing_one_second_does_not_loop(self):
        with mock.patch(f"{MODULE}.LOG_V1_PAGE_SIZE", 2):
            same_second = [{"timestamp": 7, "object": "x"}, {"timestamp": 7, "object": "y"}]
            session = _FakeSession([self._page(same_second), self._page(same_second), self._page([])])

            batches = _run("administrator_logs", session, _manager())

        # Rows are yielded exactly once even though the server keeps returning the boundary page.
        assert batches == [same_second]
        assert _query(session.urls[2])["mintime"] == "8"

    def test_resume_starts_from_saved_mintime(self):
        session = _FakeSession([self._page([{"timestamp": 51}])])

        batches = _run("administrator_logs", session, _manager(CiscoDuoResumeConfig(mintime=50)))

        assert batches == [[{"timestamp": 51}]]
        assert _query(session.urls[0])["mintime"] == "50"


class TestListV1Rows:
    def _page(self, items: list[dict], next_offset: Any = None) -> mock.MagicMock:
        metadata = {"next_offset": next_offset} if next_offset is not None else {}
        return _response(json_data={"stat": "OK", "response": items, "metadata": metadata})

    def test_follows_next_offset_until_absent(self):
        first = [{"user_id": "u1"}]
        second = [{"user_id": "u2"}]
        session = _FakeSession([self._page(first, next_offset=100), self._page(second)])
        manager = _manager()

        batches = _run("users", session, manager)

        assert batches == [first, second]
        assert _query(session.urls[0])["offset"] == "0"
        assert _query(session.urls[1])["offset"] == "100"
        manager.save_state.assert_called_once_with(CiscoDuoResumeConfig(offset=100))

    def test_resume_starts_from_saved_offset(self):
        session = _FakeSession([self._page([{"user_id": "u3"}])])

        _run("users", session, _manager(CiscoDuoResumeConfig(offset=200)))

        assert _query(session.urls[0])["offset"] == "200"


class TestValidateCredentials:
    def _validate(self, response: mock.MagicMock, schema_name: str | None = None) -> tuple[bool, str | None]:
        session = _FakeSession([response])
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            return validate_credentials(HOST, IKEY, SKEY, schema_name=schema_name, team_id=1)

    def test_200_is_valid(self):
        assert self._validate(_response(json_data={"stat": "OK", "response": []})) == (True, None)

    def test_401_is_invalid(self):
        ok, message = self._validate(_response(status_code=401))
        assert ok is False
        assert "Invalid Cisco Duo credentials" in (message or "")

    def test_403_accepted_at_source_create(self):
        # Duo Admin API permissions are granular; a log-only key must still connect.
        assert self._validate(_response(status_code=403)) == (True, None)

    def test_403_fails_for_scoped_probe(self):
        ok, _ = self._validate(_response(status_code=403), schema_name="users")
        assert ok is False

    def test_redirect_fails(self):
        ok, _ = self._validate(_response(status_code=302))
        assert ok is False

    def test_disallowed_hostname_fails_without_request(self):
        ok, message = validate_credentials("api.evil.com", IKEY, SKEY, team_id=1)
        assert ok is False
        assert "hostname" in (message or "")


class TestCiscoDuoSource:
    @pytest.mark.parametrize("endpoint", list(CISCO_DUO_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint):
        config = CISCO_DUO_ENDPOINTS[endpoint]
        response = cisco_duo_source(
            api_hostname=HOST,
            integration_key=IKEY,
            secret_key=SKEY,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
