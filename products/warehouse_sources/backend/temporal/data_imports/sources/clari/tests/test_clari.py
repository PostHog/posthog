from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import validate_incremental_sync
from products.warehouse_sources.backend.temporal.data_imports.sources.clari.clari import (
    ClariResumeConfig,
    ClariRetryableError,
    _extract_result_rows,
    _format_timestamp,
    _to_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clari.settings import (
    ACTIVITY_INITIAL_LOOKBACK_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clari.source import ClariSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clari import ClariSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(ClariSource(), ClariSourceConfig(api_key="key", forecast_id="fc-1"))


def _activity_script() -> list[ScriptedResponse]:
    return [
        ScriptedResponse(json={"jobId": "job-a"}),
        ScriptedResponse(json={"job": {"id": "job-a", "status": "DONE"}}),
        ScriptedResponse(json={"activities": [{"activityId": "act-1", "activityType": "MEETING"}]}),
    ]


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
    def test_formats(self, value: Any, expected: str) -> None:
        assert _format_timestamp(value) == expected


class TestExtractResultRows:
    @pytest.mark.parametrize(
        "data, expected",
        [
            ([{"a": 1}, {"b": 2}], [{"a": 1}, {"b": 2}]),
            ([{"a": 1}, "junk"], [{"a": 1}]),
            ({"data": [{"a": 1}]}, [{"a": 1}]),
            ({"rows": [{"a": 1}]}, [{"a": 1}]),
            ({"activities": [{"a": 1}]}, [{"a": 1}]),
            ({"activities": []}, []),
            ({"unknown_key": "x"}, [{"unknown_key": "x"}]),
            ("junk", []),
        ],
    )
    def test_extracts_rows(self, data: Any, expected: list[dict[str, Any]]) -> None:
        assert _extract_result_rows(data) == expected


class TestToDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (1702906200000, datetime(2023, 12, 18, 13, 30, tzinfo=UTC)),
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)),
            (datetime(2024, 1, 2, 3, 4, 5), datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)),
            (date(2024, 1, 2), datetime(2024, 1, 2, tzinfo=UTC)),
            ("2024-01-02T03:04:05Z", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)),
            ("not a date", None),
            (None, None),
        ],
    )
    def test_converts_watermarks(self, value: Any, expected: datetime | None) -> None:
        assert _to_datetime(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("key") is expected

        assert [request.path for request in network.requests_log] == ["/v4/audit/events"]
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["apikey"] == "key"


class TestGetAuditEvents:
    def test_follows_next_link_until_absent(self) -> None:
        next_link = "https://api.clari.com/v4/audit/events?skip=1000"
        result = _driver().run(
            "audit_events",
            [
                ScriptedResponse(json={"items": [{"event": "login"}], "nextLink": next_link}),
                ScriptedResponse(json={"items": [{"event": "logout"}]}),
            ],
        )

        assert result.raised is None
        assert [row["event"] for row in result.rows] == ["login", "logout"]
        assert result.paths == ["/v4/audit/events", "/v4/audit/events"]
        # State saved once, after the first page yielded, pointing at the next page.
        assert result.saved_states == [ClariResumeConfig(next_link=next_link)]

    def test_incremental_passes_date_from(self) -> None:
        result = _driver().run(
            "audit_events",
            [ScriptedResponse(json={"items": []})],
            incremental_field="eventTimestamp",
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("dateFrom") == ["2024-01-02T03:04:05Z"]
        assert result.params("limit") == ["1000"]

    def test_resumes_from_saved_next_link(self) -> None:
        result = _driver().run(
            "audit_events",
            [ScriptedResponse(json={"items": [{"event": "x"}]})],
            resume_state=ClariResumeConfig(next_link="https://api.clari.com/v4/audit/events?skip=2000"),
        )

        assert result.raised is None
        assert result.items == [[{"event": "x"}]]
        assert result.urls == ["https://api.clari.com/v4/audit/events?skip=2000"]

    def test_accepts_activities_response_key(self) -> None:
        result = _driver().run("audit_events", [ScriptedResponse(json={"activities": [{"event": "x"}]})])

        assert result.raised is None
        assert result.items == [[{"event": "x"}]]


class TestGetForecast:
    def test_creates_job_polls_and_downloads_results(self) -> None:
        result = _driver().run(
            "forecast",
            [
                ScriptedResponse(json={"jobId": "job-1"}),
                ScriptedResponse(json={"job": {"id": "job-1", "status": "STARTED"}}),
                ScriptedResponse(json={"job": {"id": "job-1", "status": "DONE"}}),
                ScriptedResponse(json=[{"Field": "forecast", "Data Value": 100}]),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"Field": "forecast", "Data Value": 100}]]
        assert [(request.method, request.path) for request in result.requests] == [
            ("POST", "/v4/export/forecast/fc-1"),
            ("GET", "/v4/export/jobs/job-1"),
            ("GET", "/v4/export/jobs/job-1"),
            ("GET", "/v4/export/jobs/job-1/results"),
        ]
        assert result.requests[0].json() == {"exportFormat": "JSON"}
        # Job id persisted immediately after creation — exports are quota-limited.
        assert result.saved_states[0] == ClariResumeConfig(job_id="job-1")
        assert result.final_state == ClariResumeConfig(job_id="job-1")

    def test_resumes_existing_job_without_creating_a_new_one(self) -> None:
        result = _driver().run(
            "forecast",
            [
                ScriptedResponse(json={"job": {"id": "job-9", "status": "DONE"}}),
                ScriptedResponse(json=[{"Field": "quota"}]),
            ],
            resume_state=ClariResumeConfig(job_id="job-9"),
        )

        assert result.raised is None
        assert result.items == [[{"Field": "quota"}]]
        assert [(request.method, request.path) for request in result.requests] == [
            ("GET", "/v4/export/jobs/job-9"),
            ("GET", "/v4/export/jobs/job-9/results"),
        ]

    @pytest.mark.parametrize("terminal_status", ["FAILED", "CANCELLED", "ABORTED"])
    def test_dead_job_raises_and_clears_resume_state(self, terminal_status: str) -> None:
        result = _driver().run(
            "forecast",
            [
                ScriptedResponse(json={"jobId": "job-1"}),
                ScriptedResponse(json={"job": {"id": "job-1", "status": terminal_status}}),
            ],
        )

        assert isinstance(result.raised, ValueError)
        assert terminal_status in str(result.raised)
        assert result.saved_states[-1] == ClariResumeConfig(job_id=None)
        assert result.final_state == ClariResumeConfig(job_id=None)

    def test_exhausted_poll_budget_raises_retryable(self) -> None:
        result = _driver().run(
            "forecast",
            [ScriptedResponse(json={"jobId": "job-1"})]
            + [ScriptedResponse(json={"job": {"id": "job-1", "status": "STARTED"}})] * 60,
        )

        assert isinstance(result.raised, ClariRetryableError)
        assert result.paths.count("/v4/export/jobs/job-1") == 60

    def test_missing_job_id_in_create_response_raises(self) -> None:
        result = _driver().run("forecast", [ScriptedResponse(json={"unexpected": True})])

        assert isinstance(result.raised, ValueError)
        assert "no jobId" in str(result.raised)


class TestGetActivity:
    def test_exports_every_activity_type_and_reads_the_activities_key(self) -> None:
        result = _driver().run("activity", _activity_script())

        assert result.raised is None
        assert result.items == [[{"activityId": "act-1", "activityType": "MEETING"}]]
        assert (result.requests[0].method, result.requests[0].path) == ("POST", "/v4/export/activity")
        assert result.requests[0].json()["activityTypes"] == [
            "MEETING",
            "EMAIL_SENT",
            "EMAIL_RECEIVED",
            "ATTACHMENT_SENT",
            "ATTACHMENT_RECEIVED",
        ]

    def test_full_refresh_exports_the_initial_lookback_window(self) -> None:
        result = _driver().run("activity", _activity_script(), db_incremental_field_last_value=123)

        assert result.raised is None
        body = result.requests[0].json()
        start = datetime.strptime(body["startDate"], "%Y-%m-%dT%H:%M:%SZ")
        end = datetime.strptime(body["endDate"], "%Y-%m-%dT%H:%M:%SZ")
        assert (end - start).days == ACTIVITY_INITIAL_LOOKBACK_DAYS

    def test_incremental_starts_from_the_epoch_millisecond_watermark(self) -> None:
        result = _driver().run(
            "activity",
            _activity_script(),
            incremental_field="date",
            db_incremental_field_last_value=1702906200000,
        )

        assert result.raised is None
        assert result.requests[0].json()["startDate"] == "2023-12-18T13:30:00Z"

    def test_first_incremental_sync_falls_back_to_the_lookback_window(self) -> None:
        result = _driver().run("activity", _activity_script(), incremental_field="date")

        assert result.raised is None
        body = result.requests[0].json()
        start = datetime.strptime(body["startDate"], "%Y-%m-%dT%H:%M:%SZ")
        end = datetime.strptime(body["endDate"], "%Y-%m-%dT%H:%M:%SZ")
        assert (end - start).days == ACTIVITY_INITIAL_LOOKBACK_DAYS


class TestClariSourceResponse:
    def test_audit_events_metadata(self) -> None:
        result = _driver().run("audit_events", [ScriptedResponse(json={"items": []})])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == "audit_events"
        assert response.primary_keys == ["eventTimestamp", "actorId", "sessionId", "event"]
        assert response.sort_mode == "desc"
        # The composite key can collide, but that's expected for this data and must not block
        # incremental syncing - regression test for the schema-wide incremental sync outage this
        # caused when has_duplicate_primary_keys was set unconditionally.
        assert not response.has_duplicate_primary_keys
        validate_incremental_sync(True, response)

    def test_activity_metadata(self) -> None:
        result = _driver().run("activity", _activity_script())

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == "activity"
        assert response.primary_keys == ["activityId"]
        assert response.sort_mode == "desc"
        validate_incremental_sync(True, response)

    def test_forecast_metadata(self) -> None:
        result = _driver().run(
            "forecast",
            [
                ScriptedResponse(json={"jobId": "job-1"}),
                ScriptedResponse(json={"status": "DONE"}),
                ScriptedResponse(json=[]),
            ],
        )

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == "forecast"
        assert response.primary_keys is None
