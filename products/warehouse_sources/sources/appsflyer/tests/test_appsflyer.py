from datetime import UTC, date, datetime, timedelta

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.appsflyer import (
    CHUNK_SIZE,
    LOOKBACK_DAYS,
    MASTER_MAX_LOOKBACK_DAYS,
    MASTER_MAX_REQUEST_DAYS,
    RAW_LOOKBACK_DAYS,
    RAW_MAX_LOOKBACK_DAYS,
    RAW_MAX_REQUEST_DAYS,
    AppsFlyerCredentialsError,
    AppsFlyerRetryableError,
    _normalize_header,
    _parse_csv_rows,
    _to_date,
    _validate_app_id,
    appsflyer_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.settings import APPSFLYER_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.source import AppsFlyerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appsflyer import (
    AppsFlyerSourceConfig,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.appsflyer"

_CSV = (
    "Date,Agency/PMD (af_prt),Media Source (pid),Campaign (c),Impressions,Clicks\n"
    "2024-01-01,agency,google,brand,100,10\n"
    "2024-01-02,agency,meta,retargeting,200,20\n"
)


def _driver() -> SourceDriver:
    return SourceDriver(AppsFlyerSource(), AppsFlyerSourceConfig(app_id="id123", api_token="token"))


def _csv_response(body: str = _CSV) -> ScriptedResponse:
    return ScriptedResponse(body=body.encode())


def _requested_windows(result: DriveResult) -> list[tuple[date, date]]:
    windows = []
    for request in result.requests:
        start = request.param("from")
        end = request.param("to")
        assert start is not None
        assert end is not None
        windows.append((date.fromisoformat(start), date.fromisoformat(end)))
    return windows


class TestHelpers:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ("Date", "date"),
            ("Media Source (pid)", "media_source_pid"),
            ("Agency/PMD (af_prt)", "agency_pmd_af_prt"),
            ("Campaign (c)", "campaign_c"),
            ("Click-Through Rate", "click_through_rate"),
        ],
    )
    def test_normalize_header(self, header, expected):
        assert _normalize_header(header) == expected

    def test_parse_csv_rows(self):
        rows = list(_parse_csv_rows(_CSV))
        assert rows[0]["date"] == "2024-01-01"
        assert rows[0]["media_source_pid"] == "google"
        assert rows[1]["campaign_c"] == "retargeting"

    def test_parse_csv_skips_blank_lines(self):
        rows = list(_parse_csv_rows(_CSV + ",,,,,\n"))
        assert len(rows) == 2

    def test_parse_csv_skips_rows_with_mismatched_length(self):
        # A short row would let zip silently drop primary-key columns; it must be skipped.
        logger = mock.MagicMock()
        rows = list(_parse_csv_rows(_CSV + "2024-01-03,agency,google\n", logger))
        assert len(rows) == 2
        logger.warning.assert_called_once()

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2024-01-02", date(2024, 1, 2)),
            ("2024-01-02T03:04:05Z", date(2024, 1, 2)),
            (date(2024, 1, 2), date(2024, 1, 2)),
            (datetime(2024, 1, 2, 3, tzinfo=UTC), date(2024, 1, 2)),
        ],
    )
    def test_to_date(self, value, expected):
        assert _to_date(value) == expected

    @pytest.mark.parametrize("value", ["", "bad app", "app?id"])
    def test_invalid_app_ids_raise(self, value):
        with pytest.raises(ValueError):
            _validate_app_id(value)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_substring",
        [
            # 401 means the token is bad; 403/404 mean the app id (or subscription) is the problem.
            (401, "API token"),
            (403, "denied access"),
            (404, "app id"),
        ],
    )
    def test_validate_credentials_distinguishes_token_from_app_id(
        self, status_code: int, expected_substring: str
    ) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]):
            with pytest.raises(AppsFlyerCredentialsError) as exc:
                validate_credentials("token", "id123")
        assert expected_substring in str(exc.value)

    @pytest.mark.parametrize(
        "body, expected_reason",
        [
            ("Pull API is not enabled\nfor this account", "AppsFlyer said: Pull API is not enabled for this account"),
            ("token secret-token is not allowed", "AppsFlyer said: token [redacted] is not allowed"),
            ("<html><body>Forbidden</body></html>", None),
            ("Forbidden: <!DOCTYPE html><html><body>Denied</body></html>", None),
        ],
    )
    def test_validate_credentials_surfaces_appsflyer_reason(self, body: str, expected_reason: str | None) -> None:
        with scripted_network([ScriptedResponse(status=403, body=body.encode())]):
            with pytest.raises(AppsFlyerCredentialsError) as exc:
                validate_credentials("Bearer secret-token", "id123")
        message = str(exc.value)
        if expected_reason is None:
            assert "AppsFlyer said" not in message
        else:
            assert message.endswith(expected_reason)
        assert "secret-token" not in message

    @pytest.mark.parametrize("api_token", [" token ", "Bearer token", "bearer  token"])
    def test_validate_credentials_sends_a_clean_token_and_ios_app_id(self, api_token: str) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials(api_token, "123456789")

        request = network.requests_log[0]
        assert request.headers["authorization"] == "Bearer token"
        assert "/app/id123456789/" in request.path

    @pytest.mark.parametrize(
        "api_token, app_id, expected_substring",
        [
            ("token", "bad app!", "app id"),
            ("token\u201d", "id123", "API token"),
            ("\u201ctoken\u201d", "id123", "API token"),
        ],
    )
    def test_validate_rejects_bad_input_without_request(
        self, api_token: str, app_id: str, expected_substring: str
    ) -> None:
        with scripted_network([]) as network:
            with pytest.raises(AppsFlyerCredentialsError) as exc:
                validate_credentials(api_token, app_id)
        assert expected_substring in str(exc.value)
        assert network.requests_log == []

    @pytest.mark.parametrize("status_code", [400, 418, 451])
    def test_validate_raises_with_status_on_unexpected_code(self, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]):
            with pytest.raises(AppsFlyerCredentialsError) as exc:
                validate_credentials("token", "id123")
        assert str(status_code) in str(exc.value)

    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_validate_raises_on_transient_status(self, status_code: int) -> None:
        # Rate-limit / 5xx are transient; the caller must be able to tell them from a bad token.
        with scripted_network(always(ScriptedResponse(status=status_code))):
            with pytest.raises(AppsFlyerRetryableError):
                validate_credentials("token", "id123")


