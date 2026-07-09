from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import structlog
from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram import deepgram as deepgram_module
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.deepgram import (
    DeepgramResumeConfig,
    deepgram_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.settings import DEEPGRAM_ENDPOINTS

LOGGER = structlog.get_logger()

PROJECTS_PAYLOAD = {
    "projects": [
        {"project_id": "p1", "name": "First project"},
        {"project_id": "p2", "name": "Second project"},
    ]
}


def _response(payload: dict[str, Any], status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = HTTPError(f"{status_code} Client Error", response=response)
    return response


def _session_with(responses: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = responses
    return session


def _manager(resume: DeepgramResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _requested_urls(session: MagicMock) -> list[str]:
    return [call.args[0] for call in session.get.call_args_list]


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        session = _session_with([_response({"projects": []}, status_code=status_code)])
        with patch.object(deepgram_module, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("boom")
        with patch.object(deepgram_module, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is False


class TestProjectsEndpoint:
    def test_yields_projects_from_single_fetch(self) -> None:
        session = _session_with([_response(PROJECTS_PAYLOAD)])
        with patch.object(deepgram_module, "make_tracked_session", return_value=session):
            batches = list(get_rows("key", "projects", LOGGER, _manager()))

        assert batches == [PROJECTS_PAYLOAD["projects"]]
        assert session.get.call_count == 1

    def test_auth_header_uses_token_scheme(self) -> None:
        session = _session_with([_response(PROJECTS_PAYLOAD)])
        with patch.object(deepgram_module, "make_tracked_session", return_value=session):
            list(get_rows("secret-key", "projects", LOGGER, _manager()))

        headers = session.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Token secret-key"


class TestSnapshotEndpoints:
    def test_api_keys_rows_flatten_key_and_carry_project_id(self) -> None:
        keys_payload = {
            "api_keys": [
                {
                    "member": {"member_id": "m1", "email": "a@b.com"},
                    "api_key": {"api_key_id": "k1", "comment": "ci", "scopes": ["usage:read"]},
                }
            ]
        }
        session = _session_with([_response(PROJECTS_PAYLOAD), _response(keys_payload), _response({"api_keys": []})])
        with patch.object(deepgram_module, "make_tracked_session", return_value=session):
            batches = list(get_rows("key", "api_keys", LOGGER, _manager()))

        assert batches == [
            [
                {
                    "project_id": "p1",
                    "api_key_id": "k1",
                    "comment": "ci",
                    "scopes": ["usage:read"],
                    "member": {"member_id": "m1", "email": "a@b.com"},
                }
            ]
        ]
        assert _requested_urls(session) == [
            "https://api.deepgram.com/v1/projects",
            "https://api.deepgram.com/v1/projects/p1/keys",
            "https://api.deepgram.com/v1/projects/p2/keys",
        ]

    @parameterized.expand(
        [
            ("members", "members", {"member_id": "m1", "email": "a@b.com"}),
            ("balances", "balances", {"balance_id": "b1", "amount": 12.5, "units": "usd"}),
        ]
    )
    def test_rows_carry_project_id(self, endpoint: str, response_key: str, item: dict[str, Any]) -> None:
        session = _session_with(
            [_response(PROJECTS_PAYLOAD), _response({response_key: [item]}), _response({response_key: []})]
        )
        with patch.object(deepgram_module, "make_tracked_session", return_value=session):
            batches = list(get_rows("key", endpoint, LOGGER, _manager()))

        assert batches == [[{"project_id": "p1", **item}]]


class TestRequestsEndpoint:
    def _run(
        self,
        responses: list[MagicMock],
        manager: MagicMock,
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
        page_limit: int = 2,
    ) -> tuple[list[Any], MagicMock]:
        session = _session_with(responses)
        with (
            patch.object(deepgram_module, "make_tracked_session", return_value=session),
            patch.object(deepgram_module, "REQUESTS_PAGE_LIMIT", page_limit),
        ):
            batches = list(
                get_rows(
                    "key",
                    "requests",
                    LOGGER,
                    manager,
                    should_use_incremental_field=should_use_incremental_field,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
            )
        return batches, session

    def test_paginates_until_short_page_and_saves_state_after_yield(self) -> None:
        manager = _manager()
        full_page = {"requests": [{"request_id": "r1", "created": "2026-01-01"}, {"request_id": "r2"}]}
        short_page = {"requests": [{"request_id": "r3"}]}
        single_project = {"projects": [{"project_id": "p1"}]}
        batches, session = self._run([_response(single_project), _response(full_page), _response(short_page)], manager)

        assert [[row["request_id"] for row in batch] for batch in batches] == [["r1", "r2"], ["r3"]]
        assert all(row["project_id"] == "p1" for batch in batches for row in batch)

        request_urls = _requested_urls(session)[1:]
        assert [_query(url)["page"] for url in request_urls] == [["0"], ["1"]]

        saved = manager.save_state.call_args_list[0].args[0]
        assert saved.project_id == "p1"
        assert saved.page == 1
        assert saved.end is not None

    def test_bookmarks_next_project_between_projects(self) -> None:
        manager = _manager()
        batches, session = self._run(
            [_response(PROJECTS_PAYLOAD), _response({"requests": [{"request_id": "r1"}]}), _response({"requests": []})],
            manager,
        )

        assert [[row["project_id"] for row in batch] for batch in batches] == [["p1"]]
        bookmark = manager.save_state.call_args_list[0].args[0]
        assert bookmark.project_id == "p2"
        assert bookmark.page == 0

    def test_incremental_sync_passes_start_filter(self) -> None:
        manager = _manager()
        single_project = {"projects": [{"project_id": "p1"}]}
        _, session = self._run(
            [_response(single_project), _response({"requests": []})],
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC),
        )

        query = _query(_requested_urls(session)[1])
        assert query["start"] == ["2026-03-01T12:30:45"]
        assert "end" in query

    def test_first_sync_has_no_start_filter(self) -> None:
        manager = _manager()
        single_project = {"projects": [{"project_id": "p1"}]}
        _, session = self._run(
            [_response(single_project), _response({"requests": []})],
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        query = _query(_requested_urls(session)[1])
        assert "start" not in query
        assert "end" in query

    def test_resumes_from_saved_project_page_and_window(self) -> None:
        resume = DeepgramResumeConfig(project_id="p2", page=3, start="2026-01-01T00:00:00", end="2026-02-01T00:00:00")
        manager = _manager(resume)
        _, session = self._run(
            [_response(PROJECTS_PAYLOAD), _response({"requests": [{"request_id": "r9"}]})],
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC),
        )

        request_urls = _requested_urls(session)[1:]
        assert len(request_urls) == 1
        assert "/projects/p2/requests" in request_urls[0]
        query = _query(request_urls[0])
        # The interrupted sync's window is reused verbatim so page offsets stay stable.
        assert query["page"] == ["3"]
        assert query["start"] == ["2026-01-01T00:00:00"]
        assert query["end"] == ["2026-02-01T00:00:00"]

    def test_stale_resume_bookmark_starts_from_first_project(self) -> None:
        resume = DeepgramResumeConfig(project_id="gone", page=5, start=None, end="2026-02-01T00:00:00")
        manager = _manager(resume)
        _, session = self._run(
            [_response(PROJECTS_PAYLOAD), _response({"requests": []}), _response({"requests": []})],
            manager,
        )

        request_urls = _requested_urls(session)[1:]
        assert "/projects/p1/requests" in request_urls[0]
        assert _query(request_urls[0])["page"] == ["0"]


class TestFetchErrors:
    def test_non_retryable_http_error_raises(self) -> None:
        session = _session_with([_response({"err_msg": "not found"}, status_code=404)])
        with patch.object(deepgram_module, "make_tracked_session", return_value=session):
            with pytest.raises(HTTPError):
                list(get_rows("key", "projects", LOGGER, _manager()))


class TestSourceResponse:
    @parameterized.expand([(name, config.primary_keys) for name, config in DEEPGRAM_ENDPOINTS.items()])
    def test_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        response = deepgram_source("key", endpoint, LOGGER, _manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_requests_partitioning_and_sort_mode(self) -> None:
        response = deepgram_source("key", "requests", LOGGER, _manager())
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created"]
        assert response.sort_mode == "desc"

    def test_snapshot_endpoints_have_no_partitioning(self) -> None:
        response = deepgram_source("key", "members", LOGGER, _manager())
        assert response.partition_mode is None
        assert response.partition_keys is None
