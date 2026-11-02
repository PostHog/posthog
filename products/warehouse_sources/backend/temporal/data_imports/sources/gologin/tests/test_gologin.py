from typing import Any

import pytest
import time_machine

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gologin import (
    GoLoginSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.gologin import (
    GoLoginResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.settings import REQUEST_TIMEOUT
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.source import GoLoginSource


class TestGoLoginTransport:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(GoLoginSource(), GoLoginSourceConfig(api_key="test-token"))

    @pytest.mark.parametrize("resume_page", [None, 4])
    @pytest.mark.parametrize("incremental", [False, True])
    def test_profiles_page_requests_and_checkpoints(self, resume_page: int | None, incremental: bool) -> None:
        rows = [{"id": f"profile-{index}", "createdAt": "2026-01-01T00:00:00Z"} for index in range(31)]
        result = self._driver().run(
            "profiles",
            [
                ScriptedResponse(json={"profiles": rows[:30], "allProfilesCount": 31}),
                ScriptedResponse(json={"profiles": rows[30:], "allProfilesCount": 31}),
                ScriptedResponse(json={"profiles": [], "allProfilesCount": 31}),
            ],
            resume_state=GoLoginResumeConfig(page=resume_page) if resume_page is not None else None,
            should_use_incremental_field=incremental,
            db_incremental_field_last_value="2026-01-02T00:00:00Z",
        )

        first_page = resume_page or 1
        assert result.raised is None
        assert result.items == [rows[:30], rows[30:]]
        assert result.rows == rows
        assert result.saved_states == [
            GoLoginResumeConfig(page=first_page + 1),
            GoLoginResumeConfig(page=first_page + 2),
        ]
        assert result.committed_states == result.saved_states
        assert len(result.requests) == 3
        for index, request in enumerate(result.requests):
            assert request.method == "GET"
            assert request.origin == "https://api.gologin.com"
            assert request.path == "/browser/v2"
            assert request.query == {
                "page": (str(first_page + index),),
                "sorterField": ("createdAt",),
                "sorterOrder": ("ascend",),
            }
            assert request.headers["authorization"] == "Bearer test-token"
            assert request.read_timeout == REQUEST_TIMEOUT[1]

    @pytest.mark.parametrize("status", [401, 403])
    def test_pipeline_errors_match_user_messages(self, status: int) -> None:
        result = self._driver().run("profiles", [ScriptedResponse(status=status, json={"statusCode": status})])

        assert isinstance(result.raised, HTTPError)
        errors = GoLoginSource().get_non_retryable_errors()
        assert any(key in str(result.raised) and message for key, message in errors.items())
        assert result.paths == ["/browser/v2"]

    @pytest.mark.parametrize(
        "endpoint,path,workspace_query,child_bodies,expected_rows",
        [
            (
                "tags",
                "/tags/all",
                "workspace",
                [
                    {"success": True, "tags": [{"_id": "tag-1", "title": "ads", "color": "blue"}]},
                    {"success": True, "tags": [{"id": "tag-2", "title": "seo", "color": "pink"}]},
                ],
                [
                    {"id": "tag-1", "title": "ads", "color": "blue", "workspace_id": "ws-1"},
                    {"id": "tag-2", "title": "seo", "color": "pink", "workspace_id": "ws-2"},
                ],
            ),
            (
                "folders",
                None,
                None,
                [
                    {"id": "ws-1", "folders": [{"id": "folder-1", "name": "Team A"}]},
                    {"id": "ws-2", "folders": [{"id": "folder-2", "name": "Team B"}]},
                ],
                [
                    {"id": "folder-1", "name": "Team A", "workspace_id": "ws-1"},
                    {"id": "folder-2", "name": "Team B", "workspace_id": "ws-2"},
                ],
            ),
            (
                "cloud_usage_daily",
                "/cloud-usage/stats",
                "workspaceId",
                [
                    {"days": [{"date": "2026-10-20", "launches": 3, "hours": 1.5}], "limits": {}},
                    {"days": [{"date": "2026-10-20", "launches": 0, "hours": 0}], "limits": {}},
                ],
                [
                    {"date": "2026-10-20", "launches": 3, "hours": 1.5, "workspace_id": "ws-1"},
                    {"date": "2026-10-20", "launches": 0, "hours": 0, "workspace_id": "ws-2"},
                ],
            ),
        ],
    )
    def test_workspace_endpoints_fan_out_per_workspace(
        self,
        endpoint: str,
        path: str | None,
        workspace_query: str | None,
        child_bodies: list[dict[str, Any]],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = self._driver().run(
            endpoint,
            [
                ScriptedResponse(json=[{"id": "ws-1", "name": "One"}, {"id": "ws-2", "name": "Two"}]),
                *(ScriptedResponse(json=body) for body in child_bodies),
            ],
        )

        assert result.raised is None
        assert result.rows == expected_rows
        assert result.paths[0] == "/workspaces"
        for workspace_id, request in zip(["ws-1", "ws-2"], result.requests[1:]):
            if workspace_query is None:
                assert request.path == f"/workspaces/{workspace_id}"
            else:
                assert request.path == path
                assert request.query[workspace_query] == (workspace_id,)

    def test_deleted_profiles_advance_offset_until_gologin_reports_no_more(self) -> None:
        result = self._driver().run(
            "deleted_profiles",
            [
                ScriptedResponse(json=[{"id": "ws-1"}]),
                ScriptedResponse(
                    json={
                        "deletedProfilesList": [{"profileId": "p-1"}, {"profileId": "p-2"}],
                        "isMoreDeletedProfilesAvailable": True,
                    }
                ),
                ScriptedResponse(
                    json={"deletedProfilesList": [{"profileId": "p-3"}], "isMoreDeletedProfilesAvailable": False}
                ),
            ],
        )

        assert result.raised is None
        assert [row["profileId"] for row in result.rows] == ["p-1", "p-2", "p-3"]
        assert {row["workspace_id"] for row in result.rows} == {"ws-1"}
        assert [request.query for request in result.requests[1:]] == [
            {"currentWorkspace": ("ws-1",), "offset": ("0",)},
            {"currentWorkspace": ("ws-1",), "offset": ("2",)},
        ]

    @time_machine.travel("2026-10-21T12:00:00Z", tick=False)
    @pytest.mark.parametrize(
        "incremental,last_value,expected_days",
        [
            (False, "2026-10-18", "30"),
            (True, None, "30"),
            (True, "2026-10-18", "4"),
            (True, "2026-10-21", "1"),
            (True, "2026-01-01", "30"),
        ],
    )
    def test_cloud_usage_window_starts_at_the_watermark_day(
        self, incremental: bool, last_value: str | None, expected_days: str
    ) -> None:
        result = self._driver().run(
            "cloud_usage_daily",
            [ScriptedResponse(json=[{"id": "ws-1"}]), ScriptedResponse(json={"days": []})],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.requests[1].query["days"] == (expected_days,)

    def test_pipeline_refuses_redirect(self) -> None:
        result = self._driver().run(
            "profiles",
            [ScriptedResponse(status=302, headers={"Location": "https://example.com/browser/v2"})],
        )

        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/browser/v2"]

    @pytest.mark.parametrize("status", [404])
    def test_validation_uses_one_request(self, status: int) -> None:
        with scripted_network(
            [ScriptedResponse(status=status, json={"id": "user-1"} if status == 200 else {"statusCode": status})]
        ) as network:
            if status == 404:
                with pytest.raises(HTTPError):
                    validate_credentials("test-token")
            else:
                valid, error = validate_credentials("test-token")
                assert valid is (status == 200)
                assert (error is None) is (status == 200)
                if error is not None:
                    assert "API key" in error

        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.method == "GET"
        assert request.url == "https://api.gologin.com/user"
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.read_timeout == REQUEST_TIMEOUT[1]

    def test_validation_refuses_redirect(self) -> None:
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://example.com/user"})]
        ) as network:
            with pytest.raises(ValueError):
                validate_credentials("test-token")

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/user"
