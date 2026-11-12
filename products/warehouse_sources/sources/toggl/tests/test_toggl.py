import base64
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network
from products.warehouse_sources.sources.toggl._config import TogglSourceConfig
from products.warehouse_sources.sources.toggl.source import TogglSource
from products.warehouse_sources.sources.toggl.toggl import TogglResumeConfig, _windows

WORKSPACES_PATH = "/api/v9/me/workspaces"


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[None]:
    with time_machine.travel(datetime(2026, 3, 10, 12, tzinfo=UTC), tick=False):
        yield


def _driver() -> SourceDriver:
    return SourceDriver(TogglSource(), TogglSourceConfig(api_token="tok"))


def _search_path(workspace_id: int) -> str:
    return f"/reports/api/v3/workspace/{workspace_id}/search/time_entries"


def _group(entry_ids: list[int], **shared: Any) -> dict[str, Any]:
    return {
        "user_id": 7,
        "username": "Ada",
        "description": "Writing",
        "project_id": 3,
        "tag_ids": [11],
        "row_number": 1,
        **shared,
        "time_entries": [
            {"id": entry_id, "seconds": 60, "start": "2025-03-01T09:00:00+00:00", "stop": None, "at": "x"}
            for entry_id in entry_ids
        ],
    }


class TestTimeEntries:
    def test_walks_windows_and_pages_and_flattens_entries(self) -> None:
        result = _driver().run(
            "time_entries",
            [
                ScriptedResponse(json=[{"id": 1, "max_data_retention_days": 400}]),
                ScriptedResponse(json=[_group([101, 102])], headers={"X-Next-Row-Number": "51"}),
                ScriptedResponse(json=[_group([103], description="Review")]),
                ScriptedResponse(json=[]),
            ],
        )

        assert result.raised is None
        assert result.paths == [WORKSPACES_PATH, _search_path(1), _search_path(1), _search_path(1)]
        bodies = [request.json() for request in result.requests[1:]]
        assert [(b["start_date"], b["end_date"], b.get("first_row_number")) for b in bodies] == [
            ("2025-02-03", "2026-02-02", None),
            ("2025-02-03", "2026-02-02", 51),
            ("2026-02-03", "2026-03-11", None),
        ]
        assert {(b["order_by"], b["order_dir"], b["grouped"]) for b in bodies} == {("date", "ASC", False)}
        assert [(row["id"], row["workspace_id"], row["description"]) for row in result.rows] == [
            (101, 1, "Writing"),
            (102, 1, "Writing"),
            (103, 1, "Review"),
        ]
        assert "time_entries" not in result.rows[0]
        assert result.rows[0]["tag_ids"] == [11]
        assert result.committed_states == [
            TogglResumeConfig(workspace_id=1, window_start="2025-02-03", first_row_number=51),
            TogglResumeConfig(workspace_id=1, window_start="2026-02-03"),
            TogglResumeConfig(completed_workspace_ids=[1]),
        ]

    @parameterized.expand(
        [
            # The watermark moves the start back one day for creators in time zones ahead of UTC.
            (
                "incremental_watermark",
                {"max_data_retention_days": 0},
                datetime(2026, 3, 5, 8, tzinfo=UTC),
                "2026-03-04",
            ),
            (
                "watermark_older_than_retention",
                {"max_data_retention_days": 30},
                datetime(2020, 1, 1, tzinfo=UTC),
                "2026-02-08",
            ),
            ("watermark_as_string", {}, "2026-03-05T08:00:00Z", "2026-03-04"),
        ]
    )
    def test_first_window_starts_at_the_latest_bound(
        self, _name: str, workspace: dict[str, Any], watermark: Any, expected_start: str
    ) -> None:
        result = _driver().run(
            "time_entries",
            [ScriptedResponse(json=[{"id": 1, **workspace}]), ScriptedResponse(json=[])],
            incremental_field="start",
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert result.requests[1].json()["start_date"] == expected_start
        assert result.requests[1].json()["end_date"] == "2026-03-11"

    def test_resume_skips_finished_workspaces_and_continues_the_saved_page(self) -> None:
        result = _driver().run(
            "time_entries",
            [
                ScriptedResponse(json=[{"id": 1}, {"id": 2, "max_data_retention_days": 400}]),
                ScriptedResponse(json=[_group([201])]),
            ],
            resume_state=TogglResumeConfig(
                completed_workspace_ids=[1], workspace_id=2, window_start="2026-02-03", first_row_number=51
            ),
        )

        assert result.raised is None
        assert result.paths == [WORKSPACES_PATH, _search_path(2)]
        body = result.requests[1].json()
        assert (body["start_date"], body["first_row_number"]) == ("2026-02-03", 51)
        assert [row["id"] for row in result.rows] == [201]
        assert result.committed_states[-1] == TogglResumeConfig(completed_workspace_ids=[1, 2])

    def test_sends_the_token_with_the_api_token_password(self) -> None:
        result = _driver().run("time_entries", [ScriptedResponse(json=[])])

        expected = base64.b64encode(b"tok:api_token").decode()
        assert result.requests[0].headers["authorization"] == f"Basic {expected}"


class TestWindows:
    @parameterized.expand(
        [
            ("single_day_gets_a_later_end_date", date(2026, 3, 11), date(2026, 3, 11), [("2026-03-11", "2026-03-12")]),
            ("short_range", date(2026, 3, 1), date(2026, 3, 11), [("2026-03-01", "2026-03-11")]),
            (
                "range_longer_than_a_year",
                date(2024, 1, 1),
                date(2025, 1, 2),
                [("2024-01-01", "2024-12-30"), ("2024-12-31", "2025-01-02")],
            ),
        ]
    )
    def test_windows(self, _name: str, first: date, last: date, expected: list[tuple[str, str]]) -> None:
        assert [(start.isoformat(), end.isoformat()) for start, end in _windows(first, last)] == expected


class TestWorkspaceChildren:
    @parameterized.expand(
        [
            ("full_refresh", {}, None),
            (
                "incremental",
                {"incremental_field": "at", "db_incremental_field_last_value": datetime(2026, 3, 1, tzinfo=UTC)},
                "1772323200",
            ),
        ]
    )
    def test_projects_page_until_a_short_page(self, _name: str, inputs: dict[str, Any], since: str | None) -> None:
        result = _driver().run(
            "projects",
            [
                ScriptedResponse(json=[{"id": 9}]),
                ScriptedResponse(json=[{"id": i, "workspace_id": 9} for i in range(200)]),
                ScriptedResponse(json=[{"id": 200, "workspace_id": 9}]),
            ],
            **inputs,
        )

        assert result.raised is None
        assert result.paths == [WORKSPACES_PATH, "/api/v9/workspaces/9/projects", "/api/v9/workspaces/9/projects"]
        assert result.params("page")[1:] == ["1", "2"]
        assert {r.param("per_page") for r in result.requests[1:]} == {"200"}
        assert {r.param("active") for r in result.requests[1:]} == {"both"}
        assert {r.param("since") for r in result.requests[1:]} == {since}
        assert len(result.rows) == 201
        assert {row["workspace_id"] for row in result.rows} == {9}

    def test_tasks_stop_once_the_total_count_is_read(self) -> None:
        result = _driver().run(
            "tasks",
            [
                ScriptedResponse(json=[{"id": 9}]),
                ScriptedResponse(json={"data": [{"id": 1}, {"id": 2}], "page": 1, "per_page": 2, "total_count": 3}),
                ScriptedResponse(json={"data": [{"id": 3}], "page": 2, "per_page": 2, "total_count": 3}),
            ],
        )

        assert result.raised is None
        assert result.params("page")[1:] == ["1", "2"]
        assert [(row["id"], row["workspace_id"]) for row in result.rows] == [(1, 9), (2, 9), (3, 9)]

    def test_tags_page_until_an_empty_page(self) -> None:
        result = _driver().run(
            "tags",
            [
                ScriptedResponse(json=[{"id": 9}]),
                ScriptedResponse(json=[{"id": 1}]),
                ScriptedResponse(json=[]),
            ],
        )

        assert result.raised is None
        assert result.params("page")[1:] == ["1", "2"]
        assert [row["id"] for row in result.rows] == [1]

    def test_workspace_users_skip_a_workspace_the_user_cannot_read(self) -> None:
        result = _driver().run(
            "workspace_users",
            [
                ScriptedResponse(json=[{"id": 1}, {"id": 2}]),
                ScriptedResponse(status=403, body=b"User does not have access to this resource."),
                ScriptedResponse(json=[{"id": 7, "email": "ada@example.com", "role": "admin"}]),
            ],
        )

        assert result.raised is None
        assert [(row["id"], row["workspace_id"]) for row in result.rows] == [(7, 2)]

    def test_clients_include_archived_and_carry_the_workspace_id(self) -> None:
        result = _driver().run(
            "clients",
            [ScriptedResponse(json=[{"id": 9}]), ScriptedResponse(json=[{"id": 5, "wid": 9, "archived": True}])],
        )

        assert result.raised is None
        assert result.requests[1].param("status") == "both"
        assert [(row["id"], row["workspace_id"]) for row in result.rows] == [(5, 9)]

    def test_workspaces_drop_fields_that_hold_tokens(self) -> None:
        result = _driver().run(
            "workspaces",
            [ScriptedResponse(json=[{"id": 9, "name": "Acme", "api_token": "secret", "ical_url": "/ical/secret"}])],
        )

        assert result.raised is None
        assert result.rows == [{"id": 9, "name": "Acme"}]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True, None),
            ("rejected", 403, False, "Toggl Track rejected your API token"),
            ("unauthorized", 401, False, "Toggl Track rejected your API token"),
            ("vendor_error", 500, False, "Couldn't reach Toggl Track"),
        ]
    )
    def test_maps_the_probe_status(self, _name: str, status: int, ok: bool, message_prefix: str | None) -> None:
        with scripted_network([ScriptedResponse(status=status, json={})]) as network:
            valid, message = TogglSource().validate_credentials(TogglSourceConfig(api_token="tok"), team_id=1)

        assert network.requests_log[0].path == "/api/v9/me"
        assert valid is ok
        if message_prefix is None:
            assert message is None
        else:
            assert message is not None and message.startswith(message_prefix)
