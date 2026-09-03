import io
import json
from datetime import date, timedelta
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

import urllib3
import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.gladly import (
    CHUNK_SIZE,
    GladlyReportHeaderError,
    GladlyResumeConfig,
    GladlyRetryableError,
    _base_url,
    _clean_domain,
    _clean_organization,
    _normalize_report_column,
    get_rows,
    gladly_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.settings import ENDPOINTS, GLADLY_ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gladly.gladly"


def _make_manager(resume_state: GladlyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _jobs_response(jobs: list[dict[str, Any]]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = jobs
    resp.status_code = 200
    resp.ok = True
    return resp


def _jsonl_response(rows: list[dict[str, Any]], junk_lines: list[str] | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    lines = [json.dumps(row) for row in rows] + (junk_lines or [])
    resp.iter_lines.return_value = iter(lines)
    resp.status_code = 200
    resp.ok = True
    return resp


def _job(job_id: str, updated_at: str, files: list[str] | None = None) -> dict[str, Any]:
    return {"id": job_id, "updatedAt": updated_at, "files": files or ["customers.jsonl", "agents.jsonl"]}


def _csv_response(text: str) -> requests.Response:
    # A real urllib3-backed response so iter_content streams the body and an empty
    # body closes the connection on EOF exactly as it does in production.
    raw = urllib3.HTTPResponse(body=io.BytesIO(text.encode()), preload_content=False)
    response = requests.Response()
    response.raw = raw
    response.status_code = 200
    return response


def _error_response(status_code: int) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = False
    resp.text = "error body"
    resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Client Error", response=resp)
    return resp


class TestCleanOrganization:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("myorg", "myorg"),
            ("https://myorg.gladly.com", "myorg"),
            ("myorg.gladly.com/api/v1", "myorg"),
            ("my-org", "my-org"),
            ("myorg.us-1", "myorg.us-1"),
            ("https://myorg.us-1.gladly.com", "myorg.us-1"),
            ("MYORG.GLADLY.COM", "MYORG"),
        ],
    )
    def test_valid_organizations(self, value, expected):
        assert _clean_organization(value) == expected

    @pytest.mark.parametrize("value", ["", "my org", "org?x=1", "myorg.us-1.extra"])
    def test_invalid_organizations_raise(self, value):
        with pytest.raises(ValueError):
            _clean_organization(value)

    @pytest.mark.parametrize(
        "domain, expected",
        [
            (None, "https://myorg.gladly.com/api/v1"),
            ("gladly.com", "https://myorg.gladly.com/api/v1"),
            ("gladly.qa", "https://myorg.gladly.qa/api/v1"),
        ],
    )
    def test_base_url(self, domain, expected):
        assert (_base_url("myorg") if domain is None else _base_url("myorg", domain)) == expected


class TestCleanDomain:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("gladly.com", "gladly.com"),
            ("gladly.qa", "gladly.qa"),
            ("  GLADLY.QA  ", "gladly.qa"),
        ],
    )
    def test_allowed_domains(self, value, expected):
        assert _clean_domain(value) == expected

    @pytest.mark.parametrize("value", ["", "evil.com", "gladly.com.evil.com", "gladly.qa.evil.com", "gladly.dev"])
    def test_domains_outside_the_allowlist_raise(self, value):
        with pytest.raises(ValueError):
            _clean_domain(value)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message_fragment",
        [
            (200, True, None),
            (401, False, "agent email and API token"),
            (403, False, "API User permission"),
            (404, False, "No Gladly organization found at myorg.gladly.com"),
            (500, False, "unexpected status: 500"),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_status_mapping(
        self, mock_session, status_code, expected_valid, expected_message_fragment
    ):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        is_valid, message = validate_credentials("myorg", "agent@x.com", "token")

        assert is_valid is expected_valid
        if expected_message_fragment is None:
            assert message is None
        else:
            assert expected_message_fragment in (message or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_unreachable_host_is_not_reported_as_bad_credentials(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("nodename nor servname provided")

        is_valid, message = validate_credentials("myorg", "agent@x.com", "token")

        assert is_valid is False
        assert "Could not connect to Gladly at myorg.gladly.com" in (message or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_malformed_organization_is_reported_without_a_probe(self, mock_session):
        is_valid, message = validate_credentials("my org", "agent@x.com", "token")

        assert is_valid is False
        assert "Invalid Gladly organization" in (message or "")
        mock_session.assert_not_called()

    @pytest.mark.parametrize(
        "domain, expected_url",
        [
            ("gladly.com", "https://myorg.gladly.com/api/v1/agents"),
            ("gladly.qa", "https://myorg.gladly.qa/api/v1/agents"),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_probe_targets_the_selected_domain(self, mock_session, domain, expected_url):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        assert validate_credentials("myorg", "agent@x.com", "token", domain) == (True, None)
        assert mock_session.return_value.get.call_args.args[0] == expected_url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_domain_outside_the_allowlist_is_never_probed(self, mock_session):
        is_valid, message = validate_credentials("myorg", "agent@x.com", "token", "evil.com")

        assert is_valid is False
        assert "Invalid Gladly domain" in (message or "")
        mock_session.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_session_uses_basic_auth(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("myorg", "agent@x.com", "token")

        assert mock_session.return_value.auth == ("agent@x.com", "token")


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_processes_jobs_oldest_first_and_injects_job_fields(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _jobs_response([_job("j2", "2024-01-02T00:00:00.000Z"), _job("j1", "2024-01-01T00:00:00.000Z")]),
            _jsonl_response([{"id": "c1"}]),  # j1 file (oldest first)
            _jsonl_response([{"id": "c2"}]),  # j2 file
        ]

        manager = _make_manager()
        batches = list(get_rows("myorg", "agent@x.com", "token", "customers", mock.MagicMock(), manager))

        flat = [row for batch in batches for row in batch]
        assert [(r["id"], r["_job_id"], r["_job_updated_at"]) for r in flat] == [
            ("c1", "j1", "2024-01-01T00:00:00.000Z"),
            ("c2", "j2", "2024-01-02T00:00:00.000Z"),
        ]
        # State saved after each fully-processed job.
        assert [call.args[0].last_job_updated_at for call in manager.save_state.call_args_list] == [
            "2024-01-01T00:00:00.000Z",
            "2024-01-02T00:00:00.000Z",
        ]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_skips_jobs_strictly_before_watermark(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _jobs_response([_job("j1", "2024-01-01T00:00:00.000Z"), _job("j2", "2024-01-02T00:00:00.000Z")]),
            _jsonl_response([{"id": "c2"}]),
        ]

        manager = _make_manager()
        batches = list(
            get_rows(
                "myorg",
                "agent@x.com",
                "token",
                "customers",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-01T12:00:00.000Z",
            )
        )

        flat = [row for batch in batches for row in batch]
        assert [r["id"] for r in flat] == ["c2"]
        # Only one file download happened.
        assert mock_session.return_value.get.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_job_sharing_watermark_timestamp_is_reprocessed(self, mock_session):
        # A late-arriving job with the same updatedAt as the watermark must not be
        # dropped — it is re-yielded and merge-on-id dedupes any overlapping rows.
        mock_session.return_value.get.side_effect = [
            _jobs_response([_job("j1", "2024-01-01T00:00:00.000Z"), _job("j2", "2024-01-01T00:00:00.000Z")]),
            _jsonl_response([{"id": "c1"}]),
            _jsonl_response([{"id": "c2"}]),
        ]

        manager = _make_manager()
        batches = list(
            get_rows(
                "myorg",
                "agent@x.com",
                "token",
                "customers",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-01T00:00:00.000Z",
            )
        )

        assert [row["id"] for batch in batches for row in batch] == ["c1", "c2"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_state_supersedes_older_watermark(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _jobs_response(
                [
                    _job("j1", "2024-01-01T00:00:00.000Z"),
                    _job("j2", "2024-01-02T00:00:00.000Z"),
                    _job("j3", "2024-01-03T00:00:00.000Z"),
                ]
            ),
            _jsonl_response([{"id": "c3"}]),
        ]

        # Resume cutoff (between j2 and j3) supersedes the older incremental watermark,
        # so j1 and j2 are skipped and only j3 is processed.
        manager = _make_manager(GladlyResumeConfig(last_job_updated_at="2024-01-02T12:00:00.000Z"))
        batches = list(
            get_rows(
                "myorg",
                "agent@x.com",
                "token",
                "customers",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-01T00:00:00.000Z",
            )
        )

        assert [row["id"] for batch in batches for row in batch] == ["c3"]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_jobs_missing_the_stream_file_are_skipped(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _jobs_response([_job("j1", "2024-01-01T00:00:00.000Z", files=["topics.jsonl"])]),
        ]

        manager = _make_manager()
        assert list(get_rows("myorg", "agent@x.com", "token", "customers", mock.MagicMock(), manager)) == []

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_malformed_jsonl_lines_are_skipped_with_warning(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _jobs_response([_job("j1", "2024-01-01T00:00:00.000Z")]),
            _jsonl_response([{"id": "good"}], junk_lines=["{not json", ""]),
        ]

        manager = _make_manager()
        logger = mock.MagicMock()
        batches = list(get_rows("myorg", "agent@x.com", "token", "customers", logger, manager))

        assert [row["id"] for batch in batches for row in batch] == ["good"]
        logger.warning.assert_called_once()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_large_files_are_chunked(self, mock_session):
        rows = [{"id": str(i)} for i in range(CHUNK_SIZE + 1)]
        mock_session.return_value.get.side_effect = [
            _jobs_response([_job("j1", "2024-01-01T00:00:00.000Z")]),
            _jsonl_response(rows),
        ]

        manager = _make_manager()
        batches = list(get_rows("myorg", "agent@x.com", "token", "customers", mock.MagicMock(), manager))

        assert [len(batch) for batch in batches] == [CHUNK_SIZE, 1]


class TestNormalizeReportColumn:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ("Timestamp", "timestamp"),
            ("Event Type", "event_type"),
            ("Newly Assigned Agent ID", "newly_assigned_agent_id"),
            ("Transferred To Inbox Name", "transferred_to_inbox_name"),
            ("Final IVR Selection", "final_ivr_selection"),
            ("  Fulfilled by Contact ID ", "fulfilled_by_contact_id"),
            ("Conversation ID", "conversation_id"),
            ("Assigned Agent ID - Current", "assigned_agent_id_current"),
            ("Created-to-First Closed Time", "created_to_first_closed_time"),
            ("Billable Resolution (Y/N)", "billable_resolution_y_n"),
            ("  Topics with Hierarchy ", "topics_with_hierarchy"),
        ],
    )
    def test_headers_become_stable_snake_case_columns(self, header, expected):
        assert _normalize_report_column(header) == expected


class TestGetReportRows:
    @freeze_time("2024-03-15T10:00:00Z")
    @mock.patch(f"{_MODULE}.REPORT_REQUEST_INTERVAL_SECONDS", 0)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_windows_start_one_window_behind_watermark_and_rows_are_normalized(self, mock_session):
        header = "Timestamp,Event Type,Conversation ID,Customer ID,Topic Name\n"
        mock_session.return_value.post.side_effect = [
            _csv_response(header + "2024-03-13T09:00:00.000Z,CONVERSATION/CREATED,conv-1,cust-1,\n"),
            _csv_response(header),
            _csv_response(header + '2024-03-15T08:00:00.000Z,CONVERSATION/CLOSED,conv-1,"cust, 1",Returns\n'),
        ]

        manager = _make_manager()
        batches = list(
            get_rows(
                "myorg",
                "agent@x.com",
                "token",
                "conversation_timestamps",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-03-14T05:00:00.000Z",
            )
        )

        # One report request per day, oldest first, starting one full window
        # behind the watermark date.
        calls = mock_session.return_value.post.call_args_list
        assert all(call.args[0] == "https://myorg.gladly.com/api/v1/reports" for call in calls)
        assert [call.kwargs["json"] for call in calls] == [
            {
                "metricSet": "ConversationTimestampsReport",
                "timezone": "UTC",
                "startAt": "2024-03-13",
                "endAt": "2024-03-13",
            },
            {
                "metricSet": "ConversationTimestampsReport",
                "timezone": "UTC",
                "startAt": "2024-03-14",
                "endAt": "2024-03-14",
            },
            {
                "metricSet": "ConversationTimestampsReport",
                "timezone": "UTC",
                "startAt": "2024-03-15",
                "endAt": "2024-03-15",
            },
        ]

        flat = [row for batch in batches for row in batch]
        row_ids = [row.pop("_row_id") for row in flat]
        assert flat == [
            {
                "timestamp": "2024-03-13T09:00:00.000Z",
                "event_type": "CONVERSATION/CREATED",
                "conversation_id": "conv-1",
                "customer_id": "cust-1",
                "topic_name": None,
            },
            {
                "timestamp": "2024-03-15T08:00:00.000Z",
                "event_type": "CONVERSATION/CLOSED",
                "conversation_id": "conv-1",
                "customer_id": "cust, 1",
                "topic_name": "Returns",
            },
        ]
        assert len(set(row_ids)) == 2
        assert all(len(row_id) == 64 for row_id in row_ids)

        # State saved after each fully-processed window, empty ones included.
        assert [call.args[0].last_report_window_end for call in manager.save_state.call_args_list] == [
            "2024-03-13",
            "2024-03-14",
            "2024-03-15",
        ]

    @freeze_time("2024-03-15T10:00:00Z")
    @mock.patch(f"{_MODULE}.REPORT_REQUEST_INTERVAL_SECONDS", 0)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_conversations_report_uses_weekly_windows_and_keeps_the_natural_key(self, mock_session):
        header = (
            "Created At,Conversation ID,Customer ID,Status,"
            "Assigned Agent ID - Current,Inbox ID - Current,First Closed At,Last Closed At\n"
        )
        mock_session.return_value.post.side_effect = [
            _csv_response(
                header
                + "2024-03-04T10:00:00.000Z,conv-1,cust-1,CLOSED,agent-1,inbox-1,"
                + "2024-03-05T00:00:00.000Z,2024-03-05T00:00:00.000Z\n"
            ),
            _csv_response(header + '2024-03-11T10:00:00.000Z,conv-2,"cust, 2",OPEN,,inbox-1,,\n'),
        ]

        manager = _make_manager()
        batches = list(
            get_rows(
                "myorg",
                "agent@x.com",
                "token",
                "conversations",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-03-10T05:00:00.000Z",
            )
        )

        # One window per the endpoint's 7-day report_window_days, oldest first,
        # starting one full window behind the watermark date.
        calls = mock_session.return_value.post.call_args_list
        assert [call.kwargs["json"] for call in calls] == [
            {
                "metricSet": "ConversationExportReport",
                "timezone": "UTC",
                "startAt": "2024-03-03",
                "endAt": "2024-03-09",
            },
            {
                "metricSet": "ConversationExportReport",
                "timezone": "UTC",
                "startAt": "2024-03-10",
                "endAt": "2024-03-15",
            },
        ]

        # Conversations carry a natural key, so no _row_id is injected.
        flat = [row for batch in batches for row in batch]
        assert flat == [
            {
                "created_at": "2024-03-04T10:00:00.000Z",
                "conversation_id": "conv-1",
                "customer_id": "cust-1",
                "status": "CLOSED",
                "assigned_agent_id_current": "agent-1",
                "inbox_id_current": "inbox-1",
                "first_closed_at": "2024-03-05T00:00:00.000Z",
                "last_closed_at": "2024-03-05T00:00:00.000Z",
            },
            {
                "created_at": "2024-03-11T10:00:00.000Z",
                "conversation_id": "conv-2",
                "customer_id": "cust, 2",
                "status": "OPEN",
                "assigned_agent_id_current": None,
                "inbox_id_current": "inbox-1",
                "first_closed_at": None,
                "last_closed_at": None,
            },
        ]
        assert [call.args[0].last_report_window_end for call in manager.save_state.call_args_list] == [
            "2024-03-09",
            "2024-03-15",
        ]

    @freeze_time("2024-03-15T10:00:00Z")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_first_sync_starts_at_the_backfill_horizon(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _csv_response("Timestamp,Contact ID\n2024-01-01T00:00:00.000Z,ct-1\n")
        ]

        manager = _make_manager()
        rows_iterator = get_rows("myorg", "agent@x.com", "token", "contact_timestamps", mock.MagicMock(), manager)

        first_batch = next(rows_iterator)
        assert [(row["timestamp"], row["contact_id"]) for row in first_batch] == [("2024-01-01T00:00:00.000Z", "ct-1")]
        config = GLADLY_ENDPOINTS["contact_timestamps"]
        horizon = date(2024, 3, 15) - timedelta(days=config.report_backfill_days)
        payload = mock_session.return_value.post.call_args.kwargs["json"]
        assert payload["metricSet"] == "ContactTimestampsReport"
        assert payload["startAt"] == horizon.isoformat()
        assert payload["endAt"] == (horizon + timedelta(days=config.report_window_days - 1)).isoformat()

    @freeze_time("2024-03-15T10:00:00Z")
    @mock.patch(f"{_MODULE}.REPORT_REQUEST_INTERVAL_SECONDS", 0)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_state_restarts_at_the_saved_window_and_supersedes_the_watermark(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _csv_response("Timestamp,Conversation ID\n"),
            _csv_response("Timestamp,Conversation ID\n"),
        ]

        # Resume state (mid-March) supersedes the older watermark, and the saved
        # window end itself is re-read rather than skipped.
        manager = _make_manager(GladlyResumeConfig(last_report_window_end="2024-03-14"))
        batches = list(
            get_rows(
                "myorg",
                "agent@x.com",
                "token",
                "conversation_timestamps",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-03-01T00:00:00.000Z",
            )
        )

        assert batches == []
        payloads = [call.kwargs["json"] for call in mock_session.return_value.post.call_args_list]
        assert [(p["startAt"], p["endAt"]) for p in payloads] == [
            ("2024-03-14", "2024-03-14"),
            ("2024-03-15", "2024-03-15"),
        ]
        assert [call.args[0].last_report_window_end for call in manager.save_state.call_args_list] == [
            "2024-03-14",
            "2024-03-15",
        ]

    @freeze_time("2024-03-15T10:00:00Z")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_report_body_yields_no_rows_and_advances(self, mock_session):
        # A window with no data returns an empty body; urllib3 closes the stream on
        # EOF, which used to surface as "ValueError: I/O operation on closed file".
        mock_session.return_value.post.side_effect = [_csv_response("")]

        manager = _make_manager(GladlyResumeConfig(last_report_window_end="2024-03-15"))
        batches = list(get_rows("myorg", "agent@x.com", "token", "conversation_timestamps", mock.MagicMock(), manager))

        assert batches == []
        assert manager.save_state.call_args.args[0].last_report_window_end == "2024-03-15"

    @freeze_time("2024-03-15T10:00:00Z")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_row_ids_are_deterministic_across_syncs(self, mock_session):
        csv_text = "Timestamp,Conversation ID\n2024-03-15T01:00:00.000Z,conv-1\n"

        row_ids = []
        for _ in range(2):
            mock_session.return_value.post.side_effect = [_csv_response(csv_text)]
            manager = _make_manager(GladlyResumeConfig(last_report_window_end="2024-03-15"))
            batches = list(
                get_rows("myorg", "agent@x.com", "token", "conversation_timestamps", mock.MagicMock(), manager)
            )
            row_ids.append(batches[0][0]["_row_id"])

        # Re-read windows must merge onto the previous sync's rows.
        assert row_ids[0] == row_ids[1]

    @freeze_time("2024-03-15T10:00:00Z")
    @mock.patch(f"{_MODULE}.MAX_RETRY_ATTEMPTS", 1)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    @pytest.mark.parametrize(
        "status_code, expected_error",
        [
            (429, GladlyRetryableError),
            (500, GladlyRetryableError),
            (400, requests.HTTPError),
        ],
    )
    def test_report_errors_are_classified(self, mock_session, status_code, expected_error):
        mock_session.return_value.post.return_value = _error_response(status_code)

        manager = _make_manager(GladlyResumeConfig(last_report_window_end="2024-03-15"))
        with pytest.raises(expected_error):
            list(get_rows("myorg", "agent@x.com", "token", "conversation_timestamps", mock.MagicMock(), manager))

        # A failed window is not recorded as processed.
        manager.save_state.assert_not_called()

    @freeze_time("2024-03-15T10:00:00Z")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_large_report_windows_are_chunked(self, mock_session):
        csv_text = (
            "Timestamp,Conversation ID\n"
            + "\n".join(f"2024-03-15T09:00:00.000Z,conv-{i}" for i in range(CHUNK_SIZE + 1))
            + "\n"
        )
        mock_session.return_value.post.side_effect = [_csv_response(csv_text)]

        manager = _make_manager(GladlyResumeConfig(last_report_window_end="2024-03-15"))
        batches = list(get_rows("myorg", "agent@x.com", "token", "conversation_timestamps", mock.MagicMock(), manager))

        assert [len(batch) for batch in batches] == [CHUNK_SIZE, 1]

    @freeze_time("2024-03-15T10:00:00Z")
    @mock.patch(f"{_MODULE}.REPORT_ROW_WARNING_THRESHOLD", 2)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_windows_near_the_report_row_cap_log_a_truncation_warning(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _csv_response(
                "Timestamp,Conversation ID\n2024-03-15T09:00:00.000Z,conv-1\n2024-03-15T10:00:00.000Z,conv-2\n"
            )
        ]

        manager = _make_manager(GladlyResumeConfig(last_report_window_end="2024-03-15"))
        logger = mock.MagicMock()
        list(get_rows("myorg", "agent@x.com", "token", "conversation_timestamps", logger, manager))

        logger.warning.assert_called_once()

    @freeze_time("2024-03-15T10:00:00Z")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_blank_lines_before_the_header_do_not_erase_the_columns(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _csv_response("\r\n\r\nTimestamp,Contact ID\r\n2024-03-15T09:00:00.000Z,ct-1\r\n")
        ]

        manager = _make_manager(GladlyResumeConfig(last_report_window_end="2024-03-15"))
        batches = list(get_rows("myorg", "agent@x.com", "token", "contact_timestamps", mock.MagicMock(), manager))

        flat = [row for batch in batches for row in batch]
        assert [(row["timestamp"], row["contact_id"]) for row in flat] == [("2024-03-15T09:00:00.000Z", "ct-1")]

    @freeze_time("2024-03-15T10:00:00Z")
    @pytest.mark.parametrize(
        "endpoint,body",
        [
            ("contact_timestamps", '[\n{"timestamp":"2024-03-15T09:00:00.000Z"}\n]\n'),
            ("contact_timestamps", "<html>\n<body>\nGladly is unavailable\n</body>\n</html>\n"),
            ("contact_timestamps", "Event Type,Contact ID\nCONTACT/STARTED,ct-1\n"),
            ("conversations", "Conversation ID,Status\nconv-1,OPEN\n"),
        ],
        ids=["json_body", "html_body", "cursor_column_renamed", "primary_key_column_renamed"],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_a_report_missing_the_columns_it_syncs_on_fails_at_the_source(self, mock_session, endpoint, body):
        mock_session.return_value.post.side_effect = [_csv_response(body)]

        manager = _make_manager(GladlyResumeConfig(last_report_window_end="2024-03-15"))
        with pytest.raises(GladlyReportHeaderError, match="missing required columns"):
            list(get_rows("myorg", "agent@x.com", "token", endpoint, mock.MagicMock(), manager))

    @freeze_time("2024-03-15T10:00:00Z")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_a_whitespace_only_body_is_treated_as_an_empty_window(self, mock_session):
        mock_session.return_value.post.side_effect = [_csv_response("\r\n")]

        manager = _make_manager(GladlyResumeConfig(last_report_window_end="2024-03-15"))
        batches = list(get_rows("myorg", "agent@x.com", "token", "contact_timestamps", mock.MagicMock(), manager))

        assert batches == []


class TestGladlySourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = GLADLY_ENDPOINTS[endpoint]
        response = gladly_source("myorg", "agent@x.com", "token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
