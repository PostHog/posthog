from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.heyreach import (
    HeyReachSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heyreach.heyreach import (
    STATS_START_DATE,
    HeyReachResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heyreach.source import HeyReachSource


def _driver() -> SourceDriver:
    return SourceDriver(HeyReachSource(), HeyReachSourceConfig(api_key="test-key"))


def _page(items: list[dict[str, Any]], total_count: int) -> ScriptedResponse:
    return ScriptedResponse(json={"totalCount": total_count, "items": items})


class TestTopLevelEndpoints:
    def test_fresh_run_pages_by_total_count_and_saves_offsets(self) -> None:
        result = _driver().run(
            "campaigns",
            [
                _page([{"id": i} for i in range(100)], 150),
                _page([{"id": i} for i in range(100, 150)], 150),
            ],
        )

        assert result.raised is None
        assert [request.json().get("offset") for request in result.requests] == [0, 100]
        assert all(request.json().get("limit") == 100 for request in result.requests)
        assert result.saved_states == [HeyReachResumeConfig(offset=100)]
        assert len(result.rows) == 150

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        result = _driver().run(
            "campaigns",
            [_page([{"id": 100}], 101)],
            resume_state=HeyReachResumeConfig(offset=100),
        )

        assert result.raised is None
        assert [request.json().get("offset") for request in result.requests] == [100]


class TestFanoutEndpoints:
    def test_campaign_leads_fans_out_per_campaign_and_injects_campaign_id(self) -> None:
        result = _driver().run(
            "campaign_leads",
            [
                _page([{"id": 1}, {"id": 2}], 2),
                _page([{"id": 11, "leadCampaignStatus": "Finished"}], 1),
                _page([{"id": 21, "leadCampaignStatus": "Pending"}], 1),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/api/public/campaign/GetAll",
            "/api/public/campaign/GetLeadsFromCampaign",
            "/api/public/campaign/GetLeadsFromCampaign",
        ]
        assert [request.json().get("campaignId") for request in result.requests[1:]] == [1, 2]
        assert all(
            request.json().get("offset") == 0 and request.json().get("limit") == 100 for request in result.requests
        )
        assert result.rows == [
            {"campaignId": 1, "id": 11, "leadCampaignStatus": "Finished"},
            {"campaignId": 2, "id": 21, "leadCampaignStatus": "Pending"},
        ]

    def test_list_leads_only_fans_out_lead_lists_and_skips_parents_without_id(self) -> None:
        result = _driver().run(
            "list_leads",
            [
                _page([{"id": 5}, {"name": "row without id"}], 2),
                _page([], 0),
            ],
        )

        assert result.raised is None
        assert result.paths[0] == "/api/public/list/GetAll"
        # Company lists serve companies via a different endpoint, so the parent listing is
        # restricted to lead lists.
        assert result.requests[0].json()["listType"] == "USER_LIST"
        # Only the parent with an id produces a child request, and an empty child page yields no batch.
        assert len(result.requests) == 2
        assert result.requests[1].json()["listId"] == 5
        assert result.items == []


class TestOverallStats:
    @pytest.mark.parametrize(
        ("payload", "expected_days"),
        [
            (
                {
                    "byDayStats": {
                        "2024-12-17T00:00:00Z": {"messagesSent": 5, "connectionsSent": 10},
                        "2024-12-18T00:00:00Z": {"messagesSent": 2, "connectionsSent": 0},
                    },
                    "overallStats": {"messagesSent": 7},
                },
                2,
            ),
            ({"overallStats": {"messagesSent": 7}}, 0),
            ({"byDayStats": None}, 0),
        ],
    )
    def test_yields_one_row_per_day(self, payload: dict[str, Any], expected_days: int) -> None:
        result = _driver().run("overall_stats", [ScriptedResponse(json=payload)])

        assert result.raised is None
        assert len(result.rows) == expected_days
        if result.rows:
            assert result.rows[0]["messagesSent"] == 5
            assert result.rows[0]["date"].isoformat() == "2024-12-17T00:00:00+00:00"

        assert result.paths == ["/api/public/stats/GetOverallStats"]
        body = result.requests[0].json()
        assert body["startDate"] == STATS_START_DATE
        assert body["accountIds"] == []
        assert body["campaignIds"] == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_fragment"),
        [
            (200, True, None),
        ],
    )
    def test_maps_status_to_user_message(
        self, status_code: int, expected_valid: bool, expected_fragment: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            valid, message = validate_credentials("test-key")

        assert valid is expected_valid
        if expected_fragment is None:
            assert message is None
        else:
            assert expected_fragment in (message or "")
        assert network.requests_log[0].path == "/api/public/auth/CheckApiKey"
        assert network.requests_log[0].headers["x-api-key"] == "test-key"

    def test_transport_error_reports_unreachable_instead_of_raising(self) -> None:
        # A DNS failure or timeout during the probe must not raise out of validate_credentials
        # and fail source creation with a stack trace.
        with scripted_network(always(requests.ConnectionError("dns failure"))) as network:
            valid, message = validate_credentials("test-key")

        assert valid is False
        assert "Couldn't reach HeyReach" in (message or "")
        assert {request.path for request in network.requests_log} == {"/api/public/auth/CheckApiKey"}

    def test_non_ascii_key_fails_without_a_request(self) -> None:
        # A non-latin-1 key can't be encoded into the X-API-KEY header; the raw
        # UnicodeEncodeError must never surface to the user.
        with scripted_network([]) as network:
            valid, message = validate_credentials("bad中key")

        assert valid is False
        assert "Retype it by hand" in (message or "")
        assert network.requests_log == []
        assert network.session_options == []
