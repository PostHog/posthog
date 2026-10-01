import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.campaign_monitor import (
    FULL_REFRESH_SINCE_DATE,
    JOURNEY_FULL_REFRESH_SINCE_DATE,
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

    @mock.patch(CM_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("test-key") is False


class TestNonPaginatedEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_array_endpoint_yields_once_and_does_not_save_state(self, MockSession) -> None:
        session = MockSession.return_value
        rows = [{"ClientID": "c1"}, {"ClientID": "c2"}]
        snapshots = _wire(session, [_response(rows)])

        manager = _make_manager()
        assert _rows(_source("clients", manager)) == rows
        assert snapshots[0][0] == "https://api.createsend.com/api/v3.3/clients.json"
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_array_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(_source("lists")) == []

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
    def test_stops_at_number_of_pages_without_extra_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_envelope([{"EmailAddress": "a@x.com"}], number_of_pages=1, page_number=1)])

        rows = _rows(_source("suppression_list"))

        assert rows == [{"EmailAddress": "a@x.com"}]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_page_params_omit_date_for_non_date_filter_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_envelope([{"EmailAddress": "a@x.com"}])])

        _rows(_source("suppression_list"))

        _url, params = snapshots[0]
        assert "date" not in params
        assert params["pagesize"] == 1000
        assert params["orderfield"] == "date"
        assert params["orderdirection"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_envelope([{"EmailAddress": "b@x.com"}], number_of_pages=2, page_number=2)])

        manager = _make_manager(CampaignMonitorResumeConfig(page=2))
        rows = _rows(_source("suppression_list", manager))

        assert rows == [{"EmailAddress": "b@x.com"}]
        assert session.send.call_count == 1
        assert snapshots[0][1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sent_campaigns_endpoint_reads_paged_envelope(self, MockSession) -> None:
        # The sent-campaigns endpoint returns the paged envelope, not a bare array — a dict body
        # was raising "Required a list response body" and failing every campaign sync.
        session = MockSession.return_value
        snapshots = _wire(session, [_envelope([{"CampaignID": "c1"}, {"CampaignID": "c2"}])])

        rows = _rows(_source("campaigns"))

        assert [r["CampaignID"] for r in rows] == ["c1", "c2"]
        assert snapshots[0][0].endswith("clients/client-abc/campaigns.json")
        assert snapshots[0][1]["pagesize"] == 1000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_results_key_yields_nothing(self, MockSession) -> None:
        # Campaign Monitor's paged envelope without Results is treated as a zero-row page.
        session = MockSession.return_value
        _wire(session, [_response({"NumberOfPages": 1, "PageNumber": 1})])

        assert _rows(_source("suppression_list")) == []


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
    def test_date_filter_endpoint_requests_full_history(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"ListID": "l1"}]),
                _envelope([{"EmailAddress": "a@x.com"}]),
            ],
        )

        _rows(_source("active_subscribers"))

        _url, params = snapshots[1]
        assert params["date"] == FULL_REFRESH_SINCE_DATE
        assert params["page"] == 1
        assert params["pagesize"] == 1000
        assert params["orderfield"] == "date"
        assert params["orderdirection"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_within_a_list(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"ListID": "l1"}]),
                _envelope([{"EmailAddress": "a@x.com"}], number_of_pages=2, page_number=1),
                _envelope([{"EmailAddress": "b@x.com"}], number_of_pages=2, page_number=2),
            ],
        )

        rows = _rows(_source("active_subscribers"))

        assert [r["EmailAddress"] for r in rows] == ["a@x.com", "b@x.com"]
        assert snapshots[2][0].endswith("lists/l1/active.json")
        assert snapshots[2][1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_completed_lists(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"ListID": "l1"}, {"ListID": "l2"}]),
                _envelope([{"EmailAddress": "a@x.com"}]),
                _envelope([{"EmailAddress": "b@x.com"}]),
            ],
        )

        manager = _make_manager()
        _rows(_source("active_subscribers", manager))

        # after finishing l1 a checkpoint marks it completed, so a crash resumes on l2, not l1
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert any(
            state.fanout_state is not None and "lists/l1/active.json" in state.fanout_state["completed"]
            for state in saved
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_lists_and_resumes_page(self, MockSession) -> None:
        # Resuming mid-fan-out must not re-request lists completed before the crash, and must start
        # the in-progress list from its saved page.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"ListID": "l1"}, {"ListID": "l2"}, {"ListID": "l3"}]),  # lists.json re-fetched
                _envelope([{"EmailAddress": "b@x.com"}], number_of_pages=2, page_number=2),  # l2 resumed
                _envelope([{"EmailAddress": "c@x.com"}]),  # l3 fresh
            ],
        )

        manager = _make_manager(
            CampaignMonitorResumeConfig(
                fanout_state={
                    "completed": ["lists/l1/active.json"],
                    "current": "lists/l2/active.json",
                    "child_state": {"page": 2},
                }
            )
        )
        rows = _rows(_source("active_subscribers", manager))

        urls = [url for url, _params in snapshots]
        assert not any("lists/l1/active.json" in url for url in urls)
        assert snapshots[1][0].endswith("lists/l2/active.json")
        assert snapshots[1][1]["page"] == 2
        assert snapshots[2][0].endswith("lists/l3/active.json")
        assert snapshots[2][1]["page"] == 1
        assert [(r["EmailAddress"], r["ListID"]) for r in rows] == [("b@x.com", "l2"), ("c@x.com", "l3")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pre_migration_resume_state_starts_fresh(self, MockSession) -> None:
        # An old-shape bookmark (list_id + page, no fanout_state) can't be translated into the
        # framework's completed/current map — the fan-out restarts from the first list instead.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"ListID": "l1"}, {"ListID": "l2"}]),
                _envelope([{"EmailAddress": "a@x.com"}]),
                _envelope([{"EmailAddress": "b@x.com"}]),
            ],
        )

        manager = _make_manager(CampaignMonitorResumeConfig(list_id="l2", page=3))
        rows = _rows(_source("active_subscribers", manager))

        assert [(r["EmailAddress"], r["ListID"]) for r in rows] == [("a@x.com", "l1"), ("b@x.com", "l2")]
        assert snapshots[1][0].endswith("lists/l1/active.json")
        assert snapshots[1][1]["page"] == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_custom_fields_yield_a_row_per_field_with_its_list_id(self, MockSession) -> None:
        # Custom field keys are unique within a list, not across them, so the list id has to land
        # as a plain column — it is half the primary key.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"ListID": "l1"}, {"ListID": "l2"}]),
                _response([{"FieldName": "website", "Key": "[website]", "DataType": "Text", "FieldOptions": []}]),
                _response([{"FieldName": "age", "Key": "[age]", "DataType": "Number", "FieldOptions": []}]),
            ],
        )

        rows = _rows(_source("list_custom_fields"))

        assert [(row["Key"], row["ListID"]) for row in rows] == [("[website]", "l1"), ("[age]", "l2")]
        assert snapshots[1][0].endswith("lists/l1/customfields.json")
        assert snapshots[2][0].endswith("lists/l2/customfields.json")
        assert "page" not in snapshots[1][1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_custom_fields_non_list_body_raises_loudly(self, MockSession) -> None:
        # The endpoint returns a bare array; a 200 object means the response shape changed.
        session = MockSession.return_value
        _wire(session, [_response([{"ListID": "l1"}]), _response({"Code": 250, "Message": "Fail"})])

        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("list_custom_fields"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stats_yield_one_snapshot_row_per_list(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"ListID": "l1"}, {"ListID": "l2"}]),
                _response({"TotalActiveSubscribers": 10, "TotalUnsubscribes": 1}),
                _response({"TotalActiveSubscribers": 20, "TotalUnsubscribes": 2}),
            ],
        )

        rows = _rows(_source("list_stats"))

        assert rows == [
            {"TotalActiveSubscribers": 10, "TotalUnsubscribes": 1, "ListID": "l1"},
            {"TotalActiveSubscribers": 20, "TotalUnsubscribes": 2, "ListID": "l2"},
        ]
        assert snapshots[1][0].endswith("lists/l1/stats.json")
        assert snapshots[2][0].endswith("lists/l2/stats.json")


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
    def test_campaign_summary_yields_object_per_campaign_and_checkpoints(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _envelope([{"CampaignID": "c1"}, {"CampaignID": "c2"}]),
                _response({"Name": "Newsletter", "Recipients": 100, "UniqueOpened": 40}),  # c1 summary
                _response({"Name": "Promo", "Recipients": 50, "UniqueOpened": 10}),  # c2 summary
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("campaign_summary", manager))

        assert rows == [
            {"Name": "Newsletter", "Recipients": 100, "UniqueOpened": 40, "CampaignID": "c1"},
            {"Name": "Promo", "Recipients": 50, "UniqueOpened": 10, "CampaignID": "c2"},
        ]
        assert snapshots[1][0].endswith("campaigns/c1/summary.json")
        assert snapshots[2][0].endswith("campaigns/c2/summary.json")
        # after finishing c1 a checkpoint marks it completed, so a crash resumes on c2, not c1
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert any(
            state.fanout_state is not None and "campaigns/c1/summary.json" in state.fanout_state["completed"]
            for state in saved
        )

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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_campaign_recipients_order_by_email_and_carry_their_list(self, MockSession) -> None:
        # Recipient rows have no timestamp, so this endpoint orders by email rather than by the
        # `date` the other campaign reports use — passing `orderfield=date` here is rejected.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _envelope([{"CampaignID": "c1"}]),
                _envelope([{"EmailAddress": "a@x.com", "ListID": "l1"}]),
            ],
        )

        rows = _rows(_source("campaign_recipients"))

        assert rows == [{"EmailAddress": "a@x.com", "ListID": "l1", "CampaignID": "c1"}]
        assert snapshots[1][0].endswith("campaigns/c1/recipients.json")
        _url, params = snapshots[1]
        assert params["orderfield"] == "email"
        assert params["orderdirection"] == "asc"
        assert "date" not in params

    @staticmethod
    def _lists_and_segments() -> Response:
        return _response(
            {
                "Lists": [{"ListID": "l1", "Name": "My List"}],
                "Segments": [{"ListID": "l1", "SegmentID": "s1", "Title": "My Segment"}],
            }
        )

    @pytest.mark.parametrize(
        "endpoint, expected_row",
        [
            ("campaign_lists", {"ListID": "l1", "Name": "My List", "CampaignID": "c1"}),
            ("campaign_segments", {"ListID": "l1", "SegmentID": "s1", "Title": "My Segment", "CampaignID": "c1"}),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_lists_and_segments_body_feeds_two_tables(self, MockSession, endpoint: str, expected_row: dict) -> None:
        # One endpoint, two collections: each table must pick only its own array out of the body.
        session = MockSession.return_value
        snapshots = _wire(session, [_envelope([{"CampaignID": "c1"}]), self._lists_and_segments()])

        assert _rows(_source(endpoint)) == [expected_row]
        assert snapshots[1][0].endswith("campaigns/c1/listsandsegments.json")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_lists_and_segments_tolerates_a_missing_collection(self, MockSession) -> None:
        # A campaign sent to no segments is a zero-row page, not a response-shape failure.
        session = MockSession.return_value
        _wire(session, [_envelope([{"CampaignID": "c1"}]), _response({"Lists": [{"ListID": "l1", "Name": "My List"}]})])

        assert _rows(_source("campaign_segments")) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_email_client_usage_yields_a_row_per_client_version(self, MockSession) -> None:
        # A client family appears once per version, so both are part of the primary key.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _envelope([{"CampaignID": "c1"}]),
                _response(
                    [
                        {"Client": "Apple Mail", "Version": "Apple Mail 6", "Percentage": 13.02, "Subscribers": 4633},
                        {"Client": "Apple Mail", "Version": "Apple Mail 7", "Percentage": 4.94, "Subscribers": 1632},
                    ]
                ),
            ],
        )

        rows = _rows(_source("campaign_email_client_usage"))

        assert [(row["Client"], row["Version"], row["CampaignID"]) for row in rows] == [
            ("Apple Mail", "Apple Mail 6", "c1"),
            ("Apple Mail", "Apple Mail 7", "c1"),
        ]
        assert snapshots[1][0].endswith("campaigns/c1/emailclientusage.json")


