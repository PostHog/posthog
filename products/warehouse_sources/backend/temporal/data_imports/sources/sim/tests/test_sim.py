from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

from requests.exceptions import HTTPError
from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sim import SimSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sim.sim import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    WORKSPACE_ERROR,
    SimResumeConfig,
    sim_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sim.source import SimSource


@pytest.mark.parametrize("table,key", [("logs", "runId"), ("workflows", "id")])
def test_resume_preserves_workspace_and_sort(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    redis_client: MagicMock,
    http: Mocker,
    table: str,
    key: str,
) -> None:
    inputs.schema_name = table
    redis_client.exists.return_value = 1
    redis_client.get.return_value = b'{"cursor":"saved-cursor"}'
    http.get(f"https://www.sim.ai/api/v2/{table}", json={"data": [{key: "remaining-row"}], "nextCursor": None})
    response = sim_source(config, inputs, manager, "v2")
    assert list(cast(Iterable[Any], response.items())) == [[{key: "remaining-row"}]]
    assert http.last_request is not None
    assert http.last_request.qs["cursor"] == ["saved-cursor"]
    assert http.last_request.qs["workspaceid"] == ["workspace-example"]
    assert http.last_request.qs["sortorder"] == ["asc"]


def test_empty_page_keeps_following_cursor(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    http: Mocker,
) -> None:
    http.get(
        "https://www.sim.ai/api/v2/logs",
        [
            {"json": {"data": [], "nextCursor": "next-page"}},
            {"json": {"data": [{"runId": "after-empty-page"}], "nextCursor": None}},
        ],
    )
    assert list(cast(Iterable[Any], sim_source(config, inputs, manager, "v2").items())) == [
        [{"runId": "after-empty-page"}]
    ]


def test_missing_data_fails_instead_of_replacing_table_with_empty_rows(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    http: Mocker,
) -> None:
    http.get("https://www.sim.ai/api/v2/logs", json={"error": {"code": "UNEXPECTED_RESPONSE"}})
    with pytest.raises(ValueError, match="Required data_selector"):
        list(cast(Iterable[Any], sim_source(config, inputs, manager, "v2").items()))


@pytest.mark.parametrize("status,message", [(401, AUTH_ERROR), (403, PERMISSION_ERROR), (404, WORKSPACE_ERROR)])
def test_auth_failures_are_terminal(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    http: Mocker,
    status: int,
    message: str,
) -> None:
    http.get(
        "https://www.sim.ai/api/v2/logs",
        status_code=status,
        json={"error": {"code": "UNAUTHORIZED", "message": "Authentication required"}},
    )
    with pytest.raises(HTTPError) as error:
        list(cast(Iterable[Any], sim_source(config, inputs, manager, "v2").items()))
    assert http.call_count == 1
    messages = SimSource().get_non_retryable_errors()
    assert error_message_matches(str(error.value), messages)
    assert next(value for pattern, value in messages.items() if pattern in str(error.value)) == message


@pytest.mark.parametrize(
    "status,schema,expected",
    [
        (200, None, (True, None)),
        (200, "logs", (True, None)),
        (401, None, (False, AUTH_ERROR)),
        (403, None, (True, None)),
        (403, "logs", (False, PERMISSION_ERROR)),
        (404, None, (False, WORKSPACE_ERROR)),
    ],
)
def test_credential_probe_maps_status_and_scopes(
    config: SimSourceConfig,
    http: Mocker,
    status: int,
    schema: str | None,
    expected: tuple[bool, str | None],
) -> None:
    http.get(
        f"https://www.sim.ai/api/v2/{schema or 'workflows'}", status_code=status, json={"data": [], "nextCursor": None}
    )
    assert validate_credentials(config, "v2", schema) == expected
    assert http.call_count == 1
    assert http.last_request is not None
    assert http.last_request.qs["limit"] == ["1"]
    assert http.last_request.qs["workspaceid"] == [config.workspace_id]
    assert http.last_request.headers["X-API-Key"] == config.api_key


def test_invalid_request_is_not_reported_as_invalid_credentials(config: SimSourceConfig, http: Mocker) -> None:
    http.get(
        "https://www.sim.ai/api/v2/workflows",
        status_code=400,
        json={"error": {"code": "BAD_REQUEST", "message": "Invalid request"}},
    )
    with pytest.raises(HTTPError):
        validate_credentials(config, "v2")
