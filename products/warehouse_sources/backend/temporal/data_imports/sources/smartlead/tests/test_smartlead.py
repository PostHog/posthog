import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.smartlead import (
    SmartleadResumeConfig,
    smartlead_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the smartlead module.
SMARTLEAD_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.smartlead.make_tracked_session"
)
FANOUT_REST_RESOURCES_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
)


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SmartleadResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return smartlead_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _accounts(count: int, start: int = 0) -> list[dict[str, Any]]:
    return [{"id": start + i, "from_email": f"a{start + i}@example.com"} for i in range(count)]


class TestSmartleadSource:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_offset_pagination_walks_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [_response(_accounts(PAGE_SIZE)), _response(_accounts(1, start=PAGE_SIZE))],
        )

        rows = _rows(_source("email_accounts", _make_manager()))

        assert len(rows) == PAGE_SIZE + 1
        assert session.send.call_count == 2
        assert snapshots[0]["url"] == "https://server.smartlead.ai/api/v1/email-accounts/"
        assert snapshots[0]["params"] == {"offset": 0, "limit": PAGE_SIZE}
        assert snapshots[1]["params"]["offset"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_is_framework_api_key_query_param(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response(_accounts(1))])

        _rows(_source("email_accounts", _make_manager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, APIKeyAuth)
        assert auth.name == "api_key"
        assert auth.location == "query"
        assert auth.api_key == "key"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_email_accounts_strip_mailbox_credentials(self, MockSession) -> None:
        # Smartlead returns the connected mailbox's SMTP/IMAP passwords (base64-encoded) on
        # this endpoint; syncing them would store live credentials in the warehouse.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    [
                        {
                            "id": 1,
                            "from_email": "a@example.com",
                            "password": "c2VjcmV0",
                            "imap_password": "c2VjcmV0",
                        }
                    ]
                )
            ],
        )

        rows = _rows(_source("email_accounts", _make_manager()))

        assert rows == [{"id": 1, "from_email": "a@example.com"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_campaigns_single_page_never_paginates(self, MockSession) -> None:
        # The campaign list is unpaginated. An offset paginator here would refetch the same full
        # array forever, because a full-length page never triggers the short-page stop.
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": i} for i in range(PAGE_SIZE * 2)])])

        rows = _rows(_source("campaigns", _make_manager()))

        assert len(rows) == PAGE_SIZE * 2
        assert session.send.call_count == 1
        assert snapshots[0]["url"] == "https://server.smartlead.ai/api/v1/campaigns/"
        assert "offset" not in snapshots[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_enveloped_body_on_list_endpoint_fails_loud(self, MockSession) -> None:
        # The docs show an `{ok, data}` envelope for /client/ while the live API historically
        # returns a bare array. Whichever way the API answers, a non-list body must raise
        # instead of silently syncing a garbage row.
        session = MockSession.return_value
        _wire(session, [_response({"ok": True, "data": [{"id": 1}]})])

        with pytest.raises(ValueError, match="Required a list response body"):
            _rows(_source("clients", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_only_while_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_accounts(PAGE_SIZE)), _response(_accounts(1, start=PAGE_SIZE))])

        manager = _make_manager()
        _rows(_source("email_accounts", manager))

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == SmartleadResumeConfig(next_offset=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response(_accounts(1, start=PAGE_SIZE))])

        rows = _rows(_source("email_accounts", _make_manager(SmartleadResumeConfig(next_offset=PAGE_SIZE))))

        assert [r["id"] for r in rows] == [PAGE_SIZE]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["offset"] == PAGE_SIZE


class TestSmartleadFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_leads_fan_out_paginates_per_campaign_and_injects_campaign_id(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": 11}, {"id": 22}]),
                _response(
                    {"total_leads": str(PAGE_SIZE + 1), "data": [{"campaign_lead_map_id": i} for i in range(PAGE_SIZE)]}
                ),
                _response({"total_leads": str(PAGE_SIZE + 1), "data": [{"campaign_lead_map_id": PAGE_SIZE}]}),
                _response({"total_leads": "1", "data": [{"campaign_lead_map_id": 9000}]}),
            ],
        )

        rows = _rows(_source("campaign_leads", _make_manager()))

        # Parent listed once (no pagination), campaign 11 paged twice, campaign 22 once.
        assert session.send.call_count == 4
        assert snapshots[0]["url"].endswith("/campaigns/")
        assert "offset" not in snapshots[0]["params"]
        assert snapshots[1]["url"].endswith("/campaigns/11/leads")
        assert snapshots[1]["params"]["offset"] == 0
        assert snapshots[2]["params"]["offset"] == PAGE_SIZE
        assert snapshots[3]["url"].endswith("/campaigns/22/leads")
        assert snapshots[3]["params"]["offset"] == 0

        assert len(rows) == PAGE_SIZE + 2
        # Lead rows don't carry their campaign id; the fan-out injects it for the composite key.
        assert rows[0]["campaign_id"] == 11
        assert rows[-1]["campaign_id"] == 22

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_analytics_object_body_becomes_one_row_per_campaign(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 11}]),
                _response({"campaign_name": "Q1", "total_sent": 10}),
            ],
        )

        rows = _rows(_source("campaign_analytics", _make_manager()))

        assert rows == [{"campaign_name": "Q1", "total_sent": 10, "campaign_id": 11}]

    @mock.patch(FANOUT_REST_RESOURCES_PATCH)
    def test_fan_out_resumes_completed_and_current_campaign(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            mock.MagicMock(name="campaigns"),
            mock.MagicMock(name="campaign_leads"),
        ]
        mock_rest_api_resources.return_value[0].name = "campaigns"
        mock_rest_api_resources.return_value[1].name = "campaign_leads"

        resume = SmartleadResumeConfig(
            completed=["/campaigns/11/leads"],
            current="/campaigns/22/leads",
            child_state={"offset": PAGE_SIZE},
        )
        _source("campaign_leads", _make_manager(resume))

        _, kwargs = mock_rest_api_resources.call_args
        assert kwargs["initial_paginator_state"] == {
            "completed": ["/campaigns/11/leads"],
            "current": "/campaigns/22/leads",
            "child_state": {"offset": PAGE_SIZE},
        }


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, (True, 200)), (401, (False, 401)), (403, (False, 403))])
    @mock.patch(SMARTLEAD_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("key") == expected

    @mock.patch(SMARTLEAD_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") == (False, None)

    @mock.patch(SMARTLEAD_SESSION_PATCH)
    def test_probe_carries_key_in_query_and_never_follows_redirects(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://server.smartlead.ai/api/v1/email-accounts/?api_key=key&offset=0&limit=1"
        # The key rides in the query string; following a redirect would replay it off-host.
        assert call.kwargs["allow_redirects"] is False
        # The tracked session must mask the key in logs and captured samples.
        assert mock_session.call_args.kwargs["redact_values"] == ("key",)
