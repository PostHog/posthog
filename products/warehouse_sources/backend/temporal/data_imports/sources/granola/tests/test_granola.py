import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.granola.granola import (
    GRANOLA_BASE_URL,
    PAGE_SIZE,
    GranolaResumeConfig,
    _build_initial_params,
    _build_url,
    _format_timestamp,
    get_rows,
    granola_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.granola.settings import GRANOLA_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.granola.granola"


def _response(status: int = 200, body: Optional[dict[str, Any]] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    return resp


class _StubManager:
    """Minimal stand-in for ResumableSourceManager that records saved state."""

    def __init__(self, resume_state: Optional[GranolaResumeConfig] = None) -> None:
        self._resume_state = resume_state
        self.saved: list[GranolaResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> Optional[GranolaResumeConfig]:
        return self._resume_state

    def save_state(self, data: GranolaResumeConfig) -> None:
        self.saved.append(data)


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
            mock_session.return_value.get.return_value = _response(status)

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
            mock_session.return_value.get.return_value = _response(200)

            validate_credentials("grn_test", schema_name)

            called_url = mock_session.return_value.get.call_args[0][0]

        assert called_url.startswith(f"{GRANOLA_BASE_URL}{expected_path}?")


class TestGetRows:
    def _run(self, manager: _StubManager, pages: list[dict[str, Any]], **kwargs: Any) -> list[list[dict[str, Any]]]:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [_response(200, page) for page in pages]
            return list(
                get_rows(
                    api_key="grn_test",
                    endpoint="notes",
                    logger=structlog.get_logger(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                    **kwargs,
                )
            )

    def test_paginates_and_yields_each_page(self) -> None:
        manager = _StubManager()
        pages = [
            {"notes": [{"id": "not_1"}, {"id": "not_2"}], "hasMore": True, "cursor": "c1"},
            {"notes": [{"id": "not_3"}], "hasMore": False, "cursor": None},
        ]

        batches = self._run(manager, pages)

        assert batches == [[{"id": "not_1"}, {"id": "not_2"}], [{"id": "not_3"}]]

    def test_saves_state_after_yielding_each_page(self) -> None:
        manager = _StubManager()
        pages = [
            {"notes": [{"id": "not_1"}], "hasMore": True, "cursor": "c1"},
            {"notes": [{"id": "not_2"}], "hasMore": False, "cursor": None},
        ]

        self._run(manager, pages)

        # Only one checkpoint - the final page has no next cursor.
        assert len(manager.saved) == 1
        assert "cursor=c1" in manager.saved[0].next_url

    def test_stops_when_cursor_missing_even_if_has_more(self) -> None:
        manager = _StubManager()
        pages = [{"notes": [{"id": "not_1"}], "hasMore": True, "cursor": None}]

        batches = self._run(manager, pages)

        assert batches == [[{"id": "not_1"}]]
        assert manager.saved == []

    def test_resumes_from_saved_url(self) -> None:
        resume_url = f"{GRANOLA_BASE_URL}/v1/notes?page_size=30&cursor=resume_token"
        manager = _StubManager(resume_state=GranolaResumeConfig(next_url=resume_url))

        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, {"notes": [{"id": "not_9"}], "hasMore": False, "cursor": None})
            ]
            list(
                get_rows(
                    api_key="grn_test",
                    endpoint="notes",
                    logger=structlog.get_logger(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
            )

            called_url = mock_session.return_value.get.call_args[0][0]

        assert called_url == resume_url


class TestGranolaSource:
    def test_notes_response_has_datetime_partition(self) -> None:
        response = granola_source(
            api_key="grn_test",
            endpoint="notes",
            logger=structlog.get_logger(),
            resumable_source_manager=mock.MagicMock(),
        )

        assert response.name == "notes"
        assert response.primary_keys == ["id"]
        # "desc" defers the incremental watermark commit until every page is processed.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "week"

    def test_folders_response_has_no_partition(self) -> None:
        response = granola_source(
            api_key="grn_test",
            endpoint="folders",
            logger=structlog.get_logger(),
            resumable_source_manager=mock.MagicMock(),
        )

        assert response.name == "folders"
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
