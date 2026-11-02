from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa import (
    EXPORT_EPOCH_MS,
    EXPORT_WINDOW_MS,
    DixaResumeConfig,
    _to_iso8601_ms,
    _to_ms,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.settings import DIXA_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.source import DixaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dixa import DixaSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(DixaSource(), DixaSourceConfig(api_token="token"))


def _make_manager(resume_state: DixaResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _json_response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = status_code < 400
    return resp


class TestToMs:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000000, 1700000000000),
            (1700000000000.9, 1700000000000),
            ("1700000000000", 1700000000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp() * 1000)),
            ("not-a-number", None),
            (True, None),
        ],
    )
    def test_to_ms_values(self, value: Any, expected: int | None) -> None:
        assert _to_ms(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            # Transient failures must not be reported as an invalid token.
            (
                429,
                False,
                "Dixa returned an unexpected response (429) while validating the API token. Please try again.",
            ),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status_code: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("token") == (expected_valid, expected_message)

        assert {request.path for request in network.requests_log} == {"/v1/agents"}
        assert all(request.headers["authorization"] == "Bearer token" for request in network.requests_log)

    def test_validate_credentials_swallows_exceptions(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            assert validate_credentials("token") == (
                False,
                "Could not reach Dixa to validate the API token. Please try again.",
            )

        assert {request.path for request in network.requests_log} == {"/v1/agents"}

    def test_validate_credentials_disables_redirects(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials("token")

        assert network.session_options[0]["allow_redirects"] is False


class TestGetRowsExport:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.time.sleep")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_does_not_sleep_before_first_window(self, mock_session, mock_now, mock_sleep):
        # Two windows: no sleep before the first request, one sleep before the second.
        mock_now.return_value = EXPORT_EPOCH_MS + EXPORT_WINDOW_MS + 1000
        mock_session.return_value.get.side_effect = [
            _json_response([{"id": "1", "updated_at": EXPORT_EPOCH_MS + 5}]),
            _json_response([{"id": "2", "updated_at": EXPORT_EPOCH_MS + EXPORT_WINDOW_MS + 5}]),
        ]

        list(get_rows("token", "conversations", mock.MagicMock(), _make_manager()))

        assert mock_session.return_value.get.call_count == 2
        assert mock_sleep.call_count == 1


class TestGetRowsMain:
    def test_paginates_via_meta_next_and_absolutizes(self) -> None:
        result = _driver().run(
            "endusers",
            [
                ScriptedResponse(json={"data": [{"id": "1"}], "meta": {"next": "/v1/endusers?pageKey=abc"}}),
                ScriptedResponse(json={"data": [{"id": "2"}], "meta": {}}),
            ],
        )

        assert result.raised is None
        assert [item["id"] for item in result.rows] == ["1", "2"]
        saved_url = "https://dev.dixa.io/v1/endusers?pageKey=abc"
        assert result.saved_states == [DixaResumeConfig(next_url=saved_url)]
        assert result.urls[1] == saved_url

    def test_resumes_from_saved_url(self) -> None:
        resume_url = "https://dev.dixa.io/v1/endusers?pageKey=resume"
        result = _driver().run(
            "endusers",
            [ScriptedResponse(json={"data": [], "meta": {}})],
            resume_state=DixaResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert result.urls == [resume_url]

    def test_meta_next_to_foreign_host_stops_pagination(self) -> None:
        # An absolute meta.next pointing off-host must not receive the token.
        result = _driver().run(
            "endusers",
            [ScriptedResponse(json={"data": [{"id": "1"}], "meta": {"next": "https://attacker.example/collect"}})],
        )

        assert result.raised is None
        assert [item["id"] for item in result.rows] == ["1"]
        assert result.paths == ["/v1/endusers"]
        assert result.saved_states == []

    def test_resume_url_on_foreign_host_falls_back_to_default(self) -> None:
        result = _driver().run(
            "endusers",
            [ScriptedResponse(json={"data": [], "meta": {}})],
            resume_state=DixaResumeConfig(next_url="https://attacker.example/collect"),
        )

        # Falls back to the default main-host URL rather than the tampered one.
        assert result.raised is None
        assert result.urls == ["https://dev.dixa.io/v1/endusers"]

    def test_session_disables_redirects(self) -> None:
        result = _driver().run("endusers", [ScriptedResponse(json={"data": [], "meta": {}})])

        assert result.raised is None
        assert result.session_options[0]["allow_redirects"] is False


class TestDixaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = DIXA_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [])
        response = result.response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestToIso8601Ms:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2021, 12, 1, 12, 46, 36, 581000, tzinfo=UTC), "2021-12-01T12:46:36.581Z"),
            # Dixa echoes back its own `...Z[GMT]` serialisation; it must still round-trip.
            ("2021-12-01T12:46:36.581Z[GMT]", "2021-12-01T12:46:36.581Z"),
            ("2021-12-01T12:46:36.581Z", "2021-12-01T12:46:36.581Z"),
            # Naive values are read as UTC rather than dropped.
            (datetime(2021, 12, 1, 12, 46, 36, 581000), "2021-12-01T12:46:36.581Z"),
            (None, None),
            ("not-a-timestamp", None),
            (1700000000000, None),
        ],
    )
    def test_to_iso8601_ms_values(self, value: Any, expected: str | None) -> None:
        assert _to_iso8601_ms(value) == expected


