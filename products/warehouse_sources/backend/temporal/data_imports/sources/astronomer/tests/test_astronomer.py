import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.astronomer.astronomer import (
    AstronomerResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.astronomer.source import AstronomerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.astronomer import (
    AstronomerSourceConfig,
)

BASE = "https://api.astronomer.io/v1/organizations/example-org"
CONFIG = AstronomerSourceConfig(api_token="test-token", organization_id="example-org")


def driver(config: AstronomerSourceConfig = CONFIG) -> SourceDriver:
    return SourceDriver(AstronomerSource(), config)


@pytest.mark.parametrize("table", ["deployments", "workspaces", "clusters"])
@pytest.mark.parametrize("last_page_size", [0, 1, 100])
def test_list_pagination_auth_and_terminal_page(table: str, last_page_size: int) -> None:
    rows = [{"id": f"row-{index}"} for index in range(100 + last_page_size)]
    result = driver().run(
        table,
        [
            ScriptedResponse(json={table: rows[:100], "totalCount": 200}),
            ScriptedResponse(json={table: rows[100:], "totalCount": len(rows)}),
        ],
    )

    assert result.raised is None
    assert result.rows == rows
    assert result.paths == [f"/v1/organizations/example-org/{table}"] * 2
    assert result.params("offset") == ["0", "100"]
    assert result.params("limit") == ["100", "100"]
    assert result.params("sorts") == ["createdAt:asc", "createdAt:asc"]
    assert result.queries == [
        {"offset": ("0",), "limit": ("100",), "sorts": ("createdAt:asc",)},
        {"offset": ("100",), "limit": ("100",), "sorts": ("createdAt:asc",)},
    ]
    assert all(request.headers["authorization"] == "Bearer test-token" for request in result.requests)
    assert result.saved_states == [AstronomerResumeConfig(paginator_state={"offset": 100})]


def test_resume_starts_at_saved_offset() -> None:
    result = driver().run(
        "workspaces",
        [ScriptedResponse(json={"workspaces": [{"id": "last"}], "totalCount": 201})],
        resume_state=AstronomerResumeConfig(paginator_state={"offset": 200}),
    )

    assert result.raised is None
    assert result.rows == [{"id": "last"}]
    assert result.params("offset") == ["200"]


def test_deploy_history_paginates_each_parent_and_preserves_unique_keys() -> None:
    first_page = [{"id": f"deploy-{index}"} for index in range(100)]
    result = driver().run(
        "deploys",
        [
            ScriptedResponse(json={"deployments": [{"id": "first"}, {"id": "second"}], "totalCount": 2}),
            ScriptedResponse(json={"deploys": first_page, "totalCount": 101}),
            ScriptedResponse(json={"deploys": [{"id": "last"}], "totalCount": 101}),
            ScriptedResponse(json={"deploys": [{"id": "last"}], "totalCount": 1}),
        ],
    )

    assert result.raised is None
    assert len(result.rows) == 102
    assert result.rows[-2:] == [{"id": "last", "deploymentId": "first"}, {"id": "last", "deploymentId": "second"}]
    assert result.response is not None
    assert len({tuple(row[key] for key in result.response.primary_keys or []) for row in result.rows}) == 102
    assert result.paths == [
        "/v1/organizations/example-org/deployments",
        "/v1/organizations/example-org/deployments/first/deploys",
        "/v1/organizations/example-org/deployments/first/deploys",
        "/v1/organizations/example-org/deployments/second/deploys",
    ]
    assert result.params("offset")[1:] == ["0", "100", "0"]
    assert result.params("limit")[1:] == ["100", "100", "100"]
    assert result.queries[1:] == [
        {"offset": ("0",), "limit": ("100",)},
        {"offset": ("100",), "limit": ("100",)},
        {"offset": ("0",), "limit": ("100",)},
    ]
    assert all(request.headers["authorization"] == "Bearer test-token" for request in result.requests[1:])
    states = [state.paginator_state for state in result.saved_states]
    assert any(state["child_state"] == {"offset": 100} for state in states)
    assert states[-1]["completed"] == [
        "organizations/example-org/deployments/first/deploys",
        "organizations/example-org/deployments/second/deploys",
    ]


def test_deploy_resume_skips_completed_parents_and_continues_child_page() -> None:
    result = driver().run(
        "deploys",
        [
            ScriptedResponse(json={"deployments": [{"id": "first"}, {"id": "second"}], "totalCount": 2}),
            ScriptedResponse(json={"deploys": [{"id": "last"}], "totalCount": 101}),
        ],
        resume_state=AstronomerResumeConfig(
            paginator_state={
                "completed": ["organizations/example-org/deployments/first/deploys"],
                "current": "organizations/example-org/deployments/second/deploys",
                "child_state": {"offset": 100},
            }
        ),
    )

    assert result.raised is None
    assert result.rows == [{"id": "last", "deploymentId": "second"}]
    assert result.paths == [
        "/v1/organizations/example-org/deployments",
        "/v1/organizations/example-org/deployments/second/deploys",
    ]
    assert result.params("offset")[1] == "100"


@pytest.mark.parametrize(
    ("status", "schema", "valid", "message"),
    [
        (403, None, True, None),
        (403, "clusters", False, "organization.clusters.get"),
        (404, None, False, "organization ID"),
    ],
)
def test_credential_probe_status_mapping(status: int, schema: str | None, valid: bool, message: str | None) -> None:
    table = schema or "deployments"
    with scripted_network([ScriptedResponse(json={table: []}, status=status)]) as network:
        actual_valid, actual_message = validate_credentials(CONFIG, schema)

    assert actual_valid is valid
    if message:
        assert actual_message and message in actual_message
    else:
        assert actual_message is None
    assert len(network.requests_log) == 1
    assert network.requests_log[0].url.startswith(f"{BASE}/{table}?")
    assert network.requests_log[0].param("limit") == "1"
    assert network.requests_log[0].query == {"limit": ("1",)}
    assert network.requests_log[0].headers["authorization"] == "Bearer test-token"


@pytest.mark.parametrize("parent_status, child_status", [(403, None), (200, 403), (200, 200), (200, None)])
def test_deploy_permission_probe(parent_status: int, child_status: int | None) -> None:
    script = [
        ScriptedResponse(json={"deployments": [] if child_status is None else [{"id": "first"}]}, status=parent_status)
    ]
    if child_status is not None:
        script.append(ScriptedResponse(json={"deploys": []}, status=child_status))
    with scripted_network(script):
        valid, message = validate_credentials(CONFIG, "deploys")

    assert valid is (parent_status == 200 and child_status != 403)
    if parent_status == 403:
        assert message and "organization.deployments.get" in message
    elif child_status == 403:
        assert message and "deployment.deploys.get" in message
    else:
        assert message is None


@pytest.mark.parametrize("organization_id", ["", "../example", "https://example.com", "a?b", "a#b", "a/b"])
def test_invalid_organization_never_sends_token(organization_id: str) -> None:
    config = AstronomerSourceConfig(api_token="test-token", organization_id=organization_id)
    with scripted_network([]) as network:
        valid, message = validate_credentials(config)
    result = driver(config).run("deployments", [])

    assert not valid
    assert message and "organization ID" in message
    assert isinstance(result.raised, ValueError)
    assert "organization ID" in str(result.raised)
    assert not network.requests_log
    assert not result.requests


@pytest.mark.parametrize("status", [401, 403, 400, 429, 500])
def test_sync_errors_and_retry_classification(status: int) -> None:
    response = ScriptedResponse(json={"error": "test_error"}, status=status)
    script = always(response) if status in (429, 500) else [response]
    result = driver().run("deployments", script)

    expected = RESTClientRetryableError if status in (429, 500) else HTTPError
    assert isinstance(result.raised, expected)
    mapped = [
        message
        for pattern, message in AstronomerSource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert bool(mapped) is (status in (401, 403))
    assert (len(result.requests) > 1) is (status in (429, 500))


def test_validation_does_not_hide_unexpected_http_errors() -> None:
    with scripted_network([ScriptedResponse(json={"error": "bad_request"}, status=400)]):
        with pytest.raises(HTTPError):
            validate_credentials(CONFIG)


@pytest.mark.parametrize("operation", ["validate", "sync"])
def test_unknown_table(operation: str) -> None:
    if operation == "validate":
        with scripted_network([]) as network:
            with pytest.raises(UnknownResourceError):
                validate_credentials(CONFIG, "unknown")
        assert not network.requests_log
    else:
        result = driver().run("unknown", [])
        assert isinstance(result.raised, UnknownResourceError)
        assert not result.requests


@pytest.mark.parametrize("table", ["deployments", "deploys"])
def test_warehouse_rows_exclude_environment_values_and_upload_urls(table: str) -> None:
    script: list[ScriptedResponse] = []
    if table == "deploys":
        script.append(ScriptedResponse(json={"deployments": [{"id": "first"}], "totalCount": 1}))
    script.append(
        ScriptedResponse(
            json={
                table: [
                    {
                        "id": "row-1",
                        "status": "DEPLOYED",
                        "environmentVariables": [{"key": "SECRET", "value": "fake-secret", "isSecret": True}],
                        "bundleUploadUrl": "https://example.com/upload?token=fake",
                        "dagsUploadUrl": "https://example.com/upload?token=fake",
                    }
                ],
                "totalCount": 1,
            }
        )
    )
    result = driver().run(table, script)

    expected = {"id": "row-1", "status": "DEPLOYED"}
    if table == "deploys":
        expected["deploymentId"] = "first"
    assert result.raised is None
    assert result.rows == [expected]


def test_missing_collection_fails_instead_of_replacing_table_with_no_rows() -> None:
    result = driver().run("deployments", [ScriptedResponse(json={"unexpected": []})])

    assert isinstance(result.raised, ValueError)
    assert "Required data_selector" in str(result.raised)
