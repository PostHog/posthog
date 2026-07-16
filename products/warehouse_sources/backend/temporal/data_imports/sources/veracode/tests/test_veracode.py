from datetime import UTC, date, datetime
from typing import Any

from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.veracode.settings import VERACODE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.veracode.veracode import (
    VeracodeHMACAuth,
    VeracodeResumeConfig,
    VeracodeRetryableError,
    _calculate_signature,
    _fetch_page_once,
    _modified_after,
    _strip_region_prefix,
    get_rows,
    resolve_host,
    validate_credentials,
    veracode_source,
)


def _mock_response(status_code: int, body: Any = None) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = body if body is not None else {}
    response.text = ""

    def raise_for_status() -> None:
        if not response.ok:
            error = requests.HTTPError(f"{status_code} Client Error", response=response)
            raise error

    response.raise_for_status.side_effect = raise_for_status
    return response


def _page(rows: list[dict], embedded_key: str, total_pages: int) -> dict:
    return {"_embedded": {embedded_key: rows}, "page": {"total_pages": total_pages}}


class TestHMACSigning:
    def test_signature_pins_documented_key_chain(self) -> None:
        # Golden vector guards the documented four-step HMAC-SHA-256 derivation. If someone reorders
        # or alters the chain (or the version string), every real request would 401 — this catches it.
        sig = _calculate_signature(
            "abcdef0123456789",
            "id=abcdef0123456789&host=api.veracode.com&url=/appsec/v1/applications?size=1&method=GET",
            1700000000000,
            "00112233445566778899aabbccddeeff",
        )
        assert sig == "b191e323ec5f869605337d1aa9fcc689ed35ececbb28cdb67436448712e89259"

    def test_signature_is_lowercase_hex_256_bits(self) -> None:
        sig = _calculate_signature("abcdef", "id=abcdef&host=h&url=/x&method=GET", 1, "abcd")
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    @parameterized.expand(
        [
            ("prefixed", "vera01ei-abcdef0123456789", "abcdef0123456789"),
            ("unprefixed", "abcdef0123456789", "abcdef0123456789"),
        ]
    )
    def test_strip_region_prefix(self, _name: str, credential: str, expected: str) -> None:
        assert _strip_region_prefix(credential) == expected

    def test_auth_header_format_and_signed_url_includes_query(self) -> None:
        auth = VeracodeHMACAuth("abcdef0123456789", "abcdef0123456789")
        request = requests.Request("GET", "https://api.veracode.com/appsec/v1/applications?size=100&page=2").prepare()

        auth(request)

        header = request.headers["Authorization"]
        assert header.startswith("VERACODE-HMAC-SHA-256 ")
        parts = dict(kv.split("=", 1) for kv in header.removeprefix("VERACODE-HMAC-SHA-256 ").split(","))
        assert set(parts) == {"id", "ts", "nonce", "sig"}
        assert parts["id"] == "abcdef0123456789"
        assert len(parts["sig"]) == 64

    def test_prefix_stripped_from_header_id(self) -> None:
        auth = VeracodeHMACAuth("vera01ei-abcdef0123456789", "vera01ei-abcdef0123456789")
        request = requests.Request("GET", "https://api.veracode.com/appsec/v1/applications").prepare()

        auth(request)

        header = request.headers["Authorization"]
        assert "id=abcdef0123456789," in header

    def test_each_call_produces_fresh_signature(self) -> None:
        auth = VeracodeHMACAuth("abcdef0123456789", "abcdef0123456789")
        r1 = requests.Request("GET", "https://api.veracode.com/x").prepare()
        r2 = requests.Request("GET", "https://api.veracode.com/x").prepare()

        auth(r1)
        auth(r2)

        # Nonce + timestamp are regenerated per call, so signatures differ even for the same URL.
        assert r1.headers["Authorization"] != r2.headers["Authorization"]


class TestResolveHost:
    @parameterized.expand(
        [
            ("commercial", "com", "api.veracode.com"),
            ("europe", "eu", "api.veracode.eu"),
            ("federal", "us", "api.veracode.us"),
            ("default_when_none", None, "api.veracode.com"),
            ("default_when_unknown", "bogus", "api.veracode.com"),
        ]
    )
    def test_resolve_host(self, _name: str, region: str | None, expected: str) -> None:
        assert resolve_host(region) == expected


class TestModifiedAfter:
    @parameterized.expand(
        [
            ("datetime_utc", datetime(2026, 3, 4, 12, 0, tzinfo=UTC), "2026-03-03"),
            ("naive_datetime", datetime(2026, 3, 4, 12, 0), "2026-03-03"),
            ("date", date(2026, 3, 4), "2026-03-03"),
            ("non_temporal", "not-a-date", None),
        ]
    )
    def test_modified_after_applies_day_lookback(self, _name: str, value: Any, expected: str | None) -> None:
        # Day-granular filter with a 1-day lookback so nothing is dropped at the day boundary.
        assert _modified_after(value) == expected


