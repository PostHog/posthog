import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.granola.granola import (
    GRANOLA_BASE_URL,
    PAGE_SIZE,
    GranolaResumeConfig,
    _build_initial_params,
    _build_url,
    _format_timestamp,
    granola_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.granola.settings import GRANOLA_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.granola.granola"
# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _mock_response(status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    return resp


def _response(body: dict[str, Any], status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = f"{GRANOLA_BASE_URL}/v1/notes"
    return resp


def _make_manager(resume_state: Optional[GranolaResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    The client mutates a single ``Request`` object in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    seen: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        seen.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return seen


def _pages(source_response) -> list[list[dict[str, Any]]]:
    return list(source_response.items())


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 1, 27, 15, 30, 0, tzinfo=UTC), "2026-01-27T15:30:00Z"),
            (datetime(2026, 1, 27, 15, 30, 0), "2026-01-27T15:30:00Z"),
            (date(2026, 1, 27), "2026-01-27T00:00:00Z"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_timestamp(self, value: Any, expected: str) -> None:
        assert _format_timestamp(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_timestamp(datetime(2026, 1, 27, 15, 30, tzinfo=UTC))


class TestBuildInitialParams:
    def test_non_incremental_only_sets_page_size(self) -> None:
        params = _build_initial_params(GRANOLA_ENDPOINTS["notes"], False, None, None)

        assert params == {"page_size": PAGE_SIZE}

    @pytest.mark.parametrize(
        "incremental_field, expected_param",
        [
            ("updated_at", "updated_after"),
            ("created_at", "created_after"),
            (None, "updated_after"),  # falls back to the first advertised field
        ],
    )
    def test_incremental_maps_field_to_server_filter(self, incremental_field, expected_param) -> None:
        params = _build_initial_params(
            GRANOLA_ENDPOINTS["notes"],
            True,
            datetime(2026, 1, 27, 15, 30, 0, tzinfo=UTC),
            incremental_field,
        )

        assert params[expected_param] == "2026-01-27T15:30:00Z"
        assert params["page_size"] == PAGE_SIZE

    def test_incremental_without_last_value_skips_filter(self) -> None:
        params = _build_initial_params(GRANOLA_ENDPOINTS["notes"], True, None, "updated_at")

        assert params == {"page_size": PAGE_SIZE}

    def test_folders_has_no_server_filter(self) -> None:
        # folders advertises no incremental fields, so it never gets a timestamp filter.
        params = _build_initial_params(
            GRANOLA_ENDPOINTS["folders"], True, datetime(2026, 1, 27, tzinfo=UTC), "updated_at"
        )

        assert params == {"page_size": PAGE_SIZE}


class TestBuildUrl:
    def test_build_url(self) -> None:
        url = _build_url("/v1/notes", {"page_size": 30, "cursor": "abc"})

        assert url == f"{GRANOLA_BASE_URL}/v1/notes?page_size=30&cursor=abc"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (200, "notes", True),
            (401, None, False),
            (401, "notes", False),
            (403, None, True),  # valid key, scope not granted - accepted at source-create
            (403, "notes", False),  # scope required for the specific schema
            (500, None, False),
        ],
    )
    def test_status_mapping(self, status, schema_name, expected_valid) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _mock_response(status)

            is_valid, _ = validate_credentials("grn_test", schema_name)

        assert is_valid is expected_valid

    def test_network_error_is_invalid(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("grn_test")

        assert is_valid is False
        assert message is not None

    @pytest.mark.parametrize(
        "schema_name, expected_path",
        [
            (None, "/v1/notes"),
            ("notes", "/v1/notes"),
            ("folders", "/v1/folders"),
            ("unknown", "/v1/notes"),
        ],
    )
    def test_probes_path_matching_schema(self, schema_name, expected_path) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _mock_response(200)

            validate_credentials("grn_test", schema_name)

            called_url = mock_session.return_value.get.call_args[0][0]

        assert called_url.startswith(f"{GRANOLA_BASE_URL}{expected_path}?")


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_yields_each_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"notes": [{"id": "not_1"}, {"id": "not_2"}], "hasMore": True, "cursor": "c1"}),
                _response({"notes": [{"id": "not_3"}], "hasMore": False, "cursor": None}),
            ],
        )

        pages = _pages(
            granola_source("grn_test", "notes", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )

        assert pages == [[{"id": "not_1"}, {"id": "not_2"}], [{"id": "not_3"}]]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding_each_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"notes": [{"id": "not_1"}], "hasMore": True, "cursor": "c1"}),
                _response({"notes": [{"id": "not_2"}], "hasMore": False, "cursor": None}),
            ],
        )

        manager = _make_manager()
        _rows(granola_source("grn_test", "notes", team_id=1, job_id="j", resumable_source_manager=manager))

        # Only one checkpoint - the final page has no next cursor.
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, GranolaResumeConfig)
        assert "cursor=c1" in saved.next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_cursor_missing_even_if_has_more(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"notes": [{"id": "not_1"}], "hasMore": True, "cursor": None})])

        manager = _make_manager()
        rows = _rows(granola_source("grn_test", "notes", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"id": "not_1"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_url(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = f"{GRANOLA_BASE_URL}/v1/notes?page_size=30&cursor=resume_token"
        seen = _wire(session, [_response({"notes": [{"id": "not_9"}], "hasMore": False, "cursor": None})])

        manager = _make_manager(GranolaResumeConfig(next_url=resume_url))
        _rows(granola_source("grn_test", "notes", team_id=1, job_id="j", resumable_source_manager=manager))

        assert seen[0]["url"] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_page_carries_page_size(self, MockSession) -> None:
        session = MockSession.return_value
        seen = _wire(session, [_response({"notes": [{"id": "not_1"}], "hasMore": False, "cursor": None})])

        _rows(granola_source("grn_test", "notes", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        assert seen[0]["params"]["page_size"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_in_first_request_and_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        seen = _wire(
            session,
            [
                _response({"notes": [{"id": "not_1"}], "hasMore": True, "cursor": "c1"}),
                _response({"notes": [{"id": "not_2"}], "hasMore": False, "cursor": None}),
            ],
        )

        manager = _make_manager()
        _rows(
            granola_source(
                "grn_test",
                "notes",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 27, 15, 30, 0, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        # Server-side filter is present on the initial request...
        assert seen[0]["params"]["updated_after"] == "2026-01-27T15:30:00Z"
        # ...and persists into the self-contained next-page URL so it isn't dropped after page 1.
        saved = manager.save_state.call_args.args[0]
        assert "updated_after=2026-01-27T15%3A30%3A00Z" in saved.next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        # A body without the wrapper key is treated as an empty page (not a hard error).
        _wire(session, [_response({"hasMore": False, "cursor": None})])

        rows = _rows(
            granola_source("grn_test", "notes", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )

        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_forbidden_status_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "forbidden"}, status=403)])

        with pytest.raises(HTTPError):
            _rows(granola_source("grn_test", "notes", team_id=1, job_id="j", resumable_source_manager=_make_manager()))


class TestGranolaSource:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_notes_response_has_datetime_partition(self, MockSession) -> None:
        response = granola_source("grn_test", "notes", team_id=1, job_id="j", resumable_source_manager=_make_manager())

        assert response.name == "notes"
        assert response.primary_keys == ["id"]
        # "desc" defers the incremental watermark commit until every page is processed.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "week"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_folders_response_has_no_partition(self, MockSession) -> None:
        response = granola_source(
            "grn_test", "folders", team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )

        assert response.name == "folders"
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