class TestJourneyFanOut:
    @staticmethod
    def _summary(journey_id: str, email_ids: list[str]) -> Response:
        return _response(
            {
                "JourneyID": journey_id,
                "Name": "Welcome",
                "TriggerType": "On Subscription",
                "Status": "Active",
                "Emails": [{"EmailID": email_id, "Name": "Email one", "Sent": 1} for email_id in email_ids],
            }
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_summary_yields_one_row_per_journey_email(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"JourneyID": "j1"}, {"JourneyID": "j2"}]),  # journeys.json (bare array)
                self._summary("j1", ["e1", "e2"]),
                self._summary("j2", ["e3"]),
            ],
        )

        rows = _rows(_source("journey_email_summary"))

        # the nested `Emails` array is the grain, with the parent journey id as a plain column
        assert [(row["JourneyID"], row["EmailID"]) for row in rows] == [("j1", "e1"), ("j1", "e2"), ("j2", "e3")]
        assert snapshots[0][0].endswith("clients/client-abc/journeys.json")
        assert snapshots[1][0].endswith("journeys/j1.json")
        assert snapshots[2][0].endswith("journeys/j2.json")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_journey_without_emails_yields_nothing(self, MockSession) -> None:
        # A journey that has never been built has no emails — that is a zero-row page, not a
        # response-shape failure.
        session = MockSession.return_value
        _wire(session, [_response([{"JourneyID": "j1"}]), self._summary("j1", [])])

        assert _rows(_source("journey_email_summary")) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_report_resolves_email_ids_through_the_journey_summary(self, MockSession) -> None:
        # The journeys list exposes no email ids, so a report endpoint has to walk two levels:
        # journeys -> journey summary -> the report for each of its emails.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"JourneyID": "j1"}, {"JourneyID": "j2"}]),
                self._summary("j1", ["e1"]),
                _envelope([{"EmailAddress": "a@x.com", "Date": "2026-01-02 03:04:00"}]),
                self._summary("j2", ["e2"]),
                _envelope([{"EmailAddress": "b@x.com", "Date": "2026-01-03 03:04:00"}]),
            ],
        )

        rows = _rows(_source("journey_email_opens"))

        # both parent ids must land as plain columns — they are part of the primary key
        assert [(row["EmailAddress"], row["JourneyID"], row["EmailID"]) for row in rows] == [
            ("a@x.com", "j1", "e1"),
            ("b@x.com", "j2", "e2"),
        ]
        urls = [url for url, _params in snapshots]
        assert urls[1].endswith("journeys/j1.json")
        assert urls[2].endswith("journeys/email/e1/opens.json")
        assert urls[4].endswith("journeys/email/e2/opens.json")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_report_requests_full_history_without_an_order_field(self, MockSession) -> None:
        # Journey reports default `date` to the last 30 days, so it always has to be sent, in the
        # documented `YYYY-MM-DD HH:MM` form. They accept `orderdirection` but no `orderfield`.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"JourneyID": "j1"}]),
                self._summary("j1", ["e1"]),
                _envelope([{"EmailAddress": "a@x.com"}]),
            ],
        )

        _rows(_source("journey_email_clicks"))

        _url, params = snapshots[2]
        assert params["date"] == JOURNEY_FULL_REFRESH_SINCE_DATE
        assert params["orderdirection"] == "asc"
        assert "orderfield" not in params
        assert params["pagesize"] == 1000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_report_paginates_within_a_journey_email(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"JourneyID": "j1"}]),
                self._summary("j1", ["e1"]),
                _envelope([{"EmailAddress": "a@x.com"}], number_of_pages=2, page_number=1),
                _envelope([{"EmailAddress": "b@x.com"}], number_of_pages=2, page_number=2),
            ],
        )

        rows = _rows(_source("journey_email_bounces"))

        assert [row["EmailAddress"] for row in rows] == ["a@x.com", "b@x.com"]
        assert snapshots[3][0].endswith("journeys/email/e1/bounces.json")
        assert snapshots[3][1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_report_saves_no_resume_state(self, MockSession) -> None:
        # The framework refuses to share one resume hook across a two-level chain, because state
        # written from both levels would be ambiguous. A restart re-walks the chain instead, and
        # the merge dedupes the re-pulled rows.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"JourneyID": "j1"}]),
                self._summary("j1", ["e1"]),
                _envelope([{"EmailAddress": "a@x.com"}]),
            ],
        )

        manager = _make_manager()
        _rows(_source("journey_email_unsubscribes", manager))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_summary_checkpoints_completed_journeys(self, MockSession) -> None:
        # The summary is a single-level fan-out, so it does checkpoint: a crash resumes on j2.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"JourneyID": "j1"}, {"JourneyID": "j2"}]),
                self._summary("j1", ["e1"]),
                self._summary("j2", ["e2"]),
            ],
        )

        manager = _make_manager()
        _rows(_source("journey_email_summary", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert any(
            state.fanout_state is not None and "journeys/j1.json" in state.fanout_state["completed"] for state in saved
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
        response = _source(endpoint)

        if expected_partition_key is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition_key]
            assert response.partition_mode == "datetime"
