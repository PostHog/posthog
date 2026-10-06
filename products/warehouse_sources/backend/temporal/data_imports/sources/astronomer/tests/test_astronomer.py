from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import responses
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.astronomer.astronomer import (
    AstronomerResumeConfig,
    astronomer_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.astronomer.source import AstronomerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.astronomer import (
    AstronomerSourceConfig,
)

BASE = "https://api.astronomer.io/v1/organizations/example-org"
CONFIG = AstronomerSourceConfig(api_token="test-token", organization_id="example-org")


def manager(state: dict[str, Any] | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = state is not None
    result.load_state.return_value = AstronomerResumeConfig(paginator_state=state) if state is not None else None
    return result


def items(response: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], response.items())


@pytest.mark.parametrize("table", ["deployments", "workspaces", "clusters"])
@pytest.mark.parametrize("last_page_size", [0, 1, 100])
@responses.activate
def test_list_pagination_auth_and_terminal_page(table: str, last_page_size: int) -> None:
    rows = [{"id": f"row-{index}"} for index in range(100 + last_page_size)]
    responses.get(f"{BASE}/{table}", json={table: rows[:100], "totalCount": 200})
    responses.get(f"{BASE}/{table}", json={table: rows[100:], "totalCount": len(rows)})
    checkpoint = manager()
    result = astronomer_source(CONFIG, table, 1, "test-job", checkpoint)

    assert [row for page in items(result) for row in page] == rows
    assert len(responses.calls) == 2
    for offset, call in zip([0, 100], responses.calls):
        assert call.request.headers["Authorization"] == "Bearer test-token"
        assert parse_qs(urlparse(call.request.url).query) == {
            "offset": [str(offset)],
            "limit": ["100"],
            "sorts": ["createdAt:asc"],
        }
    checkpoint.save_state.assert_called_once_with(AstronomerResumeConfig(paginator_state={"offset": 100}))


@responses.activate
def test_resume_starts_at_saved_offset() -> None:
    responses.get(f"{BASE}/workspaces", json={"workspaces": [{"id": "last"}], "totalCount": 201})
    result = astronomer_source(CONFIG, "workspaces", 1, "test-job", manager({"offset": 200}))
    assert [row for page in items(result) for row in page] == [{"id": "last"}]
    assert parse_qs(urlparse(responses.calls[0].request.url).query)["offset"] == ["200"]


@responses.activate
def test_deploy_history_paginates_each_parent_and_preserves_unique_keys() -> None:
    responses.get(f"{BASE}/deployments", json={"deployments": [{"id": "first"}, {"id": "second"}], "totalCount": 2})
    first_page = [{"id": f"deploy-{index}"} for index in range(100)]
    responses.get(f"{BASE}/deployments/first/deploys", json={"deploys": first_page, "totalCount": 101})
    responses.get(f"{BASE}/deployments/first/deploys", json={"deploys": [{"id": "last"}], "totalCount": 101})
    responses.get(f"{BASE}/deployments/second/deploys", json={"deploys": [{"id": "last"}], "totalCount": 1})
    checkpoint = manager()
    result = astronomer_source(CONFIG, "deploys", 1, "test-job", checkpoint)
    rows = [row for page in items(result) for row in page]

    assert len(rows) == 102
    assert rows[-2:] == [{"id": "last", "deploymentId": "first"}, {"id": "last", "deploymentId": "second"}]
    assert len({tuple(row[key] for key in result.primary_keys or []) for row in rows}) == 102
    for offset, call in zip([0, 100, 0], responses.calls[1:]):
        assert parse_qs(urlparse(call.request.url).query) == {"offset": [str(offset)], "limit": ["100"]}
        assert call.request.headers["Authorization"] == "Bearer test-token"
    states = [call.args[0].paginator_state for call in checkpoint.save_state.call_args_list]
    assert any(state["child_state"] == {"offset": 100} for state in states)
    assert states[-1]["completed"] == [
        "organizations/example-org/deployments/first/deploys",
        "organizations/example-org/deployments/second/deploys",
    ]


@responses.activate
def test_deploy_resume_skips_completed_parents_and_continues_child_page() -> None:
    responses.get(f"{BASE}/deployments", json={"deployments": [{"id": "first"}, {"id": "second"}], "totalCount": 2})
    responses.get(f"{BASE}/deployments/second/deploys", json={"deploys": [{"id": "last"}], "totalCount": 101})
    checkpoint = manager(
        {
            "completed": ["organizations/example-org/deployments/first/deploys"],
            "current": "organizations/example-org/deployments/second/deploys",
            "child_state": {"offset": 100},
        }
    )
    result = astronomer_source(CONFIG, "deploys", 1, "test-job", checkpoint)
    assert [row for page in items(result) for row in page] == [{"id": "last", "deploymentId": "second"}]
    assert len(responses.calls) == 2
    assert parse_qs(urlparse(responses.calls[1].request.url).query)["offset"] == ["100"]


@pytest.mark.parametrize("empty_parent", [True, False])
@responses.activate
def test_deploys_with_no_rows(empty_parent: bool) -> None:
    responses.get(
        f"{BASE}/deployments", json={"deployments": [] if empty_parent else [{"id": "first"}], "totalCount": 1}
    )
    if not empty_parent:
        responses.get(f"{BASE}/deployments/first/deploys", json={"deploys": [], "totalCount": 0})
    result = astronomer_source(CONFIG, "deploys", 1, "test-job", manager())
    assert [row for page in items(result) for row in page] == []
    assert len(responses.calls) == (1 if empty_parent else 2)


@pytest.mark.parametrize(
    ("status", "schema", "valid", "message"),
    [
        (200, None, True, None),
        (401, None, False, "API token"),
        (403, None, True, None),
        (403, "clusters", False, "organization.clusters.get"),
        (404, None, False, "organization ID"),
    ],
)
@responses.activate
def test_credential_probe_status_mapping(status: int, schema: str | None, valid: bool, message: str | None) -> None:
    table = schema or "deployments"
    responses.get(f"{BASE}/{table}", json={table: []}, status=status)
    actual_valid, actual_message = validate_credentials(CONFIG, schema)
    assert actual_valid is valid
    if message:
        assert actual_message and message in actual_message
    else:
        assert actual_message is None
    assert len(responses.calls) == 1
    assert parse_qs(urlparse(responses.calls[0].request.url).query) == {"limit": ["1"]}
    assert responses.calls[0].request.headers["Authorization"] == "Bearer test-token"


@pytest.mark.parametrize("parent_status, child_status", [(403, None), (200, 403), (200, 200), (200, None)])
@responses.activate
def test_deploy_permission_probe(parent_status: int, child_status: int | None) -> None:
    responses.get(
        f"{BASE}/deployments",
        json={"deployments": [] if child_status is None else [{"id": "first"}]},
        status=parent_status,
    )
    if child_status is not None:
        responses.get(f"{BASE}/deployments/first/deploys", json={"deploys": []}, status=child_status)
    valid, message = validate_credentials(CONFIG, "deploys")
    assert valid is (parent_status == 200 and child_status != 403)
    if parent_status == 403:
        assert message and "organization.deployments.get" in message
    elif child_status == 403:
        assert message and "deployment.deploys.get" in message
    else:
        assert message is None


@pytest.mark.parametrize("organization_id", ["", "../example", "https://example.com", "a?b", "a#b", "a/b"])
@responses.activate
def test_invalid_organization_never_sends_token(organization_id: str) -> None:
    config = AstronomerSourceConfig(api_token="test-token", organization_id=organization_id)
    valid, message = validate_credentials(config)
    assert not valid
    assert message and "organization ID" in message
    with pytest.raises(ValueError, match="organization ID"):
        astronomer_source(config, "deployments", 1, "test-job", manager())
    assert not responses.calls


@pytest.mark.parametrize("status", [401, 403, 400, 429, 500])
@responses.activate
def test_sync_errors_and_retry_classification(status: int) -> None:
    responses.get(f"{BASE}/deployments", json={"error": "test_error"}, status=status)
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.RESTClient._send_request.retry.sleep"
    ):
        result = astronomer_source(CONFIG, "deployments", 1, "test-job", manager())
        expected = RESTClientRetryableError if status in (429, 500) else HTTPError
        with pytest.raises(expected) as caught:
            list(items(result))
    mapped = [
        message
        for pattern, message in AstronomerSource().get_non_retryable_errors().items()
        if pattern in str(caught.value)
    ]
    assert bool(mapped) is (status in (401, 403))
    assert (len(responses.calls) > 1) is (status in (429, 500))


