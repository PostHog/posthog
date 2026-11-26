from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine

import requests

from products.warehouse_sources.sources.genesys_cloud import genesys_cloud
from products.warehouse_sources.sources.genesys_cloud._config import GenesysCloudSourceConfig
from products.warehouse_sources.sources.genesys_cloud.genesys_cloud import (
    _GENESYS_CLOUD_RETRY,
    GenesysCloudResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.sources.genesys_cloud.source import GenesysCloudSource
from products.warehouse_sources.sources.sdk import OAuth2AuthRequestError
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)

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

    @pytest.mark.parametrize(
        "resume,expected_deactivated",
        [
            (None, ["false", "true"]),
            (GenesysCloudResumeConfig(page_number=2), ["true"]),
        ],
    )
    def test_unpaged_reads_each_param_set(self, resume, expected_deactivated):
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return TOKEN
            deactivated = request.param("deactivated")
            return ScriptedResponse(json={"entities": [{"id": f"presence-{deactivated}"}], "total": 1})

        result = _driver().run("presence_definitions", respond, resume_state=resume)

        assert result.raised is None
        assert result.params("deactivated")[1:] == expected_deactivated
        assert result.params("localeCode")[1:] == ["ALL"] * len(expected_deactivated)
        assert result.params("pageNumber")[1:] == [None] * len(expected_deactivated)
        assert [row["id"] for row in result.rows] == [f"presence-{value}" for value in expected_deactivated]
        assert result.saved_states == ([GenesysCloudResumeConfig(page_number=2)] if resume is None else [])
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


def _queue_members_respond(request: RecordedRequest) -> ScriptedResponse:
    if request.path == "/oauth/token":
        return TOKEN
    if request.path == "/api/v2/routing/queues":
        page = int(request.param("pageNumber") or 0)
        queues = {1: [{"id": "q1"}, {"id": "q2"}], 2: [{"id": "q3"}]}.get(page, [])
        return ScriptedResponse(json={"entities": queues, "pageNumber": page, "pageCount": 2})
    queue_id = request.path.split("/")[5]
    member_page = request.param("pageNumber")
    if queue_id == "q1" and member_page == "1":
        return ScriptedResponse(
            json={"entities": [{"id": "u1"}], "nextUri": "/api/v2/routing/queues/q1/members?pageSize=100&pageNumber=2"}
        )
    if queue_id == "q1" and member_page == "2":
        return ScriptedResponse(json={"entities": [{"id": "u2"}]})
    if queue_id == "q2":
        return ScriptedResponse(status=404, json={"code": "not.found"})
    return ScriptedResponse(json={"entities": [{"id": "u3"}]})


