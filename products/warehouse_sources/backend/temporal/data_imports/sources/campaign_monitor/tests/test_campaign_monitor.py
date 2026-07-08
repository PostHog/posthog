import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.campaign_monitor import (
    FULL_REFRESH_SINCE_DATE,
    CampaignMonitorResumeConfig,
    _page_params,
    campaign_monitor_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.settings import (
    CAMPAIGN_MONITOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


def _make_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class _FakeSession:
    """Records request URLs and returns queued responses in order."""

    def __init__(self, responses: list[Response]) -> None:
        self._responses = iter(responses)
        self.urls: list[str] = []

    def get(self, url: str, *_args: Any, **_kwargs: Any) -> Response:
        self.urls.append(url)
        return next(self._responses)


def _patch_session(session: _FakeSession):
    return patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.campaign_monitor.make_tracked_session",
        return_value=session,
    )


def _manager(can_resume: bool = False, state: CampaignMonitorResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


def _drive(endpoint: str, responses: list[Response], manager: MagicMock) -> tuple[_FakeSession, list[list[dict]]]:
    session = _FakeSession(responses)
    with _patch_session(session):
        batches = list(
            get_rows(
                api_key="test-key",
                client_id="client-abc",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
            )
        )
    return session, batches


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        session = _FakeSession([_make_response({}, status_code=status_code)])
        with _patch_session(session):
            assert validate_credentials("test-key") is expected
        assert session.urls[0].endswith("/clients.json")

    def test_validate_credentials_swallows_exceptions(self) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("boom")
        with _patch_session(session):
            assert validate_credentials("test-key") is False


class TestPageParams:
    def test_date_filter_endpoint_includes_full_history_date(self) -> None:
        params = _page_params(CAMPAIGN_MONITOR_ENDPOINTS["active_subscribers"], page=1)

        assert params["date"] == FULL_REFRESH_SINCE_DATE
        assert params["orderfield"] == "date"
        assert params["orderdirection"] == "asc"
        assert params["page"] == 1
        assert params["pagesize"] == 1000

    def test_non_date_filter_endpoint_omits_date(self) -> None:
        params = _page_params(CAMPAIGN_MONITOR_ENDPOINTS["suppression_list"], page=2)

        assert "date" not in params
        assert params["page"] == 2
        assert params["orderfield"] == "date"


class TestGetRowsNonPaginated:
    def test_array_endpoint_yields_once_and_does_not_save_state(self) -> None:
        manager = _manager()
        rows = [{"ClientID": "c1"}, {"ClientID": "c2"}]
        session, batches = _drive("clients", [_make_response(rows)], manager)

        assert batches == [rows]
        assert session.urls == ["https://api.createsend.com/api/v3.3/clients.json"]
        manager.save_state.assert_not_called()

    def test_empty_array_yields_nothing(self) -> None:
        manager = _manager()
        _, batches = _drive("lists", [_make_response([])], manager)

        assert batches == []


class TestGetRowsPaginated:
    def test_multi_page_saves_state_between_pages_only(self) -> None:
        manager = _manager()
        responses = [
            _make_response({"Results": [{"EmailAddress": "a@x.com"}], "NumberOfPages": 2, "PageNumber": 1}),
            _make_response({"Results": [{"EmailAddress": "b@x.com"}], "NumberOfPages": 2, "PageNumber": 2}),
        ]
        session, batches = _drive("suppression_list", responses, manager)

        assert batches == [[{"EmailAddress": "a@x.com"}], [{"EmailAddress": "b@x.com"}]]
        # First page is not terminal -> save next page; second page is terminal -> no save.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [CampaignMonitorResumeConfig(list_id=None, page=2)]
        assert "page=1" in session.urls[0]
        assert "page=2" in session.urls[1]

    def test_resume_starts_from_saved_page(self) -> None:
        manager = _manager(can_resume=True, state=CampaignMonitorResumeConfig(list_id=None, page=2))
        responses = [
            _make_response({"Results": [{"EmailAddress": "b@x.com"}], "NumberOfPages": 2, "PageNumber": 2}),
        ]
        session, batches = _drive("suppression_list", responses, manager)

        assert batches == [[{"EmailAddress": "b@x.com"}]]
        assert len(session.urls) == 1
        assert "page=2" in session.urls[0]
        manager.load_state.assert_called_once()


class TestGetRowsFanOut:
    def test_fan_out_over_lists_injects_list_id(self) -> None:
        manager = _manager()
        responses = [
            _make_response([{"ListID": "l1"}, {"ListID": "l2"}]),  # lists.json
            _make_response({"Results": [{"EmailAddress": "a@x.com"}], "NumberOfPages": 1, "PageNumber": 1}),  # l1
            _make_response({"Results": [{"EmailAddress": "b@x.com"}], "NumberOfPages": 1, "PageNumber": 1}),  # l2
        ]
        session, batches = _drive("active_subscribers", responses, manager)

        assert batches == [
            [{"EmailAddress": "a@x.com", "ListID": "l1"}],
            [{"EmailAddress": "b@x.com", "ListID": "l2"}],
        ]
        assert session.urls[0].endswith("clients/client-abc/lists.json")
        assert "lists/l1/active.json" in session.urls[1]
        assert "lists/l2/active.json" in session.urls[2]

    def test_fan_out_advances_bookmark_to_next_list(self) -> None:
        manager = _manager()
        responses = [
            _make_response([{"ListID": "l1"}, {"ListID": "l2"}]),
            _make_response({"Results": [{"EmailAddress": "a@x.com"}], "NumberOfPages": 1, "PageNumber": 1}),
            _make_response({"Results": [{"EmailAddress": "b@x.com"}], "NumberOfPages": 1, "PageNumber": 1}),
        ]
        _drive("active_subscribers", responses, manager)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        # Each list finishes on a single (terminal) page, so the only save is the cross-list
        # advance written after the first list. No save after the last list (nothing follows).
        assert saved == [CampaignMonitorResumeConfig(list_id="l2", page=1)]

    def test_fan_out_resumes_into_correct_list_and_page(self) -> None:
        manager = _manager(can_resume=True, state=CampaignMonitorResumeConfig(list_id="l2", page=1))
        responses = [
            _make_response([{"ListID": "l1"}, {"ListID": "l2"}]),
            _make_response({"Results": [{"EmailAddress": "b@x.com"}], "NumberOfPages": 1, "PageNumber": 1}),  # l2 only
        ]
        session, batches = _drive("active_subscribers", responses, manager)

        assert batches == [[{"EmailAddress": "b@x.com", "ListID": "l2"}]]
        # lists.json is re-fetched to rebuild the ordering, then we skip straight to l2.
        assert "lists/l2/active.json" in session.urls[1]

    def test_fan_out_resume_restarts_when_bookmarked_list_is_gone(self) -> None:
        # The bookmarked list was deleted between runs: fall back to the first list rather than
        # resuming into the wrong one (the index-based bookmark would have silently mis-resumed).
        manager = _manager(can_resume=True, state=CampaignMonitorResumeConfig(list_id="deleted", page=3))
        responses = [
            _make_response([{"ListID": "l1"}, {"ListID": "l2"}]),
            _make_response({"Results": [{"EmailAddress": "a@x.com"}], "NumberOfPages": 1, "PageNumber": 1}),
            _make_response({"Results": [{"EmailAddress": "b@x.com"}], "NumberOfPages": 1, "PageNumber": 1}),
        ]
        session, batches = _drive("active_subscribers", responses, manager)

        assert batches == [
            [{"EmailAddress": "a@x.com", "ListID": "l1"}],
            [{"EmailAddress": "b@x.com", "ListID": "l2"}],
        ]
        assert "lists/l1/active.json" in session.urls[1]
        assert "page=1" in session.urls[1]


class TestGetRowsCampaignFanOut:
    def test_fan_out_over_campaigns_injects_campaign_id(self) -> None:
        manager = _manager()
        responses = [
            _make_response([{"CampaignID": "c1"}, {"CampaignID": "c2"}]),  # campaigns.json
            _make_response({"Results": [{"EmailAddress": "a@x.com"}], "NumberOfPages": 1, "PageNumber": 1}),  # c1
            _make_response({"Results": [{"EmailAddress": "b@x.com"}], "NumberOfPages": 1, "PageNumber": 1}),  # c2
        ]
        session, batches = _drive("campaign_opens", responses, manager)

        assert batches == [
            [{"EmailAddress": "a@x.com", "CampaignID": "c1"}],
            [{"EmailAddress": "b@x.com", "CampaignID": "c2"}],
        ]
        assert session.urls[0].endswith("clients/client-abc/campaigns.json")
        assert "campaigns/c1/opens.json" in session.urls[1]
        assert "campaigns/c2/opens.json" in session.urls[2]

    def test_campaign_summary_yields_object_per_campaign_and_advances_bookmark(self) -> None:
        manager = _manager()
        responses = [
            _make_response([{"CampaignID": "c1"}, {"CampaignID": "c2"}]),
            _make_response({"Name": "Newsletter", "Recipients": 100, "UniqueOpened": 40}),  # c1 summary
            _make_response({"Name": "Promo", "Recipients": 50, "UniqueOpened": 10}),  # c2 summary
        ]
        session, batches = _drive("campaign_summary", responses, manager)

        assert batches == [
            [{"Name": "Newsletter", "Recipients": 100, "UniqueOpened": 40, "CampaignID": "c1"}],
            [{"Name": "Promo", "Recipients": 50, "UniqueOpened": 10, "CampaignID": "c2"}],
        ]
        assert "campaigns/c1/summary.json" in session.urls[1]
        assert "campaigns/c2/summary.json" in session.urls[2]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [CampaignMonitorResumeConfig(campaign_id="c2", page=1)]

    def test_fan_out_resumes_into_correct_campaign(self) -> None:
        manager = _manager(can_resume=True, state=CampaignMonitorResumeConfig(campaign_id="c2", page=1))
        responses = [
            _make_response([{"CampaignID": "c1"}, {"CampaignID": "c2"}]),
            _make_response({"Results": [{"EmailAddress": "b@x.com"}], "NumberOfPages": 1, "PageNumber": 1}),  # c2 only
        ]
        session, batches = _drive("campaign_opens", responses, manager)

        assert batches == [[{"EmailAddress": "b@x.com", "CampaignID": "c2"}]]
        assert "campaigns/c2/opens.json" in session.urls[1]


class TestCampaignMonitorSourceResponse:
    @pytest.mark.parametrize("endpoint", list(CAMPAIGN_MONITOR_ENDPOINTS.keys()))
    def test_source_response_primary_keys_match_settings(self, endpoint: str) -> None:
        response = campaign_monitor_source(
            api_key="test-key",
            client_id="client-abc",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )

        config = CAMPAIGN_MONITOR_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize(
        "endpoint, expected_partition_key",
        [
            ("campaigns", "SentDate"),
            ("suppression_list", "Date"),
            ("active_subscribers", "Date"),
            ("campaign_opens", "Date"),
            ("campaign_summary", None),
            ("clients", None),
            ("lists", None),
        ],
    )
    def test_source_response_partition_keys(self, endpoint: str, expected_partition_key: str | None) -> None:
        response = campaign_monitor_source(
            api_key="test-key",
            client_id="client-abc",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )

        if expected_partition_key is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition_key]
            assert response.partition_mode == "datetime"
