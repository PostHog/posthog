import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.clickup import (
    ClickUpResumeConfig,
    _ms_to_iso,
    _normalize_task,
    _to_epoch_ms,
    clickup_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.settings import (
    CLICKUP_ENDPOINTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the clickup module.
CLICKUP_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.clickup.clickup.make_tracked_session"
)


def _response(payload: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(payload).encode()
    return resp


def _make_manager(resume_state: ClickUpResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return clickup_source("pk", "9", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestMsToIso:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("1567785250202", "2019-09-06T15:54:10.202000+00:00"),
            (1567785250202, "2019-09-06T15:54:10.202000+00:00"),
            (None, None),
            ("", ""),
            ("not-a-number", "not-a-number"),
        ],
    )
    def test_ms_to_iso(self, value: Any, expected: Any) -> None:
        assert _ms_to_iso(value) == expected


class TestNormalizeTask:
    def test_converts_known_date_fields(self) -> None:
        task = _normalize_task(
            {"id": "abc", "date_created": "1567785250202", "date_updated": "1567785260202", "name": "Task"}
        )
        assert task["date_created"] == "2019-09-06T15:54:10.202000+00:00"
        assert task["date_updated"] == "2019-09-06T15:54:20.202000+00:00"
        assert task["name"] == "Task"

    def test_leaves_missing_and_null_fields(self) -> None:
        task = _normalize_task({"id": "abc", "date_closed": None})
        assert task["date_closed"] is None
        assert "due_date" not in task


class TestToEpochMs:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2019, 9, 6, 15, 54, 10, 202000, tzinfo=UTC), 1567785250202),
            (datetime(2019, 9, 6, 15, 54, 10, 202000), 1567785250202),
            (date(2019, 9, 6), 1567728000000),
            ("1567785250202", 1567785250202),
            ("nope", None),
        ],
    )
    def test_to_epoch_ms(self, value: Any, expected: Any) -> None:
        assert _to_epoch_ms(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(CLICKUP_SESSION_PATCH)
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected_valid: bool) -> None:
        mock_session.return_value.get.return_value = _response({"teams": [{"id": "9"}]}, status_code=status_code)
        valid, _ = validate_credentials("pk_token", workspace_id=None)
        assert valid is expected_valid

    @mock.patch(CLICKUP_SESSION_PATCH)
    def test_workspace_must_be_accessible(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"teams": [{"id": "9"}]})

        ok, _ = validate_credentials("pk_token", workspace_id="9")
        assert ok is True

        bad, message = validate_credentials("pk_token", workspace_id="404")
        assert bad is False
        assert message is not None and "404" in message

    @mock.patch(CLICKUP_SESSION_PATCH)
    def test_request_exception_returns_error(self, mock_session: mock.MagicMock) -> None:
        import requests

        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        valid, message = validate_credentials("pk_token", workspace_id=None)
        assert valid is False
        assert message == "boom"


class TestTasks:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        full_page = {"tasks": [{"id": str(i), "date_updated": "1567785250202"} for i in range(100)]}
        short_page = {"tasks": [{"id": "100", "date_updated": "1567785250202"}]}
        snapshots = _wire(session, [_response(full_page), _response(short_page)])

        manager = _make_manager()
        rows = _rows(_source("tasks", manager))

        assert session.send.call_count == 2
        assert len(rows) == 101
        # Date fields normalized to ISO on the way out.
        assert rows[0]["date_updated"].startswith("2019-09-06T")
        assert snapshots[0]["params"]["page"] == 0
        assert snapshots[1]["params"]["page"] == 1
        # Checkpoint the page just yielded so a crash re-fetches it (merge dedupes). The final short
        # page has no next page, so no checkpoint follows it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ClickUpResumeConfig(page=0)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_last_page_flag_stops_pagination(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        page = {"tasks": [{"id": str(i)} for i in range(100)], "last_page": True}
        _wire(session, [_response(page)])

        _rows(_source("tasks", _make_manager()))
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"tasks": []})])

        manager = _make_manager()
        rows = _rows(_source("tasks", manager))
        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"tasks": [{"id": "1"}]})])

        _rows(_source("tasks", _make_manager(ClickUpResumeConfig(page=4))))
        assert snapshots[0]["params"]["page"] == 4

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_adds_date_updated_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"tasks": [{"id": "1"}]})])

        _rows(
            _source(
                "tasks",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2019, 9, 6, 15, 54, 10, 202000, tzinfo=UTC),
            )
        )
        assert snapshots[0]["params"]["date_updated_gt"] == 1567785250202

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_omits_date_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"tasks": [{"id": "1"}]})])

        _rows(_source("tasks", _make_manager(), should_use_incremental_field=False))
        assert "date_updated_gt" not in snapshots[0]["params"]


class TestTeamScoped:
    @pytest.mark.parametrize(
        "endpoint, expected_path",
        [
            ("workspaces", "/team"),
            ("spaces", "/team/9/space"),
            ("goals", "/team/9/goal"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_team_scoped_endpoints(self, MockSession: mock.MagicMock, endpoint: str, expected_path: str) -> None:
        session = MockSession.return_value
        data_key = CLICKUP_ENDPOINTS[endpoint].data_key
        snapshots = _wire(session, [_response({data_key: [{"id": "1"}, {"id": "2"}]})])

        rows = _rows(_source(endpoint, _make_manager()))

        assert snapshots[0]["url"].endswith(expected_path)
        assert [row["id"] for row in rows] == ["1", "2"]


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_folders_fan_out_over_spaces(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"spaces": [{"id": "s1"}, {"id": "s2"}]}),
                _response({"folders": [{"id": "f1"}]}),
                _response({"folders": [{"id": "f2"}]}),
            ],
        )

        rows = _rows(_source("folders", _make_manager()))
        assert [row["id"] for row in rows] == ["f1", "f2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_lists_combine_folderless_and_folder_lists(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        # Folderless lists are fetched first (space -> list), then folder lists (space -> folder ->
        # list); the space list is re-fetched to drive each of the two fan-outs.
        _wire(
            session,
            [
                _response({"spaces": [{"id": "s1"}]}),
                _response({"lists": [{"id": "l1"}]}),
                _response({"spaces": [{"id": "s1"}]}),
                _response({"folders": [{"id": "f1"}]}),
                _response({"lists": [{"id": "l2"}]}),
            ],
        )

        rows = _rows(_source("lists", _make_manager()))
        assert [row["id"] for row in rows] == ["l1", "l2"]


class TestClickUpSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = CLICKUP_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_tasks_use_desc_sort_mode(self) -> None:
        assert _source("tasks", _make_manager()).sort_mode == "desc"

    def test_non_task_endpoints_use_asc_sort_mode(self) -> None:
        assert _source("spaces", _make_manager()).sort_mode == "asc"

    @pytest.mark.parametrize("config", list(CLICKUP_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config: Any) -> None:
        if config.partition_key:
            assert config.partition_key == "date_created"
