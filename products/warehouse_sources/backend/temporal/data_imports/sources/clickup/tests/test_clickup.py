from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.clickup import (
    TIME_ENTRIES_HISTORY_FLOOR,
    TIME_IN_STATUS_BATCH_SIZE,
    ClickUpResumeConfig,
    _ms_to_iso,
    _to_epoch_ms,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.settings import (
    CLICKUP_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.source import ClickUpSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clickup import (
    ClickUpSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(ClickUpSource(), ClickUpSourceConfig(api_key="pk_token", workspace_id="9"))


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
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={"teams": [{"id": "9"}]}))) as network:
            valid, _ = validate_credentials("pk_token", workspace_id=None)

        assert valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/api/v2/team"}
        assert network.requests_log[0].headers["authorization"] == "pk_token"

    def test_workspace_must_be_accessible(self) -> None:
        with scripted_network([ScriptedResponse(json={"teams": [{"id": "9"}]})]) as network:
            ok, _ = validate_credentials("pk_token", workspace_id="9")

        with scripted_network([ScriptedResponse(json={"teams": [{"id": "9"}]})]) as second_network:
            bad, message = validate_credentials("pk_token", workspace_id="404")

        assert ok is True
        assert bad is False
        assert message is not None and "can't access this workspace" in message
        assert [request.path for request in network.requests_log] == ["/api/v2/team"]
        assert [request.path for request in second_network.requests_log] == ["/api/v2/team"]

    @pytest.mark.parametrize(
        "workspace_id",
        ["https://app.clickup.com/9/settings/team/9/general", "app.clickup.com/9/home", " 9 "],
    )
    def test_pasted_workspace_url_resolves_to_its_id(self, workspace_id: str) -> None:
        with scripted_network([ScriptedResponse(json={"teams": [{"id": "9"}]})]):
            valid, message = validate_credentials("pk_token", workspace_id=workspace_id)

        assert (valid, message) == (True, None)

    @pytest.mark.parametrize(
        "workspace_id",
        ["https://app.clickup.com/t/86abc123", "my-workspace", "https://evil.com/app.clickup.com/9"],
    )
    def test_non_numeric_workspace_is_rejected_before_calling_clickup(self, workspace_id: str) -> None:
        with scripted_network([]) as network:
            valid, message = validate_credentials("pk_token", workspace_id=workspace_id)

        assert valid is False
        assert message is not None and "Paste that URL or enter just the number" in message
        assert workspace_id not in message
        assert network.requests_log == []

    def test_request_exception_returns_error(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            valid, message = validate_credentials("pk_token", workspace_id=None)

        assert valid is False
        assert message is not None and "boom" in message
        assert {request.path for request in network.requests_log} == {"/api/v2/team"}


class TestTasks:
    def test_paginates_until_short_page(self) -> None:
        full_page = {"tasks": [{"id": str(i), "date_updated": "1567785250202"} for i in range(100)]}
        short_page = {"tasks": [{"id": "100", "date_updated": "1567785250202"}]}
        result = _driver().run("tasks", [ScriptedResponse(json=full_page), ScriptedResponse(json=short_page)])

        assert result.raised is None
        assert len(result.requests) == 2
        assert len(result.rows) == 101
        # Date fields normalized to ISO on the way out.
        assert result.rows[0]["date_updated"].startswith("2019-09-06T")
        assert result.params("page") == ["0", "1"]
        # Checkpoint the page just yielded so a crash re-fetches it (merge dedupes). The final short
        # page has no next page, so no checkpoint follows it.
        assert result.saved_states == [ClickUpResumeConfig(page=0)]

    def test_empty_first_page_yields_nothing(self) -> None:
        result = _driver().run("tasks", [ScriptedResponse(json={"tasks": []})])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "tasks",
            [ScriptedResponse(json={"tasks": [{"id": "1"}]})],
            resume_state=ClickUpResumeConfig(page=4),
        )

        assert result.raised is None
        assert result.params("page") == ["4"]

    def test_incremental_adds_date_updated_filter(self) -> None:
        result = _driver().run(
            "tasks",
            [ScriptedResponse(json={"tasks": [{"id": "1"}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2019, 9, 6, 15, 54, 10, 202000, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("date_updated_gt") == ["1567785250202"]


class TestTimeEntries:
    TEAMS = {"teams": [{"id": "9", "members": [{"user": {"id": 11}}, {"user": {"id": 22}}]}]}

    def _entries(self, *ids: str) -> dict[str, Any]:
        return {"data": [{"id": entry_id, "start": "1567785250202"} for entry_id in ids]}

    def test_resumes_from_the_saved_window(self) -> None:
        resume_start = round((datetime.now(tz=UTC) - timedelta(days=10)).timestamp() * 1000)
        result = _driver().run(
            "time_entries",
            [ScriptedResponse(json=self.TEAMS), ScriptedResponse(json=self._entries("e1"))],
            resume_state=ClickUpResumeConfig(window_start=resume_start),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now(tz=UTC) - timedelta(days=365),
        )

        assert result.raised is None
        # The saved window wins over the watermark, so a resumed sync doesn't re-walk a year.
        assert result.requests[1].param("start_date") == str(resume_start)

    def test_full_refresh_starts_at_the_history_floor(self) -> None:
        def answer(request: RecordedRequest) -> ScriptedResponse:
            return ScriptedResponse(json=self.TEAMS if request.path == "/api/v2/team" else {"data": []})

        result = _driver().run("time_entries", answer, should_use_incremental_field=False)

        assert result.raised is None
        # No watermark means the whole history, which the endpoint only returns when asked,
        # because without an explicit start_date it answers with the last 30 days.
        assert result.requests[1].param("start_date") == str(round(TIME_ENTRIES_HISTORY_FLOOR.timestamp() * 1000))

    def test_fails_when_no_members_resolve(self) -> None:
        result = _driver().run(
            "time_entries",
            [ScriptedResponse(json={"teams": [{"id": "404", "members": [{"user": {"id": 11}}]}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now(tz=UTC) - timedelta(days=1),
        )

        # A token that can see other workspaces but not the configured one.
        # Syncing without `assignee` would fill a workspace-wide table with one user's time, and
        # nothing downstream could tell that from a workspace where only one person tracks time.
        assert isinstance(result.raised, ValueError)
        assert "no members for workspace 9" in str(result.raised)


class TestTaskTimeInStatus:
    def test_batches_at_the_endpoint_cap(self) -> None:
        first_batch = [str(i) for i in range(TIME_IN_STATUS_BATCH_SIZE)]
        result = _driver().run(
            "task_time_in_status",
            [
                ScriptedResponse(json={"tasks": [{"id": task_id} for task_id in first_batch]}),
                ScriptedResponse(
                    json={task_id: {"current_status": {}, "status_history": []} for task_id in first_batch}
                ),
                ScriptedResponse(json={"tasks": [{"id": "last"}]}),
                ScriptedResponse(json={"last": {"current_status": {}, "status_history": []}}),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == TIME_IN_STATUS_BATCH_SIZE + 1
        # The batch is flushed as soon as it fills, before the next task page is fetched.
        assert result.paths == [
            "/api/v2/team/9/task",
            "/api/v2/task/bulk_time_in_status/task_ids",
            "/api/v2/team/9/task",
            "/api/v2/task/bulk_time_in_status/task_ids",
        ]
        assert result.requests[1].query["task_ids"] == tuple(first_batch)
        assert result.requests[3].param("task_ids") == "last"


class TestListChildren:
    # Two lists reached by both routes: one folderless, one under a folder.
    LISTS_WALK = [
        {"spaces": [{"id": "s1"}]},
        {"lists": [{"id": "l1"}]},
        {"spaces": [{"id": "s1"}]},
        {"folders": [{"id": "f1"}]},
        {"lists": [{"id": "l2"}]},
    ]

    def test_skips_a_list_that_stops_serving_its_fields(self) -> None:
        result = _driver().run(
            "list_custom_fields",
            [
                ScriptedResponse(json=self.LISTS_WALK[0]),
                ScriptedResponse(json=self.LISTS_WALK[1]),
                ScriptedResponse(status=404, json={"err": "List not found"}),
                ScriptedResponse(json=self.LISTS_WALK[2]),
                ScriptedResponse(json=self.LISTS_WALK[3]),
                ScriptedResponse(json=self.LISTS_WALK[4]),
                ScriptedResponse(json={"fields": [{"id": "cf2"}]}),
            ],
        )

        # An archived or deleted list must not take the whole table down with it.
        assert result.raised is None
        assert [(row["_list_id"], row["id"]) for row in result.rows] == [("l2", "cf2")]


class TestClickUpSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = CLICKUP_ENDPOINTS[endpoint]
        answer = ScriptedResponse(
            json={
                "teams": [{"id": "9", "members": [{"user": {"id": 11}}]}],
                "spaces": [],
                "folders": [],
                "lists": [],
                "tasks": [],
                "goals": [],
                "data": [],
                "fields": [],
            }
        )
        result = _driver().run(endpoint, always(answer))

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        if config.partition_key:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_keys == [config.partition_key]
        else:
            assert result.response.partition_mode is None
            assert result.response.partition_keys is None
