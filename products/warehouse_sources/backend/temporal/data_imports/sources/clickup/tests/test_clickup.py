import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.clickup import (
    TIME_ENTRIES_HISTORY_FLOOR,
    TIME_IN_STATUS_BATCH_SIZE,
    ClickUpResumeConfig,
    _ms_to_iso,
    _normalize_task,
    _normalize_time_entry,
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


def _wire_repeating(session: mock.MagicMock, first: list[Response], then: Any) -> list[dict[str, Any]]:
    """Like `_wire`, but answers every request past `first` by calling `then()` for a fresh response.

    A full-refresh window walk issues one request per window back to the history floor, far more
    than a fixed list can hold.
    """
    remaining = list(first)

    def _send(*args: Any, **kwargs: Any) -> Response:
        return remaining.pop(0) if remaining else then()

    snapshots = _wire(session, [])
    session.send.side_effect = _send
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


class TestNormalizeTimeEntry:
    def test_converts_entry_timestamps(self) -> None:
        entry = _normalize_time_entry(
            {"id": "4", "start": "1567785250202", "end": "1567785260202", "at": "1567785270202", "duration": "10000"}
        )
        assert entry["start"] == "2019-09-06T15:54:10.202000+00:00"
        assert entry["end"] == "2019-09-06T15:54:20.202000+00:00"
        assert entry["at"] == "2019-09-06T15:54:30.202000+00:00"
        # Duration is a millisecond count, not a timestamp, so it must survive untouched.
        assert entry["duration"] == "10000"


class TestTimeEntries:
    TEAMS = {"teams": [{"id": "9", "members": [{"user": {"id": 11}}, {"user": {"id": 22}}]}]}

    def _entries(self, *ids: str) -> dict[str, Any]:
        return {"data": [{"id": entry_id, "start": "1567785250202"} for entry_id in ids]}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_windows_from_the_watermark(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        watermark = datetime.now(tz=UTC) - timedelta(days=45)
        snapshots = _wire(
            session,
            [_response(self.TEAMS), _response(self._entries("e1")), _response(self._entries("e2"))],
        )

        manager = _make_manager()
        rows = _rows(
            _source(
                "time_entries",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )
        )

        # Members first, then one request per 30-day window up to now: 45 days spans two.
        assert [row["id"] for row in rows] == ["e1", "e2"]
        assert snapshots[0]["url"].endswith("/team")
        windows = snapshots[1:]
        assert len(windows) == 2
        assert all(snapshot["url"].endswith("/team/9/time_entries") for snapshot in windows)
        assert windows[0]["params"]["start_date"] == round(watermark.timestamp() * 1000)
        # Windows are contiguous and oldest first, so nothing between them goes unfetched.
        assert windows[0]["params"]["end_date"] == windows[1]["params"]["start_date"]
        assert windows[0]["params"]["start_date"] < windows[1]["params"]["start_date"]
        # Only the workspace's own members are named; `assignee` is what widens the endpoint past
        # the calling user's own entries.
        assert windows[0]["params"]["assignee"] == "11,22"
        assert rows[0]["start"].startswith("2019-09-06T")
        # Checkpoint the window just yielded, not the next one: a crash re-fetches it and merge
        # dedupes.
        saved = [call.args[0].window_start for call in manager.save_state.call_args_list]
        assert saved == [window["params"]["start_date"] for window in windows]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_the_saved_window(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        resume_start = round((datetime.now(tz=UTC) - timedelta(days=10)).timestamp() * 1000)
        snapshots = _wire(session, [_response(self.TEAMS), _response(self._entries("e1"))])

        _rows(
            _source(
                "time_entries",
                _make_manager(ClickUpResumeConfig(window_start=resume_start)),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime.now(tz=UTC) - timedelta(days=365),
            )
        )

        # The saved window wins over the watermark, so a resumed sync doesn't re-walk a year.
        assert snapshots[1]["params"]["start_date"] == resume_start

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_starts_at_the_history_floor(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire_repeating(session, [_response(self.TEAMS)], lambda: _response({"data": []}))

        _rows(_source("time_entries", _make_manager(), should_use_incremental_field=False))

        # No watermark means the whole history, which the endpoint only returns when asked,
        # because without an explicit start_date it answers with the last 30 days.
        assert snapshots[1]["params"]["start_date"] == round(TIME_ENTRIES_HISTORY_FLOOR.timestamp() * 1000)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fails_when_no_members_resolve(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        # A token that can see other workspaces but not the configured one.
        _wire(session, [_response({"teams": [{"id": "404", "members": [{"user": {"id": 11}}]}]})])

        # Syncing without `assignee` would fill a workspace-wide table with one user's time, and
        # nothing downstream could tell that from a workspace where only one person tracks time.
        with pytest.raises(ValueError, match="no members for workspace 9"):
            _rows(
                _source(
                    "time_entries",
                    _make_manager(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime.now(tz=UTC) - timedelta(days=1),
                )
            )


class TestTaskTimeInStatus:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flattens_the_map_into_rows_keyed_by_task(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"tasks": [{"id": "t1"}, {"id": "t2"}]}),
                _response(
                    {
                        "t1": {"current_status": {"status": "open"}, "status_history": []},
                        "t2": {"current_status": {"status": "done"}, "status_history": []},
                        # ClickUp has no wrapper key here, so a stray non-object value would
                        # otherwise be merged into a row.
                        "error": "nope",
                    }
                ),
            ],
        )

        rows = _rows(_source("task_time_in_status", _make_manager()))

        assert [(row["task_id"], row["current_status"]["status"]) for row in rows] == [("t1", "open"), ("t2", "done")]
        assert snapshots[1]["url"].endswith("/task/bulk_time_in_status/task_ids")
        assert snapshots[1]["params"]["task_ids"] == ["t1", "t2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_batches_at_the_endpoint_cap(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        first_batch = [str(i) for i in range(TIME_IN_STATUS_BATCH_SIZE)]
        snapshots = _wire(
            session,
            [
                _response({"tasks": [{"id": task_id} for task_id in first_batch]}),
                _response({task_id: {"current_status": {}, "status_history": []} for task_id in first_batch}),
                _response({"tasks": [{"id": "last"}]}),
                _response({"last": {"current_status": {}, "status_history": []}}),
            ],
        )

        rows = _rows(_source("task_time_in_status", _make_manager()))

        assert len(rows) == TIME_IN_STATUS_BATCH_SIZE + 1
        # The batch is flushed as soon as it fills, before the next task page is fetched.
        assert [snapshot["url"].rsplit("/", 1)[-1] for snapshot in snapshots] == [
            "task",
            "task_ids",
            "task",
            "task_ids",
        ]
        assert snapshots[3]["params"]["task_ids"] == ["last"]


class TestListChildren:
    # Two lists reached by both routes: one folderless, one under a folder.
    LISTS_WALK = [
        {"spaces": [{"id": "s1"}]},
        {"lists": [{"id": "l1"}]},
        {"spaces": [{"id": "s1"}]},
        {"folders": [{"id": "f1"}]},
        {"lists": [{"id": "l2"}]},
    ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stamps_each_field_with_the_list_it_came_from(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        responses = [
            _response(self.LISTS_WALK[0]),
            _response(self.LISTS_WALK[1]),
            _response({"fields": [{"id": "cf1"}]}),
            _response(self.LISTS_WALK[2]),
            _response(self.LISTS_WALK[3]),
            _response(self.LISTS_WALK[4]),
            _response({"fields": [{"id": "cf1"}, {"id": "cf2"}]}),
        ]
        snapshots = _wire(session, responses)

        rows = _rows(_source("list_custom_fields", _make_manager()))

        # A field defined above the list repeats per list, so the row needs the list id the
        # composite primary key merges on.
        assert [(row["_list_id"], row["id"]) for row in rows] == [("l1", "cf1"), ("l2", "cf1"), ("l2", "cf2")]
        assert snapshots[2]["url"].endswith("/list/l1/field")
        assert snapshots[6]["url"].endswith("/list/l2/field")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_skips_a_list_that_stops_serving_its_fields(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(self.LISTS_WALK[0]),
                _response(self.LISTS_WALK[1]),
                _response({"err": "List not found"}, status_code=404),
                _response(self.LISTS_WALK[2]),
                _response(self.LISTS_WALK[3]),
                _response(self.LISTS_WALK[4]),
                _response({"fields": [{"id": "cf2"}]}),
            ],
        )

        rows = _rows(_source("list_custom_fields", _make_manager()))

        # An archived or deleted list must not take the whole table down with it.
        assert [(row["_list_id"], row["id"]) for row in rows] == [("l2", "cf2")]


class TestTeamScoped:
    @pytest.mark.parametrize(
        "endpoint, expected_path",
        [
            ("workspaces", "/team"),
            ("spaces", "/team/9/space"),
            ("goals", "/team/9/goal"),
            ("custom_fields", "/team/9/field"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_team_scoped_endpoints(self, MockSession: mock.MagicMock, endpoint: str, expected_path: str) -> None:
        session = MockSession.return_value
        data_key = CLICKUP_ENDPOINTS[endpoint].data_key or ""
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