@responses.activate
def test_validation_does_not_hide_unexpected_http_errors() -> None:
    responses.get(f"{BASE}/deployments", json={"error": "bad_request"}, status=400)
    with pytest.raises(HTTPError):
        validate_credentials(CONFIG)


@pytest.mark.parametrize("operation", ["validate", "sync"])
@responses.activate
def test_unknown_table(operation: str) -> None:
    with pytest.raises(UnknownResourceError):
        if operation == "validate":
            validate_credentials(CONFIG, "unknown")
        else:
            astronomer_source(CONFIG, "unknown", 1, "test-job", manager())
    assert not responses.calls


@pytest.mark.parametrize("table", ["deployments", "deploys"])
@responses.activate
def test_warehouse_rows_exclude_environment_values_and_upload_urls(table: str) -> None:
    path = table
    if table == "deploys":
        responses.get(f"{BASE}/deployments", json={"deployments": [{"id": "first"}], "totalCount": 1})
        path = "deployments/first/deploys"
    responses.get(
        f"{BASE}/{path}",
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
        },
    )
    result = astronomer_source(CONFIG, table, 1, "test-job", manager())
    expected = {"id": "row-1", "status": "DEPLOYED"}
    if table == "deploys":
        expected["deploymentId"] = "first"
    assert [row for page in items(result) for row in page] == [expected]


@responses.activate
def test_missing_collection_fails_instead_of_replacing_table_with_no_rows() -> None:
    responses.get(f"{BASE}/deployments", json={"unexpected": []})
    result = astronomer_source(CONFIG, "deployments", 1, "test-job", manager())
    with pytest.raises(ValueError, match="Required data_selector"):
        list(items(result))
