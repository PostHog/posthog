from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs

import pytest

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.taboola._config import TaboolaSourceConfig
from products.warehouse_sources.sources.taboola.settings import ENDPOINTS, REPORT_LOOKBACK_DAYS, TABOOLA_ENDPOINTS
from products.warehouse_sources.sources.taboola.source import TaboolaSource
from products.warehouse_sources.sources.taboola.taboola import (
    TaboolaResumeConfig,
    _targeting_rows,
    _to_date,
    validate_credentials,
)

_TOKEN_PATH = "/backstage/oauth/token"


def _driver() -> SourceDriver:
    return SourceDriver(TaboolaSource(), TaboolaSourceConfig(client_id="cid", client_secret="sec", account_id="acct"))


def _token_response() -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "tok-1", "token_type": "bearer", "expires_in": 3600})


def _script(
    api: ScriptedResponse | Sequence[ScriptedResponse], tokens: Sequence[ScriptedResponse] | None = None
) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer the token endpoint from `tokens` (a fresh token every time by default) and the API from `api`."""
    api_queue = None if isinstance(api, ScriptedResponse) else list(api)
    token_queue = None if tokens is None else list(tokens)

    def respond(request: RecordedRequest) -> ScriptedResponse:
        queue, fixed = (token_queue, _token_response()) if request.path == _TOKEN_PATH else (api_queue, api)
        if queue is None:
            assert isinstance(fixed, ScriptedResponse)
            return fixed
        if not queue:
            raise UnexpectedRequest(f"no answer left for {request.url}")
        return queue.pop(0)

    return respond


def _api_requests(requests: Sequence[RecordedRequest]) -> list[RecordedRequest]:
    return [request for request in requests if request.path != _TOKEN_PATH]


def _token_requests(requests: Sequence[RecordedRequest]) -> list[RecordedRequest]:
    return [request for request in requests if request.path == _TOKEN_PATH]


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
    def test_valid_credentials_mint_a_token(self):
        with scripted_network(always(_token_response())) as network:
            assert validate_credentials("cid", "sec") is True

        assert parse_qs((network.requests_log[0].body or b"").decode()) == {
            "client_id": ["cid"],
            "client_secret": ["sec"],
            "grant_type": ["client_credentials"],
        }


class TestEntityEndpoints:
    def test_mid_sync_401_re_mints_token(self):
        result = _driver().run(
            "conversion_rules",
            _script(
                [ScriptedResponse(status=401, json={}), ScriptedResponse(json={"results": [{"id": "1"}]})],
                tokens=[_token_response(), _token_response()],
            ),
        )

        assert result.items == [[{"id": "1"}]]
        assert len(_token_requests(result.requests)) == 2

    def test_initial_token_mint_retries_on_transient_error(self):
        result = _driver().run(
            "campaigns",
            _script(
                ScriptedResponse(json={"results": [{"id": "1"}]}),
                tokens=[ScriptedResponse(status=503, json={}), _token_response()],
            ),
        )

        assert result.items == [[{"id": "1"}]]
        assert len(_token_requests(result.requests)) == 2

    @pytest.mark.parametrize(
        "endpoint, expected_path",
        [
            ("campaigns", "/backstage/api/1.0/acct/campaigns/"),
            ("allowed_accounts", "/backstage/api/1.0/users/current/allowed-accounts"),
            ("advertisers", "/backstage/api/1.0/acct/advertisers"),
            ("my_audiences", "/backstage/api/1.0/acct/my_audiences"),
            ("combined_audiences", "/backstage/api/1.0/acct/combined_audiences/"),
        ],
    )
    def test_requests_account_or_user_scoped_path(self, endpoint, expected_path):
        result = _driver().run(endpoint, _script(ScriptedResponse(json={"results": [{"id": 1}], "metadata": {}})))

        assert result.items == [[{"id": 1}]]
        assert [request.path for request in _api_requests(result.requests)] == [expected_path]

    @pytest.mark.parametrize("endpoint, expect_failure", [("advertisers", False), ("campaigns", True)])
    def test_404_is_empty_only_for_endpoints_that_allow_it(self, endpoint, expect_failure):
        result = _driver().run(
            endpoint,
            _script(ScriptedResponse(status=404, json={"http_status": 404, "message": "Not found"})),
        )

        assert result.items == []
        assert (result.raised is not None and "404" in str(result.raised)) is expect_failure


class TestCampaignItemsFanOut:
    def test_resumes_from_saved_campaign_index(self):
        result = _driver().run(
            "campaign_items",
            _script(
                [
                    ScriptedResponse(json={"results": [{"id": 11}, {"id": 22}]}),
                    ScriptedResponse(json={"results": [{"id": "i2"}]}),
                ]
            ),
            resume_state=TaboolaResumeConfig(next_campaign_index=1),
        )

        assert [row["id"] for row in result.rows] == ["i2"]
        urls = _api_requests(result.requests)
        assert len(urls) == 2
        assert urls[1].path.endswith("/acct/campaigns/22/items/")


class TestTargetingRows:
    @pytest.mark.parametrize(
        "data, expected",
        [
            (
                {
                    "collection": [
                        {"collection": [1900004, 1900024], "type": "INCLUDE"},
                        {"collection": [1905924], "type": "EXCLUDE"},
                    ]
                },
                [
                    {"collection": [1900004, 1900024], "type": "INCLUDE", "campaign_id": "7"},
                    {"collection": [1905924], "type": "EXCLUDE", "campaign_id": "7"},
                ],
            ),
            ({"collection": []}, []),
            (
                {"collection": [{"collection": [], "type": "INCLUDE"}, {"collection": [3], "type": None}]},
                [],
            ),
            (
                {"type": "INCLUDE", "collection": ["1351", "1430"]},
                [{"type": "INCLUDE", "collection": ["1351", "1430"], "campaign_id": "7"}],
            ),
            ({"type": "ALL", "collection": []}, []),
            ({"collection": None}, []),
            ({}, []),
            ([], []),
        ],
        ids=[
            "multi_targeting_include_and_exclude",
            "multi_targeting_empty",
            "drops_empty_and_untyped_restrictions",
            "postal_code_include",
            "postal_code_default_all",
            "null_collection",
            "empty_object",
            "non_object",
        ],
    )
    def test_flattens_restrictions(self, data, expected):
        assert _targeting_rows("7", data) == expected


class TestCampaignTargetingFanOut:
    @pytest.mark.parametrize(
        "endpoint, suffix",
        [
            ("campaign_audience_segment_targeting", "targeting/audience_segments"),
            ("campaign_contextual_targeting", "targeting/contextual_segments"),
            ("campaign_my_audience_targeting", "targeting/my_audiences"),
            ("campaign_postal_code_targeting", "targeting/postal_code"),
        ],
    )
    def test_fetches_targeting_per_campaign(self, endpoint, suffix):
        result = _driver().run(
            endpoint,
            _script(
                [
                    ScriptedResponse(json={"results": [{"id": "11"}, {"id": "22"}, {"id": "33"}]}),
                    ScriptedResponse(json={"collection": [{"collection": [5, 6], "type": "INCLUDE"}]}),
                    ScriptedResponse(json={"collection": []}),
                    ScriptedResponse(json={"type": "EXCLUDE", "collection": ["1351"]}),
                ]
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"collection": [5, 6], "type": "INCLUDE", "campaign_id": "11"},
            {"type": "EXCLUDE", "collection": ["1351"], "campaign_id": "33"},
        ]
        assert [request.path for request in _api_requests(result.requests)] == [
            "/backstage/api/1.0/acct/campaigns/",
            f"/backstage/api/1.0/acct/campaigns/11/{suffix}",
            f"/backstage/api/1.0/acct/campaigns/22/{suffix}",
            f"/backstage/api/1.0/acct/campaigns/33/{suffix}",
        ]
        assert [state.next_campaign_index for state in result.saved_states] == [1, 2, 3]

    def test_resumes_from_saved_campaign_index(self):
        result = _driver().run(
            "campaign_contextual_targeting",
            _script(
                [
                    ScriptedResponse(json={"results": [{"id": "11"}, {"id": "22"}]}),
                    ScriptedResponse(json={"collection": [{"collection": [9], "type": "EXCLUDE"}]}),
                ]
            ),
            resume_state=TaboolaResumeConfig(next_campaign_index=1),
        )

        assert result.rows == [{"collection": [9], "type": "EXCLUDE", "campaign_id": "22"}]
        assert _api_requests(result.requests)[-1].path.endswith("/acct/campaigns/22/targeting/contextual_segments")


class TestReportWindows:
    def test_full_refresh_walks_windows_from_default_backfill(self):
        result = _driver().run(
            "campaign_summary_by_day",
            _script(ScriptedResponse(json={"results": [{"date": "2024-01-01", "campaign": "1"}]})),
        )

        assert len(result.items) > 1
        first = _api_requests(result.requests)[0]
        assert first.param("start_date") is not None and first.param("end_date") is not None
        # Walked oldest-first: every saved window start moves forward.
        starts = [state.next_window_start for state in result.saved_states]
        assert starts == sorted(starts)

    def test_incremental_starts_lookback_before_watermark(self):
        watermark = datetime.now(tz=UTC).date()
        result = _driver().run(
            "campaign_summary_by_day",
            _script(ScriptedResponse(json={"results": []})),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark.isoformat(),
        )

        expected_start = (watermark - timedelta(days=REPORT_LOOKBACK_DAYS)).isoformat()
        assert _api_requests(result.requests)[0].param("start_date") == expected_start

    def test_resume_window_start_supersedes_older_start(self):
        resume_start = datetime.now(tz=UTC).date().isoformat()
        result = _driver().run(
            "campaign_summary_by_day",
            _script(ScriptedResponse(json={"results": []})),
            resume_state=TaboolaResumeConfig(next_window_start=resume_start),
        )

        api_requests = _api_requests(result.requests)
        assert api_requests[0].param("start_date") == resume_start
        assert len(api_requests) == 1

    @pytest.mark.parametrize(
        "endpoint, dimension, row",
        [
            ("top_campaign_content", "top-campaign-content/dimensions/item_breakdown", {"campaign": "1", "item": "9"}),
            (
                "campaign_summary_by_site",
                "campaign-summary/dimensions/site_breakdown",
                {"site": "demo-site", "site_name": "Demo Site", "blocking_level": "NONE", "spent": 1.5},
            ),
            (
                "campaign_summary_by_country",
                "campaign-summary/dimensions/country_breakdown",
                {"country": "FR", "country_name": "France", "clicks": 3},
            ),
            (
                "campaign_summary_by_region",
                "campaign-summary/dimensions/region_breakdown",
                {"region": "Bavaria", "country": "DE", "clicks": 4},
            ),
            (
                "campaign_summary_by_dma",
                "campaign-summary/dimensions/dma_breakdown",
                {"dma": "New York", "country": "US", "spent": 2.5},
            ),
        ],
    )
    def test_snapshot_report_uses_trailing_window_single_fetch(self, endpoint, dimension, row):
        result = _driver().run(endpoint, _script(ScriptedResponse(json={"results": [row]})))

        assert result.items == [[row]]
        api_requests = _api_requests(result.requests)
        assert len(api_requests) == 1
        assert api_requests[0].path == f"/backstage/api/1.0/acct/reports/{dimension}"
        start, end = api_requests[0].param("start_date"), api_requests[0].param("end_date")
        assert start is not None and end is not None
        assert date.fromisoformat(end) - date.fromisoformat(start) == timedelta(days=REPORT_LOOKBACK_DAYS)
        assert result.saved_states == []


class TestTaboolaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = TABOOLA_ENDPOINTS[endpoint]
        response = _driver().run(endpoint, _script(ScriptedResponse(json={"results": []}))).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