class TestFanOutEndpoints:
    @pytest.mark.parametrize(
        "resume,expected_rows,expected_requests",
        [
            (
                None,
                [("q1", "u1"), ("q1", "u2"), ("q3", "u3")],
                [("queues", "1"), ("q1", "1"), ("q1", "2"), ("q2", "1"), ("queues", "2"), ("q3", "1")],
            ),
            (
                GenesysCloudResumeConfig(
                    page_number=1,
                    parent_id="q1",
                    next_uri="/api/v2/routing/queues/q1/members?pageSize=100&pageNumber=2",
                ),
                [("q1", "u2"), ("q3", "u3")],
                [("queues", "1"), ("q1", "2"), ("q2", "1"), ("queues", "2"), ("q3", "1")],
            ),
            (
                GenesysCloudResumeConfig(page_number=1, parent_id="q2"),
                [("q3", "u3")],
                [("queues", "1"), ("q2", "1"), ("queues", "2"), ("q3", "1")],
            ),
            (
                GenesysCloudResumeConfig(page_number=1, parent_id="removed-queue", next_uri="/stale?pageNumber=9"),
                [("q1", "u1"), ("q1", "u2"), ("q3", "u3")],
                [("queues", "1"), ("q1", "1"), ("q1", "2"), ("q2", "1"), ("queues", "2"), ("q3", "1")],
            ),
            (GenesysCloudResumeConfig(page_number=2), [("q3", "u3")], [("queues", "2"), ("q3", "1")]),
            (GenesysCloudResumeConfig(page_number=3), [], [("queues", "3")]),
        ],
    )
    def test_queue_members_walk_parents_and_child_pages(self, resume, expected_rows, expected_requests):
        result = _driver().run("queue_members", _queue_members_respond, resume_state=resume)

        assert result.raised is None
        assert [(row["queueId"], row["id"]) for row in result.rows] == expected_rows
        assert [
            ("queues" if request.path.endswith("/queues") else request.path.split("/")[5], request.param("pageNumber"))
            for request in result.requests[1:]
        ] == expected_requests
        assert result.final_state is None

    def test_queue_members_stage_the_position_after_each_child_page(self):
        result = _driver().run("queue_members", _queue_members_respond)

        assert result.saved_states == [
            GenesysCloudResumeConfig(
                page_number=1, parent_id="q1", next_uri="/api/v2/routing/queues/q1/members?pageSize=100&pageNumber=2"
            ),
            GenesysCloudResumeConfig(page_number=1, parent_id="q2"),
            GenesysCloudResumeConfig(page_number=2),
            GenesysCloudResumeConfig(page_number=3),
        ]

    @pytest.mark.parametrize(
        "status,body,expected_error",
        [
            (400, {"code": "quality.query.invalid.user"}, None),
            (400, {"code": "bad.request"}, requests.HTTPError),
            (403, {"code": "missing.permissions"}, requests.HTTPError),
        ],
    )
    def test_evaluations_are_read_per_evaluator(self, status, body, expected_error):
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return TOKEN
            if request.path == "/api/v2/users":
                return ScriptedResponse(json={"entities": [{"id": "removed"}, {"id": "e1"}], "pageCount": 1})
            if request.param("evaluatorUserId") == "removed":
                return ScriptedResponse(status=status, json=body)
            return ScriptedResponse(json={"entities": [{"id": "ev1", "evaluator": {"id": "e1"}}]})

        result = _driver().run("evaluations", respond)

        if expected_error is not None:
            assert isinstance(result.raised, expected_error)
            assert result.rows == []
            return
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["ev1"]
        evaluation_requests = result.requests[2:]
        assert [request.param("evaluatorUserId") for request in evaluation_requests] == ["removed", "e1"]
        assert all(request.path == "/api/v2/quality/evaluations/query" for request in evaluation_requests)
        assert all(request.param("expandAnswerTotalScores") == "true" for request in evaluation_requests)

    def test_evaluations_follow_next_uri_for_the_same_evaluator(self):
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return TOKEN
            if request.path == "/api/v2/users":
                return ScriptedResponse(json={"entities": [{"id": "e1"}], "pageCount": 1})
            if request.param("pageNumber") == "1":
                return ScriptedResponse(
                    json={
                        "entities": [{"id": "ev1"}],
                        "nextUri": "https://evil.example.com/api/v2/quality/evaluations/query?evaluatorUserId=other&pageNumber=2&previousPage=tok",
                    }
                )
            return ScriptedResponse(json={"entities": [{"id": "ev2"}], "nextUri": None})

        result = _driver().run("evaluations", respond)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["ev1", "ev2"]
        second_page = result.requests[-1]
        assert second_page.origin == result.requests[2].origin
        assert second_page.path == "/api/v2/quality/evaluations/query"
        assert (second_page.param("evaluatorUserId"), second_page.param("previousPage")) == ("e1", "tok")

    def test_a_child_page_that_repeats_ends_the_parent(self):
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return TOKEN
            if request.path == "/api/v2/routing/queues":
                return ScriptedResponse(json={"entities": [{"id": "q1"}], "pageCount": 1})
            return ScriptedResponse(
                json={"entities": [{"id": "u1"}], "nextUri": "/api/v2/routing/queues/q1/members?pageNumber=2"}
            )

        result = _driver().run("queue_members", respond)

        assert result.raised is None
        assert result.params("pageNumber")[2:] == ["1", "2"]


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
            (
                "presence_definitions",
                403,
                False,
                "The OAuth client's role is missing the `presence:presenceDefinition:view` permission, which the presence_definitions table needs.",
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
                "presence_definitions": "/api/v2/presence/definitions",
            }[endpoint]
        )

    @pytest.mark.parametrize(
        "users,child_status,child_body,expected",
        [
            ([], None, None, (True, None)),
            ([{"id": "u1"}], 200, {"entities": []}, (True, None)),
            ([{"id": "u1"}], 400, {"code": "quality.query.invalid.user"}, (True, None)),
            (
                [{"id": "u1"}],
                403,
                {},
                (
                    False,
                    "The OAuth client's role is missing the `quality:evaluation:view` permission, which the evaluations table needs.",
                ),
            ),
        ],
    )
    def test_fan_out_probe_reads_one_child_of_the_first_parent(self, users, child_status, child_body, expected):
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return TOKEN
            if request.path == "/api/v2/users":
                return ScriptedResponse(json={"entities": users})
            return ScriptedResponse(status=child_status or 500, json=child_body)

        with scripted_network(respond) as network:
            result = validate_credentials("mypurecloud.com", "cid", "secret", "evaluations")

        assert result == expected
        child_requests = network.requests_log[2:]
        assert [(request.path, request.param("evaluatorUserId")) for request in child_requests] == (
            [("/api/v2/quality/evaluations/query", "u1")] if users else []
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


class TestRetryPolicy:
    @pytest.mark.parametrize(
        "status_code,expected_retry",
        [
            (429, True),
            (504, True),
            (404, False),
        ],
    )
    def test_analytics_post_retries_like_the_listing_gets(self, status_code, expected_retry):
        # The analytics/user-analytics endpoints are read via POST; without the override below,
        # DEFAULT_RETRY would only retry the listing/scan endpoints' GETs and let a transient
        # 429/5xx on the POST query bubble up as an unhandled HTTPError.
        for method in ("GET", "POST"):
            assert _GENESYS_CLOUD_RETRY.is_retry(method, status_code) is expected_retry
