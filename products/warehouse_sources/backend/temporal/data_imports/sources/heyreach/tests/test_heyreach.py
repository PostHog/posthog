import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.heyreach.heyreach import (
    STATS_START_DATE,
    HeyReachResumeConfig,
    heyreach_source,
    validate_credentials,
)

_REST_CLIENT_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"
    ".make_tracked_session"
)
_HEYREACH_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.heyreach.heyreach.make_tracked_session"
)


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _drive(
    endpoint: str, manager: MagicMock, responses: list[Response]
) -> tuple[list[tuple[str, dict[str, Any]]], list[Any]]:
    # Returns (sent, batches) where sent is a list of (url, json_body) captured at send time.
    # The Request object is mutated in place by the paginator between pages, so bodies are
    # copied per send instead of read back from call_args_list.
    sent: list[tuple[str, dict[str, Any]]] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent.append((request.url, dict(request.json or {})))
        return next(response_iter)

    with patch(_REST_CLIENT_SESSION) as MockSession:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.side_effect = lambda req: req
        mock_session.send.side_effect = fake_send

        response = heyreach_source(
            api_key="test-key",
            endpoint=endpoint,
            team_id=1,
            job_id="test_job",
            resumable_source_manager=manager,
        )
        batches = list(cast(Iterable[Any], response.items()))
        return sent, batches


def _fresh_manager(can_resume: bool = False) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    return manager


class TestTopLevelEndpoints:
    def test_fresh_run_pages_by_total_count_and_saves_offsets(self) -> None:
        manager = _fresh_manager()
        responses = [
            _make_http_response({"totalCount": 150, "items": [{"id": i} for i in range(100)]}),
            _make_http_response({"totalCount": 150, "items": [{"id": i} for i in range(100, 150)]}),
        ]

        sent, _ = _drive("campaigns", manager, responses)

        assert [body.get("offset") for _, body in sent] == [0, 100]
        assert all(body.get("limit") == 100 for _, body in sent)
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [HeyReachResumeConfig(offset=100)]

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        manager = _fresh_manager(can_resume=True)
        manager.load_state.return_value = HeyReachResumeConfig(offset=100)
        responses = [
            _make_http_response({"totalCount": 101, "items": [{"id": 100}]}),
        ]

        sent, _ = _drive("campaigns", manager, responses)

        assert [body.get("offset") for _, body in sent] == [100]
        manager.load_state.assert_called_once()

    def test_conversations_request_carries_required_filters_object(self) -> None:
        # GetConversationsV2 rejects requests without a `filters` object in the body.
        manager = _fresh_manager()
        responses = [
            _make_http_response({"totalCount": 1, "items": [{"id": "thread-1", "linkedInAccountId": 7}]}),
        ]

        sent, _ = _drive("conversations", manager, responses)

        url, body = sent[0]
        assert url.endswith("/inbox/GetConversationsV2")
        assert body["filters"] == {}
        assert body["offset"] == 0


class TestFanoutEndpoints:
    def test_campaign_leads_fans_out_per_campaign_and_injects_campaign_id(self) -> None:
        responses = [
            _make_http_response({"totalCount": 2, "items": [{"id": 1}, {"id": 2}]}),
            _make_http_response({"totalCount": 1, "items": [{"id": 11, "leadCampaignStatus": "Finished"}]}),
            _make_http_response({"totalCount": 1, "items": [{"id": 21, "leadCampaignStatus": "Pending"}]}),
        ]

        sent, batches = _drive("campaign_leads", _fresh_manager(), responses)

        paths = [url.split("/api/public")[1] for url, _ in sent]
        assert paths == [
            "/campaign/GetAll",
            "/campaign/GetLeadsFromCampaign",
            "/campaign/GetLeadsFromCampaign",
        ]
        assert [body.get("campaignId") for _, body in sent[1:]] == [1, 2]
        assert all(body.get("offset") == 0 and body.get("limit") == 100 for _, body in sent)

        rows = [row for batch in batches for row in batch]
        assert rows == [
            {"campaignId": 1, "id": 11, "leadCampaignStatus": "Finished"},
            {"campaignId": 2, "id": 21, "leadCampaignStatus": "Pending"},
        ]

    def test_list_leads_only_fans_out_lead_lists_and_skips_parents_without_id(self) -> None:
        responses = [
            _make_http_response({"totalCount": 2, "items": [{"id": 5}, {"name": "row without id"}]}),
            _make_http_response({"totalCount": 0, "items": []}),
        ]

        sent, batches = _drive("list_leads", _fresh_manager(), responses)

        parent_url, parent_body = sent[0]
        assert parent_url.endswith("/list/GetAll")
        # Company lists serve companies via a different endpoint, so the parent listing is
        # restricted to lead lists.
        assert parent_body["listType"] == "USER_LIST"
        # Only the parent with an id produces a child request, and an empty child page yields no batch.
        assert len(sent) == 2
        assert sent[1][1]["listId"] == 5
        assert batches == []


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
        responses = [_make_http_response(payload)]

        sent, batches = _drive("overall_stats", _fresh_manager(), responses)
        rows = [row for batch in batches for row in batch]

        assert len(rows) == expected_days
        if rows:
            assert rows[0]["messagesSent"] == 5
            assert rows[0]["date"].isoformat() == "2024-12-17T00:00:00+00:00"

        url, body = sent[0]
        assert url.endswith("/stats/GetOverallStats")
        assert body["startDate"] == STATS_START_DATE
        assert body["accountIds"] == []
        assert body["campaignIds"] == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_fragment"),
        [
            (200, True, None),
            (401, False, "HeyReach rejected the API key"),
            (403, False, "HeyReach rejected the API key"),
            (500, False, "unexpected status (500)"),
        ],
    )
    def test_maps_status_to_user_message(
        self, status_code: int, expected_valid: bool, expected_fragment: str | None
    ) -> None:
        with patch(_HEYREACH_SESSION) as MockSession:
            mock_session = MockSession.return_value
            mock_session.get.return_value = _make_http_response({}, status_code=status_code)

            valid, message = validate_credentials("test-key")

        assert valid is expected_valid
        if expected_fragment is None:
            assert message is None
        else:
            assert expected_fragment in (message or "")

    def test_transport_error_reports_unreachable_instead_of_raising(self) -> None:
        # A DNS failure or timeout during the probe must not raise out of validate_credentials
        # and fail source creation with a stack trace.
        with patch(_HEYREACH_SESSION) as MockSession:
            MockSession.return_value.get.side_effect = requests.ConnectionError("dns failure")

            valid, message = validate_credentials("test-key")

        assert valid is False
        assert "Couldn't reach HeyReach" in (message or "")

    def test_non_ascii_key_fails_without_a_request(self) -> None:
        # A non-latin-1 key can't be encoded into the X-API-KEY header; the raw
        # UnicodeEncodeError must never surface to the user.
        with patch(_HEYREACH_SESSION) as MockSession:
            valid, message = validate_credentials("bad中key")

        assert valid is False
        assert "Retype it by hand" in (message or "")
        MockSession.assert_not_called()


class TestUnknownEndpoint:
    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError, match="HeyReach endpoint does not exist"):
            heyreach_source(
                api_key="test-key",
                endpoint="does_not_exist",
                team_id=1,
                job_id="test_job",
                resumable_source_manager=_fresh_manager(),
            )
