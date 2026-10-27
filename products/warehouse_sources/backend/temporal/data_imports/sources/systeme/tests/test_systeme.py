from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.systeme import (
    SystemeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.systeme.source import SystemeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.systeme.systeme import (
    SystemeResumeConfig,
    validate_credentials,
)


def driver() -> SourceDriver:
    return SourceDriver(SystemeSource(), SystemeSourceConfig(api_key="key"))


@pytest.mark.parametrize(
    "endpoint,incremental,watermark,expected",
    [
        ("contacts", True, datetime(2026, 1, 2, tzinfo=UTC), "2026-01-02T00:00:00+00:00"),
        ("contacts", True, "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z"),
        ("contacts", True, None, None),
        ("contacts", False, "2026-01-02T00:00:00Z", None),
        ("tags", True, "2026-01-02T00:00:00Z", None),
    ],
)
def test_incremental_filter_and_full_refresh(
    endpoint: str, incremental: bool, watermark: datetime | str | None, expected: str | None
) -> None:
    result = driver().run(
        endpoint,
        [
            ScriptedResponse(json={"items": [{"id": 20}], "hasMore": True}),
            ScriptedResponse(json={"items": [{"id": 10}], "hasMore": False}),
        ],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )
    assert result.rows == [{"id": 20}, {"id": 10}]
    assert result.response is not None
    assert result.response.sort_mode == "desc"
    assert result.params("registeredAfter") == [expected, expected]


@pytest.mark.parametrize(
    "body,message",
    [
        ({"items": [], "hasMore": True}, "invalid pagination data"),
        ({"items": [{"id": 20}]}, "invalid pagination data"),
        ({"items": [{"id": 0}], "hasMore": True}, "invalid record ID"),
        ({"items": [{"id": "20"}], "hasMore": True}, "invalid record ID"),
        ({"items": [{"id": True}], "hasMore": True}, "invalid record ID"),
        ({"items": [{"id": 20}], "hasMore": True}, "repeated cursor"),
    ],
)
def test_invalid_or_repeated_cursor_fails(body: dict[str, Any], message: str) -> None:
    result = driver().run("contacts", always(ScriptedResponse(json=body)), resume_state=SystemeResumeConfig(cursor=20))
    assert isinstance(result.raised, ValueError)
    assert message in str(result.raised)
    assert len(result.requests) == 1
    assert result.saved_states == []


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, None),
    ],
)
@pytest.mark.parametrize(
    "schema,path",
    [
        (None, "contacts"),
        ("newsletters", "mailing/newsletters"),
        ("digital_products", "payment/digital-products"),
        ("physical_products", "payment/physical-products"),
    ],
)
def test_validate_credentials_status_and_probe(
    status: int, expected: str | None, schema: str | None, path: str
) -> None:
    response = ScriptedResponse(
        status=status,
        json={"items": [{"id": 10}], "hasMore": True}
        if status == 200
        else {"detail": "Full authentication is required to access this resource."},
    )
    with scripted_network([response]) as network:
        valid, message = validate_credentials("test-key", schema)
    assert valid is (status == 200)
    if expected:
        assert expected in (message or "")
    else:
        assert message is None
    assert len(network.requests_log) == 1
    last_request = network.requests_log[-1]
    assert last_request.path == f"/api/{path}"
    assert dict(last_request.query) == {"limit": ("10",)}
    assert last_request.headers["x-api-key"] == "test-key"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_sync_error_classification(status: int) -> None:
    result = driver().run("contacts", always(ScriptedResponse(status=status, json={"detail": "Request failed"})))
    error_type = RESTClientRetryableError if status >= 500 or status == 429 else requests.HTTPError
    assert isinstance(result.raised, error_type)
    matched = [
        message
        for pattern, message in SystemeSource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert bool(matched) is (status in (401, 403))
    assert "test-key" not in str(result.raised)
    assert len(result.requests) == (5 if status in (429, 500) else 1)


@pytest.mark.parametrize("status", [404, 429, 500])
def test_probe_does_not_report_transient_or_other_errors_as_invalid_key(status: int) -> None:
    error_type = RESTClientRetryableError if status in (429, 500) else requests.HTTPError
    with scripted_network(always(ScriptedResponse(status=status, json={"detail": "Request failed"}))):
        with pytest.raises(error_type):
            validate_credentials("key")


def test_source_adapter_forwards_pipeline_inputs() -> None:
    source = SystemeSource()
    config = SystemeSourceConfig(api_key="key")
    inputs = MagicMock(spec=SourceInputs)
    inputs.schema_name = "contacts"
    inputs.team_id = 1
    inputs.job_id = "job"
    inputs.should_use_incremental_field = True
    inputs.db_incremental_field_last_value = "2026-01-02T00:00:00Z"

    resumable_manager = MagicMock(spec=ResumableSourceManager)
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.systeme.source.validate_systeme_credentials",
            return_value=(True, None),
        ) as mock_validate,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.systeme.source.ResumableSourceManager",
            return_value=resumable_manager,
        ) as mock_manager_class,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.systeme.source.systeme_source",
            return_value=MagicMock(spec=SourceResponse),
        ) as mock_source,
    ):
        assert source.validate_credentials(config, inputs.team_id, inputs.schema_name) == (True, None)
        mock_validate.assert_called_once_with("key", "contacts")

        assert source.get_resumable_source_manager(inputs) is resumable_manager
        mock_manager_class.assert_called_once_with(inputs, SystemeResumeConfig)
        source.source_for_pipeline(config, resumable_manager, inputs)
        mock_source.assert_called_once_with(
            api_key="key",
            endpoint="contacts",
            team_id=1,
            job_id="job",
            resumable_source_manager=resumable_manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-02T00:00:00Z",
        )


def test_unknown_endpoint_does_not_fetch() -> None:
    result = driver().run("unknown", [])
    assert isinstance(result.raised, UnknownResourceError)
    with scripted_network([]) as network:
        with pytest.raises(UnknownResourceError):
            validate_credentials("key", "unknown")
    assert result.requests == []
    assert network.requests_log == []
