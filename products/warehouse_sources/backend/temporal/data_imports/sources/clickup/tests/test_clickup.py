from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.clickup import (
    ClickUpResumeConfig,
    _build_url,
    _ms_to_iso,
    _normalize_task,
    _to_epoch_ms,
    clickup_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.settings import (
    CLICKUP_ENDPOINTS,
    ENDPOINTS,
)

SESSION_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.clickup.clickup.make_tracked_session"


def _make_manager(resume_state: ClickUpResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(payload: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = payload
    return resp


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


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("/team") == "https://api.clickup.com/api/v2/team"

    def test_encodes_params(self) -> None:
        url = _build_url("/team/9/task", {"page": 0, "include_closed": "true"})
        assert url == "https://api.clickup.com/api/v2/team/9/task?page=0&include_closed=true"


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
    @mock.patch(SESSION_PATH)
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected_valid: bool) -> None:
        mock_session.return_value.get.return_value = _response({"teams": [{"id": "9"}]}, status_code=status_code)
        valid, _ = validate_credentials("pk_token", workspace_id=None)
        assert valid is expected_valid

    @mock.patch(SESSION_PATH)
    def test_workspace_must_be_accessible(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"teams": [{"id": "9"}]})

        ok, _ = validate_credentials("pk_token", workspace_id="9")
        assert ok is True

        bad, message = validate_credentials("pk_token", workspace_id="404")
        assert bad is False
        assert message is not None and "404" in message

    @mock.patch(SESSION_PATH)
    def test_request_exception_returns_error(self, mock_session: mock.MagicMock) -> None:
        import requests

        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        valid, message = validate_credentials("pk_token", workspace_id=None)
        assert valid is False
        assert message == "boom"


class TestGetRowsTasks:
    @mock.patch(SESSION_PATH)
    def test_paginates_until_short_page(self, mock_session: mock.MagicMock) -> None:
        full_page = {"tasks": [{"id": str(i), "date_updated": "1567785250202"} for i in range(100)]}
        short_page = {"tasks": [{"id": "100", "date_updated": "1567785250202"}]}
        mock_session.return_value.get.side_effect = [_response(full_page), _response(short_page)]

        manager = _make_manager()
        batches = list(get_rows("pk", "9", "tasks", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_count == 2
        assert sum(len(b) for b in batches) == 101
        # date fields normalized to ISO on the way out
        assert batches[0][0]["date_updated"].startswith("2019-09-06T")
        # State saved after each yielded page.
        assert manager.save_state.call_count == 2
        assert manager.save_state.call_args_list[0].args[0].page == 0
        assert manager.save_state.call_args_list[1].args[0].page == 1

    @mock.patch(SESSION_PATH)
    def test_last_page_flag_stops_pagination(self, mock_session: mock.MagicMock) -> None:
        page = {"tasks": [{"id": str(i)} for i in range(100)], "last_page": True}
        mock_session.return_value.get.return_value = _response(page)

        list(get_rows("pk", "9", "tasks", mock.MagicMock(), _make_manager()))
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(SESSION_PATH)
    def test_empty_first_page_yields_nothing(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"tasks": []})
        manager = _make_manager()

        batches = list(get_rows("pk", "9", "tasks", mock.MagicMock(), manager))
        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(SESSION_PATH)
    def test_resumes_from_saved_page(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"tasks": [{"id": "1"}]})
        manager = _make_manager(ClickUpResumeConfig(page=4))

        list(get_rows("pk", "9", "tasks", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "page=4" in url

    @mock.patch(SESSION_PATH)
    def test_incremental_adds_date_updated_filter(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"tasks": [{"id": "1"}]})

        list(
            get_rows(
                "pk",
                "9",
                "tasks",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2019, 9, 6, 15, 54, 10, 202000, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "date_updated_gt=1567785250202" in url

    @mock.patch(SESSION_PATH)
    def test_full_refresh_omits_date_filter(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"tasks": [{"id": "1"}]})

        list(get_rows("pk", "9", "tasks", mock.MagicMock(), _make_manager(), should_use_incremental_field=False))

        url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "date_updated_gt" not in url


class TestGetRowsTeamScoped:
    @pytest.mark.parametrize(
        "endpoint, expected_path",
        [
            ("workspaces", "/team"),
            ("spaces", "/team/9/space"),
            ("goals", "/team/9/goal"),
        ],
    )
    @mock.patch(SESSION_PATH)
    def test_team_scoped_endpoints(self, mock_session: mock.MagicMock, endpoint: str, expected_path: str) -> None:
        data_key = CLICKUP_ENDPOINTS[endpoint].data_key
        mock_session.return_value.get.return_value = _response({data_key: [{"id": "1"}, {"id": "2"}]})

        batches = list(get_rows("pk", "9", endpoint, mock.MagicMock(), _make_manager()))

        called_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert called_url.endswith(expected_path)
        assert [item["id"] for batch in batches for item in batch] == ["1", "2"]


class TestGetRowsFanOut:
    @mock.patch(SESSION_PATH)
    def test_folders_fan_out_over_spaces(self, mock_session: mock.MagicMock) -> None:
        spaces = _response({"spaces": [{"id": "s1"}, {"id": "s2"}]})
        s1_folders = _response({"folders": [{"id": "f1"}]})
        s2_folders = _response({"folders": [{"id": "f2"}]})
        mock_session.return_value.get.side_effect = [spaces, s1_folders, s2_folders]

        batches = list(get_rows("pk", "9", "folders", mock.MagicMock(), _make_manager()))

        assert [item["id"] for batch in batches for item in batch] == ["f1", "f2"]

    @mock.patch(SESSION_PATH)
    def test_lists_combine_folderless_and_folder_lists(self, mock_session: mock.MagicMock) -> None:
        spaces = _response({"spaces": [{"id": "s1"}]})
        folderless = _response({"lists": [{"id": "l1"}]})
        folders = _response({"folders": [{"id": "f1"}]})
        folder_lists = _response({"lists": [{"id": "l2"}]})
        mock_session.return_value.get.side_effect = [spaces, folderless, folders, folder_lists]

        batches = list(get_rows("pk", "9", "lists", mock.MagicMock(), _make_manager()))

        assert [item["id"] for batch in batches for item in batch] == ["l1", "l2"]


class TestClickUpSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = CLICKUP_ENDPOINTS[endpoint]
        response = clickup_source("pk", "9", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_tasks_use_desc_sort_mode(self) -> None:
        assert clickup_source("pk", "9", "tasks", mock.MagicMock(), _make_manager()).sort_mode == "desc"

    def test_non_task_endpoints_use_asc_sort_mode(self) -> None:
        assert clickup_source("pk", "9", "spaces", mock.MagicMock(), _make_manager()).sort_mode == "asc"

    @pytest.mark.parametrize("config", list(CLICKUP_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config: Any) -> None:
        if config.partition_key:
            assert config.partition_key == "date_created"
