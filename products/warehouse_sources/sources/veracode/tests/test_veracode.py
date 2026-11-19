from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk import TrackedHTTPAdapter
from products.warehouse_sources.sources.veracode.settings import VERACODE_ENDPOINTS
from products.warehouse_sources.sources.veracode.veracode import (
    VeracodeHMACAuth,
    VeracodeReportError,
    VeracodeResumeConfig,
    VeracodeRetryableError,
    _calculate_signature,
    _fetch_page_once,
    _make_session,
    _modified_after,
    _report_start_date,
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


class TestSessionSecurity:
    def test_session_disables_sample_capture_and_redacts_credentials(self) -> None:
        # Veracode response bodies carry customers' vulnerability inventory, so both the credential
        # probe and the sync must stay out of HTTP sample capture. Re-enabling capture here would
        # leak that data to anyone with sample access, outside the warehouse table's access path.
        session = _make_session("00vc-api-id", "ff-api-secret")
        adapter = session.get_adapter("https://api.veracode.com")
        assert isinstance(adapter, TrackedHTTPAdapter)
        assert adapter._capture is False
        assert "00vc-api-id" in adapter._redact_values
        assert "ff-api-secret" in adapter._redact_values


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

    @parameterized.expand(
        [
            (
                "incremental_applications_add_modified_after",
                "applications",
                True,
                "https://api.veracode.com/appsec/v1/applications?size=100&modified_after=2026-03-03&page=0",
            ),
            # Without `all_for_org`, the Identity API lists only the teams of the service account.
            (
                "teams_list_whole_organization",
                "teams",
                False,
                "https://api.veracode.com/api/authn/v2/teams?size=100&all_for_org=true&page=0",
            ),
        ]
    )
    def test_request_url(self, _name: str, endpoint: str, use_incremental: bool, expected_url: str) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(200, _page([], VERACODE_ENDPOINTS[endpoint].embedded_key, 1))
        manager = MagicMock()
        manager.can_resume.return_value = False

        with _patched_session(session):
            list(
                get_rows(
                    "id",
                    "secret",
                    "com",
                    endpoint,
                    MagicMock(),
                    manager,
                    should_use_incremental_field=use_incremental,
                    db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
                )
            )

        assert session.get.call_args_list[0].args[0] == expected_url


class TestGetRowsFanOut:
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

    def test_sca_issues_fan_out_over_workspaces_with_open_and_fixed_issues(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _mock_response(200, _page([{"id": "ws-1"}], "workspaces", total_pages=2)),
            _mock_response(200, _page([{"id": "ws-2"}], "workspaces", total_pages=2)),
            _mock_response(200, _page([{"id": "issue-1"}], "issues", total_pages=1)),
            _mock_response(200, _page([{"id": "issue-2"}], "issues", total_pages=1)),
        ]
        manager = MagicMock()
        manager.can_resume.return_value = False

        with _patched_session(session):
            batches = list(get_rows("id", "secret", "eu", "sca_workspace_issues", MagicMock(), manager))

        assert batches == [[{"id": "issue-1", "workspace_id": "ws-1"}], [{"id": "issue-2", "workspace_id": "ws-2"}]]
        # The API returns only open issues unless the status filter repeats each status.
        assert [call.args[0] for call in session.get.call_args_list[2:]] == [
            "https://api.veracode.eu/srcclr/v3/workspaces/ws-1/issues?size=100&status=open&status=fixed&page=0",
            "https://api.veracode.eu/srcclr/v3/workspaces/ws-2/issues?size=100&status=open&status=fixed&page=0",
        ]

    def test_summary_report_yields_one_row_per_application(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _mock_response(200, _page([{"guid": "app-1"}, {"guid": "app-2"}], "applications", total_pages=1)),
            _mock_response(200, {"app_name": "one", "total_flaws": 3}),
            _mock_response(200, {"app_name": "two", "total_flaws": 0}),
        ]
        manager = MagicMock()
        manager.can_resume.return_value = False

        with _patched_session(session):
            batches = list(get_rows("id", "secret", "com", "summary_report", MagicMock(), manager))

        assert batches == [
            [{"app_name": "one", "total_flaws": 3, "application_guid": "app-1"}],
            [{"app_name": "two", "total_flaws": 0, "application_guid": "app-2"}],
        ]
        assert (
            session.get.call_args_list[1]
            .args[0]
            .startswith("https://api.veracode.com/appsec/v2/applications/app-1/summary_report?")
        )


def _report(status: str, scans: list[dict] | None = None, total_pages: int = 0) -> dict:
    return {
        "_embedded": {
            "id": "report-1",
            "status": status,
            "scans": scans or [],
            "page_metadata": {"total_pages": total_pages},
        }
    }


class TestReportStartDate:
    @parameterized.expand(
        [
            ("full_refresh_uses_max_lookback", False, None, "2026-05-18"),
            ("recent_watermark_with_day_lookback", True, date(2026, 11, 10), "2026-11-09"),
            ("old_watermark_clamped_to_max_lookback", True, date(2025, 1, 1), "2026-05-18"),
            ("incremental_without_watermark", True, None, "2026-05-18"),
        ]
    )
    def test_report_start_date(self, _name: str, use_incremental: bool, last_value: Any, expected: str) -> None:
        # The Reporting API rejects a start date more than six months back.
        assert _report_start_date(use_incremental, last_value, date(2026, 11, 14)) == expected


class TestGetRowsScansReport:
    @time_machine.travel(datetime(2026, 11, 14, 12, 0, tzinfo=UTC), tick=False)
    def test_submits_polls_and_pages_through_report(self) -> None:
        session = MagicMock()
        session.post.return_value = _mock_response(200, _report("SUBMITTED"))
        session.get.side_effect = [
            _mock_response(200, _report("PROCESSING")),
            _mock_response(200, _report("COMPLETED", [{"scan_id": "1"}], total_pages=2)),
            _mock_response(200, _report("COMPLETED", [{"scan_id": "2"}], total_pages=2)),
        ]
        manager = MagicMock()
        manager.can_resume.return_value = False

        with _patched_session(session):
            batches = list(
                get_rows(
                    "id",
                    "secret",
                    "eu",
                    "scans",
                    MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=date(2026, 11, 1),
                )
            )

        assert [row["scan_id"] for batch in batches for row in batch] == ["1", "2"]
        assert session.post.call_args.args[0] == "https://api.veracode.eu/analytics/scans/report"
        assert session.post.call_args.kwargs["json"] == {"last_updated_start_date": "2026-10-31"}
        assert [call.args[0] for call in session.get.call_args_list] == [
            "https://api.veracode.eu/analytics/scans/report/report-1?page=0",
            "https://api.veracode.eu/analytics/scans/report/report-1?page=0",
            "https://api.veracode.eu/analytics/scans/report/report-1?page=1",
        ]
        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            VeracodeResumeConfig(page=0, report_id="report-1"),
            VeracodeResumeConfig(page=1, report_id="report-1"),
        ]

    def test_resume_reads_saved_page_of_saved_report(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(200, _report("COMPLETED", [{"scan_id": "3"}], total_pages=3))
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = VeracodeResumeConfig(page=2, report_id="report-1")

        with _patched_session(session):
            batches = list(get_rows("id", "secret", "com", "scans", MagicMock(), manager))

        assert batches == [[{"scan_id": "3"}]]
        session.post.assert_not_called()
        assert session.get.call_args.args[0] == "https://api.veracode.com/analytics/scans/report/report-1?page=2"

    def test_resume_requests_new_report_when_saved_one_is_gone(self) -> None:
        session = MagicMock()
        session.post.return_value = _mock_response(200, {"_embedded": {"id": "report-2", "status": "SUBMITTED"}})
        session.get.side_effect = [
            _mock_response(404),
            _mock_response(200, _report("COMPLETED", [{"scan_id": "1"}], total_pages=1)),
        ]
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = VeracodeResumeConfig(page=4, report_id="expired")

        with _patched_session(session):
            batches = list(get_rows("id", "secret", "com", "scans", MagicMock(), manager))

        assert batches == [[{"scan_id": "1"}]]
        assert session.get.call_args.args[0] == "https://api.veracode.com/analytics/scans/report/report-2?page=0"

    @parameterized.expand([("failed", "FAILED"), ("unknown_status", None)])
    def test_report_that_does_not_complete_raises(self, _name: str, status: str | None) -> None:
        session = MagicMock()
        session.post.return_value = _mock_response(200, _report("SUBMITTED"))
        session.get.return_value = _mock_response(200, {"_embedded": {"status": status}})
        manager = MagicMock()
        manager.can_resume.return_value = False

        with _patched_session(session), pytest.raises(VeracodeReportError):
            list(get_rows("id", "secret", "com", "scans", MagicMock(), manager))


class TestVeracodeSourceResponse:
    @parameterized.expand(list(VERACODE_ENDPOINTS.keys()))
    def test_source_response_matches_endpoint_config(self, endpoint: str) -> None:
        config = VERACODE_ENDPOINTS[endpoint]
        response = veracode_source("id", "secret", "com", endpoint, MagicMock(), MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # The scans report order is undocumented, so only the applications read promises ascending order.
        assert response.sort_mode == (None if endpoint == "scans" else "asc")
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand([("forbidden", 403, False)])
    def test_status_maps_to_ok_flag(self, _name: str, status_code: int, expected_ok: bool) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code)
        with _patched_session(session):
            ok, returned_status = validate_credentials("id", "secret", "com")
        assert ok is expected_ok
        assert returned_status == status_code


class _patched_session:
    """Context manager patching `_make_session` so tests inject a mock requests session."""

    def __init__(self, session: MagicMock):
        self._session = session
        self._patcher: Any = None

    def __enter__(self) -> MagicMock:
        from unittest.mock import patch

        self._patcher = patch(
            "products.warehouse_sources.sources.veracode.veracode._make_session",
            return_value=self._session,
        )
        self._patcher.start()
        return self._session

    def __exit__(self, *args: Any) -> None:
        self._patcher.stop()
