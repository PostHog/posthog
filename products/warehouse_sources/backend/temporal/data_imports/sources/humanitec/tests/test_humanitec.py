from http import HTTPStatus
from typing import cast

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.humanitec import (
    HumanitecSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitec.humanitec import validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitec.source import HumanitecSource

BASE = "https://api.humanitec.io/orgs/example-org"
CONFIG = HumanitecSourceConfig(api_token="test-token", organization_id="example-org")


@pytest.mark.parametrize(
    "endpoint,suffix,key", [("deployments", "deploys", "id"), ("active_resources", "resources", "gu_res_id")]
)
def test_environment_children_keep_parent_keys(endpoint: str, suffix: str, key: str) -> None:
    result = SourceDriver(HumanitecSource(), CONFIG).run(
        endpoint,
        [
            ScriptedResponse(
                json=[
                    {"id": "app-a", "envs": [{"id": "staging"}, {"id": "production"}]},
                    {"id": "empty-app", "envs": []},
                    {"id": "app-b", "envs": [{"id": "staging"}]},
                ]
            ),
            ScriptedResponse(json=[{key: "same-id", "env_id": "staging"}]),
            ScriptedResponse(json=[]),
            ScriptedResponse(json=[{key: "same-id", "env_id": "staging"}]),
        ],
    )

    assert result.raised is None
    assert result.rows == [
        {key: "same-id", "app_id": "app-a", "env_id": "staging"},
        {key: "same-id", "app_id": "app-b", "env_id": "staging"},
    ]
    assert result.response is not None
    assert len({tuple(row[field] for field in result.response.primary_keys or []) for row in result.rows}) == 2
    assert result.urls == [
        f"{BASE}/apps",
        f"{BASE}/apps/app-a/envs/staging/{suffix}",
        f"{BASE}/apps/app-a/envs/production/{suffix}",
        f"{BASE}/apps/app-b/envs/staging/{suffix}",
    ]


def test_deployment_deltas_keep_application_key() -> None:
    result = SourceDriver(HumanitecSource(), CONFIG).run(
        "deployment_deltas",
        [
            ScriptedResponse(json=[{"id": "app-a", "envs": []}, {"id": "app-b", "envs": []}]),
            ScriptedResponse(json=[{"id": "same-delta"}]),
            ScriptedResponse(json=[{"id": "same-delta"}]),
        ],
    )

    assert result.raised is None
    assert result.rows == [{"id": "same-delta", "app_id": "app-a"}, {"id": "same-delta", "app_id": "app-b"}]
    assert result.urls == [f"{BASE}/apps", f"{BASE}/apps/app-a/deltas", f"{BASE}/apps/app-b/deltas"]


def test_pipeline_runs_follow_link_pages() -> None:
    run = {"app_id": "app-a", "pipeline_id": "deploy"}
    result = SourceDriver(HumanitecSource(), CONFIG).run(
        "pipeline_runs",
        [
            ScriptedResponse(
                json=[{**run, "id": "run-2"}],
                headers={"Link": f'<{BASE}/pipeline-runs?per_page=100&page=next-token>; rel="next"'},
            ),
            ScriptedResponse(json=[{**run, "id": "run-1"}]),
        ],
    )

    assert result.raised is None
    assert [row["id"] for row in result.rows] == ["run-2", "run-1"]
    assert result.urls == [
        f"{BASE}/pipeline-runs?per_page=100",
        f"{BASE}/pipeline-runs?per_page=100&page=next-token",
    ]


@pytest.mark.parametrize("status,expected", [(404, "could not find")])
def test_credential_probe(status: int, expected: str | None) -> None:
    body = {"id": "example-org"} if status == 200 else {"error": f"HTTP-{status}", "message": HTTPStatus(status).phrase}
    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        valid, error = validate_credentials(CONFIG)

    assert valid is (status == 200)
    assert (error is None) if expected is None else expected in cast(str, error)
    assert len(network.requests_log) == 1
    assert network.requests_log[0].url == BASE
    assert network.requests_log[0].headers["authorization"] == "Bearer test-token"


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_errors_are_terminal(status: int) -> None:
    result = SourceDriver(HumanitecSource(), CONFIG).run(
        "applications",
        [ScriptedResponse(status=status, json={"error": f"HTTP-{status}", "message": HTTPStatus(status).phrase})],
    )

    assert isinstance(result.raised, HTTPError)
    assert any(pattern in str(result.raised) for pattern in HumanitecSource().get_non_retryable_errors())
    assert len(result.requests) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_probe_errors_propagate(status: int) -> None:
    with scripted_network([ScriptedResponse(status=status, json={"error": f"HTTP-{status}"})] * 5) as network:
        with pytest.raises(RESTClientRetryableError):
            validate_credentials(CONFIG)

    assert len(network.requests_log) == 5
    assert all(request.url == BASE for request in network.requests_log)


@pytest.mark.parametrize(
    "organization",
    ["", "../users", "example/org", "https://example.com", "UPPERCASE", "bad--id", "a" * 49 + "!", "a" * 51],
)
def test_invalid_organization_never_sends_token(organization: str) -> None:
    config = HumanitecSourceConfig(api_token="test-token", organization_id=organization)
    with scripted_network([]) as network:
        valid, error = validate_credentials(config)

    result = SourceDriver(HumanitecSource(), config).run("applications", [])

    assert not valid
    assert error and "organization ID" in error
    assert isinstance(result.raised, ValueError)
    assert "organization ID" in str(result.raised)
    assert network.requests_log == []
    assert result.requests == []


@pytest.mark.parametrize(
    "next_url", ["https://example.com/steal", "http://api.humanitec.io/orgs/example-org/apps/app-a/pipelines"]
)
def test_pipeline_links_cannot_retarget_credentials(next_url: str) -> None:
    result = SourceDriver(HumanitecSource(), CONFIG).run(
        "pipelines",
        [
            ScriptedResponse(json=[{"id": "app-a"}]),
            ScriptedResponse(json=[{"id": "first"}], headers={"Link": f'<{next_url}>; rel="next"'}),
        ],
    )

    assert isinstance(result.raised, ValueError)
    assert "Refusing to send" in str(result.raised)
    assert len(result.requests) == 2


def test_unexpected_probe_error_is_not_reported_as_invalid_credentials() -> None:
    with scripted_network([ScriptedResponse(status=400, json={"error": "HTTP-400"})]) as network:
        with pytest.raises(HTTPError):
            validate_credentials(CONFIG)

    assert len(network.requests_log) == 1
