from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.usersnap import (
    UsersnapSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.settings import (
    ENDPOINTS,
    USERSNAP_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.source import UsersnapSource
from products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap import (
    UsersnapResumeConfig,
    _format_datetime,
    validate_credentials,
)


def _run(endpoint: str, script: Script, **kwargs: Any) -> DriveResult:
    driver = SourceDriver(UsersnapSource(), UsersnapSourceConfig(jwt_secret="secret", jwt_id="jwt-id"))
    return driver.run(endpoint, script, **kwargs)


def _resp(payload: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json=payload)


def _resp_404() -> ScriptedResponse:
    return ScriptedResponse(status=404, json={"status": False})


def _projects_page(projects: list[dict[str, Any]], has_more: bool = False) -> dict[str, Any]:
    return {"status": True, "data": {"has_more": has_more, "count": len(projects), "projects": projects}}


def _feedbacks_page(
    items: list[dict[str, Any]], has_more: bool = False, next_after: str | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {"has_more": has_more, "count": len(items), "feedbacks": items}
    if next_after is not None:
        data["next"] = {"after": next_after, "limit": 100}
    return {"status": True, "data": data}


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
            (datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
            (date(2026, 1, 2), "2026-01-02T00:00:00Z"),
            ("2026-01-02T03:04:05Z", "2026-01-02T03:04:05Z"),
        ],
    )
    def test_format_datetime_values(self, value, expected):
        assert _format_datetime(value) == expected


class TestValidateCredentials:
    def test_validate_credentials_disables_http_sample_capture(self):
        with scripted_network([ScriptedResponse(json={})]) as network:
            assert validate_credentials("secret", "jwt-id") is True

        assert network.session_options[0]["capture"] is False


class TestGetRows:
    def test_projects_truncation_is_surfaced(self):
        logger = mock.MagicMock()

        _run("projects", [_resp(_projects_page([{"project_id": "p1"}], has_more=True))], logger=logger)

        logger.warning.assert_called_once()

    def test_feedbacks_falls_back_to_last_item_cursor_when_next_missing(self):
        result = _run(
            "feedbacks",
            [
                _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}])),
                _resp(_feedbacks_page([{"feedback_id": "f1"}], has_more=True)),
                _resp(_feedbacks_page([{"feedback_id": "f2"}], has_more=False)),
            ],
        )

        assert [item["feedback_id"] for item in result.rows] == ["f1", "f2"]
        assert result.requests[2].param("after") == "f1"

    def test_a_run_with_no_saved_state_starts_from_the_first_project_and_page(self):
        result = _run(
            "feedbacks",
            [
                _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}, {"project_id": "p2", "api_key": "k2"}])),
                _resp(_feedbacks_page([], has_more=False)),
                _resp(_feedbacks_page([], has_more=False)),
            ],
        )

        assert result.paths[1:] == ["/v0.1/projects/p1/feedbacks/filter", "/v0.1/projects/p2/feedbacks/filter"]
        assert result.params("after") == [None, None, None]

    @pytest.mark.parametrize(
        "incremental_inputs, expected_query",
        [
            (
                {
                    "incremental_field": "created_at",
                    "db_incremental_field_last_value": datetime(2026, 1, 1, tzinfo=UTC),
                },
                [{"filter_type": "created_at", "operator": "gte", "value": "2026-01-01T00:00:00Z"}],
            ),
            ({}, None),
            ({"incremental_field": "created_at"}, None),
        ],
    )
    def test_feedbacks_filter_body(self, incremental_inputs, expected_query):
        result = _run(
            "feedbacks",
            [
                _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}])),
                _resp(_feedbacks_page([{"feedback_id": "f1"}], has_more=False)),
            ],
            **incremental_inputs,
        )

        body = result.requests[1].json()
        assert body["order_by"] == {"direction": "asc", "order_by_type": "created_at"}
        assert body.get("query") == expected_query

    def test_feedbacks_resumes_from_bookmarked_project_and_cursor(self):
        result = _run(
            "feedbacks",
            [
                _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}, {"project_id": "p2", "api_key": "k2"}])),
                _resp(_feedbacks_page([{"feedback_id": "f9"}], has_more=False)),
            ],
            resume_state=UsersnapResumeConfig(project_id="p2", after="f8"),
        )

        assert [item["feedback_id"] for item in result.rows] == ["f9"]
        assert result.requests[1].path == "/v0.1/projects/p2/feedbacks/filter"
        assert result.requests[1].param("after") == "f8"

    def test_feedbacks_skips_project_deleted_mid_sync(self):
        result = _run(
            "feedbacks",
            [
                _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}, {"project_id": "p2", "api_key": "k2"}])),
                _resp_404(),
                _resp(_feedbacks_page([{"feedback_id": "f2"}], has_more=False)),
            ],
        )

        assert result.raised is None
        assert [item["feedback_id"] for item in result.rows] == ["f2"]

    def test_assignees_fan_out_rows_carry_project_id(self):
        result = _run(
            "project_assignees",
            [
                _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}, {"project_id": "p2", "api_key": "k2"}])),
                _resp({"status": True, "data": {"users": [{"user_id": "u1"}]}}),
                _resp({"status": True, "data": {"users": [{"user_id": "u1"}, {"user_id": "u2"}]}}),
            ],
        )

        assert [(row["project_id"], row["user_id"]) for row in result.rows] == [
            ("p1", "u1"),
            ("p2", "u1"),
            ("p2", "u2"),
        ]
        # The assignees endpoint is keyed on the project's api_key, not its project_id.
        assert result.paths[1:] == ["/v0.1/projects/k1/assignees", "/v0.1/projects/k2/assignees"]


class TestUsersnapSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = USERSNAP_ENDPOINTS[endpoint]
        response = _run(endpoint, [_resp(_projects_page([]))]).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # The feedbacks fan-out concatenates per-project streams, so it must not checkpoint
        # the incremental watermark per batch.
        assert response.sort_mode == ("desc" if endpoint == "feedbacks" else "asc")
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
