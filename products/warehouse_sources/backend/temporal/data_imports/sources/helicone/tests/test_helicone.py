from datetime import UTC, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.helicone import (
    HeliconeResumeConfig,
    _extract_data,
    _format_timestamp,
    _prompts_rows,
    _requests_rows,
    _sessions_rows,
    _users_rows,
    helicone_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.settings import (
    PROMPTS_ENDPOINT,
    REQUESTS_ENDPOINT,
    SESSIONS_ENDPOINT,
    USERS_ENDPOINT,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.helicone.helicone"


def _response(status: int = 200, json_body: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status
    response.ok = 200 <= status < 300
    response.text = text
    response.json.return_value = json_body
    return response


def _session_returning(responses: list[mock.MagicMock]) -> mock.MagicMock:
    session = mock.MagicMock(spec=requests.Session)
    session.post.side_effect = responses
    return session


def _no_resume_manager() -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


class TestExtractData:
    @parameterized.expand(
        [
            ("wrapped", {"data": [{"id": 1}], "error": None}, [{"id": 1}]),
            ("bare_list", [{"id": 2}], [{"id": 2}]),
            ("null_data", {"data": None, "error": None}, []),
            ("missing_data", {}, []),
        ]
    )
    def test_unwraps_result_shapes(self, _name: str, body: Any, expected: list[dict[str, Any]]) -> None:
        assert _extract_data(body, "https://api.helicone.ai/x") == expected

    def test_error_result_raises(self) -> None:
        with pytest.raises(Exception, match="unauthorized"):
            _extract_data({"data": None, "error": "unauthorized"}, "https://api.helicone.ai/x")


class TestFormatTimestamp:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 3, 4, 2, 58, 14, 123000, tzinfo=UTC), "2026-03-04T02:58:14.123Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("string_passthrough", "2026-03-04T00:00:00Z", "2026-03-04T00:00:00Z"),
            ("none", None, None),
        ]
    )
    def test_formats_cursor_values(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_timestamp(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value.post.return_value = _response(status=status)
            is_valid, message = validate_credentials("key", "us")

        assert is_valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_network_error_is_not_valid(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value.post.side_effect = requests.ConnectionError("boom")
            is_valid, message = validate_credentials("key", "us")

        assert is_valid is False
        assert message is not None

    @parameterized.expand([("us", "https://api.helicone.ai"), ("eu", "https://eu.api.helicone.ai")])
    def test_uses_regional_host(self, region: str, expected_host: str) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value.post.return_value = _response(status=200)
            validate_credentials("key", region)

        called_url = make_session.return_value.post.call_args.args[0]
        assert called_url.startswith(expected_host)


class TestRequestsRows:
    def _rows(self, session: mock.MagicMock, manager: mock.MagicMock, **kwargs: Any) -> list[list[dict[str, Any]]]:
        defaults: dict[str, Any] = {
            "should_use_incremental_field": False,
            "db_incremental_field_last_value": None,
            "incremental_field": None,
        }
        defaults.update(kwargs)
        return list(
            _requests_rows(
                session,
                "https://api.helicone.ai",
                {},
                mock.MagicMock(),
                manager,
                **defaults,
            )
        )

    def test_full_refresh_pages_until_short_page(self) -> None:
        with mock.patch(f"{MODULE}.REQUESTS_PAGE_SIZE", 2):
            session = _session_returning(
                [
                    _response(json_body={"data": [{"request_id": "a"}, {"request_id": "b"}], "error": None}),
                    _response(json_body={"data": [{"request_id": "c"}], "error": None}),
                ]
            )
            manager = _no_resume_manager()

            batches = self._rows(session, manager)

        assert [row["request_id"] for batch in batches for row in batch] == ["a", "b", "c"]

        bodies = [call.kwargs["json"] for call in session.post.call_args_list]
        assert [body["offset"] for body in bodies] == [0, 2]
        assert all(body["filter"] == "all" for body in bodies)
        assert all(body["sort"] == {"created_at": "asc"} for body in bodies)

        # State is saved after each yielded page with the cumulative offset.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert [state.offset for state in saved] == [2, 3]

    def test_incremental_builds_gte_filter_leaf(self) -> None:
        session = _session_returning([_response(json_body={"data": [], "error": None})])
        manager = _no_resume_manager()

        self._rows(
            session,
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
            incremental_field="request_created_at",
        )

        body = session.post.call_args.kwargs["json"]
        # Helicone's filter AST requires one condition per leaf, wrapped in the table name.
        assert body["filter"] == {"request_response_rmt": {"request_created_at": {"gte": "2026-06-01T12:00:00.000Z"}}}

    @freeze_time("2026-06-04 12:00:00")
    def test_first_incremental_sync_bounds_backfill_to_lookback(self) -> None:
        session = _session_returning([_response(json_body={"data": [], "error": None})])
        manager = _no_resume_manager()

        self._rows(session, manager, should_use_incremental_field=True, db_incremental_field_last_value=None)

        body = session.post.call_args.kwargs["json"]
        assert body["filter"] == {"request_response_rmt": {"request_created_at": {"gte": "2025-06-04T12:00:00.000Z"}}}

    def test_resume_state_restores_offset_and_pins_cutoff(self) -> None:
        session = _session_returning([_response(json_body={"data": [], "error": None})])
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = HeliconeResumeConfig(offset=4000, created_after="2026-01-01T00:00:00.000Z")

        self._rows(
            session,
            manager,
            should_use_incremental_field=True,
            # A resumed run must page the window captured at run start, not this newer value.
            db_incremental_field_last_value=datetime(2026, 5, 1, tzinfo=UTC),
        )

        body = session.post.call_args.kwargs["json"]
        assert body["offset"] == 4000
        assert body["filter"] == {"request_response_rmt": {"request_created_at": {"gte": "2026-01-01T00:00:00.000Z"}}}

    def test_api_error_result_raises(self) -> None:
        session = _session_returning([_response(json_body={"data": None, "error": "invalid filter"})])
        manager = _no_resume_manager()

        with pytest.raises(Exception, match="invalid filter"):
            self._rows(session, manager)


class TestSessionsRows:
    @freeze_time("2026-06-04 12:00:00")
    def test_sends_required_params_and_pages_until_short_page(self) -> None:
        with mock.patch(f"{MODULE}.SESSIONS_PAGE_SIZE", 2):
            session = _session_returning(
                [
                    _response(json_body={"data": [{"session_id": "s1"}, {"session_id": "s2"}], "error": None}),
                    _response(json_body={"data": [], "error": None}),
                ]
            )
            manager = _no_resume_manager()

            batches = list(_sessions_rows(session, "https://api.helicone.ai", {}, mock.MagicMock(), manager))

        assert [row["session_id"] for batch in batches for row in batch] == ["s1", "s2"]

        body = session.post.call_args_list[0].kwargs["json"]
        # These fields are required by the API even when unused; dropping one is a 400.
        assert body["search"] == ""
        assert body["timezoneDifference"] == 0
        assert body["filter"] == "all"
        assert body["timeFilter"] == {"startTimeUnixMs": 0, "endTimeUnixMs": 1780574400000}

    def test_resume_pins_time_window_across_attempts(self) -> None:
        session = _session_returning([_response(json_body={"data": [], "error": None})])
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = HeliconeResumeConfig(offset=6, end_time_unix_ms=1700000000000)

        list(_sessions_rows(session, "https://api.helicone.ai", {}, mock.MagicMock(), manager))

        body = session.post.call_args.kwargs["json"]
        assert body["offset"] == 6
        # Recomputing "now" on resume would shift rows across page boundaries.
        assert body["timeFilter"]["endTimeUnixMs"] == 1700000000000


class TestUsersRows:
    def test_yields_rows_from_single_unpaginated_request(self) -> None:
        session = _session_returning([_response(json_body={"data": [{"user_id": "u1", "cost": 1.5}], "error": None})])

        batches = list(_users_rows(session, "https://api.helicone.ai", {}, mock.MagicMock()))

        assert batches == [[{"user_id": "u1", "cost": 1.5}]]
        assert session.post.call_count == 1
        assert "timeFilter" in session.post.call_args.kwargs["json"]

    def test_empty_result_yields_nothing(self) -> None:
        session = _session_returning([_response(json_body={"data": [], "error": None})])
        assert list(_users_rows(session, "https://api.helicone.ai", {}, mock.MagicMock())) == []


class TestPromptsRows:
    def test_pages_with_page_numbers_and_handles_bare_array_response(self) -> None:
        with mock.patch(f"{MODULE}.PROMPTS_PAGE_SIZE", 2):
            session = _session_returning(
                [
                    # The prompts endpoint documents a bare-array response (no {data, error} wrapper).
                    _response(json_body=[{"id": "p1"}, {"id": "p2"}]),
                    _response(json_body=[{"id": "p3"}]),
                ]
            )
            manager = _no_resume_manager()

            batches = list(_prompts_rows(session, "https://api.helicone.ai", {}, mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["p1", "p2", "p3"]

        bodies = [call.kwargs["json"] for call in session.post.call_args_list]
        assert [body["page"] for body in bodies] == [0, 1]
        assert all(body["search"] == "" and body["tagsFilter"] == [] for body in bodies)


class TestHeliconeSourceResponse:
    def test_requests_response_metadata(self) -> None:
        response = helicone_source(
            api_key="key",
            region="us",
            endpoint=REQUESTS_ENDPOINT,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(spec=ResumableSourceManager),
        )

        assert response.name == REQUESTS_ENDPOINT
        assert response.primary_keys == ["request_id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["request_created_at"]
        assert response.partition_format == "week"
        assert response.sort_mode == "asc"

    @parameterized.expand(
        [
            (SESSIONS_ENDPOINT, ["session_id"]),
            (USERS_ENDPOINT, ["user_id"]),
            (PROMPTS_ENDPOINT, ["id"]),
        ]
    )
    def test_full_refresh_response_metadata(self, endpoint: str, expected_primary_keys: list[str]) -> None:
        response = helicone_source(
            api_key="key",
            region="us",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(spec=ResumableSourceManager),
        )

        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestNonRetryableErrorMessages:
    def test_401_http_error_matches_a_non_retryable_key(self) -> None:
        # `get_non_retryable_errors` matches on substrings of str(exc); this guards the keys
        # against drift from the message `requests.raise_for_status` actually produces.
        from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.source import HeliconeSource

        response = requests.Response()
        response.status_code = 401
        response.url = "https://api.helicone.ai/v1/request/query-clickhouse"
        response.reason = "Unauthorized"

        with pytest.raises(requests.HTTPError) as exc_info:
            response.raise_for_status()

        keys = HeliconeSource().get_non_retryable_errors().keys()
        assert any(key in str(exc_info.value) for key in keys)
