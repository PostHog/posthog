from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.taboola.settings import (
    ENDPOINTS,
    REPORT_LOOKBACK_DAYS,
    TABOOLA_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.taboola.taboola import (
    TaboolaResumeConfig,
    _to_date,
    get_rows,
    taboola_source,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.taboola.taboola"


def _make_manager(resume_state: TaboolaResumeConfig | None = None) -> mock.MagicMock:
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


def _token_response() -> mock.MagicMock:
    return _response({"access_token": "tok-1", "token_type": "bearer", "expires_in": 3600})


class TestToDate:
    @pytest.mark.parametrize(
        "value, expected_iso",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02"),
            (date(2024, 1, 2), "2024-01-02"),
            ("2024-01-02", "2024-01-02"),
            ("2024-01-02T03:04:05Z", "2024-01-02"),
            ("junk", None),
            (None, None),
        ],
    )
    def test_parses(self, value, expected_iso):
        result = _to_date(value)
        assert (result.isoformat() if result else None) == expected_iso


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_credentials_mint_a_token(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()

        assert validate_credentials("cid", "sec") is True
        body = mock_session.return_value.post.call_args.kwargs["data"]
        assert body == {"client_id": "cid", "client_secret": "sec", "grant_type": "client_credentials"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_credentials(self, mock_session):
        response = _response({}, status_code=401)
        response.raise_for_status.side_effect = Exception("401")
        mock_session.return_value.post.return_value = response

        assert validate_credentials("cid", "bad") is False


class TestEntityEndpoints:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_mid_sync_401_re_mints_token(self, mock_session):
        mock_session.return_value.post.side_effect = [_token_response(), _token_response()]
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=401),
            _response({"results": [{"id": "1"}]}),
        ]

        batches = list(get_rows("cid", "sec", "acct", "conversion_rules", mock.MagicMock(), _make_manager()))

        assert batches == [[{"id": "1"}]]
        assert mock_session.return_value.post.call_count == 2

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_initial_token_mint_retries_on_transient_error(self, mock_session, _sleep):
        mock_session.return_value.post.side_effect = [
            _response({}, status_code=503),
            _token_response(),
        ]
        mock_session.return_value.get.return_value = _response({"results": [{"id": "1"}]})

        batches = list(get_rows("cid", "sec", "acct", "campaigns", mock.MagicMock(), _make_manager()))

        assert batches == [[{"id": "1"}]]
        assert mock_session.return_value.post.call_count == 2


class TestCampaignItemsFanOut:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_campaign_index(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _response({"results": [{"id": 11}, {"id": 22}]}),
            _response({"results": [{"id": "i2"}]}),
        ]

        manager = _make_manager(TaboolaResumeConfig(next_campaign_index=1))
        batches = list(get_rows("cid", "sec", "acct", "campaign_items", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["i2"]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert len(urls) == 2
        assert urls[1].endswith("/acct/campaigns/22/items/")


class TestReportWindows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_walks_windows_from_default_backfill(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"results": [{"date": "2024-01-01", "campaign": "1"}]})

        manager = _make_manager()
        batches = list(get_rows("cid", "sec", "acct", "campaign_summary_by_day", mock.MagicMock(), manager))

        assert len(batches) > 1
        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "start_date=" in first_url and "end_date=" in first_url
        # Walked oldest-first: every saved window start moves forward.
        starts = [call.args[0].next_window_start for call in manager.save_state.call_args_list]
        assert starts == sorted(starts)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_starts_lookback_before_watermark(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"results": []})

        watermark = datetime.now(tz=UTC).date()
        list(
            get_rows(
                "cid",
                "sec",
                "acct",
                "campaign_summary_by_day",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark.isoformat(),
            )
        )

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        expected_start = (watermark - timedelta(days=REPORT_LOOKBACK_DAYS)).isoformat()
        assert f"start_date={expected_start}" in first_url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_window_start_supersedes_older_start(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"results": []})

        resume_start = datetime.now(tz=UTC).date().isoformat()
        manager = _make_manager(TaboolaResumeConfig(next_window_start=resume_start))
        list(get_rows("cid", "sec", "acct", "campaign_summary_by_day", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert f"start_date={resume_start}" in first_url
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_snapshot_report_uses_trailing_window_single_fetch(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"results": [{"campaign": "1", "item": "9"}]})

        manager = _make_manager()
        batches = list(get_rows("cid", "sec", "acct", "top_campaign_content", mock.MagicMock(), manager))

        assert batches == [[{"campaign": "1", "item": "9"}]]
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()


class TestTaboolaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = TABOOLA_ENDPOINTS[endpoint]
        response = taboola_source("cid", "sec", "acct", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
