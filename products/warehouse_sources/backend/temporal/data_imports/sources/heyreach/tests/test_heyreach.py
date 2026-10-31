import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import requests
from dateutil import parser

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
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

    @pytest.mark.parametrize(
        ("endpoint", "list_type", "child_path"),
        [
            ("list_leads", "USER_LIST", "/api/public/list/GetLeadsFromList"),
            ("list_companies", "COMPANY_LIST", "/api/public/list/GetCompaniesFromList"),
        ],
    )
    def test_list_children_fan_out_matching_list_type_and_skip_parents_without_id(
        self, endpoint: str, list_type: str, child_path: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _page([{"id": 5}, {"name": "row without id"}], 2),
                _page([], 0),
            ],
        )

        assert result.raised is None
        # Lead lists and company lists serve their rows through different endpoints, so the
        # parent listing is restricted to the matching list type.
        assert result.paths == ["/api/public/list/GetAll", child_path]
        assert result.requests[0].json()["listType"] == list_type
        # Only the parent with an id produces a child request, and an empty child page yields no batch.
        assert result.requests[1].json()["listId"] == 5
        assert result.items == []

    def test_sender_network_pages_by_page_number_until_empty_page(self) -> None:
        result = _driver().run(
            "sender_network",
            [
                _page([{"id": 7}], 1),
                _page([{"profileUrl": "https://www.linkedin.com/in/a"}], 2),
                _page([{"profileUrl": "https://www.linkedin.com/in/b"}], 2),
                _page([], 2),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/api/public/li_account/GetAll"] + ["/api/public/MyNetwork/GetMyNetworkForSender"] * 3
        child_bodies = [request.json() for request in result.requests[1:]]
        assert [body["pageNumber"] for body in child_bodies] == [0, 1, 2]
        assert all(body["senderId"] == 7 and body["pageSize"] == 100 for body in child_bodies)
        assert all("offset" not in body for body in child_bodies)
        assert result.rows == [
            {"senderId": 7, "profileUrl": "https://www.linkedin.com/in/a"},
            {"senderId": 7, "profileUrl": "https://www.linkedin.com/in/b"},
        ]


class TestDailyStats:
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

    @pytest.mark.parametrize(
        ("endpoint", "sender_ids", "expected_account_filters", "expected_sender_id"),
        [
            ("campaign_stats", None, [[]], None),
            # Sender 8 has no stats in any window, so it yields no rows but still walks every window.
            ("campaign_stats_by_sender", [7, 8], [[7], [8]], 7),
        ],
    )
    def test_campaign_stats_walk_contiguous_windows_per_sender_filter(
        self,
        endpoint: str,
        sender_ids: list[int] | None,
        expected_account_filters: list[list[int]],
        expected_sender_id: int | None,
    ) -> None:
        payload = {
            "byDayStats": {
                "2024-12-17T00:00:00Z": [
                    {"campaignId": 1, "campaignName": "A", "messagesSent": 3},
                    {"campaignId": 2, "campaignName": "B", "messagesSent": 4},
                ],
                "2024-12-18T00:00:00Z": [],
            },
            "overallStats": [{"campaignId": 1, "messagesSent": 3}],
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/api/public/li_account/GetAll":
                assert sender_ids is not None
                return _page([{"id": sender_id} for sender_id in sender_ids], len(sender_ids))
            body = request.json()
            if body["accountIds"] in ([], [7]) and body["startDate"] <= "2024-12-17" <= body["endDate"]:
                return ScriptedResponse(json=payload)
            return ScriptedResponse(json={"byDayStats": {}, "overallStats": []})

        result = _driver().run(endpoint, respond)

        assert result.raised is None
        stats_requests = [r for r in result.requests if r.path == "/api/public/stats/GetOverallStatsByCampaign"]
        assert len(result.requests) - len(stats_requests) == (0 if sender_ids is None else 1)
        assert all(r.json()["campaignIds"] == [] for r in stats_requests)

        # Each sender filter walks its own full window series, one filter after the other.
        account_filters = [r.json()["accountIds"] for r in stats_requests]
        assert [key for key, _ in itertools.groupby(account_filters)] == expected_account_filters
        for account_filter in expected_account_filters:
            windows = [
                (parser.parse(r.json()["startDate"]), parser.parse(r.json()["endDate"]))
                for r in stats_requests
                if r.json()["accountIds"] == account_filter
            ]
            assert windows[0][0] == parser.parse(STATS_START_DATE)
            assert windows[-1][1] > datetime.now(tz=UTC) - timedelta(minutes=5)
            for (start, end), (next_start, _) in itertools.pairwise(windows):
                assert end - start < timedelta(days=30)
                assert next_start - end == timedelta(milliseconds=1)

        assert [
            (row["date"].isoformat(), row["campaignId"], row["messagesSent"], row.get("linkedInAccountId"))
            for row in result.rows
        ] == [
            ("2024-12-17T00:00:00+00:00", 1, 3, expected_sender_id),
            ("2024-12-17T00:00:00+00:00", 2, 4, expected_sender_id),
        ]


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
