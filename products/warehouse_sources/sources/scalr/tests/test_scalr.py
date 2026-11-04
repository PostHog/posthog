from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests.exceptions import HTTPError

from products.warehouse_sources.sources.scalr._config import ScalrSourceConfig
from products.warehouse_sources.sources.scalr.scalr import ScalrResumeConfig
from products.warehouse_sources.sources.scalr.source import ScalrSource
from products.warehouse_sources.sources.sdk import ResumableSourceManager, SourceInputs
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)

MIXINS = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins"


@pytest.fixture
def config() -> ScalrSourceConfig:
    return ScalrSourceConfig(host="scalr.example.com", account_id="acc-example", api_token="fake-token")


@pytest.fixture
def send() -> Iterator[MagicMock]:
    with (
        patch("requests.sessions.Session.send") as mock_send,
        patch(f"{MIXINS}.is_cloud", return_value=True),
        patch(f"{MIXINS}.get_instance_region", return_value="US"),
        patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]),
    ):
        yield mock_send


def response(body: dict[str, Any], status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def page(endpoint: str, identifier: str | None, next_page: int | None) -> ScriptedResponse:
    return response(
        {
            "data": [
                {
                    "id": identifier,
                    "type": endpoint,
                    "attributes": {
                        "created-at": "2025-01-01T00:00:00Z",
                        "updated-at": "2025-01-02T00:00:00Z",
                        "name": "Example",
                    },
                    "relationships": {"account": {"data": {"id": "acc-example", "type": "accounts"}}},
                }
            ]
            if identifier
            else [],
            "meta": {"pagination": {"next-page": next_page}},
        }
    )


def inputs(endpoint: str, incremental: bool = False, watermark: datetime | str | None = None) -> SourceInputs:
    return SourceInputs(
        schema_name=endpoint,
        schema_id="schema-example",
        source_id="source-example",
        team_id=123,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
        db_incremental_field_earliest_value=None,
        incremental_field="updated_at" if incremental else None,
        incremental_field_type=None,
        job_id="job-example",
        logger=MagicMock(),
        reset_pipeline=False,
    )


def manager(next_page: str | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = next_page is not None
    result.load_state.return_value = ScalrResumeConfig(next_page=next_page) if next_page else None
    return result


@pytest.mark.parametrize(
    ("incremental", "watermark", "expected"),
    [
        (False, "2025-01-01T00:00:00Z", None),
        (True, None, None),
        (True, "2025-01-01T00:00:00Z", "gte:2025-01-01T00:00:00Z"),
        (True, datetime(2025, 1, 1, tzinfo=UTC), "gte:2025-01-01T00:00:00+00:00"),
    ],
)
def test_workspace_filter_on_every_page(
    config: ScalrSourceConfig,
    incremental: bool,
    watermark: datetime | str | None,
    expected: str | None,
) -> None:
    run_inputs: dict[str, Any] = {"db_incremental_field_last_value": watermark}
    if incremental:
        run_inputs["incremental_field"] = "updated_at"

    result = SourceDriver(ScalrSource(), config).run(
        "workspaces", [page("workspaces", "ws-1", 2), page("workspaces", None, None)], **run_inputs
    )

    assert result.raised is None
    assert result.response is not None
    assert result.response.sort_mode == "asc"
    for request in result.requests:
        assert request.query["sort"] == ("updated-at",)
        assert request.query.get("filter[updated-at]") == ((expected,) if expected else None)
    assert len(result.requests) == 2


@pytest.mark.parametrize("status", [404])
def test_auth_errors_are_non_retryable(config: ScalrSourceConfig, status: int) -> None:
    script = always(response({"errors": [{"status": str(status)}]}, status))
    source = ScalrSource()
    with scripted_network(script) as network:
        valid, error = source.validate_credentials(config, team_id=123)
    assert not valid
    assert error == source.get_non_retryable_errors()[f"{status} Client Error"]
    assert len(network.requests_log) == 1

    result = SourceDriver(source, config).run("environments", script)

    assert isinstance(result.raised, HTTPError)
    assert f"{status} Client Error" in str(result.raised)
    assert len(result.requests) == 1


def test_validation_uses_one_small_page(config: ScalrSourceConfig) -> None:
    with scripted_network([page("environments", "env-1", 2)]) as network:
        assert ScalrSource().validate_credentials(config, team_id=123) == (True, None)
    assert len(network.requests_log) == 1
    assert dict(network.requests_log[0].query) == {"filter[account]": ("acc-example",), "page[size]": ("1",)}


@pytest.mark.parametrize("endpoint", ["runs", "plans"])
@pytest.mark.parametrize("body", [{"errors": [{"title": "Unexpected result"}]}, {"data": {"id": "wrong-shape"}}])
def test_malformed_response_fails(config: ScalrSourceConfig, endpoint: str, body: dict[str, Any]) -> None:
    result = SourceDriver(ScalrSource(), config).run(endpoint, [response(body)])

    assert isinstance(result.raised, ValueError)
    assert len(result.requests) == 1


@pytest.mark.parametrize(
    "host",
    [
        "http://scalr.example.com",
        "scalr.example.com/path",
        "user@scalr.example.com",
        "scalr.example.com:443",
        "localhost",
        "127.0.0.1",
        "169.254.169.254",
    ],
)
def test_invalid_host_sends_no_token(config: ScalrSourceConfig, send: MagicMock, host: str) -> None:
    config.host = host
    valid, error = ScalrSource().validate_credentials(config, team_id=123)
    assert not valid
    assert error
    with pytest.raises(ValueError):
        ScalrSource().source_for_pipeline(config, manager(), inputs("runs"))
    send.assert_not_called()


def test_private_dns_sends_no_token(config: ScalrSourceConfig, send: MagicMock) -> None:
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 443))]):
        valid, error = ScalrSource().validate_credentials(config, team_id=123)
    assert not valid
    assert error
    send.assert_not_called()


