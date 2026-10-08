from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud import genesys_cloud
from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.genesys_cloud import (
    GenesysCloudResumeConfig,
    genesys_cloud_source,
    validate_credentials,
)

SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.genesys_cloud.make_tracked_session"
)
NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def _response(payload: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def _conversation(conversation_id: str, start: datetime, participants: list[dict[str, Any]] | None = None) -> dict:
    return {
        "conversationId": conversation_id,
        "conversationStart": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "participants": participants or [],
    }


def _manager(resume: GenesysCloudResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _request_interval(call: Any) -> tuple[datetime, datetime]:
    start, end = call.kwargs["json"]["interval"].split("/")
    return datetime.fromisoformat(start), datetime.fromisoformat(end)


def _run(endpoint: str, session: mock.MagicMock, manager: mock.MagicMock, watermark: Any = None) -> list[dict]:
    with mock.patch(SESSION_PATCH, return_value=session):
        response = genesys_cloud_source(
            region="mypurecloud.com",
            client_id="cid",
            client_secret="secret",
            endpoint=endpoint,
            resumable_source_manager=manager,
            db_incremental_field_last_value=watermark,
        )
        items = response.items()
        assert isinstance(items, Iterable)
        return [row for batch in items for row in batch]


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
        session = mock.MagicMock()
        session.post.side_effect = [
            _response({"totalHits": 102, "conversations": full_page}),
            _response({"totalHits": 102, "conversations": last_page}),
        ]
        manager = _manager(GenesysCloudResumeConfig(window_start=start.isoformat()))

        rows = _run("conversations", session, manager)

        assert [row["conversationId"] for row in rows] == [f"c{i}" for i in range(101)]
        assert [c.kwargs["json"]["paging"]["pageNumber"] for c in session.post.call_args_list] == [1, 2]
        assert _request_interval(session.post.call_args_list[0]) == (start, NOW)
        manager.save_state.assert_called_once_with(GenesysCloudResumeConfig(window_start="2026-03-10T12:00:00.000Z"))

    def test_splits_a_dense_ten_minute_window(self):
        start = NOW - timedelta(minutes=10)
        middle = NOW - timedelta(minutes=5)
        session = mock.MagicMock()
        session.post.side_effect = [
            _response({"totalHits": genesys_cloud.MAX_RESULTS_PER_WINDOW + 1, "conversations": []}),
            _response({"totalHits": 1, "conversations": [_conversation("early", start)]}),
            _response({"totalHits": 1, "conversations": [_conversation("late", middle)]}),
        ]
        manager = _manager(GenesysCloudResumeConfig(window_start=start.isoformat()))

        rows = _run("conversations", session, manager)

        assert [row["conversationId"] for row in rows] == ["early", "late"]
        assert [_request_interval(c) for c in session.post.call_args_list[1:]] == [(start, middle), (middle, NOW)]

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
        session = mock.MagicMock()
        session.post.return_value = _response({"totalHits": 0})
        manager = _manager(resume)

        _run("calls", session, manager, watermark=watermark)

        assert _request_interval(session.post.call_args_list[0])[0] == expected_start
        assert _request_interval(session.post.call_args_list[-1])[1] == NOW
        manager.safe_point.assert_called()

    def test_participants_are_flattened_with_conversation_keys(self):
        start = NOW - timedelta(hours=1)
        session = mock.MagicMock()
        session.post.return_value = _response(
            {
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
        )

        rows = _run("participants", session, _manager(GenesysCloudResumeConfig(window_start=start.isoformat())))

        assert [(row["conversationId"], row["participantId"], row["purpose"]) for row in rows] == [
            ("conv-1", "p1", "customer"),
            ("conv-1", "p2", "agent"),
        ]
        assert all(row["conversationStart"] == "2026-03-10T11:00:00.000Z" for row in rows)


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
            1: _response({"entities": [{"id": "q1"}], "pageNumber": 1, "pageCount": 2}),
            2: _response({"entities": [{"id": "q2"}], "pageNumber": 2, "pageCount": 2}),
        }
        session = mock.MagicMock()
        session.get.side_effect = lambda url, params, timeout: pages[params["pageNumber"]]
        manager = _manager(resume)

        rows = _run("queues", session, manager)

        requested = [c.kwargs["params"]["pageNumber"] for c in session.get.call_args_list]
        assert requested == expected_pages
        assert [row["id"] for row in rows] == [f"q{page}" for page in expected_pages]
        saved = [c.args[0].page_number for c in manager.save_state.call_args_list]
        assert saved == ([2] if resume is None else [])
        manager.clear_state.assert_called_once_with()


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "endpoint,status_code,expected_valid,expected_message",
        [
            (None, 200, True, None),
            (None, 403, True, None),
            (
                None,
                401,
                False,
                "Genesys Cloud rejected the access token. Check the client ID, client secret, and region.",
            ),
            (
                "conversations",
                403,
                False,
                "The OAuth client's role is missing the `analytics:conversationDetail:view` permission, which the conversations table needs.",
            ),
            ("users", 403, False, "The OAuth client does not have access to the users table."),
            ("queues", 500, False, "Genesys Cloud returned HTTP 500. Try again in a few minutes."),
        ],
    )
    def test_maps_probe_status(self, endpoint, status_code, expected_valid, expected_message):
        session = mock.MagicMock()
        session.get.return_value = _response({}, status_code)
        session.post.return_value = _response({}, status_code)

        with mock.patch(SESSION_PATCH, return_value=session):
            result = validate_credentials("mypurecloud.com", "cid", "secret", endpoint)

        assert result == (expected_valid, expected_message)

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
            (
                requests.ConnectionError("Name or service not known"),
                "Could not connect to Genesys Cloud. Check the selected region and try again.",
            ),
        ],
    )
    def test_maps_request_errors(self, error, expected_message):
        session = mock.MagicMock()
        session.get.side_effect = error

        with mock.patch(SESSION_PATCH, return_value=session):
            result = validate_credentials("mypurecloud.com", "cid", "secret")

        assert result == (False, expected_message)

    def test_rejects_unknown_region_without_a_request(self):
        with mock.patch(SESSION_PATCH) as make_session:
            result = validate_credentials("evil.example.com", "cid", "secret")

        assert result == (False, "Select the Genesys Cloud region your organization is hosted in.")
        make_session.assert_not_called()