class TestGetRows:
    @pytest.mark.parametrize(
        "endpoint, expected_path",
        [
            ("daily_report", "/api/agg-data/export/app/id123/daily_report/v5"),
            ("geo_report", "/api/agg-data/export/app/id123/geo_by_date_report/v5"),
            ("partners_report", "/api/agg-data/export/app/id123/partners_by_date_report/v5"),
            ("installs", "/api/raw-data/export/app/id123/installs_report/v5"),
            ("installs_organic", "/api/raw-data/export/app/id123/organic_installs_report/v5"),
            # AppsFlyer spells the retargeting slugs with hyphens while every other raw report
            # uses underscores, so a "consistent" rename here 404s.
            ("installs_retargeting", "/api/raw-data/export/app/id123/installs-retarget/v5"),
            ("in_app_events", "/api/raw-data/export/app/id123/in_app_events_report/v5"),
            ("in_app_events_organic", "/api/raw-data/export/app/id123/organic_in_app_events_report/v5"),
            ("in_app_events_retargeting", "/api/raw-data/export/app/id123/in-app-events-retarget/v5"),
            ("uninstall_events", "/api/raw-data/export/app/id123/uninstall_events_report/v5"),
            ("blocked_installs", "/api/raw-data/export/app/id123/blocked_installs_report/v5"),
            ("blocked_in_app_events", "/api/raw-data/export/app/id123/blocked_in_app_events_report/v5"),
            ("post_attribution_installs", "/api/raw-data/export/app/id123/detection/v5"),
            ("ad_revenue", "/api/raw-data/export/app/id123/ad_revenue_raw/v5"),
            ("ad_revenue_organic", "/api/raw-data/export/app/id123/ad_revenue_organic_raw/v5"),
            ("ad_revenue_retargeting", "/api/raw-data/export/app/id123/ad-revenue-raw-retarget/v5"),
            ("master_report", "/api/master-agg-data/v4/app/id123"),
        ],
    )
    def test_report_slug_matches_appsflyer_api(self, endpoint: str, expected_path: str) -> None:
        result = _driver().run(endpoint, always(_csv_response()))

        assert result.raised is None
        assert result.paths
        assert all(path == expected_path for path in result.paths)

    def test_incremental_starts_at_watermark_minus_lookback(self) -> None:
        watermark = datetime.now(UTC).date()

        result = _driver().run(
            "daily_report",
            [_csv_response()],
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        expected_from = watermark.toordinal() - LOOKBACK_DAYS
        start = result.params("from")[0]
        assert start is not None
        assert date.fromisoformat(start).toordinal() == expected_from

    def test_rows_are_chunked(self) -> None:
        header = "Date,Agency/PMD (af_prt),Media Source (pid),Campaign (c)\n"
        body = "".join(f"2024-01-01,a,m,c{i}\n" for i in range(CHUNK_SIZE + 1))

        result = _driver().run("daily_report", [_csv_response(header + body)])

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [CHUNK_SIZE, 1]

    def test_requests_csv_explicitly(self) -> None:
        result = _driver().run("daily_report", [_csv_response()])

        assert result.raised is None
        headers = result.session_options[0]["headers"]
        assert headers["Accept"] == "text/csv"


class TestRawAndMasterWindows:
    def test_raw_pull_walks_contiguous_windows_inside_the_lookback_limit(self) -> None:
        # AppsFlyer refuses a raw window starting more than 90 days back, and the windows have to
        # tile the range exactly once: a gap loses rows, an overlap re-merges them, and a window
        # that doesn't advance loops forever.
        today = datetime.now(UTC).date()

        result = _driver().run("installs", always(_csv_response()))

        assert result.raised is None
        windows = _requested_windows(result)
        assert windows[0][0] == today - timedelta(days=RAW_MAX_LOOKBACK_DAYS)
        assert windows[-1][1] == today
        for window_start, window_end in windows:
            assert 0 <= (window_end - window_start).days < RAW_MAX_REQUEST_DAYS
        for (_, previous_end), (next_start, _) in zip(windows, windows[1:]):
            assert next_start == previous_end + timedelta(days=1)

    def test_master_pull_never_exceeds_the_31_day_call_limit(self) -> None:
        # The Master API rejects a range wider than 31 days, so the backfill has to be windowed.
        today = datetime.now(UTC).date()

        result = _driver().run("master_report", always(_csv_response()))

        assert result.raised is None
        windows = _requested_windows(result)
        assert windows[0][0] == today - timedelta(days=MASTER_MAX_LOOKBACK_DAYS)
        assert windows[-1][1] == today
        for window_start, window_end in windows:
            assert 0 <= (window_end - window_start).days < MASTER_MAX_REQUEST_DAYS

    @pytest.mark.parametrize("endpoint", ["installs", "in_app_events", "ad_revenue"])
    def test_raw_incremental_repulls_a_whole_window_before_the_watermark(self, endpoint: str) -> None:
        # A worker shutdown can interrupt a window part-way through, and AppsFlyer documents no row
        # order within one, so the next run has to start far enough back to redo the whole window.
        watermark = datetime.now(UTC).date() - timedelta(days=10)

        result = _driver().run(
            endpoint,
            always(_csv_response()),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        windows = _requested_windows(result)
        assert windows[0][0] == watermark - timedelta(days=RAW_LOOKBACK_DAYS)
        assert RAW_LOOKBACK_DAYS >= RAW_MAX_REQUEST_DAYS

    def test_ad_revenue_pull_requests_its_monetization_dimensions(self) -> None:
        # monetization_network / ad_unit / placement are additional fields, and they make up the
        # row key — without them every revenue row for a user collapses onto one key.
        result = _driver().run("ad_revenue", always(_csv_response()))

        assert result.raised is None
        additional_fields = result.params("additional_fields")[0]
        assert additional_fields is not None
        requested = set(additional_fields.split(","))
        assert {"monetization_network", "ad_unit", "placement"} <= requested
        assert set(APPSFLYER_ENDPOINTS["ad_revenue"].primary_keys) - {"appsflyer_id", "event_time"} <= requested

    @pytest.mark.parametrize(
        "endpoint, expected_field",
        [
            ("blocked_installs", "blocked_reason"),
            ("blocked_in_app_events", "blocked_reason"),
            ("post_attribution_installs", "fraud_reason"),
            ("post_attribution_installs", "detection_date"),
        ],
    )
    def test_protect360_pull_requests_its_fraud_columns(self, endpoint: str, expected_field: str) -> None:
        # The fraud classification is an additional field, so a report pulled without asking for it
        # comes back saying nothing about why the row was blocked.
        result = _driver().run(endpoint, always(_csv_response()))

        assert result.raised is None
        additional_fields = result.params("additional_fields")[0]
        assert additional_fields is not None
        assert expected_field in additional_fields.split(",")

    def test_master_pull_sends_groupings_and_kpis(self) -> None:
        # The Master API rejects a request that omits either one.
        result = _driver().run("master_report", always(_csv_response()))

        assert result.raised is None
        groupings = result.params("groupings")[0]
        kpis = result.params("kpis")[0]
        assert groupings is not None
        assert kpis is not None
        assert "install_time" in groupings.split(",")
        assert "installs" in kpis.split(",")

    @mock.patch(f"{_MODULE}.RAW_MAX_ROWS", 2)
    def test_warns_when_a_raw_window_fills_the_row_cap(self):
        # AppsFlyer drops the rest of the window silently, so the sync has to say so.
        logger = mock.MagicMock()

        result = _driver().run("installs", always(_csv_response()), logger=logger)

        assert result.raised is None
        assert set(result.params("maximum_rows")) == {"2"}
        assert logger.warning.called

    def test_value_with_an_embedded_newline_survives_streaming(self) -> None:
        # Raw event values carry newlines; splitting the body into lines would tear the row apart.
        csv_body = 'AppsFlyer ID,Event Time,Event Value\naf-1,2024-01-01 00:00:00,"line one\nline two"\n'

        result = _driver().run("installs", always(_csv_response(csv_body)))

        assert result.raised is None
        assert result.rows[0] == {
            "appsflyer_id": "af-1",
            "event_time": "2024-01-01 00:00:00",
            "event_value": "line one\nline two",
        }


class TestAppsFlyerSourceResponse:
    def test_geo_report_key_includes_country(self):
        response = appsflyer_source("token", "id123", "geo_report", mock.MagicMock())
        assert "country" in (response.primary_keys or [])
