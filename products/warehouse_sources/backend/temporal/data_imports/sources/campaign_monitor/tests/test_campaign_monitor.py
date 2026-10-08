import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.campaign_monitor import (
    CampaignMonitorResumeConfig,
    campaign_monitor_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.settings import (
    CAMPAIGN_MONITOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the campaign_monitor module.
CM_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.campaign_monitor.make_tracked_session"


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _envelope(items: list[dict[str, Any]], number_of_pages: int = 1, page_number: int = 1) -> Response:
    return _response({"Results": items, "NumberOfPages": number_of_pages, "PageNumber": page_number})


def _make_manager(resume_state: CampaignMonitorResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session and return (url, params) snapshots captured AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock | None = None) -> SourceResponse:
    return campaign_monitor_source(
        api_key="test-key",
        client_id="client-abc",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager if manager is not None else _make_manager(),
    )


def _rows(source_response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(CM_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("test-key") is expected
        url = mock_session.return_value.get.call_args.args[0]
        assert url.endswith("/clients.json")


class TestNonPaginatedEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_raises_loudly(self, MockSession) -> None:
        # A 200 body that isn't a JSON array means the response shape changed — fail loud rather
        # than syncing a stray object as a row.
        session = MockSession.return_value
        _wire(session, [_response({"error": "unexpected"})])

        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("clients"))


class TestPaginatedEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_multi_page_saves_state_between_pages_only(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _envelope([{"EmailAddress": "a@x.com"}], number_of_pages=2, page_number=1),
                _envelope([{"EmailAddress": "b@x.com"}], number_of_pages=2, page_number=2),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("suppression_list", manager))

        assert rows == [{"EmailAddress": "a@x.com"}, {"EmailAddress": "b@x.com"}]
        assert snapshots[0][1]["page"] == 1
        assert snapshots[1][1]["page"] == 2
        # First page is not terminal -> save next page; second page is terminal -> no save.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == CampaignMonitorResumeConfig(page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_envelope([{"EmailAddress": "b@x.com"}], number_of_pages=2, page_number=2)])

        manager = _make_manager(CampaignMonitorResumeConfig(page=2))
        rows = _rows(_source("suppression_list", manager))

        assert rows == [{"EmailAddress": "b@x.com"}]
        assert session.send.call_count == 1
        assert snapshots[0][1]["page"] == 2


class TestListFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_iterates_every_list_and_injects_list_id(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"ListID": "l1"}, {"ListID": "l2"}]),  # lists.json
                _envelope([{"EmailAddress": "a@x.com"}]),  # l1
                _envelope([{"EmailAddress": "b@x.com"}]),  # l2
            ],
        )

        rows = _rows(_source("active_subscribers"))

        # the injected id must be the plain `ListID` column, not the prefixed parent key
        assert rows == [
            {"EmailAddress": "a@x.com", "ListID": "l1"},
            {"EmailAddress": "b@x.com", "ListID": "l2"},
        ]
        assert snapshots[0][0].endswith("clients/client-abc/lists.json")
        assert snapshots[1][0].endswith("lists/l1/active.json")
        assert snapshots[2][0].endswith("lists/l2/active.json")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_custom_fields_non_list_body_raises_loudly(self, MockSession) -> None:
        # The endpoint returns a bare array; a 200 object means the response shape changed.
        session = MockSession.return_value
        _wire(session, [_response([{"ListID": "l1"}]), _response({"Code": 250, "Message": "Fail"})])

        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("list_custom_fields"))


class TestCampaignFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_iterates_every_campaign_and_injects_campaign_id(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _envelope([{"CampaignID": "c1"}, {"CampaignID": "c2"}]),  # campaigns.json (paged envelope)
                _envelope([{"EmailAddress": "a@x.com"}]),  # c1
                _envelope([{"EmailAddress": "b@x.com"}]),  # c2
            ],
        )

        rows = _rows(_source("campaign_opens"))

        assert rows == [
            {"EmailAddress": "a@x.com", "CampaignID": "c1"},
            {"EmailAddress": "b@x.com", "CampaignID": "c2"},
        ]
        assert snapshots[0][0].endswith("clients/client-abc/campaigns.json")
        assert snapshots[1][0].endswith("campaigns/c1/opens.json")
        assert snapshots[2][0].endswith("campaigns/c2/opens.json")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_summary_object_yields_no_row(self, MockSession) -> None:
        # An empty summary body is not a row — no record carrying only the injected CampaignID.
        session = MockSession.return_value
        _wire(session, [_envelope([{"CampaignID": "c1"}]), _response({})])

        assert _rows(_source("campaign_summary")) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_campaigns(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _envelope([{"CampaignID": "c1"}, {"CampaignID": "c2"}]),  # campaigns.json re-fetched
                _envelope([{"EmailAddress": "b@x.com"}]),  # c2 only
            ],
        )

        manager = _make_manager(
            CampaignMonitorResumeConfig(
                fanout_state={"completed": ["campaigns/c1/opens.json"], "current": None, "child_state": None}
            )
        )
        rows = _rows(_source("campaign_opens", manager))

        assert rows == [{"EmailAddress": "b@x.com", "CampaignID": "c2"}]
        assert snapshots[1][0].endswith("campaigns/c2/opens.json")

    @staticmethod
    def _lists_and_segments() -> Response:
        return _response(
            {
                "Lists": [{"ListID": "l1", "Name": "My List"}],
                "Segments": [{"ListID": "l1", "SegmentID": "s1", "Title": "My Segment"}],
            }
        )


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
        response = _source(endpoint)

        config = CAMPAIGN_MONITOR_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
