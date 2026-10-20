import hmac
import base64
import hashlib
from datetime import UTC, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.cisco_duo import (
    CiscoDuoHostNotAllowedError,
    CiscoDuoLogSaturationError,
    CiscoDuoResumeConfig,
    CiscoDuoRetryableError,
    _fetch_json_once,
    _normalize_next_offset,
    _to_epoch_ms,
    _to_epoch_seconds,
    sign_request,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.settings import CISCO_DUO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.source import CiscoDuoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ciscoduo import (
    CiscoDuoSourceConfig,
)

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
    """Returns canned responses in order."""

    def __init__(self, responses: list[mock.MagicMock]) -> None:
        self._responses = list(responses)

    def get(self, _url: str, **_kwargs: Any) -> mock.MagicMock:
        return self._responses.pop(0)


def _signature(headers: dict[str, str]) -> str:
    decoded = base64.b64decode(headers["Authorization"].removeprefix("Basic ")).decode()
    return decoded.partition(":")[2]


@pytest.fixture(autouse=True)
def _safe_host():
    with mock.patch(f"{MODULE}._is_host_safe", return_value=(True, None)):
        yield


def _driver(api_hostname: str = HOST) -> SourceDriver:
    return SourceDriver(
        CiscoDuoSource(), CiscoDuoSourceConfig(api_hostname=api_hostname, integration_key=IKEY, secret_key=SKEY)
    )


class TestHostnameValidation:
    def test_get_rows_rejects_disallowed_hostname(self):
        result = _driver(api_hostname="api.evil.com").run("users", [])

        assert isinstance(result.raised, CiscoDuoHostNotAllowedError)
        assert result.requests == []


class TestSigning:
    def test_v5_signature_appends_body_and_header_hashes(self):
        # Some /admin/v2 handlers reject Duo's legacy v2 signing. v5 signs two extra canonical
        # lines — the request body and the signed X-Duo-* headers — with SHA-512 instead of
        # SHA-1. A GET carries neither, so both are the hash of the empty string.
        date_str = "Tue, 21 Aug 2012 17:29:18 -0000"
        empty = hashlib.sha512(b"").hexdigest()
        canon = "\n".join([date_str, "GET", HOST, "/admin/v2/policies", "limit=100", empty, empty])
        expected = hmac.new(SKEY.encode("utf-8"), canon.encode("utf-8"), hashlib.sha512).hexdigest()

        headers = sign_request("GET", HOST, "/admin/v2/policies", {"limit": "100"}, IKEY, SKEY, date_str, 5)

        assert _signature(headers) == expected

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
    def _page(self, items: list[dict], next_offset: Any = None) -> ScriptedResponse:
        return ScriptedResponse(
            json={
                "stat": "OK",
                "response": {"authlogs": items, "metadata": {"next_offset": next_offset} if next_offset else {}},
            }
        )

    def test_paginates_with_fixed_window_and_saves_state_after_yield(self):
        first = [{"txid": "a", "timestamp": 1700000001}]
        second = [{"txid": "b", "timestamp": 1700000002}]
        result = _driver().run(
            "authentication_logs",
            [self._page(first, next_offset=["1700000001000", "a"]), self._page(second)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.items == [first, second]

        first_params = {key: values[0] for key, values in result.queries[0].items()}
        assert first_params["mintime"] == "1700000000000"
        assert first_params["sort"] == "ts:asc"
        assert first_params["limit"] == "1000"
        assert "next_offset" not in first_params

        second_params = {key: values[0] for key, values in result.queries[1].items()}
        assert second_params["next_offset"] == "1700000001000,a"
        # The window must stay pinned across pages, or pagination is non-deterministic.
        assert second_params["mintime"] == first_params["mintime"]
        assert second_params["maxtime"] == first_params["maxtime"]

        assert result.saved_states == [
            CiscoDuoResumeConfig(
                next_offset="1700000001000,a", mintime=1700000000000, maxtime=int(first_params["maxtime"])
            )
        ]

    def test_first_sync_uses_lookback_window(self):
        result = _driver().run("authentication_logs", [self._page([])])

        assert result.raised is None
        mintime = result.requests[0].param("mintime")
        maxtime = result.requests[0].param("maxtime")
        assert mintime is not None
        assert maxtime is not None
        window_days = (int(maxtime) - int(mintime)) / (24 * 60 * 60 * 1000)
        assert window_days == 180

    def test_resume_restores_window_and_cursor(self):
        resume = CiscoDuoResumeConfig(next_offset="cursor123", mintime=1000, maxtime=2000)

        result = _driver().run(
            "authentication_logs", [self._page([{"txid": "c", "timestamp": 3}])], resume_state=resume
        )

        assert result.raised is None
        assert len(result.items) == 1
        params = {key: values[0] for key, values in result.queries[0].items()}
        assert params == {
            "mintime": "1000",
            "maxtime": "2000",
            "limit": "1000",
            "sort": "ts:asc",
            "next_offset": "cursor123",
        }

    def test_telephony_uses_items_data_key_and_iso_watermark(self):
        items = [{"telephony_id": "t1", "ts": "2024-01-01T00:00:05+00:00"}]
        result = _driver().run(
            "telephony_logs",
            [ScriptedResponse(json={"stat": "OK", "response": {"items": items, "metadata": {}}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00+00:00",
        )

        assert result.raised is None
        assert result.items == [items]
        assert result.requests[0].param("mintime") == str(1704067200 * 1000)


class TestLogV1Rows:
    def _page(self, items: list[dict]) -> ScriptedResponse:
        return ScriptedResponse(json={"stat": "OK", "response": items})

    def test_watermark_rows_are_dropped_client_side(self):
        # Duo's docs are ambiguous on mintime inclusivity; boundary rows already synced in
        # append mode must not be yielded again or they'd be duplicated.
        items = [{"timestamp": 100}, {"timestamp": 101}]
        result = _driver().run(
            "administrator_logs",
            [self._page(items)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=100,
        )

        assert result.raised is None
        assert result.items == [[{"timestamp": 101}]]
        assert result.requests[0].param("mintime") == "100"

    def test_saturated_second_raises_instead_of_dropping_records(self):
        # A full page whose rows all share one second means more events exist at that second
        # than one page can return. Because the v1 log API only pages by mintime (seconds),
        # advancing would silently drop the remaining same-second audit records — so the sync
        # must fail loudly rather than skip them.
        same_second = [{"timestamp": 7, "object": f"event_{index}"} for index in range(1000)]
        result = _driver().run("administrator_logs", [self._page(same_second), self._page(same_second)])

        assert isinstance(result.raised, CiscoDuoLogSaturationError)

    def test_resume_starts_from_saved_mintime(self):
        result = _driver().run(
            "administrator_logs", [self._page([{"timestamp": 51}])], resume_state=CiscoDuoResumeConfig(mintime=50)
        )

        assert result.raised is None
        assert result.items == [[{"timestamp": 51}]]
        assert result.requests[0].param("mintime") == "50"


class TestListV1Rows:
    def _page(self, items: list[dict], next_offset: Any = None) -> ScriptedResponse:
        metadata = {"next_offset": next_offset} if next_offset is not None else {}
        return ScriptedResponse(json={"stat": "OK", "response": items, "metadata": metadata})

    def test_follows_next_offset_until_absent(self):
        first = [{"user_id": "u1"}]
        second = [{"user_id": "u2"}]
        result = _driver().run("users", [self._page(first, next_offset=100), self._page(second)])

        assert result.raised is None
        assert result.items == [first, second]
        assert result.params("offset") == ["0", "100"]
        assert result.saved_states == [CiscoDuoResumeConfig(offset=100)]

    def test_resume_starts_from_saved_offset(self):
        result = _driver().run(
            "users", [self._page([{"user_id": "u3"}])], resume_state=CiscoDuoResumeConfig(offset=200)
        )

        assert result.raised is None
        assert result.requests[0].param("offset") == "200"

    def test_integrations_secret_key_is_redacted(self):
        # The integrations endpoint returns each integration's secret_key; persisting it would
        # leak Duo application secrets into the warehouse table, so it must be stripped.
        result = _driver().run(
            "integrations", [self._page([{"integration_key": "DI123", "name": "web sdk", "secret_key": "supersecret"}])]
        )

        assert result.raised is None
        assert result.items == [[{"integration_key": "DI123", "name": "web sdk"}]]

    @parameterized.expand([("integrations", False), ("users", True)])
    def test_http_capture_disabled_when_response_needs_redaction(self, endpoint: str, expected_capture: bool):
        # Sample capture records the raw response before redaction, so it must be off for
        # endpoints whose responses carry secrets (integrations), and left on otherwise.
        result = _driver().run(endpoint, [self._page([])])

        assert result.raised is None
        assert result.session_options[0]["capture"] is expected_capture


class TestFanoutV1Rows:
    def _page(self, items: list[dict], next_offset: Any = None) -> ScriptedResponse:
        metadata = {"next_offset": next_offset} if next_offset is not None else {}
        return ScriptedResponse(json={"stat": "OK", "response": items, "metadata": metadata})

    def _group(self, group_id: str) -> dict:
        return {"group_id": group_id, "name": group_id}

    def test_checkpoints_the_next_child_page_then_the_next_parent(self):
        result = _driver().run(
            "group_users",
            [
                self._page([self._group("DG1"), self._group("DG2")]),
                self._page([{"user_id": "u1"}], next_offset=100),
                self._page([{"user_id": "u2"}]),
                self._page([{"user_id": "u3"}]),
            ],
        )
        assert result.raised is None
        assert result.params("offset")[1:3] == ["0", "100"]
        # Each checkpoint names the work still to do. Naming the work just done would re-yield
        # it on resume, and these tables are full-refresh, so the rows would duplicate.
        assert result.saved_states == [
            CiscoDuoResumeConfig(parent_offset=0, parent_id="DG1", offset=100),
            CiscoDuoResumeConfig(parent_offset=0, parent_id="DG2", offset=0),
        ]

    def test_resume_skips_finished_parents_and_continues_mid_parent(self):
        resume = CiscoDuoResumeConfig(parent_offset=0, parent_id="DG2", offset=100)
        result = _driver().run(
            "group_users",
            [
                self._page([self._group("DG1"), self._group("DG2")]),
                self._page([{"user_id": "u9"}]),
            ],
            resume_state=resume,
        )

        assert result.raised is None
        assert result.items == [[{"user_id": "u9", "group_id": "DG2"}]]
        assert result.paths[1] == "/admin/v2/groups/DG2/users"
        assert result.requests[1].param("offset") == "100"

    def test_restarts_the_page_when_the_checkpointed_parent_is_gone(self):
        # The group was deleted since the checkpoint, so every offset behind it has shifted and
        # there is no safe place to pick up inside the page.
        resume = CiscoDuoResumeConfig(parent_offset=0, parent_id="DGGONE", offset=100)
        result = _driver().run(
            "group_users",
            [
                self._page([self._group("DG1")]),
                self._page([{"user_id": "u1"}]),
            ],
            resume_state=resume,
        )

        assert result.raised is None
        assert result.items == [[{"user_id": "u1", "group_id": "DG1"}]]
        assert result.requests[1].param("offset") == "0"

    def test_follows_the_parent_next_offset(self):
        result = _driver().run(
            "group_users",
            [
                self._page([self._group("DG1")], next_offset=100),
                self._page([{"user_id": "u1"}]),
                self._page([self._group("DG2")]),
                self._page([{"user_id": "u2"}]),
            ],
        )
        assert result.raised is None
        assert result.params("offset")[0] == "0"
        assert result.params("offset")[2] == "100"
        assert CiscoDuoResumeConfig(parent_offset=100) in result.saved_states


class TestValidateCredentials:
    def _validate(self, response: ScriptedResponse, schema_name: str | None = None) -> tuple[bool, str | None]:
        with scripted_network([response]) as network:
            result = validate_credentials(HOST, IKEY, SKEY, schema_name=schema_name, team_id=1)
            assert [request.path for request in network.requests_log] == ["/admin/v1/users"]
            assert network.requests_log[0].param("limit") == "1"
            return result

    def test_200_is_valid(self):
        assert self._validate(ScriptedResponse(json={"stat": "OK", "response": []})) == (True, None)

    def test_401_is_invalid(self):
        ok, message = self._validate(ScriptedResponse(status=401))
        assert ok is False
        assert "Invalid Cisco Duo credentials" in (message or "")

    def test_403_accepted_at_source_create(self):
        # Duo Admin API permissions are granular; a log-only key must still connect.
        assert self._validate(ScriptedResponse(status=403)) == (True, None)

    def test_403_fails_for_scoped_probe(self):
        ok, _ = self._validate(ScriptedResponse(status=403), schema_name="users")
        assert ok is False

    def test_redirect_fails(self):
        ok, _ = self._validate(ScriptedResponse(status=302, headers={"Location": "https://example.com"}))
        assert ok is False

    def test_disallowed_hostname_fails_without_request(self):
        ok, message = validate_credentials("api.evil.com", IKEY, SKEY, team_id=1)
        assert ok is False
        assert "hostname" in (message or "")


class TestCiscoDuoSource:
    @pytest.mark.parametrize("endpoint", list(CISCO_DUO_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint):
        config = CISCO_DUO_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [ScriptedResponse(json={"stat": "OK", "response": []})])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
