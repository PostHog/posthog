from types import SimpleNamespace
from typing import cast

import pytest
from unittest.mock import MagicMock

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.telli import TelliSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.telli.source import TelliSource
from products.warehouse_sources.backend.temporal.data_imports.sources.telli.telli import TelliResumeConfig


@pytest.mark.parametrize(
    "schema_name,path,params",
    [
        (None, "/v1/verify-api-key", {}),
        ("calls", "/v1/list-calls", {"limit": "1"}),
        ("contacts", "/v2/contacts", {"limit": "1"}),
        ("agents", "/v2/agents", {"limit": "1"}),
        ("contact_properties", "/v2/properties/contacts", {}),
        ("phone_numbers", "/v1/phone-numbers", {}),
    ],
)
def test_validation_probes_only_requested_resource(schema_name: str | None, path: str, params: dict[str, str]) -> None:
    response = ScriptedResponse(json={"message": "API key is valid", "data": [], "calls": [], "next_cursor": "unused"})
    with scripted_network([response]) as network:
        assert TelliSource().validate_credentials(
            TelliSourceConfig(api_key="test-telli-key"), 1, schema_name=schema_name
        ) == (True, None)
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.origin + request.path == f"https://api.telli.com{path}"
    assert {name: values[0] for name, values in request.query.items()} == params
    assert request.headers["authorization"] == "Bearer test-telli-key"


@pytest.mark.parametrize(
    "status,schema_name,expected_message",
    [
        (401, None, "invalid or expired"),
        (402, None, "paid telli plan"),
        (403, None, "does not have permission"),
        (401, "contacts", "invalid or expired"),
        (402, "contacts", "paid telli plan"),
        (403, "contacts", "does not have permission"),
    ],
)
def test_auth_errors_are_actionable_and_terminal(status: int, schema_name: str | None, expected_message: str) -> None:
    source = TelliSource()
    answer = always(ScriptedResponse(status=status, json={"message": "Access denied"}))
    path = "/v2/contacts" if schema_name else "/v1/verify-api-key"
    with scripted_network(answer) as network:
        valid, message = source.validate_credentials(
            TelliSourceConfig(api_key="test-telli-key"), 1, schema_name=schema_name
        )
        assert valid is False
        assert message and expected_message in message
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == path

    result = SourceDriver(source, TelliSourceConfig(api_key="test-telli-key")).run("contacts", answer)
    assert isinstance(result.raised, HTTPError)
    assert error_message_matches(str(result.raised), source.get_non_retryable_errors())
    assert result.saved_states == []


def test_resumable_manager_uses_telli_state() -> None:
    inputs = cast(SourceInputs, SimpleNamespace(logger=MagicMock(), team_id=1, job_id="test-job"))
    manager = TelliSource().get_resumable_source_manager(inputs)

    assert isinstance(manager, ResumableSourceManager)
    assert manager._inputs is inputs
    assert manager._data_class is TelliResumeConfig


def test_unexpected_validation_error_is_not_invalid_credentials() -> None:
    with scripted_network(always(ScriptedResponse(status=400, json={"message": "Bad request"}))):
        with pytest.raises(HTTPError):
            TelliSource().validate_credentials(TelliSourceConfig(api_key="test-telli-key"), 1)


@pytest.mark.parametrize("operation", ["validate", "sync"])
def test_unknown_schema_fails_before_http(operation: str) -> None:
    source = TelliSource()
    config = TelliSourceConfig(api_key="test-telli-key")
    with scripted_network([]) as network:
        if operation == "validate":
            with pytest.raises(UnknownResourceError):
                source.validate_credentials(config, 1, schema_name="unknown")
            requests_made = network.requests_log
        else:
            result = SourceDriver(source, config).run("unknown", [])
            assert isinstance(result.raised, UnknownResourceError)
            requests_made = result.requests
    assert not requests_made
