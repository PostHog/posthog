from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.matomo import (
    VISITS_PAGE_SIZE,
    MatomoResumeConfig,
    get_rows,
    hostname_of,
    matomo_source,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.settings import (
    DEFAULT_BACKFILL_DAYS,
    ENDPOINTS,
    MATOMO_ENDPOINTS,
    REPORT_LOOKBACK_DAYS,
    VISIT_FINALITY_WINDOW_SECONDS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.matomo.matomo"


def _make_manager(resume_state: MatomoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = status_code < 400
    return resp


def _now_ts() -> int:
    return int(datetime.now(tz=UTC).timestamp())


def _final_ts(offset_seconds: int = 0) -> int:
    # A timestamp safely older than the finality window.
    return int(datetime.now(tz=UTC).timestamp()) - VISIT_FINALITY_WINDOW_SECONDS - 100 - offset_seconds


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://myorg.matomo.cloud", "https://myorg.matomo.cloud"),
            ("myorg.matomo.cloud", "https://myorg.matomo.cloud"),
            ("https://analytics.example.com/", "https://analytics.example.com"),
            ("http://analytics.internal:8080", "http://analytics.internal:8080"),
        ],
    )
    def test_valid_hosts(self, value, expected):
        assert normalize_host(value) == expected

    @pytest.mark.parametrize("value", ["", "   ", "ftp://example.com", "https://"])
    def test_invalid_hosts_raise(self, value):
        with pytest.raises(ValueError):
            normalize_host(value)

    def test_hostname_of(self):
        assert hostname_of("https://myorg.matomo.cloud/path") == "myorg.matomo.cloud"


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_credentials(self, mock_session):
        mock_session.return_value.post.return_value = _response({"idsite": "1", "name": "My site"})

        assert validate_credentials("https://myorg.matomo.cloud", "1", "token") is True
        body = mock_session.return_value.post.call_args.kwargs["data"]
        assert body["method"] == "SitesManager.getSiteFromId"
        assert body["token_auth"] == "token"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_error_envelope_fails_validation(self, mock_session):
        mock_session.return_value.post.return_value = _response({"result": "error", "message": "bad token"})

        assert validate_credentials("https://myorg.matomo.cloud", "1", "bad") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_http_error_fails_validation(self, mock_session):
        mock_session.return_value.post.return_value = _response({}, status_code=403)

        assert validate_credentials("https://myorg.matomo.cloud", "1", "token") is False


@mock.patch(f"{_MODULE}.time.sleep")
class TestVisits:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_backfill_walks_the_default_window_day_by_day(self, mock_session, mock_sleep):
        # Asking for the whole backfill window in one request is what the instance's gateway
        # answers 502 to, identically on every retry, so the backfill never gets past it.
        mock_session.return_value.post.return_value = _response([])

        list(get_rows("https://m.example.com", "1", "token", "visits", mock.MagicMock(), _make_manager()))

        bodies = [call.kwargs["data"] for call in mock_session.return_value.post.call_args_list]
        today = datetime.now(tz=UTC).date()
        assert {body["period"] for body in bodies} == {"day"}
        assert [body["date"] for body in bodies] == [
            (today - timedelta(days=DEFAULT_BACKFILL_DAYS - offset)).isoformat()
            for offset in range(DEFAULT_BACKFILL_DAYS + 1)
        ]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_short_batch_yields_and_moves_to_the_next_day(self, mock_session, mock_sleep):
        ts = _final_ts()
        watermark = _now_ts()
        mock_session.return_value.post.return_value = _response(
            [{"idVisit": "1", "serverTimestamp": ts}, {"idVisit": "2", "serverTimestamp": ts + 1}]
        )

        manager = _make_manager()
        batches = list(
            get_rows(
                "https://m.example.com",
                "1",
                "token",
                "visits",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )
        )

        assert [len(batch) for batch in batches] == [2, 2]
        body = mock_session.return_value.post.call_args_list[0].kwargs["data"]
        assert body["method"] == "Live.getLastVisitsDetails"
        assert body["filter_sort_order"] == "asc"
        assert body["minTimestamp"] == watermark
        assert body["token_auth"] == "token"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_page_advances_min_timestamp_cursor_within_the_day(self, mock_session, mock_sleep):
        base = _final_ts(10_000)
        first_page = [{"idVisit": str(i), "serverTimestamp": base + i} for i in range(VISITS_PAGE_SIZE)]
        second_page = [{"idVisit": "last", "serverTimestamp": base + VISITS_PAGE_SIZE}]
        mock_session.return_value.post.side_effect = [
            _response(first_page),
            _response(second_page),
            *[_response([]) for _ in range(10)],
        ]

        manager = _make_manager()
        batches = list(
            get_rows(
                "https://m.example.com",
                "1",
                "token",
                "visits",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=base - 60,
            )
        )

        assert [len(batch) for batch in batches] == [VISITS_PAGE_SIZE, 1]
        bodies = [call.kwargs["data"] for call in mock_session.return_value.post.call_args_list]
        # The second request pages within the same day; the third has moved on.
        assert bodies[1]["date"] == bodies[0]["date"]
        assert bodies[1]["minTimestamp"] == base + VISITS_PAGE_SIZE - 1
        assert bodies[2]["date"] > bodies[0]["date"]
        assert manager.save_state.call_args_list[0].args[0] == MatomoResumeConfig(
            min_timestamp=base + VISITS_PAGE_SIZE - 1, next_date=bodies[0]["date"]
        )

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_page_at_one_timestamp_steps_past_cursor(self, mock_session, mock_sleep):
        # minTimestamp is inclusive, so a full page whose visits all share the
        # same second must step the cursor forward or it would refetch forever.
        ts = _final_ts(10_000)
        first_page = [{"idVisit": str(i), "serverTimestamp": ts} for i in range(VISITS_PAGE_SIZE)]
        second_page = [{"idVisit": "last", "serverTimestamp": ts + 5}]
        mock_session.return_value.post.side_effect = [
            _response(first_page),
            _response(second_page),
            *[_response([]) for _ in range(10)],
        ]

        manager = _make_manager()
        batches = list(
            get_rows(
                "https://m.example.com",
                "1",
                "token",
                "visits",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=ts - 60,
            )
        )

        assert [len(batch) for batch in batches] == [VISITS_PAGE_SIZE, 1]
        assert mock_session.return_value.post.call_args_list[1].kwargs["data"]["minTimestamp"] == ts + 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_still_active_visits_are_deferred(self, mock_session, mock_sleep):
        now = int(datetime.now(tz=UTC).timestamp())
        mock_session.return_value.post.return_value = _response(
            [
                {"idVisit": "done", "serverTimestamp": _final_ts()},
                {"idVisit": "active", "serverTimestamp": now - 10},
            ]
        )

        batches = list(
            get_rows(
                "https://m.example.com",
                "1",
                "token",
                "visits",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=_now_ts(),
            )
        )

        assert {row["idVisit"] for batch in batches for row in batch} == {"done"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_watermark_sets_min_timestamp_and_start_day(self, mock_session, mock_sleep):
        mock_session.return_value.post.return_value = _response([])
        watermark = _now_ts()

        list(
            get_rows(
                "https://m.example.com",
                "1",
                "token",
                "visits",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )
        )

        body = mock_session.return_value.post.call_args_list[0].kwargs["data"]
        assert body["minTimestamp"] == watermark
        # A day earlier than the watermark, because `period=day` resolves in the site's timezone.
        assert body["date"] == (datetime.now(tz=UTC).date() - timedelta(days=1)).isoformat()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_state_supersedes_older_watermark(self, mock_session, mock_sleep):
        mock_session.return_value.post.return_value = _response([])
        resumed = _now_ts()

        manager = _make_manager(MatomoResumeConfig(min_timestamp=resumed))
        list(
            get_rows(
                "https://m.example.com",
                "1",
                "token",
                "visits",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=resumed - 86_400,
            )
        )

        assert mock_session.return_value.post.call_args_list[0].kwargs["data"]["minTimestamp"] == resumed

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_day_restarts_the_walk_where_it_stopped(self, mock_session, mock_sleep):
        mock_session.return_value.post.return_value = _response([])
        today = datetime.now(tz=UTC).date()

        manager = _make_manager(MatomoResumeConfig(min_timestamp=1, next_date=today.isoformat()))
        list(get_rows("https://m.example.com", "1", "token", "visits", mock.MagicMock(), manager))

        assert mock_session.return_value.post.call_count == 1
        assert mock_session.return_value.post.call_args.kwargs["data"]["date"] == today.isoformat()


@mock.patch(f"{_MODULE}.time.sleep")
class TestReports:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_walks_days_oldest_first_and_injects_date(self, mock_session, mock_sleep):
        mock_session.return_value.post.return_value = _response({"nb_visits": 5})

        manager = _make_manager()
        batches = list(
            get_rows(
                "https://m.example.com",
                "1",
                "token",
                "visits_summary",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime.now(tz=UTC).date().isoformat(),
            )
        )

        # Lookback window: REPORT_LOOKBACK_DAYS + 1 days, one row per day.
        assert len(batches) == REPORT_LOOKBACK_DAYS + 1
        dates = [batch[0]["_date"] for batch in batches]
        assert dates == sorted(dates)
        assert all(batch[0]["nb_visits"] == 5 for batch in batches)
        first_body = mock_session.return_value.post.call_args_list[0].kwargs["data"]
        assert first_body["period"] == "day"
        assert first_body["method"] == "VisitsSummary.get"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_list_reports_yield_rows_per_day(self, mock_session, mock_sleep):
        mock_session.return_value.post.return_value = _response([{"label": "Direct"}, {"label": "Search"}])

        batches = list(
            get_rows(
                "https://m.example.com",
                "1",
                "token",
                "referrers",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime.now(tz=UTC).date().isoformat(),
            )
        )

        assert all(len(batch) == 2 for batch in batches)
        assert all("_date" in row for batch in batches for row in batch)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_date_supersedes_older_start(self, mock_session, mock_sleep):
        mock_session.return_value.post.return_value = _response({})

        today = datetime.now(tz=UTC).date().isoformat()
        manager = _make_manager(MatomoResumeConfig(next_date=today))
        list(get_rows("https://m.example.com", "1", "token", "visits_summary", mock.MagicMock(), manager))

        assert mock_session.return_value.post.call_count == 1
        assert mock_session.return_value.post.call_args.kwargs["data"]["date"] == today

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_api_error_envelope_raises(self, mock_session, mock_sleep):
        mock_session.return_value.post.return_value = _response({"result": "error", "message": "no access"})

        with pytest.raises(ValueError, match="no access"):
            list(
                get_rows(
                    "https://m.example.com",
                    "1",
                    "token",
                    "visits_summary",
                    mock.MagicMock(),
                    _make_manager(MatomoResumeConfig(next_date=datetime.now(tz=UTC).date().isoformat())),
                )
            )


class TestMatomoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = MATOMO_ENDPOINTS[endpoint]
        response = matomo_source("https://m.example.com", "1", "token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize(
        "endpoint,expected_mode,expected_keys,expected_format",
        [
            # visits' primary key idVisit is an incrementing int, so it must ship an explicit
            # datetime scheme — otherwise the pipeline buckets one Delta partition per visit.
            ("visits", "datetime", ["serverTimestamp"], "month"),
            ("visits_summary", None, None, None),
            ("referrers", None, None, None),
        ],
    )
    def test_partition_scheme_per_endpoint(self, endpoint, expected_mode, expected_keys, expected_format):
        response = matomo_source("https://m.example.com", "1", "token", endpoint, mock.MagicMock(), _make_manager())

        assert response.partition_mode == expected_mode
        assert response.partition_keys == expected_keys
        assert response.partition_format == expected_format
        # partition_size=1 is what caused the per-row explosion; it must never come back.
        assert response.partition_size is None
        assert response.partition_count is None
