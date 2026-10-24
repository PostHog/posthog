import io
import json
from typing import Any

import pytest
import time_machine
from unittest import mock

import urllib3
import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gladly import GladlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.gladly import (
    CHUNK_SIZE,
    GladlyReportHeaderError,
    GladlyReportNotAvailableForAccountError,
    GladlyReportUnavailableError,
    GladlyResumeConfig,
    GladlyRetryableError,
    _clean_domain,
    _clean_organization,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.settings import ENDPOINTS, GLADLY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source import GladlySource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gladly.gladly"


def _make_manager(resume_state: GladlyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _driver() -> SourceDriver:
    return SourceDriver(
        GladlySource(), GladlySourceConfig(organization="myorg", agent_email="agent@x.com", api_token="token")
    )


def _jsonl_response(rows: list[dict[str, Any]], junk_lines: list[str] | None = None) -> ScriptedResponse:
    lines = [json.dumps(row) for row in rows] + (junk_lines or [])
    return ScriptedResponse(body=("\n".join(lines) + "\n").encode())


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


def _csv(text: str) -> ScriptedResponse:
    return ScriptedResponse(body=text.encode())


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


class TestCleanDomain:
    @pytest.mark.parametrize("value", ["", "evil.com", "gladly.com.evil.com", "gladly.qa.evil.com", "gladly.dev"])
    def test_domains_outside_the_allowlist_raise(self, value):
        with pytest.raises(ValueError):
            _clean_domain(value)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message_fragment",
        [
            (404, False, "No Gladly organization found at myorg.gladly.com"),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status_code: int, expected_valid: bool, expected_message_fragment: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, message = validate_credentials("myorg", "agent@x.com", "token")

        assert is_valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/api/v1/agents"}
        if expected_message_fragment is None:
            assert message is None
        else:
            assert expected_message_fragment in (message or "")

    def test_unreachable_host_is_not_reported_as_bad_credentials(self) -> None:
        with scripted_network(always(ConnectionError("nodename nor servname provided"))) as network:
            is_valid, message = validate_credentials("myorg", "agent@x.com", "token")

        assert is_valid is False
        assert "Could not connect to Gladly at myorg.gladly.com" in (message or "")
        assert {request.path for request in network.requests_log} == {"/api/v1/agents"}

    def test_malformed_organization_is_reported_without_a_probe(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("my org", "agent@x.com", "token")

        assert is_valid is False
        assert "Invalid Gladly organization" in (message or "")
        assert network.requests_log == []
        assert network.session_options == []

    def test_domain_outside_the_allowlist_is_never_probed(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("myorg", "agent@x.com", "token", "evil.com")

        assert is_valid is False
        assert "Invalid Gladly domain" in (message or "")
        assert network.requests_log == []
        assert network.session_options == []


class TestGetRows:
    def test_processes_jobs_oldest_first_and_injects_job_fields(self) -> None:
        result = _driver().run(
            "customers",
            [
                ScriptedResponse(json=[_job("j2", "2024-01-02T00:00:00.000Z"), _job("j1", "2024-01-01T00:00:00.000Z")]),
                _jsonl_response([{"id": "c1"}]),  # j1 file (oldest first)
                _jsonl_response([{"id": "c2"}]),  # j2 file
            ],
        )

        assert result.raised is None
        assert [(r["id"], r["_job_id"], r["_job_updated_at"]) for r in result.rows] == [
            ("c1", "j1", "2024-01-01T00:00:00.000Z"),
            ("c2", "j2", "2024-01-02T00:00:00.000Z"),
        ]
        # State saved after each fully-processed job.
        assert [state.last_job_updated_at for state in result.saved_states] == [
            "2024-01-01T00:00:00.000Z",
            "2024-01-02T00:00:00.000Z",
        ]

    def test_resume_state_supersedes_older_watermark(self) -> None:
        # Resume cutoff (between j2 and j3) supersedes the older incremental watermark,
        # so j1 and j2 are skipped and only j3 is processed.
        result = _driver().run(
            "customers",
            [
                ScriptedResponse(
                    json=[
                        _job("j1", "2024-01-01T00:00:00.000Z"),
                        _job("j2", "2024-01-02T00:00:00.000Z"),
                        _job("j3", "2024-01-03T00:00:00.000Z"),
                    ]
                ),
                _jsonl_response([{"id": "c3"}]),
            ],
            resume_state=GladlyResumeConfig(last_job_updated_at="2024-01-02T12:00:00.000Z"),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00.000Z",
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c3"]
        assert result.paths == ["/api/v1/export/jobs", "/api/v1/export/jobs/j3/files/customers.jsonl"]

    def test_jobs_missing_the_stream_file_are_skipped(self) -> None:
        result = _driver().run(
            "customers", [ScriptedResponse(json=[_job("j1", "2024-01-01T00:00:00.000Z", files=["topics.jsonl"])])]
        )

        assert result.raised is None
        assert result.items == []
        assert result.paths == ["/api/v1/export/jobs"]

    def test_malformed_jsonl_lines_are_skipped_with_warning(self) -> None:
        logger = mock.MagicMock()
        result = _driver().run(
            "customers",
            [
                ScriptedResponse(json=[_job("j1", "2024-01-01T00:00:00.000Z")]),
                _jsonl_response([{"id": "good"}], junk_lines=["{not json", ""]),
            ],
            logger=logger,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["good"]
        logger.warning.assert_called_once()

    def test_large_files_are_chunked(self) -> None:
        rows = [{"id": str(i)} for i in range(CHUNK_SIZE + 1)]
        result = _driver().run(
            "customers",
            [ScriptedResponse(json=[_job("j1", "2024-01-01T00:00:00.000Z")]), _jsonl_response(rows)],
        )

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [CHUNK_SIZE, 1]

    @pytest.mark.parametrize(
        "endpoint, path, body",
        [
            ("teams", "teams", [{"id": "team-1", "name": "Tier 1", "agentIds": ["agent-1"]}]),
            ("inboxes", "inboxes", [{"id": "inbox-1", "name": "Support", "disabled": False}]),
        ],
    )
    def test_lookup_streams_read_the_whole_list_and_ignore_the_watermark(self, endpoint, path, body) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=body)],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-03-14T05:00:00.000Z",
        )

        assert result.raised is None
        assert result.items == [body]
        assert result.urls == [f"https://myorg.gladly.com/api/v1/{path}"]
        assert result.saved_states == []


class TestGetEventRows:
    @time_machine.travel("2024-03-15T10:00:00Z", tick=False)
    def test_walks_hourly_windows_from_one_window_behind_the_watermark(self) -> None:
        result = _driver().run(
            "events",
            [
                _jsonl_response(
                    [{"id": "e1", "type": "AGENT_STATUS/LOGGED_IN", "timestamp": "2024-03-15T07:45:00.000Z"}],
                    junk_lines=["{not json"],
                ),
                _jsonl_response([]),
                _jsonl_response([{"id": "e2", "type": "TASK/CREATED", "timestamp": "2024-03-15T09:40:00.000Z"}]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-03-15T08:30:00.000Z",
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/events"] * 3
        assert [(query["startAt"], query["endAt"]) for query in result.queries] == [
            (("2024-03-15T07:30:00.000Z",), ("2024-03-15T08:30:00.000Z",)),
            (("2024-03-15T08:30:00.000Z",), ("2024-03-15T09:30:00.000Z",)),
            (("2024-03-15T09:30:00.000Z",), ("2024-03-15T10:00:00.000Z",)),
        ]
        assert set(result.queries[0]["entities"]) == set(GLADLY_ENDPOINTS["events"].event_entities)
        assert [row["id"] for row in result.rows] == ["e1", "e2"]
        # The empty window still advances the cursor, so a resumed run skips it.
        assert [state.last_event_window_end for state in result.committed_states] == [
            "2024-03-15T08:30:00.000Z",
            "2024-03-15T09:30:00.000Z",
            "2024-03-15T10:00:00.000Z",
        ]

    @time_machine.travel("2024-03-15T10:00:00Z", tick=False)
    @pytest.mark.parametrize(
        "watermark, resume_state, expected_first_start, expected_windows, expect_warning",
        [
            (None, None, "2024-03-14T10:05:00.000Z", 24, False),
            ("2024-03-10T00:00:00.000Z", None, "2024-03-14T10:05:00.000Z", 24, True),
            ("not a timestamp", None, "2024-03-14T10:05:00.000Z", 24, True),
            (
                "2024-03-15T06:00:00.000Z",
                GladlyResumeConfig(last_event_window_end="2024-03-15T08:00:00.000Z"),
                "2024-03-15T08:00:00.000Z",
                2,
                False,
            ),
            (
                "2024-03-15T10:00:00.000Z",
                GladlyResumeConfig(last_event_window_end="2024-03-15T10:00:00.000Z"),
                None,
                0,
                False,
            ),
        ],
        ids=[
            "first_sync_reads_the_retained_24_hours",
            "stale_watermark_is_clamped_to_the_retention_limit",
            "unparseable_watermark_reads_the_retained_24_hours",
            "resume_state_supersedes_an_older_watermark",
            "caught_up_run_makes_no_request",
        ],
    )
    def test_start_of_the_first_window(
        self, watermark, resume_state, expected_first_start, expected_windows, expect_warning
    ) -> None:
        logger = mock.MagicMock()
        result = _driver().run(
            "events",
            always(_jsonl_response([])),
            resume_state=resume_state,
            should_use_incremental_field=watermark is not None,
            db_incremental_field_last_value=watermark,
            logger=logger,
        )

        assert result.raised is None
        assert len(result.requests) == expected_windows
        if expected_first_start is not None:
            assert result.params("startAt")[0] == expected_first_start
            assert result.params("endAt")[-1] == "2024-03-15T10:00:00.000Z"
        assert logger.warning.called is expect_warning


class TestGetVoiceTranscriptRows:
    def test_fetches_transcripts_for_voice_items_only_and_skips_missing_ones(self) -> None:
        def item(item_id: str, item_type: str) -> dict[str, Any]:
            return {"id": item_id, "conversationId": f"conv-{item_id}", "content": {"type": item_type}}

        files = ["conversation_items.jsonl"]
        result = _driver().run(
            "voice_transcripts",
            [
                ScriptedResponse(
                    json=[
                        _job("j2", "2024-01-02T00:00:00.000Z", files=files),
                        _job("j1", "2024-01-01T00:00:00.000Z", files=files),
                        _job("j0", "2024-01-01T12:00:00.000Z", files=["customers.jsonl"]),
                    ]
                ),
                _jsonl_response(
                    [item("chat-1", "CHAT_MESSAGE"), item("call-1", "PHONE_CALL"), item("vm-1", "VOICEMAIL")],
                    junk_lines=["{not json"],
                ),
                ScriptedResponse(json={"paragraphs": [{"transcript": "Hello", "speaker": 0}], "language": "en"}),
                ScriptedResponse(status=404),
                _jsonl_response([item("vm-2", "VOICEMAIL")]),
                ScriptedResponse(status=404),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/api/v1/export/jobs",
            "/api/v1/export/jobs/j1/files/conversation_items.jsonl",
            "/api/v1/conversation-items/call-1/voice-transcript",
            "/api/v1/conversation-items/vm-1/voice-transcript",
            "/api/v1/export/jobs/j2/files/conversation_items.jsonl",
            "/api/v1/conversation-items/vm-2/voice-transcript",
        ]
        assert result.rows == [
            {
                "paragraphs": [{"transcript": "Hello", "speaker": 0}],
                "language": "en",
                "conversation_item_id": "call-1",
                "conversation_id": "conv-call-1",
                "item_type": "PHONE_CALL",
                "_job_id": "j1",
                "_job_updated_at": "2024-01-01T00:00:00.000Z",
            }
        ]
        # A job whose voice items have no transcript still advances the cursor.
        assert [state.last_job_updated_at for state in result.committed_states] == [
            "2024-01-01T00:00:00.000Z",
            "2024-01-02T00:00:00.000Z",
        ]

    @mock.patch(f"{_MODULE}.MAX_RETRY_ATTEMPTS", 1)
    @pytest.mark.parametrize(
        "status_code, expected_error",
        [(429, GladlyRetryableError), (500, GladlyRetryableError), (403, requests.HTTPError)],
    )
    def test_transcript_errors_other_than_not_found_fail_the_job(self, status_code, expected_error) -> None:
        answers = {
            "/api/v1/export/jobs": ScriptedResponse(
                json=[_job("j1", "2024-01-01T00:00:00.000Z", files=["conversation_items.jsonl"])]
            ),
            "/api/v1/export/jobs/j1/files/conversation_items.jsonl": _jsonl_response(
                [{"id": "call-1", "content": {"type": "PHONE_CALL"}}]
            ),
        }
        # The transport retries a 429 and a 5xx, so the transcript answers every attempt.
        result = _driver().run(
            "voice_transcripts", lambda request: answers.get(request.path, ScriptedResponse(status=status_code))
        )

        assert isinstance(result.raised, expected_error)
        assert result.saved_states == []


class TestGetReportRows:
    @time_machine.travel("2024-03-15T10:00:00Z", tick=False)
    def test_work_session_report_uses_a_time_range_and_keys_rows_on_contact_and_agent(self) -> None:
        header = (
            "Timezone Filter,id,contact_session_id,contact_session_created_at,agent_id,"
            "contact_session_ended_at,work_session_handle_time_sec\n"
        )
        result = _driver().run(
            "work_session_events",
            [
                _csv(
                    header
                    + "UTC,,cs-open,2024-03-14T08:00:00.000Z,,,\n"
                    + "UTC,ws-2,cs-2,2024-03-14T08:30:00.000Z,,2024-03-14T08:45:00.000Z,\n"
                    + "UTC,,cs-1,2024-03-14T09:00:00.000Z,agent-1,2024-03-14T23:00:00.000Z,100\n"
                ),
                _csv(header + "UTC,ws-1,cs-1,2024-03-14T09:00:00.000Z,agent-1,2024-03-14T23:00:00.000Z,120\n"),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-03-15T00:30:00.000Z",
        )

        assert result.raised is None
        assert [request.json() for request in result.requests] == [
            {
                "metricSet": "WorkSessionEventsReportV4",
                "timezone": "UTC",
                "startAtTime": "2024-03-14T00:00Z",
                "endAtTime": "2024-03-14T23:59Z",
            },
            {
                "metricSet": "WorkSessionEventsReportV4",
                "timezone": "UTC",
                "startAtTime": "2024-03-15T00:00Z",
                "endAtTime": "2024-03-15T23:59Z",
            },
        ]

        # The open contact has no agent yet, so its key would never match the row it
        # gets once it ends. It is skipped, while the ended unhandled contact stays.
        unhandled, first_read, restated = result.rows
        assert unhandled["contact_session_id"] == "cs-2"
        assert unhandled["agent_id"] is None
        # A restated session must merge onto its earlier row even though its id
        # and handle time changed.
        assert first_read["_row_id"] == restated["_row_id"]
        assert unhandled["_row_id"] != first_read["_row_id"]
        assert restated["work_session_handle_time_sec"] == "120"

    @time_machine.travel("2024-03-15T10:00:00Z", tick=False)
    @mock.patch(f"{_MODULE}.MAX_RETRY_ATTEMPTS", 1)
    @pytest.mark.parametrize(
        "status_code, expected_error",
        [
            (429, GladlyRetryableError),
            (500, GladlyRetryableError),
            (400, requests.HTTPError),
        ],
    )
    def test_report_errors_are_classified(self, status_code: int, expected_error: type[Exception]) -> None:
        result = _driver().run(
            "conversation_timestamps",
            always(ScriptedResponse(status=status_code, body=b"error body")),
            resume_state=GladlyResumeConfig(last_report_window_end="2024-03-15"),
        )

        assert isinstance(result.raised, expected_error)
        # A failed window is not recorded as processed.
        assert result.saved_states == []

    @time_machine.travel("2024-03-15T10:00:00Z", tick=False)
    def test_large_report_windows_are_chunked(self) -> None:
        csv_text = (
            "Timestamp,Conversation ID\n"
            + "\n".join(f"2024-03-15T09:00:00.000Z,conv-{i}" for i in range(CHUNK_SIZE + 1))
            + "\n"
        )
        result = _driver().run(
            "conversation_timestamps",
            [_csv(csv_text)],
            resume_state=GladlyResumeConfig(last_report_window_end="2024-03-15"),
        )

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [CHUNK_SIZE, 1]

    @time_machine.travel("2024-03-15T10:00:00Z", tick=False)
    @mock.patch(f"{_MODULE}.REPORT_ROW_WARNING_THRESHOLD", 2)
    def test_windows_near_the_report_row_cap_log_a_truncation_warning(self) -> None:
        logger = mock.MagicMock()
        result = _driver().run(
            "conversation_timestamps",
            [_csv("Timestamp,Conversation ID\n2024-03-15T09:00:00.000Z,conv-1\n2024-03-15T10:00:00.000Z,conv-2\n")],
            resume_state=GladlyResumeConfig(last_report_window_end="2024-03-15"),
            logger=logger,
        )

        assert result.raised is None
        logger.warning.assert_called_once()

    @time_machine.travel("2024-03-15T10:00:00Z", tick=False)
    @pytest.mark.parametrize(
        "endpoint,body",
        [
            ("contact_timestamps", "Event Type,Contact ID\nCONTACT/STARTED,ct-1\n"),
            ("conversations", "Conversation ID,Status\nconv-1,OPEN\n"),
        ],
        ids=["cursor_column_renamed", "primary_key_column_renamed"],
    )
    def test_a_report_missing_the_columns_it_syncs_on_fails_at_the_source(self, endpoint, body) -> None:
        result = _driver().run(
            endpoint,
            [_csv(body)],
            resume_state=GladlyResumeConfig(last_report_window_end="2024-03-15"),
        )

        assert isinstance(result.raised, GladlyReportHeaderError)
        assert "missing required columns" in str(result.raised)
        assert result.paths == ["/api/v1/reports"]

    @time_machine.travel("2024-03-15T10:00:00Z", tick=False)
    @pytest.mark.parametrize(
        "body",
        [
            "Unexpected error occurred",
            '[\n{"timestamp":"2024-03-15T09:00:00.000Z"}\n]\n',
            "<html>\n<body>\nGladly is unavailable\n</body>\n</html>\n",
        ],
        ids=["plain_text_error", "json_body", "html_body"],
    )
    def test_an_error_body_in_place_of_the_report_is_retried_and_stays_retryable(self, body: str) -> None:
        result = _driver().run(
            "contact_timestamps",
            [_csv(body) for _ in range(5)],
            resume_state=GladlyResumeConfig(last_report_window_end="2024-03-15"),
        )

        assert isinstance(result.raised, GladlyReportUnavailableError)
        assert "Gladly returned no report" in str(result.raised)
        assert result.paths == ["/api/v1/reports"] * 5
        assert result.saved_states == []

    @time_machine.travel("2024-03-15T10:00:00Z", tick=False)
    @pytest.mark.parametrize(
        "schema_has_ever_synced, expected_error",
        [
            (False, GladlyReportNotAvailableForAccountError),
            (True, GladlyReportUnavailableError),
        ],
        ids=["never_served", "reset_run_after_a_successful_sync"],
    )
    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_an_error_body_stops_the_sync_only_when_gladly_never_served_the_report(
        self, mock_session, _sleep, schema_has_ever_synced, expected_error
    ):
        mock_session.return_value.post.side_effect = [_csv_response("Unexpected error occurred") for _ in range(5)]

        manager = _make_manager()
        with pytest.raises(expected_error):
            list(
                get_rows(
                    "myorg",
                    "agent@x.com",
                    "token",
                    "contact_timestamps",
                    mock.MagicMock(),
                    manager,
                    schema_has_ever_synced=schema_has_ever_synced,
                )
            )

        manager.save_state.assert_not_called()

    @time_machine.travel("2024-03-15T10:00:00Z", tick=False)
    def test_an_error_body_after_a_window_landed_stays_retryable(self) -> None:
        result = _driver().run(
            "contact_timestamps",
            [
                _csv("Timestamp,Contact ID\n2024-03-14T09:00:00.000Z,ct-1\n"),
                *[_csv("Unexpected error occurred") for _ in range(5)],
            ],
        )

        assert isinstance(result.raised, GladlyReportUnavailableError)
        assert "Gladly returned no report" in str(result.raised)
        assert [row["contact_id"] for row in result.rows] == ["ct-1"]
        assert result.paths == ["/api/v1/reports"] * 6

    @time_machine.travel("2024-03-15T10:00:00Z", tick=False)
    def test_a_whitespace_only_body_is_treated_as_an_empty_window(self) -> None:
        result = _driver().run(
            "contact_timestamps",
            [_csv("\r\n")],
            resume_state=GladlyResumeConfig(last_report_window_end="2024-03-15"),
        )

        assert result.raised is None
        assert result.items == []


class TestGladlySourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = GLADLY_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [])
        response = result.response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
