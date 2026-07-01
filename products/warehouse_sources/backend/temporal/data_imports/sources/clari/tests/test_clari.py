from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.clari.clari import (
    ClariResumeConfig,
    ClariRetryableError,
    _extract_result_rows,
    _format_timestamp,
    clari_source,
    get_audit_events,
    get_forecast,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.clari.clari"


def _make_manager(resume_state: ClariResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_formats(self, value, expected):
        assert _format_timestamp(value) == expected


class TestExtractResultRows:
    @pytest.mark.parametrize(
        "data, expected",
        [
            ([{"a": 1}, {"b": 2}], [{"a": 1}, {"b": 2}]),
            ([{"a": 1}, "junk"], [{"a": 1}]),
            ({"data": [{"a": 1}]}, [{"a": 1}]),
            ({"rows": [{"a": 1}]}, [{"a": 1}]),
            ({"unknown_key": "x"}, [{"unknown_key": "x"}]),
            ("junk", []),
        ],
    )
    def test_extracts_rows(self, data, expected):
        assert _extract_result_rows(data) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key") is expected


class TestGetAuditEvents:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_follows_next_link_until_absent(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _response({"items": [{"event": "login"}], "nextLink": "https://api.clari.com/v4/audit/events?skip=1000"}),
            _response({"items": [{"event": "logout"}]}),
        ]

        manager = _make_manager()
        batches = list(get_audit_events("key", mock.MagicMock(), manager))

        assert [row["event"] for batch in batches for row in batch] == ["login", "logout"]
        # State saved once, after the first page yielded, pointing at the next page.
        saved = manager.save_state.call_args_list
        assert [call.args[0].next_link for call in saved] == ["https://api.clari.com/v4/audit/events?skip=1000"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_passes_date_from(self, mock_session):
        mock_session.return_value.request.side_effect = [_response({"items": []})]

        list(
            get_audit_events(
                "key",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.request.call_args.args[1]
        assert "dateFrom=2024-01-02T03%3A04%3A05Z" in url
        assert "limit=1000" in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_next_link(self, mock_session):
        mock_session.return_value.request.side_effect = [_response({"items": [{"event": "x"}]})]

        manager = _make_manager(ClariResumeConfig(next_link="https://api.clari.com/v4/audit/events?skip=2000"))
        batches = list(get_audit_events("key", mock.MagicMock(), manager))

        assert len(batches) == 1
        url = mock_session.return_value.request.call_args.args[1]
        assert url == "https://api.clari.com/v4/audit/events?skip=2000"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_accepts_activities_response_key(self, mock_session):
        mock_session.return_value.request.side_effect = [_response({"activities": [{"event": "x"}]})]

        batches = list(get_audit_events("key", mock.MagicMock(), _make_manager()))

        assert batches == [[{"event": "x"}]]


class TestGetForecast:
    @mock.patch(f"{_MODULE}.time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_creates_job_polls_and_downloads_results(self, mock_session, mock_sleep):
        mock_session.return_value.request.side_effect = [
            _response({"jobId": "job-1"}),
            _response({"job": {"id": "job-1", "status": "STARTED"}}),
            _response({"job": {"id": "job-1", "status": "DONE"}}),
            _response([{"Field": "forecast", "Data Value": 100}]),
        ]

        manager = _make_manager()
        batches = list(get_forecast("key", "fc-1", mock.MagicMock(), manager))

        assert batches == [[{"Field": "forecast", "Data Value": 100}]]
        create_call = mock_session.return_value.request.call_args_list[0]
        assert create_call.args == ("POST", "https://api.clari.com/v4/export/forecast/fc-1")
        assert create_call.kwargs["json"] == {"exportFormat": "JSON"}
        # Job id persisted immediately after creation — exports are quota-limited.
        assert manager.save_state.call_args_list[0].args[0].job_id == "job-1"

    @mock.patch(f"{_MODULE}.time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_existing_job_without_creating_a_new_one(self, mock_session, mock_sleep):
        mock_session.return_value.request.side_effect = [
            _response({"job": {"id": "job-9", "status": "DONE"}}),
            _response([{"Field": "quota"}]),
        ]

        manager = _make_manager(ClariResumeConfig(job_id="job-9"))
        batches = list(get_forecast("key", "fc-1", mock.MagicMock(), manager))

        assert batches == [[{"Field": "quota"}]]
        methods = [call.args[0] for call in mock_session.return_value.request.call_args_list]
        assert "POST" not in methods

    @pytest.mark.parametrize("terminal_status", ["FAILED", "CANCELLED", "ABORTED"])
    @mock.patch(f"{_MODULE}.time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_dead_job_raises_and_clears_resume_state(self, mock_session, mock_sleep, terminal_status):
        mock_session.return_value.request.side_effect = [
            _response({"jobId": "job-1"}),
            _response({"job": {"id": "job-1", "status": terminal_status}}),
        ]

        manager = _make_manager()
        with pytest.raises(ValueError, match=terminal_status):
            list(get_forecast("key", "fc-1", mock.MagicMock(), manager))

        assert manager.save_state.call_args_list[-1].args[0].job_id is None

    @mock.patch(f"{_MODULE}.EXPORT_POLL_MAX_ATTEMPTS", 2)
    @mock.patch(f"{_MODULE}.time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_exhausted_poll_budget_raises_retryable(self, mock_session, mock_sleep):
        mock_session.return_value.request.side_effect = [
            _response({"jobId": "job-1"}),
            _response({"job": {"id": "job-1", "status": "STARTED"}}),
            _response({"job": {"id": "job-1", "status": "STARTED"}}),
        ]

        with pytest.raises(ClariRetryableError):
            list(get_forecast("key", "fc-1", mock.MagicMock(), _make_manager()))

    @mock.patch(f"{_MODULE}.time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_missing_job_id_in_create_response_raises(self, mock_session, mock_sleep):
        mock_session.return_value.request.side_effect = [_response({"unexpected": True})]

        with pytest.raises(ValueError, match="no jobId"):
            list(get_forecast("key", "fc-1", mock.MagicMock(), _make_manager()))


class TestClariSourceResponse:
    def test_audit_events_metadata(self):
        response = clari_source("key", "fc-1", "audit_events", mock.MagicMock(), _make_manager())

        assert response.name == "audit_events"
        assert response.primary_keys == ["eventTimestamp", "actorId", "sessionId", "event"]
        assert response.sort_mode == "desc"
        assert response.has_duplicate_primary_keys is True

    def test_forecast_metadata(self):
        response = clari_source("key", "fc-1", "forecast", mock.MagicMock(), _make_manager())

        assert response.name == "forecast"
        assert response.primary_keys is None
