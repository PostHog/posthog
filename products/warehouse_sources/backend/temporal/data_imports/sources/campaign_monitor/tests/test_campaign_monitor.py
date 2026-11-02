from typing import Any, cast

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.campaign_monitor import (
    CampaignMonitorResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.settings import (
    CAMPAIGN_MONITOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.source import (
    CampaignMonitorSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.campaignmonitor import (
    CampaignMonitorSourceConfig,
)


def _driver() -> SourceDriver:
    config = CampaignMonitorSourceConfig(api_key="test-key", client_id="client-abc")
    return SourceDriver(CampaignMonitorSource(), config)


def _response(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


def _envelope(items: list[dict[str, Any]], number_of_pages: int = 1, page_number: int = 1) -> ScriptedResponse:
    return _response({"Results": items, "NumberOfPages": number_of_pages, "PageNumber": page_number})


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("test-key") is expected

        assert {request.path for request in network.requests_log} == {"/api/v3.3/clients.json"}


class TestNonPaginatedEndpoints:
    def test_non_list_body_raises_loudly(self) -> None:
        # A 200 body that isn't a JSON array means the response shape changed — fail loud rather
        # than syncing a stray object as a row.
        result = _driver().run("clients", [_response({"error": "unexpected"})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestPaginatedEndpoints:
    def test_multi_page_saves_state_between_pages_only(self) -> None:
        result = _driver().run(
            "suppression_list",
            [
                _envelope([{"EmailAddress": "a@x.com"}], number_of_pages=2, page_number=1),
                _envelope([{"EmailAddress": "b@x.com"}], number_of_pages=2, page_number=2),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"EmailAddress": "a@x.com"}, {"EmailAddress": "b@x.com"}]
        assert result.params("page") == ["1", "2"]
        # First page is not terminal -> save next page; second page is terminal -> no save.
        assert result.saved_states == [CampaignMonitorResumeConfig(page=2)]
        assert result.committed_states == [CampaignMonitorResumeConfig(page=2)]

    def test_resume_starts_from_saved_page(self) -> None:
        result = _driver().run(
            "suppression_list",
            [_envelope([{"EmailAddress": "b@x.com"}], number_of_pages=2, page_number=2)],
            resume_state=CampaignMonitorResumeConfig(page=2),
        )

        assert result.raised is None
        assert result.rows == [{"EmailAddress": "b@x.com"}]
        assert result.params("page") == ["2"]


class TestListFanOut:
    def test_iterates_every_list_and_injects_list_id(self) -> None:
        result = _driver().run(
            "active_subscribers",
            [
                _response([{"ListID": "l1"}, {"ListID": "l2"}]),  # lists.json
                _envelope([{"EmailAddress": "a@x.com"}]),  # l1
                _envelope([{"EmailAddress": "b@x.com"}]),  # l2
            ],
        )

        assert result.raised is None
        # the injected id must be the plain `ListID` column, not the prefixed parent key
        assert result.rows == [
            {"EmailAddress": "a@x.com", "ListID": "l1"},
            {"EmailAddress": "b@x.com", "ListID": "l2"},
        ]
        assert result.paths == [
            "/api/v3.3/clients/client-abc/lists.json",
            "/api/v3.3/lists/l1/active.json",
            "/api/v3.3/lists/l2/active.json",
        ]

    def test_custom_fields_non_list_body_raises_loudly(self) -> None:
        # The endpoint returns a bare array; a 200 object means the response shape changed.
        result = _driver().run(
            "list_custom_fields",
            [_response([{"ListID": "l1"}]), _response({"Code": 250, "Message": "Fail"})],
        )

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestCampaignFanOut:
    def test_iterates_every_campaign_and_injects_campaign_id(self) -> None:
        result = _driver().run(
            "campaign_opens",
            [
                _envelope([{"CampaignID": "c1"}, {"CampaignID": "c2"}]),  # campaigns.json (paged envelope)
                _envelope([{"EmailAddress": "a@x.com"}]),  # c1
                _envelope([{"EmailAddress": "b@x.com"}]),  # c2
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"EmailAddress": "a@x.com", "CampaignID": "c1"},
            {"EmailAddress": "b@x.com", "CampaignID": "c2"},
        ]
        assert result.paths == [
            "/api/v3.3/clients/client-abc/campaigns.json",
            "/api/v3.3/campaigns/c1/opens.json",
            "/api/v3.3/campaigns/c2/opens.json",
        ]

    def test_empty_summary_object_yields_no_row(self) -> None:
        # An empty summary body is not a row — no record carrying only the injected CampaignID.
        result = _driver().run(
            "campaign_summary",
            [_envelope([{"CampaignID": "c1"}]), _response({})],
        )

        assert result.raised is None
        assert result.rows == []

    def test_resume_skips_completed_campaigns(self) -> None:
        result = _driver().run(
            "campaign_opens",
            [
                _envelope([{"CampaignID": "c1"}, {"CampaignID": "c2"}]),  # campaigns.json re-fetched
                _envelope([{"EmailAddress": "b@x.com"}]),  # c2 only
            ],
            resume_state=CampaignMonitorResumeConfig(
                fanout_state={"completed": ["campaigns/c1/opens.json"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.rows == [{"EmailAddress": "b@x.com", "CampaignID": "c2"}]
        assert result.paths == [
            "/api/v3.3/clients/client-abc/campaigns.json",
            "/api/v3.3/campaigns/c2/opens.json",
        ]


class TestResumeConfigCompatibility:
    def test_old_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — state saved by the
        # pre-framework implementation must keep loading after the migration.
        state = CampaignMonitorResumeConfig(**cast("dict[str, Any]", {"list_id": "l1", "campaign_id": None, "page": 3}))
        assert state.list_id == "l1"
        assert state.campaign_id is None
        assert state.page == 3
        assert state.fanout_state is None


class TestCampaignMonitorSourceResponse:
    @pytest.mark.parametrize("endpoint", list(CAMPAIGN_MONITOR_ENDPOINTS.keys()))
    def test_source_response_primary_keys_match_settings(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [])

        assert result.response is not None
        config = CAMPAIGN_MONITOR_ENDPOINTS[endpoint]
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        assert result.response.sort_mode == "asc"
