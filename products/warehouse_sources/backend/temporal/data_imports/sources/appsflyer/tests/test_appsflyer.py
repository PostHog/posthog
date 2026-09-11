import io
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import validate_incremental_sync
from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.appsflyer import (
    CHUNK_SIZE,
    LOOKBACK_DAYS,
    MASTER_MAX_LOOKBACK_DAYS,
    MASTER_MAX_REQUEST_DAYS,
    MAX_WINDOW_DAYS,
    RAW_LOOKBACK_DAYS,
    RAW_MAX_LOOKBACK_DAYS,
    RAW_MAX_REQUEST_DAYS,
    RAW_MAX_ROWS,
    AppsFlyerCredentialsError,
    AppsFlyerRetryableError,
    _normalize_header,
    _parse_csv_rows,
    _to_date,
    _validate_app_id,
    appsflyer_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.settings import (
    APPSFLYER_ENDPOINTS,
    ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.appsflyer"

_CSV = (
    "Date,Agency/PMD (af_prt),Media Source (pid),Campaign (c),Impressions,Clicks\n"
    "2024-01-01,agency,google,brand,100,10\n"
    "2024-01-02,agency,meta,retargeting,200,20\n"
)


class _Raw(io.BytesIO):
    """Stands in for urllib3's raw stream, which the transport sets `decode_content` on."""

    decode_content = False


def _response(text: str, status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.text = text
    resp.raw = _Raw(text.encode())
    resp.status_code = status
    resp.ok = status < 400
    return resp


def _serve(text: str = _CSV, status: int = 200):
    """A fresh response per call, since each request consumes its own stream."""
    return lambda *args, **kwargs: _response(text, status)


def _requested_windows(mock_session: mock.MagicMock) -> list[tuple[date, date]]:
    windows = []
    for call in mock_session.return_value.get.call_args_list:
        query = parse_qs(urlparse(call.args[0]).query)
        windows.append((date.fromisoformat(query["from"][0]), date.fromisoformat(query["to"][0])))
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
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_succeeds_on_200(self, mock_session):
        mock_session.return_value.get.return_value = _response("", status=200)

        assert validate_credentials("token", "id123") is True

    @pytest.mark.parametrize(
        "status_code, expected_substring",
        [
            # 401 means the token is bad; 403/404 mean the app id (or subscription) is the problem.
            (401, "API token"),
            (403, "denied access"),
            (404, "app id"),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_distinguishes_token_from_app_id(self, mock_session, status_code, expected_substring):
        mock_session.return_value.get.return_value = _response("", status=status_code)

        with pytest.raises(AppsFlyerCredentialsError) as exc:
            validate_credentials("token", "id123")
        assert expected_substring in str(exc.value)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_rejects_bad_app_id_without_request(self, mock_session):
        with pytest.raises(AppsFlyerCredentialsError) as exc:
            validate_credentials("token", "bad app!")
        assert "app id" in str(exc.value)
        mock_session.return_value.get.assert_not_called()

    @pytest.mark.parametrize("status_code", [400, 418, 451])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_raises_with_status_on_unexpected_code(self, mock_session, status_code):
        mock_session.return_value.get.return_value = _response("", status=status_code)

        with pytest.raises(AppsFlyerCredentialsError) as exc:
            validate_credentials("token", "id123")
        assert str(status_code) in str(exc.value)

    @pytest.mark.parametrize("status_code", [429, 500, 503])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_raises_on_transient_status(self, mock_session, status_code):
        # Rate-limit / 5xx are transient; the caller must be able to tell them from a bad token.
        mock_session.return_value.get.return_value = _response("", status=status_code)

        with pytest.raises(AppsFlyerRetryableError):
            validate_credentials("token", "id123")


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_pull_uses_max_window(self, mock_session):
        mock_session.return_value.get.side_effect = _serve()

        batches = list(get_rows("token", "id123", "daily_report", mock.MagicMock()))

        flat = [row for batch in batches for row in batch]
        assert len(flat) == 2
        url = mock_session.return_value.get.call_args.args[0]
        query = parse_qs(urlparse(url).query)
        window = date.fromisoformat(query["to"][0]) - date.fromisoformat(query["from"][0])
        assert window.days == MAX_WINDOW_DAYS
        assert urlparse(url).path == "/api/agg-data/export/app/id123/daily_report/v5"

    @pytest.mark.parametrize(
        "endpoint, expected_path",
        [
            ("daily_report", "/api/agg-data/export/app/id123/daily_report/v5"),
            ("geo_report", "/api/agg-data/export/app/id123/geo_by_date_report/v5"),
            ("partners_report", "/api/agg-data/export/app/id123/partners_by_date_report/v5"),
            ("installs", "/api/raw-data/export/app/id123/installs_report/v5"),
            ("in_app_events", "/api/raw-data/export/app/id123/in_app_events_report/v5"),
            ("ad_revenue", "/api/raw-data/export/app/id123/ad_revenue_raw/v5"),
            ("ad_revenue_organic", "/api/raw-data/export/app/id123/ad_revenue_organic_raw/v5"),
            ("ad_revenue_retargeting", "/api/raw-data/export/app/id123/ad-revenue-raw-retarget/v5"),
            ("master_report", "/api/master-agg-data/v4/app/id123"),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_report_slug_matches_appsflyer_api(self, mock_session, endpoint, expected_path):
        mock_session.return_value.get.side_effect = _serve()

        list(get_rows("token", "id123", endpoint, mock.MagicMock()))

        for call in mock_session.return_value.get.call_args_list:
            assert urlparse(call.args[0]).path == expected_path

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_starts_at_watermark_minus_lookback(self, mock_session):
        mock_session.return_value.get.side_effect = _serve()
        watermark = datetime.now(UTC).date()

        list(
            get_rows(
                "token",
                "id123",
                "daily_report",
                mock.MagicMock(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        query = parse_qs(urlparse(url).query)
        expected_from = watermark.toordinal() - LOOKBACK_DAYS
        assert date.fromisoformat(query["from"][0]).toordinal() == expected_from

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rows_are_chunked(self, mock_session):
        header = "Date,Agency/PMD (af_prt),Media Source (pid),Campaign (c)\n"
        body = "".join(f"2024-01-01,a,m,c{i}\n" for i in range(CHUNK_SIZE + 1))
        mock_session.return_value.get.side_effect = _serve(header + body)

        batches = list(get_rows("token", "id123", "daily_report", mock.MagicMock()))

        assert [len(batch) for batch in batches] == [CHUNK_SIZE, 1]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_requests_csv_explicitly(self, mock_session):
        mock_session.return_value.get.side_effect = _serve()

        list(get_rows("token", "id123", "daily_report", mock.MagicMock()))

        headers = mock_session.call_args.kwargs["headers"]
        assert headers["Accept"] == "text/csv"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_report_yields_nothing(self, mock_session):
        mock_session.return_value.get.side_effect = _serve("Date,Media Source (pid)\n")

        assert list(get_rows("token", "id123", "daily_report", mock.MagicMock())) == []


class TestRawAndMasterWindows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_raw_pull_walks_contiguous_windows_inside_the_lookback_limit(self, mock_session):
        # AppsFlyer refuses a raw window starting more than 90 days back, and the windows have to
        # tile the range exactly once: a gap loses rows, an overlap re-merges them, and a window
        # that doesn't advance loops forever.
        mock_session.return_value.get.side_effect = _serve()
        today = datetime.now(UTC).date()

        list(get_rows("token", "id123", "installs", mock.MagicMock()))

        windows = _requested_windows(mock_session)
        assert windows[0][0] == today - timedelta(days=RAW_MAX_LOOKBACK_DAYS)
        assert windows[-1][1] == today
        for window_start, window_end in windows:
            assert 0 <= (window_end - window_start).days < RAW_MAX_REQUEST_DAYS
        for (_, previous_end), (next_start, _) in zip(windows, windows[1:]):
            assert next_start == previous_end + timedelta(days=1)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_master_pull_never_exceeds_the_31_day_call_limit(self, mock_session):
        # The Master API rejects a range wider than 31 days, so the backfill has to be windowed.
        mock_session.return_value.get.side_effect = _serve()
        today = datetime.now(UTC).date()

        list(get_rows("token", "id123", "master_report", mock.MagicMock()))

        windows = _requested_windows(mock_session)
        assert windows[0][0] == today - timedelta(days=MASTER_MAX_LOOKBACK_DAYS)
        assert windows[-1][1] == today
        for window_start, window_end in windows:
            assert 0 <= (window_end - window_start).days < MASTER_MAX_REQUEST_DAYS

    @pytest.mark.parametrize("endpoint", ["installs", "in_app_events", "ad_revenue"])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_raw_incremental_repulls_a_whole_window_before_the_watermark(self, mock_session, endpoint):
        # A worker shutdown can interrupt a window part-way through, and AppsFlyer documents no row
        # order within one, so the next run has to start far enough back to redo the whole window.
        mock_session.return_value.get.side_effect = _serve()
        watermark = datetime.now(UTC).date() - timedelta(days=10)

        list(
            get_rows(
                "token",
                "id123",
                endpoint,
                mock.MagicMock(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )
        )

        windows = _requested_windows(mock_session)
        assert windows[0][0] == watermark - timedelta(days=RAW_LOOKBACK_DAYS)
        assert RAW_LOOKBACK_DAYS >= RAW_MAX_REQUEST_DAYS

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_raw_pull_asks_for_the_larger_row_cap(self, mock_session):
        # Without maximum_rows AppsFlyer truncates at 200k rows per window.
        mock_session.return_value.get.side_effect = _serve()

        list(get_rows("token", "id123", "installs", mock.MagicMock()))

        query = parse_qs(urlparse(mock_session.return_value.get.call_args.args[0]).query)
        assert query["maximum_rows"] == [str(RAW_MAX_ROWS)]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_ad_revenue_pull_requests_its_monetization_dimensions(self, mock_session):
        # monetization_network / ad_unit / placement are additional fields, and they make up the
        # row key — without them every revenue row for a user collapses onto one key.
        mock_session.return_value.get.side_effect = _serve()

        list(get_rows("token", "id123", "ad_revenue", mock.MagicMock()))

        query = parse_qs(urlparse(mock_session.return_value.get.call_args.args[0]).query)
        requested = set(query["additional_fields"][0].split(","))
        assert {"monetization_network", "ad_unit", "placement"} <= requested
        assert set(APPSFLYER_ENDPOINTS["ad_revenue"].primary_keys) - {"appsflyer_id", "event_time"} <= requested

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_master_pull_sends_groupings_and_kpis(self, mock_session):
        # The Master API rejects a request that omits either one.
        mock_session.return_value.get.side_effect = _serve()

        list(get_rows("token", "id123", "master_report", mock.MagicMock()))

        query = parse_qs(urlparse(mock_session.return_value.get.call_args.args[0]).query)
        assert "install_time" in query["groupings"][0].split(",")
        assert "installs" in query["kpis"][0].split(",")

    @mock.patch(f"{_MODULE}.RAW_MAX_ROWS", 2)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_warns_when_a_raw_window_fills_the_row_cap(self, mock_session):
        # AppsFlyer drops the rest of the window silently, so the sync has to say so.
        mock_session.return_value.get.side_effect = _serve()
        logger = mock.MagicMock()

        list(get_rows("token", "id123", "installs", logger))

        assert logger.warning.called

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_value_with_an_embedded_newline_survives_streaming(self, mock_session):
        # Raw event values carry newlines; splitting the body into lines would tear the row apart.
        csv_body = 'AppsFlyer ID,Event Time,Event Value\naf-1,2024-01-01 00:00:00,"line one\nline two"\n'
        mock_session.return_value.get.side_effect = _serve(csv_body)

        rows = [row for batch in get_rows("token", "id123", "installs", mock.MagicMock()) for row in batch]

        assert rows[0] == {
            "appsflyer_id": "af-1",
            "event_time": "2024-01-01 00:00:00",
            "event_value": "line one\nline two",
        }


class TestAppsFlyerSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = APPSFLYER_ENDPOINTS[endpoint]
        response = appsflyer_source("token", "id123", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [config.partition_key]
        assert response.partition_format == config.partition_format
        # Dimension keys can collide (blank campaigns etc), but that's expected for report data
        # and must not block incremental syncing - regression test for the schema-wide incremental
        # sync outage this caused when has_duplicate_primary_keys was set unconditionally.
        assert not response.has_duplicate_primary_keys
        validate_incremental_sync(True, response)

    def test_geo_report_key_includes_country(self):
        response = appsflyer_source("token", "id123", "geo_report", mock.MagicMock())
        assert "country" in (response.primary_keys or [])
