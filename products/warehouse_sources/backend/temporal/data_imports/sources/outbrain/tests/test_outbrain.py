from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.outbrain import (
    PAGE_SIZE,
    OutbrainClientError,
    OutbrainResumeConfig,
    _token_cache_key,
    get_rows,
    outbrain_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.settings import (
    ENDPOINTS,
    OUTBRAIN_ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.outbrain"


def _make_manager(resume_state: OutbrainResumeConfig | None = None) -> mock.MagicMock:
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


def _no_cache() -> mock.MagicMock:
    cache = mock.MagicMock()
    cache.get.return_value = None
    return cache


class TestTokenCaching:
    def test_cache_key_is_stable_and_credential_scoped(self):
        assert _token_cache_key("u", "p") == _token_cache_key("u", "p")
        assert _token_cache_key("u", "p") != _token_cache_key("u", "other")

    @mock.patch(f"{_MODULE}.cache")
    @mock.patch(f"{_MODULE}.requests.get")
    def test_login_mints_and_caches_token(self, mock_get, mock_cache):
        mock_cache.get.return_value = None
        mock_get.return_value = _response({"OB-TOKEN-V1": "tok-1"})

        assert validate_credentials("u", "p") is True
        login_call = mock_get.call_args
        assert login_call.args[0] == "https://api.outbrain.com/amplify/v0.1/login"
        assert login_call.kwargs["auth"] == ("u", "p")
        mock_cache.set.assert_called_once()
        assert mock_cache.set.call_args.args[1] == "tok-1"

    @mock.patch(f"{_MODULE}.cache")
    @mock.patch(f"{_MODULE}.requests.get")
    def test_cached_token_skips_login(self, mock_get, mock_cache):
        # /login is capped at 2 requests/hour, so the cache must short-circuit.
        mock_cache.get.return_value = "tok-cached"

        assert validate_credentials("u", "p") is True
        mock_get.assert_not_called()

    @mock.patch(f"{_MODULE}.cache")
    @mock.patch(f"{_MODULE}.requests.get")
    def test_login_without_token_in_response_fails(self, mock_get, mock_cache):
        mock_cache.get.return_value = None
        mock_get.return_value = _response({"message": "nope"})

        assert validate_credentials("u", "p") is False


@mock.patch(f"{_MODULE}.cache")
class TestEntityStreams:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_marketers_single_fetch(self, mock_session, mock_cache):
        mock_cache.get.return_value = "tok"
        mock_session.return_value.get.return_value = _response({"marketers": [{"id": "m1"}, {"id": "m2"}]})

        batches = list(get_rows("u", "p", "marketers", mock.MagicMock(), _make_manager()))

        assert [row["id"] for batch in batches for row in batch] == ["m1", "m2"]
        url = mock_session.return_value.get.call_args.args[0]
        assert url == "https://api.outbrain.com/amplify/v0.1/marketers"
        assert mock_session.return_value.get.call_args.kwargs["headers"] == {"OB-TOKEN-V1": "tok"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_campaigns_fan_out_per_marketer_with_offset_pagination(self, mock_session, mock_cache):
        mock_cache.get.return_value = "tok"
        full_page = [{"id": f"c{i}"} for i in range(PAGE_SIZE)]
        mock_session.return_value.get.side_effect = [
            _response({"marketers": [{"id": "m1"}]}),
            _response({"campaigns": full_page}),
            _response({"campaigns": [{"id": "c-last"}]}),
        ]

        manager = _make_manager()
        batches = list(get_rows("u", "p", "campaigns", mock.MagicMock(), manager))

        assert [len(batch) for batch in batches] == [PAGE_SIZE, 1]
        assert all(row["_marketer_id"] == "m1" for batch in batches for row in batch)
        second_page_url = mock_session.return_value.get.call_args_list[2].args[0]
        assert f"offset={PAGE_SIZE}" in second_page_url
        assert [call.args[0].next_index for call in manager.save_state.call_args_list] == [1]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_promoted_links_fan_out_per_campaign(self, mock_session, mock_cache):
        mock_cache.get.return_value = "tok"
        mock_session.return_value.get.side_effect = [
            _response({"marketers": [{"id": "m1"}]}),
            _response({"campaigns": [{"id": "c1"}]}),
            _response({"promotedLinks": [{"id": "pl1"}]}),
        ]

        batches = list(get_rows("u", "p", "promoted_links", mock.MagicMock(), _make_manager()))

        flat = [row for batch in batches for row in batch]
        assert [(r["id"], r["_campaign_id"]) for r in flat] == [("pl1", "c1")]
        links_url = mock_session.return_value.get.call_args_list[2].args[0]
        assert "/campaigns/c1/promotedLinks" in links_url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_parent_index(self, mock_session, mock_cache):
        mock_cache.get.return_value = "tok"
        mock_session.return_value.get.side_effect = [
            _response({"marketers": [{"id": "m1"}, {"id": "m2"}]}),
            _response({"budgets": [{"id": "b2"}]}),
        ]

        manager = _make_manager(OutbrainResumeConfig(next_index=1))
        batches = list(get_rows("u", "p", "budgets", mock.MagicMock(), manager))

        flat = [row for batch in batches for row in batch]
        assert [r["_marketer_id"] for r in flat] == ["m2"]

    @mock.patch(f"{_MODULE}.requests.get")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_mid_sync_401_re_mints_token(self, mock_session, mock_get, mock_cache):
        mock_cache.get.return_value = "tok-stale"
        # The data requests run on the tracked session; the mid-sync re-mint
        # logs in on an untracked session (requests.get).
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=401),
            _response({"marketers": [{"id": "m1"}]}),
        ]
        mock_get.return_value = _response({"OB-TOKEN-V1": "tok-fresh"})

        batches = list(get_rows("u", "p", "marketers", mock.MagicMock(), _make_manager()))

        assert [row["id"] for batch in batches for row in batch] == ["m1"]
        retry_headers = mock_session.return_value.get.call_args_list[1].kwargs["headers"]
        assert retry_headers == {"OB-TOKEN-V1": "tok-fresh"}


@mock.patch(f"{_MODULE}.cache")
class TestReportStreams:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_periodic_report_injects_date_and_marketer(self, mock_session, mock_cache):
        mock_cache.get.return_value = "tok"
        mock_session.return_value.get.side_effect = [
            _response({"marketers": [{"id": "m1"}]}),
            _response(
                {
                    "results": [
                        {"metadata": {"fromDate": "2024-01-01"}, "metrics": {"clicks": 5}},
                        {"metadata": {"fromDate": "2024-01-02"}, "metrics": {"clicks": 7}},
                        {"metrics": {"clicks": 0}},  # no date — dropped
                    ]
                }
            ),
        ]

        manager = _make_manager()
        batches = list(get_rows("u", "p", "marketer_performance_daily", mock.MagicMock(), manager))

        flat = [row for batch in batches for row in batch]
        assert [(r["_date"], r["_marketer_id"]) for r in flat] == [("2024-01-01", "m1"), ("2024-01-02", "m1")]
        report_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "breakdown=daily" in report_url
        assert "from=" in report_url and "to=" in report_url
        assert [call.args[0].next_index for call in manager.save_state.call_args_list] == [1]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_starts_lookback_before_watermark(self, mock_session, mock_cache):
        mock_cache.get.return_value = "tok"
        mock_session.return_value.get.side_effect = [
            _response({"marketers": [{"id": "m1"}]}),
            _response({"results": []}),
        ]

        list(
            get_rows(
                "u",
                "p",
                "marketer_performance_daily",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-06-01",
            )
        )

        report_url = mock_session.return_value.get.call_args_list[1].args[0]
        # 30-day lookback before the watermark.
        assert "from=2024-05-02" in report_url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_campaign_performance_is_trailing_window_snapshot(self, mock_session, mock_cache):
        mock_cache.get.return_value = "tok"
        mock_session.return_value.get.side_effect = [
            _response({"marketers": [{"id": "m1"}]}),
            _response({"results": [{"campaignId": "c1", "metrics": {"spend": 12.5}}]}),
        ]

        batches = list(get_rows("u", "p", "campaign_performance", mock.MagicMock(), _make_manager()))

        flat = [row for batch in batches for row in batch]
        assert flat[0]["_marketer_id"] == "m1"
        assert "_date" not in flat[0]
        report_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "breakdown" not in report_url


@mock.patch(f"{_MODULE}.cache")
class TestClientErrorSkips:
    # One marketer returning a 4xx must not abort the whole fan-out sync.
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_per_marketer_400_skips_marketer_and_continues(self, mock_session, mock_cache):
        mock_cache.get.return_value = "tok"
        mock_session.return_value.get.side_effect = [
            _response({"marketers": [{"id": "m1"}, {"id": "m2"}]}),
            _response({}, status_code=400),  # budgets for m1 — inaccessible
            _response({"budgets": [{"id": "b2"}]}),  # budgets for m2
        ]

        manager = _make_manager()
        batches = list(get_rows("u", "p", "budgets", mock.MagicMock(), manager))

        flat = [row for batch in batches for row in batch]
        assert [r["_marketer_id"] for r in flat] == ["m2"]
        # State advances past both marketers so a resume does not retry the bad one.
        assert [call.args[0].next_index for call in manager.save_state.call_args_list] == [1, 2]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_per_campaign_400_on_campaign_listing_skips_marketer(self, mock_session, mock_cache):
        mock_cache.get.return_value = "tok"
        mock_session.return_value.get.side_effect = [
            _response({"marketers": [{"id": "m1"}, {"id": "m2"}]}),
            _response({}, status_code=400),  # campaigns listing for m1 — inaccessible
            _response({"campaigns": [{"id": "c1"}]}),  # campaigns for m2
            _response({"promotedLinks": [{"id": "pl1"}]}),  # links for c1
        ]

        batches = list(get_rows("u", "p", "promoted_links", mock.MagicMock(), _make_manager()))

        flat = [row for batch in batches for row in batch]
        assert [(r["id"], r["_campaign_id"]) for r in flat] == [("pl1", "c1")]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_report_stream_400_skips_marketer_and_continues(self, mock_session, mock_cache):
        mock_cache.get.return_value = "tok"
        mock_session.return_value.get.side_effect = [
            _response({"marketers": [{"id": "m1"}, {"id": "m2"}]}),
            _response({}, status_code=400),  # report for m1 — inaccessible
            _response({"results": [{"metadata": {"fromDate": "2024-01-01"}, "metrics": {"clicks": 5}}]}),
        ]

        manager = _make_manager()
        batches = list(get_rows("u", "p", "marketer_performance_daily", mock.MagicMock(), manager))

        flat = [row for batch in batches for row in batch]
        assert [r["_marketer_id"] for r in flat] == ["m2"]
        assert [call.args[0].next_index for call in manager.save_state.call_args_list] == [1, 2]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_400_on_marketer_listing_is_fatal(self, mock_session, mock_cache):
        # A client error listing the marketers themselves has nothing to skip, so
        # it must still abort rather than silently yield an empty sync.
        mock_cache.get.return_value = "tok"
        mock_session.return_value.get.return_value = _response({}, status_code=400)

        with pytest.raises(OutbrainClientError):
            list(get_rows("u", "p", "budgets", mock.MagicMock(), _make_manager()))


class TestOutbrainSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = OUTBRAIN_ENDPOINTS[endpoint]
        response = outbrain_source("u", "p", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        expected_sort = "desc" if config.incremental_fields else "asc"
        assert response.sort_mode == expected_sort