def test_redirect_is_rejected(config: ScalrSourceConfig) -> None:
    redirect = ScriptedResponse(status=302, json={}, headers={"Location": "http://internal.example.com"})
    with scripted_network([redirect]) as network:
        valid, error = ScalrSource().validate_credentials(config, team_id=123)
    assert not valid
    assert error and "refusing to follow" in error
    assert len(network.requests_log) == 1


@pytest.mark.parametrize(("endpoint", "field"), [("runs", "created_at"), ("workspaces", "created_at")])
def test_unsupported_incremental_field_fails(config: ScalrSourceConfig, endpoint: str, field: str) -> None:
    result = SourceDriver(ScalrSource(), config).run(endpoint, [], incremental_field=field)

    assert isinstance(result.raised, ValueError)
    assert "only for the workspace updated_at" in str(result.raised)
    assert result.requests == []


def test_plans_come_from_included_runs_on_every_page(config: ScalrSourceConfig) -> None:
    def runs_page(run_id: str, plan_id: str, next_page: int | None) -> ScriptedResponse:
        return response(
            {
                "data": [{"id": run_id, "type": "runs", "attributes": {}}],
                "included": [
                    {"id": plan_id, "type": "plans", "attributes": {"resource-additions": 2, "status": "finished"}},
                    {"id": "ws-1", "type": "workspaces", "attributes": {}},
                ],
                "meta": {"pagination": {"next-page": next_page}},
            }
        )

    result = SourceDriver(ScalrSource(), config).run(
        "plans",
        [runs_page("run-1", "plan-1", 2), runs_page("run-2", "plan-2", 3), response({"data": [], "meta": {}})],
    )

    assert result.raised is None
    assert [(row["id"], row["resource_additions"]) for row in result.rows] == [("plan-1", 2), ("plan-2", 2)]
    assert [request.path for request in result.requests] == ["/api/iacp/v3/runs"] * 3
    assert all(request.param("include") == "plan" for request in result.requests)


def test_state_versions_fan_out_over_workspaces_without_state_secrets(config: ScalrSourceConfig) -> None:
    state_versions = {
        "ws-1": [
            response(
                {
                    "data": [
                        {
                            "id": "sv-1",
                            "type": "state-versions",
                            "attributes": {
                                "created-at": "2025-01-01T00:00:00Z",
                                "serial": 1,
                                "state": "c2VjcmV0",
                                "outputs": [
                                    {"name": "password", "sensitive": True, "value": "secret"},
                                    {"name": "url", "sensitive": False, "value": "https://example.com"},
                                ],
                            },
                        }
                    ],
                    "meta": {"pagination": {"next-page": 2}},
                }
            ),
            page("state-versions", "sv-2", None),
        ],
        "ws-2": [response({"errors": [{"status": "404"}]}, 404)],
    }

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/workspaces"):
            return response(
                {
                    "data": [{"id": ws, "type": "workspaces", "attributes": {}} for ws in state_versions],
                    "meta": {"pagination": {"next-page": None}},
                }
            )
        workspace = request.param("filter[workspace]")
        assert workspace is not None
        return state_versions[workspace].pop(0)

    result = SourceDriver(ScalrSource(), config).run("state_versions", respond)

    assert result.raised is None
    assert [row["id"] for row in result.rows] == ["sv-1", "sv-2"]
    assert "state" not in result.rows[0]
    assert result.rows[0]["outputs"] == [
        {"name": "password", "sensitive": True, "value": None},
        {"name": "url", "sensitive": False, "value": "https://example.com"},
    ]
    assert [(request.path, request.param("filter[workspace]")) for request in result.requests] == [
        ("/api/iacp/v3/workspaces", None),
        ("/api/iacp/v3/state-versions", "ws-1"),
        ("/api/iacp/v3/state-versions", "ws-1"),
        ("/api/iacp/v3/state-versions", "ws-2"),
    ]
    assert result.requests[2].param("page[number]") == "2"
