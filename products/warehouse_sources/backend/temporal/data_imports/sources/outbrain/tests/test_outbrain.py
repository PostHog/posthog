import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.outbrain import (
    OutbrainSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.outbrain import (
    PAGE_SIZE,
    OutbrainResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.settings import (
    ENDPOINTS,
    OUTBRAIN_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.source import OutbrainSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.outbrain"


def _driver() -> SourceDriver:
    return SourceDriver(OutbrainSource(), OutbrainSourceConfig(username="u", password="p"))


@mock.patch(f"{_MODULE}.cache")
class TestTokenCaching:
    def test_cached_token_skips_login(self, mock_cache: mock.MagicMock) -> None:
        # /login is capped at 2 requests/hour, so the cache must short-circuit.
        mock_cache.get.return_value = "tok-cached"

        with scripted_network([]) as network:
            assert validate_credentials("u", "p") is True
        assert network.requests_log == []

    def test_login_without_token_in_response_fails(self, mock_cache: mock.MagicMock) -> None:
        mock_cache.get.return_value = None

        with scripted_network([ScriptedResponse(json={"message": "nope"})]) as network:
            assert validate_credentials("u", "p") is False
        assert [request.path for request in network.requests_log] == ["/amplify/v0.1/login"]


@mock.patch(f"{_MODULE}.cache")
class TestEntityStreams:
    def test_campaigns_fan_out_per_marketer_with_offset_pagination(self, mock_cache: mock.MagicMock) -> None:
        mock_cache.get.return_value = "tok"
        full_page = [{"id": f"c{i}"} for i in range(PAGE_SIZE)]
        result = _driver().run(
            "campaigns",
            [
                ScriptedResponse(json={"marketers": [{"id": "m1"}]}),
                ScriptedResponse(json={"campaigns": full_page}),
                ScriptedResponse(json={"campaigns": [{"id": "c-last"}]}),
            ],
        )

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [PAGE_SIZE, 1]
        assert all(row["_marketer_id"] == "m1" for row in result.rows)
        assert result.requests[2].param("offset") == str(PAGE_SIZE)
        assert result.saved_states == [OutbrainResumeConfig(next_index=1)]

    def test_promoted_links_fan_out_per_campaign(self, mock_cache: mock.MagicMock) -> None:
        mock_cache.get.return_value = "tok"
        result = _driver().run(
            "promoted_links",
            [
                ScriptedResponse(json={"marketers": [{"id": "m1"}]}),
                ScriptedResponse(json={"campaigns": [{"id": "c1"}]}),
                ScriptedResponse(json={"promotedLinks": [{"id": "pl1"}]}),
            ],
        )

        assert result.raised is None
        assert [(row["id"], row["_campaign_id"]) for row in result.rows] == [("pl1", "c1")]
        assert result.requests[2].path == "/amplify/v0.1/campaigns/c1/promotedLinks"

    def test_resumes_from_saved_parent_index(self, mock_cache: mock.MagicMock) -> None:
        mock_cache.get.return_value = "tok"
        result = _driver().run(
            "budgets",
            [
                ScriptedResponse(json={"marketers": [{"id": "m1"}, {"id": "m2"}]}),
                ScriptedResponse(json={"budgets": [{"id": "b2"}]}),
            ],
            resume_state=OutbrainResumeConfig(next_index=1),
        )

        assert result.raised is None
        assert [row["_marketer_id"] for row in result.rows] == ["m2"]
        assert result.paths == ["/amplify/v0.1/marketers", "/amplify/v0.1/marketers/m2/budgets"]

    def test_mid_sync_401_re_mints_token(self, mock_cache: mock.MagicMock) -> None:
        mock_cache.get.return_value = "tok-stale"
        # The data requests run on the tracked session; the mid-sync re-mint
        # logs in on an untracked session (requests.get).
        result = _driver().run(
            "marketers",
            [
                ScriptedResponse(status=401, json={}),
                ScriptedResponse(json={"OB-TOKEN-V1": "tok-fresh"}),
                ScriptedResponse(json={"marketers": [{"id": "m1"}]}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["m1"]
        assert result.paths == ["/amplify/v0.1/marketers", "/amplify/v0.1/login", "/amplify/v0.1/marketers"]
        assert result.requests[2].headers["ob-token-v1"] == "tok-fresh"
        assert result.session_options[0]["redact_values"] == ("p", "tok-stale")
        assert result.session_options[1]["redact_values"] == ("p", "tok-fresh")


@mock.patch(f"{_MODULE}.cache")
class TestReportStreams:
    def test_periodic_report_injects_date_and_marketer(self, mock_cache: mock.MagicMock) -> None:
        mock_cache.get.return_value = "tok"
        result = _driver().run(
            "marketer_performance_daily",
            [
                ScriptedResponse(json={"marketers": [{"id": "m1"}]}),
                ScriptedResponse(
                    json={
                        "results": [
                            {"metadata": {"fromDate": "2024-01-01"}, "metrics": {"clicks": 5}},
                            {"metadata": {"fromDate": "2024-01-02"}, "metrics": {"clicks": 7}},
                            {"metrics": {"clicks": 0}},  # no date — dropped
                        ]
                    }
                ),
            ],
        )

        assert result.raised is None
        assert [(row["_date"], row["_marketer_id"]) for row in result.rows] == [
            ("2024-01-01", "m1"),
            ("2024-01-02", "m1"),
        ]
        assert result.requests[1].param("breakdown") == "daily"
        assert result.requests[1].param("from") is not None
        assert result.requests[1].param("to") is not None
        assert result.saved_states == [OutbrainResumeConfig(next_index=1)]

    def test_incremental_starts_lookback_before_watermark(self, mock_cache: mock.MagicMock) -> None:
        mock_cache.get.return_value = "tok"
        result = _driver().run(
            "marketer_performance_daily",
            [
                ScriptedResponse(json={"marketers": [{"id": "m1"}]}),
                ScriptedResponse(json={"results": []}),
            ],
            incremental_field="_date",
            db_incremental_field_last_value="2024-06-01",
        )

        assert result.raised is None
        # 30-day lookback before the watermark.
        assert result.requests[1].param("from") == "2024-05-02"

    def test_campaign_performance_is_trailing_window_snapshot(self, mock_cache: mock.MagicMock) -> None:
        mock_cache.get.return_value = "tok"
        result = _driver().run(
            "campaign_performance",
            [
                ScriptedResponse(json={"marketers": [{"id": "m1"}]}),
                ScriptedResponse(json={"results": [{"campaignId": "c1", "metrics": {"spend": 12.5}}]}),
            ],
        )

        assert result.raised is None
        assert result.rows[0]["_marketer_id"] == "m1"
        assert "_date" not in result.rows[0]
        assert result.requests[1].param("breakdown") is None


class TestOutbrainSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = OUTBRAIN_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, always(ScriptedResponse(json={"OB-TOKEN-V1": "tok", "marketers": []})))

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        expected_sort = "desc" if config.incremental_fields else "asc"
        assert result.response.sort_mode == expected_sort
