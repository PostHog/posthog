from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa import (
    EXPORT_EPOCH_MS,
    EXPORT_WINDOW_MS,
    DixaResumeConfig,
    _to_iso8601_ms,
    _to_ms,
    dixa_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.settings import DIXA_ENDPOINTS, ENDPOINTS


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


@pytest.fixture(autouse=True)
def _no_sleep():
    with mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.time.sleep"):
        yield


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
    def test_to_ms_values(self, value, expected):
        assert _to_ms(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Dixa API token"),
            (403, False, "Invalid Dixa API token"),
            # Transient failures must not be reported as an invalid token.
            (
                429,
                False,
                "Dixa returned an unexpected response (429) while validating the API token. Please try again.",
            ),
            (
                500,
                False,
                "Dixa returned an unexpected response (500) while validating the API token. Please try again.",
            ),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected_valid, expected_message):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("token") == (expected_valid, expected_message)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") == (
            False,
            "Could not reach Dixa to validate the API token. Please try again.",
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_validate_credentials_disables_redirects(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("token")

        assert mock_session.call_args.kwargs["allow_redirects"] is False


class TestGetRowsExport:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_walks_time_windows_from_epoch_on_full_export(self, mock_session, mock_now):
        # Two 30-day windows cover the configured "now".
        mock_now.return_value = EXPORT_EPOCH_MS + EXPORT_WINDOW_MS + 1000
        mock_session.return_value.get.side_effect = [
            _json_response([{"id": "1", "updated_at": EXPORT_EPOCH_MS + 5}]),
            _json_response([{"id": "2", "updated_at": EXPORT_EPOCH_MS + EXPORT_WINDOW_MS + 5}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "conversations", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2"]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        first_query = parse_qs(urlparse(urls[0]).query)
        assert first_query["updated_after"] == [str(EXPORT_EPOCH_MS)]
        assert first_query["updated_before"] == [str(EXPORT_EPOCH_MS + EXPORT_WINDOW_MS)]
        second_query = parse_qs(urlparse(urls[1]).query)
        assert second_query["updated_after"] == [str(EXPORT_EPOCH_MS + EXPORT_WINDOW_MS)]
        # Window end clamps to "now".
        assert second_query["updated_before"] == [str(EXPORT_EPOCH_MS + EXPORT_WINDOW_MS + 1000)]
        # State saved after each window, pointing at the next window start.
        assert [call.args[0].window_start_ms for call in manager.save_state.call_args_list] == [
            EXPORT_EPOCH_MS + EXPORT_WINDOW_MS,
            EXPORT_EPOCH_MS + EXPORT_WINDOW_MS + 1000,
        ]

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

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_incremental_starts_from_watermark(self, mock_session, mock_now):
        watermark = 1700000000000
        mock_now.return_value = watermark + 1000
        mock_session.return_value.get.return_value = _json_response([])

        manager = _make_manager()
        list(
            get_rows(
                "token",
                "conversations",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["updated_after"] == [str(watermark)]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_resumes_from_saved_window(self, mock_session, mock_now):
        resume_start = 1700000000000
        mock_now.return_value = resume_start + 1000
        mock_session.return_value.get.return_value = _json_response([])

        manager = _make_manager(DixaResumeConfig(window_start_ms=resume_start))
        list(get_rows("token", "conversations", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["updated_after"] == [str(resume_start)]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_caught_up_watermark_makes_no_requests(self, mock_session, mock_now):
        now = 1700000000000
        mock_now.return_value = now

        manager = _make_manager()
        batches = list(
            get_rows(
                "token",
                "conversations",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=now,
            )
        )

        assert batches == []
        mock_session.return_value.get.assert_not_called()


class TestGetRowsMain:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_paginates_via_meta_next_and_absolutizes(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _json_response({"data": [{"id": "1"}], "meta": {"next": "/v1/endusers?pageKey=abc"}}),
            _json_response({"data": [{"id": "2"}], "meta": {}}),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "endusers", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2"]
        manager.save_state.assert_called_once()
        saved_url = manager.save_state.call_args.args[0].next_url
        assert saved_url == "https://dev.dixa.io/v1/endusers?pageKey=abc"
        assert mock_session.return_value.get.call_args_list[1].args[0] == saved_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_resumes_from_saved_url(self, mock_session):
        mock_session.return_value.get.return_value = _json_response({"data": [], "meta": {}})

        resume_url = "https://dev.dixa.io/v1/endusers?pageKey=resume"
        manager = _make_manager(DixaResumeConfig(next_url=resume_url))
        list(get_rows("token", "endusers", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_empty_page_with_next_link_stops(self, mock_session):
        mock_session.return_value.get.return_value = _json_response(
            {"data": [], "meta": {"next": "/v1/endusers?pageKey=loop"}}
        )

        manager = _make_manager()
        batches = list(get_rows("token", "endusers", mock.MagicMock(), manager))

        assert batches == []
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_meta_next_to_foreign_host_stops_pagination(self, mock_session):
        # An absolute meta.next pointing off-host must not receive the token.
        mock_session.return_value.get.side_effect = [
            _json_response({"data": [{"id": "1"}], "meta": {"next": "https://attacker.example/collect"}}),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "endusers", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1"]
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_resume_url_on_foreign_host_falls_back_to_default(self, mock_session):
        mock_session.return_value.get.return_value = _json_response({"data": [], "meta": {}})

        manager = _make_manager(DixaResumeConfig(next_url="https://attacker.example/collect"))
        list(get_rows("token", "endusers", mock.MagicMock(), manager))

        # Falls back to the default main-host URL rather than the tampered one.
        requested_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert urlparse(requested_url).netloc == "dev.dixa.io"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_session_disables_redirects(self, mock_session):
        mock_session.return_value.get.return_value = _json_response({"data": [], "meta": {}})

        list(get_rows("token", "endusers", mock.MagicMock(), _make_manager()))

        assert mock_session.call_args.kwargs["allow_redirects"] is False


class TestDixaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = DIXA_ENDPOINTS[endpoint]
        response = dixa_source("token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(DIXA_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"


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
    def test_to_iso8601_ms_values(self, value, expected):
        assert _to_iso8601_ms(value) == expected


class TestActivityLog:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_incremental_sends_from_datetime_and_strips_zone_id(self, mock_session):
        mock_session.return_value.get.return_value = _json_response(
            {"data": [{"id": "a", "activityTimestamp": "2021-12-02T09:00:00.000Z[GMT]"}], "meta": {}}
        )

        batches = list(
            get_rows(
                "token",
                "conversation_activity_log",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2021, 12, 1, 12, 46, 36, 581000, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["fromDatetime"] == ["2021-12-01T12:46:36.581Z"]
        # The trailing zone id would stop the column parsing as a timestamp.
        assert batches[0][0]["activityTimestamp"] == "2021-12-02T09:00:00.000Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_full_refresh_omits_the_watermark(self, mock_session):
        mock_session.return_value.get.return_value = _json_response({"data": [], "meta": {}})

        list(
            get_rows(
                "token",
                "conversation_activity_log",
                mock.MagicMock(),
                _make_manager(),
                db_incremental_field_last_value=datetime(2021, 12, 1, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert urlparse(url).query == ""


class TestFanOutOverConversations:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_injects_parent_id_and_cursor_onto_child_rows(self, mock_session, mock_now):
        mock_now.return_value = EXPORT_EPOCH_MS + 1000
        mock_session.return_value.get.side_effect = [
            _json_response([{"id": 1, "updated_at": 1700000000000}, {"id": 2, "updated_at": 1700000000005}]),
            _json_response({"data": [{"id": "m1", "createdAt": "2021-12-01T12:46:36.581Z[GMT]"}]}),
            _json_response({"data": [{"id": "m2", "createdAt": "2021-12-02T12:46:36.581Z[GMT]"}]}),
        ]

        batches = list(get_rows("token", "conversation_messages", mock.MagicMock(), _make_manager()))
        rows = [row for batch in batches for row in batch]

        assert [(row["id"], row["conversation_id"], row["conversation_updated_at"]) for row in rows] == [
            ("m1", 1, 1700000000000),
            ("m2", 2, 1700000000005),
        ]
        assert rows[0]["createdAt"] == "2021-12-01T12:46:36.581Z"
        child_urls = [call.args[0] for call in mock_session.return_value.get.call_args_list[1:]]
        assert child_urls == [
            "https://dev.dixa.io/v1/conversations/1/messages",
            "https://dev.dixa.io/v1/conversations/2/messages",
        ]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_incremental_bounds_the_parent_walk_to_the_watermark(self, mock_session, mock_now):
        watermark = 1700000000000
        mock_now.return_value = watermark + 1000
        mock_session.return_value.get.return_value = _json_response([])

        list(
            get_rows(
                "token",
                "conversation_ratings",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )
        )

        # Only the export parent walk runs, and it starts at the child watermark.
        assert mock_session.return_value.get.call_count == 1
        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["updated_after"] == [str(watermark)]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_state_saved_once_a_parent_window_is_fully_fanned_out(self, mock_session, mock_now):
        mock_now.return_value = EXPORT_EPOCH_MS + 1000
        mock_session.return_value.get.side_effect = [
            _json_response([{"id": 1, "updated_at": 1700000000000}]),
            _json_response({"data": [{"id": "m1"}]}),
        ]

        manager = _make_manager()
        list(get_rows("token", "conversation_messages", mock.MagicMock(), manager))

        assert [call.args[0].window_start_ms for call in manager.save_state.call_args_list] == [EXPORT_EPOCH_MS + 1000]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_resumes_the_parent_walk_from_saved_window(self, mock_session, mock_now):
        resume_start = 1700000000000
        mock_now.return_value = resume_start + 1000
        mock_session.return_value.get.return_value = _json_response([])

        manager = _make_manager(DixaResumeConfig(window_start_ms=resume_start))
        list(get_rows("token", "conversation_messages", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["updated_after"] == [str(resume_start)]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa._now_ms")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_deleted_conversation_is_skipped_not_fatal(self, mock_session, mock_now):
        mock_now.return_value = EXPORT_EPOCH_MS + 1000
        mock_session.return_value.get.side_effect = [
            _json_response([{"id": 1, "updated_at": 1}, {"id": 2, "updated_at": 2}]),
            _json_response({"message": "The requested resource could not be found"}, status_code=404),
            _json_response({"data": [{"id": "m2"}]}),
        ]

        batches = list(get_rows("token", "conversation_messages", mock.MagicMock(), _make_manager()))

        assert [row["id"] for batch in batches for row in batch] == ["m2"]


class TestFanOutOverTeams:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_team_members_carry_their_team_id(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _json_response({"data": [{"id": "team-a", "name": "Team A"}], "meta": {}}),
            _json_response({"data": [{"id": "agent-1", "email": "a@example.com"}]}),
        ]

        batches = list(get_rows("token", "team_members", mock.MagicMock(), _make_manager()))
        rows = [row for batch in batches for row in batch]

        assert rows == [{"id": "agent-1", "email": "a@example.com", "team_id": "team-a"}]
        assert mock_session.return_value.get.call_args_list[1].args[0] == "https://dev.dixa.io/v1/teams/team-a/agents"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa.make_tracked_session")
    def test_parent_pages_are_walked_before_the_next_page(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _json_response({"data": [{"id": "team-a"}], "meta": {"next": "/v1/teams?pageKey=abc"}}),
            _json_response({"data": [{"id": "agent-1"}]}),
            _json_response({"data": [{"id": "team-b"}], "meta": {}}),
            _json_response({"data": [{"id": "agent-2"}]}),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "team_members", mock.MagicMock(), manager))

        assert [row["team_id"] for batch in batches for row in batch] == ["team-a", "team-b"]
        # The parent cursor is only persisted once its page's children have been yielded.
        assert [call.args[0].next_url for call in manager.save_state.call_args_list] == [
            "https://dev.dixa.io/v1/teams?pageKey=abc"
        ]