class TestFetchPage:
    # Call the single-attempt function so retry backoff isn't incurred. This guards the
    # retryable-vs-permanent status classification.
    _fetch_once = staticmethod(_fetch_page_once)

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code)
        try:
            self._fetch_once(session, "https://api.veracode.com/x", MagicMock())
        except VeracodeRetryableError:
            pass
        else:
            raise AssertionError("expected VeracodeRetryableError")

    def test_client_error_raises_http_error(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(401)
        try:
            self._fetch_once(session, "https://api.veracode.com/x", MagicMock())
        except requests.HTTPError:
            pass
        else:
            raise AssertionError("expected HTTPError")

    def test_ok_returns_json_body(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"_embedded": {"applications": []}})
        assert self._fetch_once(session, "https://api.veracode.com/x", MagicMock()) == {
            "_embedded": {"applications": []}
        }


class TestGetRowsTopLevel:
    def test_pages_through_all_hal_pages_and_saves_resume_state(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _mock_response(200, _page([{"guid": "a"}], "applications", total_pages=2)),
            _mock_response(200, _page([{"guid": "b"}], "applications", total_pages=2)),
        ]
        manager = MagicMock()
        manager.can_resume.return_value = False

        with _patched_session(session):
            batches = list(
                get_rows(
                    "id", "secret", "com", "applications", MagicMock(), manager, should_use_incremental_field=False
                )
            )

        assert [row["guid"] for batch in batches for row in batch] == ["a", "b"]
        # State saved after the first page (more remained), so a crash re-yields page 2, not skips it.
        manager.save_state.assert_called_once_with(VeracodeResumeConfig(page=1))

    def test_resumes_from_saved_page(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(200, _page([{"guid": "b"}], "applications", total_pages=2))
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = VeracodeResumeConfig(page=1)

        with _patched_session(session):
            list(get_rows("id", "secret", "com", "applications", MagicMock(), manager))

        # Resumed straight at page=1 rather than refetching page 0.
        assert "page=1" in session.get.call_args_list[0].args[0]

    def test_incremental_adds_modified_after_filter(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(200, _page([], "applications", total_pages=1))
        manager = MagicMock()
        manager.can_resume.return_value = False

        with _patched_session(session):
            list(
                get_rows(
                    "id",
                    "secret",
                    "com",
                    "applications",
                    MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
                )
            )

        assert "modified_after=2026-03-03" in session.get.call_args_list[0].args[0]


class TestGetRowsFanOut:
    def test_stamps_application_guid_on_child_rows(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            # application enumeration
            _mock_response(200, _page([{"guid": "app-1"}], "applications", total_pages=1)),
            # findings for app-1
            _mock_response(200, _page([{"issue_id": 7}], "findings", total_pages=1)),
        ]
        manager = MagicMock()
        manager.can_resume.return_value = False

        with _patched_session(session):
            batches = list(get_rows("id", "secret", "com", "findings", MagicMock(), manager))

        rows = [row for batch in batches for row in batch]
        assert rows == [{"issue_id": 7, "application_guid": "app-1"}]

    def test_deleted_application_404_is_skipped(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _mock_response(200, _page([{"guid": "app-gone"}, {"guid": "app-ok"}], "applications", total_pages=1)),
            _mock_response(404),  # app-gone deleted between enumeration and fetch
            _mock_response(200, _page([{"issue_id": 1}], "findings", total_pages=1)),  # app-ok
        ]
        manager = MagicMock()
        manager.can_resume.return_value = False

        with _patched_session(session):
            batches = list(get_rows("id", "secret", "com", "findings", MagicMock(), manager))

        rows = [row for batch in batches for row in batch]
        assert rows == [{"issue_id": 1, "application_guid": "app-ok"}]

    def test_sca_findings_requests_scan_type_sca(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _mock_response(200, _page([{"guid": "app-1"}], "applications", total_pages=1)),
            _mock_response(200, _page([], "findings", total_pages=1)),
        ]
        manager = MagicMock()
        manager.can_resume.return_value = False

        with _patched_session(session):
            list(get_rows("id", "secret", "com", "sca_findings", MagicMock(), manager))

        findings_url = session.get.call_args_list[1].args[0]
        assert "scan_type=SCA" in findings_url


class TestVeracodeSourceResponse:
    @parameterized.expand(list(VERACODE_ENDPOINTS.keys()))
    def test_source_response_matches_endpoint_config(self, endpoint: str) -> None:
        config = VERACODE_ENDPOINTS[endpoint]
        response = veracode_source("id", "secret", "com", endpoint, MagicMock(), MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_ok_flag(self, _name: str, status_code: int, expected_ok: bool) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code)
        with _patched_session(session):
            ok, returned_status = validate_credentials("id", "secret", "com")
        assert ok is expected_ok
        assert returned_status == status_code

    def test_network_error_returns_false_none(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError()
        with _patched_session(session):
            ok, status = validate_credentials("id", "secret", "com")
        assert ok is False
        assert status is None


class _patched_session:
    """Context manager patching `_make_session` so tests inject a mock requests session."""

    def __init__(self, session: MagicMock):
        self._session = session
        self._patcher: Any = None

    def __enter__(self) -> MagicMock:
        from unittest.mock import patch

        self._patcher = patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.veracode.veracode._make_session",
            return_value=self._session,
        )
        self._patcher.start()
        return self._session

    def __exit__(self, *args: Any) -> None:
        self._patcher.stop()
