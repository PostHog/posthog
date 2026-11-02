from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.genesyscloud import (
    GenesysCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud import genesys_cloud
from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.genesys_cloud import (
    GenesysCloudResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.source import GenesysCloudSource

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
TOKEN = ScriptedResponse(json={"access_token": "test-token", "expires_in": 3600})


def _driver() -> SourceDriver:
    return SourceDriver(
        GenesysCloudSource(),
        GenesysCloudSourceConfig(region="mypurecloud.com", client_id="cid", client_secret="secret"),
    )


def _conversation(conversation_id: str, start: datetime, participants: list[dict[str, Any]] | None = None) -> dict:
    return {
        "conversationId": conversation_id,
        "conversationStart": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "participants": participants or [],
    }


def _request_interval(request: RecordedRequest) -> tuple[datetime, datetime]:
    start, end = request.json()["interval"].split("/")
    return datetime.fromisoformat(start), datetime.fromisoformat(end)


class TestAnalyticsEndpoints:
    @pytest.fixture(autouse=True)
    def frozen_clock(self):
        with time_machine.travel(NOW, tick=False):
            yield

    def test_pages_within_window_and_drops_conversations_outside_it(self):
        start = NOW - timedelta(hours=6)
        full_page = [_conversation(f"c{i}", start + timedelta(seconds=i)) for i in range(100)]
        last_page = [
            _conversation("c100", start + timedelta(minutes=5)),
            _conversation("from-previous-window", start - timedelta(hours=1)),
        ]

        result = _driver().run(
            "conversations",
            [
                TOKEN,
                ScriptedResponse(json={"totalHits": 102, "conversations": full_page}),
                ScriptedResponse(json={"totalHits": 102, "conversations": last_page}),
            ],
            resume_state=GenesysCloudResumeConfig(window_start=start.isoformat()),
        )

        assert result.raised is None
        assert [row["conversationId"] for row in result.rows] == [f"c{i}" for i in range(101)]
        assert [request.json()["paging"]["pageNumber"] for request in result.requests[1:]] == [1, 2]
        assert _request_interval(result.requests[1]) == (start, NOW)
        assert result.saved_states == [GenesysCloudResumeConfig(window_start="2026-03-10T12:00:00.000Z")]

    def test_splits_a_dense_ten_minute_window(self):
        start = NOW - timedelta(minutes=10)
        middle = NOW - timedelta(minutes=5)

        result = _driver().run(
            "conversations",
            [
                TOKEN,
                ScriptedResponse(json={"totalHits": genesys_cloud.MAX_RESULTS_PER_WINDOW + 1, "conversations": []}),
                ScriptedResponse(json={"totalHits": 1, "conversations": [_conversation("early", start)]}),
                ScriptedResponse(json={"totalHits": 1, "conversations": [_conversation("late", middle)]}),
            ],
            resume_state=GenesysCloudResumeConfig(window_start=start.isoformat()),
        )

        assert result.raised is None
        assert [row["conversationId"] for row in result.rows] == ["early", "late"]
        assert [_request_interval(request) for request in result.requests[2:]] == [(start, middle), (middle, NOW)]

    @pytest.mark.parametrize(
        "resume,watermark,expected_start",
        [
            (None, None, NOW - genesys_cloud.INITIAL_HISTORY),
            (None, datetime(2026, 3, 9, 6, 0), datetime(2026, 3, 7, 6, 0, tzinfo=UTC)),
            (
                GenesysCloudResumeConfig(window_start="2026-03-10T08:00:00.000Z"),
                datetime(2026, 3, 9, 6, 0),
                datetime(2026, 3, 10, 8, 0, tzinfo=UTC),
            ),
        ],
    )
    def test_first_window_start(self, resume, watermark, expected_start):
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return TOKEN
            return ScriptedResponse(json={"totalHits": 0})

        result = _driver().run(
            "calls",
            respond,
            resume_state=resume,
            incremental_field="conversationStart" if watermark is not None else None,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert _request_interval(result.requests[1])[0] == expected_start
        assert _request_interval(result.requests[-1])[1] == NOW
        assert result.committed_states
        assert result.final_state is None

    def test_participants_are_flattened_with_conversation_keys(self):
        start = NOW - timedelta(hours=1)

        result = _driver().run(
            "participants",
            [
                TOKEN,
                ScriptedResponse(
                    json={
                        "totalHits": 1,
                        "conversations": [
                            _conversation(
                                "conv-1",
                                start,
                                participants=[
                                    {"participantId": "p1", "purpose": "customer"},
                                    {"participantId": "p2", "purpose": "agent"},
                                ],
                            )
                        ],
                    }
                ),
            ],
            resume_state=GenesysCloudResumeConfig(window_start=start.isoformat()),
        )

        assert result.raised is None
        assert [(row["conversationId"], row["participantId"], row["purpose"]) for row in result.rows] == [
            ("conv-1", "p1", "customer"),
            ("conv-1", "p2", "agent"),
        ]
        assert all(row["conversationStart"] == "2026-03-10T11:00:00.000Z" for row in result.rows)

    @pytest.mark.parametrize("resumed", [False, True])
    def test_user_status_records_are_emitted_once_per_run(self, resumed):
        watermark = NOW - timedelta(hours=1)
        start = watermark - genesys_cloud.INCREMENTAL_LOOKBACK
        second_window = start + genesys_cloud.ANALYTICS_WINDOW

        def record(at: datetime, **fields: Any) -> dict[str, Any]:
            return {"startTime": at.strftime("%Y-%m-%dT%H:%M:%S.000Z"), **fields}

        def page(total_hits: int, *details: dict[str, Any]) -> ScriptedResponse:
            return ScriptedResponse(json={"totalHits": total_hits, "userDetails": list(details)})

        spans_windows = record(second_window - timedelta(hours=1), routingStatus="IDLE")
        first_window_users = {
            "userId": "u1",
            "primaryPresence": [
                record(start - timedelta(days=3), systemPresence="OFFLINE"),
                record(start + timedelta(hours=1), systemPresence="AVAILABLE"),
            ],
            "routingStatus": [spans_windows, record(second_window + timedelta(hours=1), routingStatus="IDLE")],
        }
        second_window_users = {
            "userId": "u1",
            "primaryPresence": [record(second_window + timedelta(hours=2), systemPresence="BUSY")],
            "routingStatus": [spans_windows, {"routingStatus": "OFF_QUEUE"}],
        }

        result = _driver().run(
            "user_status_history",
            [
                TOKEN,
                page(101, first_window_users),
                page(
                    101, {"userId": "u2", "routingStatus": [record(start + timedelta(hours=2), routingStatus="IDLE")]}
                ),
                page(1, second_window_users),
                page(0),
            ],
            resume_state=GenesysCloudResumeConfig(window_start=start.isoformat()) if resumed else None,
            incremental_field="startTime",
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert result.response is not None and result.response.sort_mode is None
        assert [request.path for request in result.requests[1:]] == ["/api/v2/analytics/users/details/query"] * 4
        assert [request.json()["paging"]["pageNumber"] for request in result.requests[1:]] == [1, 2, 1, 1]
        carried_over = [] if resumed else [("u1", "presence", "2026-03-05T11:00:00.000Z")]
        assert [(row["userId"], row["recordType"], row["startTime"]) for row in result.rows] == [
            *carried_over,
            ("u1", "presence", "2026-03-08T12:00:00.000Z"),
            ("u1", "routing_status", "2026-03-09T10:00:00.000Z"),
            ("u2", "routing_status", "2026-03-08T13:00:00.000Z"),
            ("u1", "presence", "2026-03-09T13:00:00.000Z"),
        ]


class TestListingEndpoints:
    @pytest.mark.parametrize(
        "resume,expected_pages",
        [
            (None, [1, 2]),
            (GenesysCloudResumeConfig(page_number=2), [2]),
        ],
    )
    def test_pages_until_page_count(self, resume, expected_pages):
        pages = {
            1: ScriptedResponse(json={"entities": [{"id": "q1"}], "pageNumber": 1, "pageCount": 2}),
            2: ScriptedResponse(json={"entities": [{"id": "q2"}], "pageNumber": 2, "pageCount": 2}),
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return TOKEN
            return pages[int(request.param("pageNumber") or 0)]

        result = _driver().run("queues", respond, resume_state=resume)

        assert result.raised is None
        assert result.params("pageNumber")[1:] == [str(page) for page in expected_pages]
        assert [row["id"] for row in result.rows] == [f"q{page}" for page in expected_pages]
        assert result.saved_states == ([GenesysCloudResumeConfig(page_number=2)] if resume is None else [])
        assert result.final_state is None

    @pytest.mark.parametrize(
        "endpoint,cursor_param,first_page,resume,expected_cursors",
        [
            ("external_organizations", "cursor", {"cursors": {"after": "after-1"}}, None, [None, "after-1"]),
            (
                "external_organizations",
                "cursor",
                {"cursors": {"after": "after-1"}},
                GenesysCloudResumeConfig(cursor="after-1"),
                ["after-1"],
            ),
            ("teams", "after", {"nextUri": "/api/v2/teams?pageSize=100&after=after-1"}, None, [None, "after-1"]),
        ],
    )
    def test_scan_pages_until_cursor_runs_out(self, endpoint, cursor_param, first_page, resume, expected_cursors):
        pages = {
            None: ScriptedResponse(json={"entities": [{"id": "o1"}], **first_page}),
            "after-1": ScriptedResponse(json={"entities": [{"id": "o2"}], "cursors": {}}),
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return TOKEN
            return pages[request.param(cursor_param)]

        result = _driver().run(endpoint, respond, resume_state=resume)

        assert result.raised is None
        assert result.params(cursor_param)[1:] == expected_cursors
        assert [row["id"] for row in result.rows] == ["o1", "o2"][-len(expected_cursors) :]
        assert result.saved_states == ([GenesysCloudResumeConfig(cursor="after-1")] if resume is None else [])
        assert result.final_state is None

    def test_scan_drops_an_expired_resumed_cursor(self):
        result = _driver().run(
            "external_organizations",
            [TOKEN, ScriptedResponse(status=422, json={"code": "bad.request"})],
            resume_state=GenesysCloudResumeConfig(cursor="expired"),
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert result.rows == []
        assert result.final_state is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "endpoint,status_code,expected_valid,expected_message",
        [
            (None, 200, True, None),
            ("external_organizations", 200, True, None),
            (
                "user_status_history",
                403,
                False,
                "The OAuth client's role is missing the `analytics:userDetail:view` permission, which the user_status_history table needs.",
            ),
        ],
    )
    def test_maps_probe_status(self, endpoint, status_code, expected_valid, expected_message):
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return TOKEN
            return ScriptedResponse(status=status_code, json={})

        with scripted_network(respond) as network:
            result = validate_credentials("mypurecloud.com", "cid", "secret", endpoint)

        assert result == (expected_valid, expected_message)
        assert network.requests_log[0].path == "/oauth/token"
        assert (
            network.requests_log[1].path
            == {
                None: "/api/v2/organizations/me",
                "conversations": "/api/v2/analytics/conversations/details/query",
                "users": "/api/v2/users",
                "queues": "/api/v2/routing/queues",
                "external_organizations": "/api/v2/externalcontacts/scan/organizations",
                "user_status_history": "/api/v2/analytics/users/details/query",
            }[endpoint]
        )

    @pytest.mark.parametrize(
        "error,expected_message",
        [
            (
                OAuth2AuthRequestError("HTTP 400 from the OAuth2 token endpoint: invalid_client", is_permanent=True),
                "Genesys Cloud rejected the client ID and secret. Check that the OAuth client uses the client credentials grant and belongs to the selected region.",
            ),
            (
                OAuth2AuthRequestError("HTTP 503 from the OAuth2 token endpoint", is_permanent=False),
                "Could not get an access token from Genesys Cloud. Try again in a few minutes.",
            ),
        ],
    )
    def test_maps_request_errors(self, error, expected_message):
        script: Script
        if isinstance(error, OAuth2AuthRequestError):
            response = ScriptedResponse(
                status=400 if error.is_permanent else 503,
                json={"error": "invalid_client"} if error.is_permanent else {},
            )
            script = [response]
        else:
            script = always(error)

        with scripted_network(script) as network:
            result = validate_credentials("mypurecloud.com", "cid", "secret")

        assert result == (False, expected_message)
        assert network.requests_log[0].path == "/oauth/token"

    def test_rejects_unknown_region_without_a_request(self):
        with scripted_network([]) as network:
            result = validate_credentials("evil.example.com", "cid", "secret")

        assert result == (False, "Select the Genesys Cloud region your organization is hosted in.")
        assert network.requests_log == []
        assert network.session_options == []