class TestActivityLog:
    def test_incremental_sends_from_datetime_and_strips_zone_id(self) -> None:
        result = _driver().run(
            "conversation_activity_log",
            [
                ScriptedResponse(
                    json={"data": [{"id": "a", "activityTimestamp": "2021-12-02T09:00:00.000Z[GMT]"}], "meta": {}}
                )
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2021, 12, 1, 12, 46, 36, 581000, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("fromDatetime") == "2021-12-01T12:46:36.581Z"
        # The trailing zone id would stop the column parsing as a timestamp.
        assert result.rows[0]["activityTimestamp"] == "2021-12-02T09:00:00.000Z"


class TestFanOutOverConversations:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    def test_injects_parent_id_and_cursor_onto_child_rows(self, mock_now: mock.MagicMock) -> None:
        mock_now.return_value = EXPORT_EPOCH_MS + 1000
        result = _driver().run(
            "conversation_messages",
            [
                ScriptedResponse(json=[{"id": 1, "updated_at": 1700000000000}, {"id": 2, "updated_at": 1700000000005}]),
                ScriptedResponse(json={"data": [{"id": "m1", "createdAt": "2021-12-01T12:46:36.581Z[GMT]"}]}),
                ScriptedResponse(json={"data": [{"id": "m2", "createdAt": "2021-12-02T12:46:36.581Z[GMT]"}]}),
            ],
        )

        assert result.raised is None
        assert [(row["id"], row["conversation_id"], row["conversation_updated_at"]) for row in result.rows] == [
            ("m1", 1, 1700000000000),
            ("m2", 2, 1700000000005),
        ]
        assert result.rows[0]["createdAt"] == "2021-12-01T12:46:36.581Z"
        assert result.urls[1:] == [
            "https://dev.dixa.io/v1/conversations/1/messages",
            "https://dev.dixa.io/v1/conversations/2/messages",
        ]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    def test_incremental_bounds_the_parent_walk_to_the_watermark(self, mock_now: mock.MagicMock) -> None:
        watermark = 1700000000000
        mock_now.return_value = watermark + 1000
        result = _driver().run(
            "conversation_ratings",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        # Only the export parent walk runs, and it starts at the child watermark.
        assert result.raised is None
        assert result.paths == ["/v1/conversation_export"]
        assert result.requests[0].param("updated_after") == str(watermark)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    def test_resumes_the_parent_walk_from_saved_window(self, mock_now: mock.MagicMock) -> None:
        resume_start = 1700000000000
        mock_now.return_value = resume_start + 1000
        result = _driver().run(
            "conversation_messages",
            [ScriptedResponse(json=[])],
            resume_state=DixaResumeConfig(window_start_ms=resume_start),
        )

        assert result.raised is None
        assert result.requests[0].param("updated_after") == str(resume_start)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    def test_deleted_conversation_is_skipped_not_fatal(self, mock_now: mock.MagicMock) -> None:
        mock_now.return_value = EXPORT_EPOCH_MS + 1000
        result = _driver().run(
            "conversation_messages",
            [
                ScriptedResponse(json=[{"id": 1, "updated_at": 1}, {"id": 2, "updated_at": 2}]),
                ScriptedResponse(status=404, json={"message": "The requested resource could not be found"}),
                ScriptedResponse(json={"data": [{"id": "m2"}]}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["m2"]


class TestFanOutOverTeams:
    def test_parent_pages_are_walked_before_the_next_page(self) -> None:
        result = _driver().run(
            "team_members",
            [
                ScriptedResponse(json={"data": [{"id": "team-a"}], "meta": {"next": "/v1/teams?pageKey=abc"}}),
                ScriptedResponse(json={"data": [{"id": "agent-1"}]}),
                ScriptedResponse(json={"data": [{"id": "team-b"}], "meta": {}}),
                ScriptedResponse(json={"data": [{"id": "agent-2"}]}),
            ],
        )

        assert result.raised is None
        assert [row["team_id"] for row in result.rows] == ["team-a", "team-b"]
        assert result.paths == ["/v1/teams", "/v1/teams/team-a/agents", "/v1/teams", "/v1/teams/team-b/agents"]
        # The parent cursor is only persisted once its page's children have been yielded.
        assert result.saved_states == [DixaResumeConfig(next_url="https://dev.dixa.io/v1/teams?pageKey=abc")]
